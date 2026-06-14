# Phase 13: Deploy Pipeline & Metrics Stack — Research

**Researched:** 2026-06-14
**Domain:** Kubernetes observability — Helm-rendered Prometheus + Grafana + exporters, CI deploy pipeline
**Confidence:** MEDIUM (chart versions verified from GitHub; resource sizing from community data + official docs; some sizing values ASSUMED)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Claude's Discretion
Use ROADMAP phase goal, success criteria, and codebase conventions to guide all decisions.

### Hard constraint from Phase 12 live preflight
The staging node is 4 CPU / 7.75Gi RAM with only ~2.5Gi memory available alongside the app
(plus a 2G host swapfile that does NOT back pods). Every observability workload MUST run in
the `monitoring` namespace with `priorityClassName: obs-background` and TIGHT resource
requests/limits, so the scheduler evicts obs before the app under pressure. Deploy via the
obs-ci-deployer path, not the runtime CD glob.

### Deferred Ideas (OUT OF SCOPE)
- Public ingress / TLS (Phase 14)
- Log stack / Loki (Phase 15)
- GlitchTip / error tracking (Phase 16)
- NetworkPolicy enforcement (Phase 17)
- App-side Sentry SDK (Phase 18)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEP-01 | Obs manifests rendered with `helm template`, committed under `k8s/observability/`. | § Helm Render Workflow; § Recommended File Layout |
| DEP-02 | Separate `deploy-observability.yml` CI workflow, own concurrency group, obs-ci-deployer + WireGuard path. | § CI Workflow Design; § Code Examples |
| DEP-03 | Runtime deploy path does not depend on obs deploy succeeding. | § CI Workflow Design — separate jobs/workflows by design |
| DEP-04 | All obs secrets rendered from GitHub env secrets into k8s Secrets; no secret values in git. | § Secret Rendering Strategy |
| MET-01 | Prometheus runs from standalone rendered manifests (no operator/CRDs), tuned scrape interval + bounded retention sized to PVC. | § Standard Stack; § Prometheus Configuration |
| MET-02 | kube-state-metrics and node-exporter run and are scraped. | § Standard Stack; § Scrape Config Design |
| MET-03 | postgres-exporter (app ≥ v0.15.0, non-superuser `pg_monitor` role) exposes PostgreSQL metrics. | § postgres-exporter; § Code Examples |
| MET-04 | RabbitMQ metrics via native `rabbitmq_prometheus` plugin (port 15692). | § RabbitMQ Plugin; § Code Examples |
| MET-05 | Grafana runs with Prometheus as a healthy provisioned datasource. | § Grafana Configuration |
| MET-06 | Standard dashboards provisioned as code, rendering live data. | § Grafana Dashboards |
</phase_requirements>

---

## Summary

Phase 13 deploys the full metrics stack onto the staging k3s cluster using a git-as-source-of-truth model: manifests are rendered once via `helm template` (no in-cluster Helm, no operators, no CRDs) and committed under `k8s/observability/`. A separate `deploy-observability.yml` workflow — its own concurrency group, its own SA token (`obs-ci-deployer` in `monitoring`), the same WireGuard + kubeconfig-setup.sh path — applies them independently of the runtime CD. The runtime `deploy-staging.yml` workflow is unchanged and does not depend on obs deploy status.

The stack has six workloads: Prometheus server, kube-state-metrics, node-exporter (DaemonSet), postgres-exporter, Grafana, and the already-existing RabbitMQ with its native plugin enabled. All run in `monitoring` namespace with `priorityClassName: obs-background`. Total memory budget is ~2.5Gi; the sizing table in § Resource Sizing shows the stack fits within ~1.5Gi working set with ~0.5Gi headroom, leaving room for occasional spikes before eviction kicks in.

