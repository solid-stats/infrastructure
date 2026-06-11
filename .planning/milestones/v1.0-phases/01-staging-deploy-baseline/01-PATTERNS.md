# Phase 01 - Pattern Map

## Existing Patterns to Reuse

| Target | Closest Existing Pattern | Notes |
|--------|--------------------------|-------|
| `scripts/validate-staging.py` | `scripts/render-staging-secrets.py` | Use Python standard library only, explicit helper functions, deterministic stderr/stdout, exit non-zero on validation failures. |
| `.github/workflows/deploy-staging.yml` validation | Existing `validate` job | Keep validation before deploy and avoid printing secret values. |
| Kubernetes manifests | `k8s/staging/*.yaml` | Plain YAML, numeric apply order, explicit namespaces, standard labels, pinned images for app workloads. |
| Operator docs | `README.md`, `docs/staging.md` | Concise runbook style with commands, required secrets, expected outputs, and scope boundaries. |
| Deploy verification | `scripts/deploy-staging.sh` | Remote `kubectl` over SSH, rollout status for stateful/runtime workloads, CronJob listing for scheduled jobs. |

## Files Expected to Change

- `.github/workflows/deploy-staging.yml`
- `README.md`
- `docs/staging.md`
- `k8s/staging/10-postgres.yaml`
- `k8s/staging/20-rabbitmq.yaml`
- `k8s/staging/35-server-2-deployment.yaml`
- `k8s/staging/40-replay-parser-2.yaml`
- `k8s/staging/50-replays-fetcher.yaml`
- `k8s/staging/60-postgres-backup.yaml`
- `scripts/render-staging-secrets.py`
- `scripts/validate-staging.py`

## Constraints

- Do not add Helm, Kustomize, Node, Python dependencies, or a package manager.
- Do not commit real secrets or rendered secret fixtures.
- Do not enable the suspended `replays-fetcher` CronJob.
- Do not move legacy app repository deployment ownership in Phase 1.
