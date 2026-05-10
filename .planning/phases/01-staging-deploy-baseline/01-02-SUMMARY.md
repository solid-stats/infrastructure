---
phase: "01"
plan: "01-02"
subsystem: "kubernetes"
status: complete
tags:
  - kubernetes
  - hardening
key-files:
  - k8s/staging/10-postgres.yaml
  - k8s/staging/20-rabbitmq.yaml
  - k8s/staging/35-server-2-deployment.yaml
  - k8s/staging/40-replay-parser-2.yaml
  - k8s/staging/50-replays-fetcher.yaml
  - k8s/staging/60-postgres-backup.yaml
  - docs/staging.md
metrics:
  tasks_completed: 3
  deviations: 0
---

# Plan 01-02 Summary - Kubernetes hardening baseline

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 01-02-01 | 4b98b5d | Added explicit ServiceAccounts, `serviceAccountName`, and disabled token automount for staging workloads. |
| 01-02-02 | 4b98b5d | Added PostgreSQL/RabbitMQ resources and security-context decisions across workload manifests. |
| 01-02-03 | 4b98b5d | Documented the Phase 1 NetworkPolicy exception until staging CNI enforcement is verified. |

## Verification

- `grep -R "kind: ServiceAccount" k8s/staging` passed.
- `grep -R "serviceAccountName:" k8s/staging` passed.
- `grep -n "resources:" k8s/staging/10-postgres.yaml` passed.
- `grep -n "resources:" k8s/staging/20-rabbitmq.yaml` passed.
- `grep -R "securityContext:" k8s/staging` passed.
- `grep -R "kind: NetworkPolicy" k8s/staging || grep -q "NetworkPolicy exception" docs/staging.md` passed.
- `python3 scripts/validate-staging.py` passed.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

Plan acceptance criteria are satisfied.
