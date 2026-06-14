# Phase 17: Network Isolation & Stack Validation - Research

**Researched:** 2026-06-14
**Domain:** Kubernetes NetworkPolicy (k3s/kube-router), validation scripting
**Confidence:** MEDIUM (architecture HIGH; host-node traffic behavior MEDIUM with empirical-proof required)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
Implementation choices are at Claude's discretion, guided by the live stack as it actually runs (Phases 12–16 all deployed) and the constraints below.

### Live Constraints That MUST Be Honored
1. k3s enforces NetworkPolicy via the bundled kube-router netpol controller (flannel CNI). NET-01 still requires an empirical enforcement check (apply a deny + prove a blocked connection) BEFORE any default-deny is relied on.
2. The public edge is host nginx on the NODE, proxying to in-cluster ClusterIPs: `grafana.solid-stats.ru` → grafana (monitoring, 3000) and `errors.solid-stats.ru` → glitchtip-web (error-tracking, 8000). A default-deny ingress on those namespaces MUST keep an allow rule for the edge/host source, or both public URLs break.
3. Prometheus (monitoring) scrapes cross-namespace into `solid-stats-staging`: rabbitmq :15692 and postgres :5432 (via postgres-exporter). Default-deny egress on monitoring needs an allow-prometheus-scrape egress rule to `solid-stats-staging`. Do NOT add a default-deny ingress policy onto `solid-stats-staging` pods.
4. DNS egress (to kube-system kube-dns/coredns :53 udp/tcp) must be allowed in every default-deny egress policy.
5. Intra-namespace flows to preserve: monitoring — prometheus↔grafana, prometheus scrapes kube-state-metrics/node-exporter/loki/alloy, alloy→loki, grafana→prometheus+loki. error-tracking — web↔glitchtip-postgres, worker↔glitchtip-postgres.
6. node-exporter runs with hostNetwork/hostPID — its scrape path is host-level; verify the netpol does not silently drop it.
7. GlitchTip does NOT expose prometheus metrics (ENABLE_OBSERVABILITY_API off) → no cross-ns scrape into error-tracking is needed.

### Validation Script (VAL-01)
One re-runnable `scripts/validate-stack.sh` that fails loudly, composing the existing per-phase harnesses rather than duplicating them. Must run green BOTH before and after the NetworkPolicies are applied.

### Claude's Discretion
All implementation choices (YAML structure, ordering, exact selector shapes, script composition pattern).

### Deferred Ideas (OUT OF SCOPE)
- Default-deny / micro-segmentation of `solid-stats-staging`
- mTLS / service mesh
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NET-01 | Confirm NetworkPolicy enforcement under k3s/kube-router BEFORE applying default-deny | §NET-01 enforcement proof protocol |
| NET-02 | Default-deny + minimal-allow isolating monitoring + error-tracking namespaces | §Architecture Patterns, §NetworkPolicy Skeletons |
| VAL-01 | One re-runnable `scripts/validate-stack.sh` composing existing harnesses | §VAL-01 script design |
</phase_requirements>

---

## Summary

Phase 17 adds NetworkPolicies to the two obs namespaces (`monitoring`, `error-tracking`) after all scraping and datasources have been validated, then unifies the per-phase validation scripts into a single re-runnable `scripts/validate-stack.sh`. No new workloads are deployed; only YAML manifests and one shell script are created.

k3s bundles kube-router's netpol controller library as its NetworkPolicy enforcement engine. Enforcement is implemented via iptables `KUBE-NWPLCY*` chains; it can be confirmed by inspecting these chains or by a test deny + blocked-curl probe. The most important live constraint is that host nginx on the node proxies to pod ClusterIPs — the source IP seen by the pod is the **node's IP** (89.223.124.200), not a pod-CIDR address. Therefore every ingress allow for grafana and glitchtip-web must include an `ipBlock: cidr: <NODE_IP>/32` rule, not just a podSelector.

node-exporter runs with `hostNetwork: true` and `hostPID: true`, so its network namespace is the host network namespace. When Prometheus scrapes the node-exporter ClusterIP (port 9100), the scrape endpoint resolves via kube-proxy DNAT to the host's own loopback/interface. Because node-exporter is in the host network namespace, kube-router NetworkPolicy rules (which operate at the CNI/overlay layer) do NOT intercept host-network pod traffic — it is effectively invisible to netpol. No NetworkPolicy is needed for node-exporter scrape traffic; it already bypasses the filtering layer.

The `kubernetes.io/metadata.name` label is automatically applied to all namespaces on Kubernetes ≥1.21 (GA). k3s ≥v1.24 (which this cluster runs) has this label on all namespaces; `namespaceSelector: matchLabels: kubernetes.io/metadata.name: <ns>` works without any manual labeling.

