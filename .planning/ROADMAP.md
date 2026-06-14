# Roadmap: Solid Stats Infrastructure

## Milestones

- ✅ **v1.0 Staging Foundation** - Phases 1-5 (shipped 2026-05-10)
- ✅ **v2.0 Production-Ready Infra & kubectl-native CD** - Phases 6-11 (shipped 2026-06-13; live prod cutover flip deferred by scope)
- 🚧 **v3.0 Staging Observability Stack** - Phases 12-18 (in progress)

## Overview

v1 proved the staging infrastructure path and v2.0 hardened it into production-readiness — kubectl-native CD over WireGuard, edge automation, an automated restore drill, S3 lifecycle, and a reversible cutover lever. v3.0 makes that runtime *observable* without destabilizing the workloads it observes. The node is RAM-bound (8 GB, no swap, ~1.7 GB free), so the keystone is resource protection: because host swap does NOT protect pods on k3s (NoSwap default + issue #12677), protection comes from PriorityClasses + app pods at Guaranteed QoS, and that must land *before* any observability pod does. On that foundation, a separate observability deploy path (its own `deploy-observability.yml`, `k8s/observability/`, `obs-ci-deployer` SA) carries the metrics stack (standalone Prometheus + Grafana + kube-state-metrics + node-exporter, rendered with `helm template`, never the operator), validated internally first. The public edge — DNS, the independent host-nginx obs-edge bootstrap, and certbot TLS — is split into its own phase so Grafana goes public on a clean, reusable edge that the error-tracking vhost later reuses. Logs (Loki monolithic + Alloy) and Sentry-compatible error tracking (GlitchTip, PostgreSQL-only) layer on as additional Grafana datasources and a second public edge vhost. NetworkPolicy comes last — only after scraping and datasources are proven — so a wrong default-deny can't mask earlier breakage. App-side error SDK PRs are tracked here but owned in the app repos, prepared once the GlitchTip DSN exists.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Staging Deploy Baseline** - Operator can deploy and verify the staging runtime from this infrastructure repository.
- [x] **Phase 2: Backup Gate** - Operator has a current PostgreSQL backup point in Timeweb S3 with restore-list validation and restore drill instructions.
- [x] **Phase 3: App CD Boundary** - App repositories can keep building images while infrastructure owns staging runtime wiring and pinned image tags.
- [x] **Phase 4: Controlled Full Run** - Operator can explicitly start and monitor a manual ingest run without enabling recurring fetching first.
- [x] **Phase 5: Diff and Cutover Readiness** - Operator can produce reviewable old-vs-new diff output while production cutover remains blocked.
- [x] **Phase 6: kubectl-native CD** - CI deploys staging via `kubectl` over a WireGuard tunnel as a namespace-scoped ServiceAccount, with SSH removed.
- [x] **Phase 7: Edge Automation** - Host nginx, TLS renewal, and firewall for staging are repo-managed, idempotent, and proven reversible.
- [x] **Phase 8: Automated Restore Drill** - Operator can prove the latest S3 backup restores cleanly into an ephemeral scratch PostgreSQL, never touching live data.
- [x] **Phase 9: web Runtime Wiring** - The future `web` application has a conventions-compliant, validated Kubernetes slot deployed as a stub.
- [x] **Phase 10: S3 Lifecycle & Retention** - Backup-prefix retention is enforced via a repo-stored expiration policy, with Timeweb support proven empirically.
- [x] **Phase 11: Production Cutover** - Operator can flip production traffic to the new runtime in one reversible nginx-upstream edit, gated and smoke-checked.
- [ ] **Phase 12: Resource Protection & Obs Foundation** - The node is OOM-protected (swap, PriorityClasses, app pods at Guaranteed QoS) and the two obs namespaces + least-privilege RBAC exist before any observability pod lands.
- [ ] **Phase 13: Deploy Pipeline & Metrics Stack** - Prometheus + Grafana + exporters run via a separate obs deploy path and dashboards render live data, validated internally (no public edge yet).
- [ ] **Phase 14: Public Edge & Grafana TLS** - DNS, the independent host-nginx obs-edge bootstrap, and certbot make Grafana reachable over TLS at its public staging URL behind local-user auth.
- [ ] **Phase 15: Log Stack** - Loki + Alloy collect cluster logs with ~7-day retention and a LogQL query returns recent `server-2` lines in Grafana.
- [x] **Phase 16: Error Tracking (GlitchTip)** - GlitchTip runs with its own PostgreSQL, closed registration, and a public TLS URL on the reused obs-edge; a forced test error appears and a project DSN exists.
- [ ] **Phase 17: Network Isolation & Stack Validation** - NetworkPolicies isolate the obs namespaces without breaking scraping, and one re-runnable script validates the whole stack on any fresh deploy.
- [ ] **Phase 18: App-side Error SDK** - Errors-only Sentry SDK integration is prepared as separate app-repo PRs for server-2, replay-parser-2, and replays-fetcher using the GlitchTip DSN.

## Phase Details

<details>
<summary>✅ v1.0 Staging Foundation (Phases 1-5) - SHIPPED 2026-05-10</summary>

### Phase 1: Staging Deploy Baseline

**Goal**: Operator can safely deploy and verify the complete staging runtime from the infrastructure repository.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: OWN-01, OWN-02, RUN-01, RUN-02, RUN-04, VAL-01, VAL-02, VAL-03, VAL-04, K8S-01, K8S-02, K8S-03
**Success Criteria** (what must be TRUE):

  1. Operator can see namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`, `replays-fetcher`, and backup resources represented in this repository.
  2. Operator can apply the staging manifests to k3s from this repository without relying on app repository deploy steps.
  3. Operator can verify PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2` rollout state after deploy.
  4. CI catches broken manifest/script syntax, unsafe secret rendering, missing resource limits, default ServiceAccount usage, and missing security-context or NetworkPolicy decisions before deploy reaches staging.
  5. Documentation states which v1 resources remain intentionally outside infrastructure ownership and which Kubernetes hardening exceptions are deliberate.

**Plans**: 4/4 complete

### Phase 2: Backup Gate

**Goal**: Operator has a verified PostgreSQL backup point before any full ingest run begins.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: BKP-01, BKP-02, BKP-03, BKP-04, BKP-05, K8S-04
**Success Criteria** (what must be TRUE):

  1. Nightly PostgreSQL backups write custom-format dumps to Timeweb S3 under `backups/postgres/`.
  2. Operator can launch a one-off backup Job from the CronJob and wait for it to complete.
  3. Each backup upload includes a dump, `pg_restore --list` output, and manifest metadata in S3.
  4. The backup gate blocks full ingest until the backup Job completed, S3 upload succeeded, and `pg_restore --list` succeeded.
  5. Operator can verify backup-related storage and PVC changes without risking PostgreSQL or RabbitMQ persistent state.

**Plans**: 1/1 complete

### Phase 3: App CD Boundary

**Goal**: Application repositories can keep publishing images while infrastructure becomes the source of truth for staging deployment wiring.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: OWN-03, OWN-04
**Success Criteria** (what must be TRUE):

  1. Operator can identify which shared Kubernetes resources app repositories should stop applying in v1.
  2. Staging app image tags are pinned explicitly in infrastructure manifests rather than relying on mutable `latest`.
  3. Operator can update a pinned app image tag in this repository while app repositories retain ownership of image builds.
  4. Legacy app CD overlap is documented with a gradual handoff path that avoids breaking active staging.

**Plans**: 1/1 complete

### Phase 4: Controlled Full Run

**Goal**: Operator can run and monitor a manual replay ingest after backup confidence exists.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: RUN-03, FULL-01, FULL-02, FULL-03
**Success Criteria** (what must be TRUE):

  1. `replays-fetcher` remains deployed but suspended until the operator explicitly starts a controlled manual ingest run.
  2. Operator can start a manual full-run path without enabling the recurring fetch schedule first.
  3. The full-run procedure records checkpoints and logs sufficient to resume or diagnose ingest failures.
  4. Operator can monitor queue depth, parser consumers, server readiness, and S3 object writes during the run.

**Plans**: 1/1 complete

### Phase 5: Diff and Cutover Readiness

**Goal**: Operator can compare old and new statistics and keep production cutover blocked until review is clean enough.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: DIFF-01, DIFF-02, DIFF-03
**Success Criteria** (what must be TRUE):

  1. Project defines the old-vs-new statistics comparison inputs, execution path, and expected output shape.
  2. Diff output separates strict failures from allowlisted known differences.
  3. Operator can review diff results after a full run without treating the output as automatic production approval.
  4. Production traffic cutover remains explicitly blocked until diff output is clean enough for review.

**Plans**: 1/1 complete

</details>

<details>
<summary>✅ v2.0 Production-Ready Infra & kubectl-native CD (Phases 6-11) - SHIPPED 2026-06-13</summary>

### Phase 6: kubectl-native CD

**Goal**: CI deploys staging by running `kubectl` on the runner over a WireGuard tunnel as a namespace-scoped ServiceAccount, with all SSH transport removed and the operator-bootstrap boundary documented.
**Depends on**: Phase 5
**Requirements**: CD-01, CD-02, CD-03, CD-04, CD-05, CD-06, CD-07, CD-08, CD-09
**Plans**: 4/4 complete

### Phase 7: Edge Automation

**Goal**: The public staging edge — host nginx vhost, TLS renewal, and firewall — is repo-managed, idempotently re-runnable, and proven reversible in isolation before it becomes the cutover lever.
**Depends on**: Phase 6
**Requirements**: EDGE-01, EDGE-02, EDGE-03, EDGE-04, EDGE-05
**Plans**: 4/4 complete

### Phase 8: Automated Restore Drill

**Goal**: Operator can prove on demand that the latest S3 backup restores into an ephemeral scratch PostgreSQL, never touching live data, with the drill kept out of the CD deploy path.
**Depends on**: Phase 6
**Requirements**: DRILL-01, DRILL-02, DRILL-03, DRILL-04
**Plans**: 3/3 complete

### Phase 9: web Runtime Wiring

**Goal**: The future `web` application has a conventions-compliant Kubernetes slot — deployed as a 0-replica / image-pending stub — wired into validation and the rollout-status gate.
**Depends on**: Phase 6
**Requirements**: WEB-01, WEB-02, WEB-03
**Plans**: 1/1 complete

### Phase 10: S3 Lifecycle & Retention

**Goal**: Backup-prefix retention is enforced through a repo-stored, script-applied expiration policy, with Timeweb S3 lifecycle support proven empirically before retention is relied upon.
**Depends on**: Phase 8
**Requirements**: S3-01, S3-02, S3-03
**Plans**: 3/3 complete

### Phase 11: Production Cutover

**Goal**: Operator can switch production traffic to the new runtime in a single reversible nginx-upstream edit, gated on a fresh backup and a green diff, with a tested rollback and a post-cutover smoke check (mechanism live-verified; live flip deferred by scope).
**Depends on**: Phase 7, Phase 8, Phase 9, Phase 10
**Requirements**: CUT-01, CUT-02, CUT-03, CUT-04
**Plans**: 2/2 complete

</details>

### 🚧 v3.0 Staging Observability Stack (In Progress)

**Milestone Goal:** Stand up the full self-hosted observability stack — metrics, logs, and Sentry-compatible error tracking — on the RAM-bound single-node staging k3s cluster, fitted with real OOM protection and a deploy path independent of runtime CD. Staging only; the production mirror (decision D2) is a later milestone.

**Execution Order:** Resource protection FIRST (swap + PriorityClasses + app pods to Guaranteed QoS + the two namespaces/RBAC) before any observability workload lands — swap does NOT protect pods (k3s NoSwap + issue #12677), so protection is PriorityClass/QoS. The separate obs deploy pipeline lands with the metrics stack (settles the render-then-apply model + Grafana) so metrics has a path to deploy without widening runtime CD; metrics is validated internally first (port-forward / ClusterIP). The public edge (DNS → HTTP vhost → certbot → TLS vhost) is its own phase that puts Grafana online and establishes the reusable obs-edge bootstrap that the GlitchTip vhost later reuses. Logs and error tracking layer on as additional datasources / a second edge vhost. NetworkPolicy LAST, only after scraping + datasources are validated. The app-side SDK track comes after the GlitchTip DSN exists.

#### Phase 12: Resource Protection & Obs Foundation

**Goal**: The staging node is protected against OOM eviction of postgres/server-2 before any observability pod is deployed, and the two observability namespaces with least-privilege RBAC exist as the foundation everything else deploys into.
**Depends on**: Phase 11
**Requirements**: PREP-01, PREP-02, PREP-03, PREP-04, PREP-05
**Success Criteria** (what must be TRUE):

  1. Operator can re-run a resource preflight that snapshots node CPU/memory/disk and existing allocations, recording the headroom available before any obs workload is applied.
  2. Persistent host swap is configured on the staging node (visible in `free -h` and `/proc/swaps`, persisted in fstab) and documented as host-process relief only — explicitly NOT a substitute for pod memory limits.
  3. `app-critical` and `obs-background` PriorityClasses exist, and the app workloads (postgres, server-2, and the other runtime pods) carry `app-critical` so the scheduler evicts observability pods first under memory pressure.
  4. postgres and server-2 run at Guaranteed QoS (memory requests == limits), confirmed on the live pods, so they are last to be evicted.
  5. `monitoring` and `error-tracking` namespaces exist, each with a non-default ServiceAccount and least-privilege RBAC (`obs-ci-deployer`), kept separate from the runtime `ci-deployer`.

**Plans**: 5 plans
Plans:
**Wave 1**

- [x] 12-01-PLAN.md — Validation harness: resource-preflight.sh + validate-phase-12.sh + validate-staging.py registration (PREP-01) [wave 1]
- [x] 12-02-PLAN.md — Bootstrap manifests: 01-obs-rbac.yaml (ns + obs-ci-deployer RBAC) + 02-priority-classes.yaml + CI glob exclusion (PREP-03, PREP-05) [wave 1]
- [x] 12-03-PLAN.md — Workload patches: priorityClassName app-critical on all 6 + Guaranteed QoS on postgres/server-2 (PREP-03, PREP-04) [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 12-04-PLAN.md — Host swap + kubelet NoSwap drop-in over SSH + docs/resource-protection.md (PREP-02) [wave 2, operator-gated]
- [x] 12-05-PLAN.md — Live apply: preflight sizing + bootstrap apply + QoS rollout + validate-phase-12.sh (PREP-01/03/04/05) [wave 2, operator-gated]

#### Phase 13: Deploy Pipeline & Metrics Stack

**Goal**: A complete metrics stack — Prometheus, Grafana, kube-state-metrics, node-exporter, and the PostgreSQL/RabbitMQ exporters — runs on staging via a deploy path independent of runtime CD, with dashboards rendering live data, validated internally (port-forward / ClusterIP) with no public edge yet.
**Depends on**: Phase 12
**Requirements**: DEP-01, DEP-02, DEP-03, DEP-04, MET-01, MET-02, MET-03, MET-04, MET-05, MET-06
**Success Criteria** (what must be TRUE):

  1. Observability manifests are rendered with `helm template`, committed under `k8s/observability/`, and applied by a separate `deploy-observability.yml` workflow (own concurrency group, obs-ci-deployer + WireGuard path); the runtime deploy path does not depend on the obs deploy succeeding, and all obs secrets are rendered from GitHub environment secrets into k8s Secrets with no secret values in git.
  2. Prometheus runs from standalone rendered manifests (no operator/CRDs) with a tuned scrape interval and bounded retention sized to its PVC, and its `/targets` page shows kube-state-metrics, node-exporter, postgres-exporter (app ≥ v0.15.0, non-superuser `pg_monitor` role), and RabbitMQ (native plugin, port 15692) all UP.
  3. Grafana runs with Prometheus provisioned as a healthy datasource and standard dashboards (node-exporter, kube-state/cluster, PostgreSQL, RabbitMQ) provisioned as code, all rendering live data.
  4. Operator can reach Grafana internally (port-forward or ClusterIP) and confirm dashboards render live data, with no public ingress or TLS configured yet.

**Plans**: 6 plans
Plans:
**Wave 1** *(authoring — autonomous)*

- [x] 13-01-PLAN.md — Validation scaffold + obs secret renderer: render-obs-secrets.py + validate-obs-manifests.py + validate-phase-13.sh (DEP-04) [wave 1]
- [x] 13-02-PLAN.md — Helm render: Prometheus + kube-state-metrics + node-exporter + postgres-exporter values + manifests (DEP-01, MET-01/02/03) [wave 1]
- [x] 13-03-PLAN.md — Helm render: Grafana datasource + sidecar + 4 vendored dashboards as ConfigMaps (DEP-01, MET-05, MET-06) [wave 1]
- [x] 13-04-PLAN.md — Prometheus SD ClusterRole into 01-obs-rbac.yaml + rabbitmq 15692/plugin + deploy-observability.yml (DEP-02, DEP-03, MET-04) [wave 1]

**Wave 2** *(operator bootstrap — autonomous:false)*

- [x] 13-05-PLAN.md — Operator bootstrap: apply Prometheus RBAC + create pg_monitor role + set GitHub secrets + storage preflight + docs/observability.md (DEP-04, MET-03) [wave 2, operator-gated]

**Wave 3** *(live apply + validation — autonomous:false)*

- [x] 13-06-PLAN.md — Live apply obs stack + rolling-restart rabbitmq + validate-phase-13.sh + right-size from kubectl top (MET-01..06) [wave 3, operator-gated]

**UI hint**: yes

#### Phase 14: Public Edge & Grafana TLS

**Goal**: Grafana is reachable over TLS at its public staging URL behind local-user auth via an independent host-nginx obs-edge bootstrap, establishing the reusable edge pattern the error-tracking vhost will later reuse.
**Depends on**: Phase 13
**Requirements**: EDGE-01, EDGE-02, EDGE-03, MET-07
**Success Criteria** (what must be TRUE):

  1. DNS A records for both `grafana.stats-staging.solid-stats.ru` and `errors.stats-staging.solid-stats.ru` resolve to the staging host (both issued now to avoid Let's Encrypt rate limits per Pitfall 9, even though the `errors.` upstream is wired later).
  2. An independent host nginx obs-edge bootstrap (v2.0 Phase 07 adopt-reconcile pattern, a dedicated `bootstrap-obs-edge.sh`) serves an HTTP-only vhost first, then a certbot-issued TLS certificate, proxying Grafana over a valid certificate — established as the reusable bootstrap the GlitchTip phase later extends for the `errors.` vhost.
  3. Operator can reach Grafana at `https://grafana.stats-staging.solid-stats.ru` behind local-user auth with healthy dashboards rendering live data.

**Plans**: 4 plans
**Wave 1**

- [x] 14-01-PLAN.md — author bootstrap-obs-edge.sh (env-parameterized adopt-reconcile, ClusterIP discovery, per-domain certbot)
- [x] 14-02-PLAN.md — author the grafana. (WebSocket TLS proxy) and errors. (503 placeholder) nginx vhosts

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 14-03-PLAN.md — author validate-obs-edge.py offline validator + docs/obs-edge-bootstrap.md runbook

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 14-04-PLAN.md — operator-gated: create DNS A records, run live bootstrap + per-domain certbot, verify Grafana over HTTPS

**UI hint**: yes

#### Phase 15: Log Stack

**Goal**: Cluster logs are collected conservatively into Loki with bounded retention and queryable in Grafana as a second datasource, without leaking request bodies or secrets.
**Depends on**: Phase 13
**Requirements**: LOG-01, LOG-02, LOG-03
**Success Criteria** (what must be TRUE):

  1. Loki runs in monolithic/filesystem mode on a right-sized PVC with compactor-driven ~7-day retention, confirmed by `loki_compactor_runs_total > 0`.
  2. A Grafana Alloy DaemonSet collects cluster logs with a conservative label set (namespace/pod/container/app/job only — no request bodies, no secrets) and reports `alloy_logs_entries_total > 0`.
  3. Loki is a healthy Grafana datasource and a LogQL query in Grafana Explore returns recent `server-2` log lines.

> **Metric-name correction (15-RESEARCH):** success criteria 1 & 2 above cite `loki_compactor_runs_total` / `alloy_logs_entries_total`, which do NOT exist in Loki/Alloy source. The real proofs are `loki_boltdb_shipper_compactor_running == 1` and `loki_write_sent_entries_total > 0`. Validation uses the corrected names.

**Plans**: 4 plans
Plans:
**Wave 1** *(authoring — autonomous)*

- [x] 15-01-PLAN.md — Render Loki (SingleBinary/filesystem/168h compactor retention) + validate-phase-15.sh harness with corrected metric names (LOG-01, LOG-03) [wave 1]
- [x] 15-02-PLAN.md — Render Alloy DaemonSet (conservative 5-label River pipeline) + 03-alloy-rbac.yaml operator bootstrap + validate-obs-manifests.py ClusterRole guard (LOG-02) [wave 1]
- [x] 15-03-PLAN.md — Add loki+alloy Prometheus scrape targets + Loki as 2nd Grafana datasource, re-render 10-prometheus.yaml + 50-grafana.yaml (LOG-01, LOG-03) [wave 1]

**Wave 2** *(live apply + validation — operator-gated, autonomous:false)*

- [x] 15-04-PLAN.md — Operator-apply alloy ClusterRole + live-apply obs stack + validate-phase-15.sh + right-size from kubectl top (LOG-01, LOG-02, LOG-03) [wave 2]

**UI hint**: yes

#### Phase 16: Error Tracking (GlitchTip)

**Goal**: GlitchTip captures errors with its own PostgreSQL and closed registration, is reachable over TLS at its public staging URL on the reused obs-edge bootstrap, and a forced staging test error is visible with a project DSN issued for the app-SDK track.
**Depends on**: Phase 13, Phase 14
**Requirements**: ERR-01, ERR-02, ERR-03
**Success Criteria** (what must be TRUE):

  1. GlitchTip runs with its own PostgreSQL (PostgreSQL-only mode, Valkey/Redis disabled) following the strict first-run order (migrate → close registration → create superuser), separate from the app database.
  2. Self-registration is disabled and only the seeded local superuser can log in (verified against the registration endpoint).
  3. The `errors.stats-staging.solid-stats.ru` vhost serves GlitchTip over valid TLS (reusing the Phase 14 obs-edge bootstrap with GlitchTip's ClusterIP), and a project + DSN exist with a deliberately forced staging test error appearing in GlitchTip.

**Plans**: 5 plans
**Wave 1**

- [x] 16-01-PLAN.md — GlitchTip own-postgres StatefulSet + web/worker Deployments + ClusterIP Service (ERR-01) [wave 1]
- [x] 16-02-PLAN.md — migrate Job + superuser seed Job (first-run order) + bin/start.sh SERVER_ROLE check (ERR-01) [wave 1]
- [x] 16-03-PLAN.md — secret renderer + validator + obs deploy workflow extensions for error-tracking; validate-phase-16.sh + test-glitchtip-ingest.sh + docs/glitchtip.md (ERR-01/02/03) [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 16-04-PLAN.md — live deploy + migrate/seed in order + org/project/DSN + forced-error test + right-size (ERR-01/02/03) [wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 16-05-PLAN.md — errors. vhost cutover to GlitchTip ClusterIP + operator DNS/cert public TLS (ERR-03) [wave 3]

**UI hint**: yes

#### Phase 17: Network Isolation & Stack Validation

**Goal**: NetworkPolicies isolate the observability namespaces without breaking validated scraping or datasources, and a single re-runnable script proves the whole stack healthy on any fresh staging deploy.
**Depends on**: Phase 15, Phase 16
**Requirements**: NET-01, NET-02, VAL-01
**Success Criteria** (what must be TRUE):

  1. NetworkPolicy enforcement under k3s/kube-router is confirmed with a test policy before any default-deny is relied upon.
  2. Default-deny + minimal-allow NetworkPolicies isolate `monitoring` and `error-tracking` (including an allow-prometheus-scrape rule into `solid-stats-staging`), applied only after scraping/datasources were validated, and all Prometheus targets remain UP and all Grafana datasources remain healthy after they are applied.
  3. A re-runnable validation script verifies the full stack on a fresh staging deploy: Prometheus target health, Grafana datasource health, a Loki query, and a forced GlitchTip test event — failing loudly on any broken capability.

**Plans**: TBD

#### Phase 18: App-side Error SDK

**Goal**: Errors-only Sentry SDK integration is prepared as separate, reviewable app-repo PRs for server-2, replay-parser-2, and replays-fetcher, wired to the GlitchTip DSN — tracked here, owned in those repos.
**Depends on**: Phase 16
**Requirements**: SDK-01
**Success Criteria** (what must be TRUE):

  1. A separate PR exists in each of server-2, replay-parser-2, and replays-fetcher adding errors-only Sentry SDK init (no traces/APM/session replay) wired to the GlitchTip DSN via a `SENTRY_DSN` env var sourced from secrets, not committed.
  2. The GlitchTip DSN handoff is documented (project DSN → app-repo secret → SDK env var) so each app repo can adopt it independently of this repo's deploy path.
  3. With the SDK PR merged in at least one app workload, a forced error from that workload appears in GlitchTip — confirming the end-to-end app → GlitchTip path.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Staging Deploy Baseline | v1.0 | 4/4 | Complete | 2026-05-10 |
| 2. Backup Gate | v1.0 | 1/1 | Complete | 2026-05-10 |
| 3. App CD Boundary | v1.0 | 1/1 | Complete | 2026-05-10 |
| 4. Controlled Full Run | v1.0 | 1/1 | Complete | 2026-05-10 |
| 5. Diff and Cutover Readiness | v1.0 | 1/1 | Complete | 2026-05-10 |
| 6. kubectl-native CD | v2.0 | 4/4 | Complete | 2026-06-12 |
| 7. Edge Automation | v2.0 | 4/4 | Complete | 2026-06-12 |
| 8. Automated Restore Drill | v2.0 | 3/3 | Complete | 2026-06-12 |
| 9. web Runtime Wiring | v2.0 | 1/1 | Complete | 2026-06-12 |
| 10. S3 Lifecycle & Retention | v2.0 | 3/3 | Complete | 2026-06-12 |
| 11. Production Cutover | v2.0 | 2/2 | Complete | 2026-06-12 |
| 12. Resource Protection & Obs Foundation | v3.0 | 5/5 | Complete   | 2026-06-13 |
| 13. Deploy Pipeline & Metrics Stack | v3.0 | 6/6 | Complete   | 2026-06-13 |
| 14. Public Edge & Grafana TLS | v3.0 | 3/4 | In Progress|  |
| 15. Log Stack | v3.0 | 4/4 | Complete   | 2026-06-13 |
| 16. Error Tracking (GlitchTip) | v3.0 | 5/5 | Complete   | 2026-06-14 |
| 17. Network Isolation & Stack Validation | v3.0 | 0/TBD | Not started | - |
| 18. App-side Error SDK | v3.0 | 0/TBD | Not started | - |
