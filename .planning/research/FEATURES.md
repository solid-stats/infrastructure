# Feature Research

**Domain:** Staging observability stack — metrics + logs + error tracking on k3s
**Researched:** 2026-06-13
**Confidence:** MEDIUM (official Grafana/Loki/Alloy docs via context7; GlitchTip via official install docs + community K8s guide; dashboard IDs cross-checked via grafana.com)

---

## Feature Landscape

### Table Stakes (Must-Have for "Usable")

These are the capabilities without which the observability stack provides no value.
Missing any of these = stack feels broken.

| Feature | Why Expected | Complexity | Acceptance Check |
|---------|--------------|------------|-----------------|
| Prometheus scraping kubelet/cAdvisor | Container CPU/mem/restart data is the baseline cluster signal | LOW | Targets page shows kubelet and cAdvisor endpoints as UP |
| kube-state-metrics scraping | Pod phase, deployment replicas desired/available, CronJob last-schedule | LOW | `kube_pod_status_phase` metric present in Prometheus |
| node-exporter scraping | Host CPU, memory, disk, network — the node is RAM-bound so this is critical | LOW | `node_memory_MemAvailable_bytes` present in Prometheus |
| Grafana with Prometheus datasource provisioned as code | The UI through which all metrics are viewed; provisioned so it's reproducible | LOW | Datasource shows "Data source connected and labels found" in health check |
| Grafana with Loki datasource provisioned as code | Log viewer wired to the same Grafana instance | LOW | Loki datasource health returns green; a LogQL query returns results |
| Node/host dashboard (Grafana ID 1860) | RAM-bound single node — you must see memory pressure immediately | LOW | Dashboard loads, panels show current data |
| Kubernetes cluster overview dashboard (ID 7249 or 21742) | Pod restarts, deployment health — the day-one "is anything broken?" view | LOW | Dashboard loads, pod phase panels populate |
| Loki + Alloy collecting cluster logs (~7d retention) | Without logs you cannot diagnose crashes or errors you see in Grafana | MEDIUM | LogQL `{namespace="solid-stats-staging"}` returns recent lines |
| GlitchTip with closed registration + local admin user | Error tracking with no open signup — single-node staging, not public | MEDIUM | Admin UI accessible; no self-register link visible at /accounts/signup/ |
| GlitchTip project + DSN issued | DSN is what the SDK needs; without it, SDK integration has nothing to send to | LOW | DSN string visible in project Settings > Client Keys |
| Prometheus scraping postgres-exporter | PostgreSQL health is core to the product — connection count, replication lag, transaction rate | MEDIUM | `pg_up` metric = 1 in Prometheus; exporter target UP |
| Prometheus scraping RabbitMQ built-in /metrics (port 15692) | Queue depth and consumer count are the primary signals for the message pipeline | LOW | `rabbitmq_queue_messages` metric present; target UP |
| PostgreSQL exporter dashboard (ID 9628 or 14114) | First signal that DB is healthy / under pressure | LOW | Dashboard loads, `pg_up` panel shows 1 |
| RabbitMQ overview dashboard (ID 10991) | Queue depth visible immediately after deploy | LOW | Dashboard loads, queue panels show data |
| Datasources and dashboards provisioned as ConfigMaps | Reproducibility: stack can be torn down and rebuilt from git, no manual re-import | MEDIUM | `kubectl apply` of manifests produces a working Grafana with all datasources and dashboards present |
| Observability namespace isolation from runtime namespace | Observability outage must never cause a runtime deploy failure (brief validation gate) | LOW | Separate namespace; runtime CD has no dependency on obs namespace readiness |
| Secrets for all credentials (Grafana admin, GlitchTip DB, exporter DSNs) | Project-wide rule: no credential values in git or ConfigMaps | LOW | No plaintext passwords in rendered manifests or ConfigMaps; all via Kubernetes Secrets |

### Differentiators (Adds Value Beyond Baseline)

