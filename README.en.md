# infrastructure

[Русский](README.md) · **English**

Source of truth for the **Solid Stats** runtime — statistics for the
[Solid Games](https://sg.zone) community (ArmA 3). Owns the Kubernetes (k3s)
staging environment: the `k8s/staging/` manifests, runtime wiring (secrets, env,
network isolation), deployment scripts and operational runbooks, the PostgreSQL
backup schedule to S3, and observability.

Part of a multi-repo platform: the backend and source of truth live in
`server-2`, raw replay discovery in `replays-fetcher`, OCAP parsing in
`replay-parser-2`, the web UI in `web`. infrastructure is the layer where their
images are composed into a working runtime. The images and application source
belong to those repos; this repo owns only how they are wired together in
staging.

> Solid Stats is built end to end by AI agents via the
> [GSD](https://github.com/open-gsd/gsd-core) process. Development outside GSD is
> outside the process.

## Quick start

Validate the manifests, scripts, and rendered Secret structure before deploy:

```bash
python3 scripts/validate-staging.py
```

Deploy runs in CI on pushes to `master` (or manually via `workflow_dispatch`):
it opens an SSH local-forward to the closed k3s API, builds a kubeconfig from the
`ci-deployer` ServiceAccount token, and applies `k8s/staging/`. Manual backup
after the manifests are applied:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
```

Secrets come from the GitHub environment at deploy time and are never stored in git.

## Documentation

- [docs/deploy.md](docs/deploy.md) — deploy model, v1 scope, ownership boundary
- [docs/staging.md](docs/staging.md) — staging operations and the Staging Handoff Matrix
- [docs/backup-restore.md](docs/backup-restore.md) — PostgreSQL backup and restore
- [docs/k3s-api-access.md](docs/k3s-api-access.md) — k3s API access from a workstation
- [docs/observability.md](docs/observability.md) · [docs/glitchtip.md](docs/glitchtip.md) — observability
- other runbooks live in [docs/](docs/); product context and state (GSD) live in `.planning/`

## Stack

Kubernetes (k3s) · PostgreSQL · RabbitMQ · Timeweb S3 · GitHub Actions · Bash · Python 3

## License — [MIT](LICENSE)
