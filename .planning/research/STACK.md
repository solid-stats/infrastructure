# Stack Research

**Domain:** Self-hosted Kubernetes observability stack (metrics + logs + error tracking)
**Researched:** 2026-06-13
**Confidence:** HIGH (chart versions verified via GitHub Chart.yaml / ArtifactHub; resource figures derived from known component baselines and official documentation)

---

## Decision 1: kube-prometheus-stack vs Standalone Charts

**Recommendation: standalone `prometheus` chart + separate `grafana` chart.**

Reason: the deploy model is `helm template` → `kubectl apply` with no in-cluster Helm controller. kube-prometheus-stack installs the Prometheus Operator and ~14 CRDs (AlertmanagerConfig, Alertmanager, PodMonitor, Probe, PrometheusAgent, PrometheusRule, ScrapeConfig, ServiceMonitor, ThanosRuler, etc.). CRDs are **not** rendered by `helm template` — they live in the `crds/` subchart and are applied as part of `helm install`. When you strip Helm from the loop, you must apply CRDs separately with `kubectl apply --server-side` before the main manifest set lands, and then every chart upgrade that touches CRD schemas requires the same manual server-side apply (some CRDs exceed the 256 KiB annotation limit and fail without `--server-side`). This is operationally friction every upgrade.

The standalone `prometheus` chart (prometheus-community/prometheus) deploys a plain Deployment / ConfigMap / Service — no operator, no CRDs, no ServiceMonitor objects. Grafana, kube-state-metrics, and node-exporter are available as thin separate charts from the same repo. Alertmanager ships as an optional subchart of `prometheus` (disable it via `alertmanager.enabled=false`). The rendered manifest set is pure Kubernetes primitives that `kubectl apply` handles cleanly every time.

The **only** cost is that ServiceMonitor/PodMonitor auto-discovery is unavailable; scrape configs must be written manually in `prometheus.yml`. For a single-node staging cluster with ~7 scrape targets (node, cadvisor, kube-state-metrics, postgres-exporter, rabbitmq via pod-annotation, loki, glitchtip if desired), this is a non-issue.

**What to disable in kube-prometheus-stack if you end up forced to use it:**
`alertmanager.enabled=false`, `thanosRuleNamespaceSelector=null`, `prometheus.prometheusSpec.replicas=1`, `grafana.sidecar.dashboards.enabled=false` (use pre-provisioned ConfigMaps instead), `prometheusOperator.tls.enabled=false`.

---

## Recommended Stack — Pinned Version Table

### Metrics Stack

| Component | Chart | Chart Repo | Chart Version | App/Image Version |
|-----------|-------|------------|--------------|-------------------|
| Prometheus | `prometheus` | prometheus-community | **29.11.0** | v3.12.0 |
| Grafana | `grafana` | grafana-community | **12.4.4** | (included in kps subchart; standalone grafana-community chart is 12.4.4 → Grafana 11.x) |
| kube-state-metrics | `kube-state-metrics` | prometheus-community | **7.4.1** | 2.19.1 |
| node-exporter | `prometheus-node-exporter` | prometheus-community | **4.55.0** | 1.11.1 |

**Chart repo URLs:**
- `https://prometheus-community.github.io/helm-charts`
- `https://grafana.github.io/helm-charts` (legacy, being migrated)
- `https://grafana-community.github.io/helm-charts` (new, use for Grafana + Loki)

### Log Stack

| Component | Chart | Chart Repo | Chart Version | App/Image Version |
|-----------|-------|------------|--------------|-------------------|
| Loki | `loki` | grafana-community | **17.3.4** | 3.7.2 |
| Grafana Alloy | `alloy` | grafana | **1.10.0** | v1.17.0 |

### Error Tracking

| Component | Chart | Chart Repo | Chart Version | App/Image Version |
|-----------|-------|------------|--------------|-------------------|
| GlitchTip | official Helm chart | `https://gitlab.com/api/v4/projects/16325141/packages/helm/stable` | **8.2.0** | glitchtip v6.1.4 |
| Valkey (cache/queue) | `valkey` | `https://valkey.io/valkey-helm/` | **~0.9.2** | Valkey 7.x |
| PostgreSQL for GlitchTip | managed externally (see note) | — | — | postgres:17-alpine |

