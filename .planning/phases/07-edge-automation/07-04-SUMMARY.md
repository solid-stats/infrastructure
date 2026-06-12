---
phase: "07-edge-automation"
plan: 4
subsystem: edge
tags: [runbook, docs, edge-bootstrap, nginx, certbot, ufw, reversibility, phase-11-lever]
dependency_graph:
  requires:
    - scripts/validate-edge.py (07-01)
    - config/nginx/sites-available/stats-staging-solid-stats.conf (07-01)
    - config/systemd/certbot.service.d/onfailure.conf (07-02)
    - config/systemd/certbot-renew-failure.service (07-02)
    - config/systemd/certbot-deploy-hook.sh (07-02)
    - scripts/bootstrap-edge.sh (07-03)
    - scripts/teardown-edge.sh (07-03)
  provides:
    - docs/edge-bootstrap.md
  affects: []
tech_stack:
  added: []
  patterns:
    - Operator runbook with OFFLINE-VERIFIABLE / OPERATOR-ONLY section labels
    - Adopt-not-build documentation pattern (same style as docs/operator-bootstrap.md)
key_files:
  created:
    - docs/edge-bootstrap.md
  modified: []
decisions:
  - "All EDGE-01..05 requirements have documentation evidence in the runbook"
  - "Offline vs. operator-only split explicitly labeled per 07-VALIDATION.md"
  - "Stock certbot.timer documented as preserved; no new timer created (D-4)"
  - "Phase 11 cutover lever documented: solid_stats_staging_server2 upstream block + # CUTOVER: marker"
  - "Reversibility section documents teardown-edge.sh + .bak restore mechanism (D-8)"
metrics:
  duration: "60s"
  completed: "2026-06-13"
  tasks: 1
  files: 1
status: complete
---

# Phase 07 Plan 04: Edge Bootstrap Operator Runbook Summary

**One-liner:** Operator runbook (docs/edge-bootstrap.md) connecting all Phase 7 artifacts — offline CI checks, adopt-reconcile bootstrap invocation, OPERATOR-ONLY live verification, Phase 11 nginx upstream cutover lever, and reversibility proof via teardown-edge.sh + .bak restore.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Operator runbook — docs/edge-bootstrap.md (EDGE-01..05, D-1..D-9) | 220747b | docs/edge-bootstrap.md |

## What Was Built

### docs/edge-bootstrap.md

Operator runbook following the structure and tone of `docs/operator-bootstrap.md`. Ten `##`
sections:

1. **Context: Adopt, Not Rebuild** — explains the adopt-not-build reality; five bullet points
   for what Phase 7 does (vhost in repo, deploy hook, OnFailure= drop-in, ufw rules, stock
   certbot.timer preserved).
2. **Prerequisites** — SSH, git clone, ADMIN_EMAIL, wg0 up, ports 80/443 reachable.
3. **Offline Checks (CI)** — `OFFLINE-VERIFIABLE` label; `python3 scripts/validate-edge.py`
   invocation; expected five `ok:` lines.
4. **Step 1: Clone / Update the Repo on the VPS** — `git pull` / `git clone`.
5. **Step 2: Run the Bootstrap Script** — `ADMIN_EMAIL=... scripts/bootstrap-edge.sh`; full
   list of what bootstrap does (packages, .bak backup, vhost install + nginx -t gate, cert
   skip, deploy hook, OnFailure= drop-in, ufw rules with wg0 pre-check); `SKIP_UFW=1` variant;
   idempotency guarantee.
6. **Step 3: Operator-Only Live Verification** — five sub-sections each labeled
   `OPERATOR-ONLY`: nginx -t (3a), certbot renew --dry-run (3b), systemctl show OnFailure
   (3c), ufw status verbose with expected split-tunnel rules (3d), curl -I smoke check (3e).
7. **Step 4: Certificate Renewal Verification** — `OPERATOR-ONLY`; journalctl -t certbot-alert;
   explicit "Do NOT create a custom certbot-renew.timer" warning (T-7-04-04 mitigation).
8. **Phase 11 Cutover Lever** — exact file path, upstream block name
   `solid_stats_staging_server2`, the `# CUTOVER:` marker line, and edit instruction.
9. **Reversibility: Teardown** — `scripts/teardown-edge.sh` invocation; what is removed vs.
   preserved (.bak restore, certs preserved, 22/tcp preserved, ufw remains enabled); four
   post-teardown verification commands.
10. **Troubleshooting** — table with six common failure modes, causes, and fixes.

## Verification Results

All plan verification checks passed:

- `grep -c "^## " docs/edge-bootstrap.md` → `10` (>= 8 required)
- `grep "OPERATOR-ONLY" docs/edge-bootstrap.md` → exit 0
- `grep "CUTOVER" docs/edge-bootstrap.md` → exit 0
- `grep "solid_stats_staging_server2" docs/edge-bootstrap.md` → exit 0
- `grep "teardown-edge.sh" docs/edge-bootstrap.md` → exit 0
- `grep "validate-edge.py" docs/edge-bootstrap.md` → exit 0
- `grep "bootstrap-edge.sh" docs/edge-bootstrap.md` → exit 0
- `grep "certbot renew --dry-run" docs/edge-bootstrap.md` → exit 0
- `grep "ufw status" docs/edge-bootstrap.md` → exit 0
- `grep "\.bak" docs/edge-bootstrap.md` → exit 0
- `grep "certbot.timer" docs/edge-bootstrap.md` → exit 0

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — the runbook is complete. It references host-runtime paths and commands that are
host dependencies, not documentation stubs.

## Threat Surface Scan

Documentation-only plan — no new network endpoints, auth paths, file access patterns, or
schema changes introduced. Threat model items addressed:

- T-7-04-01 (Phase 11 lever documented incorrectly): mitigated — runbook references exact
  upstream block name `solid_stats_staging_server2` and exact `# CUTOVER:` marker
- T-7-04-02 (ADMIN_EMAIL in docs): accepted — Let's Encrypt registration email, not a secret
- T-7-04-03 (operator skips teardown proof): accepted — dedicated Reversibility section with
  step-by-step verification commands makes the requirement explicit
- T-7-04-04 (operator creates second certbot timer): mitigated — Step 4 has explicit "Do NOT
  create a custom certbot-renew.timer" warning with the reason

## Self-Check: PASSED

- FOUND: docs/edge-bootstrap.md
- FOUND: commit 220747b (Task 1)
