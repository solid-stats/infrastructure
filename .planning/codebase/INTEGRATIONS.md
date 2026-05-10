---
last_mapped: 2026-05-10
last_mapped_commit: uncommitted-initial-infra
focus: tech
---

# Integrations

## GitHub Actions

`.github/workflows/deploy-staging.yml` deploys infrastructure on pushes to
`main` or `master`, and through `workflow_dispatch`.

It expects GitHub `staging` environment secrets for SSH, GHCR, PostgreSQL,
RabbitMQ, app runtime URLs, and S3 credentials. The full list is documented in
`docs/staging.md`.

## SSH Deploy Target

`scripts/deploy-staging.sh` connects to the staging host using:

- `CD_SSH_USER`
- `CD_SSH_HOST`
- `CD_SSH_PORT`
- `CD_SSH_KEY_PATH`

The remote host must have `kubectl` configured for the k3s cluster. The script
does not install k3s or bootstrap the server.

## Kubernetes API

All runtime objects are applied through `kubectl apply -f -` or `kubectl apply`
against the remote cluster. Manifests target the namespace
`solid-stats-staging`.

## Container Registry

Application and runtime images come from:

- `ghcr.io/solid-stats/server-2`
- `ghcr.io/solid-stats/replay-parser-2`
- `ghcr.io/solid-stats/replays-fetcher`
- Docker Hub images `postgres:17-alpine`, `rabbitmq:4-management`, and
  `busybox:1.37`

The `ghcr-pull` image pull secret is rendered by
`scripts/render-staging-secrets.py`.

## PostgreSQL

The `postgres` service is internal to the namespace and exposes port `5432`.

Consumers:

- `server-2` through `SERVER2_DATABASE_URL`.
- `replays-fetcher` through `REPLAYS_FETCHER_DATABASE_URL`.
- `postgres-backup` through Kubernetes service DNS `postgres`.

## RabbitMQ

The `rabbitmq` service exposes AMQP port `5672` and management port `15672`
inside the namespace.

Consumers:

- `server-2` through `SERVER2_RABBITMQ_URL`.
- `replay-parser-2` through `REPLAY_PARSER_AMQP_URL`.

The parser queue contract is encoded in `k8s/staging/40-replay-parser-2.yaml`:

- job queue `server2.parse.requested`
- result exchange `solid_stats.parser`
- completed key `parse.completed`
- failed key `parse.failed`

## Timeweb S3

All app manifests point at `https://s3.twcstorage.ru` with region `ru-1` and
path-style access.

Current object prefixes:

- raw replay and artifact prefixes are owned by app contracts.
- PostgreSQL backups use `backups/postgres/`.

## Public HTTP

This repo does not currently own nginx, ingress, or certificate resources. The
current staging public entrypoint is documented operationally, while Kubernetes
serves `server-2` through an internal `Service`.