The hardest problem is RBAC: `obs-ci-deployer` is namespace-scoped to `monitoring` (can't create ClusterRole/ClusterRoleBinding), but Prometheus's own runtime ServiceAccount needs a ClusterRole to perform kubernetes_sd_configs discovery across namespaces. The solution is to split the bootstrap: Prometheus's ClusterRole + ClusterRoleBinding for its runtime SA is added to `01-obs-rbac.yaml` (operator-applied once) — NOT applied by `obs-ci-deployer` from CI.

**Primary recommendation:** Use `prometheus-community/prometheus` chart v29.11.0 rendered with `helm template --namespace monitoring`, disable sub-charts (alertmanager, pushgateway), inject custom scrapeConfigs via values file. Use `grafana/grafana` chart v10.5.15 with sidecar dashboard provisioning. Vendor dashboard JSONs as ConfigMaps. Render obs secrets from GitHub env secrets via a `render-obs-secrets.py` script mirroring the existing `render-staging-secrets.py` pattern.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Metrics collection (scraping) | Prometheus pod (in-cluster) | — | Pull-based; runs inside monitoring namespace |
| Cluster-state metrics | kube-state-metrics (in-cluster) | — | Reads k8s API; separate Deployment in monitoring |
| Node-level metrics | node-exporter DaemonSet (host-network) | — | Needs host network/PID access; one pod per node |
| PostgreSQL metrics | postgres-exporter (in-cluster) | — | Sidecar-style Deployment in monitoring, connects cross-namespace |
| RabbitMQ metrics | RabbitMQ native plugin (existing pod) | — | Port 15692 on rabbitmq pod; no new pod needed |
| Dashboard rendering | Grafana (in-cluster) | — | Deployment in monitoring; reads Prometheus over ClusterIP |
| Dashboard provisioning | Grafana sidecar + ConfigMaps | — | Watches labeled ConfigMaps; zero UI imports needed |
| Secret injection | CI render script (build-time) | GitHub env secrets | Mirrors render-staging-secrets.py pattern |
| Manifest delivery | CI kubectl apply (obs-ci-deployer) | — | namespace-scoped SA token; no in-cluster Helm |
| RBAC bootstrap (Prometheus runtime SA ClusterRole) | Operator-applied (01-obs-rbac.yaml) | — | ClusterRole is cluster-scoped; obs-ci-deployer is namespace-scoped only |

---

## Standard Stack

### Core
| Library / Image | Version (verified) | Purpose | Why Standard |
|---|---|---|---|
| prometheus-community/prometheus | chart 29.11.0, app v3.12.0 | Prometheus server manifests | Official community chart; no operator/CRDs; widely used [CITED: artifacthub.io] |
| grafana/grafana | chart 10.5.15 | Grafana manifests | Official Grafana chart; sidecar provisioning well-supported [CITED: artifacthub.io] |
| prom/prometheus | v3.12.0 (via chart appVersion) | Prometheus server container | Latest stable v3 track [CITED: github.com/prometheus-community] |
| grafana/grafana | (chart appVersion ~11.x) | Grafana container | Current stable; provisioning API stable [ASSUMED] |
| kube-state-metrics | chart 7.4.1, app 2.19.1 | Cluster-state metrics | Official chart; minimal footprint [CITED: github.com/prometheus-community] |
| prometheus-node-exporter | chart 4.55.0, app 1.11.1 | Node-level metrics DaemonSet | Official chart; standard for host metrics [CITED: github.com/prometheus-community] |
| prometheus-postgres-exporter | chart 8.0.0, app v0.19.1 | PostgreSQL metrics | Official chart; ≥ v0.15.0 requirement met; pg_monitor role support [CITED: github.com/prometheus-community/postgres_exporter] |

> **Note on Prometheus v3:** The `latest` Docker tag still points to v2.x (Docker Hub issue #16805). The chart's appVersion v3.12.0 explicitly pins v3. v3 has minor breaking changes (strict Content-Type scrape validation, PromQL range selector semantics). For this stack all targets use standard exporters that emit correct Content-Type — no compatibility risk. [CITED: prometheus.io/blog/2024/11/14/prometheus-3-0/]

### Alternatives Considered
| Instead of | Could Use | Why Not |
|------------|-----------|---------|
| prometheus-community/prometheus chart | kube-prometheus-stack | Includes Prometheus Operator + CRDs — explicitly excluded by requirement |
| prometheus-community/prometheus chart | Hand-authored Deployment+ConfigMap | More maintenance; chart handles SA, RBAC, PVC, ConfigMap; easier to `helm template` |
| grafana/grafana chart | Bitnami grafana | Bitnami has divergent defaults; official chart is authoritative |
| sidecar dashboard provisioning | Static ConfigMaps via grafana.dashboardProviders | Sidecar auto-discovers new ConfigMaps; no Grafana restart needed for new dashboards |

### Helm Render Command Pattern
```bash
# Render prometheus chart (example — actual values file path in k8s/observability/)
helm template prometheus prometheus-community/prometheus \
  --version 29.11.0 \
  --namespace monitoring \
  --values k8s/observability/values/prometheus-values.yaml \
  > k8s/observability/10-prometheus.yaml

# Render grafana chart
helm template grafana grafana/grafana \
  --version 10.5.15 \
  --namespace monitoring \
  --values k8s/observability/values/grafana-values.yaml \
  > k8s/observability/50-grafana.yaml
```

**Helm is a dev/CI tool only** — not installed in-cluster. Rendered YAML is committed; `helm` binary runs in CI or on dev machine.

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| prometheus-community/prometheus (chart) | artifacthub.io | 6+ yrs | Millions | github.com/prometheus-community/helm-charts | OK | Approved |
| grafana/grafana (chart) | artifacthub.io | 6+ yrs | Millions | github.com/grafana/helm-charts | OK | Approved |
| prom/prometheus (image) | Docker Hub / quay.io | 10+ yrs | Billions | github.com/prometheus/prometheus | OK | Approved |
| grafana/grafana (image) | Docker Hub | 10+ yrs | Billions | github.com/grafana/grafana | OK | Approved |
| kube-state-metrics (chart) | artifacthub.io | 6+ yrs | Millions | github.com/prometheus-community/helm-charts | OK | Approved |
| prometheus-node-exporter (chart) | artifacthub.io | 6+ yrs | Millions | github.com/prometheus-community/helm-charts | OK | Approved |
| prometheus-postgres-exporter (chart) | artifacthub.io | 5+ yrs | Millions | github.com/prometheus-community/postgres_exporter | OK | Approved |
| quay.io/prometheuscommunity/postgres-exporter | quay.io | 5+ yrs | High | github.com/prometheus-community/postgres_exporter | OK | Approved |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious:** none

---

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  GitHub Actions: deploy-observability.yml                        │
│  (own concurrency group: infrastructure-obs-deploy)              │
│  [WireGuard] → [kubeconfig-setup.sh: obs token] → kubectl apply  │
│  render-obs-secrets.py → k8s Secret (no values in git)          │
└──────────────────────┬───────────────────────────────────────────┘
                       │ kubectl apply k8s/observability/
                       ▼
┌───────────────────────────────────────────────────────────────────────┐
│  namespace: monitoring                                                 │
│                                                                        │
│  ┌──────────────┐   scrape :9090   ┌──────────────────────────┐        │
│  │  Prometheus  │ ◄──────────────── │  kube-state-metrics :8080│        │
│  │  (15d TSDB)  │ ◄──────────────── │  node-exporter :9100     │        │
│  │  ClusterIP   │ ◄──────────────── │  postgres-exporter :9187 │        │
│  │  :9090       │ ◄──────────────── │  rabbitmq :15692         │        │
│  └──────┬───────┘   (cross-ns SD)   └──────────────────────────┘        │
│         │                                                                │
│         │ datasource                                                     │
│         ▼                                                                │
│  ┌──────────────┐                                                        │
│  │   Grafana    │ ◄── sidecar watches ConfigMaps (dashboards)           │
│  │   :3000      │ ◄── grafana-secrets (admin password)                  │
│  └──────────────┘                                                        │
└───────────────────────────────────────────────────────────────────────┘
         ▲                     ▲
         │                     │
┌────────┴─────┐   ┌───────────┴────────────────┐
│  port-forward │   │  namespace: solid-stats-staging│
│  operator     │   │  postgres :5432              │
│  validation   │   │  rabbitmq :5672 / :15672 / :15692│
└──────────────┘   └────────────────────────────┘
```

### Recommended File Layout

```
k8s/observability/
├── values/                          # helm values (committed; no secrets)
│   ├── prometheus-values.yaml       # scrapeConfigs, retention, resources
│   ├── kube-state-metrics-values.yaml
│   ├── node-exporter-values.yaml
│   ├── postgres-exporter-values.yaml
│   └── grafana-values.yaml          # sidecar, datasource provisioning
├── dashboards/                      # vendored dashboard JSONs → ConfigMaps
│   ├── node-exporter-full.json      # dashboard ID 1860 / 18603
│   ├── kube-state-metrics.json      # dashboard ID 13332 or modern equiv
│   ├── postgresql.json              # dashboard ID 9628
│   └── rabbitmq-overview.json       # dashboard ID 10991
├── 10-prometheus.yaml               # helm template output
├── 20-kube-state-metrics.yaml       # helm template output
├── 30-node-exporter.yaml            # helm template output
├── 40-postgres-exporter.yaml        # helm template output
├── 50-grafana.yaml                  # helm template output
└── 60-grafana-dashboards.yaml       # dashboard ConfigMaps (hand-authored from JSONs)
```

> **Numeric prefix ordering**: CI applies `find k8s/observability -name '*.yaml' | sort` — prefixes ensure correct creation order (PVC/SA before Deployment).

---

## Resource Sizing

**Total node headroom:** ~2.5Gi. Target: obs stack ≤ 1.5Gi working set (leaves ~1Gi before evictions).

| Workload | Memory Request | Memory Limit | CPU Request | CPU Limit | Rationale |
|---|---|---|---|---|---|
| Prometheus | 256Mi | 512Mi | 100m | 500m | ~4 targets, 30s interval, 15d retention; TSDB blocks ~50k series [ASSUMED] |
| Grafana | 128Mi | 256Mi | 50m | 200m | SQLite backend, no dashboards with heavy queries [ASSUMED] |
| kube-state-metrics | 32Mi | 128Mi | 10m | 100m | Small cluster (~10 objects); official default 64Mi limit [CITED: github.com] |
| node-exporter (DaemonSet) | 20Mi | 64Mi | 10m | 100m | Single node; official kube-prometheus reference: 20/40Mi [CITED: github.com/prometheus-operator] |
| postgres-exporter | 32Mi | 64Mi | 10m | 50m | Lightweight; no expensive custom queries [ASSUMED] |
| **Total (requests)** | **478Mi** | **1064Mi** | **180m** | **950m** | Well within 2.5Gi headroom |

> **ASSUMED values flagged:** All per-workload figures are estimates. Plan 05 (live apply) MUST verify with `kubectl top pods -n monitoring` after first deployment. If any pod approaches its limit, raise the limit before the next deploy — prefer OOM-safety over tightness at this stage.

**RabbitMQ plugin:** No new pod. Plugin runs inside the existing `rabbitmq` container which already has `requests: 512Mi / limits: 2Gi`. No resource change needed; the plugin adds negligible overhead (~10MB RSS). [ASSUMED]

---

## Key Technical Decisions

### 1. Helm Render Workflow (DEP-01)

**Decision:** `helm template` renders YAML locally/in CI → commit → CI applies via `kubectl apply`. No in-cluster Helm, no Tiller, no CRDs.

**Render step runs in CI as part of the PR cycle** — the rendered YAML is committed to git so the cluster state is always auditable from the repo. The `deploy-observability.yml` workflow applies the pre-rendered files (no helm binary needed on deploy runner).

**Alternative considered:** Run `helm template` inside the deploy job and pipe to `kubectl apply` (never commit rendered YAML). Rejected: breaks the "git as source of truth" model — the running cluster state cannot be audited from a PR diff.

### 2. Prometheus RBAC Split (critical)

`obs-ci-deployer` is a **namespace-scoped Role** in `monitoring`. It cannot create ClusterRole or ClusterRoleBinding. But Prometheus needs a ClusterRole to perform `kubernetes_sd_configs` discovery across namespaces (to find node-exporter, kube-state-metrics, and target pods).

**Solution:** Add Prometheus's runtime ServiceAccount ClusterRole + ClusterRoleBinding to `k8s/staging/01-obs-rbac.yaml` (operator-applied bootstrap, already excluded from CI glob). The obs-ci-deployer applies the Prometheus Deployment which references a pre-existing SA with cluster-read permissions.

**Minimum ClusterRole verbs needed for Prometheus SD:**
```yaml
rules:
  - apiGroups: [""]
    resources: ["nodes", "nodes/proxy", "nodes/metrics", "services", "endpoints", "pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["extensions", "networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
    verbs: ["get"]
```

### 3. Scrape Config Design (MET-01, MET-02, MET-03, MET-04)

For a single-node cluster with static targets, **static_configs is simpler and more predictable** than kubernetes_sd_configs for postgres-exporter and rabbitmq. Use kubernetes_sd_configs only where needed (kube-state-metrics endpoint discovery, node-exporter node role).

```yaml
# Prometheus scrape_configs (in values/prometheus-values.yaml)
scrapeConfigs:
  prometheus:
    enabled: true   # self-scrape

  # Disable default kube-api, cadvisor, pushgateway, blackbox jobs:
  kubernetes-apiservers:
    enabled: false
  kubernetes-pods:
    enabled: false
  # ... etc

  kube-state-metrics:
    enabled: true
    static_configs:
      - targets: ["kube-state-metrics.monitoring.svc:8080"]

  node-exporter:
    enabled: true
    static_configs:
      - targets: ["node-exporter.monitoring.svc:9100"]

  postgres-exporter:
    enabled: true
    static_configs:
      - targets: ["postgres-exporter.monitoring.svc:9187"]

  rabbitmq:
    enabled: true
    static_configs:
      - targets: ["rabbitmq.solid-stats-staging.svc:15692"]
```

> **Cross-namespace DNS:** Prometheus in `monitoring` reaches RabbitMQ in `solid-stats-staging` via FQDN `rabbitmq.solid-stats-staging.svc.cluster.local:15692`. Phase 17 NetworkPolicy will add the explicit allow-prometheus-scrape rule; until then, no NetworkPolicy means scraping works.

### 4. Prometheus Retention Sizing (MET-01)

```
retention:       15d
retentionSize:   5GB   (size-based safety cap)
PVC size:        8Gi   (leaves ~3Gi slack for WAL + compaction overhead)
```

With ~50,000 active series (small cluster + 4 targets), 30s scrape interval, 15d retention:
`50000 × (15×86400 / 30) × 2 bytes ≈ 4.3 GB` — fits in an 8Gi PVC with headroom. [ASSUMED — verify with `prometheus_tsdb_head_series` metric after first scrape]

### 5. RabbitMQ Plugin Enablement (MET-04)

The existing `20-rabbitmq.yaml` StatefulSet does NOT have an `enabled_plugins` file mounted. The `rabbitmq:4-management` image ships with management plugin pre-enabled. To add `rabbitmq_prometheus`, mount a ConfigMap as `/etc/rabbitmq/enabled_plugins`:

```yaml
# ConfigMap
data:
  enabled_plugins: |
    [rabbitmq_management,rabbitmq_prometheus].

# StatefulSet volumeMount
- name: enabled-plugins
  mountPath: /etc/rabbitmq/enabled_plugins
  subPath: enabled_plugins

# volumes:
- name: enabled-plugins
  configMap:
    name: rabbitmq-enabled-plugins
```

Expose port 15692 in the Service. This requires patching `20-rabbitmq.yaml` — the change is part of Phase 13 scope (CI applies it from the runtime deploy glob on next push). [CITED: rabbitmq.com/docs/prometheus]

> **Rolling restart impact:** Patching a StatefulSet pod template triggers a rolling restart of the `rabbitmq-0` pod. Downtime ~30s for AMQP consumers. Acceptable for staging.

### 6. postgres-exporter Setup (MET-03)

**Non-superuser pg_monitor role:** `pg_monitor` is a built-in PostgreSQL role (available since PG 10) that grants read access to all `pg_stat_*` views without superuser. No custom permissions needed beyond the grant.

```sql
-- Run once against the app database (solid_stats)
CREATE USER solid_monitor WITH PASSWORD 'XXX';
GRANT pg_monitor TO solid_monitor;
```

The connection string (DATA_SOURCE_NAME) is rendered into a k8s Secret by `render-obs-secrets.py`. The secret is never in git. [CITED: postgresql.org/docs/current/default-roles.html via training knowledge — ASSUMED no official URL verified this session]

Target: `postgresql://solid_monitor:PASSWORD@postgres.solid-stats-staging.svc:5432/solid_stats?sslmode=disable`

**One-time DB setup** is a Wave 0 operator task (run via kubectl exec against postgres-0), not a CI-applied manifest.

### 7. Grafana Provisioning (MET-05, MET-06)

**Datasource:** Provisioned via helm values `grafana.datasources`:
```yaml
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.monitoring.svc:80
        access: proxy
        isDefault: true
```

**Dashboard sidecar:** Set `sidecar.dashboards.enabled: true` and `sidecar.dashboards.label: grafana_dashboard`. Dashboard JSONs stored as ConfigMaps with that label are auto-discovered and loaded without Grafana restart.

**Standard dashboard IDs to vendor:**
| Dashboard | grafana.com ID | Source JSON |
|---|---|---|
| Node Exporter Full | 1860 | grafana.com/grafana/dashboards/1860 |
| Kubernetes / kube-state-metrics | 13332 | grafana.com/grafana/dashboards/13332 [ASSUMED — verify ID] |
| PostgreSQL Database | 9628 | grafana.com/grafana/dashboards/9628 |
| RabbitMQ Overview | 10991 | grafana.com/grafana/dashboards/10991 (official rabbitmq-prometheus repo JSON) |

> Dashboard JSONs must be downloaded and committed as files under `k8s/observability/dashboards/` then wrapped in ConfigMaps. Do NOT import from grafana.com at runtime (requires internet + UI action).

### 8. CI Workflow Design (DEP-02, DEP-03)

Mirror `deploy-staging.yml` structure exactly. Key differences:

| Property | deploy-staging.yml | deploy-observability.yml |
|---|---|---|
| Concurrency group | `infrastructure-staging-deploy` | `infrastructure-obs-deploy` |
| SA token secret | `K8S_TOKEN` | `K8S_OBS_TOKEN` (obs-ci-deployer token) |
| Namespace env | `solid-stats-staging` | `monitoring` |
| Manifest glob | `k8s/staging/*.yaml` | `k8s/observability/*.yaml` |
| Secret render script | `render-staging-secrets.py` | `render-obs-secrets.py` |
| Kubeconfig user | `ci-deployer` | `obs-ci-deployer` |
| Trigger | push to master | push to master (parallel; independent) |
| Runtime deploy dep | — | none (DEP-03: independent) |

The two workflows run in parallel on push to master. A failure in `deploy-observability.yml` does NOT block or cancel `deploy-staging.yml`.

**New GitHub secrets needed:** `K8S_OBS_TOKEN` (obs-ci-deployer SA token from `monitoring` namespace), `K8S_OBS_CA_CERT` (same CA as existing), `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD`.

### 9. Secret Rendering (DEP-04)

New `scripts/render-obs-secrets.py` following the existing pattern:
```python
# Renders (to stdout, piped to kubectl apply):
# - grafana-secrets  (GRAFANA_ADMIN_PASSWORD → admin-password)
# - postgres-monitor-secret  (PG_MONITOR_PASSWORD → dsn)
```

No secret values in git. Script runs in CI deploy job with env vars from GitHub environment secrets.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prometheus server manifests | Custom Deployment YAML | `helm template prometheus-community/prometheus` | Chart handles SA, RBAC, PVC, ConfigMap, liveness probes correctly |
| Grafana server manifests | Custom Deployment YAML | `helm template grafana/grafana` | Sidecar provisioning, ini config, secret mounting all handled |
| kube-state-metrics manifests | Custom Deployment | Chart via `helm template` | ClusterRole list is extensive; chart keeps it correct across KSM versions |
| Dashboard provisioning | Manual Grafana API calls | Grafana sidecar + ConfigMaps | Declarative; idempotent; no UI state |
| postgres-exporter auth | Superuser connection | `pg_monitor` built-in role | Least privilege; pg_monitor covers all needed views |
| RabbitMQ metrics | prometheus-rabbitmq-exporter (deprecated) | Native `rabbitmq_prometheus` plugin | Official; deprecated exporter does not support RabbitMQ 4 |

---

## Common Pitfalls

### Pitfall 1: Prometheus v3 Content-Type strict validation
**What goes wrong:** Prometheus v3 fails scrapes if target responds without `Content-Type: text/plain; version=0.0.4` or `application/openmetrics-text`. Unlike v2 which silently falls back.
**Why it happens:** v3 breaking change (strict scrape protocol enforcement).
**How to avoid:** All four targets (kube-state-metrics, node-exporter, postgres-exporter, rabbitmq native plugin) emit standard Prometheus text format. No action needed. If adding non-standard targets later, check their Content-Type.
**Warning signs:** `scrape_error` in Prometheus targets page with `invalid content type` message.

### Pitfall 2: obs-ci-deployer cannot create ClusterRole
**What goes wrong:** `kubectl apply` from obs-ci-deployer fails on Prometheus's ClusterRole/ClusterRoleBinding — "forbidden: cannot create resource clusterroles".
**Why it happens:** obs-ci-deployer is namespace-scoped (Role, not ClusterRole). ClusterRole is cluster-scoped.
**How to avoid:** Add Prometheus runtime SA ClusterRole + ClusterRoleBinding to `01-obs-rbac.yaml` (operator-applied bootstrap). Verify before first obs deploy with `kubectl auth can-i create clusterroles --as=system:serviceaccount:monitoring:obs-ci-deployer`.
**Warning signs:** `deploy-observability.yml` fails on the manifest apply step with 403.

### Pitfall 3: Helm chart renders wrong namespace
**What goes wrong:** Rendered YAML has `namespace: default` instead of `monitoring` because `--namespace monitoring` was omitted from `helm template`.
**Why it happens:** `helm template` does not infer namespace from context.
**How to avoid:** Always pass `--namespace monitoring --set global.namespaceOverride=monitoring` (chart-dependent). Grep rendered YAML for `namespace:` and assert all values are `monitoring` in CI validation step.
**Warning signs:** Pods scheduled in `default` namespace, missing `priorityClassName: obs-background`.

### Pitfall 4: Grafana SQLite write permissions
**What goes wrong:** Grafana crashes with `permission denied` on SQLite DB file.
**Why it happens:** Grafana image runs as UID 472; PVC may be formatted by root.
**How to avoid:** Set `securityContext.fsGroup: 472` on the Grafana pod spec (chart values: `securityContext.fsGroup: 472`).
**Warning signs:** Grafana pod in CrashLoopBackOff; logs show `FATAL: Failed to start grafana` with sqlite open error.

### Pitfall 5: RabbitMQ enabled_plugins file format
**What goes wrong:** RabbitMQ fails to start with `{error,{bad_return,{{rabbit,start,[normal,[]]},{error,{could_not_start_plugin,rabbitmq_prometheus,...}}}}}`.
**Why it happens:** `enabled_plugins` file must end with a period (`.`) and be an Erlang term list: `[plugin1,plugin2].` — missing period or wrong format.
**How to avoid:** ConfigMap value must be exactly `[rabbitmq_management,rabbitmq_prometheus].` (period included, newline after).
**Warning signs:** rabbitmq-0 pod in CrashLoopBackOff; logs show plugin startup errors.

### Pitfall 6: Prometheus kubernetes_sd scraping cross-namespace
**What goes wrong:** Prometheus discovers no targets; `/targets` shows empty target list.
**Why it happens:** Prometheus SA lacks ClusterRole get/list/watch on pods/services/endpoints cluster-wide. If `kubernetes_sd_configs` is used, the SA must be able to read across namespaces.
**How to avoid:** For this stack: use `static_configs` for postgres-exporter and rabbitmq (simpler, no SD needed). For kube-state-metrics and node-exporter, use static_configs pointing to their ClusterIP Services. Prometheus ClusterRole only needed for self-monitoring node metrics if using `role: node` SD.
**Warning signs:** Prometheus logs `level=error ... msg="Get ... : forbidden"`.

### Pitfall 7: OOM eviction under app load
**What goes wrong:** Prometheus or Grafana pod is OOM-killed during a busy app period.
**Why it happens:** `obs-background` PriorityClass means kubelet evicts these pods first — desired behaviour. But if limits are set too low, the Linux kernel OOM killer kills the pod without kubelet involvement (kernel doesn't respect PriorityClass).
**How to avoid:** Set memory limits to at least 2× the observed idle working set from `kubectl top pods`. The sizing table above is conservative; verify after first deploy.
**Warning signs:** Pod restarts with OOMKilled reason in describe; `kubectl top pods -n monitoring` shows RSS near limit.

### Pitfall 8: Dashboard ConfigMap size limit
**What goes wrong:** Dashboard ConfigMap fails to apply with `Request entity too large`.
**Why it happens:** Kubernetes has a 1 MiB object size limit. Large dashboard JSONs (e.g., Node Exporter Full is ~250 KB) must each be in a separate ConfigMap.
**How to avoid:** One ConfigMap per dashboard JSON, not one ConfigMap for all dashboards. `60-grafana-dashboards.yaml` should be a multi-document YAML with `---` separators, each document a separate ConfigMap.
**Warning signs:** `kubectl apply` error: `etcd cluster is unavailable` or `Request entity too large`.

### Pitfall 9: Render step re-generates non-idempotent resources
**What goes wrong:** Each `helm template` run regenerates Secrets or tokens with new random values, causing unnecessary k8s Secret updates.
**Why it happens:** Some charts generate random values in templates (e.g., cookie secrets). Prometheus chart is clean but Grafana chart may generate a cookie secret.
**How to avoid:** Pin Grafana admin secret via `grafana.adminExistingSecret` pointing to the operator-rendered Secret. Do not let helm template generate credentials.
**Warning signs:** Grafana sessions invalidated on every deploy.

---

## Code Examples

### Prometheus values.yaml (key sections)
```yaml
# Source: prometheus-community/prometheus chart values pattern
# [ASSUMED: structure based on chart v29.11.0 values schema]
server:
  retention: "15d"
  retentionSize: "5GB"
  priorityClassName: obs-background
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  persistentVolume:
    enabled: true
    size: 8Gi
    storageClass: ""   # use cluster default (local-path on k3s)
  securityContext:
    runAsUser: 65534
    runAsNonRoot: true
    runAsGroup: 65534
    fsGroup: 65534
  service:
    type: ClusterIP
    port: 80
    targetPort: 9090

alertmanager:
  enabled: false

pushgateway:
  enabled: false

# kube-state-metrics subchart disabled (deployed separately for tighter control)
kube-state-metrics:
  enabled: false

prometheus-node-exporter:
  enabled: false

scrapeConfigs:
  # prometheus self-scrape (keep enabled)
  # add custom jobs below
```

### Grafana values.yaml (key sections)
```yaml
# Source: grafana/grafana chart values pattern
# [ASSUMED: structure based on chart v10.5.15 schema]
grafana:
  adminExistingSecret: grafana-secrets
  adminUser: admin
  adminPasswordKey: admin-password

persistence:
  enabled: true
  size: 2Gi
  storageClassName: ""  # k3s local-path default

priorityClassName: obs-background

securityContext:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472

resources:
  requests:
    cpu: 50m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi

sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    folder: /var/lib/grafana/dashboards
    provider:
      foldersFromFilesStructure: false

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.monitoring.svc:80
        access: proxy
        isDefault: true
        jsonData:
          timeInterval: "30s"
```

### Dashboard ConfigMap pattern
```yaml
# Source: Grafana provisioning pattern [ASSUMED]
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-node-exporter
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
    app.kubernetes.io/part-of: solid-stats
data:
  node-exporter-full.json: |
    { ... JSON content from grafana.com/grafana/dashboards/1860 ... }
```

### deploy-observability.yml (workflow skeleton)
```yaml
name: Deploy observability stack

on:
  push:
    branches: [master]
  workflow_dispatch:

concurrency:
  group: infrastructure-obs-deploy
  cancel-in-progress: false

permissions:
  contents: read

env:
  K8S_NAMESPACE: monitoring

jobs:
  validate:
    name: Validate
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6
      - name: Validate obs manifests
        run: |
          set -euo pipefail
          test -d k8s/observability
          find k8s/observability -name '*.yaml' | sort
          # Verify no secret values in rendered YAML
          python3 scripts/validate-obs-manifests.py

  deploy:
    name: Deploy to k3s (obs)
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: [validate]
    if: github.event_name == 'push' && github.ref == 'refs/heads/master' || github.event_name == 'workflow_dispatch'
    environment: staging
    steps:
      - uses: actions/checkout@v6
      - name: Install WireGuard tools
        run: sudo apt-get update && sudo apt-get install -y wireguard-tools
      - name: Bring up WireGuard tunnel
        env:
          WG_PRIVATE_KEY: ${{ secrets.WG_PRIVATE_KEY }}
          WG_PEER_PUBLIC_KEY: ${{ secrets.WG_PEER_PUBLIC_KEY }}
          WG_ENDPOINT: ${{ secrets.WG_ENDPOINT }}
          WG_LOCAL_IP: 10.8.0.3/32
        run: bash scripts/wg-tunnel-up.sh
      - name: Setup kubeconfig (obs-ci-deployer)
        env:
          K8S_TOKEN: ${{ secrets.K8S_OBS_TOKEN }}
          K8S_CA_CERT: ${{ secrets.K8S_CA_CERT }}
          K8S_NAMESPACE: monitoring
          K8S_USER_NAME: obs-ci-deployer
          K8S_CONTEXT_NAME: obs-k3s-staging
        run: bash scripts/kubeconfig-setup.sh
      - name: Render and apply obs secrets
        env:
          GRAFANA_ADMIN_PASSWORD: ${{ secrets.GRAFANA_ADMIN_PASSWORD }}
          PG_MONITOR_PASSWORD: ${{ secrets.PG_MONITOR_PASSWORD }}
        run: |
          set -euo pipefail
          tmp=$(mktemp)
          trap 'rm -f "$tmp"' EXIT
          python3 scripts/render-obs-secrets.py > "$tmp"
          kubectl apply -n monitoring -f "$tmp"
      - name: Apply obs manifests
        run: |
          set -euo pipefail
          find k8s/observability -maxdepth 1 -name '*.yaml' | sort \
            | sed 's/^/-f /' | xargs kubectl apply -n monitoring
      - name: Verify rollouts
        run: |
          set -euo pipefail
          kubectl -n monitoring rollout status deployment/prometheus-server --timeout=300s
          kubectl -n monitoring rollout status deployment/grafana --timeout=300s
          kubectl -n monitoring rollout status deployment/kube-state-metrics --timeout=120s
          kubectl -n monitoring rollout status daemonset/node-exporter --timeout=120s
          kubectl -n monitoring rollout status deployment/postgres-exporter --timeout=120s
```

### render-obs-secrets.py (structure)
```python
#!/usr/bin/env python3
# Source: mirrors scripts/render-staging-secrets.py pattern [CITED: existing codebase]
import os, sys, json
from urllib.parse import quote

NAMESPACE = "monitoring"

def required(name):
    v = os.environ.get(name)
    if not v:
        missing.append(name)
        return ""
    return v

missing = []
grafana_password = required("GRAFANA_ADMIN_PASSWORD")
pg_monitor_password = required("PG_MONITOR_PASSWORD")

if missing:
    print(f"Missing: {', '.join(missing)}", file=sys.stderr)
    sys.exit(64)

pg_dsn = f"postgresql://solid_monitor:{quote(pg_monitor_password)}@postgres.solid-stats-staging.svc:5432/solid_stats?sslmode=disable"

# Emit: grafana-secrets, postgres-monitor-secret
# (same YAML secret() helper pattern as render-staging-secrets.py)
```

---

## Obs Bootstrap Extension to 01-obs-rbac.yaml

The following ClusterRole + ClusterRoleBinding for Prometheus's **runtime** ServiceAccount must be added to `k8s/staging/01-obs-rbac.yaml` (operator-applied, NOT from CI). This is required before Phase 13 manifests are applied:

```yaml
---
# Prometheus runtime SA — cluster-read for kubernetes_sd and node metrics
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
  labels:
    app.kubernetes.io/name: prometheus
    app.kubernetes.io/part-of: solid-stats
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-monitoring
  labels:
    app.kubernetes.io/name: prometheus
    app.kubernetes.io/part-of: solid-stats
rules:
  - apiGroups: [""]
    resources: ["nodes", "nodes/proxy", "nodes/metrics", "services", "endpoints", "pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-monitoring
  labels:
    app.kubernetes.io/name: prometheus
    app.kubernetes.io/part-of: solid-stats
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus-monitoring
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: monitoring
```

> The helm chart will reference `serviceAccountName: prometheus` in the rendered Deployment. Set `server.serviceAccount.create: false` and `server.serviceAccount.name: prometheus` in prometheus-values.yaml to use the pre-created SA.

---

## Validation Architecture

> nyquist_validation is enabled (config.json).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Bash + kubectl (no unit test framework needed — all validation is live-cluster checks) |
| Config file | `scripts/validate-phase-13.sh` (to be created in Wave 0) |
| Quick run command | `bash scripts/validate-phase-13.sh --quick` |
| Full suite command | `bash scripts/validate-phase-13.sh` |

### Phase Requirements → Validation Map

| Req ID | Behavior | Test Type | Automated Command / Check | File Exists? |
|--------|----------|-----------|---------------------------|-------------|
| DEP-01 | Manifests in k8s/observability/ committed | static | `test -d k8s/observability && find k8s/observability -name '*.yaml' | wc -l` ≥ 5 | ❌ Wave 0 |
| DEP-02 | deploy-observability.yml exists with own concurrency group | static | `grep 'infrastructure-obs-deploy' .github/workflows/deploy-observability.yml` | ❌ Wave 0 |
| DEP-03 | deploy-staging.yml has no dependency on obs deploy | static | `grep -v 'obs' .github/workflows/deploy-staging.yml` (no obs dependency) | ✅ (verify) |
| DEP-04 | No secret values in committed YAML | static | `python3 scripts/validate-obs-manifests.py` (grep for known secret patterns) | ❌ Wave 0 |
| MET-01 | Prometheus pod Running + /targets page accessible | live | `kubectl -n monitoring get pod -l app=prometheus-server -o jsonpath='{.items[0].status.phase}'` == Running | ❌ Wave 0 |
| MET-01 | Prometheus retention configured | live | `kubectl -n monitoring exec deploy/prometheus-server -- wget -qO- localhost:9090/api/v1/status/config` contains `15d` | ❌ Wave 0 |
| MET-02 | kube-state-metrics target UP | live | `kubectl -n monitoring exec deploy/prometheus-server -- wget -qO- 'localhost:9090/api/v1/targets' | python3 -c "import sys,json; t=json.load(sys.stdin)['data']['activeTargets']; [assert a['health']=='up' for a in t if 'kube-state' in a['labels'].get('job','')]"` | ❌ Wave 0 |
| MET-02 | node-exporter target UP | live | Same target query, job=node-exporter | ❌ Wave 0 |
| MET-03 | postgres-exporter target UP | live | Same target query, job=postgres-exporter; + `pg_up == 1` | ❌ Wave 0 |
| MET-04 | RabbitMQ target UP (port 15692) | live | Same target query, job=rabbitmq; + `rabbitmq_identity_info` metric present | ❌ Wave 0 |
| MET-05 | Grafana datasource healthy | live | `kubectl -n monitoring port-forward svc/grafana 3000:80 & sleep 2; curl -s -u admin:PASSWORD localhost:3000/api/datasources/1/health` status=OK | ❌ Wave 0 |
| MET-06 | All 4 dashboards provisioned | live | `curl -s -u admin:PASSWORD localhost:3000/api/search?query=` returns ≥4 dashboards | ❌ Wave 0 |
| MET-06 | Dashboards render live data | manual | Operator confirms panels show non-zero data after port-forward to Grafana | manual only |

### Sampling Rate
- **Per task commit:** `bash scripts/validate-obs-manifests.py` (static: no secrets in git, files present)
- **Per wave merge:** Full `bash scripts/validate-phase-13.sh` against live cluster
- **Phase gate:** All targets UP + Grafana datasource healthy + dashboards provisioned before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `scripts/validate-phase-13.sh` — live validation script covering all MET-01..06
- [ ] `scripts/validate-obs-manifests.py` — static checks: no secrets, namespace=monitoring on all resources, priorityClassName=obs-background on all pod specs
- [ ] Dashboard JSON files to vendor from grafana.com (1860, 9628, 10991, and kube-state-metrics equiv)
- [ ] `k8s/observability/values/` directory with all values YAML files
- [ ] `scripts/render-obs-secrets.py` — secret renderer

---

## Security Domain

> security_enforcement: true, ASVS level 2.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (Grafana login) | Admin password from k8s Secret; no anonymous access |
| V3 Session Management | partial | Grafana cookie secret pinned via existingSecret (Pitfall 9) |
| V4 Access Control | yes | obs-ci-deployer namespace-scoped; Prometheus SA ClusterRole read-only |
| V5 Input Validation | no | No user-facing input in this phase |
| V6 Cryptography | partial | TLS deferred to Phase 14; internal traffic on ClusterIP (no TLS needed for monitoring-only internal access) |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Grafana admin password in git | Information Disclosure | render-obs-secrets.py from GitHub env; never in committed YAML |
| postgres-exporter superuser DSN | Elevation of Privilege | Use pg_monitor built-in role; credential from k8s Secret only |
| Prometheus unauthenticated /metrics | Information Disclosure | ClusterIP only; no Ingress in Phase 13; port-forward for operator access |
| obs-ci-deployer over-privileged | Elevation of Privilege | Namespace-scoped Role; no cluster-scoped verbs except those added to 01-obs-rbac.yaml bootstrap |
| RabbitMQ port 15692 exposed externally | Information Disclosure | Service selector-based; ClusterIP only; not in Service spec for external access |
| Secret values in rendered YAML committed | Information Disclosure | `validate-obs-manifests.py` grep check in CI validate job |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Prometheus Operator / kube-prometheus-stack | Standalone `helm template` | Requirements decision | No CRDs; git-as-source-of-truth; simpler RBAC |
| prometheus-rabbitmq-exporter | Native `rabbitmq_prometheus` plugin | RabbitMQ 4.x | Deprecated exporter dropped; plugin has better metrics coverage |
| Grafana UI dashboard import | Sidecar + ConfigMap provisioning | Grafana 5+ | Declarative; survives pod restarts; auditable in git |
| Prometheus v2 | Prometheus v3 (v3.12.0) | Nov 2024 | Strict Content-Type; better OTLP support; PromQL range semantics change |
| Hardcoded helm values in workflow | Committed values YAML + `helm template` pre-render | Project decision | Rendered YAML in git = auditable cluster state |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Prometheus memory footprint ~256Mi working set for this cluster size | Resource Sizing | OOM eviction; raise limit or retention |
| A2 | Grafana memory footprint ~128Mi for minimal dashboards + SQLite | Resource Sizing | OOM; raise limit |
| A3 | postgres-exporter ~32Mi RSS | Resource Sizing | OOM; raise limit |
| A4 | RabbitMQ plugin adds ~10MB RSS to existing pod | Resource Sizing | Rabbitmq-0 closer to 2Gi limit; monitor closely |
| A5 | `pg_monitor` is available in PostgreSQL 17 Alpine image (postgres:17-alpine) | postgres-exporter | Setup fails; pg_monitor exists since PG10 so risk is very low |
| A6 | Grafana chart appVersion is ~11.x | Standard Stack | If older, some provisioning API may differ; verify with `helm show chart grafana/grafana` |
| A7 | kube-state-metrics dashboard ID for modern k8s is 13332 | Grafana Dashboards | Wrong dashboard; verify correct ID at grafana.com before committing JSON |
| A8 | `server.serviceAccount.create: false` + `server.serviceAccount.name: prometheus` is valid in chart v29.11.0 | Prometheus RBAC | If chart ignores this, it creates its own SA without the ClusterRoleBinding; Prometheus can't do SD |
| A9 | Scrape interval 30s is sufficient for all four targets | Prometheus config | Some dashboards expect 15s; check dashboard requirements |

---

## Open Questions

1. **Prometheus SA name in rendered chart**
   - What we know: chart renders a ServiceAccount; name defaults to release name + `-server`
   - What's unclear: whether `server.serviceAccount.name` overrides the full name or just suffix
   - Recommendation: run `helm template` locally first with `--debug` to confirm SA name before adding ClusterRoleBinding

2. **k3s StorageClass for obs PVCs**
   - What we know: k3s ships with `local-path` StorageClass as default
   - What's unclear: whether the PVC for Prometheus (8Gi) and Grafana (2Gi) will be scheduled on a node with sufficient disk
   - Recommendation: run `df -h` on the node before Wave 2; `kubectl get storageclass` to confirm default

3. **obs-ci-deployer token extraction**
   - What we know: the token Secret `obs-ci-deployer-token` exists in `monitoring` (created in Phase 12)
   - What's unclear: operator needs to extract the token value and add it as `K8S_OBS_TOKEN` GitHub secret
   - Recommendation: `kubectl -n monitoring get secret obs-ci-deployer-token -o jsonpath='{.data.token}' | base64 -d` — document as operator bootstrap step

4. **RabbitMQ Service port 15692 — needs new Service port**
   - What we know: current `20-rabbitmq.yaml` Service only exposes 5672 (amqp) and 15672 (management)
   - What's unclear: must add `15692` port to the Service OR scrape pod IP directly
   - Recommendation: add port 15692 to the `rabbitmq` Service in `20-rabbitmq.yaml` — cleaner than pod-IP scraping; CI will apply it on next push

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| k3s (staging cluster) | All workloads | ✓ | Phase 12 confirmed live | — |
| `monitoring` namespace | All obs workloads | ✓ | Created in Phase 12 | — |
| `obs-ci-deployer` SA + token | deploy-observability.yml | ✓ | Created in Phase 12 | — |
| `obs-background` PriorityClass | All obs pods | ✓ | Created in Phase 12 | — |
| `local-path` StorageClass | Prometheus + Grafana PVCs | ✓ [ASSUMED] | k3s default | — |
| Helm (dev machine / render CI) | `helm template` render step | ? | Not verified this session | Hand-author YAML if unavailable |
| `postgres` Service (solid-stats-staging) | postgres-exporter DNS target | ✓ | Running in Phase 12 | — |
| `rabbitmq` Service (solid-stats-staging) | RabbitMQ scrape | ✓ | Running; needs port 15692 added | — |
| GitHub secrets `K8S_OBS_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD` | deploy-observability.yml | ✗ | Not yet created | Operator must add before first obs deploy |

**Missing dependencies with no fallback:**
- GitHub secrets `K8S_OBS_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD` — operator must add to GitHub `staging` environment before the workflow can run.
- Helm binary — needed on dev machine (or CI job that re-renders) to regenerate `k8s/observability/*.yaml`. If not available, alternatives: download helm as a CI step, or use the chart's raw templates directly.

**Missing dependencies with fallback:**
- None.

---

## Sources

### Primary (MEDIUM confidence)
- [github.com/prometheus-community/helm-charts](https://github.com/prometheus-community/helm-charts) — chart versions (prometheus 29.11.0/v3.12.0, kube-state-metrics 7.4.1/2.19.1, node-exporter 4.55.0/1.11.1, postgres-exporter 8.0.0/v0.19.1) confirmed from Chart.yaml via curl
- [github.com/prometheus-community/postgres_exporter/releases](https://github.com/prometheus-community/postgres_exporter/releases) — v0.17.0 (Feb 2025), v0.19.1 latest; PG17 support confirmed
- [rabbitmq.com/docs/prometheus](https://www.rabbitmq.com/docs/prometheus) — plugin enablement, port 15692, endpoint `/metrics`

### Secondary (LOW confidence — web search)
- [artifacthub.io/packages/helm/prometheus-community/prometheus](https://artifacthub.io/packages/helm/prometheus-community/prometheus) — chart 29.11.0 confirmed
- [artifacthub.io/packages/helm/grafana/grafana](https://artifacthub.io/packages/helm/grafana/grafana) — chart 10.5.15 confirmed
- [prometheus.io/blog/2024/11/14/prometheus-3-0/](https://prometheus.io/blog/2024/11/14/prometheus-3-0/) — v3 breaking changes
- [grafana.com/grafana/dashboards/1860](https://grafana.com/grafana/dashboards/1860) — Node Exporter Full dashboard ID
- [grafana.com/grafana/dashboards/9628](https://community.grafana.com/t/enhancement-in-postgresql-dashboard-id-9628) — PostgreSQL dashboard ID
- [grafana.com/grafana/dashboards/10991](https://grafana.com/grafana/dashboards/10991-rabbitmq-overview/) — RabbitMQ Overview dashboard ID

### Tertiary (LOW confidence — training knowledge, not verified this session)
- Resource sizing figures (Prometheus ~256Mi, Grafana ~128Mi, node-exporter ~40Mi) — community consensus patterns; treat as ASSUMED
- pg_monitor role availability in PG17 — documented feature since PG10; very low risk

---

## Metadata

**Confidence breakdown:**
- Standard stack (chart versions): MEDIUM — confirmed from GitHub Chart.yaml via curl
- Prometheus/Grafana configuration patterns: LOW/ASSUMED — values schema inferred from chart; verify with `helm show values`
- Resource sizing: LOW/ASSUMED — community data; must verify live after first deploy
- RBAC patterns: MEDIUM — kubernetes docs + codebase pattern match
- RabbitMQ plugin: MEDIUM — official docs confirmed

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (chart versions; re-check if planning is delayed > 30 days)
