---
status: testing
phase: 11-production-cutover
source: [11-VERIFICATION.md]
started: 2026-06-13T02:10:00Z
updated: 2026-06-13T02:10:00Z
---

## Current Test

number: 1
name: Live production cutover (operator-gated)
expected: |
  Operator runs scripts/cutover.sh to switch traffic to the new runtime in one reversible
  edit, gated on a fresh backup + green-diff coverage, with a verified rollback and a passing
  post-cutover smoke check. Evidence recorded in docs/cutover.md.
awaiting: operator execution (consequential: switches real production traffic; production target is outside this staging env, AGENTS.md)

## Tests

### 1. Pre-flight gates ready
expected: docs/backup-gate.md shows `Status: verified` (fresh backup), and docs/diff-readiness.md records `strict_failures: 0` (green-diff COVERAGE check — value divergence is expected, human-reviewed, NOT an equality gate).
result: [pending — operator] Run a controlled full-run, review the diff, record strict_failures:0 evidence.

### 2. DRY_RUN preview (non-mutating)
expected: `DRY_RUN=1 NEW_UPSTREAM=<target:port> scripts/cutover.sh` enforces both gates and prints the would-be switch without touching nginx.
result: [pending — operator] Confirm the gates pass and the preview is correct before the real flip.

### 3. Live flip + smoke check + reversibility
expected: `NEW_UPSTREAM=<target:port> scripts/cutover.sh` backs up the vhost, switches the # CUTOVER upstream line, nginx -t (fail-closed), reloads, and the post-cutover smoke check (curl 2xx/3xx) passes; on smoke failure it AUTO-ROLLS-BACK. `rollback()` reverts in one edit if needed.
result: [pending — operator] Execute the flip; capture the smoke-check curl output + flip timestamp/upstreams/operator in docs/cutover.md.

### 4. Post-cutover monitoring
expected: New runtime serves correctly; legacy kept warm for one-edit rollback during an observation window.
result: [pending — operator] Monitor ~24h; retire legacy only after the new runtime is confirmed healthy.

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

### Why operator-gated (not done in the autonomous run)
The live production traffic flip is consequential (switches real traffic) and the production target is outside this
staging environment's scope (AGENTS.md: v1 targets solid-stats-staging only; production cutover deferred). The
autonomous run built and OFFLINE-PROVED the complete mechanism — all 4 gates, the anchored single-line switch, the
TESTED rollback (SELF_TEST exercises the REAL rollback() with byte-restore asserted), the smoke check + auto-rollback,
the DRY_RUN preview — and a code review's 1 critical + 5 warnings were all fixed. The remaining step is the operator's
human decision to flip after reviewing the diff. See docs/cutover.md for the turnkey runbook.
