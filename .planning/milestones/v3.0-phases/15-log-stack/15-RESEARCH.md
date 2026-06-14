# Phase 15: Log Stack — Research

**Researched:** 2026-06-14
**Domain:** Kubernetes log collection — Loki (monolithic/filesystem) + Grafana Alloy (DaemonSet)
**Confidence:** MEDIUM (chart versions verified from ArtifactHub/GitHub; config patterns from official Grafana docs; metric names from Loki source code)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Reuse the Phase 13 obs pipeline
Loki + Alloy are helm-rendered (no operator/CRDs) into `k8s/observability/`, committed, and
applied via the same `deploy-observability.yml` path + `obs-ci-deployer`. Both run in the
`monitoring` namespace with `priorityClassName: obs-background` and TIGHT requests/limits.
Grafana gets Loki added as a second provisioned datasource (extend the Phase 13 grafana values/
rendered manifest). Extend `validate-phase-13.sh` style with a `validate-phase-15.sh`.

### Node headroom (live, 2026-06-14)
4 CPU / 7.75Gi; ~2.8Gi available, swap ~0.6Gi used, disk 25G free. Loki (monolithic/filesystem)
+ Alloy DaemonSet must be tight — target Loki ~128–256Mi, Alloy ~64–128Mi. Loki PVC sized for
~7-day retention against the 25G free disk (e.g. 8–10Gi), compactor-driven retention.

### Conservative collection (LOG-02 security)
Alloy collects only namespace/pod/container/app/job labels — NO request bodies, NO secrets.
Drop/scrub high-cardinality or sensitive content at the Alloy pipeline. Loki monolithic mode,
filesystem storage, single replica (single-node staging).

### Deferred Ideas (OUT OF SCOPE)
- GlitchTip log ingestion (errors only; logs live in Loki)
- NetworkPolicy enforcement (Phase 17)
- Production observability mirror
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LOG-01 | Loki runs in monolithic/filesystem mode with compactor-driven ~7-day retention on a right-sized PVC. | § Standard Stack (chart + image versions); § Loki Configuration Pattern; § Pitfall 2 (correct metric for compactor) |
| LOG-02 | Grafana Alloy DaemonSet collects cluster logs conservatively (namespace/pod/container/app/job only; no request bodies, no secrets). | § Alloy Pipeline Design; § Alloy RBAC; § Code Examples |
| LOG-03 | Loki is a healthy Grafana datasource and a LogQL query returns recent `server-2` log lines. | § Grafana Datasource Provisioning; § Validation Architecture |
</phase_requirements>

---

## Summary

Phase 15 adds a log layer to the existing metrics stack from Phase 13. The pattern is identical
to Phase 13: `helm template` renders manifests offline into `k8s/observability/`, committed to
git, applied by `obs-ci-deployer` via `deploy-observability.yml`. Two new workloads land in the
`monitoring` namespace:

**Loki** runs as a single-binary StatefulSet (`deploymentMode: SingleBinary`, `replicas: 1`)
using local filesystem storage on a 10Gi PVC. The compactor is enabled with
`retention_enabled: true` and `retention_period: 168h` (~7 days). No S3, no operator, no CRDs.
The `grafana/loki` chart v7.0.0 is used — `loki-stack` is deprecated. With
`fullnameOverride: loki`, the Service is named `loki` and exposes port 3100.

**Grafana Alloy** runs as a DaemonSet via the `grafana/alloy` chart v1.10.0. The Alloy config
(River/Alloy syntax in a ConfigMap) uses `discovery.kubernetes` + `discovery.relabel` to strip
all labels down to exactly {namespace, pod, container, app, job} — no message-body parsing,
no high-cardinality labels. Logs are tailed via `loki.source.kubernetes` (no node filesystem
mount required; uses the Kubernetes API) and pushed to Loki via `loki.write`. The Alloy chart's
default RBAC ClusterRole covers all required permissions (`pods/log` included).

Grafana is extended by adding Loki as a second datasource via `additionalDataSources` in
`grafana-values.yaml` + re-rendering `50-grafana.yaml`. Prometheus gets two new static scrape
targets (`loki:3100` and `alloy:12345`) added to `10-prometheus.yaml`'s ConfigMap so that
`loki_boltdb_shipper_compactor_running` and `loki_write_sent_entries_total` are scraped.

> **METRIC NAME CORRECTION:** The success criteria brief says `loki_compactor_runs_total`
> and `alloy_logs_entries_total`. These names do NOT exist in Loki/Alloy source code.
> The correct metrics are:
> - Compactor proof: `loki_boltdb_shipper_compactor_running == 1` (gauge; 1 = active) OR
>   `loki_compactor_apply_retention_operation_total > 0` (after first retention cycle)
> - Alloy proof: `loki_write_sent_entries_total > 0` (counter from `loki.write` component)
> See § Pitfall 2 and § Validation Architecture.

**Primary recommendation:** Use `grafana/loki` chart v7.0.0, `deploymentMode: SingleBinary`,
`loki.storage.type: filesystem`, `singleBinary.replicas: 1`. Use `grafana/alloy` chart v1.10.0
as DaemonSet with a hand-authored Alloy config for conservative Kubernetes log collection.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Log storage | Loki StatefulSet (in-cluster) | — | Single-binary; filesystem PVC; ClusterIP only |
| Log collection | Alloy DaemonSet (in-cluster) | — | One pod on the single staging node; tails via k8s API |
| Label filtering / scrubbing | Alloy `discovery.relabel` + `loki.process` | — | Drop at collection, not at query time |
| Log push to Loki | Alloy `loki.write` (in-cluster) | — | ClusterIP DNS: `loki.monitoring.svc:3100` |
| Loki datasource in Grafana | Grafana provisioning (ConfigMap) | — | `additionalDataSources` in grafana-values.yaml |
| Compactor / retention | Loki built-in compactor (same process) | — | In monolithic mode, compactor runs in the single binary |
| Loki + Alloy metrics scraped by Prometheus | Prometheus scrape config (10-prometheus.yaml) | — | Static targets: loki:3100/metrics, alloy:12345/metrics |
| RBAC for Alloy (k8s API access) | ClusterRole via Alloy chart (`rbac.create: true`) | 01-obs-rbac.yaml (bootstrap if needed) | Alloy chart generates CRB; obs-ci-deployer namespace-scoped (see Pitfall 4) |
| Manifest delivery | CI kubectl apply (obs-ci-deployer) | — | Same pattern as Phase 13 |