**Primary recommendation:** Apply NetworkPolicies in additive layers — default-deny first, then explicit allows — and prove enforcement with a canary deny BEFORE the real policies land. Use `ipBlock: cidr: <NODE_IP>/32` to allow host nginx ingress to grafana and glitchtip-web.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| NetworkPolicy enforcement | k3s control plane (kube-router iptables) | node kernel netfilter | Policies are Kubernetes objects; kube-router translates them to iptables chains |
| Public → pod ingress (grafana, glitchtip) | Host nginx (node process) → ClusterIP | kube-proxy DNAT | nginx is not a pod; it hits the ClusterIP which kube-proxy DNATs to pod IP |
| Prometheus → cross-ns scrape (rabbitmq, postgres-exporter) | monitoring ns (egress) → solid-stats-staging (no ingress policy) | — | Allow is on the Prometheus egress side only; app ns stays unrestricted |
| DNS resolution (all pods) | kube-system coredns | — | Every egress policy must explicitly allow UDP+TCP :53 to kube-dns |
| node-exporter scrape path | Host network namespace (bypasses CNI netpol) | — | hostNetwork pods are in the host netns; kube-router iptables rules operate per-pod-netns |
| Intra-ns pod↔pod (monitoring) | monitoring namespace | — | podSelector rules; no cross-ns needed for intra-monitoring flows |
| GlitchTip intra-ns (web/worker ↔ postgres) | error-tracking namespace | — | All in same ns; podSelector rules only |
| validate-stack.sh | operator workstation (kubectl access) | CI (with tunnel) | Script calls kubectl exec + curl + port-forward; requires WireGuard tunnel |

---

## Standard Stack

No new packages are introduced. All tooling is already present in the cluster:
- Kubernetes NetworkPolicy v1 API (built-in, no CRDs)
- kube-router netpol controller (embedded in k3s, no separate install)
- bash + kubectl + python3 (already used in existing validate scripts)
- curl (already used in existing validate scripts)

---

## Package Legitimacy Audit

No external packages are installed in this phase. All NetworkPolicy YAML uses built-in Kubernetes API objects. No `Package Legitimacy Audit` is required.

---

## Architecture Patterns

### NET-01 Enforcement Proof Protocol

**What:** Empirically confirm that kube-router is enforcing NetworkPolicies before applying any production default-deny. A failed probe proves enforcement works; a passed probe reveals that enforcement is absent (wrong CNI, disabled controller, etc.).

**Sequence (operator-run before anything else):**

1. Apply a throwaway `deny-all` NetworkPolicy in a test namespace:
```yaml
# k8s/staging/17-netpol-enforcement-test.yaml (THROWAWAY — delete after probe)
apiVersion: v1
kind: Namespace
metadata:
  name: netpol-probe
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: netpol-probe
spec:
  podSelector: {}
  policyTypes: [Ingress]
```

2. Spin up a minimal target pod in `netpol-probe` namespace:
```bash
kubectl run probe-target --image=nginx:alpine -n netpol-probe --restart=Never
kubectl wait --for=condition=Ready pod/probe-target -n netpol-probe --timeout=60s
```

3. Try to reach it from another pod (should fail if netpol is enforced):
```bash
kubectl run probe-client --image=curlimages/curl -n default --restart=Never \
  --command -- curl -s --max-time 5 http://$(kubectl get pod probe-target -n netpol-probe -o jsonpath='{.status.podIP}'):80
kubectl wait --for=condition=complete pod/probe-client -n default --timeout=30s || \
  kubectl wait --for=condition=failed pod/probe-client -n default --timeout=30s
# Expected: connection refused / timeout (netpol is blocking)
```

4. Confirm `KUBE-NWPLCY` iptables chains exist (requires node SSH):
```bash
# On node:
iptables -L | grep KUBE-NWPLCY | head -5
```

5. Cleanup:
```bash
kubectl delete ns netpol-probe
kubectl delete pod probe-client -n default --ignore-not-found
```

**Pass criterion:** The curl from `probe-client` to `probe-target` times out or fails with connection refused, AND `iptables -L | grep KUBE-NWPLCY` shows active chains.
**Fail criterion (blocking):** curl succeeds. This means NetworkPolicy is NOT enforced — do not apply default-deny policies. Escalate: check `k3s server --disable-network-policy` was not set; verify kube-router logs with `kubectl logs -n kube-system -l k8s-app=kube-router`.

### NET-02 Policy Structure

**Pattern: Default-deny base + additive allow layers**