These are the Solid-specific dashboard capabilities called for in the brief. They are not
generic — they are the observability signals specific to this product's workflows.

| Feature | Value Proposition | Complexity | Acceptance Check |
|---------|-------------------|------------|-----------------|
| Workload rollout dashboard (Deployments: desired vs available, pod restarts per workload) | Answers "did my deploy land cleanly?" without kubectl | MEDIUM | server-2 and replay-parser-2 restart counts visible per workload |
| CronJob / backup health panel (last schedule time, last success, job failure count) | postgres-backup CronJob is the primary data-safety signal | MEDIUM | `kube_cronjob_status_last_schedule_time` panel present; last backup < 25h ago |
| Queue depth + consumer count panel for replays-fetcher pipeline | replays-fetcher → RabbitMQ → replay-parser-2 is the core ingest path; queue depth = proxy for pipeline health | MEDIUM | `rabbitmq_queue_messages` per-queue panel shows solid-stats queues |
| PostgreSQL database health panel (pg_up, active connections, long-running queries) | server-2 is Postgres-heavy; connection exhaustion is a real risk at scale | MEDIUM | pg_up, pg_stat_activity panels populated for solid-stats-staging DB |
| Errors-only GlitchTip SDK integration prepared for server-2, replay-parser-2, replays-fetcher | Surfaces unhandled exceptions in production before they become silent data-loss events | HIGH | Deliberate `Sentry.captureException(new Error("staging-test"))` call produces event in GlitchTip UI |
| host nginx vhosts for grafana. and errors. subdomains + certbot TLS | Public access without VPN; standard pattern from v2.0 edge automation | MEDIUM | https://grafana.stats-staging.solid-stats.ru loads Grafana login; HTTPS certificate valid |
| Log stream per workload query pre-built | Engineers can jump to `{namespace="solid-stats-staging", pod=~"server-2.*"}` in one click | LOW | Saved LogQL queries or Explore links in dashboard row |

### Anti-Features (Out of Scope — with Rationale)

These were explicitly called out in the brief. They are listed here with reasons so they are
not re-added during roadmap or implementation planning.

| Feature | Why It Looks Attractive | Why It Is Out of Scope | Alternative Approach |
|---------|------------------------|----------------------|---------------------|
| Distributed traces / APM | "Full observability" — traces show request latency chains | Adds significant SDK complexity (auto-instrumentation), storage overhead (Tempo or Jaeger), and is a separate Grafana datasource. Staging is RAM-bound (8 GB). Zero use-case identified that can't be served by metrics + logs at this stage. | Logs + error tracking covers the 95% case. Revisit if latency regressions become a blocker. |
| Session replay | User-facing debugging for frontend issues | No frontend in staging scope; all workloads are backend/batch. SDK overhead adds to already-tight RAM budget. | Not applicable — staging has no user sessions to replay. |
| External alert delivery (Telegram/Discord/Slack/email) | "We need to know when something breaks" | Requires alert routing config, external credentials, on-call workflow setup, and noise tuning. On a single-engineer staging environment this is premature — dashboards provide sufficient visibility. | Check dashboards on deploy / after CronJob windows. Add alerting in a dedicated phase once alert rules are tuned. |
| OAuth / SSO for Grafana or GlitchTip | Convenient for team login | No team beyond 1-2 engineers in staging. Local admin users are sufficient. SSO adds external IdP dependency and configuration complexity disproportionate to the benefit. | Local Grafana admin user + local GlitchTip superuser created once via management command. |
| GlitchTip application-log ingestion | "Centralise everything in one place" | GlitchTip is not a log aggregator. Sending logs there would duplicate Loki, increase GlitchTip storage load, and blur the separation between error events (GlitchTip) and raw logs (Loki). | Logs go to Loki via Alloy. GlitchTip receives only SDK-captured error events. |
| Full custom dashboards for every domain workflow | Complete visibility from day one | High authoring cost; most domain dashboards require a running system with data to know what's useful. Day-one dashboards from community IDs cover the gap. | Import community dashboards first; add Solid-specific panels incrementally as gaps emerge from actual use. |
| Long-term metrics/log/error retention | Historical trend analysis | Staging observability data is explicitly treated as disposable (brief decision). Long retention increases PVC size on an already-constrained node, adds compaction complexity, and has no use-case until production. | Keep ~7-day log window. Prometheus default 15-day retention is fine. GlitchTip events auto-expire. |
| In-cluster Ingress controller | Clean Kubernetes ingress pattern | k3s on staging has Traefik disabled; adding an ingress controller is a separate project with network policy implications. The v2.0 edge pattern (host nginx vhosts) works and is already proven. | Reuse host nginx + certbot pattern from Phase 07 of v2.0. NodePort Services exposed to localhost; nginx proxies to them. |
| Production observability (this milestone) | Parity with staging | The brief explicitly scopes this milestone to staging only. Production mirror is a follow-on (decision D2) that requires its own preflight (sizing, retention policy, secrets, edge/TLS on prod host). | Mirror validated staging Helm values to production namespace as a separate milestone. |

