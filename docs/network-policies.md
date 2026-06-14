# Observability NetworkPolicies Runbook

Default-deny + minimal-allow NetworkPolicies isolate the `monitoring` and `error-tracking`
namespaces (NET-02), proven not to break scraping, datasources, or the public edge. The app
namespace `solid-stats-staging` is intentionally NOT locked down (only reached by an allow rule).

- Manifests: `k8s/observability/95-netpol-monitoring.yaml` (11 policies),
  `k8s/observability/96-netpol-error-tracking.yaml` (6 policies).
- Applied by `deploy-observability.yml` (obs-ci-deployer; 95 → monitoring context, 96 →
  error-tracking context). RBAC: both `obs-ci-deployer` Roles carry the `networkpolicies` verb
  (`k8s/staging/01-obs-rbac.yaml`, operator-bootstrap, CI-glob-excluded).
- Validate the whole stack any time with `scripts/validate-stack.sh` (VAL-01).

## NET-01 Enforcement Finding (live, 2026-06-14)

NetworkPolicy enforcement was proven empirically in a throwaway `netpol-probe` namespace BEFORE
any default-deny was relied on (never in monitoring/error-tracking):

| Check | Result |
|-------|--------|
| kube-router controller | active — `iptables -S \| grep KUBE-NWPLCY` shows live chains |
| pod → pod under deny-all ingress | **BLOCKED** (curl http=000) — enforcement confirmed |
| node/host → pod under deny-all ingress | **NOT blocked** (http=404 reached nginx) — host/local traffic bypasses ingress netpol |
| probe namespace | deleted after the test |

### Resolved assumptions (A1–A4)

| ID | Question | Live finding | Used in |
|----|----------|--------------|---------|
| A1/A2 | Source IP a pod sees from host nginx | **10.42.0.1** (the cni0 gateway — a node/host process is SNAT'd to it, NOT the node public IP 89.223.124.200) | grafana + glitchtip-web ingress `ipBlock 10.42.0.1/32` |
| A2 | Does the edge need the ipBlock at all? | No — host/local traffic bypasses ingress netpol, so the edge survives regardless. The `ipBlock 10.42.0.1/32` is the explicit, measured allow (belt-and-suspenders). | both ingress policies |
| A3 | Alloy k8s-API egress target | `KUBERNETES_SERVICE_HOST=10.43.0.1`, port 443 | shared `allow-apiserver-egress` (10.43.0.1/32:443) |
| A4 | postgres-exporter pod label | `app.kubernetes.io/name=prometheus-postgres-exporter` (selector correct) | `allow-postgres-exporter-egress` |

### Two gaps found beyond the original authored policies (added in 17-03)

Both surfaced from reasoning about default-deny **egress** and were added before apply, so the
post-apply validation passed first try:

1. **k8s API egress** — `kube-state-metrics` (watches cluster objects) and the Grafana sidecars
   (`sc-dashboard`/`sc-datasource` watch ConfigMaps) need the API server under default-deny-egress.
   Added Policy 11 `allow-apiserver-egress` (namespace-wide `podSelector:{}`; also covers Alloy).
   prometheus/loki/postgres-exporter don't need it but a blanket API-server allow is the standard
   pattern and not a lateral-movement risk (RBAC bounds each SA).

   **Post-DNAT correction (found live when the grafana dashboard sidecar was restarted):**
   kube-router enforces egress AFTER kube-proxy DNAT, so allowing only the kubernetes.default
   ClusterIP `10.43.0.1:443` is NOT sufficient — the post-DNAT destination is the real apiserver
   endpoint, the node IP `89.223.124.200:6443` (`kubectl get endpoints kubernetes`). The policy
   allows BOTH (ClusterIP:443 + node-IP:6443). Symptom of the missing node-IP rule: a pod that
   opens a FRESH API connection after the policy is applied gets `Connection refused` and
   crash-loops (the k8s-sidecar), while pods whose API watch was already established before the
   policy keep working — which is why validate-stack passed at apply time (no obs pod had been
   restarted yet).
2. **node-exporter scrape egress** — node-exporter runs `hostNetwork`, so its Service endpoint is
   the node IP `89.223.124.200:9100`, which the intra-ns `podSelector:{}` egress rule can't match.
   Added an explicit `ipBlock 89.223.124.200/32:9100` to `allow-prometheus-scrape-egress`.

## NET-02 Apply Runbook

```bash
# 1. Operator applies the RBAC bump (CI-glob-excluded; admin context)
kubectl apply -f k8s/staging/01-obs-rbac.yaml

# 2. Baseline: prove the stack is green BEFORE isolation
bash scripts/validate-stack.sh --quick        # -> FULL STACK VALIDATION PASSED

# 3. Apply the policies (or let deploy-observability.yml route them)
kubectl apply -f k8s/observability/95-netpol-monitoring.yaml      # -> monitoring
kubectl apply -f k8s/observability/96-netpol-error-tracking.yaml  # -> error-tracking

# 4. Post-apply: prove isolation broke nothing (full run exercises ingress/egress)
GRAFANA_ADMIN_PASSWORD=… GLITCHTIP_DSN=… SUPERUSER_TOKEN=… bash scripts/validate-stack.sh
curl -I https://grafana.solid-stats.ru/   # 302 (login), NOT 502
curl -I https://errors.solid-stats.ru/    # 200, NOT 502
```

Rollback if anything breaks: `kubectl delete -f k8s/observability/95-netpol-monitoring.yaml`
(and 96) returns to the green baseline; diagnose before retrying.

## Before / After Evidence (live, 2026-06-14)

| Check | Before policies (`--quick`) | After policies (full) |
|-------|------------------------------|------------------------|
| Prometheus targets | all UP | all 7 UP (alloy, kube-state-metrics, loki, node-exporter, postgres-exporter, prometheus, rabbitmq) |
| Grafana datasources | (skipped in --quick) | Prometheus + Loki healthy |
| Loki / Alloy | compactor running; `loki_write_sent_entries_total=41254` | LogQL returns server-2 lines; entries `41580` (Alloy still shipping → API egress works) |
| GlitchTip | pods Running; registration closed | forced Sentry event accepted (200) + issue appeared |
| `grafana.solid-stats.ru` | 302 | **302** (non-502) |
| `errors.solid-stats.ru` | 200 | **200** (non-502) |
| `validate-stack.sh` | PASSED | **FULL STACK VALIDATION PASSED** |

Live policy count: `monitoring` = 11, `error-tracking` = 6. `netpol-probe` namespace = NotFound.
