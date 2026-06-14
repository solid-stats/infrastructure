---
phase: 17-network-isolation-stack-validation
plan: "03"
subsystem: observability
status: complete
tags: [networkpolicy, kube-router, isolation, live, net-01, net-02, val-01]
completed: "2026-06-14T10:25:00Z"
duration: "~25 minutes (live)"

dependency_graph:
  requires:
    - "17-01 — authored 95/96 netpol manifests + RBAC verb + workflow routing"
    - "17-02 — authored scripts/validate-stack.sh"
    - "Phases 13-16 live (Prometheus/Grafana/exporters, Loki/Alloy, GlitchTip)"
  provides:
    - "17 NetworkPolicies live (11 monitoring + 6 error-tracking), default-deny + minimal-allow"
    - "docs/network-policies.md — NET-01 finding + apply runbook + before/after evidence"
    - "validate-stack.sh proven green before AND after isolation (VAL-01)"
  affects:
    - "18 — error-tracking ingress will gain a from-solid-stats-staging SDK rule"

key_files:
  modified:
    - k8s/observability/95-netpol-monitoring.yaml
    - k8s/observability/96-netpol-error-tracking.yaml
    - docs/network-policies.md

commits:
  - "a25ad1d feat(17-03): apply obs NetworkPolicies live — NET-01/02/VAL-01 green"

metrics:
  requirements_verified: [NET-01, NET-02, VAL-01]
---

# Phase 17 Plan 03: Live NetworkPolicy Apply + Stack Validation Summary

**One-liner:** Proved kube-router enforcement empirically first, resolved the host-source-IP /
Alloy-API / exporter-label unknowns live, found and fixed two egress gaps before apply, then
applied 17 default-deny + minimal-allow policies with validate-stack.sh green BOTH before and
after — both public obs URLs survived.

## NET-01 — enforcement proven first (throwaway netpol-probe ns)

- pod → pod under a deny-all ingress: **BLOCKED** (curl http=000) → enforcement active.
- node/host → pod under the same deny-all: **NOT blocked** (reached nginx) → host/local traffic
  bypasses ingress netpol (kube-router src-type LOCAL). The public edge survives default-deny.
- `iptables -S | grep KUBE-NWPLCY` → live chains. Probe namespace deleted.

## Assumptions resolved live

| ID | Finding | Applied as |
|----|---------|-----------|
| A1/A2 | host nginx → pod source = **10.42.0.1** (cni0 gateway, NOT node public IP) | grafana + glitchtip-web ingress `ipBlock 10.42.0.1/32` |
| A3 | Alloy `KUBERNETES_SERVICE_HOST=10.43.0.1:443` | shared `allow-apiserver-egress` |
| A4 | postgres-exporter label `prometheus-postgres-exporter` (correct) | `allow-postgres-exporter-egress` |

## Two egress gaps fixed before apply (not in the authored 17-01 policies)

1. **k8s API egress** — kube-state-metrics + Grafana sidecars (and Alloy) need 10.43.0.1:443
   under default-deny-egress. Added Policy 11 `allow-apiserver-egress` (podSelector{} → API:443).
2. **node-exporter scrape** — hostNetwork pod's endpoint is the node IP, unmatched by the intra-ns
   podSelector. Added `ipBlock 89.223.124.200/32:9100` to `allow-prometheus-scrape-egress`.

Because these were caught by reasoning (not by a failed apply), the post-apply validation passed
on the first try — no rollback needed.

## Before / After (live)

| | Before (`--quick`) | After (full) |
|---|---|---|
| Prometheus targets | all UP | all 7 UP |
| Grafana datasources | n/a | Prometheus + Loki healthy |
| Loki/Alloy | compactor running; entries 41254 | LogQL returns server-2; entries 41580 (still shipping) |
| GlitchTip | Running, reg closed | forced event accepted (200) + issue appeared |
| grafana.solid-stats.ru | 302 | 302 (non-502) |
| errors.solid-stats.ru | 200 | 200 (non-502) |
| validate-stack.sh | PASSED | FULL STACK VALIDATION PASSED |

## Operator checkpoint (Task 3) — verified live by the autonomous operator

All gate checks performed and green: `validate-stack.sh` ends with "FULL STACK VALIDATION PASSED";
both public URLs non-502; `kubectl get networkpolicy` lists 11 (monitoring) + 6 (error-tracking);
`netpol-probe` is NotFound; docs/network-policies.md holds the finding + before/after evidence.

## Self-Check: PASSED

- 17 NetworkPolicies live; default-deny + minimal-allow; app namespace untouched.
- validate-stack.sh green before and after; all targets UP; datasources healthy; both URLs non-502.
- NET-01 finding + A1-A4 + before/after evidence in docs/network-policies.md.
- Commit a25ad1d present; probe namespace cleaned up.