---

## Standard Stack

### Core
| Chart / Image | Version | Purpose | Source |
|---|---|---|---|
| `grafana/loki` (helm chart) | **7.0.0** | Loki server — StatefulSet, Service, ConfigMap | [CITED: artifacthub.io/packages/helm/grafana/loki] |
| `grafana/loki` (image) | **3.6.11** | Loki container image | [CITED: hub.docker.com/r/grafana/loki, 2026-05-13] |
| `grafana/alloy` (helm chart) | **1.10.0** | Alloy DaemonSet — ServiceAccount, ClusterRole, DaemonSet, Service | [CITED: artifacthub.io/packages/helm/grafana/alloy] |
| `grafana/alloy` (image) | **v1.17.0** | Alloy container image | [CITED: hub.docker.com/r/grafana/alloy, 2026-06-12] |

> **Note:** The `loki-stack` chart (v2.10.3) is **deprecated** — do not use it.
> [CITED: artifacthub.io/packages/helm/grafana/loki-stack, deprecated: true]

> **Image vs chart appVersion:** `grafana/loki` chart v7.0.0 lists appVersion 3.6.7, but the
> latest image on Docker Hub is **3.6.11** (2026-05-13). Pin the image explicitly in
> `singleBinary.image.tag: "3.6.11"` in loki-values.yaml to get the latest patch. [VERIFIED: hub.docker.com]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `loki.source.kubernetes` (Alloy component) | built-in to Alloy v1.17.0 | Tails pod logs via k8s API (no host filesystem) | Preferred over `loki.source.file` on k3s single-node (no DaemonSet host-path mount needed) |
| `discovery.kubernetes` (Alloy component) | built-in | Discovers pods for relabeling | Required upstream of `loki.source.kubernetes` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `loki.source.kubernetes` | `loki.source.file` with hostPath `/var/log/pods` | File source needs `varlog: true` host mount + privileged; kubernetes source avoids this. Kubernetes source uses more Kubelet network traffic but is cleaner for single-node. |
| `grafana/loki` chart SingleBinary | Standalone Deployment YAML | Chart handles StatefulSet, PVC, compactor config, Service, RBAC; hand-rolling would miss edge cases |
| Alloy DaemonSet | Promtail | Promtail is deprecated; Alloy is its direct replacement |
| `additionalDataSources` in grafana-values.yaml | Separate datasource ConfigMap | `additionalDataSources` keeps everything in one chart values file; cleaner than a separate ConfigMap |

### Helm Render Commands

```bash
# Add repos first (if not already added):
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Loki
helm template loki grafana/loki \
  --version 7.0.0 \
  --namespace monitoring \
  --values k8s/observability/values/loki-values.yaml \
  > k8s/observability/70-loki.yaml

# Alloy
helm template alloy grafana/alloy \
  --version 1.10.0 \
  --namespace monitoring \
  --values k8s/observability/values/alloy-values.yaml \
  > k8s/observability/80-alloy.yaml
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `grafana/loki` (helm chart) | artifacthub.io | 5+ yrs | Millions | github.com/grafana/loki | OK | Approved |
| `grafana/alloy` (helm chart) | artifacthub.io | ~2 yrs | Millions | github.com/grafana/alloy | OK | Approved |
| `grafana/loki` (image) | Docker Hub | 7+ yrs | Billions | github.com/grafana/loki | OK | Approved |
| `grafana/alloy` (image) | Docker Hub | ~2 yrs | Millions | github.com/grafana/alloy | OK | Approved |
| `grafana/loki-stack` (helm) | artifacthub.io | 5+ yrs | Millions | github.com/grafana/helm-charts | **DEPRECATED** | Do NOT use — deprecated in 2024 |

**Packages removed:** `grafana/loki-stack` — deprecated, use `grafana/loki` with `deploymentMode: SingleBinary` instead.
**Packages flagged as suspicious:** none.

---

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  namespace: solid-stats-staging                                          │
│                                                                          │
│  server-2 pod  replay-parser-2 pod  rabbitmq pod  postgres pod           │
│       │               │               │              │                   │
│       └───────────────┴───────────────┴──────────────┘                   │
│                               │ (k8s pod log API)                        │
└───────────────────────────────┼──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│  namespace: monitoring                                                   │
│                                                                          │
│  ┌───────────────────────────────────────┐                               │
│  │  Alloy DaemonSet (1 pod, 1 node)      │                               │
│  │  discovery.kubernetes (pod role)      │                               │
│  │    → discovery.relabel               │                               │
│  │      DROP all labels except:         │                               │
│  │      namespace/pod/container/app/job │                               │
│  │    → loki.source.kubernetes          │                               │
│  │    → loki.process (static_labels)    │                               │
│  │    → loki.write                      │──────────────────────┐        │
│  └───────────────────────────────────────┘                      │        │
│                                                                  │ push  │
│  ┌────────────────────────────────────┐                          │        │
│  │  Loki StatefulSet (singleBinary)   │◄─────────────────────────┘        │
│  │  /loki/api/v1/push  :3100         │                                   │
│  │  Compactor: retention 168h        │                                   │
│  │  Storage: PVC 10Gi /var/loki      │                                   │
│  └───────────────┬────────────────────┘                                   │
│                  │ datasource                                             │
│                  ▼                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Grafana  (existing from Phase 13)                               │    │
│  │  datasources: Prometheus (existing) + Loki (new, additionalDS)  │    │
│  │  Explore → LogQL: {app="server-2"} → returns recent log lines   │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────┐           │
│  │  Prometheus (existing)                                    │           │
│  │  new scrape jobs:                                         │           │
│  │    loki:3100/metrics  → loki_boltdb_shipper_compactor_*  │           │
│  │    alloy:12345/metrics → loki_write_sent_entries_total    │           │
│  └───────────────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Recommended File Layout

```
k8s/observability/
├── values/
│   ├── prometheus-values.yaml      # EXTEND: add loki + alloy scrape jobs
│   ├── grafana-values.yaml         # EXTEND: add additionalDataSources for Loki
│   ├── loki-values.yaml            # NEW: SingleBinary, filesystem, compactor
│   └── alloy-values.yaml           # NEW: DaemonSet, configMap content
├── 10-prometheus.yaml              # RE-RENDER: +loki +alloy scrape targets
├── 50-grafana.yaml                 # RE-RENDER: +Loki datasource
├── 70-loki.yaml                    # NEW: helm template output
└── 80-alloy.yaml                   # NEW: helm template output
```

> Numeric prefix `70-` and `80-` continue the Phase 13 ordering. CI applies `find k8s/observability -maxdepth 1 -name '*.yaml' | sort`.

---

## Key Technical Decisions

### 1. Loki Chart and Mode

Use `grafana/loki` chart v7.0.0 with `deploymentMode: SingleBinary`. This is the direct
replacement for the deprecated `loki-stack`. The chart key is `deploymentMode: SingleBinary`
(capital S and B, matches the chart enum). Set `singleBinary.replicas: 1`.

The chart renders a **StatefulSet** (not a Deployment) for the single-binary mode, giving a
stable PVC attachment. This is the correct pattern for a single-node k3s cluster.

Disable all microservice replicas to 0 (the chart defaults `deploymentMode: SimpleScalable`
which enables read/write/backend pods — must override):

```yaml
backend:
  replicas: 0
