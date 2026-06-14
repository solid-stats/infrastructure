---
phase: 15-log-stack
plan: "04"
subsystem: obs-live-apply
status: complete
tags: [live-apply, loki, alloy, log-01, log-02, log-03]

dependency_graph:
  requires: ["15-01", "15-02", "15-03"]
  provides:
    - "live Loki (SingleBinary/filesystem, 7d retention) + Alloy DaemonSet in monitoring ns"
    - "logs shipped to Loki, queryable as a 2nd Grafana datasource"
  affects:
    - "live monitoring namespace"
    - k8s/observability/70-loki.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/observability/values/loki-values.yaml
    - k8s/observability/values/grafana-values.yaml
    - k8s/observability/values/alloy-values.yaml
    - k8s/observability/80-alloy.yaml
    - scripts/validate-phase-15.sh

key_files:
  modified:
    - k8s/observability/70-loki.yaml
    - k8s/observability/80-alloy.yaml
    - k8s/observability/50-grafana.yaml
    - scripts/validate-phase-15.sh

decisions:
  - "Right-sizing: Loki ~69Mi (256Mi limit — comfortable). Alloy hit ~118Mi during the initial backfill against a 128Mi limit — bumped to 192Mi to prevent OOM flapping. Node at 66% memory after the full stack."
  - "Bootstrap RBAC (grafana + alloy + extracted Phase 13 ClusterRoles) applied as operator/admin; obs stack applied server-side (dashboard-annotation limit + field ownership)."

requirements: [LOG-01, LOG-02, LOG-03]
---

# Plan 15-04 — Live Apply & Verification

## What is live (verified by validate-phase-15.sh → PASSED)

| Req | Result |
|-----|--------|
| LOG-01 | loki-0 Running, PVC bound; `loki_boltdb_shipper_compactor_running == 1`; ConfigMap retention_period 168h (Loki renders it as `1w` in /config) |
| LOG-02 | alloy DaemonSet ready; `loki_write_sent_entries_total` = 36127 (shipping); conservative 5-label pipeline |
| LOG-03 | Loki = healthy Grafana datasource (id=2); LogQL `{namespace="solid-stats-staging",app=~"server-2.*"}` returned 5 entries |

## Defects found and fixed during the live apply (gap-closure)

1. **loki-sc-rules crashloop** — the chart's rules-watching sidecar lists Secrets via the k8s API
   and 403s (loki SA has no secrets perm, by design). Disabled `sidecar.rules.enabled` (we don't
   use the Loki ruler).
2. **grafana init-chown-data Permission denied** — the chown init ran non-root (UID 472) and
   couldn't chown pre-existing /var/lib/grafana subdirs. Disabled `initChownData.enabled`; fsGroup 472
   already makes the PVC writable.
3. **validate-phase-15.sh retention check** — execed `wget` inside the distroless loki image (no
   wget/sh) and grepped `168h` while Loki normalizes it to `1w`. Switched to reading the live Loki
   ConfigMap and accepting 168h/1w.
4. **Alloy memory** — bumped 128Mi→192Mi limit after live right-sizing (was ~118Mi at backfill).
5. **Grafana ClusterRole friction** — the chart renders a ClusterRole even with searchNamespace set;
   stripped from the obs render (lives in the operator-bootstrap 01-obs-rbac.yaml) so the hardened
   static gate (no ClusterRole in k8s/observability/) passes and the CI obs-ci-deployer path works.

## Requirements
- LOG-01, LOG-02, LOG-03 all verified live (validate-phase-15.sh PASSED). ✓
