---
phase: 12-resource-protection-obs-foundation
verified: 2026-06-14T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
notes:
  - "PREP-02 k3s-restart deviation accepted: ROADMAP Success Criterion 2 requires swap visible in free -h / /proc/swaps / fstab (verified live) and does NOT require a k3s restart. The restart clause exists only in the 12-04-PLAN must_haves; the running kubelet already carries failSwapOn=False (k3s v1.35 managed default), so swap is tolerated without restart (live evidence: 64Mi swap in use). The explicit 20-swap.conf drop-in is pre-staged on the node for the next natural restart. Functionally equivalent, restart risk to the in-progress parity baseline deliberately avoided."
---

# Phase 12: Resource Protection & Obs Foundation Verification Report

**Phase Goal:** The staging node is protected against OOM eviction of postgres/server-2 before any observability pod is deployed, and the two observability namespaces with least-privilege RBAC exist as the foundation everything else deploys into.
**Verified:** 2026-06-14T00:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal decomposes into two halves, both verified TRUE in the codebase AND on the live cluster:

1. **OOM protection before any obs pod lands** — PriorityClasses exist (`app-critical` 1000000 ≫ `obs-background` 100), all 7 runtime workloads carry `app-critical`, postgres+server-2 are Guaranteed QoS, host swap provides host-process relief. No obs pod exists yet — protection precedes it, as required.
2. **Two obs namespaces with least-privilege RBAC** — `monitoring` + `error-tracking` exist, each with non-default `obs-ci-deployer` SA + namespace-scoped Role + RoleBinding, provably isolated from `solid-stats-staging` and the runtime `ci-deployer`.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|--------------------|--------|----------|
| 1 | Operator can re-run a resource preflight snapshotting node CPU/memory/disk + existing allocations (PREP-01) | ✓ VERIFIED | `scripts/resource-preflight.sh` (55 lines): `kubectl describe node`, `top nodes`, `top pods --all-namespaces`, per-pod QoS/requests/limits custom-columns, df/free; timestamped `tee` to OUTPUT_DIR. `bash -n` clean. SUMMARY 12-05 records a real live run (node 4 CPU / 7.75Gi, ~2.5Gi free). |
| 2 | Persistent host swap configured (free -h, /proc/swaps, fstab) + documented as host-relief-only, NOT a pod-limit substitute (PREP-02) | ✓ VERIFIED | **First-hand live SSH:** `free -h` Swap 2.0Gi (64Mi in use); `/proc/swaps` `/swapfile` 2097148 active; `/etc/fstab` `/swapfile swap swap defaults 0 0`. `docs/resource-protection.md:14` "Swap is NOT a substitute for pod memory limits", NoSwap + issue #12677. Kubelet `20-swap.conf` drop-in pre-staged on node. See accepted restart deviation in frontmatter notes. |
| 3 | `app-critical` + `obs-background` PriorityClasses exist; app workloads carry `app-critical` so obs pods evict first (PREP-03) | ✓ VERIFIED | `02-priority-classes.yaml`: app-critical=1000000, obs-background=100, both globalDefault:false. All 7 workloads carry `priorityClassName: app-critical` (postgres, rabbitmq, server-2, replay-parser-2, replays-fetcher CronJob, postgres-backup CronJob, **web**). **Live validate-phase-12.sh re-run by verifier: all 5 priorityClassName asserts ok.** |
| 4 | postgres + server-2 run at Guaranteed QoS (requests==limits), confirmed on live pods (PREP-04) | ✓ VERIFIED | postgres: single container cpu/mem 500m/1Gi requests==limits. server-2: main 250m/512Mi + BOTH initContainers (wait-for-postgres, wait-for-rabbitmq) 10m/16Mi requests==limits. **Live: postgres-0 qosClass=Guaranteed, server-2 qosClass=Guaranteed (verifier re-run, exit 0).** |
| 5 | `monitoring` + `error-tracking` namespaces exist, each non-default SA + least-privilege RBAC (`obs-ci-deployer`), separate from runtime `ci-deployer` (PREP-05) | ✓ VERIFIED | `01-obs-rbac.yaml`: both namespaces, `obs-ci-deployer` SA + token Secret + namespace-scoped Role (get/list/watch/create/update/patch on apps/batch/core, read pods; NO delete, NO cluster-scope, NO solid-stats-staging) + RoleBinding ×2. **Live: SAs exist in both ns; obs-ci-deployer CAN create deployments in monitoring; CANNOT get pods in solid-stats-staging (verifier re-run).** |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/resource-preflight.sh` | Re-runnable node/pod snapshot (PREP-01) | ✓ VERIFIED | 55 lines, substantive, fault-tolerant probes (`|| echo` guards — WR-05 fixed), df/free relabelled "host running this script" (WR-06 fixed). |
| `scripts/validate-phase-12.sh` | All-PREP assertion harness | ✓ VERIFIED | 147 lines, asserts PriorityClass values, app priorityClassName (incl. web), postgres/server-2 QoS, namespaces, SAs, positive+negative RBAC. `auth can-i` exit-code swallowed (`|| true`). Live exit 0. |
| `scripts/validate-staging.py` | CI gate extended w/ 2 new scripts | ✓ VERIFIED | Both scripts registered (lines 209-210); full `validate-staging.py` run green (10/10 checks). |
| `k8s/staging/01-obs-rbac.yaml` | Obs namespaces + least-privilege RBAC (PREP-05) | ✓ VERIFIED | 169 lines, 2 ns + 2×(SA+Secret+Role+RoleBinding), no destructive/cluster verbs. |
| `k8s/staging/02-priority-classes.yaml` | app-critical + obs-background (PREP-03) | ✓ VERIFIED | 35 lines, correct values, globalDefault:false, PreemptLowerPriority. |
| `k8s/staging/10-postgres.yaml` | app-critical + Guaranteed QoS (PREP-03/04) | ✓ VERIFIED | priorityClassName + requests==limits; live Guaranteed. |
| `k8s/staging/35-server-2-deployment.yaml` | app-critical + Guaranteed incl. initContainers (PREP-03/04) | ✓ VERIFIED | priorityClassName + requests==limits on all 3 containers; live Guaranteed. |
| `k8s/staging/20,40,50,60-*.yaml` | app-critical (PREP-03) | ✓ VERIFIED | rabbitmq, replay-parser-2, replays-fetcher, postgres-backup all carry app-critical at correct pod-template-spec level. |
| `k8s/staging/37-web-deployment.yaml` | app-critical (CR-01 fix) | ✓ VERIFIED | priorityClassName: app-critical present (line 37) — CR-01 genuinely closed (commit 2603f8c). |
| `docs/resource-protection.md` | Swap runbook + host-relief-only caveat (PREP-02) | ✓ VERIFIED | 198 lines, NoSwap caveat, fstab, kubelet drop-in, fish-safe commands. |
| `.github/workflows/deploy-staging.yml` | CI glob excludes both bootstrap files | ✓ VERIFIED | `! -name '01-obs-rbac.yaml'` + `! -name '02-priority-classes.yaml'` in BOTH dry-run (76-79) and deploy (142-145) steps. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `validate-staging.py` | `resource-preflight.sh` | bash -n registration | ✓ WIRED | line 209 |
| `validate-staging.py` | `validate-phase-12.sh` | bash -n registration | ✓ WIRED | line 210 |
| `01-obs-rbac.yaml` | `deploy-staging.yml` | glob exclusion | ✓ WIRED | both find blocks |
| `02-priority-classes.yaml` | `deploy-staging.yml` | glob exclusion | ✓ WIRED | both find blocks |
| workload manifests | `02-priority-classes.yaml` | priorityClassName ref | ✓ WIRED | all 7 reference app-critical; live PriorityClass exists |
| `validate-phase-12.sh` | live k3s cluster | kubectl assertions over WG | ✓ WIRED | verifier-run live, exit 0 |
| `10-postgres.yaml` | live postgres-0 | apply → Guaranteed QoS | ✓ WIRED | live qosClass=Guaranteed |
| `docs/resource-protection.md` | node `/etc/fstab` | documented swap entry | ✓ WIRED | live fstab entry present |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Both new scripts parse | `bash -n` preflight + validate-phase-12 | both OK | ✓ PASS |
| CI manifest+script gate | `python3 scripts/validate-staging.py` | 10/10 ok, exit 0 | ✓ PASS |
| Live phase validation | `ssh root@VPS bash /tmp/phase12/scripts/validate-phase-12.sh` | "Phase 12 validation PASSED", exit 0 | ✓ PASS |
| Live swap state | `ssh root@VPS free -h / cat /proc/swaps / grep swap /etc/fstab` | 2.0Gi swap active+persisted | ✓ PASS |
| Live QoS | (within validate run) postgres-0 + server-2 qosClass | both Guaranteed | ✓ PASS |
| Live RBAC isolation | (within validate run) obs-ci-deployer can-i | CAN deploy monitoring / CANNOT get pods staging | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PREP-01 | 12-01, 12-05 | Re-runnable resource preflight snapshot | ✓ SATISFIED | resource-preflight.sh substantive + live-run |
| PREP-02 | 12-04 | Persistent host swap, documented host-relief-only | ✓ SATISFIED | live free -h/swaps/fstab + docs caveat (restart deviation accepted) |
| PREP-03 | 12-02, 12-03, 12-05 | PriorityClasses + app pods app-critical | ✓ SATISFIED | manifests + live validate green |
| PREP-04 | 12-03, 12-05 | postgres+server-2 Guaranteed QoS | ✓ SATISFIED | requests==limits incl initContainers; live Guaranteed |
| PREP-05 | 12-02, 12-05 | Obs namespaces + least-privilege RBAC | ✓ SATISFIED | 01-obs-rbac.yaml + live RBAC can-i |

**Tracking-doc note (non-blocking):** `.planning/REQUIREMENTS.md` still lists PREP-02 as `[ ] Pending` (lines 15, 103) while the other four are `Complete`. This is a stale tracking checkbox — the requirement is functionally satisfied per live evidence above. Recommend the orchestrator flip PREP-02 to Complete when bundling phase artifacts. Does not affect goal achievement.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `37-web-deployment.yaml` | 44 | `PLACEHOLDER` (pause image) | ℹ️ Info | Pre-existing Phase 9 WEB-02 stub (replicas:0, inert image never pulled). NOT a Phase 12 artifact — Phase 12 only added the priorityClassName line. Intentional, documented design. |
| `10-postgres.yaml` / `35-server-2-deployment.yaml` | 78-86 / 90-99 | "ASSUMED — verify vs live P95" comments | ℹ️ Info | Stale planning comments. SUMMARY 12-05 confirms values were validated against live kubectl top (postgres ~225Mi/1Gi, server-2 ~70Mi/512Mi) and kept. Comment cleanup is cosmetic; values are correct + applied. |

**Debt-marker gate:** CLEAN. No unreferenced `TBD`/`FIXME`/`XXX` in any of the 14 phase-modified files.

### Code-Review Disposition (12-REVIEW.md)

| Finding | Verifier disposition |
|---------|---------------------|
| CR-01 (web no priorityClassName) — CRITICAL | ✓ FIXED in code (line 37) + validate loop (lines 73-75) + commit 2603f8c. Re-verified live. |
| WR-05 (preflight abort) / WR-06 (df/free local) | ✓ FIXED — `|| echo` guards + relabelled headers. |
| WR-01 (rabbitmq Burstable, not Guaranteed) | ℹ️ ACCEPTED — within contract. ROADMAP SC4 + PREP-04 require Guaranteed only for postgres+server-2; SC3 requires rabbitmq to carry app-critical (it does). rabbitmq Burstable is consistent with live SUMMARY evidence and the phase contract. Not a gap. |
| WR-02 (`.items[0]` flaky during rollout) | ℹ️ Open robustness nit — single-replica server-2; validation passed live. Not goal-blocking. Candidate for a future hardening pass. |
| WR-03 (postgres-backup missing capabilities drop) / WR-04 (heredoc) / IN-01..04 | ℹ️ Pre-existing / cosmetic — outside Phase 12 PREP contract. validate-staging.py workload-safety gate passes. |

### Human Verification Required

None. All five ROADMAP success criteria are configuration/state assertions, every one verified first-hand by the verifier against both the codebase and the live cluster (validate-phase-12.sh re-run + direct SSH swap/QoS/RBAC checks). The only behavior not programmatically exercised is real-memory-pressure eviction ordering, which (a) is not a success criterion, (b) cannot be tested without inducing OOM on the live single node, and (c) has no obs pods to evict yet — this is the foundation phase that precedes them. The eviction *mechanism* (PriorityClass values + Guaranteed QoS) is correctly configured and live-applied.

### Gaps Summary

No gaps. The phase goal is achieved on both halves: (1) OOM protection — PriorityClass separation (1000000 vs 100), Guaranteed QoS on postgres+server-2, app-critical on all 7 runtime workloads including the previously-missed `web` (CR-01 closed), plus host swap for process relief — is in place before any observability pod is deployed; (2) the `monitoring` and `error-tracking` namespaces exist with non-default `obs-ci-deployer` least-privilege RBAC provably isolated from the runtime namespace. The one accepted deviation (k3s not restarted for swap) is functionally equivalent — the running kubelet already tolerates swap (live: 64Mi in use) and the explicit drop-in is pre-staged — and does not contradict ROADMAP Success Criterion 2, which never required a restart.

---

_Verified: 2026-06-14T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
