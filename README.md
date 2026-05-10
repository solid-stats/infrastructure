# Solid Stats Infrastructure

This repository is the source of truth for the Solid Stats staging runtime
infrastructure.

It owns shared Kubernetes resources and operational runbooks:

- `solid-stats-staging` namespace
- PostgreSQL and RabbitMQ StatefulSets
- `server-2`, `replay-parser-2`, and `replays-fetcher` runtime manifests
- PostgreSQL backup CronJob to Timeweb S3
- staging deployment, backup, and restore runbooks

Application repositories own application source code and container images. This
repository owns how those images are wired together in staging.

## Layout

- `k8s/staging/` - Kubernetes manifests applied to the staging k3s cluster.
- `scripts/render-staging-secrets.py` - renders staging Kubernetes secrets from
  CI environment variables.
- `scripts/deploy-staging.sh` - applies secrets and manifests to the server over
  SSH.
- `scripts/backup-postgres-now.sh` - creates and waits for a one-off backup job
  from the deployed backup CronJob.
- `docs/staging.md` - staging operations and deploy model.
- `docs/backup-restore.md` - PostgreSQL backup and restore runbook.

## Deploy

The GitHub Actions workflow deploys on pushes to `master` or `main`, and can be
run manually with optional image overrides.

Required GitHub environment secrets for `staging` are documented in
`docs/staging.md`.

## Manual Backup

After the staging manifests are applied:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

The job writes a PostgreSQL custom-format dump, restore list, and JSON manifest
under the configured S3 bucket prefix `backups/postgres/`.