**GlitchTip PostgreSQL note:** Chart 6.0+ dropped Bitnami postgres. The official chart now expects an external PostgreSQL connection string or optionally bundles Valkey via the valkey.io chart. For this cluster, run a dedicated `postgres:17-alpine` StatefulSet in the `error-tracking` namespace — it mirrors the pattern already used for the app's PostgreSQL and avoids pulling in a heavyweight operator (CNPG or Zalando). The GlitchTip chart accepts `glitchtip.database.existingSecret`.

**Valkey note (GlitchTip 5.2+ option):** Setting `VALKEY_URL=""` makes GlitchTip use PostgreSQL as its cache/celery backend (experimental). On a budget node this is viable — saves ~100 MB RSS — but yields slower Celery throughput. For staging/error-only workloads the performance tradeoff is acceptable. Decision: **disable Valkey, use PostgreSQL-only mode** to keep the footprint smaller.

### Exporters

| Component | Chart | Chart Repo | Chart Version | App/Image Version | Notes |
|-----------|-------|------------|--------------|-------------------|-------|
| postgres-exporter | `prometheus-postgres-exporter` | prometheus-community | **8.0.0** | v0.19.1 | targets app PostgreSQL + glitchtip PostgreSQL |
| rabbitmq-exporter | **skip chart — use native plugin** | — | — | RabbitMQ 4 built-in | see note below |

**RabbitMQ exporter note:** The `prometheus-rabbitmq-exporter` chart (v2.1.2) wraps `kbudde/rabbitmq_exporter` which is **deprecated and does not support RabbitMQ 4**. RabbitMQ 4 ships the `rabbitmq_prometheus` plugin natively; it exposes metrics on port 15692 at `/metrics`. The correct approach is a Prometheus scrape job pointing at `rabbitmq.solid-stats-staging.svc:15692` (pod annotation `prometheus.io/scrape: "true"` + `prometheus.io/port: "15692"`). No sidecar exporter needed, no separate chart needed.

---

## Resource Budget Table

Target: fit ~2–3 GB working set for the new observability namespace so the node survives on 8 GB + swap alongside the existing app workloads (~6.2 GB currently committed).

### Per-Component Resource Requests / Limits

| Component | CPU Request | CPU Limit | Mem Request | Mem Limit | Replicas | Notes |
|-----------|------------|-----------|-------------|-----------|---------|-------|
| Prometheus server | 100m | 500m | 512Mi | 768Mi | 1 | 7d retention; ~5 active series from small cluster; TSDB head ~200 MB |
| Grafana | 50m | 200m | 128Mi | 256Mi | 1 | No sidecar dashboard loader; pre-provision via ConfigMaps |
| kube-state-metrics | 10m | 100m | 64Mi | 128Mi | 1 | Lightweight API watcher |
| node-exporter | 10m | 50m | 32Mi | 64Mi | 1 (DaemonSet, 1 node) | Single node; HostPID, HostNetwork required |
| Loki | 100m | 300m | 256Mi | 384Mi | 1 | Monolithic mode; filesystem storage; 7d compactor retention |
| Grafana Alloy | 50m | 200m | 64Mi | 128Mi | 1 (DaemonSet, 1 node) | Logs only; no metrics pipeline, no traces |
| GlitchTip web | 50m | 200m | 128Mi | 256Mi | 1 | Django app; errors-only, no APM |
| GlitchTip worker | 50m | 200m | 128Mi | 256Mi | 1 | Celery worker |
| GlitchTip migrate (Job) | 50m | 200m | 128Mi | 256Mi | ephemeral | Runs once on deploy |
| GlitchTip PostgreSQL | 50m | 200m | 128Mi | 256Mi | 1 | Dedicated StatefulSet; small error-tracking DB |
| postgres-exporter | 10m | 50m | 32Mi | 64Mi | 1 | Targets both PG instances |