read:
  replicas: 0
write:
  replicas: 0
ingester:
  replicas: 0
querier:
  replicas: 0
queryFrontend:
  replicas: 0
queryScheduler:
  replicas: 0
distributor:
  replicas: 0
compactor:
  replicas: 0
indexGateway:
  replicas: 0
bloomCompactor:
  replicas: 0
bloomGateway:
  replicas: 0
```

### 2. Loki Storage: Filesystem Mode

Set `loki.storage.type: filesystem` (the chart uses this to populate `commonStorageConfig`).
The filesystem directories are `/var/loki/chunks` and `/var/loki/rules` by default (set in
`loki.storage.filesystem.*`). The PVC mounts at `/var/loki` via the StatefulSet template.

Set `singleBinary.persistence.size: 10Gi`. On a node with 25G free disk, 10Gi is safe for
~7-day retention of a small cluster's logs.

### 3. Compactor and Retention

In Loki monolithic/SingleBinary mode the compactor runs **inside the same process** — no
separate pod needed. Configure via `loki.compactor`:

```yaml
loki:
  compactor:
    working_directory: /var/loki/retention
    retention_enabled: true
    retention_delete_delay: 2h
    delete_request_store: filesystem
```

Set global retention in `loki.limits_config`:
```yaml
loki:
  limits_config:
    retention_period: 168h   # 7 days
```

**Schema requirement:** Retention only works when `index.period: 24h` in schemaConfig.
Use TSDB store (current recommended):

```yaml
loki:
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
```

### 4. Loki commonConfig

```yaml
loki:
  commonConfig:
    replication_factor: 1   # REQUIRED for single replica — requests fail without this
    path_prefix: /var/loki
  auth_enabled: false       # internal cluster use; no multi-tenant headers
```

`replication_factor: 1` is critical — without it, writes fail with quorum errors even in
single-binary mode. [CITED: grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/]

### 5. Alloy Pipeline Design (LOG-02 conservative collection)

The pipeline uses `loki.source.kubernetes` — it tails logs via the Kubernetes API without
needing a host filesystem mount or privileged container. This is the preferred approach
for single-node k3s staging. [CITED: grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/]

**Label discipline:** `discovery.relabel` keeps ONLY 5 labels, then a `keepequal` action
drops the `__meta_kubernetes_*` labels that would leak to Loki. All labels not explicitly
relabeled to a target_label are dropped by the `labelallow` stage in `loki.process`.

Push URL: `http://loki.monitoring.svc:3100/loki/api/v1/push`
(Service name: `loki` via `fullnameOverride: loki`; port 3100 http-metrics).

### 6. Alloy RBAC

The Alloy chart's default `rbac.rules` already includes everything needed — no manual
ClusterRole authoring required. With `rbac.create: true` (default), the chart generates:

```yaml
rules:
  - apiGroups: ["", "discovery.k8s.io", "networking.k8s.io"]
    resources: ["endpoints", "endpointslices", "ingresses", "pods", "services"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log", "namespaces"]
    verbs: ["get", "list", "watch"]
  # ... more rules for prometheus.operator.*, mimir, events
```

[VERIFIED: github.com/grafana/alloy/operations/helm/charts/alloy/values.yaml]

**RBAC delivery concern:** The Alloy chart renders a `ClusterRole` + `ClusterRoleBinding`.
`obs-ci-deployer` is namespace-scoped and CANNOT create cluster-scoped resources.
Same split as Phase 13 Prometheus: Alloy's ClusterRole + ClusterRoleBinding must be added
to `k8s/staging/01-obs-rbac.yaml` (operator-applied bootstrap) OR the rendered `80-alloy.yaml`
must be stripped of its ClusterRole/ClusterRoleBinding and those added to the bootstrap file.

**Recommended approach:** Extract the ClusterRole + ClusterRoleBinding from the rendered
`80-alloy.yaml` into a new `k8s/staging/03-alloy-rbac.yaml` (operator-applied once), same
pattern as Prometheus ClusterRole in Phase 13.

### 7. Grafana Loki Datasource (LOG-03)

Extend `grafana-values.yaml` with `additionalDataSources` (Grafana chart v10.5.15 supports this):

```yaml
additionalDataSources:
  - name: Loki
    type: loki
    url: http://loki.monitoring.svc:3100
    access: proxy
    isDefault: false
    jsonData:
      maxLines: 1000
```

This re-renders `50-grafana.yaml`. The Grafana chart's `datasources.yaml` ConfigMap key will
contain both Prometheus and Loki. The sidecar watches for ConfigMap labels, not datasource
ConfigMaps — datasources are provisioned at startup via the ConfigMap mount.

### 8. Prometheus Scrape Targets for Loki + Alloy

Extend `prometheus-values.yaml` scrapeConfigs (re-render `10-prometheus.yaml`):

```yaml
- job_name: loki
  static_configs:
    - targets:
      - loki.monitoring.svc:3100

- job_name: alloy
  static_configs:
    - targets:
      - alloy.monitoring.svc:12345
```

With `fullnameOverride: loki` → Service `loki`. Alloy chart fullname defaults to `alloy`
(release name) → Service `alloy`.

