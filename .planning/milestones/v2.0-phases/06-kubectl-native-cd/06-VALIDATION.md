---
phase: 6
slug: kubectl-native-cd
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-12
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> This is an infrastructure phase — there is no unit-test framework. Validation is
> empirical: shell-script self-checks, `kubectl --dry-run=server`, `kubectl auth`
> probes, and a small number of operator-run manual checks.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | none — infra phase; validation via shell + kubectl + CI logs |
| **Config file** | none |
| **Quick run command** | `bash scripts/validate-staging.sh` (manifest/file presence) |
| **Full suite command** | CI `deploy-staging.yml` PR path: `kubectl apply --dry-run=server` over the tunnel |
| **Estimated runtime** | ~30–90 seconds (tunnel bring-up + dry-run) |

---

## Sampling Rate

- **After every task commit:** Run the relevant script with `bash -n` (syntax) and any local dry-run that does not need the live cluster.
- **After every plan wave:** Re-run the validate workflow / dry-run path.
- **Before `/gsd-verify-work`:** PR-path dry-run must succeed and `kubectl auth whoami` must report a non-anonymous SA.
- **Max feedback latency:** ~90 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 6-01-01 | 01 | 1 | CD-03 | T-6-01 | Deploy aborts if WG handshake absent (fail-closed) | script | `wg show wg0 latest-handshakes` parse + nonzero exit | ❌ W0 | ⬜ pending |
| 6-01-02 | — | — | CD-02 | T-6-02 | CI authenticates as namespaced SA, not anonymous | cli | `kubectl auth whoami` ≠ `system:anonymous` | ❌ W0 | ⬜ pending |
| 6-01-03 | — | — | CD-04 | T-6-03 | SA can apply + rollout status namespaced, nothing cluster-scoped | cli | `kubectl auth can-i --list -n solid-stats-staging` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — final map is filled by the planner per PLAN.md.*

---

## Wave 0 Requirements

- [ ] A reachable k3s API over the tunnel (operator-bootstrapped SAN + namespace + SA + token Secret) — prerequisite, not built by CI.
- [ ] `wireguard-tools` installable on the runner (`apt-get install wireguard-tools`).

*Most verification here is behavioral against the live tunnel/cluster, not a local test framework.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Operator bootstrap runbook is correct & sufficient | CD-04 | One-time operator action on the VPS; not CI-reproducible | Operator follows docs runbook on a fresh namespace, confirms SA token + RBAC created |
| k3s API serving cert carries `10.8.0.1` SAN | CD-01 | Requires editing k3s config + restart on the VPS | `openssl s_client -connect 10.8.0.1:6443` shows SAN, or kubectl TLS verify succeeds |
| 51820/udp egress from GitHub-hosted runner | CD-03 | Depends on GitHub network egress + VPS firewall | First CI run completes a WG handshake within timeout |
| SA-token / WG-key rotation runbook is followed | CD-09 | Organizational cadence, not automatable here | Runbook documents owner + cadence + paired rotation |

---

## Validation Sign-Off

- [ ] Every success criterion maps to a script self-check, a kubectl probe, or a documented manual check
- [ ] WG handshake gate proven fail-closed (no kubectl runs without a fresh handshake)
- [ ] `kubectl auth whoami` proves non-anonymous SA on PR path
- [ ] `auth can-i --list` proves namespaced-only authorization
- [ ] `nyquist_compliant: true` set once the per-task map is finalized by the planner

**Approval:** pending
