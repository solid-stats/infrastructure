---
phase: 12-resource-protection-obs-foundation
plan: "03"
subsystem: kubernetes-manifests
status: complete
tags: [kubernetes, qos, priorityclass, observability, prep-03, prep-04]

dependency_graph:
  requires:
    - 12-01 (validate-staging.py + validate-phase-12.sh scripts)
    - 12-02 (02-priority-classes.yaml — app-critical PriorityClass must exist before apply)
  provides:
    - All six runtime workload manifests carry priorityClassName: app-critical
    - postgres + server-2 manifests are Guaranteed-QoS-eligible (requests==limits all containers)
  affects:
    - k8s/staging/10-postgres.yaml
    - k8s/staging/20-rabbitmq.yaml
    - k8s/staging/35-server-2-deployment.yaml
    - k8s/staging/40-replay-parser-2.yaml
    - k8s/staging/50-replays-fetcher.yaml
    - k8s/staging/60-postgres-backup.yaml

tech_stack:
  added: []
  patterns:
    - priorityClassName injected at spec.template.spec for Deployments/StatefulSets
    - priorityClassName injected at spec.jobTemplate.spec.template.spec for CronJobs
    - Guaranteed QoS via requests==limits on ALL containers including initContainers

key_files:
  modified:
    - k8s/staging/10-postgres.yaml
    - k8s/staging/20-rabbitmq.yaml
    - k8s/staging/35-server-2-deployment.yaml
    - k8s/staging/40-replay-parser-2.yaml
    - k8s/staging/50-replays-fetcher.yaml
    - k8s/staging/60-postgres-backup.yaml

decisions:
  - "ASSUMED Guaranteed QoS values for postgres (cpu 500m, memory 1Gi) and server-2 (cpu 250m, memory 512Mi) authored from 12-RESEARCH.md A1/A2; Plan 05 must confirm against live kubectl top P95 before rollout"
  - "server-2 busybox initContainers (wait-for-postgres, wait-for-rabbitmq) each received minimal resources block (cpu 10m, memory 16Mi req==lim) — required for pod-level Guaranteed QoS class"
  - "rabbitmq, replay-parser-2, replays-fetcher, postgres-backup stay Burstable — PREP-04 scope is postgres + server-2 only"
  - "priorityClassName for CronJobs placed in spec.jobTemplate.spec.template.spec (not spec.template.spec which does not exist for CronJob)"

metrics:
  duration_seconds: 273
  completed: "2026-06-13"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 6
---

# Phase 12 Plan 03: Workload Priority + Guaranteed QoS Manifest Patches Summary

**One-liner:** All six runtime manifests now carry `priorityClassName: app-critical`; postgres and server-2 achieve Guaranteed QoS via requests==limits on every container including server-2's two busybox initContainers, with ASSUMED values flagged for Plan 05 live confirmation.

## What Was Built

PREP-03 + PREP-04 manifest patches across all six `k8s/staging/*.yaml` workload files.

**Task 1 — postgres + server-2 (PREP-03 + PREP-04):**

`10-postgres.yaml`: added `priorityClassName: app-critical` to `spec.template.spec`. Resources changed from Burstable (cpu 250m/1, memory 512Mi/2Gi) to Guaranteed (cpu 500m/500m, memory 1Gi/1Gi). Values are ASSUMED (A1) and carry inline comments requiring Plan 05 `kubectl top pods` P95 confirmation before rollout.

`35-server-2-deployment.yaml`: added `priorityClassName: app-critical`. Both busybox initContainers (`wait-for-postgres`, `wait-for-rabbitmq`) gained minimal resource blocks (cpu 10m/10m, memory 16Mi/16Mi req==lim) — previously they had no resources block at all, which would have kept the pod Burstable regardless of the main container. Main container resources changed from Burstable (cpu 100m/1, memory 256Mi/1Gi) to Guaranteed (cpu 250m/250m, memory 512Mi/512Mi). Values are ASSUMED (A2) with same Plan 05 confirmation comments.

**Task 2 — rabbitmq, replay-parser-2, replays-fetcher, postgres-backup (PREP-03 only):**

