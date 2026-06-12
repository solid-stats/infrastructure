# Production Cutover: Operator Runbook

This is the Phase 11 runbook for switching production traffic at
`stats-staging.solid-stats.ru` from the legacy upstream to the new k3s
runtime (`server-2` / `replay-parser-2`). The lever is a single nginx
upstream `server` line in
`config/nginx/sites-available/stats-staging-solid-stats.conf` (the
`# CUTOVER:` marker). Switching that one line — plus `nginx -t` and a
reload — moves all traffic to the new runtime. The mechanism is proven
reversible by the Phase 7 bootstrap-edge / teardown-edge evidence
(see `docs/edge-bootstrap.md`). The actual traffic flip is
**OPERATOR-EXECUTED** — CI never runs `scripts/cutover.sh`.

## Policy

- **The live traffic flip is OPERATOR-gated.** `scripts/cutover.sh` is
  never invoked from CI or automation; it is an operator tool only.

- **The green-diff gate is COVERAGE / INTEGRITY ONLY — NOT
  value-equality.** The new parser (`server-2` / `replay-parser-2`) is a
  deliberate rewrite; computed stat VALUES diverge from legacy BY DESIGN
  (memory: `legacy-vs-new-parser-non-identical`). The `strict_failures`
  gate checks for missing matches/players, parser errors, and aggregate
  totals outside declared tolerance. Intended value differences are
  allowlisted and human-reviewed. `docs/diff-readiness.md` defines the
  full contract. Value divergence between old and new parser is EXPECTED
  and must never be treated as an equality gate.

- **CUT-05 (weighted / blue-green gradual traffic shift) is DEFERRED to
  v2.x.** This runbook documents the v1 one-edit cutover only.

- **Do NOT execute the cutover until both gates pass** and the operator
  has reviewed the diff output.

## Pre-flight Gates

All four gates must be satisfied before running `scripts/cutover.sh`.
The script enforces Gates 1 and 2 programmatically and refuses to
proceed if either is unmet — even in `DRY_RUN=1` mode.

### Gate 1 — Fresh Verified Backup (CUT-03)

`docs/backup-gate.md` must contain the line `Status: verified` and the
backup must be younger than the planned ingest window.

If the last backup is stale, create a fresh one:

```bash
kubectl -n solid-stats-staging create job \
  postgres-backup-preflight-$(date -u +%Y%m%dT%H%M%S) \
  --from=cronjob/postgres-backup
kubectl -n solid-stats-staging wait job/<job-name> \
  --for=condition=complete --timeout=120s
kubectl -n solid-stats-staging logs job/<job-name> | tail -20
```

Confirm the Job completed and the logs include `backup_id=`, then update
`docs/backup-gate.md` with the new backup ID and the line
`Status: verified`.

### Gate 2 — Green Diff Coverage (NOT Equality) (CUT-03)

`docs/diff-readiness.md` must contain the line `strict_failures: 0`
under a `## Cutover Gate Evidence` section — meaning no missing players,
no missing matches, no parser errors, and no unexplained aggregate
deviations outside tolerance.

**Allowlisted known differences (value divergence from the rewrite) do
NOT block this gate.** The operator must have reviewed the diff output
before recording the evidence marker.

To record the gate evidence after human review is complete, add this
block to `docs/diff-readiness.md`:

```markdown
## Cutover Gate Evidence

strict_failures: 0
allowlisted_known_differences: <N>
reviewed_by: <operator>
reviewed_at: <ISO-8601 timestamp>
full_run_job: <job-name>
```

### Gate 3 — Live Edge Proven Reversible

Phase 7 bootstrap → teardown → re-bootstrap cycle was executed and
passed (see `docs/edge-bootstrap.md`). The vhost `.bak` backup exists on
the VPS (created by `bootstrap-edge.sh`). Confirm:

```bash
ls -la /etc/nginx/sites-available/stats-staging-solid-stats.conf.bak
```

### Gate 4 — Smoke Target Defined and Healthy

`NEW_UPSTREAM` is known and the target runtime is healthy in k3s:

```bash
kubectl -n solid-stats-staging rollout status deployment/server-2
kubectl -n solid-stats-staging get svc
# Confirm the target ClusterIP:port for NEW_UPSTREAM
```