Apply policies in this order per namespace:
1. `allow-dns-egress` — DNS traffic to kube-system coredns (must be first, or everything breaks)
2. `default-deny-ingress` — block all ingress (empty podSelector + empty ingress)
3. `default-deny-egress` — block all egress (empty podSelector + empty egress)
4. Specific `allow-*` policies for each required flow

**Why additive not combined:** Separate policies for each flow make it easy to add/remove specific rules without touching the deny base. The k8s NetworkPolicy union semantics mean "if ANY policy allows, allow" — so multiple allow-policies combine correctly.

### NetworkPolicy File Layout

All NetworkPolicies live under `k8s/observability/` (CI-deployable, namespace-scoped). They are part of the obs deploy workflow:

```
k8s/observability/
├── 95-netpol-monitoring.yaml        # All monitoring ns NetworkPolicies
└── 96-netpol-error-tracking.yaml   # All error-tracking ns NetworkPolicies
```

Numbering after `93-glitchtip-seed.yaml`; two files (one per namespace). Each file is a multi-document YAML containing all policies for that namespace.

### validate-obs-manifests.py: NetworkPolicy awareness

The static validator does NOT currently check NetworkPolicy resources (they have no priorityClassName, namespace allowed set already covers them). No change needed to `validate-obs-manifests.py` — NetworkPolicy is a namespace-scoped resource with correct namespace, no pod spec, no secrets. It passes all existing checks already.

---

## NetworkPolicy Skeletons

### Critical: How Host Nginx Traffic Reaches Pods [MEDIUM confidence — requires NET-01 verification]

When the node's nginx process (not a pod) does `proxy_pass http://GRAFANA_CLUSTERIP:3000/`:

1. nginx opens a TCP connection to the ClusterIP (e.g., `10.43.x.y:3000`)
2. kube-proxy's iptables DNAT rules (in `PREROUTING`/`OUTPUT` chains) translate ClusterIP → actual pod IP
3. The packet arrives at the grafana pod with **source IP = node's real IP** (89.223.124.200, or the flannel/wireguard internal IP if behind NAT)
4. kube-router's ingress NetworkPolicy on the pod sees: `src=89.223.124.200, dst=<pod-ip>:3000`
5. A default-deny ingress policy WILL block this unless an `ipBlock: cidr: 89.223.124.200/32` allow rule is present

**Action required (NET-01 check):** During the enforcement proof, also test whether host-process curl to a ClusterIP in the `netpol-probe` namespace is blocked by the deny-all policy. If blocked → node IP allow rule required (expected behavior). If not blocked → kube-router may have an implicit LOCAL allow (use the verify step to confirm, but still add the ipBlock for safety).

**Recommended ipBlock:** Use the node's external IP (`89.223.124.200/32`). If the flannel interface IP is different (e.g., `10.42.0.0/1` or a WireGuard IP), also check which source IP the pod actually sees. The safest approach: allow the node's primary public IP AND the pod CIDR (`10.42.0.0/16`) in the ipBlock — the pod CIDR covers any flannel-internal NAT. [ASSUMED — verify during NET-01]

### 95-netpol-monitoring.yaml skeleton

```yaml
# ---------------------------------------------------------------
# monitoring namespace — NetworkPolicies
# Applied via deploy-observability.yml (obs-ci-deployer).
# NET-02: default-deny + minimal-allow.
# ---------------------------------------------------------------

# 1. Allow DNS egress (must apply before deny-all-egress)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
      to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
---
# 2. Default deny all ingress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes: [Ingress]
---
# 3. Default deny all egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes: [Egress]
---
# 4. Allow Grafana ingress from host nginx (node IP) and from Prometheus (intra-ns)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-grafana-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes: [Ingress]
  ingress:
    # Host nginx → Grafana (node's IP; see NOTE in research about NET-01 verification)
    - from:
        - ipBlock:
            cidr: 89.223.124.200/32
      ports:
        - port: 3000
    # Intra-ns: allow all pods in monitoring (e.g., port-forward from kubectl, future)
    - from:
        - podSelector: {}
      ports:
        - port: 3000
---
# 5. Grafana egress: reach Prometheus + Loki (intra-ns) + DNS (covered above)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-grafana-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 80   # prometheus-server ClusterIP port
        - port: 9090 # prometheus direct
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: loki
      ports:
        - port: 3100
---
# 6. Prometheus ingress: allow scrape from Grafana (intra-ns) and from self
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
      app.kubernetes.io/component: server
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: {}  # any pod in monitoring (grafana, etc.)
      ports:
        - port: 9090
        - port: 80
---
# 7. Prometheus egress: scrape all intra-ns targets + cross-ns to solid-stats-staging
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
      app.kubernetes.io/component: server
  policyTypes: [Egress]
  egress:
    # Intra-monitoring scrape targets
    - to:
        - podSelector: {}
      ports:
        - port: 8080   # kube-state-metrics
        - port: 9100   # node-exporter service (actual scrape is host-level, see NOTE)
        - port: 9187   # postgres-exporter
        - port: 3100   # loki
        - port: 12345  # alloy
    # Cross-ns: rabbitmq :15692 in solid-stats-staging
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: solid-stats-staging
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: rabbitmq
      ports:
        - port: 15692
    # Cross-ns: postgres-exporter connects OUT to postgres :5432 in solid-stats-staging
    # The egress is FROM postgres-exporter pod (monitoring), not prometheus directly.
    # This rule is on the postgres-exporter pod, not prometheus.
    # (See allow-postgres-exporter-egress below)
---
# 8. postgres-exporter egress: connect to postgres in solid-stats-staging
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-postgres-exporter-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-postgres-exporter
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: solid-stats-staging
      ports:
        - port: 5432
---
# 9. Loki ingress: allow from Alloy (intra-ns) and from Prometheus (intra-ns)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-loki-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: loki
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: {}
      ports:
        - port: 3100
        - port: 9095
---
# 10. Alloy egress: push logs to Loki (intra-ns) + k8s API (kube-system) for discovery
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-alloy-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alloy
  policyTypes: [Egress]
  egress:
    # Loki write endpoint
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: loki
      ports:
        - port: 3100
    # Kubernetes API server (for pod discovery / log tailing)
    # kube-apiserver listens on 6443 and 443; on k3s the API server is at the node IP
    - to:
        - ipBlock:
            cidr: 89.223.124.200/32
      ports:
        - port: 6443
```

