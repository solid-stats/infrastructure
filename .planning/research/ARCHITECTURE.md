# Architecture Research: v3.0 Observability Integration

**Domain:** Self-hosted observability stack integration into existing k3s staging cluster
**Researched:** 2026-06-13
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
PUBLIC INTERNET
        │ DNS A records:
        │   grafana.stats-staging.solid-stats.ru → VPS IP
        │   errors.stats-staging.solid-stats.ru  → VPS IP
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  HOST nginx (80/443) + certbot                                  │
│                                                                 │
│  vhost: stats-staging-solid-stats.conf  → upstream :3000       │
│  vhost: grafana-stats-staging.conf      → upstream :3000 (grafana ClusterIP) │
│  vhost: errors-stats-staging.conf       → upstream :8000 (glitchtip ClusterIP) │
└──────────────────────┬──────────────────────────────────────────┘
                       │ proxy_pass to ClusterIP (host-routable via k3s)
        ┌──────────────┼──────────────────────────┐
        ▼              ▼                           ▼
┌───────────────┐ ┌────────────────────┐ ┌────────────────────┐
│ solid-stats-  │ │ monitoring          │ │ error-tracking     │
│ staging ns    │ │ namespace           │ │ namespace          │
│               │ │                     │ │                     │
│ postgres      │ │ prometheus          │ │ glitchtip-web      │
│ rabbitmq      │ │ grafana             │ │ glitchtip-worker   │
│ server-2      │ │ loki                │ │ glitchtip-pg       │
│ replay-       │ │ alloy (DaemonSet)   │ │ glitchtip-redis    │
│  parser-2     │ │ kube-state-metrics  │ │                     │
│ replays-      │ │ node-exporter       │ │                     │
│  fetcher      │ │  (DaemonSet)        │ │                     │
│ postgres-     │ │ postgres-exporter   │ │                     │
│  backup       │ │ rabbitmq-exporter   │ │                     │
└───────────────┘ └────────────────────┘ └────────────────────┘
        ▲                  │ scrape /metrics cross-namespace
        └──────────────────┘ (Prometheus → solid-stats-staging pods)
```

### Component Responsibilities

| Component | Namespace | Responsibility | Service Type |
|-----------|-----------|----------------|--------------|
| prometheus | monitoring | Metrics scrape, TSDB, alerting rules | ClusterIP |
| grafana | monitoring | Dashboard UI, datasource broker | ClusterIP (proxied via host nginx) |
| loki | monitoring | Log storage + query API | ClusterIP |
| alloy | monitoring | Log/metric collection agent (DaemonSet) | None (pushes out) |
| kube-state-metrics | monitoring | Kubernetes object metrics | ClusterIP |
| node-exporter | monitoring | Host/node metrics (DaemonSet, hostNetwork) | ClusterIP |
| postgres-exporter | monitoring | App postgres metrics → Prometheus | ClusterIP |
| rabbitmq-exporter | monitoring | RabbitMQ metrics → Prometheus | ClusterIP |
| glitchtip-web | error-tracking | GlitchTip web app + API (Django) | ClusterIP (proxied via host nginx) |
| glitchtip-worker | error-tracking | Celery async worker | None (no inbound) |
| glitchtip-pg | error-tracking | Dedicated PostgreSQL for GlitchTip | ClusterIP (internal only) |
| glitchtip-redis | error-tracking | Redis for Celery broker + cache | ClusterIP (internal only) |

---

## 1. EXPOSURE — How Grafana and GlitchTip Get Public TLS

### Decision: ClusterIP + host nginx proxy_pass (not NodePort)

**Rationale:** The v2.0 Phase 07 edge pattern is already proven: host nginx terminates TLS via certbot; k3s ClusterIP addresses are routable from the VPS host node because k3s configures them on the host IP stack. NodePort would expose a random high port on the public interface, require ufw rules for that port, and complicate vhost routing — unnecessary given the existing pattern works.

**Concrete mechanism:**
- Grafana ClusterIP Service on port 3000 → host nginx upstream `grafana_obs`
- GlitchTip ClusterIP Service on port 8000 → host nginx upstream `glitchtip_obs`
- Two new vhost files added to `config/nginx/sites-available/`:
  - `grafana-stats-staging-solid-stats.conf`
  - `errors-stats-staging-solid-stats.conf`
- Each vhost: HTTP 80 → ACME challenge path + redirect; HTTPS 443 → proxy_pass to ClusterIP

**New vhost structure (mirrors existing `stats-staging-solid-stats.conf` exactly):**
```nginx
upstream grafana_obs {
    server <grafana-ClusterIP>:3000;
    keepalive 4;
}

