---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: concerns
---

# Concerns

## Initial Commit Gap

The repository has no initial commit yet. All files are currently untracked.
This is expected during bootstrap, but it means there is no committed baseline
for rollback until the first commit lands.

## App CD Overlap

Application repositories still contain deployment workflows and manifests. This
creates a temporary risk that an app deployment can overwrite resources now
owned by this repository.

The highest-risk overlaps are:

- `server-2` applying PostgreSQL, RabbitMQ, and server manifests.
- `replay-parser-2` applying parser Deployment.
- `replays-fetcher` applying fetcher CronJob.

The desired steady state is documented in `docs/staging.md`: app repositories
publish images, and this repository deploys shared runtime wiring.

## Secret Rendering Bug Risk

`scripts/render-staging-secrets.py` renders `.dockerconfigjson` through
`stringData`, but the JSON currently leaves the Docker `auth` field empty. Some
Kubernetes versions and registry clients may accept username/password without
`auth`; others may not. This should be verified or fixed before relying on the
new infra deploy workflow.

## Backup Image Startup Cost

`k8s/staging/60-postgres-backup.yaml` installs `aws-cli` with `apk add` during
each backup run. This keeps the manifest simple, but backup success depends on
Alpine package network availability at runtime. A dedicated backup image would
be more deterministic.

## Restore Drill Not Yet Executed

`docs/backup-restore.md` describes restore validation, but no restore drill has
been executed from this repo yet. A full ingest run should wait until at least
one manual backup and restore-list validation succeed.

## Missing Schema Validation

The CI validation job only checks file presence. It does not validate Kubernetes
schema, CronJob API compatibility, or shell script quality. Add manifest and
script validation before treating this repository as production-grade.

## Public Edge Not Owned Here

The current public staging path uses host-level nginx outside Kubernetes. This
repository documents Kubernetes resources but does not yet manage nginx,
certificate renewal, or host firewall state.

## S3 Prefix Lifecycle

The backup prefix is defined as `backups/postgres`, but retention and lifecycle
policy are not enforced in code. Timeweb S3 bucket lifecycle rules should be
configured or documented before backups grow.
