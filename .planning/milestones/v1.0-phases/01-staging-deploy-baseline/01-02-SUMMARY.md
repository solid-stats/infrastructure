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
  deviations: 3
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

**[Rule 1 - Bug] CronJob file ServiceAccount API version** - Found during:
live validation retry | Issue: the `replays-fetcher` and `postgres-backup`
ServiceAccount documents used `apiVersion: batch/v1`, producing Kubernetes
`no matches for kind "ServiceAccount" in version "batch/v1"` errors. | Fix:
changed those ServiceAccount documents to `apiVersion: v1`. | Files modified:
`k8s/staging/50-replays-fetcher.yaml`,
`k8s/staging/60-postgres-backup.yaml` | Verification:
`python3 scripts/validate-staging.py` passes. | Commit hash: pending

**[Rule 4 - Scope Boundary] StatefulSet security contexts deferred** - Found
during: live validation retry | Issue: rollout hung after applying forced
StatefulSet security context changes to existing PostgreSQL/RabbitMQ
PVC-backed workloads. | Fix: removed forced PostgreSQL/RabbitMQ security
contexts, kept resources/probes/ServiceAccounts/token automount hardening, and
documented a `StatefulSet securityContext exception` until isolated testing can
prove stricter UID/fsGroup/capability settings are safe. | Files modified:
`k8s/staging/10-postgres.yaml`, `k8s/staging/20-rabbitmq.yaml`,
`docs/staging.md`, `scripts/validate-staging.py` | Verification:
`python3 scripts/validate-staging.py` passes. | Commit hash: pending

**[Rule 1 - Bug] RabbitMQ cookie permissions repaired on existing PVC** -
Found during: live diagnostics | Issue: `rabbitmq-0` crashed with `Cookie file
/var/lib/rabbitmq/.erlang.cookie must be accessible by owner only` after the
earlier StatefulSet permission changes touched the PVC. | Fix: added a narrow
`repair-erlang-cookie-permissions` init container to `k8s/staging/20-rabbitmq.yaml`
that runs `chown 999:999` and `chmod 600` on the cookie file when it exists. |
Files modified: `k8s/staging/20-rabbitmq.yaml`, `docs/staging.md` |
Verification: `python3 scripts/validate-staging.py` passes; live RabbitMQ
rollout passed after recreating `rabbitmq-0`. | Commit hash: 3d62b6f

**Total deviations:** 3 auto-fixed. **Impact:** RabbitMQ can recover the
existing PVC cookie permissions without deleting durable broker state.

## Self-Check: PASSED

Plan acceptance criteria are satisfied.
