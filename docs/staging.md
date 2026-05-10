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
- production cutover
- old statistics migration logic
- host nginx, certificate renewal, and firewall automation
- the future `web` runtime
- immediate removal of legacy application deploy workflows
- scheduled replay fetching before backup verification
- backup gate execution, controlled full run, and diff readiness

## Kubernetes Hardening Exceptions

### NetworkPolicy exception

Phase 1 documents network isolation as an explicit exception until the staging
k3s CNI is verified for NetworkPolicy enforcement. Future work must either add
tested NetworkPolicy manifests or document the cluster-level CNI configuration
that enforces equivalent isolation.

Stateful vendor images may keep image-specific security-context exceptions where
forcing a stricter setting would risk PostgreSQL or RabbitMQ startup. Those
exceptions must stay visible in manifest review and validation output.

### StatefulSet securityContext exception

PostgreSQL and RabbitMQ keep resource requests, resource limits, probes,
explicit ServiceAccounts, and disabled ServiceAccount token automounting, but
Phase 1 does not force pod/container `securityContext` changes onto their
existing PVC-backed StatefulSets. These images and mounted data directories
should be tested in an isolated restore or replacement environment before
tightening UID, filesystem group, capability, or privilege settings.

RabbitMQ includes a narrow init container that repairs `.erlang.cookie`
ownership and mode on the existing PVC before startup. This exists because
RabbitMQ refuses to boot unless the cookie file is accessible by the owner only.

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
jobs. This overlap is intentional until Phase 3; do not remove or disable those
legacy deploy jobs as part of Phase 1. The target steady state is:

1. App repository builds an image.
2. App repository publishes the image to GHCR.
3. Infra repository updates the staging image tag and deploys the environment.

This keeps shared runtime state, storage, backups, and app wiring in one place.

## Staging Handoff Matrix

| Resource area | v1 source of truth | App repository action |
|---------------|--------------------|-----------------------|
| Namespace `solid-stats-staging` | infrastructure | Stop applying namespace manifests. |
| PostgreSQL and RabbitMQ | infrastructure | Stop applying shared database and broker manifests. |
| `server-2` Deployment, Service, and ConfigMap | infrastructure | Keep building/publishing images; stop applying staging runtime wiring after handoff. |
| `replay-parser-2` Deployment | infrastructure | Keep building/publishing images; stop applying staging runtime wiring after handoff. |
| `replays-fetcher` CronJob | infrastructure | Keep building/publishing images; do not enable schedule outside the infra full-run plan. |
| PostgreSQL backup CronJob | infrastructure | Do not apply from app repositories. |

Legacy app deploy workflows may remain during the transition, but any workflow
that still applies these resources can overwrite the infra-owned staging state.

## Update a pinned app image

Application repositories publish images to GHCR. To deploy one in staging:

1. Find the immutable image tag or SHA produced by the app repository.
2. Update the matching image in this repository:
   - `server-2`: `k8s/staging/35-server-2-deployment.yaml`
   - `replay-parser-2`: `k8s/staging/40-replay-parser-2.yaml`
   - `replays-fetcher`: `k8s/staging/50-replays-fetcher.yaml`
3. Do not use `latest`.
4. Run `python3 scripts/validate-staging.py`.
5. Deploy through the infrastructure workflow or `./scripts/deploy-staging.sh`.

## Deploy and Verify

Run local validation before applying manifests:

```bash
python3 scripts/validate-staging.py
```

Apply staging from this repository:

```bash
./scripts/deploy-staging.sh
```

The deploy script verifies these rollout states:

```bash
kubectl -n solid-stats-staging rollout status statefulset/postgres --timeout=300s
kubectl -n solid-stats-staging rollout status statefulset/rabbitmq --timeout=300s
kubectl -n solid-stats-staging rollout status deployment/server-2 --timeout=300s
kubectl -n solid-stats-staging rollout status deployment/replay-parser-2 --timeout=300s
```

It then lists the runtime Service and CronJob surface:

```bash
kubectl -n solid-stats-staging get service postgres rabbitmq server-2 -o wide
kubectl -n solid-stats-staging get cronjob replays-fetcher postgres-backup -o wide
```

Phase 1 lists `cronjob replays-fetcher postgres-backup` but does not force-run
either CronJob.

## Replays Fetcher

The `replays-fetcher` CronJob is intentionally deployed with `suspend: true`.
Use a manual Job for the first controlled ingest run. Enable the schedule only
after backup verification and a clean full-run plan.

Keep `suspend: true` until backup verification and the controlled full-run
phase pass. Kubernetes hardening exceptions in this document are temporary
Phase 1 decisions until they can be verified against the staging k3s runtime.
