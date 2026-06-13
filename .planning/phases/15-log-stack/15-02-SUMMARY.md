---
phase: 15-log-stack
plan: "02"
subsystem: infra
tags: [alloy, helm, kubernetes, observability, log-stack, rbac, security]

requires:
  - phase: 15-log-stack/15-01
    provides: loki Service loki:3100 push endpoint, validate-obs-manifests.py gate, validate-phase-15.sh harness

provides:
  - k8s/observability/values/alloy-values.yaml — Alloy DaemonSet helm values + conservative River pipeline (LOG-02)
  - k8s/observability/80-alloy.yaml — rendered Alloy DaemonSet + Service + ConfigMap + SA (no ClusterRole)
  - k8s/staging/03-alloy-rbac.yaml — operator-bootstrap ClusterRole + ClusterRoleBinding (read-only pods/log/namespaces)
  - scripts/validate-obs-manifests.py — hardened: forbids ClusterRole in k8s/observability/

affects: [15-03-grafana-prometheus-extend, 15-04-apply]

tech-stack:
  added: [grafana/alloy helm chart v1.10.0, alloy image v1.17.0, River/Alloy pipeline syntax]
  patterns:
    - rbac-split: rbac.create:false in alloy-values.yaml; ClusterRole hand-authored in operator-bootstrap k8s/staging/03-alloy-rbac.yaml
    - conservative-pipeline: discovery.kubernetes → drop monitoring ns → relabel 5 labels → loki.source.kubernetes → stage.label_keep → loki.write (LOG-02)
    - validate-gate-hardening: _check_no_clusterrole() blocks ClusterRole in CI-applied obs dir (T-15-07)
    - phase13-clusterrole-backfill: kube-state-metrics + grafana ClusterRoles extracted from 20/50-*.yaml into 01-obs-rbac.yaml bootstrap (gate fired on existing artefacts)

key-files:
  created:
    - k8s/observability/values/alloy-values.yaml
    - k8s/observability/80-alloy.yaml
    - k8s/staging/03-alloy-rbac.yaml
  modified:
    - scripts/validate-obs-manifests.py
    - k8s/observability/20-kube-state-metrics.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/staging/01-obs-rbac.yaml
    - .github/workflows/deploy-staging.yml

key-decisions:
  - "rbac.create:false in alloy-values.yaml — avoids ClusterRole in CI-applied 80-alloy.yaml; ClusterRole hand-authored in 03-alloy-rbac.yaml (Open Question 2 from RESEARCH)"
  - "duplicate alloy: YAML key bug fixed — RESEARCH example had two alloy: top-level blocks; second block (listenPort/enableReporting) overwrote first (resources/configMap); merged into single block"
  - "stage.label_keep allowlist: exactly 5 keys (namespace/pod/container/app/job) — LOG-02 security control; no message-body parsing, no high-cardinality labels"
  - "monitoring namespace drop rule first in discovery.relabel — prevents Alloy log self-loop (T-15-06/Pitfall 7)"
  - "_FORBIDDEN_OBS_KINDS stored as set constant — T-13-03 discipline (no self-invalidating literal in head comment)"
  - "Phase 13 ClusterRoles backfilled to 01-obs-rbac.yaml — gate fired on kube-state-metrics + grafana ClusterRoles already in obs dir; extracted per Rule 2 (missing critical: gate cannot be green otherwise)"
  - "03-alloy-rbac.yaml excluded from both dry-run and deploy find globs in deploy-staging.yml — mirrors 01-obs-rbac.yaml pattern"

requirements-completed: [LOG-02]

duration: 35min
completed: 2026-06-14
status: complete
---

# Phase 15 Plan 02: Alloy DaemonSet Render + Operator Bootstrap RBAC + Hardened Gate Summary

**Alloy v1.17.0 rendered as DaemonSet with 5-label-only River pipeline (LOG-02); ClusterRole operator-bootstrapped in 03-alloy-rbac.yaml; validate gate now blocks cluster RBAC in CI-applied obs dir**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-14T00:00:00Z
- **Completed:** 2026-06-14
- **Tasks:** 3
- **Files created:** 3 / Files modified: 5

## Accomplishments

- Authored `alloy-values.yaml`: DaemonSet mode, `rbac.create:false`, `obs-background` priority, 30m/64Mi requests, River pipeline with `discovery.kubernetes` → monitoring-namespace drop rule → 5-label relabel → `loki.source.kubernetes` → `stage.label_keep` → `loki.write http://loki.monitoring.svc:3100/loki/api/v1/push`
- Rendered `80-alloy.yaml` via `helm template grafana/alloy v1.10.0`: DaemonSet + Service alloy:12345 + ConfigMap + ServiceAccount alloy; no ClusterRole/ClusterRoleBinding
- Authored `k8s/staging/03-alloy-rbac.yaml`: operator-bootstrap header, ClusterRole `alloy` (read-only get/list/watch on pods/pods log/namespaces/events/endpoints/services), ClusterRoleBinding to SA `alloy` in `monitoring`
- Added `03-alloy-rbac.yaml` exclusion to both dry-run and deploy `find` globs in `deploy-staging.yml`
- Hardened `validate-obs-manifests.py`: `_FORBIDDEN_OBS_KINDS` constant + `_check_no_clusterrole()` + wired into `validate()` per-doc loop; gate fires with clear message directing to `k8s/staging/`
- Backfilled Phase 13 ClusterRoles (kube-state-metrics + grafana) from obs manifests to `01-obs-rbac.yaml` so hardened gate passes green

