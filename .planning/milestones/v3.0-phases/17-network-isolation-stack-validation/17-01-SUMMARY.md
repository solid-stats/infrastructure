---
phase: 17-network-isolation-stack-validation
plan: "01"
subsystem: network-isolation
tags: [network-policy, kubernetes, rbac, ci-cd, net-02]
dependency_graph:
  requires: []
  provides:
    - k8s/observability/95-netpol-monitoring.yaml
    - k8s/observability/96-netpol-error-tracking.yaml
    - networkpolicies verb in both obs-ci-deployer Roles
    - error-tracking netpol routed to obs-et-k3s-staging in CI
  affects:
    - deploy-observability.yml routing logic
    - k8s/staging/01-obs-rbac.yaml (operator-bootstrap RBAC)
tech_stack:
  added:
    - networking.k8s.io/v1 NetworkPolicy (Kubernetes built-in, no new packages)
  patterns:
    - default-deny ingress+egress + additive allow layers per namespace
    - PLACEHOLDER tokens for operator-confirmed values (NET-01 probe in 17-03)
    - find \( -name A -o -name B \) pattern for multi-predicate CI glob
key_files:
  created:
    - k8s/observability/95-netpol-monitoring.yaml
    - k8s/observability/96-netpol-error-tracking.yaml
  modified:
    - k8s/staging/01-obs-rbac.yaml
    - .github/workflows/deploy-observability.yml
decisions:
  - "PLACEHOLDER tokens (NODE_IP_PLACEHOLDER, K8S_API_EGRESS_PLACEHOLDER) left in manifests for 17-03 NET-01 empirical probe; not hardcoded"
  - "allow-dns-egress placed first in each file to prevent DNS outage before default-deny-egress"
  - "Alloy k8s API egress: both candidate forms (node:6443 + svc:443) documented as comments; 17-03 resolves A3"
  - "Workflow routing fixed with find \\( -o \\) compound predicate rather than two separate find calls"
  - "96-netpol-error-tracking.yaml excluded from monitoring step, included in error-tracking step"
metrics:
  duration: "5 minutes"
  completed: "2026-06-14"
  tasks_completed: 3
  files_changed: 4
status: complete
---

# Phase 17 Plan 01: NET-02 NetworkPolicy Authoring Summary

**One-liner:** Default-deny + minimal-allow NetworkPolicies for monitoring and error-tracking namespaces, with RBAC and CI routing fixes so the manifests deploy into the correct namespace contexts.

## What Was Built

### Task 1: 95-netpol-monitoring.yaml (already committed in prior run)
10-policy multi-document YAML for the monitoring namespace:
1. `allow-dns-egress` — all pods → kube-system :53 (first, prevents DNS outage)
2. `default-deny-ingress` — block all ingress
3. `default-deny-egress` — block all egress
4. `allow-grafana-ingress` — grafana ← NODE_IP_PLACEHOLDER/32 (host nginx) + intra-ns :3000
5. `allow-grafana-egress` — grafana → prometheus :80/:9090 + loki :3100
6. `allow-prometheus-ingress` — prometheus(server) ← intra-ns :9090/:80
7. `allow-prometheus-scrape-egress` — prometheus(server) → intra-ns :8080/9100/9187/3100/12345 + rabbitmq :15692 cross-ns
8. `allow-postgres-exporter-egress` — postgres-exporter → solid-stats-staging :5432
9. `allow-loki-ingress` — loki ← intra-ns :3100/:9095
10. `allow-alloy-egress` — alloy → loki :3100 + K8S_API_EGRESS_PLACEHOLDER (commented; 17-03 resolves)

### Task 2: 96-netpol-error-tracking.yaml
6-policy multi-document YAML for the error-tracking namespace:
1. `allow-dns-egress` — all pods → kube-system :53
2. `default-deny-ingress`
3. `default-deny-egress`
4. `allow-glitchtip-web-ingress` — web ← NODE_IP_PLACEHOLDER/32 (host nginx) + intra-ns :8000
5. `allow-glitchtip-db-egress` — glitchtip (web+worker) → glitchtip-postgres :5432
6. `allow-glitchtip-postgres-ingress` — glitchtip-postgres ← glitchtip pods :5432