### 9. Resource Sizing

**Current node state (2026-06-14):** ~290Mi used by existing obs stack (grafana 206, prometheus
47, others <35). Node has ~2.8Gi available.

| Workload | Memory Request | Memory Limit | CPU Request | CPU Limit | Rationale |
|---|---|---|---|---|---|
| Loki (SingleBinary) | 128Mi | 256Mi | 50m | 200m | Tiny log volume; single node; TSDB is lightweight [ASSUMED] |
| Alloy DaemonSet (1 pod) | 64Mi | 128Mi | 30m | 100m | Single node; k8s API log tail; conservative pipeline [ASSUMED] |
| **Total additional** | **192Mi** | **384Mi** | **80m** | **300m** | Well within 2.8Gi headroom |

**PVC:** `singleBinary.persistence.size: 10Gi` on the k3s `local-path` StorageClass.
At ~25G free disk, 10Gi leaves comfortable margin. Retention at 168h (7 days) with
`retentionSize` cap not strictly needed but add `retention_delete_worker_count: 150`
to prevent stall.

> All sizing values are [ASSUMED] — verify with `kubectl top pods -n monitoring` after deploy.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Loki manifests (StatefulSet, PVC, Service, ConfigMap) | Custom YAML | `helm template grafana/loki` | Chart handles tsdb config injection, storage helpers, compactor config merge, schema validation |
| Log collection agent | Custom DaemonSet with kubectl logs loop | `grafana/alloy` chart + `loki.source.kubernetes` | Alloy handles reconnection, Kubelet backpressure, log rotation, label relabeling atomically |
| Label scrubbing | Manual grep/sed in a sidecar | `discovery.relabel` + `loki.process` `stage.label_keep` | Declarative; applied before push; no regex footguns |
| Loki datasource ConfigMap | Custom k8s ConfigMap | `additionalDataSources` in grafana-values.yaml | Chart handles mount path, provisioning restart signal |
| Compactor scheduling | CronJob / external script | Loki built-in compactor (runs in-process) | Monolithic mode includes compactor; no separate pod needed |
| Multi-tenant log routing | tenant_id headers + per-NS Loki | Single Loki, `auth_enabled: false` | Staging has one operator; multi-tenancy adds complexity with no benefit |

---

## Common Pitfalls

### Pitfall 1: `deploymentMode` default is `SimpleScalable`, not `SingleBinary`
**What goes wrong:** Render produces read/write/backend StatefulSets with 3+ replicas.
The cluster gets OOM-killed immediately from 3× more Loki pods than expected.
**Why it happens:** Chart default is `deploymentMode: SimpleScalable`. If you only set
`singleBinary.replicas: 1` without `deploymentMode: SingleBinary`, the wrong mode activates.
**How to avoid:** Set `deploymentMode: SingleBinary` explicitly in loki-values.yaml. Also set
all other replica counts to 0 (backend, read, write, ingester, etc.) as belt-and-suspenders.
**Warning signs:** `helm template` output contains `StatefulSet` named `loki-read`, `loki-write`.

### Pitfall 2: Compactor metric name mismatch (CRITICAL — success criteria uses wrong names)
**What goes wrong:** Validation checks `loki_compactor_runs_total` and `alloy_logs_entries_total`
— neither metric exists. The validation returns "no data" even when the stack is healthy.
**Why it happens:** These metric names were in the brief but are not emitted by Loki/Alloy source code.
**Correct metric names (from Loki source `pkg/compactor/metrics.go`):**
- `loki_boltdb_shipper_compactor_running` (gauge, 1 = active) — confirms compactor is up
- `loki_compactor_apply_retention_operation_total{status="success"}` — confirms retention ran
- `loki_boltdb_shipper_compact_tables_operation_total{status="success"}` — confirms compaction ran
**Correct Alloy metric (from loki.write docs):**
- `loki_write_sent_entries_total` — counter of entries pushed to Loki
**How to avoid:** Use the correct metric names in `validate-phase-15.sh`.

### Pitfall 3: `replication_factor: 1` missing → write quorum failures
**What goes wrong:** Loki starts but all log pushes fail with `too many unhealthy instances in the ring`.
**Why it happens:** Default `replication_factor: 3` requires 3 ingesters; single-binary has 1.
**How to avoid:** Set `loki.commonConfig.replication_factor: 1` in loki-values.yaml. [CITED: official Loki monolithic install docs]
**Warning signs:** Alloy logs show `"context deadline exceeded"` pushing to Loki; `loki_write_dropped_entries_total` increases.

### Pitfall 4: Alloy ClusterRole rendered in `80-alloy.yaml` → obs-ci-deployer cannot apply it
**What goes wrong:** `deploy-observability.yml` fails with `forbidden: cannot create resource "clusterroles"`.
**Why it happens:** Same constraint as Prometheus in Phase 13 — obs-ci-deployer is namespace-scoped.
**How to avoid:** Extract ClusterRole + ClusterRoleBinding from the `helm template` output, add to
`k8s/staging/03-alloy-rbac.yaml` (operator-applied bootstrap). Remove them from `80-alloy.yaml`.
`validate-obs-manifests.py` should assert no ClusterRole in `k8s/observability/*.yaml`.
**Warning signs:** CI apply step fails on `80-alloy.yaml` with 403.

### Pitfall 5: Retention only works with `index.period: 24h` in schema
**What goes wrong:** Compactor runs but no data is deleted; retention is silently ignored.
**Why it happens:** Loki requires `index.period: 24h` for the compactor's retention sweeper to work.
**How to avoid:** Ensure `loki.schemaConfig.configs[0].index.period: 24h`. TSDB + v13 schema with 24h period is the correct current pattern. [CITED: grafana.com/docs/loki/latest/operations/storage/retention/]
**Warning signs:** `loki_compactor_apply_retention_operation_total` stays 0; disk grows unboundedly.

### Pitfall 6: Grafana datasource URL wrong → LOG-03 fails
**What goes wrong:** Grafana Explore shows "connection refused" or "bad gateway" for Loki datasource.
**Why it happens:** Wrong service name or port in `additionalDataSources.url`.
**How to avoid:** With `fullnameOverride: loki`, the Service is named exactly `loki`. URL must be
`http://loki.monitoring.svc:3100`. Port 3100 = `http-metrics` (from chart Service template).
**Warning signs:** Grafana datasource health check returns error; curl from Grafana pod to `loki:3100/ready` fails.

