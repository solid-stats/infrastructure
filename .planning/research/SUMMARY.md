# Project Research Summary

**Project:** Solid Stats Infrastructure — v3.0 Staging Observability Stack
**Domain:** Self-hosted observability (metrics + logs + error tracking) on a constrained single-node k3s
**Researched:** 2026-06-13
**Confidence:** HIGH

> Synthesized from STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md. (SUMMARY.md
> was persisted by the orchestrator after a #222 synthesizer false-refusal; content
> is the synthesizer's result reconciled against the four source documents.)

## Executive Summary

v3.0 adds a complete self-hosted observability suite — Prometheus metrics, Loki logs,
and GlitchTip (Sentry-compatible) error tracking — to the existing Solid Stats staging
k3s cluster. The cluster is a single node already running the app workloads at ~77% RAM /
93% CPU on 8 GB with **no swap**, so the binding constraint is memory headroom, not features.
The whole milestone is staging-only; the production mirror (decision D2) is a later milestone.

The recommended build uses **standalone Helm charts rendered with `helm template` then
`kubectl apply`** — explicitly NOT kube-prometheus-stack, whose ~14 CRDs are not produced by
`helm template` and break the render-then-apply / git-as-source-of-truth model carried over
from v2.0 Phase 06. Metrics come from the standalone `prometheus` + `grafana` +
`kube-state-metrics` + `prometheus-node-exporter` charts with static scrape config (no
ServiceMonitor CRDs); logs from monolithic **Loki** (filesystem storage, 7-day compactor
retention) fed by a **Grafana Alloy** DaemonSet; errors from **GlitchTip** with its own
PostgreSQL, run in PostgreSQL-only mode (Valkey/Redis disabled) to save memory. RabbitMQ
needs no separate exporter — the RabbitMQ 4 management image already exposes Prometheus
metrics on port 15692.

The dominant risk is OOM, and research overturned the original mitigation assumption:
**host swap does NOT protect pods** on k3s (kubelet default `NoSwap`, plus k3s issue #12677
where pods ignore swap even with the feature gate). Swap only relieves host processes
(kubelet/containerd/sshd). So the trimmed footprint must be real, and the deployment must
ship a **PriorityClass** split (app-critical ≫ obs-background) with app pods at Guaranteed
QoS so the scheduler always evicts observability before postgres/server-2. Budgeted footprint
is ~1.44 GB requests / ~2.5 GB limits; new PVCs total ~22–23 Gi against 31 Gi free, and
`local-path` has **no volume expansion**, so every PVC is a one-shot sizing decision.

## Key Findings

### Recommended Stack

Standalone charts only, pinned, rendered locally/CI and applied as plain manifests. No
in-cluster operator, no CRDs, no helm on the cluster. Full version table + values snippets
in STACK.md.

**Core technologies:**
- **prometheus** (chart 29.11.0, app v3.12.0) + **kube-state-metrics** (7.4.1) +
  **prometheus-node-exporter** (4.55.0) — metrics; static scrape config, not the operator.
- **grafana** (grafana-community 12.4.4) — dashboards + datasources provisioned as ConfigMaps at render time.
- **loki** (grafana-community 17.3.4, app 3.7.2) — monolithic, filesystem, compactor retention 168h.
- **alloy** (1.10.0, app v1.17.0) — DaemonSet log collector → Loki; conservative label set.
- **glitchtip** (chart 8.2.0, app v6.1.4) — own PostgreSQL, PostgreSQL-only mode (`VALKEY_URL=""`); web + worker + beat.
- **prometheus-postgres-exporter** (chart 8.0.0 → ensure app ≥ v0.15.0; v0.14.0 has a connection-leak bug) — non-superuser `pg_monitor` role.
- **RabbitMQ metrics:** native `rabbitmq_prometheus` plugin on port 15692 (management image) — the `prometheus-rabbitmq-exporter` chart is deprecated and unsupported on RabbitMQ 4. Confirm the existing `k8s/staging/20-rabbitmq.yaml` is the management variant and exposes 15692.

### Expected Features

Detail + acceptance checks in FEATURES.md.

**Must have (table stakes):**
- Grafana reachable at a stable public staging URL with healthy Prometheus + Loki datasources.
- Standard dashboards baked in as ConfigMaps: node-exporter (1860), kube-state/cluster (7249/21742), PostgreSQL (14114), RabbitMQ (10991).
- Prometheus scraping kubelet/cAdvisor, kube-state-metrics, node-exporter, postgres-exporter, RabbitMQ 15692.
- Conservative cluster-wide log collection (labels limited to namespace/pod/container/app/job; no request bodies, no secrets); a LogQL query returns recent server-2 lines.
- GlitchTip capturing errors, closed registration, local superuser, DSN issued; a forced test error appears.
- Scripted, re-runnable validation for each capability (datasource health, target health, Loki query, forced GlitchTip event).

**Should have (differentiators):**
- A small Solid-specific dashboard set (workloads, rollouts, queues, DB health, backups, CronJobs).
- postgres-exporter pointed at both the app DB and the GlitchTip DB.

**Defer / Anti-features (out of scope, with reason):**
- Traces / APM / session replay — errors-only scope; heavy, not needed for staging visibility.
- External alerting (Telegram/Discord/Slack/email) — deferred to a later milestone.
- OAuth/SSO — local users only in v1.
- GlitchTip application-log ingestion — errors only; logs live in Loki.
- Full custom dashboards for every domain workflow — start from community dashboards.

### Architecture Approach

Two namespaces — `monitoring` (Prometheus/Grafana/Loki/Alloy/exporters) and `error-tracking`
(GlitchTip + its postgres) — deployed through a **separate** `deploy-observability.yml` CI
workflow with its own concurrency group and its own `obs-ci-deployer` ServiceAccount (the
runtime `ci-deployer` RBAC is not widened, and runtime CD never depends on obs CD). Full detail
in ARCHITECTURE.md.

**Major components / integration points:**
1. **Exposure** — ClusterIP Services proxied by **host nginx** vhosts + certbot, the exact v2.0
   Phase 07 pattern (reuse the adopt-reconcile bootstrap; a dedicated `bootstrap-obs-edge.sh`
   keeps it independent). DNS A records for `grafana.`/`errors.` must exist and propagate
   **before** certbot issues; the HTTP-only vhost must be live first.
2. **Render pipeline** — `helm template` output committed under `k8s/observability/`, applied
   by the obs CI workflow over the same WireGuard tunnel + SA-token kubeconfig as v2.0.
3. **Storage** — new PVCs on `local-path`, right-sized up front (Prometheus ~7–10 Gi, Loki
   ~8–10 Gi, Grafana ~1 Gi, GlitchTip-pg ~5 Gi); ~9 Gi buffer left of 31 Gi free.
4. **Secrets** — Grafana admin, GlitchTip secret-key/superuser/DB, exporter DSNs rendered from
   GitHub environment → k8s Secrets, same model as runtime.
5. **NetworkPolicy** — k3s **does** enforce it (embedded kube-router, firewall-only mode on
   Flannel). Apply default-deny + minimal allow rules **last**, after scraping is validated.

### Critical Pitfalls

Top risks (full list + prevention + owning phase in PITFALLS.md):

1. **OOM evicts postgres/server-2** — no swap for pods + no PriorityClass. Avoid: add host swap
   for host-process relief only; ship `app-critical`/`obs-background` PriorityClasses + app pods
   at Guaranteed QoS **before** any obs pod lands. Budget memory as if pods have no swap.
2. **Undersized PVC on non-expandable local-path** — wrong size = redeploy with data loss.
   Avoid: size every PVC up front; Prometheus size-based retention capped ~80% of its PVC
   (compaction can transiently exceed the size limit, upstream #11112).
3. **GlitchTip first-run sequence** — migrations, closed registration, superuser. Avoid: strict
   order postgres → migration Job → `ENABLE_USER_REGISTRATION=false` → create superuser → issue DSN.
4. **Prometheus cardinality/CPU on an already-hot node** — cAdvisor + kube-state at short
   intervals. Avoid: longer scrape interval, metric-relabel drops, scrape only what's used.
5. **NetworkPolicy default-deny applied too early** silently kills all targets/datasources.
   Avoid: netpol strictly after Phase 1–3 connectivity is verified.

## Implications for Roadmap

Suggested **5 infra phases** plus a non-infra app-SDK track. This milestone continues v2.0's
numbering (last shipped phase was 11), so the roadmapper assigns actual numbers from **Phase 12**;
the logical sequence below is what matters.

### Phase A: Preflight & Resource Protection
**Rationale:** Hard prerequisite — without OOM protection the obs stack can take down postgres/server-2.
**Delivers:** host swap (2–4 GB persistent), `app-critical`/`obs-background` PriorityClasses, app
pods moved to Guaranteed QoS, the two namespaces + `obs-ci-deployer` RBAC, a re-runnable resource
preflight snapshot.
**Avoids:** Pitfalls 1 & 2.

### Phase B: Metrics Stack
**Rationale:** The foundation other phases observe against; standalone charts settle the render model.
**Delivers:** Prometheus (static scrape, tuned retention/cardinality) + kube-state-metrics +
node-exporter + grafana (provisioned datasource + community dashboards) + postgres-exporter +
RabbitMQ 15692 scrape; host nginx vhost + TLS for Grafana.
**Uses:** standalone prometheus/grafana/kube-state/node-exporter charts (STACK.md).
**Avoids:** Pitfall 4.

### Phase C: Log Stack
**Rationale:** Independent of metrics; adds the second Grafana datasource.
**Delivers:** Loki (monolithic, compactor retention) + Alloy DaemonSet + Loki datasource in Grafana
+ a LogQL smoke test returning recent server-2 lines.
**Avoids:** Alloy/k3s log-path and Loki retention pitfalls.

### Phase D: Error Tracking (GlitchTip) + Public Edge TLS
**Rationale:** Heaviest single component; its own validation gate; its own edge vhost.
**Delivers:** GlitchTip (own postgres, PostgreSQL-only mode) with the strict first-run sequence,
closed registration, superuser, DSN; host nginx vhost + TLS for `errors.`; a forced test-error gate.
**Avoids:** Pitfalls 3 & 9 (certbot rate limits / DNS-first).

### Phase E: Network Isolation (NetworkPolicy)
**Rationale:** Must come last so a wrong default-deny can't mask earlier breakage.
**Delivers:** default-deny + allow rules for `monitoring` and `error-tracking`, plus an
allow-prometheus-scrape rule into `solid-stats-staging`.
**Avoids:** Pitfalls 5 & 10.

### App-SDK track (not infra)
Errors-only Sentry SDK PRs in server-2 / replay-parser-2 / replays-fetcher, prepared in those
repos after the Phase D DSN exists. Tracked here, owned there.

### Phase Ordering Rationale
- Protection before payload: swap + PriorityClass + QoS before any obs pod (no-swap-for-pods reality).
- Metrics first because logs and error-tracking add datasources/edge on top of a settled render model.
- Edge work (DNS → HTTP vhost → certbot → TLS vhost) is sequenced inside the phase that needs it.
- NetworkPolicy always last, after connectivity is proven — never upfront.

### Research Flags
Phases likely needing deeper planning research:
- **Phase B:** confirm postgres-exporter app ≥ v0.15.0 in chart 8.0.0; confirm RabbitMQ management image + 15692 in the existing manifest. (~30 min)
- **Phase C:** Alloy config under k3s/containerd (log paths, permissions); verify `loki_compactor_runs_total > 0`. (~1 h)
- **Phase D:** GlitchTip Helm chart 8.2.0 maturity vs hand-crafted manifests; PostgreSQL-only mode is marked experimental (5.2+); certbot dry-run + DNS propagation. (1–2 days)
- **Phase E:** validate NetworkPolicy behavior with kube-router before committing default-deny. (~1 h)

Phases with standard patterns (lighter research):
- **Phase B core:** Prometheus/Grafana/node-exporter are well-documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Chart/app versions verified against live Chart.yaml on GitHub + ArtifactHub. |
| Features | MEDIUM | Official Grafana/Loki/GlitchTip docs; dashboard IDs cross-checked; some community sources. |
| Architecture | HIGH | k3s netpol + render-then-apply verified; direct extension of proven v2.0 Phase 06/07 patterns. |
| Pitfalls | HIGH | Memory/eviction/swap/cardinality/retention from primary k8s/Prometheus/Loki/k3s sources. |

**Overall confidence:** HIGH

### Gaps to Address
- **GlitchTip chart vs hand-crafted manifests** + PostgreSQL-only-mode stability — decide during Phase D planning; load-test with a forced error burst before declaring stable.
- **Swap mechanism** — host `fallocate`+`mkswap`+`swapon` (persistent via fstab); confirmed value is host-process relief only, not pod memory.
- **RabbitMQ plugin + port 15692** — confirm in `k8s/staging/20-rabbitmq.yaml` during Phase B.
- **PVC sizes** — conservative estimates; re-check `df -h` on the node before apply (no expansion later).
- **App repo names/locations** for the SDK PRs — confirm when that track starts.

## Sources

### Primary (HIGH confidence)
- prometheus-community Helm charts (Chart.yaml, verified): prometheus 29.11.0, kube-state-metrics 7.4.1, node-exporter 4.55.0, postgres-exporter 8.0.0/app v0.19.1.
- grafana-community/loki Chart.yaml — 17.3.4 (Loki 3.7.2); grafana/alloy 1.10.0 (v1.17.0).
- https://docs.k3s.io/networking/networking-services — embedded NetworkPolicy controller confirmed.
- https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/ — eviction/QoS.
- https://github.com/k3s-io/k3s/issues/12677 — pods ignore swap on k3s (NodeSwap).
- https://prometheus.io/docs/prometheus/latest/storage/ + issue #11112 — retention/compaction overflow.
- https://www.rabbitmq.com/docs/prometheus — RabbitMQ 4 native plugin, port 15692.
- https://github.com/prometheus-community/helm-charts/issues/3038 — kube-prometheus-stack CRDs vs `kubectl apply`.

### Secondary (MEDIUM confidence)
- ArtifactHub: glitchtip 8.2.0 (app v6.1.4), grafana-community/grafana 12.4.4.
- https://glitchtip.com/blog/2025-11-13-glitchtip-5-2-released/ — PostgreSQL-only mode, 256 MB min RAM.
- https://www.suse.com/c/rancher_blog/k3s-network-policy/ — kube-router firewall-only mode.
- Grafana docs: Alloy logs-in-kubernetes, Loki retention; Grafana provisioning via ConfigMaps.
- Grafana dashboard IDs 1860 / 7249 / 21742 / 14114 / 10991.
- https://gitlab.com/glitchtip/glitchtip-helm-chart — GlitchTip chart.
- https://letsencrypt.org/docs/rate-limits/ — certbot/Let's Encrypt limits.

### Tertiary (LOW confidence — validate during planning)
- https://blog.devops.dev/setup-glitchtip-with-k8s-... — community GlitchTip-on-k8s guide.
- https://gitlab.com/gitlab-org/omnibus-gitlab/-/issues/8292 — postgres-exporter v0.14.0 connection leak.

---
*Research completed: 2026-06-13*
*Ready for roadmap: yes*
