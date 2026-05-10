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
- `SERVER2_DATABASE_URL`
- `SERVER2_RABBITMQ_URL`
- `SERVER2_S3_BUCKET`
- `SERVER2_S3_ACCESS_KEY_ID`
- `SERVER2_S3_SECRET_ACCESS_KEY`
- `REPLAY_PARSER_AMQP_URL`
- `REPLAY_PARSER_S3_BUCKET`
- `REPLAY_PARSER_AWS_ACCESS_KEY_ID`
- `REPLAY_PARSER_AWS_SECRET_ACCESS_KEY`
- `REPLAYS_FETCHER_DATABASE_URL`
- `REPLAYS_FETCHER_REPLAY_SOURCE_URL`
- `REPLAYS_FETCHER_S3_BUCKET`
- `REPLAYS_FETCHER_S3_ACCESS_KEY_ID`
- `REPLAYS_FETCHER_S3_SECRET_ACCESS_KEY`

Optional:

- `SERVER2_BOOTSTRAP_ADMIN_STEAM_ID`
- `REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT`
- `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_HOST`
- `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_COMMAND`

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
