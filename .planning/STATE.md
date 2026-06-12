---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Production-Ready Infra & kubectl-native CD
status: executing
stopped_at: "Completed 06-02: SA token and WireGuard key rotation runbook (CD-09)"
last_updated: "2026-06-12T07:40:31.763Z"
last_activity: 2026-06-12 -- Phase 6 execution started
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 4
  completed_plans: 2
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11)

**Core value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.
**Current focus:** Phase 6 — kubectl-native CD

## Current Position

Phase: 6 (kubectl-native CD) — EXECUTING
Plan: 3 of 4
Status: Ready to execute
Last activity: 2026-06-12 -- Phase 6 execution started

Progress: [░░░░░░░░░░] 0%

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

None yet.

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

Last session: 2026-06-12T07:40:31.760Z
Stopped at: Completed 06-02: SA token and WireGuard key rotation runbook (CD-09)
Resume file: None