### Pitfall 7: Alloy tails logs from all namespaces including monitoring itself → log storm
**What goes wrong:** Alloy logs its own log lines, which Alloy ingests, creating a feedback loop.
**Why it happens:** `discovery.kubernetes` with `role: "pod"` discovers ALL pods including Alloy itself.
**How to avoid:** Add a `discovery.relabel` rule to drop pods in the `monitoring` namespace, OR
add a `__path__` filter to drop Alloy's own logs. Simplest: add a relabel rule `action: drop`
when `__meta_kubernetes_namespace == "monitoring"`. Alternatively, only ingest from `solid-stats-staging`.
**Warning signs:** `loki_write_sent_entries_total` growing very fast; Loki disk filling quickly.

### Pitfall 8: `loki.source.kubernetes` vs `loki.source.file` selection
**What goes wrong:** Using `loki.source.file` requires `hostPath` volume (`/var/log/pods`) +
`varlog: true` in alloy-values.yaml. This needs host filesystem access.
**Why it happens:** Confusion between the two log tailing strategies.
**How to avoid:** Use `loki.source.kubernetes` (tails via the k8s API). No hostPath needed.
[CITED: grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/ — "works without privileged container, without root user, without node filesystem access"]

### Pitfall 9: Loki StatefulSet PVC auto-delete on scale-down
**What goes wrong:** If Loki StatefulSet is accidentally scaled to 0 and back, PVC may be deleted.
**Why it happens:** Chart default `singleBinary.persistence.whenScaled: Delete`.
**How to avoid:** Override `singleBinary.persistence.whenScaled: Retain` and `whenDeleted: Retain`
in loki-values.yaml. [ASSUMED: chart defaults from values.yaml inspection]
**Warning signs:** After pod restart, Loki has no data — PVC missing.

---

## Code Examples

### loki-values.yaml (complete)

```yaml
# k8s/observability/values/loki-values.yaml
# Rendered via: helm template loki grafana/loki --version 7.0.0 \
#   --namespace monitoring --values k8s/observability/values/loki-values.yaml \
#   > k8s/observability/70-loki.yaml
#
# Key constraints:
#   - SingleBinary mode (NOT SimpleScalable — chart default)
#   - Filesystem storage on 10Gi PVC (local-path, k3s default)
#   - Compactor retention 168h (7 days)
#   - auth_enabled: false (internal; no multi-tenant headers)
#   - replication_factor: 1 (REQUIRED for single replica — writes fail without it)
#   - priorityClassName: obs-background (evictable before app pods)
#   - Tight resources: 128Mi/256Mi, obs-background priority

fullnameOverride: loki   # Service will be named 'loki'; URL: loki.monitoring.svc:3100

deploymentMode: SingleBinary

loki:
  auth_enabled: false

  commonConfig:
    replication_factor: 1
    path_prefix: /var/loki

  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: loki_index_
          period: 24h   # REQUIRED for compactor retention to work

  storage:
    type: filesystem
    filesystem:
      chunks_directory: /var/loki/chunks
      rules_directory:  /var/loki/rules

  compactor:
    working_directory: /var/loki/retention
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 150
    delete_request_store: filesystem

  limits_config:
    retention_period: 168h   # 7 days

singleBinary:
  replicas: 1
  image:
    tag: "3.6.11"   # pin to latest patch; chart appVersion is 3.6.7
  priorityClassName: obs-background
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi
  persistence:
    enabled: true
    size: 10Gi
    storageClassName: ""   # k3s local-path default
    whenScaled: Retain
    whenDeleted: Retain

# Disable all microservice replicas (chart default is SimpleScalable — must override)
backend:
  replicas: 0
read:
  replicas: 0
write:
  replicas: 0
ingester:
  replicas: 0
querier:
  replicas: 0
queryFrontend:
  replicas: 0
queryScheduler:
  replicas: 0
distributor:
  replicas: 0
compactor:
  replicas: 0
indexGateway:
  replicas: 0
bloomCompactor:
  replicas: 0
bloomGateway:
  replicas: 0

# Disable gateway (nginx proxy — not needed for internal ClusterIP access)
gateway:
  enabled: false

# Disable Grafana agent / self-monitoring (adds overhead; we use Prometheus scrape)
monitoring:
  selfMonitoring:
    enabled: false
  lokiCanary:
    enabled: false

test:
  enabled: false
```

### alloy-values.yaml (complete)

