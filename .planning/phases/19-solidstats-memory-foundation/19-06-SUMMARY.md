---
phase: 19-solidstats-memory-foundation
plan: 06
subsystem: infrastructure
tags: [kubernetes, github-actions, secrets, validation, s3]
requires:
  - phase: 19-05
    provides: accepted Prometheus render parity and isolated memory runtime manifests
provides:
  - checked-in memory backup endpoint and prefix
  - copy-only manifest staging with offline fail-closed validation
  - direct repository S3 secret reuse in the dedicated deploy workflow
affects: [memory deployment, operator evidence gates, staging backups]
tech-stack:
  added: []
  patterns: [repository-owned non-secret desired state, explicit synthetic renderer environments]
key-files:
  created: []
  modified:
    - .github/workflows/deploy-memory.yml
    - k8s/memory/40-backup.yaml
    - scripts/render-memory-manifests.py
    - scripts/render-memory-secrets.py
    - scripts/validate-memory-manifests.py
    - tests/test-memory-runtime-contract.py
    - docs/solidstats-memory.md
key-decisions:
  - "Keep endpoint and prefix in the backup manifest while retaining bucket and credentials as secrets."
  - "Preserve the existing SolidStats Qdrant namespace because its manifest is outside this plan's owned files."
actuals:
  tokens: 18875
  tasks: 2
  commits: 2
requirements-completed: [ISO-02, OPS-01]
coverage:
  - id: D1
    description: Checked-in memory configuration and copy-only renderer
    requirement: OPS-01
    verification:
      - kind: unit
        ref: tests/test-memory-runtime-contract.py
        status: pass
    human_judgment: false
  - id: D2
    description: Fail-closed deploy secret and evidence-marker contract
    requirement: ISO-02
    verification:
      - kind: unit
        ref: tests/test-memory-runtime-contract.py
        status: pass
    human_judgment: false
duration: 25 min
completed: 2026-08-19
status: complete
---

# Phase 19 Plan 06: Checked-in Memory Deployment Inputs Summary

Repository-owned manifests now supply the backup endpoint and prefix. CI reuses
only approved S3 secrets and fails closed on unresolved evidence markers.

## Performance

- **Duration:** 25 min
- **Completed:** 2026-08-19T21:36:57Z
- **Tasks:** 2/2
- **Files modified:** 7

## Accomplishments

- Staged the exact top-level memory YAML source set byte-for-byte without
  environment-driven replacements.
- Moved Timeweb endpoint and backup prefix into the CronJob while preserving
  secret-backed bucket and credentials.
- Replaced GitHub memory variables and obsolete backup aliases with direct S3
  secret reuse, secret inventory validation, and offline regression coverage.

## Task Commits

1. **Task 1: Checked-in configuration path** — `74cd501` (`feat`)
2. **Task 2: Fail-closed workflow and validator** — `39fca60` (`feat`)

## Files Created/Modified

- `.github/workflows/deploy-memory.yml` — direct S3 secret inputs and test gate.
- `k8s/memory/40-backup.yaml` — checked-in endpoint and prefix.
- `scripts/render-memory-manifests.py` — byte-preserving copy-only renderer.
- `scripts/render-memory-secrets.py` — approved five-input secret renderer.
- `scripts/validate-memory-manifests.py` — configuration, secret inventory,
  marker-position, and resolved-value checks.
- `tests/test-memory-runtime-contract.py` — synthetic environment and mutation
  regression coverage.
- `docs/solidstats-memory.md` — operator-facing configuration and secret-gate contract.

## Verification Results

- `python3 tests/test-memory-runtime-contract.py` — passed (25 tests).
- `python3 scripts/validate-memory-manifests.py --allow-operator-placeholders`
  — passed.
- `python3 -m py_compile ...` — passed.
- `git diff --check` — passed.
- Strict validation failed as expected before mutation, reporting all eight
  unresolved operator markers.
- `markdownlint-cli2 --fix docs/solidstats-memory.md` — passed with no errors.

## Deviations from Plan

### Plan conflict

**1. [Rule 4 - Ownership boundary] Preserved the existing Qdrant namespace value**

- **Found during:** Task 2
- **Issue:** The plan required `MEMPALACE_QDRANT_NAMESPACE=solidstats_memory`,
  but `20-mempalace.yaml` locks it to `SolidStats` outside this task's files.
- **Resolution:** Kept the existing validated contract; did not modify another
  agent's manifest.
- **Impact:** The rename requires an evidence-backed, separately owned manifest
  change.

## TDD Gate Compliance

RED failures were observed before each implementation, but the task commits
combine test and implementation changes rather than using separate RED/GREEN
commits.

## Known Stubs

None. The eight explicit operator markers are intentional deploy gates, not
runtime stubs.

## Next Phase Readiness

The source gate is ready for an evidence-backed replacement of all eight
markers. `K8S_MEMORY_TOKEN` bootstrap and kube-router enforcement remain
operator-owned gates; no live infrastructure action was performed.

## Self-Check: PASSED

- Summary file exists.
- Task commits `74cd501` and `39fca60` exist in Git history.