**Totals (steady-state, excluding migrate Job):**

| | CPU Request | CPU Limit | Mem Request | Mem Limit |
|--|------------|-----------|-------------|-----------|
| Sum | **490m** | **2000m** | **1,472Mi (~1.44 GB)** | **2,560Mi (2.5 GB)** |

The 2.5 GB ceiling fits a node that gains swap (planned: 2–4 GB swap). Existing app workloads request ~1.5 GB and run at ~6.2 GB committed today. Adding 1.44 GB request + up to 2.5 GB headroom is the tightest part; the swap backstop absorbs burst. The target 2–3 GB new working set is achieved.

**Budget-blowing risks and mitigations:**

| Component | Risk | Mitigation |
|-----------|------|-----------|
| Prometheus | TSDB head grows with series count; k3s produces ~3-5k series | Set `--storage.tsdb.retention.time=7d` AND `--storage.tsdb.retention.size=4GB` (belt+suspenders); set `--storage.tsdb.wal-compression` |
| Grafana Alloy | log volume spike on busy period; allocates buffers per-stream | Set `loki.write.batch_size = 102400` (100 KB); limit streams per pod in pipeline |
| GlitchTip web | Django startup + gunicorn workers eat RAM | Set `GUNICORN_WORKERS=2` (or 1 for staging); RAM peaks at startup |
| Loki | chunks accumulate faster than compactor runs if retention is misconfigured | Use `compactor.retention_enabled: true` + `limits_config.retention_period: 168h` (7d) |

**Components to explicitly disable / exclude:**
- **Alertmanager** — disable in `prometheus` chart (`alertmanager.enabled: false`). No external alerting in v1.
- **Thanos sidecar** — not applicable (standalone prometheus chart; sidecar only exists in kube-prometheus-stack).
- **Prometheus Operator** — excluded by choosing standalone chart.
- **Loki ruler / query-scheduler / distributor** — not present in monolithic mode.
- **Loki self-monitoring / meta-monitoring** — disable (`monitoring.selfMonitoring.enabled: false`, `monitoring.lokiCanary.enabled: false`).
- **Loki gateway (nginx)** — disable (`gateway.enabled: false`); Alloy writes directly to Loki ClusterIP.
- **Alloy metrics pipeline** — disable; configure only log collection to Loki.
- **GlitchTip Valkey** — disable (PostgreSQL-only cache mode via `VALKEY_URL=""`).
- **GlitchTip celery beat** — removed in chart 8.0.0; no separate beat pod needed.
- **GlitchTip open registration** — `GLITCHTIP_MAX_USER_EMAILS=0` or closed-registration env var.

---

## PVC Sizing

**Constraint: `local-path` StorageClass has `allowVolumeExpansion: false`. Size right the first time. 31 GB free disk.**

| PVC | Component | Size | Rationale |
|-----|-----------|------|-----------|
| prometheus-data | Prometheus TSDB | **10 Gi** | 7-day retention + WAL; ~5k series at 2 bytes/sample × 15s interval × 7 days × 5000 series ≈ 700 MB raw + WAL + 2× safety headroom = ~3 GB; 10 Gi leaves room for series growth and avoids needing an emergency resize |
| loki-data | Loki chunks + index | **8 Gi** | 7-day log retention; ~50 MB/day of structured k3s logs at moderate verbosity × 7 = 350 MB; 8 Gi provides 20× headroom for log spikes and index overhead |
| glitchtip-postgres-data | GlitchTip PostgreSQL | **5 Gi** | Error events DB; errors-only ingestion, no APM, no log ingestion; should stay under 1 GB even after months; 5 Gi is comfortable |

**Total PVC consumption: 23 Gi of 31 Gi free. Leaves ~8 Gi for existing PVCs (postgres-data 20 Gi already claimed, rabbitmq-data 5 Gi already claimed) plus OS/app headroom.** Verify against `df -h` on the node before apply.

**Note on existing PVCs:** The app's `postgres-data` (20 Gi) and `rabbitmq-data` (5 Gi) are already provisioned. The 31 Gi free refers to unallocated disk, not unbound PVCs. Confirm with `kubectl get pv` before claiming new storage.

