---
phase: 06-kubectl-native-cd
plan: 3
subsystem: infra
tags: [wireguard, kubernetes, kubectl, bash, ci-cd, k3s, github-actions]

requires:
  - phase: 06-kubectl-native-cd/06-01
    provides: operator-bootstrap runbook with GitHub secret names, tunnel IP 10.8.0.1, API port 6443
  - phase: 06-kubectl-native-cd/06-02
    provides: SA token and WireGuard key rotation runbook context

provides:
  - scripts/wg-tunnel-up.sh — fail-closed WireGuard handshake gate for CI runners
  - scripts/kubeconfig-setup.sh — kubeconfig construction from SA token + CA cert with auth verification

affects:
  - 06-04 (deploy workflow refactor calls both scripts as steps)

tech-stack:
  added: []
  patterns:
    - "Fail-closed handshake gate: poll wg show latest-handshakes for non-zero epoch, exit 1 on timeout"
    - "exit 64 for missing required config (per AGENTS.md), exit 1 for runtime failures"
    - "Process substitution <(printf '%s' $VAR) for WireGuard private key — never written to disk"
    - "mktemp + trap 'rm -f' EXIT for temp CA cert file"
    - "kubectl config set-* subcommands (no YAML templating) for kubeconfig construction"

key-files:
  created:
    - scripts/wg-tunnel-up.sh
    - scripts/kubeconfig-setup.sh
  modified: []

key-decisions:
  - "Non-zero epoch detection uses grep -qP '\\t[1-9][0-9]*$' — avoids false positive from zero timestamp that a naive digit check would pass"
  - "WG_PRIVATE_KEY passed via <(printf '%s' ...) process substitution — key never touches disk"
  - "kubectl auth whoami output captured and checked for system:anonymous string before any deploy kubectl runs"
  - "Required vars validated with explicit [[ -z ]] + exit 64 rather than :? expansion (which exits 1 not 64)"

requirements-completed: [CD-01, CD-02, CD-03]

duration: 5min
completed: 2026-06-12
status: complete
---

# Phase 6 Plan 3: CI Helper Scripts (WireGuard gate + kubeconfig) Summary

**Fail-closed WireGuard handshake gate and SA-token kubeconfig builder — two bash scripts enabling kubectl-native CD over WireGuard tunnel with non-zero epoch detection and system:anonymous guard**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-12T07:43:00Z
- **Completed:** 2026-06-12T07:44:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `scripts/wg-tunnel-up.sh`: brings up WireGuard interface wg0, polls `wg show latest-handshakes` for non-zero epoch, exits 1 on timeout (fail-closed gate per CD-03), verifies TCP reachability of 10.8.0.1:6443 via `/dev/tcp` before returning 0
- `scripts/kubeconfig-setup.sh`: builds kubeconfig targeting `https://10.8.0.1:6443` via `kubectl config set-*`, writes CA to mktemp with trap cleanup, verifies `kubectl auth whoami` is not `system:anonymous` (exits 1 if so), never uses `--insecure-skip-tls-verify`
- Both scripts follow project bash conventions: `#!/usr/bin/env bash`, `set -euo pipefail`, exit 64 for missing config, pass `bash -n`

## Task Commits

1. **Task 1: WireGuard handshake gate script** — `a8be0f5` (feat)
2. **Task 2: Kubeconfig construction script** — `1663ccc` (feat)

## Files Created/Modified

- `scripts/wg-tunnel-up.sh` — WireGuard bring-up + fail-closed handshake gate + TCP API reachability check
- `scripts/kubeconfig-setup.sh` — kubeconfig from SA token + CA, system:anonymous auth check

## Decisions Made

- Non-zero epoch detection: `grep -qP '\t[1-9][0-9]*$'` on `wg show latest-handshakes` output — more precise than a naive digit check which would match the zero timestamp `0` that appears before any handshake occurs.
- Private key via process substitution: `<(printf '%s' "$WG_PRIVATE_KEY")` keeps the key in memory only, never written to a temp file on disk (addresses T-6-03-03).
- Explicit `[[ -z ]]` + `exit 64` for required vars rather than `:?` expansion — `:?` exits with code 1, but AGENTS.md requires exit 64 for missing configuration.
- `kubectl auth whoami` output captured to variable then grepped — avoids the case where the command succeeds but returns anonymous identity silently.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required for script creation. Scripts are called from the deploy workflow (Plan 04) with secrets injected from GitHub environment.

## Next Phase Readiness

- Both scripts are ready to be called from the refactored `.github/workflows/deploy-staging.yml` (Plan 04).
- Plan 04 must call `wg-tunnel-up.sh` before any kubectl step and `kubeconfig-setup.sh` immediately after tunnel confirmation.
- No blockers.

## Self-Check

- [x] `scripts/wg-tunnel-up.sh` exists and passes `bash -n`
- [x] `scripts/kubeconfig-setup.sh` exists and passes `bash -n`
- [x] Both commits exist: `a8be0f5`, `1663ccc`
- [x] `exit 64` present in both scripts
- [x] `latest-handshakes` in wg-tunnel-up.sh
- [x] `system:anonymous` in kubeconfig-setup.sh
- [x] No `insecure-skip-tls-verify` in functional code of kubeconfig-setup.sh

---
*Phase: 06-kubectl-native-cd*
*Completed: 2026-06-12*