---

## Feature Dependencies

```
Prometheus (scraping) ──requires──> kube-state-metrics (for K8s object metrics)
Prometheus (scraping) ──requires──> node-exporter (for host metrics)
Prometheus (scraping) ──requires──> postgres-exporter (for PG metrics)
Prometheus (scraping) ──requires──> RabbitMQ /metrics:15692 plugin enabled (already present in k8s/staging/20-rabbitmq.yaml)

Grafana dashboards ──require──> Grafana running with Prometheus datasource provisioned
Grafana log view ──requires──> Loki datasource provisioned + Loki running + Alloy collecting

Loki (log storage) ──requires──> Alloy (DaemonSet collector)
Alloy ──requires──> RBAC to list/watch pods in all namespaces

GlitchTip web/worker ──require──> GlitchTip-own PostgreSQL (separate from app DB)
GlitchTip web/worker ──require──> Redis/Valkey
GlitchTip DSN ──requires──> GlitchTip running + Organization created + Project created
SDK integration in app repos ──requires──> DSN issued from GlitchTip

Dashboard provisioning as ConfigMaps ──requires──> Grafana deployment mounting provisioning volumes
                                      ──requires──> Dashboard JSON baked into ConfigMaps at render time

host nginx vhosts (grafana./errors.) ──require──> NodePort or ClusterIP Services for Grafana + GlitchTip
                                      ──require──> certbot certs for the subdomains
                                      ──require──> DNS records pointing to VPS (external, manual)

NetworkPolicy for obs namespaces ──requires──> CNI enforcement confirmed (fluent from v2.0 research)
```

### Dependency Notes

- **RabbitMQ plugin already enabled:** RabbitMQ 4 management image exposes `/metrics` on port 15692 via the built-in prometheus plugin. No separate exporter Deployment needed — only a scrape target annotation or ServiceMonitor.
- **GlitchTip DB is separate from app DB:** GlitchTip needs its own PostgreSQL instance (or a separate database in a separate StatefulSet) to avoid entangling error-tracking availability with the app DB.
- **Dashboard provisioning is render-time:** Dashboard JSON ConfigMaps are generated during Helm render and applied with the rest of the manifests. This means dashboard changes require a re-render + re-apply cycle, not just a Grafana UI save.
- **Alloy RBAC is cluster-wide:** To collect logs from all namespaces (monitoring + solid-stats-staging + kube-system), Alloy's ServiceAccount needs a ClusterRole with get/list/watch on pods and namespaces.
- **host nginx requires pre-existing DNS:** The grafana. and errors. subdomains must resolve to the VPS before certbot can issue certs. This is an external prerequisite (Timeweb DNS panel or registrar).

---

## MVP Definition (v3.0 Scope)

### Launch With (v3.0 milestone)

