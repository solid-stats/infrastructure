---
phase: 06-kubectl-native-cd
plan: "02"
subsystem: infra
tags: [kubernetes, wireguard, serviceaccount, rotation, runbook, security]

requires:
  - phase: 06-kubectl-native-cd plan 01
    provides: operator-bootstrap.md with initial SA token and WireGuard setup

provides:
  - docs/sa-token-rotation.md — quarterly SA token and WireGuard key rotation runbook with named owner, ordering rule, step-by-step procedures, verification steps, and troubleshooting table

affects:
  - operator runbook reading; CD-09 requirement closure

tech-stack:
  added: []
  patterns:
    - "Rotation ordering: update GitHub secrets before rotating VPS side to prevent mid-window deploy failures"
    - "Runbook structure: overview table → numbered sub-steps with bash blocks → verification → troubleshooting table"

key-files:
  created:
    - docs/sa-token-rotation.md
  modified: []

key-decisions:
  - "Both SA token and WireGuard key rotate in the same maintenance window; split windows create a gap where GitHub holds new credentials the VPS has not yet accepted"
  - "GitHub secrets are updated first (before VPS rotation) so the runner never connects with revoked credentials mid-deploy"

patterns-established:
  - "Runbook: same structure as docs/backup-restore.md and docs/operator-bootstrap.md (intro + overview table + numbered steps with bash blocks + troubleshooting table)"

requirements-completed:
  - CD-09

duration: 2min
completed: "2026-06-12"
status: complete
---

# Phase 6 Plan 02: SA Token and WireGuard Key Rotation Runbook Summary

**Quarterly rotation runbook for CI deployer SA token (K8S_TOKEN) and WireGuard key pair, with explicit GitHub-secrets-first ordering and troubleshooting table (CD-09)**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-12T07:36:34Z
- **Completed:** 2026-06-12T07:38:02Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `docs/sa-token-rotation.md` satisfying all CD-09 requirements: named owner (operator), quarterly cadence, step-by-step SA token rotation, step-by-step WireGuard key pair rotation
- Documented the GitHub-secrets-first ordering rule to prevent mid-rotation deploy failures
- Included verification steps (wg show latest-handshakes, kubectl auth whoami, dry-run pass)
- Troubleshooting table covers all common failure modes with root cause and fix
- Cross-reference to `docs/operator-bootstrap.md` for initial setup context

## Task Commits

1. **Task 1: SA-token and WireGuard key rotation runbook (CD-09)** - `d2d7f73` (docs)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `docs/sa-token-rotation.md` — quarterly rotation runbook: overview table, Step 1 SA token rotation (delete/re-apply/extract/update), Step 2 WireGuard key pair rotation (genkey/pubkey/update-GitHub/syncconf-VPS/verify), Step 3 end-to-end verification, troubleshooting table, cross-reference

## Decisions Made

- Both rotations must happen in the same window to prevent a race where GitHub holds new credentials the VPS rejects (or vice versa)
- GitHub secrets updated first (before VPS rotation) — this is the ordering rule documented prominently at the top of the runbook

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced — documentation only. No threat flags.

## Known Stubs

None — runbook is complete and self-contained; no data sources or wiring required.

## Next Phase Readiness

- CD-09 closed; rotation runbook is production-ready
- Phase 06 Plans 03 and 04 (workflow refactor and deploy scripts) can proceed independently

---
*Phase: 06-kubectl-native-cd*
*Completed: 2026-06-12*
