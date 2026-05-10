---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: arch
---

# Architecture

## System Role

The repository is the staging infrastructure control plane for Solid Stats. It
turns already-built application images into a working staging environment and
owns shared operational resources that do not belong to one application repo.

## Runtime Topology

The Kubernetes namespace `solid-stats-staging` contains:

- PostgreSQL StatefulSet and Service from `k8s/staging/10-postgres.yaml`.
- RabbitMQ StatefulSet and Service from `k8s/staging/20-rabbitmq.yaml`.
- `server-2` ConfigMap, Service, and Deployment from
  `k8s/staging/30-server-2.yaml` and
  `k8s/staging/35-server-2-deployment.yaml`.
- `replay-parser-2` Deployment from `k8s/staging/40-replay-parser-2.yaml`.
- `replays-fetcher` CronJob from `k8s/staging/50-replays-fetcher.yaml`.
- `postgres-backup` CronJob from `k8s/staging/60-postgres-backup.yaml`.

## Data Flow

The ingest and parse data flow is:

1. `replays-fetcher` discovers replay files, writes raw objects to S3, and
   writes ingest staging rows to PostgreSQL.
2. `server-2` promotes ingest rows, publishes parser jobs to RabbitMQ, receives
   parser result messages, and persists canonical statistics to PostgreSQL.
3. `replay-parser-2` consumes `server2.parse.requested`, reads raw replay
   objects from S3, writes artifacts to S3, and publishes completed or failed
   result messages.
4. `postgres-backup` dumps PostgreSQL and uploads backup artifacts to S3.

## Deployment Flow

The intended deployment flow is:

1. Application repositories build and push images to GHCR.
2. This repository pins image tags in `k8s/staging/*.yaml`.
3. `.github/workflows/deploy-staging.yml` runs
   `scripts/deploy-staging.sh`.
4. The script renders Kubernetes secrets with
   `scripts/render-staging-secrets.py`.
5. The script applies secrets and manifests to the remote k3s cluster.
6. The script waits for StatefulSet and Deployment rollouts.

## Ownership Boundaries

Application repos own source code, image builds, migrations, parser contracts,
and app-level behavior.

This repo owns shared deployment wiring:

- namespace
- persistent services
- runtime manifests
- backup scheduling
- deployment runbooks
- staging operational docs

## Current Transitional Boundary

App repositories still contain legacy deployment workflows and app manifests.
`docs/staging.md` records the target steady state: app repos should publish
images, while this repo should be the source of truth for staging wiring.

## Entry Points

- Human docs: `README.md`, `docs/staging.md`, `docs/backup-restore.md`.
- CI/CD: `.github/workflows/deploy-staging.yml`.
- Deploy script: `scripts/deploy-staging.sh`.
- Manual backup script: `scripts/backup-postgres-now.sh`.
- Runtime manifests: `k8s/staging/*.yaml`.