## Task Commits

1. **Task 1: alloy-values.yaml + 80-alloy.yaml** — `7faea8e` (feat)
2. **Task 2: 03-alloy-rbac.yaml + CI glob exclusion** — `513dfbd` (feat)
3. **Task 3: harden validate-obs-manifests.py + Phase 13 ClusterRole backfill** — `0b22795` (feat)

## Files Created

- `k8s/observability/values/alloy-values.yaml` — Alloy DaemonSet helm values with full River pipeline
- `k8s/observability/80-alloy.yaml` — rendered: 1 ServiceAccount + 1 ConfigMap + 1 Service + 1 DaemonSet (no ClusterRole)
- `k8s/staging/03-alloy-rbac.yaml` — ClusterRole alloy (read-only) + ClusterRoleBinding → SA alloy/monitoring

## Files Modified

- `scripts/validate-obs-manifests.py` — `_check_no_clusterrole()` added; `_FORBIDDEN_OBS_KINDS` constant
- `k8s/observability/20-kube-state-metrics.yaml` — ClusterRole + ClusterRoleBinding stripped
- `k8s/observability/50-grafana.yaml` — ClusterRole + ClusterRoleBinding stripped
- `k8s/staging/01-obs-rbac.yaml` — kube-state-metrics + grafana ClusterRole/CRB appended
- `.github/workflows/deploy-staging.yml` — `! -name '03-alloy-rbac.yaml'` added to dry-run and deploy globs

## Decisions Made

- `rbac.create: false` approach (RESEARCH Open Question 2) — cleaner than rendering then stripping; bootstrap file stays canonical
- `loki.source.kubernetes` over `loki.source.file` — no hostPath/privileged needed (Pitfall 8)
- monitoring namespace drop as first relabel rule — prevents log self-loop before any label computation (Pitfall 7, T-15-06)
- Phase 13 ClusterRole backfill treated as Rule 2 (not Rule 4) — no new table/service/auth approach; purely moving existing YAML docs to correct file

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate `alloy:` YAML key in alloy-values.yaml**
- **Found during:** Task 1 (helm render showed 10m/50Mi resources instead of 30m/64Mi)
- **Issue:** RESEARCH example had two top-level `alloy:` blocks. YAML parsers silently use the last key, so the `resources` + `configMap` block was overwritten by the `listenPort` + `enableReporting` block.
- **Fix:** Merged `listenPort` and `enableReporting` into the single `alloy:` block alongside `resources` and `configMap`.
- **Files modified:** `k8s/observability/values/alloy-values.yaml`
- **Commit:** `7faea8e`

**2. [Rule 2 - Missing Critical] Phase 13 ClusterRoles blocking hardened gate**
- **Found during:** Task 3 (validate-obs-manifests.py fired on existing obs files after adding `_check_no_clusterrole`)
- **Issue:** `20-kube-state-metrics.yaml` and `50-grafana.yaml` contained ClusterRole + ClusterRoleBinding from Phase 13 helm renders. The pre-15-02 validator had no ClusterRole check so these passed silently. The hardened gate correctly rejected them.
- **Fix:** Python doc-split filtered both files to remove ClusterRole/ClusterRoleBinding docs; all 4 docs appended to `k8s/staging/01-obs-rbac.yaml` with operator-bootstrap header comments.
- **Files modified:** `k8s/observability/20-kube-state-metrics.yaml`, `k8s/observability/50-grafana.yaml`, `k8s/staging/01-obs-rbac.yaml`
- **Commit:** `0b22795`

## Threat Surface Scan

All threat model items covered:

| T-ID | Mitigation | Status |
|------|-----------|--------|
| T-15-04 | Alloy ClusterRole read-only get/list/watch; no write verbs, no secrets | 03-alloy-rbac.yaml |
| T-15-05 | stage.label_keep allows exactly 5 keys; all other labels dropped | alloy-values.yaml River pipeline |
| T-15-06 | monitoring namespace drop rule first in discovery.relabel | alloy-values.yaml River pipeline |
| T-15-07 | rbac.create:false; ClusterRole only in operator-bootstrap; gate forbids ClusterRole in obs dir | all three files |

No new threat surface beyond the plan's threat model.

## Known Stubs

None — authoring only (Wave 1). Alloy DaemonSet will start collecting logs only after 15-04 applies the stack live.

## Next Phase Readiness

- `80-alloy.yaml` ready for apply in 15-04 (Wave 2)
- `03-alloy-rbac.yaml` must be applied by operator BEFORE 15-04 CI apply (ClusterRoleBinding must exist before DaemonSet starts)
- Prometheus scrape target for 15-03: `alloy.monitoring.svc:12345/metrics`
- Alloy DaemonSet SA name: `alloy` (namespace `monitoring`) — matches ClusterRoleBinding subject in 03-alloy-rbac.yaml

---
*Phase: 15-log-stack*
*Completed: 2026-06-14*