No cross-ns scrape ingress (GlitchTip has ENABLE_OBSERVABILITY_API off). Phase 18 note inline for future SDK DSN ingest rule.

### Task 3: RBAC + workflow routing
- `k8s/staging/01-obs-rbac.yaml`: added `networking.k8s.io/networkpolicies` with full CRUD verbs to both obs-ci-deployer Roles (monitoring + error-tracking)
- `.github/workflows/deploy-observability.yml`:
  - monitoring apply step: added `! -name '96-netpol-error-tracking.yaml'` exclusion
  - error-tracking apply step: broadened predicate to `\( -name '9*-glitchtip*.yaml' -o -name '96-netpol-error-tracking.yaml' \)` so the netpol routes to obs-et-k3s-staging context

## Verification Results

```
python3 validate-obs-manifests.py → ok: validated 21 manifest file(s) — PASSED
95-netpol-monitoring.yaml: 10 NetworkPolicy docs, all namespace=monitoring — PASSED
96-netpol-error-tracking.yaml: 6 NetworkPolicy docs, all namespace=error-tracking — PASSED
both obs-ci-deployer Roles have networkpolicies create/delete verb — PASSED
workflow routes 96-netpol-error-tracking.yaml to error-tracking context — PASSED
find simulation: monitoring step includes 95-netpol, excludes 96-netpol — PASSED
find simulation: error-tracking step includes 96-netpol + all glitchtip files — PASSED
```

## Placeholder Tokens for 17-03

| Token | Location | Resolved By |
|-------|----------|-------------|
| `NODE_IP_PLACEHOLDER/32` | 95-netpol-monitoring.yaml (allow-grafana-ingress, allow-alloy-egress comments) | 17-03 NET-01 probe: confirm source IP grafana pod sees from host nginx |
| `NODE_IP_PLACEHOLDER/32` | 96-netpol-error-tracking.yaml (allow-glitchtip-web-ingress) | Same 17-03 probe — one substitution covers both files |
| `K8S_API_EGRESS_PLACEHOLDER` | 95-netpol-monitoring.yaml (allow-alloy-egress comments) | 17-03 A3 probe: `kubectl exec -n monitoring ds/alloy -- env \| grep KUBERNETES_SERVICE_HOST` |

## Deviations from Plan

### Continuation from prior partial run

**Found during:** Task 1/2 startup
**Issue:** A prior GSD executor had already committed `95-netpol-monitoring.yaml` (commit e753d59) and even `96-netpol-error-tracking.yaml` (commit 160cec2) before the session was interrupted. Task 3 (RBAC + workflow) was not done.
**Fix:** Verified both existing netpol files against plan verification criteria (all pass), skipped re-authoring, proceeded directly to Task 3.
**Classification:** No deviation — continuation behavior, not a plan deviation.

No other deviations. Plan executed exactly as written for Task 3.

## Threat Surface Scan

No new network endpoints introduced. The NetworkPolicies themselves are a security control (T-17-01/02/03 mitigations), not new attack surface. The workflow change only affects which files apply to which context — no new credentials or trust boundaries.

## Known Stubs

None. All PLACEHOLDER tokens are intentional and documented with resolution procedure for 17-03. They are not stubs blocking the plan's goal — the files are correctly authored; the tokens are empirically resolved before live apply.

## Self-Check: PASSED

- k8s/observability/95-netpol-monitoring.yaml: exists, 10 NetworkPolicy docs in monitoring namespace
- k8s/observability/96-netpol-error-tracking.yaml: exists, 6 NetworkPolicy docs in error-tracking namespace
- k8s/staging/01-obs-rbac.yaml: both obs-ci-deployer Roles have networkpolicies verb
- .github/workflows/deploy-observability.yml: 96-netpol excluded from monitoring step, included in error-tracking step
- validate-obs-manifests.py: PASSED (21 manifests)
- Commits: e753d59 (95-netpol), 160cec2 (96-netpol), 08c2751 (RBAC+workflow)
