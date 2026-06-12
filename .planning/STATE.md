---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Production-Ready Infra & kubectl-native CD
status: executing
stopped_at: "Phase 07 executed + reviewed + fixed; verification human_needed (live-VPS checks in 07-UAT.md). Autonomous run STOPPED by user to validate Phase 07 live before continuing to Phase 08."
last_updated: "2026-06-13T00:00:00Z"
last_activity: 2026-06-13 -- Phase 07 plans done, code review fixed (2 crit + 7 warn), verification human_needed, run paused for live validation
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 8
  completed_plans: 8
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** Phase 07 — edge-automation

## Current Position

Phase: 07 (edge-automation) — PLANS DONE, verification human_needed ⏸
Plan: 4 of 4
Status: All 4 plans executed; code review (2 crit + 7 warn) fixed; verification human_needed — 6 live-VPS checks pending in 07-UAT.md. Run `/gsd-verify-work 7` from the VPS to close. Autonomous run STOPPED by user to validate live first.
Plans: 4/4 complete (07-01, 07-02 [wave 1] → 07-03 [wave 2] → 07-04 [wave 3])
Note: Live SSH inspection showed the staging edge ALREADY EXISTS (nginx 1.24 +
  certbot 2.9 + stock certbot.timer). Plans rewritten to ADOPT it into the repo
  (only the stats-staging vhost; relay/auth/default operator-owned, one holds a
  secret) + add ufw 6443-on-wg0 + nginx -t-gated deploy-hook + OnFailure surfacing

  + backup-before-overwrite reversibility. Real upstream = server-2 ClusterIP
  10.43.94.103:3000. http2 preserved.
Prev: Phase 06 COMPLETE ✓ (verification human_needed — live CI deploy deferred)
Last activity: 2026-06-13 -- Phase 07 complete (all 4 plans executed)

Progress: [██░░░░░░░░] 33% (2/6 phases complete; Phase 07 complete)

## Performance Metrics

**Velocity:**

- Total plans completed: 0 (this milestone)
- Average duration: N/A
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

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

### Pending Todos

- Phase 6 (human_needed, DEFERRED): live WireGuard handshake from a real GitHub
  runner + SA-token auth + actual `kubectl apply`/`rollout` can only be confirmed
  by a real CI run on `master` — this environment is VPN-isolated from the cluster.
  Confirm on the first real master deploy. See `06-VERIFICATION.md`.
- Phase 7 (human_needed, PENDING — user chose to validate before continuing): 6
  live-VPS checks in `07-UAT.md` (nginx -t, `certbot renew --dry-run`, OnFailure
  drop-in, ufw 6443-on-wg0, live `curl` TLS+upstream, teardown reversibility
  round-trip). Bootstrap is operator-run; nothing was applied to the VPS during
  execution. Run `/gsd-verify-work 7` from the VPS, then resume with
  `/gsd:autonomous --from 8`. See `07-VERIFICATION.md`.

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

Last session: 2026-06-13T00:00:00Z
Stopped at: Completed 07-04: edge-bootstrap.md operator runbook (EDGE-01..05)
Resume file: None
