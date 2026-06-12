---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Production-Ready Infra & kubectl-native CD
status: verifying
stopped_at: Completed 10-03-PLAN.md (docs tasks)
last_updated: "2026-06-12T20:04:26.932Z"
last_activity: 2026-06-13 -- Phase 10 Plan 02 complete
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 18
  completed_plans: 15
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** Phase 10 — s3-lifecycle-retention

## Current Position

Phase: 10 (s3-lifecycle-retention) — EXECUTING
Plan: 3 of 3
Status: Phase complete — ready for verification
Plans: Phase 08 = 3/3 complete (08-01, 08-02 [wave 1] → 08-03 [wave 2])
Note: Live SSH inspection showed the staging edge ALREADY EXISTS (nginx 1.24 +
  certbot 2.9 + stock certbot.timer). Plans rewritten to ADOPT it into the repo
  (only the stats-staging vhost; relay/auth/default operator-owned, one holds a
  secret) + add ufw 6443-on-wg0 + nginx -t-gated deploy-hook + OnFailure surfacing

  + backup-before-overwrite reversibility. Real upstream = server-2 ClusterIP
  10.43.94.103:3000. http2 preserved.
Prev: Phase 06 COMPLETE ✓ (verification human_needed — live CI deploy deferred)
Last activity: 2026-06-13 -- Phase 10 Plan 02 complete

Progress: [███░░░░░░░] 36% (2/6 phases complete; Phase 07, 09 complete)

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

### Pending Todos

- Phase 6 (human_needed, DEFERRED): live WireGuard handshake from a real GitHub
  runner + SA-token auth + actual `kubectl apply`/`rollout` can only be confirmed
  by a real CI run on `master` — this environment is VPN-isolated from the cluster.
  Confirm on the first real master deploy. See `06-VERIFICATION.md`.

- Phase 7 (RESOLVED 2026-06-13): all 6 live-VPS UAT checks PASSED on
  root@89.223.124.200 (nginx -t, scoped certbot --dry-run, OnFailure drop-in, ufw
  6443-on-wg0, live curl TLS+HSTS+upstream, teardown→re-bootstrap reversibility).
  Edge adopted into repo-managed state. Found+fixed 2 live-only bugs: vhost drift
  (03521f5), ufw 6443/tcp→proto tcp (cfa2485). NOTE: unscoped `certbot renew
  --dry-run` hangs on operator-owned auth.solid-stats.ru cert (relay/auth vhost,
  outside Phase 7 scope) — Phase 7 cert renews cleanly when scoped by --cert-name.

### Blockers/Concerns

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

Last session: 2026-06-12T20:04:26.929Z
Stopped at: Completed 10-03-PLAN.md (docs tasks)
Resume file: None
