---
phase: 12
slug: resource-protection-obs-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Infra phase: "tests" are kubectl assertions, host SSH checks, and RBAC can-i probes — not a unit test framework.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | kubectl assertions (imperative bash) + `scripts/resource-preflight.sh` |
| **Config file** | none — validation is a set of kubectl/SSH commands |
| **Quick run command** | per-task assertion commands (see map below) |
| **Full suite command** | `bash scripts/validate-phase-12.sh` (created in Wave 0) |
| **Estimated runtime** | ~20 seconds (remote kubectl over SSH) |

---

## Sampling Rate

- **After every task commit:** Run the relevant assertion command(s) for that task
- **After every plan wave:** Run `bash scripts/validate-phase-12.sh`
- **Before `/gsd-verify-work`:** Full suite must exit 0
- **Max feedback latency:** ~20 seconds

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| PREP-01 | Preflight script runs and snapshots node CPU/mem/disk + allocations | smoke | `bash scripts/resource-preflight.sh` | ❌ W0 | ⬜ pending |
| PREP-02 | Swap visible + persisted + k3s healthy | manual+auto | `ssh root@VPS 'free -h && grep swapfile /proc/swaps && grep swap /etc/fstab && systemctl is-active k3s'` | N/A (SSH) | ⬜ pending |
| PREP-03 | PriorityClasses exist with correct values | assertion | `kubectl get priorityclass app-critical obs-background` | ❌ W0 | ⬜ pending |
| PREP-03 | App pods carry `app-critical` priorityClassName | assertion | `kubectl -n solid-stats-staging get pods -o jsonpath='{range .items[*]}{.spec.priorityClassName}{"\n"}{end}'` | ❌ W0 | ⬜ pending |
| PREP-04 | postgres pod has Guaranteed QoS | assertion | `kubectl -n solid-stats-staging get pod postgres-0 -o jsonpath='{.status.qosClass}'` → `Guaranteed` | ❌ W0 | ⬜ pending |
| PREP-04 | server-2 pod has Guaranteed QoS | assertion | `kubectl -n solid-stats-staging get pod -l app.kubernetes.io/name=server-2 -o jsonpath='{.items[0].status.qosClass}'` → `Guaranteed` | ❌ W0 | ⬜ pending |
| PREP-05 | `monitoring` + `error-tracking` namespaces exist | assertion | `kubectl get namespace monitoring error-tracking` | ❌ W0 | ⬜ pending |
| PREP-05 | `obs-ci-deployer` SA exists in each ns | assertion | `kubectl -n monitoring get sa obs-ci-deployer && kubectl -n error-tracking get sa obs-ci-deployer` | ❌ W0 | ⬜ pending |
| PREP-05 | obs-ci-deployer CAN deploy in its ns | assertion | `kubectl auth can-i create deployments --as=system:serviceaccount:monitoring:obs-ci-deployer -n monitoring` → `yes` | ❌ W0 | ⬜ pending |
| PREP-05 | obs-ci-deployer CANNOT touch runtime ns | assertion | `kubectl auth can-i get pods --as=system:serviceaccount:monitoring:obs-ci-deployer -n solid-stats-staging` → `no` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/resource-preflight.sh` — re-runnable node snapshot (covers PREP-01)
- [ ] `scripts/validate-phase-12.sh` — wraps all kubectl assertions above, exits 1 on any failure

*These are the validation harness, created before/alongside the manifest work.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Swap persists across reboot | PREP-02 | Reboot of live staging VPS is operator-gated, not automatable in CI | After fstab entry added: `ssh root@VPS 'swapon --show && grep swap /etc/fstab'`; full reboot test deferred to operator discretion |
| QoS confirmed on live pods | PREP-04 | Requires live cluster + a rollout that may briefly restart postgres/server-2 | Operator runs the QoS assertions post-rollout against live pods |

*Pod-restart side effects of the QoS change are operator-gated (brief downtime on postgres/server-2 restart).*

---

## Validation Sign-Off

- [ ] All requirements have an `<automated>` assertion or a documented manual check
- [ ] Sampling continuity: no requirement left without a verify command
- [ ] Wave 0 creates `resource-preflight.sh` and `validate-phase-12.sh`
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter once plans wire all checks

**Approval:** pending
