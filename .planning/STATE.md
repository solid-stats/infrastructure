---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Production-Ready Infra & kubectl-native CD
status: executing
stopped_at: "All 6 phases EXECUTED. Phases 06,07,08,09 complete — 06,07,08 now LIVE-VERIFIED (06 CD proven end-to-end on staging 2026-06-13: PR dry-run + master deploy green from real runners; 6 latent bugs fixed). Phases 10 & 11 human_needed — consequential live steps (apply prod S3 retention; flip prod traffic) operator-gated."
last_updated: "2026-06-13T04:15:00Z"
last_activity: 2026-06-13 -- Phase 06 (kubectl-native CD) LIVE-VERIFIED on staging cluster; CI WireGuard peer provisioned + persisted; 6 latent CD bugs fixed and merged to master.
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 21
  completed_plans: 19
  percent: 81
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** v2.0 milestone — all phases built; operator validations pending for 10 & 11

## Current Position

Milestone v2.0: ALL 6 PHASES EXECUTED. Status by phase:
- Phase 06 (kubectl-native CD): COMPLETE ✓ + LIVE-VERIFIED on staging (2026-06-13) — PR #1 dry-run + master-push deploy green from real GitHub runners (WG handshake, ci-deployer SA auth, server-side dry-run, rollout of 5 workloads); 6 latent script/workflow bugs found & fixed. See 06-VERIFICATION
- Phase 07 (Edge Automation): COMPLETE ✓ + LIVE-VERIFIED on staging VPS (all 6 UAT items; 2 live bugs fixed)
- Phase 08 (Automated Restore Drill): COMPLETE ✓ + LIVE-VERIFIED (drill PASS on cluster; postgres-0 untouched; 26 tables/303267 rows restored to scratch)
- Phase 09 (web Runtime Wiring): COMPLETE ✓ (0-replica stub; server-side dry-run accepted by cluster; CD applies the slot)
- Phase 10 (S3 Lifecycle & Retention): EXECUTED, human_needed — S3-01/02 delivered + offline-verified (30d retention floor enforced in CI); S3-03 empirical proof + applying retention to prod backups is OPERATOR-GATED (consequential). See 10-UAT.md.
- Phase 11 (Production Cutover): EXECUTED, human_needed — CUT-01..04 mechanism delivered + offline-proven (4 gates, anchored single-line switch, SELF_TEST'd rollback, smoke+auto-rollback, DRY_RUN). The live production traffic flip is OPERATOR-GATED. See 11-UAT.md.

Quality: every phase passed gsd-plan-checker (revisions applied), gsd-code-review (all critical+warning fixed), and gsd-verifier. `python3 scripts/validate-staging.py` exits 0 (10 checks). Tree clean. Commits on master (NOT pushed — awaiting operator).

Progress: [████████░░] 81% (4/6 phases complete; 10 & 11 executed, operator-gated)

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

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

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

- Phase 10 (human_needed, OPERATOR-GATED): S3-01/S3-02 delivered + offline-verified
  (validate-staging.py enforces the 30-day retention floor). S3-03 empirical proof
  (Timeweb lifecycle API support + x-amz-expiration on an isolated test prefix) AND
  applying the retention policy to the prod `backups/postgres/` prefix are operator-run
  — applying retention DELETES old backups (consequential), and shared-S3/cluster
  writes are not done unattended. Turnkey: probe Job + scripts/apply-s3-lifecycle.sh.
  See 10-UAT.md and docs/s3-lifecycle.md.

- Phase 11 (human_needed, OPERATOR-GATED): the production cutover MECHANISM is
  delivered + offline-proven (4 gates, anchored single-line nginx-upstream switch,
  SELF_TEST'd reversible rollback, smoke check + auto-rollback, DRY_RUN that still
  enforces gates). The actual production traffic flip is operator-run (consequential;
  production target outside this staging env). Turnkey: scripts/cutover.sh + docs/cutover.md.
  See 11-UAT.md. NOTE: green-diff gate is COVERAGE-only, never value-equality (new
  parser intentionally diverges from legacy).

### Blockers/Concerns

- Phase 6 (CD) — ✓ ALL RESOLVED 2026-06-13 (live CI): 51820/udp egress from a real runner works (handshake completed), the explicit SA token Secret + namespace-scoped RBAC authenticate and cover `rollout status`, and TLS to `10.8.0.1:6443` succeeds (serving-cert SAN OK — no TLS error on apply/rollout). Original concerns kept for history:
- Phase 6 (CD): WireGuard handshake from the ephemeral runner must be gated before any `kubectl`; 51820/udp outbound from GitHub-hosted runners is assumed and must be validated early.
- Phase 6 (CD): k8s ≥1.24 SA has no auto-token Secret — the `kubernetes.io/service-account-token` Secret must be created explicitly; serving cert must carry `10.8.0.1` in its SANs.
- Phase 6 (CD): RBAC must be namespace-scoped yet still cover `rollout status`; verify with `auth can-i --list` and an SA-impersonated dry-run.
- Phase 8 (DRILL): the drill must run in an ephemeral scratch PostgreSQL with a guarded target DB name — never live `postgres-0` / `postgres-data`.
- Phase 10 (S3): Timeweb S3 lifecycle parity is MEDIUM confidence — prove with a put-then-get round-trip and an observed expiry before trusting retention.

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

## Session Continuity

Last session: 2026-06-12T20:44:06.542Z
Stopped at: Completed 10-03-PLAN.md (docs tasks)
Resume file: None
