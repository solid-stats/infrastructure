---
phase: 13-deploy-pipeline-metrics-stack
plan: "02"
subsystem: observability
status: complete
tags: [observability, prometheus, helm, metrics, kube-state-metrics, node-exporter, postgres-exporter]
completed: "2026-06-14"
duration_minutes: 35
tasks_completed: 2
files_created: 8
files_modified: 1

dependency_graph:
  requires:
    - scripts/validate-obs-manifests.py (13-01)
    - scripts/render-obs-secrets.py (13-01) — referenced in postgres-exporter values comment
  provides:
    - k8s/observability/10-prometheus.yaml
    - k8s/observability/20-kube-state-metrics.yaml
    - k8s/observability/30-node-exporter.yaml
    - k8s/observability/40-postgres-exporter.yaml
    - k8s/observability/values/prometheus-values.yaml
    - k8s/observability/values/kube-state-metrics-values.yaml
    - k8s/observability/values/node-exporter-values.yaml
    - k8s/observability/values/postgres-exporter-values.yaml
  affects:
    - k8s/staging/01-obs-rbac.yaml (Wave 3 — must include Prometheus runtime SA ClusterRole before applying)
    - .github/workflows/deploy-observability.yml (Wave 2 — applies k8s/observability/*.yaml)
    - k8s/observability/50-grafana.yaml (13-03 — datasource URL prometheus-server.monitoring.svc:80)

tech_stack:
  added:
    - prometheus-community/prometheus chart v29.11.0 (app v3.12.0)
    - prometheus-community/kube-state-metrics chart v7.4.1 (app v2.19.1)
    - prometheus-community/prometheus-node-exporter chart v4.55.0 (app v1.11.1)
    - prometheus-community/prometheus-postgres-exporter chart v8.0.0 (app v0.19.1)
    - helm v3.17.3 (dev binary at ~/.local/bin/helm — not committed)
  patterns:
    - helm template render-then-commit (DEP-01: git as source of truth; no in-cluster helm)
    - scrapeConfigs static_configs (Pitfall 6: avoids kubernetes_sd where ClusterRole not needed)
    - rbac.create=false + operator-applied ClusterRole in 01-obs-rbac.yaml (Pitfall 2 mitigation)
    - datasourceSecret existingSecret (T-13-04: no inline DSN in git)

key_files:
  created:
    - k8s/observability/values/prometheus-values.yaml
    - k8s/observability/values/kube-state-metrics-values.yaml
    - k8s/observability/values/node-exporter-values.yaml
    - k8s/observability/values/postgres-exporter-values.yaml
    - k8s/observability/10-prometheus.yaml
    - k8s/observability/20-kube-state-metrics.yaml
    - k8s/observability/30-node-exporter.yaml
    - k8s/observability/40-postgres-exporter.yaml
  modified: []

decisions:
  - "rbac.create=false in prometheus values: ClusterRole deferred to 01-obs-rbac.yaml (operator-applied) because obs-ci-deployer is namespace-scoped only"
  - "scrapeConfigs static_configs for all 4 targets: simpler and avoids kubernetes_sd ClusterRole requirement on single-node cluster"
  - "prometheus-pushgateway subchart disabled via prometheus-pushgateway.enabled=false (not pushgateway.enabled — chart v29.11.0 key is prometheus-pushgateway)"
  - "KSM ClusterRole/ClusterRoleBinding left in 20-kube-state-metrics.yaml: required for KSM to read cluster state; obs-ci-deployer needs ClusterRole create permission added in 01-obs-rbac.yaml bootstrap"
  - "postgres-exporter DSN via config.datasourceSecret (name: postgres-monitor-secret, key: dsn) — chart 8.0.0 native existing-secret field"

commits:
  - hash: 7428c08
    message: "feat(13-02): add helm values files for 4 observability charts"
  - hash: 0b16f2d
    message: "feat(13-02): fix prometheus-values.yaml — disable pushgateway/ClusterRole, correct scrapeConfigs"
  - hash: 3fca427
    message: "feat(13-02): render 4 observability manifests via helm template (DEP-01, MET-01/02/03)"
---

# Phase 13 Plan 02: Helm Render — Prometheus + Exporters Summary

**One-liner:** Helm chart v29.11.0/7.4.1/4.55.0/8.0.0 rendered into committed static YAML under k8s/observability/ — 4 values files + 4 manifests, validate-obs-manifests.py passes, Prometheus wired to pre-created SA with 15d+5GB retention on 8Gi PVC, all 4 scrape targets static_configs, postgres-exporter DSN from postgres-monitor-secret.

## What Was Built

| File | Kind(s) | Key config |
|------|---------|-----------|
| `k8s/observability/10-prometheus.yaml` | ConfigMap, PVC, Service, Deployment | SA=prometheus, retention 15d+5GB, PVC 8Gi, obs-background, 5 scrape jobs, no ClusterRole |
| `k8s/observability/20-kube-state-metrics.yaml` | SA, ClusterRole, ClusterRoleBinding, Service, Deployment | obs-background, ClusterIP:8080, app v2.19.1 |
| `k8s/observability/30-node-exporter.yaml` | SA, Service, DaemonSet | obs-background, ClusterIP:9100, app v1.11.1 |
| `k8s/observability/40-postgres-exporter.yaml` | SA, Service, Deployment | obs-background, ClusterIP:9187, DSN from postgres-monitor-secret, app v0.19.1 |

### Helm render commands (reproducible)

```bash
export PATH="$HOME/.local/bin:$PATH"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm template prometheus prometheus-community/prometheus \
  --version 29.11.0 --namespace monitoring \
  --values k8s/observability/values/prometheus-values.yaml \
  > k8s/observability/10-prometheus.yaml

helm template kube-state-metrics prometheus-community/kube-state-metrics \
  --version 7.4.1 --namespace monitoring \
  --values k8s/observability/values/kube-state-metrics-values.yaml \
  > k8s/observability/20-kube-state-metrics.yaml

helm template node-exporter prometheus-community/prometheus-node-exporter \
  --version 4.55.0 --namespace monitoring \
  --values k8s/observability/values/node-exporter-values.yaml \
  > k8s/observability/30-node-exporter.yaml

helm template postgres-exporter prometheus-community/prometheus-postgres-exporter \
  --version 8.0.0 --namespace monitoring \
  --values k8s/observability/values/postgres-exporter-values.yaml \
  > k8s/observability/40-postgres-exporter.yaml
```

### Scrape targets in prometheus.yml (ConfigMap)

| job_name | target FQDN | port | requirement |
|----------|------------|------|-------------|
| prometheus | localhost:9090 | 9090 | self-scrape |
| kube-state-metrics | kube-state-metrics.monitoring.svc:8080 | 8080 | MET-02 |
| node-exporter | node-exporter.monitoring.svc:9100 | 9100 | MET-02 |
| postgres-exporter | postgres-exporter.monitoring.svc:9187 | 9187 | MET-03 |
| rabbitmq | rabbitmq.solid-stats-staging.svc:15692 | 15692 | MET-04 (cross-ns) |

### Resource sizing committed

| Workload | CPU req/limit | Mem req/limit | PriorityClass |
|----------|--------------|---------------|---------------|
| Prometheus | 100m/500m | 256Mi/512Mi | obs-background |
| kube-state-metrics | 10m/100m | 32Mi/128Mi | obs-background |
| node-exporter | 10m/100m | 20Mi/64Mi | obs-background |
| postgres-exporter | 10m/50m | 32Mi/64Mi | obs-background |

Total requests: 130m CPU / 340Mi memory — well within Phase 12 headroom constraint (~2.5Gi available).

## Tasks

### Task 1 — Install helm + author 4 values files

Downloaded helm v3.17.3 to `~/.local/bin/helm` (not committed — dev tool only). Added `prometheus-community` repo. Used `helm show values` to confirm chart schemas before authoring.

Confirmed (deviation-corrected):
- Chart v29.11.0 uses `prometheus-pushgateway.enabled` not `pushgateway.enabled`
- SA field is `serviceAccounts.server.create/name` not `server.serviceAccount.*`
- postgres-exporter existingSecret field: `config.datasourceSecret.name/key`

### Task 2 — Render 4 manifests (DEP-01, MET-01/02/03)

Three render iterations were needed before final clean output:

1. First render: pushgateway workload appeared (wrong values key); ClusterRole in prometheus (rbac.create not set)
2. Second render: ClusterRole removed; pushgateway job still in ConfigMap (default scrapeConfigs not disabled)
3. Third render (final): all kubernetes_sd jobs disabled via scrapeConfigs map; pushgateway job removed; 5 clean job_names only

Final `python3 scripts/validate-obs-manifests.py` output:
```
ok: validated 8 manifest file(s) under k8s/observability
=== obs manifest validation PASSED ===
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wrong pushgateway subchart values key**
- **Found during:** Task 2 first render — pushgateway Deployment appeared despite `pushgateway.enabled: false`
- **Issue:** Chart v29.11.0 subchart key is `prometheus-pushgateway`, not `pushgateway`
- **Fix:** Changed to `prometheus-pushgateway.enabled: false`; also added `prometheus-pushgateway: enabled: false` to scrapeConfigs to drop the residual pushgateway job from ConfigMap
- **Files modified:** `k8s/observability/values/prometheus-values.yaml`
- **Commit:** 0b16f2d

**2. [Rule 1 - Bug] Prometheus ClusterRole rendered despite intent to skip**
- **Found during:** Task 2 first render — `kind: ClusterRole` present in 10-prometheus.yaml
- **Issue:** `server.serviceAccount.create: false` does not suppress ClusterRole; separate `rbac.create: false` is required
- **Fix:** Added `rbac.create: false` to values; confirmed ClusterRole absent in re-render
- **Files modified:** `k8s/observability/values/prometheus-values.yaml`
- **Commit:** 0b16f2d

**3. [Rule 1 - Bug] Default kubernetes_sd scrapeConfigs present in rendered ConfigMap**
- **Found during:** Task 2 second render — kubernetes-api-servers, kubernetes-nodes etc. jobs present
- **Issue:** Chart merges `serverFiles.prometheus.yml` with its own scrapeConfigs template; to disable jobs, must set `scrapeConfigs.<name>.enabled: false` at the chart values level
- **Fix:** Moved scrape job config from `serverFiles.prometheus.yml` to chart `scrapeConfigs` map with `enabled: false` for all kubernetes_sd jobs
- **Files modified:** `k8s/observability/values/prometheus-values.yaml`
- **Commit:** 0b16f2d

**4. [Rule 2 - Missing critical] KSM ClusterRole/ClusterRoleBinding in rendered YAML**
- **Found during:** Task 2 final check
- **Issue:** `20-kube-state-metrics.yaml` contains ClusterRole/ClusterRoleBinding (KSM needs cluster-read to function); obs-ci-deployer is namespace-scoped and cannot apply these
- **Status:** Left in rendered YAML (correct — KSM requires it). This means `obs-ci-deployer` Role must include `create/patch/delete clusterroles/clusterrolebindings` OR these resources must be moved to `01-obs-rbac.yaml` (operator-applied). Tracked as operator action before first apply.
- **Deferred to:** 13-04 (RBAC bootstrap) — add KSM ClusterRole to 01-obs-rbac.yaml or extend obs-ci-deployer permissions

## Known Stubs

None — values files are authoritative; rendered YAML is complete. No data flows to UI in this plan.

## Threat Flags

None beyond what is in the plan's threat model. KSM ClusterRole presence in committed YAML is expected (no secret values; cluster-read only).

## Self-Check

- [x] `k8s/observability/values/prometheus-values.yaml` exists, contains `15d`, `obs-background`, `serviceAccounts.server.create: false/name: prometheus`, 4 static_configs targets incl rabbitmq cross-ns FQDN
- [x] `k8s/observability/values/kube-state-metrics-values.yaml` exists, `fullnameOverride: kube-state-metrics`, `obs-background`
- [x] `k8s/observability/values/node-exporter-values.yaml` exists, `fullnameOverride: node-exporter`, `obs-background`
- [x] `k8s/observability/values/postgres-exporter-values.yaml` exists, `config.datasourceSecret: {name: postgres-monitor-secret, key: dsn}`, no inline DSN
- [x] `k8s/observability/10-prometheus.yaml` exists, `serviceAccountName: prometheus`, `--storage.tsdb.retention.time=15d`, no `kind: ClusterRole`
- [x] `k8s/observability/20-kube-state-metrics.yaml` exists, `obs-background`, Service on 8080
- [x] `k8s/observability/30-node-exporter.yaml` exists, `DaemonSet`, `obs-background`, Service on 9100
- [x] `k8s/observability/40-postgres-exporter.yaml` exists, `obs-background`, `postgres-monitor-secret` ref, no inline DSN
- [x] `python3 scripts/validate-obs-manifests.py` exits 0 (8 manifest files validated)
- [x] Commits 7428c08, 0b16f2d, 3fca427 exist in git log

## Self-Check: PASSED
