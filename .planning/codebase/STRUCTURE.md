---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: arch
---

# Structure

## Root Files

- `README.md` explains repository purpose, layout, deploy model, and manual
  backup entrypoint.
- `.gitignore` excludes local env files, logs, and temporary files.

## Documentation

- `docs/staging.md` documents scope, required GitHub secrets, deploy model, and
  the intentionally suspended `replays-fetcher` CronJob.
- `docs/backup-restore.md` documents PostgreSQL backup schedule, manual backup,
  backup validation, and restore drill.

## Kubernetes Manifests

All staging manifests live in `k8s/staging/` and are intended to be applied in
filename order.

- `00-namespace.yaml` creates `solid-stats-staging`.
- `10-postgres.yaml` defines PostgreSQL Service and StatefulSet.
- `20-rabbitmq.yaml` defines RabbitMQ Service and StatefulSet.
- `30-server-2.yaml` defines `server-2` ConfigMap and Service.
- `35-server-2-deployment.yaml` defines `server-2` Deployment.
- `40-replay-parser-2.yaml` defines `replay-parser-2` Deployment.
- `50-replays-fetcher.yaml` defines `replays-fetcher` CronJob.
- `60-postgres-backup.yaml` defines `postgres-backup` CronJob.

## Scripts

- `scripts/render-staging-secrets.py` renders all staging secrets from
  environment variables to Kubernetes YAML using `stringData`.
- `scripts/deploy-staging.sh` applies secrets and manifests over SSH and waits
  for rollouts.
- `scripts/backup-postgres-now.sh` creates a one-off Job from the deployed
  backup CronJob and prints logs.

## CI/CD

- `.github/workflows/deploy-staging.yml` validates the repository shape and
  deploys to k3s from GitHub Actions.

## Naming Conventions

Resource files use numeric prefixes to make apply order visible.

Kubernetes resources use `app.kubernetes.io/name` and
`app.kubernetes.io/part-of` labels consistently.

Runtime manifests pin immutable image tags for apps rather than relying on
`latest`.

## Missing Structure

There is no `Makefile`, `justfile`, schema validation tool, or kustomize/Helm
layer yet. The repository currently uses plain manifests and shell scripts.
