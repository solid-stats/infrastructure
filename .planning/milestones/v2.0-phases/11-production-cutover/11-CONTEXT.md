# Phase 11: Production Cutover - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); enriched with codebase + memory facts by the orchestrator

<domain>
## Phase Boundary

Operator can switch production traffic to the new runtime in a single reversible nginx-upstream edit,
gated on a fresh backup and a green diff, with a tested rollback and a post-cutover smoke check.

Requirements: CUT-01, CUT-02, CUT-03, CUT-04. Depends on: Phase 7, 8, 9, 10.
This phase delivers the PROVEN, TESTED, REVERSIBLE cutover MECHANISM + runbook + gates. The actual
production traffic flip is an OPERATOR action (consequential, irreversible-ish) and is NOT performed
unattended by this autonomous run. CUT-05 (weighted/blue-green gradual shift) is DEFERRED to v2.x.
</domain>

<decisions>
## Implementation Decisions

### Locked by codebase + memory facts (verified 2026-06-13)
- **The cutover lever is the nginx upstream `server` line.** `config/nginx/sites-available/stats-staging-solid-stats.conf`
  has the `# CUTOVER:` marker on `server 10.43.94.103:3000;` inside the `upstream solid_stats_staging_server2` block.
  Switching that one line (plus `nginx -t` + reload) is the single reversible cutover edit (CUT-01). Rollback (CUT-02)
  = revert that line and reload — the Phase 7 backup-before-overwrite + teardown pattern already proves this is reversible.
- **GREEN DIFF IS NOT VALUE-EQUALITY (critical — memory `legacy-vs-new-parser-non-identical`).** The new runtime
  (`server-2`/`replay-parser-2`) is a deliberate rewrite; computed stat VALUES diverge from legacy BY DESIGN. So the
  "green diff" gate (CUT-03) is a COVERAGE/INTEGRITY check only — `strict_failures` = missing matches/players, parser
  errors/crashes, aggregate totals outside a DECLARED tolerance. Intended value differences go to an allowlist and are
  HUMAN review, never an automated equality gate. This is already specified in `docs/diff-readiness.md` (Phase 5).
  Do NOT build an equality gate.
- **Existing Phase-5 gate tooling to REUSE (do not duplicate):**
  - `docs/backup-gate.md` — the fresh-backup gate (`Status: verified`). `scripts/start-controlled-full-run.sh`
    already refuses to run unless this is verified — mirror that gate pattern in the cutover script (CUT-03 backup gate).
  - `docs/diff-readiness.md` — the old-vs-new coverage/review contract (CUT-03 green-diff gate; review gate, not auto-equality).
  - `docs/full-run.md` + `scripts/start-controlled-full-run.sh` — the controlled full run that produces the new stats to diff.
- **"Legacy kept warm" / parallel run (CUT-01, CUT-02):** the parallel run of legacy + new exists for backfill, rollback
  (warm legacy = one-edit upstream revert), load proof, and the coverage-only auto-check — NOT for value comparison. The
  cutover script keeps the previous (legacy) upstream value recorded so rollback is a single edit back.

### Claude's discretion (decide during planning, justify in PLAN)
- **Cutover script (`scripts/cutover.sh` or similar)** that, when run by the operator on the edge host:
  1. GATE: refuses unless (a) `docs/backup-gate.md` is `Status: verified` (fresh backup, CUT-03) AND (b) a green-diff
     coverage evidence marker is recorded (e.g. `docs/diff-readiness.md` or a cutover-gate doc shows the coverage check
     passed / `strict_failures: 0`). Fail loudly if either gate is unmet.
  2. Backs up the current live vhost (reversibility), switches the upstream `server` line to the target value
     (parameterized: `NEW_UPSTREAM`), `nginx -t` (fail-closed), reload.
  3. SMOKE CHECK (CUT-04): `curl -fsS -I https://<host>/` confirms the new runtime responds (2xx/expected) BEFORE legacy
     is retired; on smoke-check failure, AUTO-ROLLBACK.
  4. ROLLBACK function (CUT-02): restore the backed-up vhost (or revert the one line) + `nginx -t` + reload, single edit.
  - Mirror `scripts/bootstrap-edge.sh`/`teardown-edge.sh` style + fail-closed gates. `#!/usr/bin/env bash`, `set -euo pipefail`,
    `required()` env checks, exit 64. NEVER echo secrets.
- **Runbook `docs/cutover.md`:** the full operator procedure — the 4 gates, the one-edit switch, the tested rollback, the
  smoke check, the "how long to accumulate new stats / observe coverage + load before flipping" timing question (per memory),
  and the explicit note that the green-diff gate is coverage-only (value divergence is expected, human-reviewed).
- **Offline validator check:** assert the cutover script + runbook exist and contain the required gate markers (backup gate,
  green-diff/coverage gate, smoke check, rollback). Stdlib-only, wired into validate-staging.py.
- **Reversibility proof:** the cutover/rollback reversibility can be argued from the Phase 7 teardown evidence (vhost
  backup→restore proven live) + a `--dry-run`/self-test path; a LIVE traffic-affecting switch on the edge is OPERATOR-gated
  (it disrupts the served host) — design a non-disruptive self-test where possible, and mark the live cutover autonomous:false.
</decisions>

<code_context>
## Existing Code Insights
- `config/nginx/sites-available/stats-staging-solid-stats.conf` — the `# CUTOVER:` upstream lever (Phase 7).
- `scripts/bootstrap-edge.sh` / `scripts/teardown-edge.sh` — backup-before-overwrite + fail-closed nginx -t/reload + reversibility pattern to mirror.
- `scripts/start-controlled-full-run.sh` — the `grep "Status: verified" docs/backup-gate.md` gate pattern to reuse for CUT-03.
- `docs/backup-gate.md`, `docs/diff-readiness.md`, `docs/full-run.md` — the Phase-5 gate docs to wire into the cutover gates.
- `scripts/validate-staging.py` / `scripts/validate-edge.py` — stdlib-only validators to extend.
- AGENTS.md — production cutover is out of v1/v2 STAGING scope as a live action; this phase delivers the mechanism. §D: infra owns the edge wiring, not the app/production environment.
</code_context>

<specifics>
## Specific Ideas
- The cutover is ONE reversible line edit on the nginx upstream, gated, smoke-checked, with auto-rollback on smoke failure.
- The green-diff gate is coverage/integrity only (strict_failures), never value-equality — value divergence is expected and human-reviewed.
- The live production flip is operator-run; the autonomous build delivers and offline-proves the mechanism.
</specifics>

<deferred>
## Deferred Ideas
- CUT-05: weighted / blue-green nginx cutover with gradual traffic shift — deferred to v2.x.
- The actual production traffic flip + a live traffic-affecting reversibility test on the served host — operator-gated.
</deferred>
