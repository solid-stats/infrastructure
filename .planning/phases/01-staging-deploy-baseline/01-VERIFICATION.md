---
phase: "01"
status: passed
verified_at: 2026-05-10
---

# Phase 01 Verification - Staging Deploy Baseline

## Status

status: human_needed

Local validation, plan acceptance criteria, and live staging rollout evidence
passed.

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
- Live rollout verification passed:
  - `statefulset/postgres`
  - `statefulset/rabbitmq`
  - `deployment/server-2`
  - `deployment/replay-parser-2`
- Live resource listing passed:
  - `service/postgres`
  - `service/rabbitmq`
  - `service/server-2`
  - `cronjob/replays-fetcher` with `SUSPEND=True`
  - `cronjob/postgres-backup`

## Success Criteria Review

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Operator can see namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`, `replays-fetcher`, and backup resources represented in this repository. | passed | `k8s/staging/*.yaml`, README, and staging docs name the resource set. |
| Operator can apply the staging manifests to k3s from this repository without relying on app repository deploy steps. | passed | Live apply and follow-up targeted applies succeeded through `kubectl apply --validate=false`; rollout blockers were fixed without app repository deploy steps. |
| Operator can verify PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2` rollout state after deploy. | passed | Live rollout status succeeded for both StatefulSets and both Deployments. |
| CI catches broken manifest/script syntax, unsafe secret rendering, missing resource limits, default ServiceAccount usage, and missing security-context or NetworkPolicy decisions before deploy reaches staging. | passed | `scripts/validate-staging.py` enforces these checks and CI invokes it. |
| Documentation states which v1 resources remain intentionally outside infrastructure ownership and which Kubernetes hardening exceptions are deliberate. | passed | `README.md` and `docs/staging.md` document Phase 1 scope, exclusions, app-CD overlap, suspended fetcher, and NetworkPolicy exception. |

## Live Verification Notes

Live validation found and fixed three deployment blockers:

1. Remote `kubectl apply` validation required cluster-scoped CRD list
   permissions, so `scripts/deploy-staging.sh` now applies with
   `--validate=false`.
2. CronJob file ServiceAccount documents used `apiVersion: batch/v1`; they now
   use `apiVersion: v1`, and the validator checks kind/API compatibility.
3. RabbitMQ's existing PVC had a non-owner-only `.erlang.cookie`; the RabbitMQ
   manifest now includes a narrow init container that repairs the cookie mode
   before startup.

## Gaps

No implementation gaps remain for Phase 1.
