# Phase 12: Resource Protection & Obs Foundation - Research

**Researched:** 2026-06-13
**Domain:** Kubernetes QoS / PriorityClass / node-pressure eviction / host swap / RBAC bootstrap
**Confidence:** MEDIUM (Kubernetes mechanics from official docs; swap k3s specifics from GitHub issue + community docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Claude's Discretion
Use ROADMAP phase goal, success criteria, and codebase conventions to guide all decisions.

### Deferred Ideas (OUT OF SCOPE)
None — discuss phase skipped. Phase boundary: OOM protection + obs namespace bootstrap only.
Phases 13-18 are out of scope for this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PREP-01 | Operator can re-run a resource preflight that snapshots node CPU/memory/disk and existing allocations before any obs workload is applied. | Script pattern: `kubectl top nodes`, `kubectl describe node`, `df -h`, `free -h` over SSH or local kubectl. See § Resource Preflight. |
| PREP-02 | Host swap (persistent) is configured on the staging node for host-process relief, documented as NOT a substitute for pod memory limits. | Swap mechanics fully researched. See § Host Swap. kubelet drop-in + fstab pattern confirmed. |
| PREP-03 | PriorityClasses (`app-critical` ≫ `obs-background`) exist so the scheduler evicts obs pods before postgres/server-2 under memory pressure. | PriorityClass mechanics + value ranges researched from official k8s docs. See § PriorityClass Design. |
| PREP-04 | The app workloads (postgres, server-2) run at Guaranteed QoS (requests == limits) so they are last to be evicted. | QoS class mechanics researched. Current manifests audited — postgres and server-2 are currently Burstable (cpu limits ≠ requests). See § QoS Audit. |
| PREP-05 | Two namespaces (`monitoring`, `error-tracking`) exist, each with a non-default ServiceAccount and least-privilege RBAC (`obs-ci-deployer`), separate from the runtime `ci-deployer`. | Exact RBAC pattern mirrors existing `01-ci-rbac.yaml`. See § Namespace + RBAC. |
</phase_requirements>

---

## Summary

Phase 12 is a pure infrastructure-hardening phase with no application code changes. It has five independent work streams that can be sequenced as follows: (1) run the preflight snapshot script first to baseline the node; (2) set up host swap as OOM relief for host processes; (3) create PriorityClasses and patch app workload pod specs; (4) pin postgres and server-2 to Guaranteed QoS by equalising cpu requests==limits; (5) create the `monitoring` and `error-tracking` namespaces with `obs-ci-deployer` RBAC.

**Critical finding:** Kubernetes node-pressure eviction orders by PriorityClass value FIRST, then QoS class within the same priority band. This means PriorityClass separation (`app-critical` vs `obs-background`) is the primary protection mechanism, not QoS alone — however QoS still matters for the Linux kernel OOM killer, which ignores PriorityClass entirely and kills BestEffort/Burstable pods first. Both mechanisms are required.

**Critical finding:** Host swap does NOT protect pods on k3s. With `swapBehavior: NoSwap` (the default k3s config and what we will use), pods receive zero swap allocation even when the host has swap configured. Swap benefits only host-OS processes (systemd, kubelet). This is confirmed by k3s issue #12677 and the official Kubernetes swap docs.

**Primary recommendation:** Apply PriorityClasses cluster-wide first, patch all app pod specs with `priorityClassName: app-critical`, then equalise postgres and server-2 cpu requests==limits to achieve Guaranteed QoS. The namespace/RBAC bootstrap is a separate operator-applied file matching the existing `01-ci-rbac.yaml` pattern. Swap and preflight script are pure host-level tasks requiring SSH access.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Resource preflight snapshot | Host OS / operator script | kubectl (remote) | Captures node-level metrics (`free`, `df`, `kubectl top`) — no in-cluster object needed |
| Host swap provisioning | Host OS | kubelet config | fstab + kubelet drop-in are host-level; k3s/kubelet must tolerate swap (`failSwapOn: false`) |
| PriorityClass definition | Kubernetes cluster (non-namespaced) | — | PriorityClass is a cluster-scoped resource; operator applies once |
| Pod priority assignment | Kubernetes workload manifests | CI deploy | `priorityClassName` in pod spec templates; deployed via CI glob |
| QoS class enforcement | Kubernetes workload manifests | CI deploy | Set by equalising requests==limits in container specs |
| Namespace + RBAC bootstrap | Kubernetes cluster (operator-applied) | — | Namespaces and ClusterRoleBindings require cluster-scope; excludes from CI glob per `01-ci-rbac.yaml` precedent |

---

## Standard Stack

No external packages. All work is pure Kubernetes YAML and a Bash preflight script.

| Tool | Version | Purpose |
|------|---------|---------|
| kubectl | existing in CI | Apply manifests, verify QoS, run `auth can-i` checks |
| Bash | existing on VPS | Preflight script, swap provisioning |
| k3s kubelet | existing | Swap `failSwapOn: false` drop-in config |

### No Package Legitimacy Audit Required

This phase installs no external npm/pypi/crates packages. All resources are Kubernetes-native YAML objects and host-level Bash.

---

## Architecture Patterns

### System Architecture Diagram

```
Operator (SSH to VPS)
  │
  ├─► scripts/resource-preflight.sh
  │     └─ kubectl top nodes/pods → snapshot stdout/log
  │         df -h, free -h
  │
  ├─► Host swap provisioning (SSH)
  │     fallocate + mkswap + swapon + /etc/fstab
  │     + kubelet drop-in: /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf
  │       (failSwapOn: false, swapBehavior: NoSwap)
  │
  ├─► kubectl apply  k8s/staging/02-priority-classes.yaml   [cluster-scoped, operator-once]
  │     PriorityClass: app-critical (value: 1000000)
  │     PriorityClass: obs-background (value: 100)
  │
  ├─► kubectl apply  k8s/staging/01-obs-rbac.yaml            [cluster-scoped, operator-once]
  │     Namespace: monitoring
  │     Namespace: error-tracking
  │     ServiceAccount: obs-ci-deployer (in each ns)
  │     Role + RoleBinding: obs-ci-deployer (in each ns)
  │     Secret: obs-ci-deployer-token (in each ns)
  │
  └─► CI deploy (master push) applies workload manifests with patched pod specs:
        10-postgres.yaml    → priorityClassName: app-critical, cpu requests==limits (Guaranteed QoS)
        35-server-2-deployment.yaml → priorityClassName: app-critical, cpu requests==limits
        40-replay-parser-2.yaml     → priorityClassName: app-critical
        50-replays-fetcher.yaml     → priorityClassName: app-critical
        60-postgres-backup.yaml     → priorityClassName: app-critical
        (future obs pods will carry priorityClassName: obs-background)
```

### Recommended Project Structure

```
k8s/staging/
├── 00-namespace.yaml          # existing — solid-stats-staging namespace
├── 01-ci-rbac.yaml            # existing — operator-applied, excluded from CI glob
├── 01-obs-rbac.yaml           # NEW — operator-applied: monitoring + error-tracking ns + obs-ci-deployer RBAC
├── 02-priority-classes.yaml   # NEW — operator-applied: app-critical + obs-background PriorityClasses
├── 10-postgres.yaml           # PATCHED — add priorityClassName: app-critical, equalise cpu req==lim
├── 20-rabbitmq.yaml           # PATCHED — add priorityClassName: app-critical
├── 35-server-2-deployment.yaml # PATCHED — add priorityClassName: app-critical, equalise cpu req==lim
├── 40-replay-parser-2.yaml    # PATCHED — add priorityClassName: app-critical
├── 50-replays-fetcher.yaml    # PATCHED — add priorityClassName: app-critical
├── 60-postgres-backup.yaml    # PATCHED — add priorityClassName: app-critical
scripts/
└── resource-preflight.sh      # NEW — re-runnable snapshot script
```

**File numbering note:** `01-obs-rbac.yaml` uses the same `01-` prefix tier as `01-ci-rbac.yaml` since both are operator-applied bootstrap files excluded from CI. The CI glob already excludes `01-ci-rbac.yaml` by name; `01-obs-rbac.yaml` must be added to the same exclusion. `02-priority-classes.yaml` uses `02-` to apply before any workload (10+) and is also operator-applied.

**Alternative numbering:** Use `05-obs-rbac.yaml` and `06-priority-classes.yaml` if a clean numeric gap is preferred. The planner should pick; this research uses `01-obs-rbac.yaml` / `02-priority-classes.yaml` as the default recommendation.

---

## Kubernetes QoS Classes

[CITED: https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/]

### Guaranteed QoS Requirements

Every container in the pod must satisfy ALL of the following:
- `resources.requests.memory` == `resources.limits.memory` (both non-zero)
- `resources.requests.cpu` == `resources.limits.cpu` (both non-zero)

Init containers also count — they must also satisfy requests==limits if present.

QoS class is immutable after pod creation. To change QoS class, pods must be restarted (rolling update on Deployment/StatefulSet).

### Current QoS Audit of Staging Workloads

| Workload | CPU request | CPU limit | Memory req | Memory lim | Current QoS | Target QoS |
|----------|-------------|-----------|------------|------------|-------------|------------|
| postgres StatefulSet | 250m | 1 (1000m) | 512Mi | 2Gi | **Burstable** | **Guaranteed** (req==lim) |
| server-2 Deployment | 100m | 1 (1000m) | 256Mi | 1Gi | **Burstable** | **Guaranteed** (req==lim) |
| replay-parser-2 Deployment | 250m | 2 (2000m) | 512Mi | 2Gi | **Burstable** | Burstable (ok — not required by PREP-04) |
| replays-fetcher CronJob | 100m | 1 (1000m) | 256Mi | 1Gi | **Burstable** | Burstable (ok) |
| postgres-backup CronJob | 100m | 1 (1000m) | 256Mi | 1Gi | **Burstable** | Burstable (ok) |

**PREP-04 scope:** Only postgres and server-2 must reach Guaranteed QoS. The requirement language is explicit: "postgres and server-2 run at Guaranteed QoS". replay-parser-2, replays-fetcher, and postgres-backup get `priorityClassName: app-critical` but can stay Burstable.

**Required changes for Guaranteed QoS:**
- postgres: set `cpu requests: 1 / cpu limits: 1` (raise request to match limit), OR lower limit to match request. Recommended: lower limit to a safe ceiling that matches request — e.g., `requests.cpu: 500m / limits.cpu: 500m` and `requests.memory: 1Gi / limits.memory: 1Gi`. [ASSUMED: exact values need operator judgment based on live usage; these are conservative examples]
- server-2: similarly e.g. `requests.cpu: 250m / limits.cpu: 250m`, `requests.memory: 512Mi / limits.memory: 512Mi` [ASSUMED: exact values need live usage review]

**Pitfall:** Setting cpu limits == requests too low starves the app. The planner should flag that the operator must check `kubectl top pods` before committing the equalised values.

### Eviction Order Under Memory Pressure

[CITED: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/]

Node pressure eviction (kubelet) selection sequence:
1. Pod priority value (PriorityClass — **lower value evicted first**)
2. QoS class within same priority band (BestEffort → Burstable → Guaranteed)
3. Resource usage relative to request (pods consuming more of starved resource first)

Linux kernel OOM killer (hard memory wall): ignores PriorityClass entirely, uses per-process OOM score. Guaranteed pods (cgroup limits) are better protected but not immune.

**Implication:** Setting `app-critical` (value: 1000000) and `obs-background` (value: 100) means all app pods are evicted AFTER all obs pods during node-pressure eviction, regardless of QoS class. Guaranteed QoS adds a second layer of protection against both kubelet eviction (last in QoS ranking) and kernel OOM (lower oom_score_adj for Guaranteed containers).

---

## PriorityClass Design

[CITED: https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/]

### Recommended Values

```yaml
# k8s/staging/02-priority-classes.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: app-critical
value: 1000000
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Runtime app workloads — evicted after obs-background under node pressure"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: obs-background
value: 100
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: "Observability pods — evicted first under node memory pressure"
```

**Value separation rationale:** 1000000 vs 100 gives a 10000x gap. Any value works as long as `app-critical > obs-background`. System classes (`system-cluster-critical = 2000001000`, `system-node-critical = 2000000000`) are untouched. Do NOT set `globalDefault: true` on either — pods without a priorityClassName (k3s system pods, existing operator bootstrap resources) will get priority 0 which is fine.

**preemptionPolicy:** Use `PreemptLowerPriority` on both so that if a high-priority pod is pending, it can evict lower-priority pods to schedule. This is especially useful if obs pods are using more RAM than expected and an app pod needs to (re-)schedule.

**PriorityClass is cluster-scoped (non-namespaced):** Apply operator-once, exclude from CI glob — same pattern as `01-ci-rbac.yaml` and `00-namespace.yaml`.

### Applying priorityClassName to Existing Workloads

Add `priorityClassName: app-critical` to the pod spec template (`spec.template.spec.priorityClassName`) in each manifest. This field is in the pod template spec, not the Deployment/StatefulSet metadata.

For StatefulSets (postgres): the pod template update triggers a rolling restart. For k3s single-node, this means a brief unavailability during the restart. Plan should note the operator should take a backup before applying.

**Rolling restart on StatefulSet:** `kubectl rollout restart statefulset/postgres -n solid-stats-staging` — but in practice `kubectl apply -f` with the patched manifest triggers the same rolling update since `spec.template.spec.priorityClassName` is in the pod template.

---

## Host Swap

[CITED: https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/]
[LOW: https://github.com/k3s-io/k3s/issues/12677]
[LOW: https://oneuptime.com/blog/post/2026-03-20-k3s-low-resource-environments/view]

### Mechanics

With k3s default kubelet configuration (`failSwapOn: true`), the kubelet refuses to start if any swap is present on the host. To configure swap:

1. **Create and activate persistent swap on the host:**
```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
echo 'vm.swappiness=10' >> /etc/sysctl.d/99-swap.conf
sysctl -p /etc/sysctl.d/99-swap.conf
```

2. **Create kubelet drop-in so k3s kubelet tolerates swap:**
```bash
mkdir -p /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/
cat > /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf << 'EOF'
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
EOF
```

3. **Restart k3s to pick up the kubelet config:**
```bash
systemctl restart k3s
```

**`swapBehavior: NoSwap` (default):** Pods get zero swap allocation. Only host processes (systemd, kubelet, containerd) benefit from the swap. This is exactly what we want — the documentation note PREP-02 requires ("host-process relief only — NOT a substitute for pod memory limits") aligns with this behavior.

**Why 2G swap:** [ASSUMED] The node has 8 GB RAM; 2 GB is a common host-relief swap size. The actual value should be based on the operator's judgment of peak host-process pressure. This is not a hard requirement from the phase spec — any size > 0 satisfies PREP-02.

**Swap size location:** `/swapfile` in root filesystem. [ASSUMED: check available disk space on VPS root partition before choosing size]

### Verification After Setup

```bash
free -h                # shows Swap row with configured size
cat /proc/swaps        # shows /swapfile entry
swapon --show          # alternative, same info
```

k3s restart verification:
```bash
systemctl is-active k3s     # must be "active"
kubectl get nodes            # node must be Ready
```

---

## Namespace + RBAC (PREP-05)

### Pattern: Mirror `01-ci-rbac.yaml`

The existing `01-ci-rbac.yaml` establishes the pattern for operator-applied bootstrap RBAC. The new `01-obs-rbac.yaml` follows the same structure:

- Namespace declarations at top
- ServiceAccount per namespace (`obs-ci-deployer` in `monitoring`, `obs-ci-deployer` in `error-tracking`)
- Long-lived `kubernetes.io/service-account-token` Secret per SA (same pattern as `ci-deployer-token`)
- Role per namespace scoped to the verbs an obs deployer needs
- RoleBinding per namespace

**Key difference from `ci-deployer`:** The obs deployer (`obs-ci-deployer`) deploys into `monitoring` and `error-tracking` — it does NOT need access to `solid-stats-staging`. The runtime `ci-deployer` has no access to `monitoring` or `error-tracking`. These RBAC sets are fully separate.

### Required RBAC Verbs for `obs-ci-deployer`

An obs CI deployer needs to apply Prometheus/Grafana/Loki/GlitchTip manifests. Based on the metric stack (Phase 13: Deployments, StatefulSets, Services, ConfigMaps, Secrets, PVCs, ServiceAccounts, CronJobs) and the existing `ci-deployer` role as template:

```yaml
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services", "configmaps", "secrets", "persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch"]
```

DaemonSets is added (for Grafana Alloy in Phase 15). This is the same verb set as `ci-deployer` plus DaemonSets. Least-privilege: no delete, no cluster-scoped resources, no RBAC self-modification.

### Operator-Bootstrap vs CI boundary

`01-obs-rbac.yaml` and `02-priority-classes.yaml` are **operator-applied once**, NOT in the CI glob. The CI deploy workflow glob must exclude them. Document in the file header (same comment as `01-ci-rbac.yaml`).

The phase plan must include a step to update the CI workflow glob exclusion to also exclude `01-obs-rbac.yaml` and `02-priority-classes.yaml`.

---

## Resource Preflight Script (PREP-01)

### What the Script Must Capture

The script captures a point-in-time snapshot of node and pod resource state:

```bash
#!/usr/bin/env bash
set -euo pipefail
# scripts/resource-preflight.sh
# Re-runnable snapshot of node CPU/memory/disk and existing pod allocations.
# Run before applying any observability workload to record headroom.
#
# Usage: KUBECONFIG=/path/to/kubeconfig bash scripts/resource-preflight.sh
#        (or from operator workstation with WireGuard tunnel up)

: "${NAMESPACE:=solid-stats-staging}"
: "${OUTPUT_DIR:=${PREFLIGHT_OUTPUT_DIR:-/tmp}}"

snapshot_ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="${OUTPUT_DIR}/resource-preflight-${snapshot_ts}.txt"

{
  echo "=== Resource Preflight Snapshot ==="
  echo "timestamp=${snapshot_ts}"
  echo "namespace=${NAMESPACE}"
  echo ""
  echo "--- Node allocatable vs allocated ---"
  kubectl describe node
  echo ""
  echo "--- Node resource usage (live) ---"
  kubectl top nodes || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource usage (live, all namespaces) ---"
  kubectl top pods --all-namespaces || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource requests/limits (namespace) ---"
  kubectl -n "${NAMESPACE}" get pods \
    -o custom-columns='NAME:.metadata.name,QOS:.status.qosClass,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory'
  echo ""
  echo "--- Node disk usage ---"
  df -h
  echo ""
  echo "--- Host memory and swap ---"
  free -h
} | tee "${out_file}"

echo ""
echo "Snapshot written to: ${out_file}"
```

**Note on metrics-server:** k3s ships with metrics-server disabled by default. If `kubectl top` fails, the script degrades gracefully but still captures `kubectl describe node` (which includes allocated requests/limits under "Allocated resources"). [ASSUMED: metrics-server may or may not be running on this k3s install]

**SSH vs local kubectl:** The project uses WireGuard tunnel + kubeconfig for kubectl access. The script requires a valid KUBECONFIG pointed at the cluster. On the VPS itself (SSH), `kubectl` works natively. From CI or operator workstation, the WireGuard tunnel must be up first.

---

## Common Pitfalls

### Pitfall 1: CPU Limit Reduction Causes App Throttling
**What goes wrong:** To achieve Guaranteed QoS, cpu limits are lowered to match requests. If limits are set too low, CFS throttling occurs — the pod's CPU usage is capped even when the node has free CPU.
**Why it happens:** Guaranteed QoS requires requests==limits; the temptation is to lower limits rather than raise requests (raising requests would inflate the allocation accounting).
**How to avoid:** Check actual CPU usage with `kubectl top pods` before setting the Guaranteed limits. Set limits at or above the P95 actual usage, not at the current low-ball request values.
**Warning signs:** `kubectl top pods` shows CPU usage near 0 even under load; application response times increase.

### Pitfall 2: PriorityClass Not Inherited by Existing Running Pods
**What goes wrong:** Adding `priorityClassName: app-critical` to a manifest does NOT change the priority of already-running pods. The change only takes effect after pod restart.
**Why it happens:** Pod spec is immutable for running pods; PriorityClass is set at pod scheduling time.
**How to avoid:** After applying patched manifests, force a rolling restart. `kubectl apply` on the Deployment/StatefulSet will trigger this automatically if the pod template changes. Verify with `kubectl get pod -o jsonpath='{.spec.priorityClassName}'`.
**Warning signs:** Old pods still running after apply with no priority set.

### Pitfall 3: StatefulSet Rolling Restart Causes Brief postgres Unavailability
**What goes wrong:** Patching postgres StatefulSet triggers a rolling restart; single-replica StatefulSet means zero-downtime is not possible.
**Why it happens:** k3s single-node, single-replica postgres.
**How to avoid:** Take a fresh backup before applying the patch (`scripts/backup-postgres-now.sh`). Schedule the apply at a low-traffic window. server-2 has the `wait-for-postgres` initContainer so it will self-heal.
**Warning signs:** server-2 and replay-parser-2 show restart loops / pending during postgres rollout.

### Pitfall 4: k3s kubelet Not Picking Up Drop-in Config
**What goes wrong:** Drop-in at `/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf` is not read by k3s because k3s uses a different kubelet config mechanism in some versions.
**Why it happens:** k3s embeds kubelet and may not respect the `kubelet.conf.d/` drop-in pattern depending on version.
**How to avoid:** After creating the drop-in and restarting k3s, verify with `systemctl status k3s` (must not show "failSwapOn" errors) and `free -h` (swap must be active). Alternative: use `--kubelet-arg=fail-swap-on=false` in `/etc/rancher/k3s/config.yaml` if the drop-in is not picked up.
**Warning signs:** `systemctl status k3s` shows "failed to run Kubelet: ... swap memory is not supported" error.

### Pitfall 5: `01-obs-rbac.yaml` Accidentally Applied by CI
**What goes wrong:** If CI glob includes `01-obs-rbac.yaml`, each deploy overwrites operator-managed bootstrap RBAC. Not dangerous (same content) but violates the bootstrap model.
**Why it happens:** CI uses a glob like `k8s/staging/*.yaml` — the `01-` prefix file gets caught.
**How to avoid:** Explicitly exclude `01-obs-rbac.yaml` and `02-priority-classes.yaml` from the CI deploy glob, same as `01-ci-rbac.yaml`. Update the deploy workflow in the same plan that adds these files.
**Warning signs:** CI deploy logs show `configured` for `01-obs-rbac.yaml`.

### Pitfall 6: globalDefault PriorityClass Changing Existing Pod Priority
**What goes wrong:** If `app-critical` or `obs-background` is set with `globalDefault: true`, all pods without an explicit `priorityClassName` (k3s system pods, kube-system, etc.) inherit that priority.
**Why it happens:** `globalDefault: true` applies retroactively to new pods without a class.
**How to avoid:** Set `globalDefault: false` on both PriorityClasses (as shown in the design). k3s system pods already have `system-cluster-critical` / `system-node-critical` set explicitly so they won't be affected regardless.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Priority-based eviction ordering | Custom admission webhook or scheduler plugin | `PriorityClass` + `priorityClassName` in pod spec | k8s native; scheduler and kubelet both respect it |
| QoS enforcement | Any custom cgroup/process manager | Set `requests == limits` in container spec | k8s assigns QoS class automatically at admission |
| Namespace isolation RBAC | Custom RBAC controller | Role + RoleBinding + non-default SA (k8s native) | Standard k8s RBAC is sufficient for this scope |
| Swap persistence | Systemd unit that creates swap | Standard `/etc/fstab` entry | fstab is the canonical Linux persistence mechanism |
| Resource snapshot | Third-party monitoring tool | Bash script + `kubectl describe node` + `df` + `free` | No external dependency needed; re-runnable on any machine with kubectl |

---

## Runtime State Inventory

> Phase 12 is a greenfield phase for k8s resources (new objects) and a host modification (swap). No rename/refactor is involved. Included here because host state changes are being made.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | No persistent data touched | None |
| Live service config | postgres StatefulSet, server-2 Deployment pod templates will be patched | Rolling restart triggered by manifest update; backup required first |
| OS-registered state | `/etc/fstab` on staging VPS — swap entry added | Persisted across reboots; must verify swap survives `reboot` |
| Secrets/env vars | No secret key renames | None |
| Build artifacts | No build artifacts involved | None |

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | kubectl assertions (imperative bash checks) + `scripts/resource-preflight.sh` |
| Config file | none — validation is a set of kubectl commands |
| Quick run command | see per-task checks below |
| Full suite command | `bash scripts/validate-phase-12.sh` (to be created in Wave 0) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PREP-01 | Preflight script runs and produces output | smoke | `bash scripts/resource-preflight.sh` | ❌ Wave 0 |
| PREP-02 | Swap visible in free -h and /proc/swaps, fstab entry present, k3s running | manual+automated | `ssh root@VPS 'free -h && grep swapfile /proc/swaps && grep swapfile /etc/fstab && systemctl is-active k3s'` | N/A (SSH-only) |
| PREP-03 | PriorityClasses exist with correct values | assertion | `kubectl get priorityclass app-critical obs-background -o jsonpath='{range .items[*]}{.metadata.name}={.value}\n{end}'` | ❌ Wave 0 |
| PREP-03 | App pods carry app-critical priorityClassName | assertion | `kubectl -n solid-stats-staging get pods -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.priorityClassName}\n{end}'` | ❌ Wave 0 |
| PREP-04 | postgres pod has Guaranteed QoS | assertion | `kubectl -n solid-stats-staging get pod postgres-0 -o jsonpath='{.status.qosClass}'` → must be `Guaranteed` | ❌ Wave 0 |
| PREP-04 | server-2 pod has Guaranteed QoS | assertion | `kubectl -n solid-stats-staging get pod -l app.kubernetes.io/name=server-2 -o jsonpath='{.items[0].status.qosClass}'` → must be `Guaranteed` | ❌ Wave 0 |
| PREP-05 | monitoring and error-tracking namespaces exist | assertion | `kubectl get namespace monitoring error-tracking` | ❌ Wave 0 |
| PREP-05 | obs-ci-deployer SA exists in each namespace | assertion | `kubectl -n monitoring get serviceaccount obs-ci-deployer && kubectl -n error-tracking get serviceaccount obs-ci-deployer` | ❌ Wave 0 |
| PREP-05 | obs-ci-deployer can deploy in monitoring ns | assertion | `kubectl auth can-i create deployments --as=system:serviceaccount:monitoring:obs-ci-deployer -n monitoring` | ❌ Wave 0 |
| PREP-05 | obs-ci-deployer CANNOT touch solid-stats-staging | assertion | `kubectl auth can-i get pods --as=system:serviceaccount:monitoring:obs-ci-deployer -n solid-stats-staging` → must be `no` | ❌ Wave 0 |

### Wave 0 Gaps

- [ ] `scripts/validate-phase-12.sh` — wraps all kubectl assertions above into a single re-runnable script, exits 1 on any failure
- [ ] `scripts/resource-preflight.sh` — the preflight snapshot script (covers PREP-01)

### Sampling Rate

- **Per task commit:** Run the relevant assertion commands from the test map manually
- **Per wave merge:** `bash scripts/validate-phase-12.sh`
- **Phase gate:** Full validation suite green before `/gsd-verify-work`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | namespace-scoped Role + RoleBinding, non-default SA, no wildcard verbs |
| V5 Input Validation | no | — |
| V6 Cryptography | no | — |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| obs-ci-deployer SA escaping to solid-stats-staging | Elevation of Privilege | Namespace-scoped Role only; verify with `kubectl auth can-i` cross-namespace |
| Long-lived SA token exposure | Information Disclosure | Token stored in k8s Secret, not in git; same pattern as ci-deployer-token |
| PriorityClass abuse (high-value obs pod blocking app scheduling) | Denial of Service | obs-background value (100) is far below app-critical (1000000); no globalDefault set |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kubectl (operator workstation / CI) | All manifest apply tasks | ✓ | existing in CI via WireGuard path | — |
| SSH access to staging VPS | Swap provisioning (PREP-02) | ✓ | root@89.223.124.200 | — |
| WireGuard tunnel | kubectl from CI/workstation | ✓ | established in Phase 6 | — |
| k3s on staging VPS | All k8s tasks | ✓ | running (verified in Phases 6-11) | — |
| fallocate / mkswap on VPS | Swap provisioning | ✓ (standard Linux) | standard util-linux | dd if=/dev/zero (slower alternative) |

**Missing dependencies with no fallback:** None.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | postgres safe CPU/memory Guaranteed values: `cpu: 500m req/lim`, `memory: 1Gi req/lim` | QoS Audit | Too low → CFS throttle or OOM; too high → wastes allocation. Operator must check `kubectl top` before applying. |
| A2 | server-2 safe Guaranteed values: `cpu: 250m req/lim`, `memory: 512Mi req/lim` | QoS Audit | Same risk as A1. |
| A3 | Swap size: 2G | Host Swap | Node may have insufficient disk space; or 2G may be insufficient for host relief. Operator should check `df -h` first. |
| A4 | metrics-server is not running on this k3s install | Preflight Script | If it IS running, `kubectl top` works live and is more useful. Graceful fallback in script handles both cases. |
| A5 | k3s kubelet drop-in path `/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/` is respected by the installed k3s version | Host Swap | If not respected, fallback is `/etc/rancher/k3s/config.yaml` `kubelet-arg` key. |
| A6 | File numbering: `01-obs-rbac.yaml` and `02-priority-classes.yaml` for operator-applied bootstrap | Project Structure | If `01-` conflicts with existing ordering intent, planner may use `05-`/`06-` instead. |

---

## Open Questions

1. **Exact Guaranteed QoS values for postgres and server-2**
   - What we know: current CPU limits are 1 and 1 (1000m/1000m); current memory limits are 2Gi and 1Gi
   - What's unclear: actual live CPU usage — unknown without `kubectl top` or live metrics
   - Recommendation: plan should include a task "check `kubectl top pods` live and document observed CPU P95 before patching"; the exact values in PREP-04 manifest task should be gated behind that check

2. **k3s version and kubelet drop-in support**
   - What we know: k3s is running; kubelet config drop-in path is the standard pattern
   - What's unclear: exact k3s version installed; some older k3s versions (< 1.28) handle kubelet config differently
   - Recommendation: plan swap provisioning task to include `k3s --version` check and fallback note

3. **CI glob exclusion mechanism**
   - What we know: existing deploy workflow excludes `01-ci-rbac.yaml` and `00-namespace.yaml` explicitly
   - What's unclear: exact glob pattern in `.github/workflows/deploy-staging.yml`
   - Recommendation: read the deploy workflow before finalising the exclusion diff

---

## Code Examples

### PriorityClass Manifest

```yaml
# Source: https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/
# k8s/staging/02-priority-classes.yaml
# Operator-applied bootstrap manifest — DO NOT apply from CI.
# Applied once: kubectl apply -f k8s/staging/02-priority-classes.yaml
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: app-critical
  labels:
    app.kubernetes.io/part-of: solid-stats
value: 1000000
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: >-
  Runtime app workloads (postgres, server-2, replay-parser-2, etc).
  Scheduler evicts obs-background pods first under node memory pressure.
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: obs-background
  labels:
    app.kubernetes.io/part-of: solid-stats
value: 100
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: >-
  Observability workloads (Prometheus, Grafana, Loki, etc).
  Evicted before app-critical pods under node memory pressure.
```

### Adding priorityClassName to Pod Template (server-2 example)

```yaml
# In 35-server-2-deployment.yaml spec.template.spec — add this field:
spec:
  priorityClassName: app-critical   # ADD THIS
  serviceAccountName: server-2
  automountServiceAccountToken: false
  # ... rest unchanged
```

### Guaranteed QoS resources block (postgres example)

```yaml
# In 10-postgres.yaml container resources — change to requests==limits:
resources:
  requests:
    cpu: 500m       # was 250m — set equal to limit
    memory: 1Gi     # was 512Mi — set equal to limit [ASSUMED: verify against live usage]
  limits:
    cpu: 500m       # was 1 — lowered to match request
    memory: 1Gi     # was 2Gi — lowered to match request [ASSUMED: verify against live usage]
```

### obs-ci-deployer RBAC (monitoring namespace, error-tracking is identical)

```yaml
# Source: mirrors k8s/staging/01-ci-rbac.yaml pattern
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: obs-ci-deployer
  namespace: monitoring
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
---
apiVersion: v1
kind: Secret
metadata:
  name: obs-ci-deployer-token
  namespace: monitoring
  annotations:
    kubernetes.io/service-account.name: obs-ci-deployer
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
type: kubernetes.io/service-account-token
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: obs-ci-deployer
  namespace: monitoring
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services", "configmaps", "secrets", "persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: obs-ci-deployer
  namespace: monitoring
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
roleRef:
  kind: Role
  name: obs-ci-deployer
  apiGroup: rbac.authorization.k8s.io
subjects:
  - kind: ServiceAccount
    name: obs-ci-deployer
    namespace: monitoring
```

### kubelet drop-in for swap tolerance

```yaml
# /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf
# Source: https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Swap disabled globally on k8s nodes | `failSwapOn: false` + `swapBehavior: NoSwap` allows host swap without giving pods swap | k8s 1.22 (alpha), 1.28 (beta) | Pods still get zero swap; host processes benefit |
| Priority via Pod annotations | PriorityClass + `priorityClassName` | k8s 1.14 (stable) | Cluster-scoped, auditable, enforced by scheduler |
| QoS as primary eviction signal | PriorityClass is primary; QoS secondary within same priority band | Current | Must set BOTH for full protection |

---

## Sources

### Primary (MEDIUM confidence — official docs)
- [kubernetes.io/docs/concepts/workloads/pods/pod-qos/](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/) — QoS class mechanics and Guaranteed requirements
- [kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/) — PriorityClass design and preemption
- [kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/) — eviction selection order
- [kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/](https://kubernetes.io/docs/concepts/cluster-administration/swap-memory-management/) — official swap position and NoSwap semantics

### Secondary (LOW confidence — community/GitHub)
- [github.com/k3s-io/k3s/issues/12677](https://github.com/k3s-io/k3s/issues/12677) — k3s swap issue: pods cannot use swap even with NodeSwap flags
- [oneuptime.com/blog/post/2026-03-20-k3s-low-resource-environments/view](https://oneuptime.com/blog/post/2026-03-20-k3s-low-resource-environments/view) — kubelet drop-in path for k3s swap config

### Codebase (VERIFIED from repo)
- `k8s/staging/01-ci-rbac.yaml` — baseline RBAC pattern for operator-bootstrap files
- `k8s/staging/10-postgres.yaml` — current postgres resources (cpu 250m/1, memory 512Mi/2Gi = Burstable)
- `k8s/staging/35-server-2-deployment.yaml` — current server-2 resources (cpu 100m/1, memory 256Mi/1Gi = Burstable)
- `k8s/staging/40-replay-parser-2.yaml`, `50-replays-fetcher.yaml`, `60-postgres-backup.yaml` — all Burstable, need priorityClassName only

---

## Metadata

**Confidence breakdown:**
- QoS mechanics: MEDIUM — official k8s docs (kubernetes.io)
- PriorityClass design: MEDIUM — official k8s docs (kubernetes.io)
- Eviction order (PriorityClass primary, QoS secondary): MEDIUM — official k8s docs (kubernetes.io)
- k3s swap drop-in path: LOW — community docs + GitHub issue (not official k3s docs)
- Exact Guaranteed QoS values for postgres/server-2: LOW (ASSUMED) — requires live `kubectl top` check

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (stable Kubernetes mechanics; k3s swap handling may change with k3s releases)
