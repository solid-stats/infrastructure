---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: tech
---

# Stack

## Runtime Purpose

This repository is an infrastructure repository for the Solid Stats staging
environment. It does not build application code. It pins Kubernetes manifests,
deployment scripts, operational runbooks, and a GitHub Actions workflow for the
`solid-stats-staging` namespace.

## Primary Technologies

- Kubernetes batch/apps/core APIs in `k8s/staging/*.yaml`.
- k3s on the staging VPS, targeted through remote `kubectl` in
  `scripts/deploy-staging.sh`.
- PostgreSQL 17 Alpine image in `k8s/staging/10-postgres.yaml`.
- RabbitMQ 4 management image in `k8s/staging/20-rabbitmq.yaml`.
- GHCR-hosted application images pinned in:
  - `k8s/staging/35-server-2-deployment.yaml`
  - `k8s/staging/40-replay-parser-2.yaml`
  - `k8s/staging/50-replays-fetcher.yaml`
- Timeweb S3-compatible object storage configured through manifests and
  secrets.

## Script Languages

- Bash:
  - `scripts/deploy-staging.sh`
  - `scripts/backup-postgres-now.sh`
- Python 3:
  - `scripts/render-staging-secrets.py`

## CI/CD

GitHub Actions is configured in `.github/workflows/deploy-staging.yml`.

The workflow has two jobs:

- `validate` checks that expected files and manifest directories exist.
- `deploy` installs the SSH private key, trusts the deploy host, then runs
  `scripts/deploy-staging.sh` with secrets from the `staging` environment.

## Storage

Persistent cluster storage uses Kubernetes PVCs:

- PostgreSQL PVC `postgres-data` requests `20Gi` in
  `k8s/staging/10-postgres.yaml`.
- RabbitMQ PVC `rabbitmq-data` requests `5Gi` in
  `k8s/staging/20-rabbitmq.yaml`.

Object storage uses Timeweb S3 endpoint `https://s3.twcstorage.ru`.

## Backup Tooling

The `postgres-backup` CronJob in `k8s/staging/60-postgres-backup.yaml` uses the
`postgres:17-alpine` image, installs `aws-cli` at runtime, creates a custom
format `pg_dump`, validates it with `pg_restore --list`, and uploads dump,
list, and manifest objects to S3.

## No Package Manager

There is no `package.json`, `pyproject.toml`, `go.mod`, or `Cargo.toml`.
Dependencies are runtime tools provided by GitHub-hosted runners, container
images, and Alpine packages installed inside the backup container.