**NOTE on Alloy egress to k8s API:** Alloy uses the k8s API for pod discovery (`discovery.kubernetes`) and log tailing (`loki.source.kubernetes`). On k3s single-node, the API server runs at the node IP:6443. An `ipBlock` rule for the node IP + port 6443 covers this. Alternatively allow to `namespaceSelector: kube-system` port 6443, but the API server is not technically a pod — ipBlock is more correct. [ASSUMED — verify the exact k3s API endpoint during live apply]

### 96-netpol-error-tracking.yaml skeleton

```yaml
# ---------------------------------------------------------------
# error-tracking namespace — NetworkPolicies
# NET-02: default-deny + minimal-allow.
# GlitchTip does NOT expose Prometheus metrics (ENABLE_OBSERVABILITY_API=off).
# No cross-ns scrape into this namespace.
# ---------------------------------------------------------------

# 1. Allow DNS egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: error-tracking
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
      to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
---
# 2. Default deny all ingress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: error-tracking
spec:
  podSelector: {}
  policyTypes: [Ingress]
---
# 3. Default deny all egress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: error-tracking
spec:
  podSelector: {}
  policyTypes: [Egress]
---
# 4. GlitchTip web ingress: from host nginx (node IP) + DSN ingest from SDK clients
#    SDK clients are app pods in solid-stats-staging (Phase 18 future). For now:
#    allow from node IP (public edge) only. Phase 18 adds a from-solid-stats-staging rule.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-glitchtip-web-ingress
  namespace: error-tracking
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: glitchtip
      app.kubernetes.io/component: web
  policyTypes: [Ingress]
  ingress:
    - from:
        - ipBlock:
            cidr: 89.223.124.200/32
      ports:
        - port: 8000
    # Intra-ns: worker may need to reach web (if Django admin flows go intra-ns)
    - from:
        - podSelector: {}
      ports:
        - port: 8000
---
# 5. GlitchTip web + worker egress: connect to glitchtip-postgres
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-glitchtip-db-egress
  namespace: error-tracking
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: glitchtip
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: glitchtip-postgres
      ports:
        - port: 5432
---
# 6. GlitchTip-postgres ingress: only from web + worker
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-glitchtip-postgres-ingress
  namespace: error-tracking
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: glitchtip-postgres
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: glitchtip
      ports:
        - port: 5432
```

---

## RBAC Gap: obs-ci-deployer Needs `networkpolicies` Verb

The existing `obs-ci-deployer` Role in `01-obs-rbac.yaml` does NOT include `networking.k8s.io/networkpolicies` verbs. CI deploy of `95-netpol-monitoring.yaml` and `96-netpol-error-tracking.yaml` will fail with 403 Forbidden without this addition.

**Required addition to both monitoring and error-tracking Roles in `k8s/staging/01-obs-rbac.yaml`:**

```yaml
  # NetworkPolicies: apply isolation manifests from CI
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "create", "update", "patch", "delete"]
```

This is an operator-bootstrap change (01-obs-rbac.yaml is operator-applied, NOT from CI). The operator must apply the updated RBAC before deploying the NetworkPolicies from CI.

---