```yaml
# k8s/observability/values/alloy-values.yaml
# Rendered via: helm template alloy grafana/alloy --version 1.10.0 \
#   --namespace monitoring --values k8s/observability/values/alloy-values.yaml \
#   > k8s/observability/80-alloy.yaml
#
# IMPORTANT: The rendered 80-alloy.yaml will contain a ClusterRole + ClusterRoleBinding.
# These must be EXTRACTED from 80-alloy.yaml and added to k8s/staging/03-alloy-rbac.yaml
# (operator-applied bootstrap) because obs-ci-deployer is namespace-scoped and cannot
# create ClusterRole. Remove the ClusterRole/ClusterRoleBinding docs from 80-alloy.yaml.

fullnameOverride: alloy   # Service named 'alloy'; scrape at alloy.monitoring.svc:12345

controller:
  type: daemonset
  priorityClassName: obs-background

alloy:
  resources:
    requests:
      cpu: 30m
      memory: 64Mi
    limits:
      cpu: 100m
      memory: 128Mi

  # Conservative log collection pipeline (LOG-02):
  # - Discovers pods via k8s API (no hostPath required)
  # - Keeps ONLY 5 labels: namespace, pod, container, app, job
  # - Drops all other meta-labels (no request bodies, no secrets)
  # - Pushes to Loki at loki.monitoring.svc:3100
  configMap:
    content: |
      // Discover all pods in the cluster
      discovery.kubernetes "pods" {
        role = "pod"
      }

      // Relabel: keep ONLY namespace/pod/container/app/job; drop everything else
      discovery.relabel "pod_logs" {
        targets = discovery.kubernetes.pods.targets

        // Drop monitoring namespace (prevents Alloy log loop)
        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          regex         = "monitoring"
          action        = "drop"
        }

        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          action        = "replace"
          target_label  = "namespace"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_name"]
          action        = "replace"
          target_label  = "pod"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_container_name"]
          action        = "replace"
          target_label  = "container"
        }
        // app label: prefer app.kubernetes.io/name, fallback to app label
        rule {
          source_labels = ["__meta_kubernetes_pod_label_app_kubernetes_io_name"]
          action        = "replace"
          target_label  = "app"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_label_app"]
          regex         = "(.+)"
          target_label  = "app"
          action        = "replace"
        }
        // job = namespace/container (standard Loki convention)
        rule {
          source_labels = ["__meta_kubernetes_namespace", "__meta_kubernetes_pod_container_name"]
          separator     = "/"
          target_label  = "job"
          action        = "replace"
        }
      }

      // Tail logs via Kubernetes API (no host filesystem mount needed)
      loki.source.kubernetes "pod_logs" {
        targets    = discovery.relabel.pod_logs.output
        forward_to = [loki.process.drop_extra_labels.receiver]
      }

      // Drop any remaining labels not in the allowlist
      loki.process "drop_extra_labels" {
        stage.label_keep {
          values = ["namespace", "pod", "container", "app", "job"]
        }
        forward_to = [loki.write.loki.receiver]
      }

      // Write to Loki push API
      loki.write "loki" {
        endpoint {
          url = "http://loki.monitoring.svc:3100/loki/api/v1/push"
        }
      }

rbac:
  create: true
  # Default rules already include pods/pods/log/namespaces for loki.source.kubernetes.
  # BUT: obs-ci-deployer cannot create ClusterRole — extract from rendered YAML
  # into k8s/staging/03-alloy-rbac.yaml (operator bootstrap).

serviceAccount:
  create: true

service:
  enabled: true
  type: ClusterIP

# Alloy UI/HTTP server (port 12345) — used for Prometheus metrics scrape
alloy:
  listenPort: 12345
  enableHttpServerPort: true

# No ingress, no extra volumes (loki.source.kubernetes doesn't need /var/log)
ingress:
  enabled: false
```

### grafana-values.yaml extension (additionalDataSources)

Add to the existing `k8s/observability/values/grafana-values.yaml`:

```yaml
# Add BELOW the existing datasources block:
additionalDataSources:
  - name: Loki
    type: loki
    url: http://loki.monitoring.svc:3100
    access: proxy
    isDefault: false
    jsonData:
      maxLines: 1000
      timeout: "60"
```

Then re-render `50-grafana.yaml`:
```bash
helm template grafana grafana/grafana \
  --version 10.5.15 \
  --namespace monitoring \
  --values k8s/observability/values/grafana-values.yaml \
  > k8s/observability/50-grafana.yaml
```

### prometheus-values.yaml extension (scrape targets)

Add to `scrapeConfigs` in prometheus-values.yaml, then re-render `10-prometheus.yaml`:

```yaml
# Add these jobs alongside existing kube-state-metrics, node-exporter, etc.
- job_name: loki
  static_configs:
    - targets:
      - loki.monitoring.svc:3100

- job_name: alloy
  static_configs:
    - targets:
      - alloy.monitoring.svc:12345
```

### operator bootstrap: 03-alloy-rbac.yaml

```yaml
# k8s/staging/03-alloy-rbac.yaml
# Applied once by operator (bootstrap). NOT applied by obs-ci-deployer (namespace-scoped).
# Contains Alloy's ClusterRole + ClusterRoleBinding extracted from 80-alloy.yaml.
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: alloy
  labels:
    app.kubernetes.io/name: alloy
    app.kubernetes.io/part-of: solid-stats
rules:
  # Required for discovery.kubernetes
  - apiGroups: ["", "discovery.k8s.io", "networking.k8s.io"]
    resources: ["endpoints", "endpointslices", "ingresses", "pods", "services"]
    verbs: ["get", "list", "watch"]
  # Required for loki.source.kubernetes
  - apiGroups: [""]
    resources: ["pods", "pods/log", "namespaces"]
    verbs: ["get", "list", "watch"]
  # Required for loki.source.kubernetes_events
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: alloy
  labels:
    app.kubernetes.io/name: alloy
    app.kubernetes.io/part-of: solid-stats
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: alloy
subjects:
  - kind: ServiceAccount
    name: alloy
    namespace: monitoring
```

### LogQL acceptance query (LOG-03)

```logql
{app="server-2"}
```

Or using namespace:
```logql
{namespace="solid-stats-staging", app="server-2"}
```

Run in Grafana Explore → Loki datasource. Should return recent log lines from the `server-2` Deployment.

---

## Validation Architecture

> nyquist_validation enabled (config.json).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Bash + kubectl (live-cluster checks, mirrors validate-phase-13.sh) |
| Config file | `scripts/validate-phase-15.sh` (new) |
| Quick run command | `bash scripts/validate-phase-15.sh --quick` |
| Full suite command | `bash scripts/validate-phase-15.sh` |

### Phase Requirements → Validation Map

| Req ID | Behavior | Test Type | Automated Command / Check | File Exists? |
|--------|----------|-----------|---------------------------|-------------|
| LOG-01 | Loki pod Running | live | `kubectl -n monitoring get pod -l app.kubernetes.io/name=loki -o jsonpath='{.items[0].status.phase}'` == Running | ❌ Wave 0 |
| LOG-01 | Loki PVC bound (10Gi) | live | `kubectl -n monitoring get pvc -l app.kubernetes.io/name=loki -o jsonpath='{.items[0].status.phase}'` == Bound | ❌ Wave 0 |
| LOG-01 | Compactor active | live | Query Prometheus: `loki_boltdb_shipper_compactor_running == 1` (via `wget -qO- localhost:9090/api/v1/query?query=loki_boltdb_shipper_compactor_running`) | ❌ Wave 0 |
| LOG-01 | Retention configured 168h | live | `kubectl -n monitoring exec pod/loki-0 -- wget -qO- localhost:3100/config` contains `168h` | ❌ Wave 0 |
| LOG-02 | Alloy DaemonSet Running | live | `kubectl -n monitoring get ds alloy -o jsonpath='{.status.numberReady}'` == 1 | ❌ Wave 0 |
| LOG-02 | Log entries being pushed | live | Query Prometheus: `loki_write_sent_entries_total > 0` (alloy scrape target) | ❌ Wave 0 |
| LOG-02 | Labels are conservative (no extra labels) | live | LogQL query: `{namespace="solid-stats-staging"} \| label_format` — verify no request-body or secret fields in label set | manual |
| LOG-03 | Loki datasource healthy in Grafana | live | `curl -s -u admin:$GRAFANA_ADMIN_PASSWORD localhost:13000/api/datasources` — find datasource with type=loki and health=OK | ❌ Wave 0 |
| LOG-03 | LogQL returns server-2 lines | live | `curl -s -G "loki.monitoring.svc:3100/loki/api/v1/query_range" --data-urlencode 'query={app="server-2"}' --data-urlencode 'limit=5'` returns non-empty result (exec from prometheus pod) | ❌ Wave 0 |

