---
phase: 13-deploy-pipeline-metrics-stack
plan: "03"
subsystem: observability
status: complete
tags: [observability, grafana, helm, dashboards, prometheus-datasource, configmap]
completed: "2026-06-14"
duration_minutes: 20
tasks_completed: 2
files_created: 7
files_modified: 0

dependency_graph:
  requires:
    - k8s/observability/10-prometheus.yaml (13-02) — prometheus-server Service name for datasource URL
    - scripts/validate-obs-manifests.py (13-01) — static gate
    - grafana-secrets Secret (13-01 render-obs-secrets.py) — admin.existingSecret
  provides:
    - k8s/observability/values/grafana-values.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/observability/dashboards/node-exporter-full.json
    - k8s/observability/dashboards/kube-state-metrics.json
    - k8s/observability/dashboards/postgresql.json
    - k8s/observability/dashboards/rabbitmq-overview.json
    - k8s/observability/60-grafana-dashboards.yaml
  affects:
    - k8s/staging/01-obs-rbac.yaml (Wave 3) — Grafana chart renders ClusterRole/ClusterRoleBinding; obs-ci-deployer needs permission to apply them (same issue as KSM in 13-02)
    - .github/workflows/deploy-observability.yml (13-04) — applies k8s/observability/*.yaml including 50-grafana.yaml + 60-grafana-dashboards.yaml
    - scripts/validate-phase-13.sh (13-06) — live MET-05/MET-06 checks port-forward svc/grafana 13000:80

tech_stack:
  added:
    - grafana/grafana chart v10.5.15 (app v12.3.1) — helm template rendered
    - quay.io/kiwigrid/k8s-sidecar:2.5.0 — sidecar image (pulled by chart)
    - Grafana dashboard ID 1860 (Node Exporter Full, 518K)
    - Grafana dashboard ID 13332 (kube-state-metrics-v2, 121K)
    - Grafana dashboard ID 9628 (PostgreSQL Database, 83K)
    - Grafana dashboard ID 10991 (RabbitMQ-Overview, 263K)
  patterns:
    - helm template render-then-commit (DEP-01)
    - admin.existingSecret (not adminExistingSecret — chart v10.5.15 key is admin.existingSecret)
    - sidecar dashboard provisioning — ConfigMaps labelled grafana_dashboard=1 auto-discovered
    - one-ConfigMap-per-dashboard (Pitfall 8 — 1 MiB object limit)

key_files:
  created:
    - k8s/observability/values/grafana-values.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/observability/dashboards/node-exporter-full.json
    - k8s/observability/dashboards/kube-state-metrics.json
    - k8s/observability/dashboards/postgresql.json
    - k8s/observability/dashboards/rabbitmq-overview.json
    - k8s/observability/60-grafana-dashboards.yaml
  modified: []

decisions:
  - "admin.existingSecret (not adminExistingSecret): chart v10.5.15 uses nested admin.existingSecret/userKey/passwordKey — research listed wrong top-level key"
  - "fullnameOverride: grafana pins Service name for stable kubectl rollout-status + port-forward in 13-06"
  - "Dashboard JSONs downloaded at author-time and committed (Pitfall 8 / T-13-11): not imported at runtime"
  - "kube-state-metrics dashboard ID 13332 confirmed — title kube-state-metrics-v2, downloaded and parsed OK"
  - "60-grafana-dashboards.yaml: 4 separate ConfigMap documents separated by --- (Pitfall 8: one per JSON)"

commits:
  - hash: 8d7c223
    message: "feat(13-03): render Grafana chart v10.5.15 with Prometheus datasource + sidecar (MET-05)"
  - hash: 1e2e3cf
    message: "feat(13-03): vendor 4 dashboard JSONs + 60-grafana-dashboards.yaml ConfigMaps (MET-06)"
---

# Phase 13 Plan 03: Grafana Render + Dashboard ConfigMaps Summary

**One-liner:** grafana/grafana chart v10.5.15 rendered into 50-grafana.yaml with Prometheus provisioned datasource (prometheus-server.monitoring.svc:80), admin password from grafana-secrets existingSecret, dashboard sidecar enabled; 4 standard dashboard JSONs (1860/13332/9628/10991) vendored and wrapped as separate ConfigMaps labelled grafana_dashboard=1.

## What Was Built

| File | Kind(s) | Key config |
|------|---------|-----------|
| `k8s/observability/values/grafana-values.yaml` | values | admin.existingSecret=grafana-secrets, fsGroup=472, priorityClassName=obs-background, sidecar.dashboards.enabled=true |
| `k8s/observability/50-grafana.yaml` | SA, ConfigMap×2, PVC, ClusterRole, ClusterRoleBinding, Role, RoleBinding, Service, Deployment, Pod (test) | Grafana 12.3.1, sidecar discovery, datasource provisioned |
| `k8s/observability/dashboards/node-exporter-full.json` | — | grafana.com ID 1860, 518K |
| `k8s/observability/dashboards/kube-state-metrics.json` | — | grafana.com ID 13332, 121K |
| `k8s/observability/dashboards/postgresql.json` | — | grafana.com ID 9628, 83K |
| `k8s/observability/dashboards/rabbitmq-overview.json` | — | grafana.com ID 10991, 263K |
| `k8s/observability/60-grafana-dashboards.yaml` | ConfigMap×4 | one per dashboard, labelled grafana_dashboard=1, namespace monitoring |

### Helm render command (reproducible)

```bash
export PATH="$HOME/.local/bin:$PATH"
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm template grafana grafana/grafana \
  --version 10.5.15 \
  --namespace monitoring \
  --values k8s/observability/values/grafana-values.yaml \
  > k8s/observability/50-grafana.yaml
```

Chart appVersion: 12.3.1 (Grafana 12.x — confirmed via `helm show chart grafana/grafana --version 10.5.15`).

### Dashboard ConfigMap sizes (all under 1 MiB limit)

| ConfigMap | JSON source | Size |
|-----------|------------|------|
| grafana-dashboard-node-exporter-full | dashboards/node-exporter-full.json | 518K |
| grafana-dashboard-kube-state-metrics | dashboards/kube-state-metrics.json | 121K |
| grafana-dashboard-postgresql | dashboards/postgresql.json | 83K |
| grafana-dashboard-rabbitmq-overview | dashboards/rabbitmq-overview.json | 263K |

## Tasks

### Task 1 — grafana-values.yaml + render 50-grafana.yaml (MET-05)

Ran `helm show values grafana/grafana --version 10.5.15` to confirm exact schema before authoring. Key finding: chart uses `admin.existingSecret` (nested under `admin:` block), not `adminExistingSecret` at top level. Set `fullnameOverride: grafana` for stable Service name. Datasource provisioned via `datasources.datasources.yaml` values key. Sidecar enabled with `label: grafana_dashboard`, `labelValue: "1"`. fsGroup=472 set at pod securityContext level.

Render: 17 resources across SA, ConfigMap×2, PVC, ClusterRole, ClusterRoleBinding, Role, RoleBinding, Service, Deployment, Pod (helm test).

`python3 scripts/validate-obs-manifests.py` passed: 10 manifest files OK.

### Task 2 — 4 dashboard JSONs + 60-grafana-dashboards.yaml (MET-06)

Downloaded from `https://grafana.com/api/dashboards/{ID}/revisions/latest/download`. All 4 JSONs parse as valid. ConfigMaps authored programmatically (Python script) as multi-document YAML with `---` separators — each document ≤ 518K (Pitfall 8 avoidance). Static gate passed after adding 60-grafana-dashboards.yaml: 11 manifest files OK.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Research listed wrong chart values key for admin secret**
- **Found during:** Task 1 — `helm show values grafana/grafana --version 10.5.15` run
- **Issue:** Research § Code Examples shows `grafana.adminExistingSecret: grafana-secrets` at top level; chart v10.5.15 uses nested `admin.existingSecret: grafana-secrets` under an `admin:` block with `userKey`/`passwordKey` sub-keys
- **Fix:** Used correct `admin.existingSecret` in grafana-values.yaml; rendered 50-grafana.yaml correctly references grafana-secrets
- **Files modified:** `k8s/observability/values/grafana-values.yaml`
- **Commit:** 8d7c223

## Known Stubs

None — all wiring is complete. Datasource URL and secret references are authoritative. Live datasource-health and dashboard-render confirmation is deferred to Wave 2 (13-06).

## Threat Flags

None beyond the plan's threat model.

- T-13-08 mitigated: no admin password literal in 50-grafana.yaml (grep confirmed)
- T-13-09 mitigated: admin.existingSecret pins credentials; no helm-generated random password
- T-13-10 accepted: ClusterIP only, no Ingress
- T-13-11 mitigated: all 4 JSONs vendored from grafana.com official IDs, committed and reviewable

**Grafana chart ClusterRole/ClusterRoleBinding present in 50-grafana.yaml** — not a secret-values threat; cluster-read only (RBAC for Grafana's own SA). obs-ci-deployer namespace-scoped issue deferred to 13-04 (same pattern as KSM in 13-02).

## Self-Check

- [x] `k8s/observability/values/grafana-values.yaml` exists — admin.existingSecret=grafana-secrets, fsGroup=472, priorityClassName=obs-background, sidecar.dashboards.enabled=true, datasource url=http://prometheus-server.monitoring.svc:80
- [x] `k8s/observability/50-grafana.yaml` exists — grep confirms: prometheus-server.monitoring.svc, grafana-secrets, grafana_dashboard, obs-background, fsGroup=472, Service name=grafana, no password literal
- [x] `k8s/observability/dashboards/node-exporter-full.json` exists, parses as JSON (title: Node Exporter Full)
- [x] `k8s/observability/dashboards/kube-state-metrics.json` exists, parses as JSON (title: kube-state-metrics-v2)
- [x] `k8s/observability/dashboards/postgresql.json` exists, parses as JSON (title: PostgreSQL Database)
- [x] `k8s/observability/dashboards/rabbitmq-overview.json` exists, parses as JSON (title: RabbitMQ-Overview)
- [x] `k8s/observability/60-grafana-dashboards.yaml` exists — 4 ConfigMaps, each labelled grafana_dashboard=1, namespace=monitoring, all < 1 MiB
- [x] `python3 scripts/validate-obs-manifests.py` exits 0 (11 manifest files validated)
- [x] Commits 8d7c223, 1e2e3cf exist in git log

## Self-Check: PASSED
