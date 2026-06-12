---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Production-Ready Infra & kubectl-native CD
status: executing
stopped_at: "Phase 07 PLANNED & plan-checked (PASS); stopped before execute per user request"
last_updated: "2026-06-12T08:22:21.903Z"
last_activity: 2026-06-12 -- Phase 07 planned (4 plans, 3 waves), ready to execute
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 4
  completed_plans: 4
  percent: 17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** Phase 07 — Edge Automation

## Current Position

Phase: 07 (edge-automation) — PLANNED ✓ (research + validation + 4 plans, plan-checker PASS)
Status: Ready to execute Phase 07 — stopped before execute per user request
Plans: 0/4 executed (07-01, 07-02 [wave 1] → 07-03 [wave 2] → 07-04 [wave 3])
Prev: Phase 06 COMPLETE ✓ (verification human_needed — live CI deploy deferred)
Last activity: 2026-06-12 -- Phase 07 planned, ready to execute

Progress: [█░░░░░░░░░] 17% (1/6 phases complete; Phase 07 planned)

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

### Pending Todos

- Phase 6 (human_needed, DEFERRED): live WireGuard handshake from a real GitHub
  runner + SA-token auth + actual `kubectl apply`/`rollout` can only be confirmed
  by a real CI run on `master` — this environment is VPN-isolated from the cluster.
  Confirm on the first real master deploy. See `06-VERIFICATION.md`.

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

Last session: 2026-06-12T07:47:23.962Z
Stopped at: Completed 06-02: SA token and WireGuard key rotation runbook (CD-09)
Resume file: None