### Correct metric names for validate-phase-15.sh

```bash
# LOG-01: Compactor active (gauge = 1 when running)
compactor_running=$(kubectl -n monitoring exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=loki_boltdb_shipper_compactor_running' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '0')")
# Assert compactor_running == "1"

# LOG-02: Alloy sent entries (counter > 0 after startup)
entries_total=$(kubectl -n monitoring exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=loki_write_sent_entries_total' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '0')")
# Assert entries_total != "0"
```

### Sampling Rate
- **Per task commit:** Static checks via `validate-obs-manifests.py` (no ClusterRole in k8s/observability/, no secrets, namespace=monitoring)
- **Per wave merge:** Full `bash scripts/validate-phase-15.sh` against live cluster
- **Phase gate:** Loki Running + compactor active + Alloy entries > 0 + LogQL returns server-2 lines

### Wave 0 Gaps
- [ ] `scripts/validate-phase-15.sh` — live validation covering LOG-01, LOG-02, LOG-03
- [ ] `k8s/observability/values/loki-values.yaml` — new
- [ ] `k8s/observability/values/alloy-values.yaml` — new
- [ ] `k8s/observability/70-loki.yaml` — rendered output
- [ ] `k8s/observability/80-alloy.yaml` — rendered output (ClusterRole extracted to bootstrap)
- [ ] `k8s/staging/03-alloy-rbac.yaml` — Alloy ClusterRole bootstrap (operator-applied once)
- [ ] `grafana-values.yaml` updated with `additionalDataSources: Loki`
- [ ] `50-grafana.yaml` re-rendered
- [ ] `prometheus-values.yaml` updated with loki+alloy scrape jobs
- [ ] `10-prometheus.yaml` re-rendered

---

## Security Domain

> security_enforcement: true (config absent = enabled). ASVS level 2.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | Loki `auth_enabled: false` — internal ClusterIP only; no public ingress in Phase 15 |
| V3 Session Management | no | Loki has no user sessions |
| V4 Access Control | yes | Alloy ClusterRole least-privilege (`pods/log` read-only); operator bootstrap pattern |
| V5 Input Validation | yes | `stage.label_keep` allows only 5 labels; no message body parsing |
| V6 Cryptography | no | Internal cluster traffic only; no TLS in-cluster (consistent with Phase 13 pattern) |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Request bodies captured in logs | Information Disclosure | `stage.label_keep` in Alloy `loki.process` — only 5 label keys allowed through; log line content is not parsed/indexed |
| Loki admin API accessible in-cluster | Elevation of Privilege | `auth_enabled: false` but ClusterIP only — no Ingress; only accessible from within the cluster |
| Alloy over-privileged ClusterRole | Elevation of Privilege | Minimal rules: pods/log read-only; no write access, no secrets access |
| Secret values in Loki log lines | Information Disclosure | Log lines are stored as-is; mitigation is at the source (apps must not log secrets) — out of scope for infra |
| Alloy log self-loop (monitoring namespace) | Denial of Service | `action: drop` rule for `__meta_kubernetes_namespace == "monitoring"` in discovery.relabel |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Promtail | Grafana Alloy | 2024 | Promtail deprecated; Alloy is the replacement with River/Alloy syntax |
| `loki-stack` helm chart | `grafana/loki` chart with `deploymentMode: SingleBinary` | 2024 | loki-stack deprecated; use the main loki chart |
| boltdb-shipper store | TSDB store (schema v13) | Loki 2.8+ | TSDB is the recommended index store; better performance |
| `retention_enabled` in `table_manager` | `retention_enabled` in `compactor` block | Loki 2.x+ | table_manager approach removed; compactor owns retention |
| Loki v2.x | Loki v3.x (3.6.11) | Nov 2023 | v3 has improved TSDB, better compactor, breaking: ring config changes |

**Deprecated/outdated:**
- `grafana/loki-stack` chart: deprecated since 2024, last version 2.10.3 — DO NOT USE
- Promtail: deprecated in favor of Alloy
- boltdb-shipper: still works but TSDB is the current recommended store
- `table_manager.retention_deletes_enabled`: removed; use compactor retention

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| k3s cluster (monitoring ns) | All workloads | ✓ | Phase 12+13 confirmed | — |
| `obs-background` PriorityClass | Loki + Alloy pods | ✓ | Phase 12 | — |
| `local-path` StorageClass | Loki 10Gi PVC | ✓ [ASSUMED] | k3s default | — |
| Prometheus (scrape targets) | Loki/Alloy metrics | ✓ | Phase 13 | — |
| Grafana (datasource) | LOG-03 | ✓ | Phase 13 | — |
| `obs-ci-deployer` SA | deploy-observability.yml | ✓ | Phase 12+13 | — |
| Helm binary (dev/CI) | `helm template` render | ? | Not verified this session | Download in CI step |
| 10Gi free disk on node | Loki PVC | ✓ (25G free) | Phase 12 preflight confirmed | — |

**Missing dependencies:** None blocking. Helm binary needed for re-render.

---

## Open Questions

1. **Alloy `loki.source.kubernetes` vs `loki.source.file` performance on k3s**
   - What we know: `loki.source.kubernetes` uses the k8s API (kubelet log endpoint); adds network overhead vs file tail.
   - What's unclear: On a single-node k3s with 5–10 pods, whether API-based tailing causes measurable kubelet load.
   - Recommendation: Use `loki.source.kubernetes` (no host mount needed). Monitor kubelet CPU via node-exporter after deploy.

