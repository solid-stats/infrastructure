---
phase: quick-260614-tvy
plan: "01"
subsystem: cd-transport
tags: [ssh, tunnel, cd, kubeconfig, wireguard-migration]
status: complete

dependency_graph:
  requires: []
  provides:
    - scripts/ssh-tunnel-up.sh (SSH local-forward gate for CI)
    - scripts/kubeconfig-setup.sh (updated to 127.0.0.1:16443 + tls-server-name)
    - .github/workflows/deploy-staging.yml (SSH tunnel transport)
    - .github/workflows/deploy-observability.yml (SSH tunnel transport)
  affects:
    - scripts/validate-staging.py (adds ssh-tunnel-up.sh to bash -n loop)

tech_stack:
  added: []
  patterns:
    - SSH local-forward (-fN -L) as k3s API transport replacing WireGuard

key_files:
  created:
    - scripts/ssh-tunnel-up.sh
  modified:
    - scripts/kubeconfig-setup.sh
    - .github/workflows/deploy-staging.yml
    - .github/workflows/deploy-observability.yml
    - scripts/validate-staging.py

decisions:
  - SSH local-forward (16443->127.0.0.1:6443) replaces WireGuard (UDP dead on Timeweb hypervisor)
  - tls-server-name=10.8.0.1 required because k3s CA SAN includes 10.8.0.1 not 127.0.0.1
  - WG script + WG_* secrets retained for future restoration
  - ExitOnForwardFailure=yes + poll loop = fail-closed gate matching wg-tunnel-up.sh discipline
  - DEPLOY_SSH_* secrets referenced from existing GitHub staging environment (not created here)

metrics:
  duration: "12m"
  completed: "2026-06-14"
  tasks_completed: 3
  files_changed: 5
---

# Phase quick-260614-tvy Plan 01: Migrate CD from WireGuard to SSH Tunnel — Summary

**One-liner:** SSH local-forward (port 16443) replaces WireGuard as k3s API transport in both CD workflows, with tls-server-name=10.8.0.1 override in kubeconfig to satisfy the k3s CA SAN.

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Create scripts/ssh-tunnel-up.sh | 9bb43f6 | scripts/ssh-tunnel-up.sh (new, executable) |
| 2 | Point kubeconfig-setup.sh at 127.0.0.1:16443 | bd03ecb | scripts/kubeconfig-setup.sh |
| 3 | Swap WG steps in both workflows + update validators | 1bade73 | deploy-staging.yml, deploy-observability.yml, validate-staging.py |

## What Was Done

**Task 1 — ssh-tunnel-up.sh:** New executable bash script mirroring wg-tunnel-up.sh structure exactly. Opens `ssh -fN -L 16443:127.0.0.1:6443` in background with hardened options (ExitOnForwardFailure=yes, StrictHostKeyChecking=yes, host-pinned via temp known_hosts, BatchMode, IdentitiesOnly). Identity and known_hosts written to chmod-600 temp files removed on EXIT. Exits 64 on missing DEPLOY_SSH_* vars. Fail-closed poll loop exits 1 if 127.0.0.1:16443 unreachable within REACHABILITY_TIMEOUT_SECS.

**Task 2 — kubeconfig-setup.sh:** Two targeted changes: default K8S_API_SERVER changed from `https://10.8.0.1:6443` to `https://127.0.0.1:16443`; new `K8S_TLS_SERVER_NAME=10.8.0.1` default added and passed as `--tls-server-name` to `kubectl config set-cluster`. All auth/context/whoami logic untouched; obs workflow's multi-context overrides still work.

**Task 3 — Workflows + validator:** Both deploy-staging.yml (dry-run + deploy jobs) and deploy-observability.yml (deploy job) had their two-step WireGuard sequence replaced with a single "Open SSH tunnel" step using DEPLOY_SSH_* secrets. The validate job in deploy-staging.yml gained a `test -f scripts/ssh-tunnel-up.sh` assertion (wg-tunnel-up.sh assertion retained). validate-staging.py's `validate_scripts()` gained `scripts/ssh-tunnel-up.sh` in its bash -n loop.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment in ssh-tunnel-up.sh triggered StrictHostKeyChecking grep check**
- **Found during:** Task 1 verify
- **Issue:** The comment "NEVER use StrictHostKeyChecking=no or accept-new" contained the literal string `StrictHostKeyChecking=no`, causing `! grep -Eq 'StrictHostKeyChecking[= ](no|accept-new)'` to fail.
- **Fix:** Rephrased comment to "NEVER set StrictHostKeyChecking to no or accept-new"
- **Files modified:** scripts/ssh-tunnel-up.sh
- **Commit:** 9bb43f6

**2. [Rule 1 - Bug] kubeconfig-setup.sh header comment contained "insecure-skip-tls-verify" string**
- **Found during:** Task 2 verify
- **Issue:** Existing comment "Never uses --insecure-skip-tls-verify" caused `! grep -q 'insecure-skip-tls-verify'` to fail.
- **Fix:** Rephrased to "TLS is always verified (no insecure flag)"
- **Files modified:** scripts/kubeconfig-setup.sh
- **Commit:** bd03ecb

**3. [Plan verify self-contradiction noted] `! grep -q 'wg-tunnel-up.sh'` in task 3 verify**
- The plan's verify command includes `! grep -q 'wg-tunnel-up.sh' .github/workflows/deploy-staging.yml` but the done criteria and context explicitly require `test -f scripts/wg-tunnel-up.sh` to remain in the validate job. These are mutually exclusive. The done criteria (authoritative spec) was followed: wg-tunnel-up.sh assertion is retained. The python validator and YAML parse checks pass; the contradictory grep was skipped.

## Verification Results

```
TUNNEL_OK       — bash -n + grep checks on ssh-tunnel-up.sh
KUBECONFIG_OK   — bash -n + grep checks on kubeconfig-setup.sh
YAML_OK         — both workflow YAMLs parse via yaml.safe_load
VALIDATOR_OK    — python3 scripts/validate-staging.py exits 0 (10 checks pass)
```

## Self-Check

- [x] scripts/ssh-tunnel-up.sh exists and is executable
- [x] scripts/kubeconfig-setup.sh modified (K8S_API_SERVER, K8S_TLS_SERVER_NAME, --tls-server-name)
- [x] deploy-staging.yml has 2x "Open SSH tunnel" steps, no wireguard-tools, wg-tunnel-up.sh assert retained
- [x] deploy-observability.yml has 1x "Open SSH tunnel" step, no wireguard-tools
- [x] validate-staging.py includes scripts/ssh-tunnel-up.sh in bash -n loop
- [x] scripts/wg-tunnel-up.sh untouched (retained for WG restoration)
- [x] Commits: 9bb43f6, bd03ecb, 1bade73

## Self-Check: PASSED
