---
status: complete
phase: 11-production-cutover
source: [11-VERIFICATION.md]
started: 2026-06-13T02:10:00Z
updated: 2026-06-13T06:30:00Z
---

## Current Test

number: —
name: Cutover MECHANISM live-verified (2026-06-13, option B); live prod flip deferred by scope
expected: |
  Without flipping production traffic, exercise every safe part of the cutover mechanism live:
  gate enforcement (both directions), the non-mutating DRY_RUN preview, the reversible rollback(),
  and confirm the live edge vhost is cutover-ready (marker present + nginx -t valid).
result: |
  ✅ DONE 2026-06-13. SELF_TEST rollback PASS; DRY_RUN correctly fail-closed on the missing
  green-diff gate AND happy-path preview correct when both gates pass; the live edge vhost carries
  the # CUTOVER marker (current upstream server 10.43.94.103:3000) and `nginx -t` is successful.
  The actual live switch/reload/smoke (= the production traffic flip) remains DEFERRED BY SCOPE
  (AGENTS.md: v2 targets staging only; production cutover intentionally deferred).

## Tests

### 1. Pre-flight gates ready
expected: docs/backup-gate.md shows `Status: verified` (fresh backup), and docs/diff-readiness.md records `strict_failures: 0` (green-diff COVERAGE check — value divergence is expected, human-reviewed, NOT an equality gate).
result: ⏳ PARTIAL (mechanism verified; evidence deferred). Gate ENFORCEMENT proven live 2026-06-13: Gate A (backup `Status: verified`) reads + passes; Gate B (`strict_failures: 0`) is absent in docs/diff-readiness.md, so the gate correctly FATALs (fail-closed). Producing the real green-diff evidence requires a controlled full-run + human diff review — a deferred production-cutover step, not a v2 task.

### 2. DRY_RUN preview (non-mutating)
expected: `DRY_RUN=1 NEW_UPSTREAM=<target:port> scripts/cutover.sh` enforces both gates and prints the would-be switch without touching nginx.
result: ✅ PASS (2026-06-13). With the real backup gate + a synthetic green-diff gate (`DIFF_GATE_FILE=/tmp`, so the real evidence doc is untouched), DRY_RUN printed the correct preview (cp backup → sed switch at # CUTOVER → nginx -t → reload → curl smoke) and `gates PASSED — would proceed`. With the real (unmet) green-diff gate it exits 1 — fail-closed both ways. No nginx mutation.

### 3. Live flip + smoke check + reversibility
expected: `NEW_UPSTREAM=<target:port> scripts/cutover.sh` backs up the vhost, switches the # CUTOVER upstream line, nginx -t (fail-closed), reloads, and the post-cutover smoke check (curl 2xx/3xx) passes; on smoke failure it AUTO-ROLLS-BACK. `rollback()` reverts in one edit if needed.
result: ⏳ Reversibility VERIFIED; live switch DEFERRED. SELF_TEST exercised the REAL `rollback()` live (restore + nginx -t + reload control flow, byte-restore asserted) → PASS. The live edge vhost is cutover-ready: `# CUTOVER:` marker present, current upstream `server 10.43.94.103:3000;`, `nginx -t` successful. The actual switch + reload + smoke = the production traffic flip — DEFERRED BY SCOPE (AGENTS.md).

### 4. Post-cutover monitoring
expected: New runtime serves correctly; legacy kept warm for one-edit rollback during an observation window.
result: ⏳ DEFERRED — applies only after a real flip, which is out of v2 scope.

## Summary

total: 4
passed: 2
issues: 0
pending: 0
deferred: 2
skipped: 0
blocked: 0

note: 2026-06-13 (option B) — cutover MECHANISM live-verified without flipping production: gate enforcement (both directions), DRY_RUN preview, the reversible rollback() (SELF_TEST), and live edge cutover-readiness (marker + nginx -t). The live production traffic flip (tests 3 switch/smoke + 4 monitoring) is DEFERRED BY SCOPE per AGENTS.md (v2 = staging only; production cutover intentionally deferred) — a future production decision, not a v2 execution item.

## Gaps

### Why operator-gated (not done in the autonomous run)
The live production traffic flip is consequential (switches real traffic) and the production target is outside this
staging environment's scope (AGENTS.md: v1 targets solid-stats-staging only; production cutover deferred). The
autonomous run built and OFFLINE-PROVED the complete mechanism — all 4 gates, the anchored single-line switch, the
TESTED rollback (SELF_TEST exercises the REAL rollback() with byte-restore asserted), the smoke check + auto-rollback,
the DRY_RUN preview — and a code review's 1 critical + 5 warnings were all fixed. The remaining step is the operator's
human decision to flip after reviewing the diff. See docs/cutover.md for the turnkey runbook.
