---
phase: 06-kubectl-native-cd
plan: 4
subsystem: infra
tags: [github-actions, kubectl, wireguard, ci-cd, k3s, deploy]

# Dependency graph
requires:
  - phase: 06-kubectl-native-cd (Plan 03)
    provides: wg-tunnel-up.sh and kubeconfig-setup.sh CI helper scripts
  - phase: 06-kubectl-native-cd (Plan 01)
    provides: 01-ci-rbac.yaml operator-bootstrap RBAC and ci-deployer SA token
provides:
  - WireGuard + kubectl-native deploy-staging.yml (validate + dry-run on PR, +deploy on master)
  - Single-deploy concurrency lock (infrastructure-staging-deploy, cancel-in-progress: false)
  - Full removal of the legacy SSH deploy path (scripts/deploy-staging.sh deleted)
affects: [07-production-cutover, staging-deploy-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "kubectl-native CD over WireGuard tunnel (no SSH transport)"
    - "PR=validate+dry-run / master=validate+dry-run+deploy job split"
    - "Fixed-name concurrency group with cancel-in-progress: false for serialized deploys"
    - "find glob excludes operator-managed 01-ci-rbac.yaml from CI apply"

key-files:
  created: []
  modified:
    - .github/workflows/deploy-staging.yml
    - scripts/validate-staging.py
  deleted:
    - scripts/deploy-staging.sh

key-decisions:
  - "Removed scripts/deploy-staging.sh from validate_scripts() so the validate job stops bash -n'ing a deleted file (in-scope deviation)"
  - "Retained REPLAYS_FETCHER_REPLAY_SOURCE_SSH_* env vars in the deploy job — they are application replay-source secrets, not CD transport SSH"

patterns-established:
  - "Pattern 1: CI never applies RBAC — 01-ci-rbac.yaml is excluded from both dry-run and deploy apply globs"
  - "Pattern 2: deploy job gated on master push / workflow_dispatch only; PR forks never reach deploy"

requirements-completed: [CD-01, CD-06, CD-07, CD-08]

# Metrics
duration: 8min
completed: 2026-06-12
status: complete
---

# Phase 06 Plan 4: kubectl-native CD migration Summary

**WireGuard + kubectl-native deploy-staging.yml with PR/master job split and single-deploy concurrency lock; legacy SSH deploy script deleted and dropped from the validator.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-12T (resume session)
- **Completed:** 2026-06-12
- **Tasks:** 2 (Task 1 completed in prior session; Task 2 + 1 deviation completed this session)
- **Files modified:** 2 (1 modified, 1 deleted) this session; 1 (workflow) in prior session

## Accomplishments
- Task 1 (prior session, verified this session): deploy-staging.yml refactored to the three-job WireGuard + kubectl-native structure, fixed concurrency group, no SSH/CD_SSH_* references, 01-ci-rbac.yaml excluded from apply globs, deploy gated on master only.
- Task 2 (this session): scripts/deploy-staging.sh (the legacy SSH-based deploy script using ssh/scp + remote kubectl) deleted from the repository.
- Deviation (this session): validate-staging.py's validate_scripts() no longer references the deleted deploy-staging.sh, so the validate job's script-syntax check passes (`ok: script syntax`).

## Task Commits

1. **Task 1: Refactor deploy-staging.yml (WireGuard + kubectl native)** - `49084be` (feat) — prior session
2. **Task 2 + deviation: Delete SSH deploy script and drop it from validate-staging.py** - `5379709` (feat) — this session

**Plan metadata:** committed with this SUMMARY.

## Files Created/Modified
- `.github/workflows/deploy-staging.yml` - (prior session, verified) WireGuard + kubectl-native CD: validate + dry-run on PR, +deploy on master.
- `scripts/deploy-staging.sh` - DELETED. Legacy SSH/scp + remote-kubectl deploy path, fully replaced by the workflow.
- `scripts/validate-staging.py` - Removed `"scripts/deploy-staging.sh"` from the `validate_scripts()` syntax-check list, leaving only `"scripts/backup-postgres-now.sh"`.

## Decisions Made
- Kept the two `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_*` env vars in the deploy job's secret-render step: these are application secrets for the replay-source connection, not CD transport SSH. They are correct and must remain (confirmed against CD-07 scope).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed deploy-staging.sh from validate-staging.py validate_scripts()**
- **Found during:** Task 2 (Delete scripts/deploy-staging.sh)
- **Issue:** validate-staging.py's `validate_scripts()` ran `bash -n scripts/deploy-staging.sh`. The validate job runs `python3 scripts/validate-staging.py`. Deleting the script without this fix makes the script-syntax check fail on a missing file, breaking the validate step. The plan objective explicitly requires "The validate step must no longer reference the deleted script."
- **Fix:** Changed the loop list in `validate_scripts()` from `["scripts/deploy-staging.sh", "scripts/backup-postgres-now.sh"]` to `["scripts/backup-postgres-now.sh"]`.
- **Files modified:** scripts/validate-staging.py
- **Verification:** `python3 scripts/validate-staging.py` now prints `ok: script syntax` (the script-syntax check passes). Committed atomically with the deletion since they are interdependent.
- **Committed in:** `5379709` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The deviation was explicitly anticipated by the plan objective and is required for the validate step to stay green. No scope creep.

## Issues Encountered

**Pre-existing validator failure (out of scope — deferred):** While running the objective's "`python3 scripts/validate-staging.py` runs without error" check, `validate_manifest_shape()` fails with `error: k8s/staging/01-ci-rbac.yaml document missing apiVersion`. This was confirmed present at the base commit `49084be` (before any change in this session) — it was introduced by plan 06-01 (commit 4667fb1), which added 01-ci-rbac.yaml with a 4-line operator comment block before the first `---`; `split_documents()` treats that comment block as the first document with no apiVersion. Per the scope boundary, this is NOT caused by this task's changes, so it was not fixed — it is logged in `.planning/phases/06-kubectl-native-cd/deferred-items.md` (D-06-01) for a separate plan. The Plan 06-04 deviation is independent and correct: the `script syntax` stage now passes.

## User Setup Required

None - no new external service configuration introduced by this plan. (The deploy/dry-run jobs rely on previously-provisioned `staging` environment secrets: WG_PRIVATE_KEY, WG_PEER_PUBLIC_KEY, WG_ENDPOINT, K8S_TOKEN, K8S_CA_CERT, plus the application secrets.)

## Next Phase Readiness
- All four CD requirements (CD-01 kubectl over WireGuard, CD-06 PR=dry-run/master=deploy, CD-07 SSH removed, CD-08 concurrency lock) are now satisfied by Plans 01-04 combined.
- Blocker for green CI: deferred item D-06-01 (validate-staging.py manifest_shape on 01-ci-rbac.yaml) must be fixed before the validate job passes end-to-end on staging CI. Tracked in deferred-items.md.

## Self-Check: PASSED
- FOUND: commit `5379709` (delete SSH deploy script + validator drop)
- MISSING (intended): `scripts/deploy-staging.sh` correctly no longer exists
- FOUND: `scripts/validate-staging.py` modified; `ok: script syntax` confirmed
- Task 1 acceptance criteria (10/10) re-verified PASS against `.github/workflows/deploy-staging.yml`
- Task 2 acceptance criteria (3/3) PASS

---
*Phase: 06-kubectl-native-cd*
*Completed: 2026-06-12*