Each manifest received `priorityClassName: app-critical` at the correct pod-template depth:
- `20-rabbitmq.yaml` (StatefulSet): `spec.template.spec`
- `40-replay-parser-2.yaml` (Deployment): `spec.template.spec`
- `50-replays-fetcher.yaml` (CronJob): `spec.jobTemplate.spec.template.spec`
- `60-postgres-backup.yaml` (CronJob): `spec.jobTemplate.spec.template.spec`

No resource values changed on any of these four; they remain Burstable per PREP-04 scope.

**Task 3 — validate-staging.py guard:**

`python3 scripts/validate-staging.py` exits 0 (10/10 checks pass). All six patched manifests retained `serviceAccountName`, `automountServiceAccountToken: false`, `resources`/`requests`/`limits`, and `securityContext` (where applicable).

## Verification Results

```
# Task 1 QoS check (python3 inline)
OK  — postgres StatefulSet: priorityClassName=app-critical, all containers requests==limits
OK  — server-2 Deployment: priorityClassName=app-critical, all containers (incl. 2 initContainers) requests==limits

# Task 2 priority check (python3 inline)
OK  — rabbitmq StatefulSet: priorityClassName=app-critical
OK  — replay-parser-2 Deployment: priorityClassName=app-critical
OK  — replays-fetcher CronJob: priorityClassName=app-critical
OK  — postgres-backup CronJob: priorityClassName=app-critical

# Task 3 validate-staging.py
ok: script syntax
ok: manifest shape
ok: drill manifest safety
ok: workload safety
ok: app image pins
ok: rendered secret structure
ok: s3 lifecycle JSON
ok: s3 lifecycle config
ok: s3 lifecycle runbook
ok: cutover artifacts
```

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `2250f23` | feat(12-03): postgres + server-2 app-critical priority + Guaranteed QoS |
| Task 2 | `a1a582a` | feat(12-03): rabbitmq, replay-parser-2, replays-fetcher, postgres-backup → app-critical priority |
| Task 3 | `0b5820b` | chore(12-03): validate-staging.py guard passes after priorityClassName + QoS patches |

## Deviations from Plan

None — plan executed exactly as written. The `priorityClassName` injection point for `60-postgres-backup.yaml` was `spec.jobTemplate.spec.template.spec` before `restartPolicy` (which is the first field in that pod spec), consistent with the CronJob pattern in 12-PATTERNS.md.

## Known Stubs

None. No placeholder values or wired-but-empty data flows introduced. The ASSUMED resource values are explicitly provisional (flagged for Plan 05 confirmation) — this is by design per the plan, not a stub.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. Pure YAML field additions to existing manifests.

## Plan 05 Gate Reminder

Before applying these manifests to the live cluster (Plan 05 scope):

1. Run `kubectl top pods -n solid-stats-staging` to capture live P95 CPU and memory usage for postgres and server-2.
2. Verify that the ASSUMED values (`cpu: 500m / memory: 1Gi` for postgres; `cpu: 250m / memory: 512Mi` for server-2) are >= observed P95. If not, raise the limits before applying.
3. Take a fresh backup with `scripts/backup-postgres-now.sh` before the rolling restart (Pitfall 3 — single-replica StatefulSet means brief unavailability).

## Self-Check: PASSED

- [x] `k8s/staging/10-postgres.yaml` exists and contains `priorityClassName: app-critical` + Guaranteed QoS
- [x] `k8s/staging/35-server-2-deployment.yaml` exists and contains `priorityClassName: app-critical` + Guaranteed QoS incl. initContainers
- [x] `k8s/staging/20-rabbitmq.yaml` exists and contains `priorityClassName: app-critical`
- [x] `k8s/staging/40-replay-parser-2.yaml` exists and contains `priorityClassName: app-critical`
- [x] `k8s/staging/50-replays-fetcher.yaml` exists and contains `priorityClassName: app-critical`
- [x] `k8s/staging/60-postgres-backup.yaml` exists and contains `priorityClassName: app-critical`
- [x] Commits 2250f23, a1a582a, 0b5820b exist in git log
- [x] `python3 scripts/validate-staging.py` exits 0
- [x] No live cluster contacted