2. **ClusterRole extraction from `80-alloy.yaml`**
   - What we know: The rendered `80-alloy.yaml` will contain ClusterRole + ClusterRoleBinding from `rbac.create: true`.
   - What's unclear: The easiest extraction method (grep + split, or disable rbac in chart values then add manually).
   - Recommendation: Set `rbac.create: false` in alloy-values.yaml, hand-author `03-alloy-rbac.yaml` with only the minimal rules needed. This avoids the extraction step entirely and keeps the bootstrap file clean.

3. **Loki 3.6.11 image vs chart appVersion 3.6.7**
   - What we know: Chart v7.0.0 ships appVersion 3.6.7; Docker Hub shows 3.6.11 as latest (2026-05-13).
   - What's unclear: Whether 3.6.11 has any breaking changes vs 3.6.7.
   - Recommendation: Pin `singleBinary.image.tag: "3.6.11"` in loki-values.yaml to get the latest patch. All are 3.6.x — no breaking changes expected.

4. **Grafana datasource re-render: `datasources.yaml` ConfigMap collision**
   - What we know: The existing `50-grafana.yaml` has a `datasources.yaml` key in the `grafana` ConfigMap with only Prometheus. After adding `additionalDataSources`, the chart renders a different structure.
   - What's unclear: Whether `additionalDataSources` merges into the same ConfigMap key or generates a separate one.
   - Recommendation: Run `helm template` with updated grafana-values.yaml locally and inspect the diff before committing. The Grafana chart typically puts `additionalDataSources` into a separate `datasources.yaml` secret or additional ConfigMap entry — verify the rendered output.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Loki monolithic working set ~128Mi on small cluster with ~5-10 pods | Resource Sizing | OOM eviction; raise limit — monitor `kubectl top pod -n monitoring` |
| A2 | Alloy DaemonSet pod working set ~64Mi | Resource Sizing | OOM; raise limit |
| A3 | `local-path` StorageClass available and can provision 10Gi | Environment | Loki PVC stays Pending; check `kubectl get storageclass` |
| A4 | Loki 3.6.11 has no breaking changes vs 3.6.7 | Standard Stack | Use chart appVersion 3.6.7 image instead if issues arise |
| A5 | `loki.source.kubernetes` is low enough overhead on a 4-pod cluster | Architecture | Switch to `loki.source.file` with hostPath if kubelet load is high |
| A6 | `additionalDataSources` in grafana-values.yaml generates the correct provisioning ConfigMap in chart v10.5.15 | Grafana Datasource | Re-render and inspect diff; may need to hand-patch `50-grafana.yaml` |
| A7 | PVC `whenScaled: Retain` / `whenDeleted: Retain` is supported in Loki chart v7.0.0 | Loki config | If not, data loss on accidental scale-down |
| A8 | `delete_request_store: filesystem` is valid for Loki filesystem mode compactor | Compactor | Retention silently fails; check Loki startup logs for config errors |

---

## Sources

### Primary (verified from official repos/docs)
- [github.com/grafana/alloy/operations/helm/charts/alloy/values.yaml](https://github.com/grafana/alloy/blob/main/operations/helm/charts/alloy/values.yaml) — Alloy chart RBAC rules (verified: pods/pods/log/namespaces rules confirmed) [VERIFIED: github.com/grafana/alloy]
- [github.com/grafana/loki/pkg/compactor/metrics.go](https://github.com/grafana/loki/blob/main/pkg/compactor/metrics.go) — Correct compactor metric names (loki_boltdb_shipper_compactor_running, loki_compactor_apply_retention_operation_total) [VERIFIED: github.com/grafana/loki]
- [grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/](https://grafana.com/docs/loki/latest/setup/install/helm/install-monolithic/) — replication_factor: 1 requirement, deploymentMode: SingleBinary [CITED]
- [grafana.com/docs/alloy/latest/reference/components/loki/loki.write/](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/) — loki_write_sent_entries_total metric [CITED]
- [grafana.com/docs/loki/latest/operations/storage/retention/](https://grafana.com/docs/loki/latest/operations/storage/retention/) — compactor retention config, index.period: 24h requirement [CITED]
- [hub.docker.com/r/grafana/loki](https://hub.docker.com/r/grafana/loki) — latest image tag 3.6.11 confirmed [VERIFIED]
- [hub.docker.com/r/grafana/alloy](https://hub.docker.com/r/grafana/alloy) — latest image tag v1.17.0 confirmed [VERIFIED]
- [artifacthub.io/packages/helm/grafana/loki](https://artifacthub.io/packages/helm/grafana/alloy) — chart v7.0.0 confirmed [VERIFIED]
- [artifacthub.io/packages/helm/grafana/alloy](https://artifacthub.io/packages/helm/grafana/alloy) — chart v1.10.0 confirmed [VERIFIED]
- [artifacthub.io/packages/helm/grafana/loki-stack](https://artifacthub.io/packages/helm/grafana/loki-stack) — deprecated:true confirmed [VERIFIED]

### Secondary (official docs, not cross-verified in code)
- [grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes/) — no exports, no privileged container needed [CITED]
- [grafana.com/docs/alloy/latest/collect/logs-in-kubernetes/](https://grafana.com/docs/alloy/latest/collect/logs-in-kubernetes/) — pipeline pattern (discovery → relabel → source → write) [CITED]

### Tertiary (training knowledge / low-confidence)
- Resource sizing figures (128Mi Loki, 64Mi Alloy) — community consensus; [ASSUMED]
- `delete_request_store: filesystem` validity — inferred from compactor config docs; [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- Chart versions (loki v7.0.0, alloy v1.10.0): HIGH — verified from ArtifactHub API
- Image versions (loki 3.6.11, alloy v1.17.0): HIGH — verified from Docker Hub API
- Correct metric names: HIGH — verified from Loki source code (pkg/compactor/metrics.go) and Alloy docs (loki.write)
- Loki values.yaml schema (deploymentMode, singleBinary, compactor keys): MEDIUM — verified from github.com/grafana/loki values.yaml
- Alloy RBAC rules: HIGH — verified from github.com/grafana/alloy values.yaml
- Resource sizing: LOW — ASSUMED; must verify with kubectl top after deploy
- additionalDataSources rendering: LOW — ASSUMED; must inspect helm template output

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (chart versions; re-check if planning delayed > 30 days)
