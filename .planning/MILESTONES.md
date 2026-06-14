# Milestones

## v3.0 Staging Observability Stack (Shipped: 2026-06-14)

**Phases completed:** 7 phases, 27 plans, 30 tasks

**Key accomplishments:**

- Phase 12 preflight snapshot script and kubectl assertion harness created and wired into CI syntax checks before any manifest or live-cluster change.
- obs-ci-deployer namespace-scoped RBAC for monitoring/error-tracking plus app-critical/obs-background PriorityClasses, both excluded from CI glob.
- All six runtime manifests now carry `priorityClassName: app-critical`; postgres and server-2 achieve Guaranteed QoS via requests==limits on every container including server-2's two busybox initContainers, with ASSUMED values flagged for Plan 05 live confirmation.
- Wave 0 gap-closure — obs secret renderer (DEP-04) + static manifest gate + live MET-01..06 bash harness, mirroring phase-12/render-staging patterns exactly.
- Helm chart v29.11.0/7.4.1/4.55.0/8.0.0 rendered into committed static YAML under k8s/observability/ — 4 values files + 4 manifests, validate-obs-manifests.py passes, Prometheus wired to pre-created SA with 15d+5GB retention on 8Gi PVC, all 4 scrape targets static_configs, postgres-exporter DSN from postgres-monitor-secret.
- grafana/grafana chart v10.5.15 rendered into 50-grafana.yaml with Prometheus provisioned datasource (prometheus-server.monitoring.svc:80), admin password from grafana-secrets existingSecret, dashboard sidecar enabled; 4 standard dashboard JSONs (1860/13332/9628/10991) vendored and wrapped as separate ConfigMaps labelled grafana_dashboard=1.
- Prometheus read-only ClusterRole added to operator-bootstrap file, rabbitmq port 15692 + enabled_plugins ConfigMap mounted in StatefulSet, independent deploy-observability.yml workflow authored with own concurrency group and obs-ci-deployer path — DEP-02, DEP-03, MET-04 satisfied.
- Env-parameterized obs-edge adopt-reconcile bootstrap with runtime ClusterIP discovery, HTTP-first certbot issuance, and nginx -t auto-restore gate — mirroring bootstrap-edge.sh 7-step structure.
- Two nginx vhost templates: Grafana TLS+WebSocket reverse proxy to ClusterIP with UPSTREAM_PLACEHOLDER token, and errors. TLS placeholder returning 503 pending Phase 16 GlitchTip wiring.
- Python 3 stdlib offline validator asserting obs-edge script and both vhosts are well-formed (4 check groups, exits 0 against Wave 1 artifacts), plus operator runbook covering the DNS gate, per-domain certonly, and live verification.
- Loki 3.6.11 rendered as SingleBinary StatefulSet on 10Gi filesystem PVC with 168h compactor retention; validate-phase-15.sh asserts LOG-01/02/03 with corrected metric names
- Alloy v1.17.0 rendered as DaemonSet with 5-label-only River pipeline (LOG-02); ClusterRole operator-bootstrapped in 03-alloy-rbac.yaml; validate gate now blocks cluster RBAC in CI-applied obs dir
- Prometheus extended with loki:3100 + alloy:12345 static scrape targets; Grafana re-rendered with Loki as a second provisioned datasource alongside Prometheus
- GlitchTip v6.1.8 PostgreSQL-only mode (VALKEY_URL="") with dedicated postgres StatefulSet (uid 70) and web/worker Deployments in error-tracking namespace, all secrets via secretKeyRef.
- Two one-shot Kubernetes Jobs enforce ERR-01 first-run order: postgres-ready → migrate (92) → showmigrations DB poll → createsuperuser (93), all secrets via secretKeyRef, no extra RBAC.
- Extended render-obs-secrets.py to emit GlitchTip error-tracking secrets (4 vars, url-encoded DATABASE_URL, sslmode=disable), wired a separate error-tracking CI deploy path (K8S_OBS_ET_TOKEN + split-by-namespace), and authored validate-phase-16.sh + test-glitchtip-ingest.sh + docs/glitchtip.md.
- GlitchTip 6.1.8 deployed live into `error-tracking`, migrate+seed in first-run
- Flipped the Phase 14 `errors.solid-stats.ru` 503 placeholder into a GlitchTip
- Default-deny + minimal-allow NetworkPolicies for monitoring and error-tracking namespaces, with RBAC and CI routing fixes so the manifests deploy into the correct namespace contexts.
- Thin bash orchestrator composing validate-phase-13/15/16.sh into a single re-runnable full-stack validation command with --quick and --public flag propagation and fail-closed cluster preflight.
- Proved kube-router enforcement empirically first, resolved the host-source-IP /
- Injected an optional `SENTRY_DSN` into the three app runtime Secrets, documented the