---

## Minimal Values Configuration Snippets

### Prometheus (`values-prometheus.yaml`)

```yaml
# Disable alertmanager — no external alerting in v1
alertmanager:
  enabled: false

# Disable pushgateway — not needed
prometheus-pushgateway:
  enabled: false

# Prometheus server
server:
  retention: "7d"
  retentionSize: "4GB"
  global:
    scrape_interval: 30s        # 30s is fine for staging; halves series write rate vs 15s default
    evaluation_interval: 30s
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 768Mi
  persistentVolume:
    enabled: true
    size: 10Gi
    storageClass: "local-path"
  extraFlags:
    - "--storage.tsdb.wal-compression"

# kube-state-metrics subchart
kube-state-metrics:
  enabled: true
  resources:
    requests:
      cpu: 10m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 128Mi

# node-exporter subchart
prometheus-node-exporter:
  enabled: true
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      cpu: 50m
      memory: 64Mi

# Static scrape config — RabbitMQ native plugin (port 15692), Loki, GlitchTip
extraScrapeConfigs: |
  - job_name: 'rabbitmq'
    static_configs:
      - targets: ['rabbitmq.solid-stats-staging.svc.cluster.local:15692']
  - job_name: 'loki'
    static_configs:
      - targets: ['loki.monitoring.svc.cluster.local:3100']
  - job_name: 'postgres-exporter'
    static_configs:
      - targets: ['prometheus-postgres-exporter.monitoring.svc.cluster.local:9187']
```

### Loki (`values-loki.yaml`)

```yaml
deploymentMode: Monolithic

loki:
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  schemaConfig:
    configs:
      - from: "2024-01-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
  storage:
    type: filesystem
  limits_config:
    retention_period: 168h    # 7 days
    reject_old_samples: true
    reject_old_samples_max_age: 168h
  compactor:
    retention_enabled: true
    delete_request_store: filesystem

singleBinary:
  replicas: 1
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 300m
      memory: 384Mi
  persistence:
    enabled: true
    size: 8Gi
    storageClass: local-path

# Disable everything not needed for monolithic filesystem mode
minio:
  enabled: false
monitoring:
  selfMonitoring:
    enabled: false
    grafanaAgent:
      installOperator: false
  lokiCanary:
    enabled: false
gateway:
  enabled: false
```

### Grafana Alloy (`values-alloy.yaml`)

```yaml
# DaemonSet log collector — logs only, no metrics pipeline
alloy:
  configMap:
    content: |
      // Discover all pod logs
      discovery.kubernetes "pods" {
        role = "pod"
      }

      discovery.relabel "pod_logs" {
        targets = discovery.kubernetes.pods.targets
        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          target_label  = "namespace"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_name"]
          target_label  = "pod"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_container_name"]
          target_label  = "container"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_label_app"]
          target_label  = "app"
        }
      }

      loki.source.kubernetes "pods" {
        targets    = discovery.relabel.pod_logs.output
        forward_to = [loki.write.default.receiver]
      }

      loki.write "default" {
        endpoint {
          url = "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
        }
      }

controller:
  type: daemonset

resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 128Mi
```

### GlitchTip (`values-glitchtip.yaml`)

```yaml
# GlitchTip 8.2.0 — errors only, no traces, no log ingestion, closed registration
glitchtip:
  # secretKey from Kubernetes Secret via existingSecret
  existingSecret: glitchtip-secret
  # External PostgreSQL (separate StatefulSet in same namespace)
  database:
    existingSecret: glitchtip-db-secret  # KEY: DATABASE_URL
  # Disable Valkey — use PostgreSQL-only cache mode (GlitchTip 5.2+ experimental)
  # Set VALKEY_URL="" to activate
  extraEnv:
    - name: VALKEY_URL
      value: ""
    - name: GUNICORN_WORKERS
      value: "2"
    - name: DEFAULT_FROM_EMAIL
      value: "errors@stats-staging.solid-stats.ru"
    - name: GLITCHTIP_DOMAIN
      value: "https://errors.stats-staging.solid-stats.ru"
    - name: EMAIL_BACKEND
      value: "django.core.mail.backends.console.EmailBackend"  # No SMTP in staging v1

web:
  replicaCount: 1
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

worker:
  replicaCount: 1
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

# Valkey disabled (PostgreSQL-only cache)
valkey:
  enabled: false
```