## node-exporter + hostNetwork: No NetworkPolicy Needed

node-exporter runs with `hostNetwork: true` (confirmed in `30-node-exporter.yaml` line 149). This places it in the **host network namespace**, not the pod's virtual network namespace.

kube-router's iptables rules for NetworkPolicy are inserted in the FORWARD chain, which handles traffic **between** the host and pod network namespaces, and between pod namespaces via the bridge. Traffic that stays within the host network namespace (host process → host network pod like node-exporter) does NOT traverse the FORWARD chain — it goes through INPUT/OUTPUT on the loopback or host interface. Therefore:

- Prometheus (a normal pod in monitoring) scrapes `node-exporter.monitoring.svc:9100` → kube-proxy DNATs to the node-exporter's host IP:9100 → this is host-network traffic → **not filtered by NetworkPolicy**
- The `allow-prometheus-scrape-egress` rule includes port 9100 as a courtesy (for the Service IP path), but even if that rule were absent, the scrape would succeed

**Practical result:** node-exporter scraping is immune to NetworkPolicy enforcement in both directions. No special exception needed.

---

## VAL-01 Script Design

### Structure: compose, don't duplicate

`scripts/validate-stack.sh` is a thin orchestrator that calls the existing per-phase scripts in order and fails loudly on any failure.

```bash
#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-stack.sh
# VAL-01: Full observability stack validation.
# Composes validate-phase-13.sh (metrics), validate-phase-15.sh (logs),
# validate-phase-16.sh (error-tracking). Fails loudly on first sub-script failure.
#
# Usage:
#   bash scripts/validate-stack.sh [--quick] [--public]
#
# Flags:
#   --quick    Pass to all sub-scripts (skip Grafana port-forward, skip forced GlitchTip ingest)
#   --public   Pass to validate-phase-16.sh (use public errors.solid-stats.ru URL)
#
# Required env:
#   GRAFANA_ADMIN_PASSWORD  — for Grafana datasource health (validate-phase-13/15.sh)
#   GLITCHTIP_DSN           — for forced-error ingest test (validate-phase-16.sh)
#
# Optional env:
#   SUPERUSER_TOKEN         — GlitchTip Bearer token (validate-phase-16.sh issue check)
#   K8S_NAMESPACE_MONITORING  — override monitoring namespace (default: monitoring)
#   K8S_NAMESPACE_ERROR       — override error-tracking namespace (default: error-tracking)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

quick=false
public_flag=""
for arg in "$@"; do
  case "$arg" in
    --quick)  quick=true ;;
    --public) public_flag="--public" ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

flags=""
[[ "$quick" == "true" ]] && flags="--quick"

echo "================================================================"
echo "=== Full Stack Validation (Phase 13 + 15 + 16) ==="
echo "================================================================"
echo ""

echo "--- Phase 13: Metrics (Prometheus + Grafana) ---"
K8S_NAMESPACE="${K8S_NAMESPACE_MONITORING:-monitoring}" \
  bash "${SCRIPT_DIR}/validate-phase-13.sh" ${flags}
echo ""

echo "--- Phase 15: Logs (Loki + Alloy) ---"
K8S_NAMESPACE="${K8S_NAMESPACE_MONITORING:-monitoring}" \
  bash "${SCRIPT_DIR}/validate-phase-15.sh" ${flags}
echo ""

echo "--- Phase 16: Error Tracking (GlitchTip) ---"
K8S_NAMESPACE="${K8S_NAMESPACE_ERROR:-error-tracking}" \
  bash "${SCRIPT_DIR}/validate-phase-16.sh" ${flags} ${public_flag}
echo ""

echo "================================================================"
echo "=== FULL STACK VALIDATION PASSED ==="
echo "================================================================"
```

### Why `--quick` for pre-policy and full for post-policy

- **Before policies are applied:** Run `--quick` to confirm Prometheus targets UP and pod states are correct. Grafana port-forward and GlitchTip ingest are also valid but optional at this stage.
- **After policies are applied:** Run without `--quick` to prove everything works through the NetworkPolicy layer. The full run exercises: Prometheus API via kubectl exec, Grafana port-forward (traverses the allowed ports), Loki LogQL via port-forward, and GlitchTip ingest via port-forward.

### Pre-condition check

