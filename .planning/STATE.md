---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Staging Observability Stack
status: verifying
stopped_at: Completed 12-02-PLAN.md
last_updated: "2026-06-14T03:11:24.906Z"
last_activity: 2026-06-14 -- Phase 16 complete
progress:
  total_phases: 7
  completed_phases: 5
  total_plans: 27
  completed_plans: 26
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** Phase 17 — Network Isolation & Stack Validation

## Current Position

Phase: 16 — COMPLETE
Plan: 5 of 5
Status: Phase complete — ready for verification
Last activity: 2026-06-14 -- Phase 16 complete

Progress: [░░░░░░░░░░] 0% (0 plans complete this milestone)

## Performance Metrics

**Velocity:**

- Total plans completed: 8 (this milestone)
- Average duration: N/A
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 07 | 4 | - | - |
| 08 | 3 | - | - |
| 09 | 1 | - | - |

**Recent Trend:**

- Last 5 plans: none
- Trend: N/A

*Updated after each plan completion*
| Phase 06-kubectl-native-cd P06-01 | 10m | 2 tasks | 2 files |
| Phase 06-kubectl-native-cd P06-02 | 2 | 1 tasks | 1 files |
| Phase 07-edge-automation P07-01 | 150 | 2 tasks | 3 files |
| Phase 07-edge-automation P07-02 | 120 | 2 tasks | 3 files |
| Phase 07-edge-automation P07-03 | 117 | 2 tasks | 2 files |
| Phase 07-edge-automation P07-04 | 60 | 1 tasks | 1 files |
| Phase 08-automated-restore-drill P08-01 | 88 | 2 tasks | 2 files |
| Phase 08-automated-restore-drill P08-02 | 10 | 1 tasks | 1 files |
| Phase 08-automated-restore-drill P08-03 | 52 | 1 tasks | 1 files |
| Phase 09-web-runtime-wiring P09-01 | 10 | 2 tasks | 4 files |
| Phase 10-s3-lifecycle-retention P10-01 | 15 | 3 tasks | 4 files |
| Phase 10-s3-lifecycle-retention P10-02 | 10 | 1 tasks | 1 files |
| Phase 10-s3-lifecycle-retention P03 | 10 | 2 tasks | 2 files |
| Phase 11-production-cutover P01 | 20 | 1 tasks | 1 files |
| Phase 11-production-cutover P02 | 25 | 2 tasks | 2 files |
| Phase 12 P01 | 186 | 3 tasks | 3 files |
| Phase 12 P02 | 296 | 3 tasks | 3 files |
| Phase 12 P03 | 273 | 3 tasks | 6 files |
| Phase 13 P01 | 5 | 3 tasks | 3 files |
| Phase 13-deploy-pipeline-metrics-stack P02 | 35 | 2 tasks | 8 files |
| Phase 13-deploy-pipeline-metrics-stack P03 | 20 | 2 tasks | 7 files |
| Phase 13 P04 | 18 | 3 tasks | 3 files |
| Phase 14 P01 | 3 | 3 tasks | 1 files |
| Phase 14 P02 | 2 | 2 tasks | 2 files |
| Phase 14-public-edge-grafana-tls P03 | 12 | 2 tasks | 2 files |
| Phase 15-log-stack P01 | 35 | 3 tasks | 3 files |
| Phase 15-log-stack P03 | 20 | 2 tasks | 4 files |
| Phase 16-error-tracking-glitchtip P01 | 3m | 2 tasks | 2 files |
| Phase 16-error-tracking-glitchtip P02 | 6 | 2 tasks | 3 files |
| Phase 17 P01 | 5 | 3 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 12-17 roadmap]: v3.0 ordering invariants — resource protection (swap + PriorityClass/QoS + ns/RBAC) FIRST; metrics before logs/errors; obs deploy pipeline lands with metrics (P13) so metrics can deploy without widening runtime CD; edge (DNS→HTTP vhost→certbot→TLS) sequenced inside the UI-exposing phase; NetworkPolicy LAST (P16) after scraping/datasources proven; SDK track (P17) after the GlitchTip DSN exists.
- [Phase 12-17 roadmap]: swap does NOT protect pods on k3s (NoSwap default + issue #12677) — pod OOM protection is PriorityClass/QoS, not swap; swap is host-process relief only.
- [Phase 13/14 split]: metrics validated INTERNALLY in P13 (port-forward / ClusterIP, no public edge); the public obs-edge (DNS → HTTP vhost → certbot → TLS) is its own P14 that puts Grafana online. EDGE-01/02/03 + MET-07 → P14. Both grafana. + errors. certs issued in one P14 obs-edge bootstrap run (Pitfall 9 rate-limit avoidance); GlitchTip (P16) reuses that edge by filling in its ClusterIP.

- CD first / cutover last is the only hard ordering; Phases 7-10 are independent and sequenced by capacity.
- Edge (7) and restore drill (8) must land before cutover (11): the cutover lever IS the nginx upstream and must be proven reversible, and production is never flipped without proven recoverability.
- kubectl-native CD replaces SSH/scp: WireGuard-in-CI → namespace-scoped ServiceAccount with a long-lived token Secret → `kubectl apply` against the closed k3s API.
- Namespace + CI RBAC are operator-bootstrapped once (a namespaced Role cannot create the cluster-scoped Namespace); CI never creates the namespace.
- Anti-features confirmed out of scope: ArgoCD/Flux, service mesh / canary, cert-manager/ingress, `mc`, full-tunnel WireGuard, PITR/WAL, `--insecure-skip-tls-verify`.
- [Phase ?]: Long-lived kubernetes.io/service-account-token Secret used for ci-deployer (not TokenRequest)
- [Phase ?]: 01-ci-rbac.yaml is operator-applied once; CI deploy glob (Plan 04) must exclude it
- [Phase ?]: Both SA token and WireGuard key rotate in the same maintenance window to prevent credential gap
- [Phase ?]: GitHub environment secrets updated before VPS rotation to prevent mid-window deploy failures
- [Phase ?]: D-4: no custom certbot timer; drop-in extends stock certbot.service (EDGE-02, 07-02)
- [Phase ?]: D-5: OnFailure= drop-in routes failures to certbot-renew-failure.service, logger -p user.crit (EDGE-03, 07-02)
- [Phase 07-03]: D-7: ufw 6443 only on wg0 interface — wg0 pre-check exits 1 with FATAL if interface absent (EDGE-04)
- [Phase 07-03]: D-8: backup live vhost to .bak before overwrite; teardown restores .bak exactly (EDGE-05)
- [Phase 07-04]: EDGE-01..05: all requirements documented in docs/edge-bootstrap.md runbook (offline/operator-only split, Phase 11 lever, reversibility proof)
- [Phase 08-02]: DRILL-04 machine-enforced in CI: depth-1 glob guard in validate_manifest_shape() blocks accidental drill manifest promotion to CD path
- [Phase ?]: Six-section operator runbook order: overview-policy-apply-probe-evidence-caveat
- [Phase ?]: Evidence table blank by design: operator gate for S3-03 proof before apply
- [Phase ?]: strict_failures: 0 checks coverage; value divergence from parser rewrite is expected and allowlisted
- [Phase ?]: checks script+runbook marker strings; file existence alone insufficient (T-11-08)
- [Phase ?]: Phase 12-01 validation harness
- [Phase ?]: Phase 12-01 validation harness
- [Phase ?]: obs-ci-deployer Role is namespace-scoped to monitoring and error-tracking only — no access to solid-stats-staging enforced by k8s RBAC namespace boundary
- [Phase ?]: globalDefault:false on both PriorityClasses — prevents retroactive re-prioritisation of unclassed pods (Pitfall 6)
- [Phase ?]: daemonsets added to obs-ci-deployer Role for Grafana Alloy (Phase 15)
- [Phase ?]: ASSUMED Guaranteed QoS values (postgres cpu 500m/1Gi, server-2 cpu 250m/512Mi); Plan 05 must confirm vs live kubectl top P95
- [Phase ?]: rbac.create=false: Prometheus ClusterRole deferred to 01-obs-rbac.yaml operator-applied bootstrap
- [Phase ?]: scrapeConfigs static_configs for all 4 targets: avoids kubernetes_sd ClusterRole on single-node cluster
- [Phase ?]: postgres-exporter DSN via config.datasourceSecret existingSecret (postgres-monitor-secret/dsn)
- [Phase ?]: admin.existingSecret key correction (chart v10.5.15 nested key, not top-level adminExistingSecret)
- [Phase ?]: fullnameOverride: grafana — stable Service name for port-forward in 13-06 validation
- [Phase ?]: 4 dashboard ConfigMaps as separate YAML documents (Pitfall 8: one-per-JSON avoids 1 MiB k8s object limit)
- [Phase 14]: SKIP_UFW defaults to 1 for obs-edge — ports 80/443 already open from Phase 07; no duplicate ufw rules
- [Phase 14]: HTTP-first vhost pattern (RESEARCH Pattern 2 Option A): temp HTTP vhost install, certbot certonly -d, then TLS vhost swap; branch on cert-lineage existence
- [Phase ?]: UPSTREAM_PLACEHOLDER token in grafana vhost upstream block — sed-substituted by bootstrap-obs-edge.sh; offline validator (14-03) asserts no hardcoded ClusterIP
- [Phase ?]: errors. vhost: return 503 only, no upstream block — avoids nginx reload failure when GlitchTip not yet deployed (RESEARCH Pitfall 7)
- [Phase ?]: Validator 4 check groups mirror validate-edge.py structure
- [Phase ?]: Loki SingleBinary: replication_factor 1 + chunksCache/resultsCache disabled to prevent OOM
- [Phase ?]: Corrected metric names: loki_boltdb_shipper_compactor_running + loki_write_sent_entries_total
- [Phase ?]: ClusterRole stripped from 70-loki.yaml via Python YAML doc-split (obs-ci-deployer namespace-scoped, same as Phase 13 Prometheus)
- [Phase ?]: GlitchTip postgres uid=70 requires PGDATA subdir to avoid PVC bind error
- [Phase ?]: DB-poll migrate gate (showmigrations) instead of kubectl wait — no extra RBAC on glitchtip SA (T-16-08, 16-02)
- [Phase ?]: validate-obs-manifests.py accepts error-tracking alongside monitoring (Pitfall 5, 16-02)
- [Phase ?]: RBAC gap: obs-ci-deployer in error-tracking needs batch/jobs verb before 16-04 — operator action (16-02)
- [Phase ?]: PLACEHOLDER tokens (NODE_IP_PLACEHOLDER, K8S_API_EGRESS_PLACEHOLDER) in netpol manifests for 17-03 NET-01 probe resolution

### Pending Todos

- Phase 6 (RESOLVED 2026-06-13): live WireGuard handshake from a real GitHub runner
  + ci-deployer SA-token auth + real `kubectl apply`/`rollout` CONFIRMED. Cluster
  became reachable; operator bootstrapped `01-ci-rbac.yaml` + a dedicated CI WG peer
  (10.8.0.3, persisted in wg0.conf) + set staging-env secrets (WG_*/K8S_*/GHCR_*).
  PR #1 dry-run green; master deploy green (5 workloads rolled out). Found+fixed 6
  latent CD bugs: WG key via /dev/stdin not process-sub (sudo FD), handshake
  init (keepalive+prime), kernel route to tunnel IP, per-file `-f` for apply,
  kubeconfig `--embed-certs`, exclude `00-namespace.yaml` from CD glob. See
  `06-VERIFICATION.md` (Live CI Verification). Follow-up: doc-drift cleanup in
  docs/staging.md, README.md, AGENTS.md (CD_SSH_* / deploy-staging.sh references).

- Phase 7 (RESOLVED 2026-06-13): all 6 live-VPS UAT checks PASSED on
  root@89.223.124.200 (nginx -t, scoped certbot --dry-run, OnFailure drop-in, ufw
  6443-on-wg0, live curl TLS+HSTS+upstream, teardown→re-bootstrap reversibility).
  Edge adopted into repo-managed state. Found+fixed 2 live-only bugs: vhost drift
  (03521f5), ufw 6443/tcp→proto tcp (cfa2485). NOTE: unscoped `certbot renew
  --dry-run` hangs on operator-owned auth.solid-stats.ru cert (relay/auth vhost,
  outside Phase 7 scope) — Phase 7 cert renews cleanly when scoped by --cert-name.

- Phase 8 (RESOLVED 2026-06-13): live restore drill PASSED on the cluster
  (DRILL_RESULT=PASS, backup 20260612T030008Z, 26 tables/303267 rows restored to
  scratch solid_stats_drill; postgres-0 untouched; Job self-cleaned). Found+fixed
  2 live-only bugs: apk-needs-root → root initContainer + non-root main split
  (978e2f2); main uid 999→70 (real postgres user) for initdb getpwuid. See 08-UAT.md.

- Phase 10 (RESOLVED 2026-06-13): S3-03 empirically proven on live Timeweb S3 —
  GET returns standard 404 NoSuchLifecycleConfiguration; PUT→GET round-trip + a
  computed x-amz-expiration confirmed on an isolated test prefix; `delete-bucket-
  lifecycle` is a NO-OP (config is replace-only, never removable). 30-day retention
  APPLIED to backups/postgres/ via `FORCE_OVERWRITE=1 scripts/apply-s3-lifecycle.sh`
  after a backup-inventory review (37 backups; the 6 oldest >30d async-expire; 31
  retained, incl. today's). The `NoneType` aws-cli bug is a client parse error on the
  empty-<Message> 404; a latent v2.x follow-up: the apply guard/probe crash only on a
  CLEAN bucket (this bucket now always has a config, so non-blocking). See 10-UAT.md,
  docs/s3-lifecycle.md §5/§7.

- Phase 11 (mechanism LIVE-VERIFIED 2026-06-13; live flip DEFERRED BY SCOPE): the
  cutover MECHANISM was verified live without flipping prod (option B) — SELF_TEST ran
  the real rollback() (byte-restore asserted); DRY_RUN enforced both gates (fail-closed
  on missing green-diff, correct preview when satisfied via a /tmp gate); the live edge
  vhost is cutover-ready (`# CUTOVER:` marker + upstream server 10.43.94.103:3000;
  `nginx -t` successful). The actual production traffic flip (switch+reload+smoke +
  ~24h monitoring) is DEFERRED BY SCOPE (AGENTS.md: v2 = staging only; production
  cutover intentionally deferred) — a future production decision, not a v2 item.
  Turnkey: scripts/cutover.sh + docs/cutover.md. NOTE: green-diff gate is COVERAGE-only,
  never value-equality (new parser intentionally diverges from legacy).

### Blockers/Concerns

- Phase 6 (CD) — ✓ ALL RESOLVED 2026-06-13 (live CI): 51820/udp egress from a real runner works (handshake completed), the explicit SA token Secret + namespace-scoped RBAC authenticate and cover `rollout status`, and TLS to `10.8.0.1:6443` succeeds (serving-cert SAN OK — no TLS error on apply/rollout). Original concerns kept for history:
- Phase 6 (CD): WireGuard handshake from the ephemeral runner must be gated before any `kubectl`; 51820/udp outbound from GitHub-hosted runners is assumed and must be validated early.
- Phase 6 (CD): k8s ≥1.24 SA has no auto-token Secret — the `kubernetes.io/service-account-token` Secret must be created explicitly; serving cert must carry `10.8.0.1` in its SANs.
- Phase 6 (CD): RBAC must be namespace-scoped yet still cover `rollout status`; verify with `auth can-i --list` and an SA-impersonated dry-run.
- Phase 8 (DRILL): the drill must run in an ephemeral scratch PostgreSQL with a guarded target DB name — never live `postgres-0` / `postgres-data`.
- Phase 10 (S3) — ✓ RESOLVED 2026-06-13: Timeweb lifecycle parity proven via a live put-then-get round-trip + observed x-amz-expiration. NEW finding: `delete-bucket-lifecycle` is a NO-OP (replace-only); rollback = PUT a new config.

## Deferred Items

Items now in scope for v2.0 (previously deferred at v1 close):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| CD | kubectl-native CD over WireGuard | In scope — Phase 6 | — |
| Edge | Host nginx/certificate/firewall automation | In scope — Phase 7 | v1 planning |
| Restore | Automated restore drill validation | In scope — Phase 8 | v1 planning |
| App | `web` runtime wiring | In scope — Phase 9 | v1 planning |
| Storage | S3 lifecycle and retention policy enforcement | In scope — Phase 10 | v1 planning |
| Production | Production traffic cutover | In scope — Phase 11 | v1 planning |
| S3 | Distinct replay/artifact retention windows (S3-04) | Deferred to v2.x | v2.0 scoping |
| CD | PR dry-run diff comment (CD-10) | Deferred to v2.x | v2.0 scoping |
| DRILL | Scheduled restore-drill CronJob + alerting (DRILL-05) | Deferred to v2.x | v2.0 scoping |
| CUT | Weighted / blue-green nginx cutover (CUT-05) | Deferred to v2.x | v2.0 scoping |
| Docs | Phase 6 doc-drift: drop `CD_SSH_*` + `scripts/deploy-staging.sh` refs from docs/staging.md, README.md, AGENTS.md; document the new WG_*/K8S_* secrets | Deferred to v2.x | v2.0 close (2026-06-13) |
| S3 | `apply-s3-lifecycle.sh` GET-before-PUT guard + probe-Job heuristic crash on a CLEAN bucket (aws-cli v2.32.7 `NoneType` bug on the empty-`<Message>` 404) — classify from the raw `<Code>`/HTTP status so a fresh-bucket first apply works | Deferred to v2.x | v2.0 close (2026-06-13) |

## Session Continuity

Last session: 2026-06-14T03:10:56.994Z
Stopped at: Completed 12-02-PLAN.md
Resume file: None

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