### GlitchTip PostgreSQL StatefulSet (standalone, not a Helm chart)

```yaml
# Deploy postgres:17-alpine as a StatefulSet in error-tracking namespace
# Standard pattern matching the app's PostgreSQL in solid-stats-staging namespace
# resources:
#   requests: { cpu: 50m, memory: 128Mi }
#   limits:   { cpu: 200m, memory: 256Mi }
# PVC: 5Gi local-path
```

### postgres-exporter (`values-postgres-exporter.yaml`)

```yaml
config:
  datasource:
    # Primary app database
    host: "postgres.solid-stats-staging.svc.cluster.local"
    user: postgres
    # password via existingSecret
    database: ""
    sslmode: disable

serviceMonitor:
  enabled: false    # No Prometheus Operator; use static scrape config in prometheus values

resources:
  requests:
    cpu: 10m
    memory: 32Mi
  limits:
    cpu: 50m
    memory: 64Mi
```

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| standalone `prometheus` chart | `kube-prometheus-stack` | kps requires CRD pre-install step outside `helm template` → painful for render-then-apply model; Operator overhead unnecessary for single-node staging |
| grafana-community `loki` 17.x | grafana `loki-stack` | loki-stack is deprecated; loki-distributed requires object storage |
| Grafana Alloy DaemonSet | Promtail DaemonSet | Promtail is feature-frozen; Alloy is the official successor; Alloy config is more expressive |
| GlitchTip | self-hosted Sentry | Sentry CE requires 4 GB RAM minimum, dozens of containers; far too heavy |
| GlitchTip PostgreSQL-only mode | Valkey sidecar | Saves ~100 MB RSS; acceptable for staging errors-only workload |
| RabbitMQ native prometheus plugin | kbudde rabbitmq_exporter chart | kbudde exporter is deprecated, does not support RabbitMQ 4; native plugin ships with RabbitMQ 4 image already present on the cluster |
| Dedicated GlitchTip PostgreSQL StatefulSet | CloudNativePG operator | CNPG operator adds CRDs + operator pods (~200 MB); overkill for a single small error-tracking DB with no HA requirement |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `prometheus-rabbitmq-exporter` chart | kbudde exporter deprecated, no RabbitMQ 4 support | RabbitMQ native prometheus plugin on port 15692 |
| `loki-stack` chart | Deprecated by Grafana Labs | grafana-community `loki` chart |
| `loki-distributed` chart | Requires object storage (S3/GCS); no filesystem mode | grafana-community `loki` monolithic mode |
| `kube-prometheus-stack` for render-then-apply | CRDs not rendered by `helm template`; manual server-side-apply required on every CRD upgrade | standalone `prometheus` + `grafana` + `kube-state-metrics` + `node-exporter` charts |
| Bitnami postgresql/redis charts for GlitchTip | Bitnami abandoned free charts; chart 6.0+ dropped them | valkey.io chart (if Valkey needed) or PostgreSQL StatefulSet |
| Grafana `grafana` chart (grafana.github.io) | Being migrated to grafana-community after Jan 2026 | grafana-community `grafana` 12.4.4 |
| `alertmanager` | No external alerting in v1; wastes ~50 MB | disable in prometheus values |

---

## Helm Repo Add Commands (render-then-apply workflow)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add glitchtip https://gitlab.com/api/v4/projects/16325141/packages/helm/stable
helm repo add valkey https://valkey.io/valkey-helm/
helm repo update

# Render each chart to a flat manifest
helm template monitoring prometheus-community/prometheus --version 29.11.0 \
  -n monitoring -f values-prometheus.yaml > rendered/prometheus.yaml