server {
    listen 80;
    server_name grafana.stats-staging.solid-stats.ru;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name grafana.stats-staging.solid-stats.ru;
    ssl_certificate /etc/letsencrypt/live/grafana.stats-staging.solid-stats.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grafana.stats-staging.solid-stats.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    location / {
        proxy_pass http://grafana_obs;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

**DNS → cert → vhost sequencing (hard dependency order):**
1. Create DNS A records: `grafana.stats-staging.solid-stats.ru` → VPS IP and `errors.stats-staging.solid-stats.ru` → VPS IP. Wait for propagation (check with `dig`).
2. Install the HTTP-only vhosts first (no SSL directives) so ACME webroot challenges can be served. Reload nginx.
3. Run `certbot certonly --webroot -d grafana.stats-staging.solid-stats.ru -d errors.stats-staging.solid-stats.ru` (or two separate runs). Certbot issues against the webroot `/var/www/html`.
4. Update vhosts to add the `ssl_certificate` lines. Reload nginx.
5. Smoke-test: `curl -I https://grafana.stats-staging.solid-stats.ru/`.

**cert-manager boundary:** cert-manager exists in-cluster but is NOT used here. Public TLS lives on the host via certbot, same as v2.0. cert-manager is for in-cluster workloads — do not cross this boundary.

**Extend `bootstrap-edge.sh` or write `bootstrap-obs-edge.sh`:** The v2.0 script is idempotent and domain-parameterised. A dedicated `scripts/bootstrap-obs-edge.sh` is cleaner than modifying the runtime script, preserving the rule that runtime and obs deploy paths are independent. The obs edge script follows the exact same adopt-reconcile pattern (backup → install vhost → nginx -t → reload → certbot → deploy hook).

**ClusterIP address:** ClusterIPs are assigned at Service creation time. The vhost upstream address must be filled in after apply. Three options:
- Write the vhost with the ClusterIP (operator looks it up after apply, then restarts nginx). Simplest.
- Use the cluster DNS from the host (requires `/etc/hosts` or local resolver pointing at the cluster DNS — not standard for host nginx). Avoid.
- Use a fixed NodePort and configure nginx to `localhost:NodePort`. Works but adds the ufw rule complexity. Avoid.

**Decision:** Use ClusterIP. Add a step in the obs bootstrap runbook: `kubectl -n monitoring get svc grafana -o jsonpath='{.spec.clusterIP}'` to retrieve the address post-apply.

---

## 2. NAMESPACE LAYOUT

### Two-namespace split

| Resource | Namespace | Reason |
|----------|-----------|--------|
| Namespace manifest | monitoring | Metrics + logging stack |
| Namespace manifest | error-tracking | Error tracking — separate blast radius, separate lifecycle |
| Prometheus | monitoring | Owns TSDB; scrapes all targets |
| Grafana | monitoring | Datasources: Prometheus + Loki |
| Loki | monitoring | Log store |
| Alloy (DaemonSet) | monitoring | Collects logs from all pods, pushes to Loki |
| kube-state-metrics | monitoring | Cluster-state metrics |
| node-exporter (DaemonSet) | monitoring | Node metrics |
| postgres-exporter | monitoring | Scrapes app postgres in solid-stats-staging |
| rabbitmq-exporter | monitoring | Scrapes RabbitMQ in solid-stats-staging |
| GlitchTip web | error-tracking | Sentry-compatible HTTP API + UI |
| GlitchTip worker | error-tracking | Celery worker |
| GlitchTip postgres | error-tracking | Dedicated PostgreSQL; NOT the app postgres |
| GlitchTip redis | error-tracking | Celery broker |

### ServiceAccounts (no default SA rule maintained)

Every workload gets its own SA with `automountServiceAccountToken: false`. Explicit SAs per component:

| SA Name | Namespace | Used By |
|---------|-----------|---------|
| prometheus | monitoring | Prometheus pod (needs cluster-level read for scraping) |
| grafana | monitoring | Grafana pod |
| loki | monitoring | Loki pod |
| alloy | monitoring | Alloy DaemonSet (needs pod/node read for log metadata) |
| kube-state-metrics | monitoring | kube-state-metrics (ClusterRole, reads all namespaces) |
| node-exporter | monitoring | node-exporter DaemonSet |
| postgres-exporter | monitoring | postgres-exporter |
| rabbitmq-exporter | monitoring | rabbitmq-exporter |
| glitchtip | error-tracking | GlitchTip web + worker |
| glitchtip-postgres | error-tracking | GlitchTip postgres |
| glitchtip-redis | error-tracking | GlitchTip redis |

### Cross-namespace scraping (Prometheus → solid-stats-staging)

Prometheus needs to scrape pods in `solid-stats-staging` (and `kube-system` for kubelet). This requires a ClusterRole, not a namespace Role:

```yaml
# ClusterRole for Prometheus — read-only across all namespaces
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-scraper
rules:
  - apiGroups: [""]
    resources: ["nodes", "nodes/proxy", "nodes/metrics", "services", "endpoints", "pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["extensions", "networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics", "/metrics/cadvisor"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-scraper
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: prometheus-scraper
  apiGroup: rbac.authorization.k8s.io
```

kube-state-metrics also needs a ClusterRole (it reads all resource types). Its Helm chart generates this automatically — include in rendered output.

Alloy (DaemonSet for log collection) needs a ClusterRole to read pod metadata for log labels:
- `pods`, `nodes`, `namespaces` — get/list/watch

**NetworkPolicy implication for cross-namespace scraping:** A NetworkPolicy on `solid-stats-staging` pods that blocks ingress must explicitly allow Prometheus pods from the `monitoring` namespace. If default-deny is applied to `solid-stats-staging` before the allow rule exists, Prometheus loses targets. See section 6 for sequencing.

---

## 3. RENDER-THEN-APPLY PIPELINE

### Separate obs deploy path

```
k8s/
├── staging/          # existing runtime manifests (deploy-staging.yml owns this)
│   ├── 00-namespace.yaml
│   ├── 01-ci-rbac.yaml
│   └── ...
└── observability/    # new obs manifests (deploy-observability.yml owns this)
    ├── 00-namespaces.yaml          # monitoring + error-tracking Namespace
    ├── 01-obs-ci-rbac.yaml         # obs-ci-deployer SA + RBAC (operator-applied, excluded from CI)
    ├── 10-monitoring-namespace-config.yaml
    ├── 20-prometheus/              # rendered from helm template
    │   └── *.yaml
    ├── 30-grafana/
    │   └── *.yaml
    ├── 40-loki/
    │   └── *.yaml
    ├── 50-alloy/
    │   └── *.yaml
    ├── 60-kube-state-metrics/
    │   └── *.yaml
    ├── 70-node-exporter/
    │   └── *.yaml
    ├── 80-exporters/
    │   └── *.yaml
    └── 90-error-tracking/          # GlitchTip stack
        └── *.yaml
```

**Why a directory per component:** `helm template` output for kube-prometheus-stack is large (~50+ resources). Keeping per-component directories makes diffs readable and lets phases apply subsets.

**Helm rendering workflow:**
```bash
# Render kube-prometheus-stack (Prometheus + Grafana + kube-state-metrics + node-exporter)
helm template monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f k8s/observability/values/kube-prometheus-stack.yaml \
  > k8s/observability/20-prometheus-grafana-rendered.yaml

# Render Loki
helm template loki grafana/loki \
  -n monitoring \
  -f k8s/observability/values/loki.yaml \
  > k8s/observability/40-loki-rendered.yaml

# Render Alloy
helm template alloy grafana/alloy \
  -n monitoring \
  -f k8s/observability/values/alloy.yaml \
  > k8s/observability/50-alloy-rendered.yaml

# GlitchTip: render or write hand-crafted manifests
# (GlitchTip Helm chart at gitlab.com/glitchtip/glitchtip-helm-chart — evaluate before use;
#  hand-crafted manifests may be simpler for the small footprint required)
```

**Rendered manifests committed to git** — same philosophy as runtime manifests. Values files live in `k8s/observability/values/`. Rendering happens locally or in a pre-deploy CI step, and the output is committed. This means `git diff` shows exactly what will be applied.

**Apply ordering:**
1. `00-namespaces.yaml` — must be applied first (operator-applied, not CI)
2. `01-obs-ci-rbac.yaml` — operator-applied, excluded from CI glob
3. All others via sorted glob: `find k8s/observability -name '*.yaml' ! -name '00-*' ! -name '01-*' | sort`

### Separate CI workflow: `.github/workflows/deploy-observability.yml`

Fork from `deploy-staging.yml`. Key differences:
- Trigger: `workflow_dispatch` only (manual), or on push to `k8s/observability/**` path filter
- Concurrency group: `infrastructure-obs-deploy` (independent from runtime deploy)
- No interdependency with runtime deploy — either can run independently
- Secrets: same WG tunnel secrets (reuse), same kubeconfig secrets (reuse), PLUS obs-specific secrets (GRAFANA_ADMIN_PASSWORD, GLITCHTIP_SECRET_KEY, etc.)
- Namespace variable: `OBS_MONITORING_NS=monitoring OBS_ERROR_NS=error-tracking`
- Validate step: checks `k8s/observability/` directory + obs-specific script exists
- Dry-run: `kubectl apply -n monitoring --dry-run=server -f k8s/observability/...`
- Deploy: render secrets → apply namespaced secrets → apply manifests → rollout status checks

### RBAC extension — obs-ci-deployer

The existing `ci-deployer` SA and Role are scoped to `solid-stats-staging` only. Do NOT extend them to cover obs namespaces — that would break the independence guarantee.

Create a separate `obs-ci-deployer` SA in the `monitoring` namespace:
```yaml
# k8s/observability/01-obs-ci-rbac.yaml — operator-applied ONLY
# Two SAs: one in monitoring, one in error-tracking
# Each with a Role in their own namespace
# PLUS ClusterRoles for: Prometheus scraper (cluster-wide read), kube-state-metrics (cluster-wide read)
```

The obs CI token (`OBS_K8S_TOKEN`) is a separate GitHub secret pointing to `obs-ci-deployer` in `monitoring`. The kubeconfig script is reused with `K8S_NAMESPACE=monitoring K8S_USER_NAME=obs-ci-deployer`.

**What obs-ci-deployer needs:**
- Role in `monitoring`: full apply RBAC (same verbs as ci-deployer Role)
- Role in `error-tracking`: full apply RBAC
- ClusterRole (operator-applied, non-CI): `prometheus-scraper` ClusterRoleBinding
- ClusterRole (operator-applied, non-CI): `kube-state-metrics` ClusterRoleBinding

The ClusterRoles are workload RBAC (for Prometheus and kube-state-metrics pods at runtime), not CI deployer RBAC. The CI deployer needs namespace-scoped apply rights in `monitoring` and `error-tracking`. If the ClusterRoles for Prometheus/ksm are pre-rendered in the manifests, the obs-ci-deployer needs `clusterroles` and `clusterrolebindings` create/patch rights — or those are applied once by the operator and excluded from the CI glob.

**Simplest safe approach:** Operator applies all ClusterRoles/ClusterRoleBindings once (like `00-namespaces.yaml` and `01-obs-ci-rbac.yaml`). CI only applies namespace-scoped resources. Helm renders ClusterRole manifests into a separate file excluded from the CI deploy glob.

---

## 4. STORAGE

### Constraint recap
- local-path StorageClass: no expansion, Delete reclaim, single-node
- 31 GB free disk
- Existing PVCs: postgres-data 20Gi + rabbitmq-data 5Gi (not from free disk — they were allocated earlier; 31 GB is the remaining free space)

### PVC layout

| PVC Name | Namespace | Size | Component | Rationale |
|----------|-----------|------|-----------|-----------|
| prometheus-data | monitoring | 10Gi | Prometheus TSDB | 15-day retention, ~6 GB/day for a small cluster is far too much; for a single-node k3s with ~8 workloads scraping every 15s, expect ~100-200 MB/day. 10 Gi = 50-100 days of headroom at that rate. |
| loki-data | monitoring | 5Gi | Loki log chunks | 7-day retention on a low-traffic staging cluster. Typical compressed log volume: ~50-200 MB/day. 5 Gi = 25-100 days. |
| grafana-data | monitoring | 1Gi | Grafana dashboards + SQLite | Config only; data is disposable but useful to persist dashboards. |
| glitchtip-pg-data | error-tracking | 5Gi | GlitchTip PostgreSQL | Error events only, no app data here. GlitchTip retention policy prunes old events. |
| glitchtip-redis-data | error-tracking | 1Gi | Redis AOF | Optional persistence; Redis for Celery can be ephemeral. Consider emptyDir instead. |

**Total new PVC allocation: 22Gi** against 31 GB free. Leaves ~9 GB buffer. This is tight but workable given:
- Prometheus and Loki sizes are generous for actual staging throughput
- GlitchTip Postgres will stay small (errors only, auto-prune)
- local-path does NOT support expansion — right-sizing up front is mandatory

**Redis PVC decision:** Use 1Gi PVC (not emptyDir) so Celery tasks survive a Redis pod restart. If Redis is emptyDir, in-flight error events can be lost on pod reschedule.

**node-exporter and kube-state-metrics:** No PVCs needed — stateless.

**Alloy:** No PVC needed — stateless log forwarder (positions tracked in emptyDir or not at all for simplicity).

---

## 5. SECRETS

All secrets follow the established model: GitHub environment secrets → rendered at deploy time → `kubectl apply` as k8s Secrets. No secret values in git.

### New secrets required

**Obs CI workflow secrets (GitHub environment: staging):**

| GitHub Secret | k8s Secret Name | Namespace | Key | Used By |
|---------------|----------------|-----------|-----|---------|
| OBS_K8S_TOKEN | (CI token, not in-cluster) | — | — | obs-ci-deployer kubeconfig |
| GRAFANA_ADMIN_USER | grafana-admin | monitoring | admin-user | Grafana |
| GRAFANA_ADMIN_PASSWORD | grafana-admin | monitoring | admin-password | Grafana |
| GLITCHTIP_SECRET_KEY | glitchtip-secrets | error-tracking | SECRET_KEY | GlitchTip Django |
| GLITCHTIP_DB_PASSWORD | glitchtip-secrets | error-tracking | DATABASE_URL (full DSN) | GlitchTip → its own postgres |
| GLITCHTIP_SUPERUSER_EMAIL | glitchtip-secrets | error-tracking | GLITCHTIP_SUPERUSER_EMAIL | GlitchTip init |
| GLITCHTIP_SUPERUSER_PASSWORD | glitchtip-secrets | error-tracking | GLITCHTIP_SUPERUSER_PASSWORD | GlitchTip init |
| GLITCHTIP_PG_PASSWORD | glitchtip-pg-auth | error-tracking | POSTGRES_PASSWORD | GlitchTip's PostgreSQL |
| POSTGRES_EXPORTER_DSN | postgres-exporter-secrets | monitoring | DATA_SOURCE_NAME | postgres-exporter → app postgres |
| RABBITMQ_EXPORTER_URL | rabbitmq-exporter-secrets | monitoring | RABBITMQ_URL | rabbitmq-exporter → app RabbitMQ |

**Secret rendering:** Extend `scripts/render-staging-secrets.py` with a separate function/mode for obs secrets, or write `scripts/render-obs-secrets.py`. The latter is cleaner (one file per deploy path, independent invocations).

**GlitchTip DSN for app SDK:** The Sentry DSN (project DSN from GlitchTip) is generated post-deploy when a GlitchTip project is created. It cannot be pre-rendered as a GitHub secret. Workflow: GlitchTip admin creates project → copies DSN → operator adds `GLITCHTIP_DSN` to app repo secrets → app repo PR adds `SENTRY_DSN` env var. This is inherently a manual step after GlitchTip is live.

---

## 6. NETWORKPOLICY

### k3s NetworkPolicy enforcement confirmed

k3s ships an embedded kube-router netpol controller in firewall-only mode (no kube-router routing). This enforces `networking.k8s.io/v1` NetworkPolicy objects via iptables chains + ipsets. Flannel handles pod networking; kube-router handles policy enforcement. **NetworkPolicy IS supported and enforced on k3s with default Flannel.** No CNI replacement needed.

Confirmed from k3s docs: "K3s includes an embedded network policy controller" using "kube-router's netpol controller library."

### Ordering rule (critical)

**Apply NetworkPolicies ONLY after scraping/connectivity is confirmed working without them.** A wrong default-deny applied to `solid-stats-staging` before the Prometheus allow rule is in place will silently break metrics scraping (targets show as DOWN, but the root cause is not obvious). The sequencing is:

1. Deploy obs stack without any NetworkPolicies
2. Confirm: Prometheus targets healthy, Grafana datasources green, Loki queries return logs
3. Apply default-deny to `monitoring` namespace
4. Confirm: internal obs comms still work (Grafana → Prometheus, Alloy → Loki, etc.)
5. Apply default-deny to `error-tracking` namespace
6. Confirm: GlitchTip web → its postgres + redis, test error ingestion works
7. Apply allow-from-monitoring to `solid-stats-staging` namespace (for Prometheus scraping app targets)
8. Confirm: Prometheus targets healthy again

### NetworkPolicy design

**monitoring namespace — default deny + allow:**

```yaml
# 1. Default deny all ingress + egress in monitoring
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# 2. Allow Grafana inbound from host nginx (source: host node IP, not a pod)
# Host nginx is NOT a pod — it originates from the node's host network.
# Flannel/kube-router treats host-originating traffic as coming from the node IP.
# The correct selector is ipBlock with the VPS host IP (e.g., 10.43.0.1 is the
# k3s bridge gateway; the node's main interface IP must be used).
# Use ipBlock: cidr: 0.0.0.0/0 for host nginx ingress (acceptable for a staging
# single-node; tighten to node IP in production).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-hostnginx-to-grafana
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes: [Ingress]
  ingress:
  - from:
    - ipBlock:
        cidr: 0.0.0.0/0   # host nginx is not a pod; tighten to node CIDR if needed
    ports:
    - protocol: TCP
      port: 3000
---
# 3. Allow Grafana → Prometheus (egress from Grafana, ingress to Prometheus)
# 4. Allow Grafana → Loki (egress from Grafana, ingress to Loki)
# 5. Allow Prometheus → scrape targets in monitoring + solid-stats-staging
# 6. Allow Alloy → Loki (push logs)
# 7. Allow all monitoring pods → kube-dns (UDP 53)
# 8. Allow Prometheus → kubelet/cadvisor on host network (hostPath scrape needs egress to node IPs)
```

**error-tracking namespace — default deny + allow:**

```yaml
# 1. Default deny all
# 2. Allow host nginx → GlitchTip web (same ipBlock pattern as Grafana)
# 3. Allow GlitchTip web → its postgres (TCP 5432)
# 4. Allow GlitchTip web → its redis (TCP 6379)
# 5. Allow GlitchTip worker → its postgres + redis (same)
# 6. Allow all error-tracking pods → kube-dns (UDP 53)
# 7. Allow GlitchTip web egress for outbound (email, etc.) — defer if no external alerts
# 8. Allow app pods (solid-stats-staging) → GlitchTip web on port 8000 (Sentry SDK)
```

**solid-stats-staging namespace — add allow-from-monitoring:**

```yaml
# Do NOT apply default-deny to solid-stats-staging in v3.0.
# The runtime namespace currently has no NetworkPolicies.
# Only add the minimal allow-from-monitoring rule for Prometheus scraping:
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: solid-stats-staging
spec:
  podSelector: {}  # all pods in this namespace
  policyTypes: [Ingress]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
      podSelector:
        matchLabels:
          app.kubernetes.io/name: prometheus
    ports:
    - protocol: TCP
      port: 3000   # server-2 metrics
    - protocol: TCP
      port: 9187   # postgres-exporter (if co-located) — OR allow from monitoring NS generally
```

**Important:** Adding a NetworkPolicy to `solid-stats-staging` (even an allow-only) changes the namespace from "no policy = allow all" to "has policy = apply policy logic." Be explicit about what else needs ingress (e.g., internal app → postgres connections are within the same namespace and covered by same-namespace allows). Full default-deny for `solid-stats-staging` is out of scope for v3.0 — defer to a hardening phase.

---

## Data Flow Changes in v3.0

### New flows added

```
Prometheus ──scrape──→ server-2:3000/metrics (if /metrics exposed)
Prometheus ──scrape──→ postgres-exporter:9187 → app postgres:5432
Prometheus ──scrape──→ rabbitmq-exporter:9419 → rabbitmq:15672
Prometheus ──scrape──→ kube-state-metrics:8080
Prometheus ──scrape──→ node-exporter:9100 (hostNetwork DaemonSet)
Prometheus ──scrape──→ alloy:12345/metrics
Alloy ──tail logs──→  pod log files on host
Alloy ──push──→       Loki:3100 (HTTP)
Grafana ──query──→    Prometheus:9090
Grafana ──query──→    Loki:3100
host nginx ──proxy──→ Grafana ClusterIP:3000
host nginx ──proxy──→ GlitchTip ClusterIP:8000
app SDK (server-2, replay-parser-2, replays-fetcher) ──HTTP POST──→ GlitchTip web:8000/api/
GlitchTip web ──DB──→ glitchtip-postgres:5432
GlitchTip web ──Celery──→ glitchtip-redis:6379
GlitchTip worker ──Celery consume──→ glitchtip-redis:6379
GlitchTip worker ──DB──→ glitchtip-postgres:5432
```

### Unchanged flows

```
host nginx → server-2 ClusterIP:3000  (existing runtime path, unaffected)
server-2 → postgres:5432              (unchanged)
server-2 → rabbitmq:5672              (unchanged)
replay-parser-2 → postgres:5432       (unchanged)
postgres-backup → S3                  (unchanged)
```

---

## New vs Modified Components

### New components (net-new in v3.0)

| Component | Type | Where |
|-----------|------|-------|
| `monitoring` Namespace | k8s resource | operator-applied |
| `error-tracking` Namespace | k8s resource | operator-applied |
| `obs-ci-deployer` SA + RBAC | k8s resource | operator-applied |
| Prometheus | Deployment + PVC | monitoring |
| Grafana | Deployment + PVC | monitoring |
| Loki | StatefulSet + PVC | monitoring |
| Alloy | DaemonSet | monitoring |
| kube-state-metrics | Deployment | monitoring |
| node-exporter | DaemonSet | monitoring |
| postgres-exporter | Deployment | monitoring |
| rabbitmq-exporter | Deployment | monitoring |
| GlitchTip web | Deployment | error-tracking |
| GlitchTip worker | Deployment | error-tracking |
| GlitchTip postgres | StatefulSet + PVC | error-tracking |
| GlitchTip redis | Deployment + PVC | error-tracking |
| `grafana-stats-staging-solid-stats.conf` | host nginx vhost | VPS host |
| `errors-stats-staging-solid-stats.conf` | host nginx vhost | VPS host |
| `scripts/bootstrap-obs-edge.sh` | operator script | repo |
| `scripts/render-obs-secrets.py` | CI script | repo |
| `.github/workflows/deploy-observability.yml` | CI workflow | repo |
| `k8s/observability/values/*.yaml` | Helm values | repo |
| `k8s/observability/**/*.yaml` | rendered manifests | repo |

### Modified components (existing, changed in v3.0)

| Component | Change |
|-----------|--------|
| `config/nginx/sites-available/` | Two new vhost files added |
| GitHub staging environment | New secrets added (OBS_K8S_TOKEN, GRAFANA_ADMIN_*, GLITCHTIP_*, exporter DSNs) |
| Possibly `server-2` app config | Add `SENTRY_DSN` env var (separate app repo PR, not this repo) |
| Possibly `replay-parser-2` | Same: add `SENTRY_DSN` (app repo PR) |

### NOT modified (runtime isolation guarantee)

| Component | Status |
|-----------|--------|
| `deploy-staging.yml` | Untouched |
| `k8s/staging/*.yaml` | Untouched (except optional allow-prometheus-scrape NetworkPolicy) |
| `scripts/render-staging-secrets.py` | Untouched |
| `ci-deployer` SA | Untouched — no new permissions |

---

## Recommended Project Structure (repo layout)

```
k8s/
├── staging/                        # existing — unchanged
└── observability/
    ├── values/
    │   ├── kube-prometheus-stack.yaml   # Prometheus + Grafana values
    │   ├── loki.yaml
    │   ├── alloy.yaml
    │   └── glitchtip.yaml               # if using GlitchTip helm chart
    ├── 00-namespaces.yaml              # monitoring + error-tracking (operator-applied)
    ├── 01-obs-ci-rbac.yaml             # obs-ci-deployer + ClusterRoles (operator-applied)
    ├── 20-prometheus-grafana.yaml      # helm template output
    ├── 30-loki.yaml                    # helm template output
    ├── 40-alloy.yaml                   # helm template output
    ├── 50-kube-state-metrics.yaml      # helm template output (or bundled in kube-prometheus-stack)
    ├── 60-node-exporter.yaml           # helm template output (or bundled)
    ├── 70-exporters.yaml               # hand-crafted: postgres-exporter + rabbitmq-exporter
    └── 80-glitchtip.yaml               # hand-crafted or helm template output

config/nginx/sites-available/
├── stats-staging-solid-stats.conf      # existing — unchanged
├── grafana-stats-staging-solid-stats.conf   # new
└── errors-stats-staging-solid-stats.conf    # new

scripts/
├── bootstrap-edge.sh               # existing — unchanged
├── bootstrap-obs-edge.sh           # new: installs obs vhosts + certbot for two new domains
├── render-staging-secrets.py       # existing — unchanged
└── render-obs-secrets.py           # new: renders obs-specific secrets

.github/workflows/
├── deploy-staging.yml              # existing — unchanged
└── deploy-observability.yml        # new: obs-specific CI workflow
```

---

## Suggested Build Order (Phase Sequence)

Dependencies flow strictly downward — each step requires the previous.

### Step 0: Preflight (prerequisite, not a deploy step)
- Resource snapshot: free RAM, disk, CPU on the VPS
- Confirm 31 GB free is accurate (`df -h`)
- Confirm k3s version (`kubectl version`)
- Confirm kube-router netpol is active (`kubectl get pods -n kube-system | grep kube-router` or check if netpol enforcement works with a test policy)
- Confirm local-path StorageClass is default
- **Gate:** If free RAM after host swap is insufficient for the trimmed obs stack, stop and resize (out of scope for this research)

### Step 1: Namespaces + RBAC (operator-applied, one-time)
- Apply `00-namespaces.yaml` (monitoring, error-tracking)
- Apply `01-obs-ci-rbac.yaml` (obs-ci-deployer SA + Roles + ClusterRoles)
- Extract and store `OBS_K8S_TOKEN` → GitHub staging environment secret
- **Why first:** Everything else depends on the namespaces existing

### Step 2: DNS A records (prerequisite for TLS)
- Create `grafana.stats-staging.solid-stats.ru` → VPS IP
- Create `errors.stats-staging.solid-stats.ru` → VPS IP
- Verify propagation: `dig +short grafana.stats-staging.solid-stats.ru`
- **Why here:** certbot requires DNS to resolve before it can issue certificates

### Step 3: Obs CI workflow + secret rendering
- Write `scripts/render-obs-secrets.py`
- Write `.github/workflows/deploy-observability.yml` (validate + dry-run jobs; deploy job held until manifests exist)
- Add obs secrets to GitHub staging environment
- **Why before manifests:** The workflow needs to be in place to validate and dry-run rendered manifests

### Step 4: Metrics stack (Prometheus + Grafana + kube-state-metrics + node-exporter)
- Render `kube-prometheus-stack` with staging-trimmed values (reduced resource requests, PVC sizes, 15-day Prometheus retention)
- Write PVC manifests (prometheus-data 10Gi, grafana-data 1Gi)
- Apply via obs CI workflow (or manually with `kubectl apply`)
- Verify: Prometheus targets page shows kube-state-metrics + node-exporter as UP
- **Why before Loki:** Grafana is the query UI; get it working first so Loki datasource can be verified visually

### Step 5: Host nginx obs vhosts + TLS (depends on Step 2 DNS propagation)
- Run `scripts/bootstrap-obs-edge.sh` on the VPS
- HTTP-only vhosts first → certbot issue → add SSL directives → nginx reload
- Look up Grafana ClusterIP: `kubectl -n monitoring get svc grafana -o jsonpath='{.spec.clusterIP}'`
- Update vhost upstream with actual ClusterIP
- Smoke-test: `curl -I https://grafana.stats-staging.solid-stats.ru/`
- **Dependency:** Step 4 must have applied Grafana Service (ClusterIP exists); Step 2 DNS must be live

### Step 6: Loki + Alloy
- Render Loki (SingleBinary mode, 7-day retention, 5Gi PVC)
- Render Alloy DaemonSet (pod log collection → push to Loki)
- Apply via obs CI workflow
- Add Loki datasource in Grafana
- Verify: Explore → Loki → query shows recent logs from `solid-stats-staging`

### Step 7: Exporters + dashboards
- Write postgres-exporter Deployment (points to app postgres in solid-stats-staging, DSN from secret)
- Write rabbitmq-exporter Deployment (points to rabbitmq management port)
- Apply
- Add Prometheus scrape configs for exporter endpoints (via ServiceMonitor or static scrape in values)
- Verify: Prometheus targets show postgres-exporter + rabbitmq-exporter as UP
- Import/configure Grafana dashboards: Kubernetes cluster, PostgreSQL, RabbitMQ

### Step 8: GlitchTip stack
- Write GlitchTip manifests (web Deployment, worker Deployment, glitchtip-postgres StatefulSet, glitchtip-redis Deployment, PVCs)
- Apply via obs CI workflow
- Look up GlitchTip ClusterIP, update errors vhost in `bootstrap-obs-edge.sh` (or update and re-run)
- Smoke-test `https://errors.stats-staging.solid-stats.ru/`
- Create GlitchTip project → copy DSN
- Send deliberate test error to verify ingestion

### Step 9: NetworkPolicies (LAST — after all connectivity verified)
- Apply default-deny to `monitoring` namespace
- Confirm Grafana datasources still green (if not, the allow rules are incomplete)
- Apply default-deny to `error-tracking` namespace
- Confirm GlitchTip still functional
- Apply `allow-prometheus-scrape` NetworkPolicy to `solid-stats-staging`
- Confirm Prometheus targets in solid-stats-staging still UP
- **Why last:** Wrong policies silently break scraping; only apply once baseline is confirmed

### Step 10: App SDK integration (separate app repo PRs, not this repo)
- Add `SENTRY_DSN` env var to server-2, replay-parser-2, replays-fetcher
- Errors-only SDK init (no traces, no performance monitoring)
- Verify GlitchTip receives events from each workload

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Extending ci-deployer to cover obs namespaces

**What:** Adding `monitoring` and `error-tracking` to the existing `ci-deployer` ClusterRole or adding new RoleBindings for `ci-deployer` in the new namespaces.

**Why wrong:** Couples runtime and obs deploy paths. If the obs CI breaks or the ClusterRole gets too broad, it risks the runtime deploy. The independence guarantee requires separate SAs.

**Instead:** Create `obs-ci-deployer` SA in `monitoring` with its own Roles in both obs namespaces.

### Anti-Pattern 2: Applying default-deny NetworkPolicy before verifying connectivity

**What:** Adding `default-deny-all` to `solid-stats-staging` or `monitoring` as part of the initial obs deploy, before confirming Prometheus scraping works.

**Why wrong:** Prometheus targets go DOWN silently. The namespace is isolated, but the operator doesn't notice until checking target health — and debugging iptables rules under kube-router is non-trivial.

**Instead:** Verify all scrape targets are UP, then add NetworkPolicies in the order specified in Step 9 above, confirming after each apply.

### Anti-Pattern 3: Using NodePort for Grafana/GlitchTip Services

**What:** Setting service type to NodePort for the obs UI services so host nginx can reach them at `localhost:<nodePort>`.

**Why wrong:** Adds a ufw rule for a high port on the public interface, or requires careful `in on lo` rules. ClusterIPs are already host-routable in k3s single-node — NodePort adds complexity for no benefit.

**Instead:** ClusterIP Services + `proxy_pass http://<ClusterIP>:<port>` in host nginx.

### Anti-Pattern 4: Storing rendered manifests outside git

**What:** Rendering Helm charts in CI and applying them without committing the rendered output to git.

**Why wrong:** Breaks the `git as source of truth` invariant established in v2.0. There is no way to audit what was applied, and `kubectl diff` comparisons become impossible.

**Instead:** Render locally, commit the output to `k8s/observability/`, and CI applies what is in git.

### Anti-Pattern 5: GlitchTip sharing the app PostgreSQL

**What:** Pointing GlitchTip at the existing app `postgres` StatefulSet.

**Why wrong:** Error events from a GlitchTip write surge could exhaust connections or disk on the app database. GlitchTip schema lives alongside app schema — restoring the app database from backup also restores GlitchTip state (confusing). The plan explicitly requires separate GlitchTip postgres.

**Instead:** Dedicated `glitchtip-postgres` StatefulSet in `error-tracking` namespace.

---

## Integration Points Summary

| Point | From | To | New/Modified |
|-------|------|----|--------------|
| Host nginx proxy | VPS host | Grafana ClusterIP:3000 | New vhost |
| Host nginx proxy | VPS host | GlitchTip ClusterIP:8000 | New vhost |
| Prometheus scrape | monitoring | solid-stats-staging pods /metrics | New cross-NS scrape |
| Prometheus scrape | monitoring | postgres-exporter:9187 | New exporter |
| Prometheus scrape | monitoring | rabbitmq-exporter:9419 | New exporter |
| Alloy log tail | monitoring (DaemonSet) | All pod logs on host | New DaemonSet |
| Alloy push | monitoring | Loki:3100 | New internal flow |
| Grafana query | monitoring | Prometheus:9090 | New datasource |
| Grafana query | monitoring | Loki:3100 | New datasource |
| SDK error POST | solid-stats-staging apps | GlitchTip:8000 (cross-NS) | App repo PRs |
| GlitchTip → DB | error-tracking | glitchtip-postgres:5432 | New internal flow |
| GlitchTip → cache | error-tracking | glitchtip-redis:6379 | New internal flow |
| certbot | VPS host | LE ACME for 2 new domains | New cert lineages |
| CI deploy | GitHub Actions | monitoring + error-tracking | New workflow + SA |

---

## Sources

- [k3s Networking Services docs — embedded netpol controller confirmed](https://docs.k3s.io/networking/networking-services)
- [SUSE k3s Network Policy blog — kube-router in firewall-only mode](https://www.suse.com/c/rancher_blog/k3s-network-policy/)
- [GlitchTip Helm chart (GitLab)](https://gitlab.com/glitchtip/glitchtip-helm-chart)
- [kube-prometheus-stack Helm chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- Existing codebase: `k8s/staging/01-ci-rbac.yaml`, `scripts/bootstrap-edge.sh`, `config/nginx/sites-available/stats-staging-solid-stats.conf`, `.github/workflows/deploy-staging.yml`
- Milestone context: `.planning/PROJECT.md`, `plans/infrastructure/briefs/observability-plan.md`

---
*Architecture research for: v3.0 Staging Observability Stack integration*
*Researched: 2026-06-13*
