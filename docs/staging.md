# Staging Operations

This repository owns the staging runtime infrastructure for Solid Stats.

## Scope

The staging cluster runs on the Timeweb VPS under the Kubernetes namespace
`solid-stats-staging`.

Owned here:

- namespace
- PostgreSQL StatefulSet and PVC
- RabbitMQ StatefulSet and PVC
- runtime ConfigMaps
- `server-2` Deployment and Service
- `replay-parser-2` Deployment
- `replays-fetcher` CronJob
- PostgreSQL backup CronJob

Not owned here:

- application source code
- container image builds
- production traffic cutover
- old statistics migration logic
- host nginx, certificate renewal, and firewall automation
- the future `web` runtime
- immediate removal of legacy application deploy workflows

## Kubernetes Hardening Exceptions

### NetworkPolicy exception

Phase 1 documents network isolation as an explicit exception until the staging
k3s CNI is verified for NetworkPolicy enforcement. Future work must either add
tested NetworkPolicy manifests or document the cluster-level CNI configuration
that enforces equivalent isolation.

Stateful vendor images may keep image-specific security-context exceptions where
forcing a stricter setting would risk PostgreSQL or RabbitMQ startup. Those
exceptions must stay visible in manifest review and validation output.

## Required GitHub Secrets

The `staging` GitHub environment must define:

- `CD_SSH_PRIVATE_KEY`
- `CD_SSH_HOST`
- `CD_SSH_PORT`
- `CD_SSH_USER`
- `GHCR_USERNAME`
- `GHCR_TOKEN`
- `POSTGRES_PASSWORD`
- `RABBITMQ_PASSWORD`
- `REPLAYS_FETCHER_REPLAY_SOURCE_URL`
- `S3_BUCKET`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

Optional:

- `SERVER2_BOOTSTRAP_ADMIN_STEAM_ID`
- `REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT`
- `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST`
- `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_COMMAND`

`scripts/render-staging-secrets.py` derives app-specific runtime keys from
these shared secrets. For example, it renders `SERVER2_DATABASE_URL`,
`REPLAYS_FETCHER_DATABASE_URL`, and `REPLAY_PARSER_AMQP_URL` into Kubernetes
Secrets, but GitHub only stores the shared PostgreSQL/RabbitMQ credentials and
shared S3 credentials.

## Deploy Model

Application repositories build and push images. This repository pins the images
that staging should run.

During the transition, application repositories may still have legacy deploy
jobs. The target steady state is:

1. App repository builds an image.
2. App repository publishes the image to GHCR.
3. Infra repository updates the staging image tag and deploys the environment.

This keeps shared runtime state, storage, backups, and app wiring in one place.

## Replays Fetcher

The `replays-fetcher` CronJob is intentionally deployed with `suspend: true`.
Use a manual Job for the first controlled ingest run. Enable the schedule only
after backup verification and a clean full-run plan.
