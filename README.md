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
- `scripts/wg-tunnel-up.sh` - brings up the CI WireGuard tunnel to the k3s API
  and gates on a successful handshake before any `kubectl`.
- `scripts/kubeconfig-setup.sh` - builds a kubeconfig from the `ci-deployer`
  ServiceAccount token and k3s CA for in-CI `kubectl`.
- `scripts/backup-postgres-now.sh` - creates and waits for a one-off backup job
  from the deployed backup CronJob.
- `docs/staging.md` - staging operations and deploy model.
- `docs/backup-restore.md` - PostgreSQL backup and restore runbook.
- `docs/diff-readiness.md` - old-vs-new statistics diff contract and cutover
  block.

Forward-looking planning docs live in the central plans repo. The staging
observability architecture/rollout plan is at
`plans/infrastructure/briefs/observability-plan.md`.

## Deploy

The GitHub Actions workflow deploys on pushes to `master`, and can be run
manually with `workflow_dispatch`.

Required GitHub environment secrets for `staging` are documented in
`docs/staging.md`.

See the Staging Handoff Matrix in `docs/staging.md` for the boundary between
application repositories that build images and this repository that deploys
staging runtime wiring.

Validate the staging manifests, scripts, and rendered Secret structure before
deploy:

```bash
python3 scripts/validate-staging.py
```

Deploy runs in CI on merge to `master`: the workflow opens a WireGuard tunnel to
the closed k3s API, builds a kubeconfig from the `ci-deployer` ServiceAccount
token, and applies `k8s/staging/` (excluding the operator-managed
`01-ci-rbac.yaml`). It then waits for `statefulset/postgres`,
`statefulset/rabbitmq`, `deployment/server-2`, and `deployment/replay-parser-2`,
and lists the `postgres`, `rabbitmq`, and `server-2` Services plus the
`replays-fetcher` and `postgres-backup` CronJobs.

Phase 1 owns the namespace, PostgreSQL, RabbitMQ, `server-2`,
`replay-parser-2`, suspended `replays-fetcher`, and `postgres-backup`.
Production cutover, host edge automation, application source/image builds,
immediate legacy deploy removal, scheduled replay fetching, backup gate
execution, full run, diff readiness, and the future `web` runtime stay outside
this phase.

## Manual Backup

After the staging manifests are applied:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

The job writes a PostgreSQL custom-format dump, restore list, and JSON manifest
under the configured S3 bucket prefix `backups/postgres/`.