- [ ] Prometheus + kube-state-metrics + node-exporter deployed and scraping — baseline cluster visibility
- [ ] postgres-exporter scraping app PostgreSQL — DB health visible from day one
- [ ] RabbitMQ built-in /metrics scraped — queue depth visible from day one
- [ ] Grafana deployed with Prometheus datasource provisioned as ConfigMap
- [ ] Node Exporter Full dashboard (ID 1860) imported as ConfigMap
- [ ] Kubernetes cluster overview dashboard (ID 7249 or 21742) imported as ConfigMap
- [ ] PostgreSQL exporter dashboard (ID 9628 or 14114) imported as ConfigMap
- [ ] RabbitMQ overview dashboard (ID 10991) imported as ConfigMap
- [ ] Loki deployed with 7-day retention (168h) configured in Helm values
- [ ] Alloy DaemonSet collecting pod logs with standard labels (namespace, pod, container, app)
- [ ] Grafana Loki datasource provisioned as ConfigMap
- [ ] GlitchTip deployed (web + worker + beat + own PG + Redis), closed registration, superuser created
- [ ] GlitchTip project created, DSN issued
- [ ] Grafana + GlitchTip accessible via host nginx vhosts with certbot TLS
- [ ] NetworkPolicy added for both obs namespaces (after CNI confirmation)
- [ ] Sentry SDK integration PRs prepared for server-2, replay-parser-2, replays-fetcher (errors only, traces_sample_rate=0.0)

### Add After Validation (v3.x)

- [ ] Solid-specific workload rollout dashboard panel (deployment replicas, restarts per workload) — add once community dashboards prove insufficient
- [ ] CronJob backup health panel — add once postgres-backup CronJob has run enough to generate data
- [ ] Queue depth per-queue panel for replays-fetcher pipeline — add after replays-fetcher is unsuspended and generating data
- [ ] Saved LogQL queries or Explore shortcuts per workload — low-effort once Loki is confirmed working

### Future Consideration (v4+ / production mirror)

- [ ] Production observability mirror — separate milestone (decision D2)
- [ ] Alert rules + routing — requires alert rule tuning from real data; separate milestone
- [ ] Traces/APM — deferred explicitly; revisit only if latency regressions become a blocking problem

---

## Feature Prioritization Matrix

| Feature | Operator Value | Implementation Cost | Priority |
|---------|---------------|---------------------|----------|
| Prometheus + kube-state-metrics + node-exporter | HIGH | LOW | P1 |
| Grafana + Prometheus datasource (provisioned) | HIGH | LOW | P1 |
| Node Exporter Full dashboard (ID 1860) | HIGH | LOW | P1 |
| Kubernetes cluster overview dashboard | HIGH | LOW | P1 |
| Loki + Alloy (cluster log collection) | HIGH | MEDIUM | P1 |
| Grafana + Loki datasource (provisioned) | HIGH | LOW | P1 |
| postgres-exporter + PG dashboard | HIGH | MEDIUM | P1 |
| RabbitMQ built-in metrics + dashboard | HIGH | LOW | P1 |
| GlitchTip (closed, local users, DSN) | HIGH | MEDIUM | P1 |
| host nginx vhosts + certbot TLS | HIGH | MEDIUM | P1 |
| Dashboard JSON provisioned as ConfigMaps | HIGH | MEDIUM | P1 |
| NetworkPolicy for obs namespaces | MEDIUM | LOW | P2 |
| Sentry SDK PRs for app repos | MEDIUM | MEDIUM | P2 |
| Solid-specific workload rollout panel | MEDIUM | MEDIUM | P2 |
| CronJob backup health panel | MEDIUM | MEDIUM | P2 |
| Queue depth per-queue panel | MEDIUM | LOW | P2 |
| Saved LogQL Explore links | LOW | LOW | P3 |
| External alerting | LOW | HIGH | deferred |
| Traces/APM | LOW | HIGH | deferred |

---

## Validation Feature Map

