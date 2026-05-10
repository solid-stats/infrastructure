---
phase: "01"
status: human_needed
verified_at: 2026-05-10
---

# Phase 01 Verification - Staging Deploy Baseline

## Status

status: human_needed

Local validation and plan acceptance criteria passed. Live staging deploy and
rollout evidence still requires staging SSH access and GitHub/staging secrets,
which are not available in this local session.

## Automated Evidence

- `python3 scripts/validate-staging.py` passed.
  - `ok: script syntax`
  - `ok: manifest shape`
  - `ok: workload safety`
  - `ok: rendered secret structure`
  - `warn: kubectl dry-run skipped because configured cluster is unreachable`
- `bash -n scripts/deploy-staging.sh` passed.
- `bash -n scripts/backup-postgres-now.sh` passed.
- GSD execute init shows `plan_count: 4`, `incomplete_count: 0`, and summaries
  for all four Phase 1 plans.

## Success Criteria Review

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Operator can see namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`, `replays-fetcher`, and backup resources represented in this repository. | passed | `k8s/staging/*.yaml`, README, and staging docs name the resource set. |
| Operator can apply the staging manifests to k3s from this repository without relying on app repository deploy steps. | human_needed | `scripts/deploy-staging.sh` is wired and syntax-valid, but live SSH deploy was not run locally. |
| Operator can verify PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2` rollout state after deploy. | human_needed | deploy script contains rollout checks; live rollout output not captured locally. |
| CI catches broken manifest/script syntax, unsafe secret rendering, missing resource limits, default ServiceAccount usage, and missing security-context or NetworkPolicy decisions before deploy reaches staging. | passed | `scripts/validate-staging.py` enforces these checks and CI invokes it. |
| Documentation states which v1 resources remain intentionally outside infrastructure ownership and which Kubernetes hardening exceptions are deliberate. | passed | `README.md` and `docs/staging.md` document Phase 1 scope, exclusions, app-CD overlap, suspended fetcher, and NetworkPolicy exception. |

## Human Verification Required

1. Run the staging deploy workflow or execute `./scripts/deploy-staging.sh` with
   `CD_SSH_HOST`, `CD_SSH_USER`, SSH key, and staging secret environment
   variables available.
2. Confirm rollout output succeeds for:
   - `statefulset/postgres`
   - `statefulset/rabbitmq`
   - `deployment/server-2`
   - `deployment/replay-parser-2`
3. Confirm output lists:
   - `service/postgres`
   - `service/rabbitmq`
   - `service/server-2`
   - `cronjob/replays-fetcher`
   - `cronjob/postgres-backup`

## Gaps

No implementation gaps were found in repository-local checks. The only remaining
gap is live staging evidence.
