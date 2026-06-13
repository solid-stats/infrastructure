---
phase: 12-resource-protection-obs-foundation
plan: "01"
subsystem: validation-harness
tags: [kubernetes, observability, bash, validation, preflight]
status: complete

dependency_graph:
  requires: []
  provides:
    - scripts/resource-preflight.sh (PREP-01 node/pod snapshot)
    - scripts/validate-phase-12.sh (PREP-01..05 assertion harness)
    - validate-staging.py bash syntax-check coverage for both scripts
  affects:
    - CI: validate-staging.py now syntax-checks both new scripts on every run
    - Plans 12-02..05: validation harness is ready for live assertion after manifests are applied

tech_stack:
  added: []
  patterns:
    - bash strict mode (#!/usr/bin/env bash + set -euo pipefail)
    - env var defaults with :=
    - tee-based output capture to timestamped file
    - assert() helper (label/actual/expected) pattern for kubectl assertion scripts

key_files:
  created:
    - scripts/resource-preflight.sh
    - scripts/validate-phase-12.sh
  modified:
    - scripts/validate-staging.py

decisions:
  - PREP-02 swap not asserted in validate-phase-12.sh — SSH-only check; script emits
    a directed manual note instead of attempting SSH from kubectl context
  - postgres priorityClassName lookup falls back to pod name postgres-0 when label
    selector returns empty (StatefulSet pods may not carry app.kubernetes.io/name label)
  - EXPECTED_MANIFESTS in validate-staging.py left unchanged — 01-obs-rbac.yaml and
    02-priority-classes.yaml are operator-bootstrap files excluded from CI per 12-PATTERNS.md

metrics:
  duration_seconds: 186
  completed_date: "2026-06-13"
  tasks_completed: 3
  files_changed: 3
---

# Phase 12 Plan 01: Validation Harness Bootstrap Summary

**One-liner:** Phase 12 preflight snapshot script and kubectl assertion harness created and wired into CI syntax checks before any manifest or live-cluster change.

## What Was Built

### Task 1 — scripts/resource-preflight.sh (commit 3dec0bf)

Re-runnable bash snapshot implementing PREP-01. Captures in order:

1. `kubectl describe node` — allocatable vs allocated
2. `kubectl top nodes` — live usage (graceful fallback if metrics-server absent)
3. `kubectl top pods --all-namespaces` — same fallback
4. Per-namespace pod table with custom-columns: NAME / QOS (`.status.qosClass`) / CPU_REQ / CPU_LIM / MEM_REQ / MEM_LIM
5. `df -h` — node disk usage
6. `free -h` — host memory and swap

Output written to `${OUTPUT_DIR}/resource-preflight-${snapshot_ts}.txt` via `{ … } | tee`.

### Task 2 — scripts/validate-phase-12.sh (commit c059712)

Single re-runnable assertion harness for all PREP requirements. Exits 1 on first failure.

Assertions implemented:

| Requirement | Assertion |
|-------------|-----------|
| PREP-03 | `app-critical` PriorityClass value == `1000000` |
| PREP-03 | `obs-background` PriorityClass value == `100` |
| PREP-03 | Each app workload pod (postgres, server-2, replay-parser-2, rabbitmq) carries `priorityClassName: app-critical` |
| PREP-04 | `postgres-0` `.status.qosClass` == `Guaranteed` |
| PREP-04 | server-2 pod `.status.qosClass` == `Guaranteed` |
| PREP-05 | `monitoring` and `error-tracking` namespaces exist |
| PREP-05 | `obs-ci-deployer` SA present in both namespaces |
| PREP-05 | Positive: `auth can-i create deployments --as=…:monitoring:obs-ci-deployer -n monitoring` == `yes` |
| PREP-05 | Negative isolation: `auth can-i get pods --as=…:monitoring:obs-ci-deployer -n solid-stats-staging` == `no` |
| PREP-02 | Printed manual SSH note (swap cannot be asserted over kubectl) |

### Task 3 — scripts/validate-staging.py (commit 6e068fa)

Added `scripts/resource-preflight.sh` and `scripts/validate-phase-12.sh` to the `validate_scripts()` bash syntax-check list. `python3 scripts/validate-staging.py` exits 0 with all checks green.

## Verification

- `bash -n` clean on both scripts: **PASS**
- `test -x` on both scripts: **PASS**
- `python3 scripts/validate-staging.py` exits 0: **PASS** (all 10 checks green)
- No live cluster or host contacted: **CONFIRMED** (authoring-only plan)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] postgres label fallback in priorityClassName assertion**

- **Found during:** Task 2
- **Issue:** StatefulSet pods in k3s may not carry `app.kubernetes.io/name=postgres` label, making the uniform label-selector loop return empty for postgres.
- **Fix:** Added a fallback that queries `pod/postgres-0` by name when the label selector returns empty.
- **Files modified:** scripts/validate-phase-12.sh
- **Impact:** Assertion still fails loudly if the pod is missing; no silent false-positive.

## Known Stubs

None — all assertions are wired to real kubectl commands. No placeholder values.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. Snapshot output (T-12-01) contains node metadata only, written to operator-local `/tmp`, never committed.

## Self-Check: PASSED

- [x] `scripts/resource-preflight.sh` exists and is executable
- [x] `scripts/validate-phase-12.sh` exists and is executable
- [x] Commits 3dec0bf, c059712, 6e068fa present in git log
- [x] `python3 scripts/validate-staging.py` exits 0