helm template monitoring grafana-community/grafana --version 12.4.4 \
  -n monitoring -f values-grafana.yaml > rendered/grafana.yaml

helm template monitoring grafana-community/loki --version 17.3.4 \
  -n monitoring -f values-loki.yaml > rendered/loki.yaml

helm template monitoring grafana/alloy --version 1.10.0 \
  -n monitoring -f values-alloy.yaml > rendered/alloy.yaml

helm template monitoring prometheus-community/kube-state-metrics --version 7.4.1 \
  -n monitoring > rendered/kube-state-metrics.yaml

helm template monitoring prometheus-community/prometheus-node-exporter --version 4.55.0 \
  -n monitoring > rendered/node-exporter.yaml

helm template monitoring prometheus-community/prometheus-postgres-exporter --version 8.0.0 \
  -n monitoring -f values-postgres-exporter.yaml > rendered/postgres-exporter.yaml

helm template errors glitchtip/glitchtip --version 8.2.0 \
  -n error-tracking -f values-glitchtip.yaml > rendered/glitchtip.yaml
```

---

## Version Compatibility Notes

| Component | Compatibility Note |
|-----------|-------------------|
| Loki 3.7.2 + Alloy v1.17.0 | `loki.write` component in Alloy writes to Loki v3 push API at `/loki/api/v1/push` — confirmed compatible |
| Loki 17.x community chart | `SingleBinary` renamed to `Monolithic` since chart 12.0.0; use `deploymentMode: Monolithic` |
| GlitchTip 8.x | Requires Kubernetes 1.29+ (native lifecycle sleep support for shutdown hooks) — k3s v1.35.4 satisfies this |
| GlitchTip 5.2+ PostgreSQL-only mode | Experimental; `VALKEY_URL=""` activates it; acceptable for staging with low error event volume |
| RabbitMQ 4 + native prometheus plugin | Plugin enabled by default in RabbitMQ 4 management image; exposes port 15692; no additional config needed in the RabbitMQ manifest |
| Prometheus v3.x standalone chart | Drops TSDB v1 format (v2 is default since Prometheus 2.x); no migration concerns for fresh install |

---

## Sources

- https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus/Chart.yaml — chart 29.11.0, appVersion v3.12.0 (verified)
- https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-state-metrics/Chart.yaml — chart 7.4.1, app 2.19.1 (verified)
- https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus-node-exporter/Chart.yaml — chart 4.55.0, app 1.11.1 (verified)
- https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus-postgres-exporter/Chart.yaml — chart 8.0.0, app v0.19.1 (verified)
- https://github.com/prometheus-community/helm-charts/blob/main/charts/prometheus-rabbitmq-exporter/Chart.yaml — chart 2.1.2, app 1.0.0 (verified; **not used** — deprecated)
- https://github.com/grafana-community/helm-charts/blob/main/charts/loki/Chart.yaml — chart 17.3.4, app 3.7.2 (verified)
- https://github.com/grafana/alloy/blob/main/operations/helm/charts/alloy/Chart.yaml — chart 1.10.0, app v1.17.0 (verified)
- https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack — 86.2.2 (latest; NOT used)
- https://artifacthub.io/packages/helm/grafana-community/grafana — 12.4.4 (grafana-community)
- https://artifacthub.io/packages/helm/glitchtip/glitchtip — 8.2.0, app v6.1.4 (verified via newreleases.io + ArtifactHub)
- https://glitchtip.com/blog/2025-11-13-glitchtip-5-2-released/ — PostgreSQL-only mode, 256 MB minimum RAM
- https://www.rabbitmq.com/kubernetes/operator/operator-monitoring — RabbitMQ 4 native prometheus plugin on port 15692
- https://github.com/prometheus-community/helm-charts/issues/3038 — CRD management issues with kube-prometheus-stack + kubectl apply
- https://grafana.com/docs/loki/latest/setup/upgrade/upgrade-to-community/ — Loki chart migration to grafana-community (March 2026)

---

*Stack research for: Solid Stats v3.0 Staging Observability Stack*
*Researched: 2026-06-13*