Add a short preflight at the top of validate-stack.sh:
```bash
# Verify kubectl is configured
kubectl cluster-info --request-timeout=5s >/dev/null 2>&1 || {
  echo "FATAL: kubectl not configured or cluster unreachable" >&2; exit 1
}
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NetworkPolicy enforcement | Custom iptables rules | Kubernetes NetworkPolicy API + kube-router | k3s already has it; manual iptables rules conflict with kube-router chains |
| Namespace label for namespaceSelector | Manual label patching | `kubernetes.io/metadata.name` (auto-set ≥k8s 1.21) | Always present; no maintenance burden |
| DNS allow rule | Hardcoded coredns pod IP | Port 53 to kube-system namespace selector | Pod IPs change; namespaceSelector is stable |
| Test pod for NET-01 | Custom test image | `nginx:alpine` + `curlimages/curl` | Already in the cluster's image pull budget; smallest footprint |

---

## Common Pitfalls

### Pitfall 1: default-deny before DNS allow = total outage
**What goes wrong:** Apply default-deny-egress with no DNS allow. Every in-cluster DNS lookup fails. All pods with any cluster-internal connection break (Grafana can't reach Prometheus, alloy can't push to Loki, postgres-exporter can't connect to postgres).
**How to avoid:** ALWAYS apply `allow-dns-egress` BEFORE or simultaneously with `default-deny-egress`. In the manifest file, list `allow-dns-egress` as the first document.
**Warning signs:** Pods start crashing with "connection refused" on internal service names immediately after policy apply.

### Pitfall 2: Grafana/GlitchTip ingress broken by missing node IP rule
**What goes wrong:** default-deny-ingress applied without `ipBlock: cidr: 89.223.124.200/32`. Host nginx can no longer reach Grafana or GlitchTip web. Public URLs return 502.
**How to avoid:** Always include the node IP ipBlock in the ingress allow for grafana and glitchtip-web. Verify the node IP is correct before applying.
**Warning signs:** After policy apply, `curl -f https://grafana.solid-stats.ru/` returns 502. kubectl exec into grafana pod and curl localhost:3000 still works — proving the pod is up and only ingress is broken.

### Pitfall 3: Cross-namespace namespaceSelector syntax
**What goes wrong:** Using `namespaceSelector: matchLabels: name: solid-stats-staging` (custom label `name:`) instead of the auto-label `kubernetes.io/metadata.name`. The selector matches nothing, so the egress allow silently fails.
**How to avoid:** Always use `kubernetes.io/metadata.name: <ns>` for namespaceSelector in cross-ns rules. This label is auto-set by the control plane on all namespaces ≥k8s 1.21.
**Warning signs:** Prometheus target for rabbitmq shows as `down` immediately after egress policy is applied.

### Pitfall 4: Prometheus server label mismatch in podSelector
**What goes wrong:** The Prometheus pod has labels `app.kubernetes.io/name=prometheus, app.kubernetes.io/component=server` (from Helm render). A podSelector using only `app.kubernetes.io/name: prometheus` will match both the server and any init containers. More importantly, if the scrape target podSelectors don't match the actual pod labels in the live manifests, egress rules silently block.
**How to avoid:** Cross-check each podSelector against the actual `metadata.labels` in the rendered manifests (10-prometheus.yaml, 70-loki.yaml, 80-alloy.yaml, etc.) before writing policies.
**Warning signs:** kubectl logs for prometheus-server shows scrape errors for specific targets after policy apply.

### Pitfall 5: obs-ci-deployer RBAC missing networkpolicies verb
**What goes wrong:** CI deploy of netpol manifests fails with `403 Forbidden: cannot create resource "networkpolicies" in API group "networking.k8s.io"`.
**How to avoid:** Update `01-obs-rbac.yaml` to add `networking.k8s.io/networkpolicies` to both Roles (monitoring and error-tracking) BEFORE the CI deploy that applies the netpol manifests.
**Warning signs:** deploy-observability.yml workflow fails at the `kubectl apply -f k8s/observability/95-netpol*` step.

### Pitfall 6: Alloy loses pod log discovery after egress deny
**What goes wrong:** Alloy uses the Kubernetes API server (`discovery.kubernetes`) for pod discovery. If the API server endpoint (node IP:6443) is blocked by egress policy, Alloy silently stops shipping logs to Loki.
**How to avoid:** Add `ipBlock: cidr: 89.223.124.200/32 port: 6443` in `allow-alloy-egress`. Confirm the API server address is the node IP on this k3s single-node cluster (it is — the kubeconfig in CI uses `10.8.0.1:6443` over WireGuard, but in-cluster API address is typically the node IP or `kubernetes.default.svc`).
**Warning signs:** After policy apply, Loki LogQL query in validate-phase-15.sh still returns data (cached), but loki_write_sent_entries_total stops increasing over a 5-minute window.

**Alternative approach:** Allow egress to `kubernetes.default.svc` by allowing port 443/6443 to the entire service CIDR (`10.43.0.0/16`) — this is broader but avoids hardcoding the node IP. Decide during plan authoring.

