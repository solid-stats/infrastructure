---
phase: 11-production-cutover
plan: "01"
subsystem: infra
tags: [nginx, bash, cutover, rollback, smoke-check, gates]

requires:
  - phase: 07-edge-automation
    provides: bootstrap-edge.sh/teardown-edge.sh backup-before-overwrite + fail-closed nginx -t pattern
  - phase: 05-full-run-diff
    provides: docs/backup-gate.md and docs/diff-readiness.md gate documents the script reads

provides:
  - scripts/cutover.sh — 4-gate reversible nginx upstream cutover script
  - Offline-proven gate refusal logic (Gate A + Gate B, including DRY_RUN mode)
  - SELF_TEST=1 mode that exercises rollback() byte-restore without touching live nginx

affects:
  - 11-02-PLAN (operator runbook + live cutover)
  - validate-staging.py (future gate marker checks may be added)

tech-stack:
  added: []
  patterns:
    - "4-gate script: backup gate + coverage gate enforced before any mutation, even in DRY_RUN"
    - "Backup-before-overwrite: cp -p .cutover.bak always written pre-mutation so rollback has current state"
    - "Fail-closed nginx -t: config validated before reload; invalid config triggers rollback + exit 1"
    - "smoke_ok sentinel loop: curl 2xx/3xx success; retries with SMOKE_DELAY; auto-rollback on exhaustion"
    - "SELF_TEST isolation: rollback() redefine in-scope to skip real nginx; temp files cleaned up"

key-files:
  created:
    - scripts/cutover.sh
  modified: []

key-decisions:
  - "SELF_TEST early path placed BEFORE gate checks (gate docs not required for rollback isolation test)"
  - "DRY_RUN exits after gates pass but before any mutation — proves both gates satisfied before flip"
  - "Green-diff gate (Gate B) is coverage/integrity only: grep strict_failures: 0 — never value equality"
  - "rollback() defined after vhost backup but before first nginx mutation so it is always callable"
  - "SELF_TEST redefines rollback() locally to suppress real nginx -t/reload; avoids nginx dependency on CI/offline hosts"

patterns-established:
  - "Pattern: gate-enforced operator script — all pre-flight checks run even in dry-run/test modes"
  - "Pattern: rollback-first design — backup written before mutation, rollback() defined before nginx touch"

requirements-completed:
  - CUT-01
  - CUT-02
  - CUT-03
  - CUT-04

duration: ~20min
completed: "2026-06-13"
status: complete
---

# Phase 11 Plan 01: Cutover Script Summary

**4-gate reversible nginx upstream switch (scripts/cutover.sh) with offline-proven backup/coverage gates, byte-restore rollback, and smoke-check auto-rollback**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-13T20:15:00Z
- **Completed:** 2026-06-13T20:35:42Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- `scripts/cutover.sh` created: 281-line operator script implementing all 4 CUT-* requirements
- Gate A (backup) and Gate B (coverage) enforced before any mutation; also enforced in DRY_RUN mode
- SELF_TEST=1 exercises rollback() isolation on a temp vhost copy and asserts byte-restore
- All offline tests pass: gate-A refusal, gate-B refusal, gate-A refusal in DRY_RUN, SELF_TEST rollback
- `python3 scripts/validate-staging.py` still exits 0

## Task Commits

1. **Task 1: Write scripts/cutover.sh** - `b67f2d8` (feat)

**Plan metadata:** _(docs commit below)_

## Files Created/Modified

- `scripts/cutover.sh` — 4-gate reversible production nginx upstream cutover script

## Decisions Made

- SELF_TEST path placed before SECTION 2 gate checks per plan spec ("SELF_TEST=1 skips gate checks")
- DRY_RUN early-exits after gates pass — proves operator has satisfied both pre-flight gates before committing to live flip
- Green-diff gate is coverage/integrity only (`strict_failures: 0`) — NOT value equality; value divergence is expected by design (memory: legacy-vs-new-parser-non-identical)
- SELF_TEST redefines `rollback()` locally to suppress `nginx -t`/`systemctl reload` so it runs safely on any host with a readable VHOST_CONF

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SELF_TEST placed after gate checks in initial write**
- **Found during:** Task 1 (verification run)
- **Issue:** Initial draft placed SELF_TEST block after SECTION 4 (rollback definition), meaning SELF_TEST=1 would fail on Gate A/B checks — contradicting the plan spec "SELF_TEST=1 skips SECTION 2 gate checks"
- **Fix:** Moved SELF_TEST block to before SECTION 2; removed duplicate lower block; redefined rollback() locally within SELF_TEST scope to suppress nginx/systemctl calls
- **Files modified:** scripts/cutover.sh
- **Verification:** `SELF_TEST=1 VHOST_CONF=config/nginx/... bash scripts/cutover.sh` exits 0 with "SELF_TEST PASSED"
- **Committed in:** b67f2d8 (Task 1 commit — fix applied before final commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in initial ordering)
**Impact on plan:** Fix required for correct SELF_TEST=1 behavior per spec. No scope creep.

## Offline Verification Results

All tests run against `scripts/cutover.sh` without live nginx:

| Test | Command | Result |
|------|---------|--------|
| Syntax | `bash -n scripts/cutover.sh` | ok |
| Gate A refusal | `BACKUP_GATE_FILE=<unverified> bash scripts/cutover.sh` | "backup gate not verified" + exit 1 |
| Gate B refusal | `DIFF_GATE_FILE=<no-marker> bash scripts/cutover.sh` | "diff coverage gate not met" + exit 1 |
| Gate A in DRY_RUN | `DRY_RUN=1 BACKUP_GATE_FILE=<unverified> bash scripts/cutover.sh` | "backup gate not verified" + exit 1 |
| SELF_TEST rollback | `SELF_TEST=1 VHOST_CONF=config/nginx/... bash scripts/cutover.sh` | "SELF_TEST PASSED: rollback() correctly restored the temp vhost from backup" + exit 0 |
| validate-staging | `python3 scripts/validate-staging.py` | all checks ok + exit 0 |

## Issues Encountered

None beyond the SELF_TEST ordering bug documented as a deviation above.

## Next Phase Readiness

- `scripts/cutover.sh` is ready for the operator runbook (plan 11-02)
- Live cutover is operator-gated (autonomous: false in 11-02)
- SELF_TEST and all gate tests can be run offline to verify the mechanism before the live flip

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. `scripts/cutover.sh` runs as root on the VPS edge host; all inputs are env vars set by the operator. The `# CUTOVER:` nginx lever was already present in `config/nginx/sites-available/stats-staging-solid-stats.conf` from Phase 7. No new threat surface beyond what the plan's threat model already covers.

---
*Phase: 11-production-cutover*
*Completed: 2026-06-13*
