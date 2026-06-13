# Solid Stats Infrastructure

## What This Is

This repository is the source of truth for Solid Stats infrastructure, starting
with the staging k3s environment. It owns shared runtime wiring, Kubernetes
manifests, operational scripts, backup and restore runbooks, and the path toward
manual full-run and diff verification before any production traffic switch.

Application repositories still own application code and image builds. This
project owns how those images are composed into a reliable Solid Stats runtime.

## Core Value

Staging must be reproducible, backed up, and safe to run end-to-end before it is
used to produce or compare new statistics.

## Shipped Milestone: v2.0 — Production-Ready Infra & kubectl-native CD (✅ 2026-06-13)

**Goal:** Deploy staging with direct `kubectl` from CI over WireGuard (no SSH),
make git the source of truth for what ships, and close the remaining
production-readiness gaps deferred from v1 — edge automation, S3 lifecycle,
automated restore drill, the `web` runtime, and a controlled production cutover.

**Target features:**
- kubectl-native CD: WireGuard in the CI job → `kubectl` against the closed k3s
  API, scoped ServiceAccount + namespace RBAC, SSH/scp removed.
- Production cutover: controlled switch of traffic from legacy to the new runtime.
- Edge automation: host nginx, certificate renewal, and firewall management.
- S3 lifecycle: retention/lifecycle policies across backup, replay, and artifact
  prefixes.
- Automated restore drill: scripted PostgreSQL restore validation.
- `web` runtime wiring: Kubernetes manifests for the future `web` application.

## Current Milestone: v3.0 — Staging Observability Stack

**Goal:** Stand up the full self-hosted observability stack on the staging k3s
cluster — metrics, logs, and Sentry-compatible error tracking — fitted to the
RAM-bound single node. Staging only; the production mirror (decision D2) is a
later milestone.

**Target features:**
- Metrics: Prometheus + Grafana + kube-state-metrics + node-exporter.
- Logs: Loki + Grafana Alloy, ~7-day retention.
- Error tracking: GlitchTip with its own PostgreSQL + Redis (errors only).
- Workload exporters: postgres-exporter + rabbitmq-exporter, first dashboards.
- Public access via host nginx vhosts + certbot (`grafana.`/`errors.`
  subdomains), separate from the runtime deploy path.
- App-side Sentry SDK integration prepared as separate app-repo PRs.

**Source:** `plans/infrastructure/briefs/observability-plan.md`; RELEASE-PLAN
Phase 0 Track 2 (decision W5).

## Requirements

### Validated

- ✓ Codebase map exists for the initial infrastructure repository — bootstrap
  mapping commit
- ✓ Initial staging manifests exist for namespace, PostgreSQL, RabbitMQ,
  `server-2`, `replay-parser-2`, `replays-fetcher`, and PostgreSQL backup —
  current repository state
- ✓ Initial operational runbooks exist for staging and backup/restore — current
  repository state
- ✓ kubectl-native CD over WireGuard (scoped ServiceAccount, SSH/scp removed) — v2.0 (live-verified end-to-end on real runners)
- ✓ Edge automation: host nginx/certbot/ufw via idempotent adopt-reconcile bootstrap + reversible teardown — v2.0 (live-verified)
- ✓ Automated PostgreSQL restore drill in an ephemeral scratch DB — v2.0 (live-verified, PASS on cluster)
- ✓ `web` runtime slot wired into runtime + CD path — v2.0
- ✓ S3 lifecycle: 30-day retention on `backups/postgres/` + abort-multipart — v2.0 (applied live; Timeweb lifecycle API empirically proven)
- ✓ Production cutover mechanism: 4-gate reversible nginx-upstream switch — v2.0 (mechanism live-verified; live prod flip deferred by scope)

### Active

<!-- v3.0 — Staging Observability Stack. Detailed REQ-IDs live in REQUIREMENTS.md. -->

- [ ] Resource preflight + host swap so the trimmed stack fits the 8 GB single node.
- [ ] Metrics stack (Prometheus, Grafana, kube-state-metrics, node-exporter) on staging.
- [ ] Log stack (Loki + Grafana Alloy) collecting cluster logs into Grafana.
- [ ] GlitchTip error tracking with its own PostgreSQL + Redis, closed registration.
- [ ] Postgres + RabbitMQ exporters wired into Prometheus plus first dashboards.
- [ ] Public observability domains via host nginx + certbot, separate from runtime CD.
- [ ] NetworkPolicy isolation for the observability namespaces (after CNI proof).
- [ ] Errors-only Sentry SDK integration prepared for server-2/replay-parser-2/replays-fetcher.

### Previously Shipped (v1.0 / v2.0)

_Re-scoped out of Active at the v3.0 milestone start; the delivered items are in
the Validated list above and the Shipped Milestone sections._

### Out of Scope

- Production traffic cutover in v1 — staging must complete backup, full-run, and
  diff verification first.
- Building application images — app repositories own source code and image
  publishing.
- Rewriting application deploy workflows immediately — deployment ownership will
  move gradually after infrastructure deploy is proven.
- Running `replays-fetcher` on a schedule before backup verification — the first
  ingest must be controlled and observable.
- Managing host nginx/certificate automation in the first staging slice — the
  current public edge remains documented operational state until a later phase.

## Context

Solid Stats currently has three deployed backend components:

- `server-2`
- `replay-parser-2`
- `replays-fetcher`

The `web` app will be added later. Current staging runs on a Timeweb VPS with
k3s, PostgreSQL, RabbitMQ, GHCR images, and Timeweb S3-compatible storage. The
public staging API is available through host-level nginx to `server-2`; there
are no Kubernetes ingress or cert-manager resources in scope right now.