### Pitfall 7: Running NET-01 probe in an obs namespace (contamination)
**What goes wrong:** Running the enforcement probe IN `monitoring` or `error-tracking` accidentally leaves a test policy that interferes with the real default-deny rollout.
**How to avoid:** Always use a throwaway `netpol-probe` namespace for NET-01 testing. Delete it completely before applying the real policies.

### Pitfall 8: validate-stack.sh not idempotent for GlitchTip DSN
**What goes wrong:** test-glitchtip-ingest.sh requires `GLITCHTIP_DSN` set. If that env var is absent, validate-phase-16.sh prints a note (not failure) and skips the ingest test. This is correct behavior for a re-runnable script.
**How to avoid:** Document that `GLITCHTIP_DSN` must be set for a full stack validation. The `--quick` flag explicitly skips the ingest test. For CI-automated runs, store DSN as a GitHub env secret.

---

## Runtime State Inventory

Not applicable — this phase adds NetworkPolicies (new resources) and creates a new script. No renames, no state migrations, no stored data to change.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kubectl (on operator workstation) | All validation scripts | ✓ | — (in cluster already proven) | — |
| WireGuard tunnel (operator or CI) | kubectl cluster access | ✓ | — (live since Phase 6) | — |
| bash + python3 | validate-stack.sh | ✓ | — (already in existing scripts) | — |
| curl | Grafana/GlitchTip port-forward checks | ✓ | — (already used) | — |
| Node SSH (for NET-01 iptables check) | Verify KUBE-NWPLCY chains | ✓ (root@89.223.124.200) | — | Skip iptables check; rely on probe-client timeout |
| `nginx:alpine` image | NET-01 probe target pod | — (to be pulled during probe) | latest | `busybox:1.36` |
| `curlimages/curl` image | NET-01 probe client pod | — (to be pulled during probe) | latest | `appropriate/curl` |

**Missing dependencies with no fallback:** None that block execution.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Bash (existing pattern — all validate scripts) |
| Config file | none |
| Quick run command | `bash scripts/validate-stack.sh --quick` |
| Full suite command | `bash scripts/validate-stack.sh` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NET-01 | NetworkPolicy enforcement confirmed before default-deny | integration (manual probe) | Operator runs throwaway deny + curl probe | ❌ Wave 0 (operator procedure, not an automated script) |
| NET-02 | Default-deny + allow policies applied; Prometheus targets UP; Grafana datasources healthy after | integration | `bash scripts/validate-stack.sh` | ❌ Wave 0 |
| VAL-01 | validate-stack.sh runs green before and after policies | integration (re-runnable) | `bash scripts/validate-stack.sh` | ❌ Wave 0 |

### Wave 0 Gaps
- [ ] `scripts/validate-stack.sh` — VAL-01 orchestrator (new file)
- [ ] `k8s/observability/95-netpol-monitoring.yaml` — NET-02 monitoring policies
- [ ] `k8s/observability/96-netpol-error-tracking.yaml` — NET-02 error-tracking policies
- [ ] RBAC update to `k8s/staging/01-obs-rbac.yaml` — add networkpolicies verb (operator-bootstrap)
- [ ] NET-01 operator procedure documented in a runbook or inline plan task

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | NetworkPolicy (namespace boundary) |
| V5 Input Validation | no | — |
| V6 Cryptography | no | — |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Pod escape laterally to other ns | Spoofing/Elevation | default-deny ingress on obs namespaces |
| Compromised obs pod reaches app db | Tampering | default-deny egress; only postgres-exporter pod allowed to port 5432 |
| Cross-namespace log exfiltration | Info Disclosure | Alloy egress limited to Loki + k8s API only |
| Public registration re-enabled | Tampering | GlitchTip ingress from node IP only; no Sentry SDK in error-tracking ns |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Node IP is 89.223.124.200 for both the public edge nginx and as the source IP seen by pods in the cluster when host nginx proxies to ClusterIP | NetworkPolicy Skeletons | Both Grafana and GlitchTip ingress allow rules use the wrong CIDR → 502 on both public URLs |
| A2 | kube-router does NOT implicitly allow host-process traffic to pods under default-deny (i.e., the ipBlock rule IS required) | §Critical: How Host Nginx Traffic | If kube-router does allow src-type LOCAL automatically, the ipBlock rule is redundant but harmless. If it does NOT (more likely), skipping it breaks the public edge |
| A3 | The Alloy pod reaches the k8s API at the node IP (89.223.124.200:6443) from within the cluster | §allow-alloy-egress | If it uses `kubernetes.default.svc` (10.43.0.1:443), the ipBlock rule won't match → Alloy loses pod discovery after egress policy apply. Verify with `kubectl exec -n monitoring deploy/alloy -- env | grep KUBERNETES` |
| A4 | postgres-exporter pod label is `app.kubernetes.io/name: prometheus-postgres-exporter` | §allow-postgres-exporter-egress | Wrong label → egress rule silently fails → postgres-exporter can't reach DB → pg_up goes to 0 |
| A5 | `kubernetes.io/metadata.name` label is auto-set on all namespaces in this k3s cluster | §Architecture Patterns | If not present (k3s < 1.21 — very unlikely), namespaceSelector rules for solid-stats-staging and kube-system match nothing, blocking cross-ns and DNS traffic |