## Timing — How Long to Accumulate Before Flipping

There is no hard minimum; the operator decides when confidence is
sufficient. The recommended approach:

1. Run at least one full controlled ingest (`docs/full-run.md`) with the
   new runtime active and confirm the diff gate passes
   (`strict_failures: 0`) after reviewing the output.
2. Let the new runtime serve traffic in parallel for at least **24 h**
   and observe error rates in `kubectl logs`.
3. Confirm the diff gate passes after the full-run output is reviewed.
4. Only then declare both gates met and proceed.

The cutover is reversible within minutes if the smoke check or
post-cutover monitoring reveals a problem.

## Cutover Procedure (CUT-01)

Confirm all four gates are satisfied, then on the VPS:

```bash
NEW_UPSTREAM=<target_address:port> scripts/cutover.sh
```

For a dry-run preview (**does NOT touch nginx**):

```bash
DRY_RUN=1 NEW_UPSTREAM=<target_address:port> scripts/cutover.sh
```

`DRY_RUN=1` still enforces Gates 1 and 2 — it exits 1 if either gate is
unmet, confirming the gate state before a live run.

### What `scripts/cutover.sh` Does

1. Checks `Status: verified` in `docs/backup-gate.md` (Gate 1).
2. Checks `strict_failures: 0` in `docs/diff-readiness.md` (Gate 2).
3. Backs up the live vhost to
   `/etc/nginx/sites-available/stats-staging-solid-stats.conf.cutover.bak`.
4. Replaces the `server` line at the `# CUTOVER:` marker with
   `NEW_UPSTREAM`.
5. Runs `nginx -t` (fail-closed — exits without reloading on invalid
   config).
6. Reloads nginx.
7. Runs a smoke check: `curl -fsS -I https://stats-staging.solid-stats.ru/`
   (3 retries, 5 s delay).
8. **AUTO-ROLLBACK** if the smoke check fails (restores the backup and
   reloads nginx).

### Post-Cutover Immediate Checks — OPERATOR-ONLY

> **OPERATOR-ONLY.** These checks require live VPS access.

```bash
nginx -t
curl -I https://stats-staging.solid-stats.ru/
kubectl -n solid-stats-staging logs deployment/server-2 --since=5m | tail -20
```

### Cutover Evidence (Operator-Captured)

> **Placeholder — do NOT fabricate.** The operator records evidence here
> after the live flip is performed.

| Field | Value |
|-------|-------|
| Date | _(not yet performed)_ |
| Operator | _(not yet performed)_ |
| Previous upstream | _(not yet performed)_ |
| New upstream | _(not yet performed)_ |
| Smoke check result | _(not yet performed)_ |
| Post-cutover curl | _(not yet performed)_ |

## Rollback (CUT-02)

The auto-rollback fires automatically if the smoke check fails during
`cutover.sh`. If you need to revert manually after a successful cutover:

**Method 1 — restore from the cutover backup (fastest):**

```bash
cp /etc/nginx/sites-available/stats-staging-solid-stats.conf.cutover.bak \
   /etc/nginx/sites-available/stats-staging-solid-stats.conf
nginx -t && systemctl reload nginx
```

**Method 2 — re-run `bootstrap-edge.sh`:**

Restore the original `server` line in
`config/nginx/sites-available/stats-staging-solid-stats.conf`, then:

```bash
ADMIN_EMAIL=ops@example.com SKIP_UFW=1 scripts/bootstrap-edge.sh
```

**Verify rollback:**

```bash
curl -I https://stats-staging.solid-stats.ru/   # response from legacy upstream
nginx -t
```

The Phase 7 teardown evidence (`docs/edge-bootstrap.md` — Reversibility
section) proves that vhost backup → restore → nginx reload is a working,
tested recovery path.

## Offline Checks (CI)

The following runs in CI without VPS access:

```bash
python3 scripts/validate-staging.py
```

Expected: all `ok:` lines, including `ok: cutover artifacts`.

This validates that `scripts/cutover.sh` and `docs/cutover.md` exist and
contain all required gate markers. `bash -n` is also run on `cutover.sh`.
