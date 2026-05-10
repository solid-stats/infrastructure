<!-- GSD:project-start source:PROJECT.md -->
## Project

**Solid Stats Infrastructure**

This repository is the source of truth for Solid Stats infrastructure, starting
with the staging k3s environment. It owns shared runtime wiring, Kubernetes
manifests, operational scripts, backup and restore runbooks, and the path toward
manual full-run and diff verification before any production traffic switch.

Application repositories still own application code and image builds. This
project owns how those images are composed into a reliable Solid Stats runtime.

**Core Value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is
used to produce or compare new statistics.

### Constraints

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
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Runtime Purpose
## Primary Technologies
- Kubernetes batch/apps/core APIs in `k8s/staging/*.yaml`.
- k3s on the staging VPS, targeted through remote `kubectl` in
- PostgreSQL 17 Alpine image in `k8s/staging/10-postgres.yaml`.
- RabbitMQ 4 management image in `k8s/staging/20-rabbitmq.yaml`.
- GHCR-hosted application images pinned in:
- Timeweb S3-compatible object storage configured through manifests and
## Script Languages
- Bash:
- Python 3:
## CI/CD
- `validate` checks that expected files and manifest directories exist.
- `deploy` installs the SSH private key, trusts the deploy host, then runs
## Storage
- PostgreSQL PVC `postgres-data` requests `20Gi` in
- RabbitMQ PVC `rabbitmq-data` requests `5Gi` in
## Backup Tooling
## No Package Manager
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Manifest Style
- one environment per directory
- numeric filename prefixes for apply ordering
- explicit namespace on namespaced resources
- standard Kubernetes app labels
- image tags pinned to explicit SHAs for app deployments
- `imagePullPolicy: IfNotPresent` for pinned images
## Secret Handling
## Script Style
- `#!/usr/bin/env bash`
- `set -euo pipefail`
- explicit required env var checks through shell parameter expansion
- remote `kubectl` execution over SSH
- standard library only
- explicit `required()` helper for mandatory environment variables
- exits with code `64` for missing configuration
## Operational Safety
## Documentation Style
## Error Handling
## Commit State
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Role
## Runtime Topology
- PostgreSQL StatefulSet and Service from `k8s/staging/10-postgres.yaml`.
- RabbitMQ StatefulSet and Service from `k8s/staging/20-rabbitmq.yaml`.
- `server-2` ConfigMap, Service, and Deployment from
- `replay-parser-2` Deployment from `k8s/staging/40-replay-parser-2.yaml`.
- `replays-fetcher` CronJob from `k8s/staging/50-replays-fetcher.yaml`.
- `postgres-backup` CronJob from `k8s/staging/60-postgres-backup.yaml`.
## Data Flow
## Deployment Flow
## Ownership Boundaries
- namespace
- persistent services
- runtime manifests
- backup scheduling
- deployment runbooks
- staging operational docs
## Current Transitional Boundary
## Entry Points
- Human docs: `README.md`, `docs/staging.md`, `docs/backup-restore.md`.
- CI/CD: `.github/workflows/deploy-staging.yml`.
- Deploy script: `scripts/deploy-staging.sh`.
- Manual backup script: `scripts/backup-postgres-now.sh`.
- Runtime manifests: `k8s/staging/*.yaml`.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| kubernetes-specialist | Use when deploying or managing Kubernetes workloads. Invoke to create deployment manifests, configure pod security policies, set up service accounts, define network isolation rules, debug pod crashes, analyze resource limits, inspect container logs, or right-size workloads. Use for Helm charts, RBAC policies, NetworkPolicies, storage configuration, performance optimization, GitOps pipelines, and multi-cluster management. | `.agents/skills/kubernetes-specialist/SKILL.md` |
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