**Verify A3 and A4 immediately during plan execution (kubectl exec before writing the YAML).**
**Verify A1 and A2 during NET-01 probe.**
**A5: k3s version on staging is ≥ 1.24 (confirmed by Phase 6 live verification); label is present.**

---

## Open Questions

1. **What is the actual source IP the grafana pod sees from host nginx?**
   - What we know: nginx runs on the node; ClusterIP DNAT happens via kube-proxy iptables
   - What's unclear: does k3s/flannel masquerade the source IP to the flannel bridge IP, or does the pod see the real node IP?
   - Recommendation: During NET-01, run `kubectl exec -n monitoring deploy/prometheus-server -- wget -qO- http://ifconfig.me 2>/dev/null || echo no-inet` to understand IP routing, then add a test: `kubectl exec -n monitoring deploy/prometheus-server -- nc -lp 9999 &` and curl from the node to that ClusterIP:9999, then check what IP the nc listener logs as source.

2. **Does Alloy use the kubernetes.default.svc or the node IP for API server access?**
   - What we know: k3s in-cluster API usually available at `kubernetes.default.svc.cluster.local:443` (port 443, not 6443)
   - What's unclear: the Alloy ServiceAccount token is mounted; Alloy uses the standard KUBERNETES_SERVICE_HOST env var
   - Recommendation: `kubectl exec -n monitoring ds/alloy -- env | grep -E 'KUBERNETES|API'` to confirm API server address before writing egress rules. If it's `10.43.0.1:443` (service CIDR), allow `ipBlock: 10.43.0.1/32 port:443` instead.

---

## Sources

### Primary (verified from codebase)
- `k8s/observability/10-prometheus.yaml` — actual scrape_configs (jobs: alloy, kube-state-metrics, loki, node-exporter, postgres-exporter, prometheus, rabbitmq)
- `k8s/observability/30-node-exporter.yaml` — confirmed `hostNetwork: true, hostPID: true`
- `k8s/observability/80-alloy.yaml` — Alloy ServiceAccount and configuration
- `k8s/observability/91-glitchtip.yaml` — glitchtip-web Service selector labels
- `k8s/staging/01-obs-rbac.yaml` — obs-ci-deployer Role (missing networkpolicies verb confirmed)
- `scripts/validate-phase-13.sh`, `validate-phase-15.sh`, `validate-phase-16.sh`, `test-glitchtip-ingest.sh` — existing harnesses
- `17-CONTEXT.md` — live constraints

### Secondary (web research)
- [K3s Networking Services docs](https://docs.k3s.io/networking/networking-services) — kube-router netpol controller library embedded in k3s [LOW]
- [K3s Network Policy — SUSE Communities](https://www.suse.com/c/rancher_blog/k3s-network-policy/) — kube-router iptables KUBE-NWPLCY chains; ADDRTYPE LOCAL handling; logging via ulogd2 [LOW]
- [kube-router issue #803](https://github.com/cloudnativelabs/kube-router/issues/803) — unresolved debate on whether src-type LOCAL is auto-allowed (reason A2 is ASSUMED) [LOW]
- [kubernetes.io/metadata.name auto-label — k8s 1.21 GA](https://v1-34.docs.kubernetes.io/docs/reference/labels-annotations-taints) — confirmed auto-applied since 1.21 [LOW but well-established]
- [prometheus-operator issue #228](https://github.com/coreos/prometheus-operator/issues/228) — hostNetwork/hostPort bypass NetworkPolicy enforcement [LOW]

---

## Metadata

**Confidence breakdown:**
- NET-01 enforcement protocol: HIGH (kube-router confirmed as k3s netpol engine; iptables KUBE-NWPLCY chains confirmed; empirical test protocol is standard practice)
- NET-02 policy structure (intra-ns, DNS, cross-ns scrape): HIGH (codebase is the ground truth for labels and ports)
- Host nginx → ClusterIP source IP behavior: MEDIUM (A1, A2 — requires NET-01 empirical proof)
- Alloy API server egress address: MEDIUM (A3 — requires kubectl exec to confirm)
- VAL-01 script design: HIGH (composition of existing tested scripts)

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (k3s/kube-router behavior is stable; review if k3s is upgraded)