Each deliverable must map to a concrete acceptance check. This feeds the roadmap success criteria.

| Capability | Acceptance Check | Evidence Type |
|------------|-----------------|---------------|
| Prometheus scraping cluster metrics | Targets page: kubelet, cAdvisor, kube-state-metrics, node-exporter all UP | Prometheus UI screenshot / kubectl port-forward |
| postgres-exporter target | `pg_up{job="postgres-exporter"}` = 1 in Prometheus | PromQL query result |
| RabbitMQ target | `rabbitmq_queue_messages` present, target UP | PromQL query result |
| Grafana Prometheus datasource | Datasource health check returns green in Grafana UI | UI check |
| Grafana Loki datasource | Datasource health check returns green | UI check |
| Loki receiving logs | LogQL `{namespace="solid-stats-staging"}` returns lines with recent timestamps | LogQL in Grafana Explore |
| Node dashboard | Grafana ID 1860 loads with current CPU/mem data | UI check |
| K8s cluster dashboard | Pod phase and restart panels populated | UI check |
| PG exporter dashboard | pg_up = 1 panel visible | UI check |
| RabbitMQ dashboard | Queue depth panel shows data | UI check |
| GlitchTip up + closed registration | /accounts/signup/ returns 404 or registration disabled message | HTTP check |
| GlitchTip DSN issued | DSN string present in project Settings > Client Keys | UI check |
| GlitchTip receives test error | A forced `Sentry.captureException(new Error("staging-smoke-test"))` call produces an event in GlitchTip Issues | GlitchTip Issues UI |
| Grafana public TLS | https://grafana.stats-staging.solid-stats.ru loads, cert valid, login page visible | Browser / curl -I |
| GlitchTip public TLS | https://errors.stats-staging.solid-stats.ru loads, cert valid | Browser / curl -I |
| Dashboard provisioning idempotent | Destroy + re-apply manifests produces same dashboards without manual import | kubectl apply + verify |
| Runtime deploy independence | Applying observability manifests to failed obs namespace does not affect solid-stats-staging workloads | Namespace isolation check |

---

## Sources

- [Grafana provisioning ConfigMaps guide](https://oneuptime.com/blog/post/2026-02-09-grafana-provisioned-dashboards-configmaps/view) — MEDIUM confidence
- [Grafana Alloy collect logs in Kubernetes](https://grafana.com/docs/alloy/latest/collect/logs-in-kubernetes/) — MEDIUM confidence (official Grafana docs)
- [Grafana Node Exporter Full dashboard 1860](https://grafana.com/grafana/dashboards/1860-node-exporter-full/) — MEDIUM confidence
- [Grafana Kubernetes Cluster dashboard 7249](https://grafana.com/grafana/dashboards/7249-kubernetes-cluster/) — MEDIUM confidence
- [Kube State Metrics v2 dashboard 21742](https://grafana.com/grafana/dashboards/21742-object-s-health-kube-state-metrics-v2/) — MEDIUM confidence
- [PostgreSQL Overview dashboard 14114](https://grafana.com/grafana/dashboards/14114-postgres-overview/) — MEDIUM confidence
- [RabbitMQ Prometheus built-in metrics docs](https://www.rabbitmq.com/docs/prometheus) — MEDIUM confidence
- [RabbitMQ overview dashboard 10991](https://grafana.com/grafana/dashboards/10991) — MEDIUM confidence
- [GlitchTip install documentation](https://glitchtip.com/documentation/install/) — MEDIUM confidence (official)
- [GlitchTip K8s setup guide](https://blog.devops.dev/setup-glitchtip-with-k8s-a-simpler-sentry-alternative-0124d938736c) — LOW confidence
- [Loki retention configuration docs](https://grafana.com/docs/loki/latest/operations/storage/retention/) — MEDIUM confidence

---

*Feature research for: Solid Stats staging observability stack (v3.0 milestone)*
*Researched: 2026-06-13*
