---
phase: 15-log-stack
plan: "03"
subsystem: infra
tags: [prometheus, grafana, loki, alloy, observability, scrape-targets, datasource]

requires:
  - phase: 15-log-stack/15-01
    provides: loki Service loki:3100, validate-obs-manifests.py gate
  - phase: 15-log-stack/15-02
    provides: alloy Service alloy:12345, hardened ClusterRole gate

provides:
  - k8s/observability/values/prometheus-values.yaml — loki + alloy scrape jobs added
  - k8s/observability/10-prometheus.yaml — re-rendered with loki:3100 + alloy:12345 targets
  - k8s/observability/values/grafana-values.yaml — Loki added to datasources list (LOG-03)
  - k8s/observability/50-grafana.yaml — re-rendered with both prometheus + loki datasources

affects: [15-04-apply]

tech-stack:
  added: []
  patterns:
    - prometheus-static-scrape: two new static_configs jobs (loki + alloy) follow existing pattern (kube-state-metrics, node-exporter, etc.)
    - grafana-datasource-list: grafana/grafana chart v10.5.15 has no additionalDataSources key; Loki added inline in datasources.datasources\.yaml.datasources list
    - clusterrole-strip: ClusterRole+ClusterRoleBinding stripped from 50-grafana.yaml re-render via Python doc-split (same pattern as 15-01/15-02; grafana ClusterRole already in 01-obs-rbac.yaml from 15-02)

key-files:
  created: []
  modified:
    - k8s/observability/values/prometheus-values.yaml
    - k8s/observability/10-prometheus.yaml
    - k8s/observability/values/grafana-values.yaml
    - k8s/observability/50-grafana.yaml

key-decisions:
  - "chart v10.5.15 has no additionalDataSources top-level key — Loki added inline in datasources.datasources.yaml.datasources list alongside Prometheus (Open Question 4 resolved)"
  - "grafana chart always renders ClusterRole regardless of sidecar.searchNamespace — stripped via Python doc-split same as 15-01 (grafana ClusterRole already in 01-obs-rbac.yaml from 15-02 backfill)"
  - "sidecar.searchNamespace: monitoring documented in values comment but does not suppress ClusterRole in this chart version"

requirements-completed: [LOG-01, LOG-03]

duration: 20min
completed: 2026-06-14
status: complete
---

# Phase 15 Plan 03: Prometheus Scrape Targets + Grafana Loki Datasource Summary

**Prometheus extended with loki:3100 + alloy:12345 static scrape targets; Grafana re-rendered with Loki as a second provisioned datasource alongside Prometheus**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Extended `prometheus-values.yaml` with two new enabled static scrape jobs: `loki` (loki.monitoring.svc:3100) and `alloy` (alloy.monitoring.svc:12345), following the same per-job map style as existing kube-state-metrics/node-exporter entries
- Re-rendered `10-prometheus.yaml` via `helm template prometheus-community/prometheus v29.11.0`; both targets present, `serviceAccountName: prometheus` intact, no ClusterRole; `validate-obs-manifests.py` green
- Extended `grafana-values.yaml` with Loki entry in the `datasources.datasources.yaml.datasources` list (isDefault:false, url http://loki.monitoring.svc:3100, access proxy, maxLines 1000)
- Re-rendered `50-grafana.yaml` via `helm template grafana/grafana v10.5.15`; both `type: prometheus` and `type: loki` datasources present; ClusterRole+ClusterRoleBinding stripped via Python doc-split; `validate-obs-manifests.py` green

## Task Commits

1. **Task 1: prometheus-values.yaml + 10-prometheus.yaml** — `8325485` (feat)
2. **Task 2: grafana-values.yaml + 50-grafana.yaml** — `ef4e0b1` (feat)

## Decisions Made

- `additionalDataSources` is not a valid top-level key in `grafana/grafana` chart v10.5.15 (no match in `helm show values`). Loki entry merged into the existing `datasources.datasources.yaml.datasources` list — both datasources render into the same `datasources.yaml` ConfigMap key as expected.
- `sidecar.dashboards.searchNamespace: null → monitoring` documented in values but does NOT suppress ClusterRole rendering in chart v10.5.15. The chart renders ClusterRole unconditionally when sidecar is enabled. Strip pattern (Python doc-split) applied same as 15-01/15-02. Grafana ClusterRole was already backfilled to `k8s/staging/01-obs-rbac.yaml` in 15-02 so no additional bootstrap file change needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `additionalDataSources` not supported in grafana/grafana chart v10.5.15**
- **Found during:** Task 2 (helm template output had no Loki datasource)
- **Issue:** PLAN.md and RESEARCH specified `additionalDataSources:` as a top-level values key. `helm show values grafana/grafana --version 10.5.15` confirms this key does not exist — the chart only has `datasources:`. The RESEARCH note (Open Question 4) anticipated this ambiguity.
- **Fix:** Removed the `additionalDataSources:` block; added Loki as a second entry in the existing `datasources.datasources.yaml.datasources` list. The rendered ConfigMap now contains both datasources in the same `datasources.yaml` key.
- **Files modified:** `k8s/observability/values/grafana-values.yaml`
- **Commit:** `ef4e0b1`

**2. [Rule 2 - Missing Critical] ClusterRole still rendered despite sidecar.searchNamespace: monitoring**
- **Found during:** Task 2 (render inspection — ClusterRole present in output)
- **Issue:** PLAN.md (helm_note) stated `searchNamespace: monitoring` would cause the chart to render a namespaced Role instead of ClusterRole. In chart v10.5.15, the ClusterRole template renders unconditionally when `sidecar.dashboards.enabled: true`, regardless of `searchNamespace` setting.
- **Fix:** Applied Python doc-split ClusterRole strip (same pattern established in 15-01 for Loki, 15-02 for kube-state-metrics/grafana). Grafana ClusterRole was already present in `k8s/staging/01-obs-rbac.yaml` from the 15-02 Phase 13 backfill — no additional bootstrap changes required.
- **Files modified:** `k8s/observability/50-grafana.yaml`
- **Commit:** `ef4e0b1`

## Threat Surface Scan

| T-ID | Mitigation | Status |
|------|-----------|--------|
| T-15-08 | Loki datasource access:proxy, ClusterIP-only, no public ingress; Grafana auth still required | 50-grafana.yaml |
| T-15-09 | Prometheus datasource preserved (isDefault:true); Loki added as non-default; both verified in rendered output | 50-grafana.yaml |
| T-15-SC | Charts pinned (prometheus 29.11.0, grafana 10.5.15); render stderr captured separately (no 2>&1 splice) | 10-prometheus.yaml, 50-grafana.yaml |

No new threat surface beyond the plan's threat model.

## Known Stubs

None — authoring only (Wave 1). Scrape targets will only yield data after 15-04 applies Loki + Alloy live.

## Next Phase Readiness

- `10-prometheus.yaml` ready for apply in 15-04 — Prometheus will scrape loki:3100 and alloy:12345 after apply
- `50-grafana.yaml` ready for apply in 15-04 — Grafana will provision both Prometheus and Loki datasources after apply
- LOG-03 acceptance (LogQL query in Grafana Explore → Loki datasource) is possible only after 15-04 live apply + Alloy collecting logs

---
*Phase: 15-log-stack*
*Completed: 2026-06-14*