The old plan remains the guide: inventory server state, stand up k3s/runtime,
prepare manifests, add CI/CD, configure S3 prefixes, configure nightly
PostgreSQL backup to S3, provide restore runbook, create manual full-run
commands, build diff reporting, and only then decide how to switch production
traffic.

The current repository already contains an initial infrastructure skeleton, but
it has not yet been fully validated through infra CD and a live manual backup.
The codebase map identifies several concerns: app CD overlap, weak manifest
validation, a possible GHCR pull secret rendering bug, runtime `apk add` in the
backup job, and no restore drill yet.

The project has a local `kubernetes-specialist` skill. Kubernetes planning and
execution should apply its baseline: declarative manifests, explicit
ServiceAccounts, resource requests and limits, probes, least-privilege RBAC,
NetworkPolicies where supported, secrets for sensitive data, and documented
exceptions for any workload that must run outside those defaults.

## Constraints

- **Environment**: v1 targets `solid-stats-staging` only — production cutover is
  intentionally deferred.
- **Cluster**: k3s is already running on the staging VPS — this project deploys
  resources into it but does not reinstall the server in v1.
- **Storage**: Timeweb S3-compatible storage is the object storage provider —
  backup, raw replay, artifact, and future report prefixes must coexist safely.
- **Database**: PostgreSQL in k3s is the durable metadata source — full-run work
  must not proceed without a current backup point.
- **Deploy Ownership**: app repositories still have legacy deploy workflows —
  migration to infra-owned deploy must be gradual to avoid breaking active
  staging.
- **Safety**: `replays-fetcher` stays suspended until manual backup and
  restore-list validation pass.
- **Secrets**: secrets come from GitHub environment secrets and live Kubernetes
  Secrets — no secret values belong in git or planning docs.
- **Validation**: completion claims require fresh evidence from scripts,
  Kubernetes dry-runs, live rollout state, backup logs, or S3 object checks.
- **Kubernetes Safety**: workload manifests must avoid default ServiceAccounts,
  add pod/container security context where images allow it, keep resource
  requests/limits, and define network isolation or a documented exception.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| v1/v2 are staging-first; production cutover deferred | Staging must be reproducible/backed-up/recoverable before any prod traffic decision | ✓ Good — held through v2.0; cutover mechanism built but flip deferred by scope |
| Move app deploy ownership gradually | Existing app CD works and should not be broken before infra CD is proven | ✓ Good — v2.0 shipped kubectl-native infra CD, app repos still build images |
| Backup gate is manual backup plus `pg_restore --list` before full-run | Gives a concrete recovery point without blocking on a full restore drill | ✓ Good — extended in v2.0 by an automated restore drill (live PASS) |
| `replays-fetcher` remains suspended initially | Prevents uncontrolled S3/database writes before backup confidence exists | ✓ Good — still suspended |
| Infra repo owns shared runtime wiring | Backups, namespace, storage, and cross-app wiring do not belong to one app repo | ✓ Good |
| `kubernetes-specialist` is the infra planning baseline | Kubernetes work needs security/networking/workload/storage guardrails | ✓ Good |
| kubectl-native CD over WireGuard (not SSH/scp) | A scoped SA + closed k3s API is safer + git-as-source-of-truth than SSH deploy | ✓ Good (v2.0) — live-verified; surfaced 6 latent script bugs only a real run could catch |
| Cutover lever IS the nginx upstream; edge + restore drill land before cutover | Production is never flipped without a proven-reversible lever + recoverability | ✓ Good (v2.0) — mechanism live-verified, reversible; flip deferred by scope |
| Apply S3 retention to live backups after empirical Timeweb proof | Timeweb lifecycle parity was MEDIUM-confidence — prove GET/PUT/expiry before relying on it | ✓ Good (v2.0) — proven + applied; found `delete-bucket-lifecycle` is a no-op (replace-only) |
| Staging observability runs trimmed + host swap, not on a bigger VPS | Node is RAM-bound (8 GB, no swap, ~1.7 GB free); a resize is costly and RAM frees up once legacy is decommissioned | — Pending (v3.0) |
| Observability deploy path stays separate from the runtime CD path | Runtime deploy must not depend on the obs deploy succeeding (brief validation gate) | — Pending (v3.0) |
| Obs services exposed via host nginx + certbot, not an in-cluster ingress | k3s has no ingress controller (Traefik disabled); reuse the v2.0 Phase 07 edge pattern | — Pending (v3.0) |

## Evolution

## Current State

v2.0 is shipped (2026-06-13). Staging deploys via kubectl-native CD over a
WireGuard tunnel (SSH/scp removed, git as source of truth), with edge automation,
an automated restore drill, the `web` runtime slot, applied 30-day S3 retention,
and a live-verified reversible production-cutover mechanism. CD and the
edge/restore/retention paths were all exercised live on the staging cluster/VPS
(6 latent CD bugs surfaced and fixed only because the path was finally run for
real). The one production-readiness item left by design is the actual production
traffic flip — deferred by scope (AGENTS.md). v2.x follow-ups are tracked in
STATE.md "Deferred Items".

## Next Milestone Goals

- Production traffic cutover (when production enters scope): run the green-diff
  full-run, review the diff, then the gated reversible flip via scripts/cutover.sh.
- Clear v2.x follow-ups: Phase 6 doc-drift cleanup; the clean-bucket aws-cli guard
  fix; deferred S3-04 / CD-10 / DRILL-05 / CUT-05 enhancements.
- Drive old-vs-new statistics comparison off controlled full-run evidence.

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. "What This Is" still accurate? Update if drifted.

**After each milestone**:
1. Full review of all sections.
2. Core Value check: still the right priority?
3. Audit Out of Scope: reasons still valid?
4. Update Context with current state.

---
*Last updated: 2026-06-13 — milestone v3.0 (Staging Observability Stack) started*
