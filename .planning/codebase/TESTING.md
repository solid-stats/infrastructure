---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: quality
---

# Testing

## Current Test Surface

There is no formal test framework in the repository. There is no package manager
file and no configured unit test command.

Current validation is operational and script-based.

## GitHub Actions Validation

`.github/workflows/deploy-staging.yml` has a `validate` job that checks:

- `k8s/staging` exists
- `scripts/render-staging-secrets.py` exists
- `scripts/deploy-staging.sh` exists
- staging manifest files are discoverable

This is a smoke check, not full YAML or Kubernetes schema validation.

## Deploy-Time Verification

`scripts/deploy-staging.sh` verifies deployment by waiting for:

- `statefulset/postgres`
- `statefulset/rabbitmq`
- `deployment/server-2`
- `deployment/replay-parser-2`

It also prints the `replays-fetcher` and `postgres-backup` CronJobs.

## Backup Verification

The backup CronJob in `k8s/staging/60-postgres-backup.yaml` validates each dump
before upload by running:

- `pg_dump --format=custom`
- `pg_restore --list`

The manual backup script waits for Job completion and prints logs.

## Missing Test Coverage

Recommended additions:

- YAML parsing check for all manifests.
- `kubectl apply --dry-run=client` or `--dry-run=server` validation.
- `shellcheck` for Bash scripts.
- Python syntax and basic unit tests for `scripts/render-staging-secrets.py`.
- A CI check that rendered secrets do not print secret values to logs.
- A restore drill check that validates a downloaded dump in an isolated
  database.

## Manual Verification Commands

Useful commands for this repository:

```bash
find k8s/staging -type f -name '*.yaml' -print | sort
python3 -m py_compile scripts/render-staging-secrets.py
bash -n scripts/deploy-staging.sh
bash -n scripts/backup-postgres-now.sh
```

Live verification requires access to the staging server and S3 credentials.
