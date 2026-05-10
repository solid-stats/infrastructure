---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: quality
---

# Conventions

## Manifest Style

Kubernetes manifests are plain YAML under `k8s/staging/`.

Observed conventions:

- one environment per directory
- numeric filename prefixes for apply ordering
- explicit namespace on namespaced resources
- standard Kubernetes app labels
- image tags pinned to explicit SHAs for app deployments
- `imagePullPolicy: IfNotPresent` for pinned images

## Secret Handling

Secrets are not stored in the repository. `scripts/render-staging-secrets.py`
reads environment variables and emits Kubernetes Secret manifests with
`stringData`.

The deploy workflow passes GitHub `staging` environment secrets into the script.

## Script Style

Bash scripts use:

- `#!/usr/bin/env bash`
- `set -euo pipefail`
- explicit required env var checks through shell parameter expansion
- remote `kubectl` execution over SSH

Python script style:

- standard library only
- explicit `required()` helper for mandatory environment variables
- exits with code `64` for missing configuration

## Operational Safety

The fetcher schedule is intentionally suspended in
`k8s/staging/50-replays-fetcher.yaml`. This matches the operational plan to run
a controlled manual ingest only after backup verification.

The backup CronJob uses `concurrencyPolicy: Forbid` and keeps several successful
and failed job histories.

## Documentation Style

Docs are concise runbooks rather than implementation narratives. They describe
operator actions, required secrets, and expected outputs.

## Error Handling

Current scripts rely on shell failure propagation. `scripts/backup-postgres-now.sh`
prints Job description and logs if the backup Job does not complete.

## Commit State

At mapping time, the repository has not had an initial commit yet. All current
files are untracked initial infrastructure content.
