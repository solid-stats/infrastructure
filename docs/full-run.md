# Controlled Full Run

The controlled full run starts one manual `replays-fetcher` Job after the
backup gate is verified. It does not enable the recurring CronJob schedule.

## Preconditions

- `docs/backup-gate.md` contains `Status: verified`.
- `replays-fetcher` remains deployed with `suspend: true`.
- PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2` are rolled out.

## Start

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/start-controlled-full-run.sh
```

## Monitor

Queue depth:

```bash
kubectl -n solid-stats-staging exec statefulset/rabbitmq -- \
  rabbitmqctl list_queues name messages messages_ready messages_unacknowledged consumers
```

Parser rollout and pods:

```bash
kubectl -n solid-stats-staging rollout status deployment/replay-parser-2 --timeout=300s
kubectl -n solid-stats-staging get pods -l app.kubernetes.io/name=replay-parser-2 -o wide
```

Server readiness:

```bash
kubectl -n solid-stats-staging rollout status deployment/server-2 --timeout=300s
kubectl -n solid-stats-staging get endpoints server-2
```

Fetcher Job logs:

```bash
kubectl -n solid-stats-staging logs job/<manual-job-name> --all-containers=true
```

S3 object writes:

```bash
aws --endpoint-url=https://s3.twcstorage.ru s3 ls s3://<bucket>/ --recursive
```

## Checkpoints

Record the manual Job name, start time, finish time, queue depth trend, parser
pod health, server readiness, and observed S3 prefixes before treating the run
as usable input for diff work.
