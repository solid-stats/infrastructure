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

## Requirements

### Validated

- ✓ Codebase map exists for the initial infrastructure repository — bootstrap
  mapping commit
- ✓ Initial staging manifests exist for namespace, PostgreSQL, RabbitMQ,
  `server-2`, `replay-parser-2`, `replays-fetcher`, and PostgreSQL backup —
  current repository state
- ✓ Initial operational runbooks exist for staging and backup/restore — current
  repository state

### Active

- [ ] Make `infrastructure` the deploy source of truth for staging shared
  resources and app runtime wiring.
- [ ] Keep v1 focused on staging: deploy, backup, restore-list validation,
  controlled full-run, and old-vs-new diff readiness.
- [ ] Configure PostgreSQL backups to Timeweb S3 under a stable
  `backups/postgres/` prefix.
- [ ] Provide a manual backup command that creates a backup Job, uploads the
  dump/list/manifest to S3, and verifies `pg_restore --list`.
- [ ] Preserve `replays-fetcher` as suspended until backup verification passes
  and a controlled manual full-run is explicitly started.
- [ ] Gradually move deployment ownership out of app repositories so app repos
  build and push images while this repo deploys staging wiring.
- [ ] Add enough validation to prevent broken manifests, broken scripts, or
  unsafe secret rendering from reaching staging.
- [ ] Document and execute a restore drill path after the backup-list gate.
- [ ] Prepare manual full-run and diff pipeline phases after backup confidence
  exists.

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
| v1 is staging-first | Staging must be stable before full ingest or production traffic decisions | — Pending |
| Move app deploy ownership gradually | Existing app CD works and should not be broken before infra CD is proven | — Pending |
| Backup gate is manual backup plus `pg_restore --list` before full-run | Gives a concrete recovery point without blocking on a full restore drill | — Pending |
| `replays-fetcher` remains suspended initially | Prevents uncontrolled S3/database writes before backup confidence exists | — Pending |
| Infra repo owns shared runtime wiring | Backups, namespace, storage, and cross-app wiring do not belong to one app repo | — Pending |
| `kubernetes-specialist` is the infra planning baseline | Kubernetes work needs security, networking, workload, and storage guardrails from the local skill | — Pending |

## Evolution

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
*Last updated: 2026-05-10 after initialization*