---

## v2.0 Production-Ready Infra & kubectl-native CD (Shipped: 2026-06-13)

**Phases completed:** 6 phases (06–11), 21 plans. In-scope work 100% complete; the
live production traffic flip (Phase 11) is deferred by scope per AGENTS.md (v2 targets
staging only).

**Key accomplishments:**

- **Phase 06 — kubectl-native CD (LIVE-VERIFIED).** SSH/scp deploy replaced by a
  WireGuard tunnel brought up in CI + a namespace-scoped `ci-deployer` ServiceAccount
  applying directly against the closed k3s API (`deploy-staging.yml`: PR validate+dry-run
  / master deploy split, single-deploy concurrency lock; `01-ci-rbac.yaml`; fail-closed
  WG handshake gate + SA-token kubeconfig builder; quarterly SA-token+WG rotation runbook).
  Proven end-to-end on real GitHub runners (PR #1 dry-run + master deploy green); **6 latent
  bugs found & fixed** (WG key via /dev/stdin under sudo, lazy-handshake init, kernel route
  to the tunnel IP, per-file `-f` for apply, kubeconfig `--embed-certs`, exclude 00-namespace).

- **Phase 07 — Edge automation (LIVE-VERIFIED).** Idempotent adopt-reconcile nginx/certbot/ufw
  bootstrap (verbatim vhost mirror with the `# CUTOVER` lever; certbot OnFailure drop-in;
  ufw split-tunnel 6443-on-wg0) + reversible teardown; `validate-edge.py`. All 6 VPS UAT
  checks passed; 2 live bugs fixed.

- **Phase 08 — Automated restore drill (LIVE-VERIFIED).** Ephemeral scratch-DB restore drill
  (`70-restore-drill.yaml`) with a CI guard blocking drill manifests from the CD path; drill
  PASSED on the cluster (26 tables / 303 267 rows to a scratch DB; postgres-0 untouched).

- **Phase 09 — `web` runtime wiring.** 0-replica `web` slot wired into the runtime + CD path.
- **Phase 10 — S3 lifecycle & retention (APPLIED LIVE).** 30-day retention on
  `backups/postgres/` + abort-incomplete-multipart 7d (`apply-s3-lifecycle.sh`,
  `backups-lifecycle.json`, 30-day floor enforced in CI). S3-03 empirically proven on live
  Timeweb S3 (GET/PUT/x-amz-expiration via a reversible round-trip); retention applied after
  a backup-inventory review (6 oldest of 37 backups async-expire). **Finding:** Timeweb
  `delete-bucket-lifecycle` is a no-op — a config is replace-only.

- **Phase 11 — Production cutover (mechanism LIVE-VERIFIED).** 4-gate reversible nginx
  upstream switch (`cutover.sh`: backup + green-diff coverage gates, byte-restore rollback,
  smoke-check auto-rollback, DRY_RUN) + `docs/cutover.md` + offline CI gate. Mechanism
  verified live (SELF_TEST rollback, DRY_RUN gates both ways + preview, live edge cutover-ready);
  the live production traffic flip is deferred by scope.

**Known deferred items (v2.x):** see STATE.md "Deferred Items" — Phase 6 doc-drift cleanup,
Phase 10 clean-bucket aws-cli guard fix, S3-04, CD-10, DRILL-05, CUT-05, and the Phase 11
live production flip (deferred by scope).

---
