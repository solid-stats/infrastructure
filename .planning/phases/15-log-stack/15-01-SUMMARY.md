---
phase: 15-log-stack
plan: "01"
subsystem: infra
tags: [loki, helm, kubernetes, observability, log-stack, prometheus, validation]

requires:
  - phase: 13-obs-stack
    provides: monitoring namespace, obs-background PriorityClass, prometheus-server deploy, validate-obs-manifests.py gate
  - phase: 12-resource-protection
    provides: obs-background PriorityClass, local-path StorageClass, obs-ci-deployer SA

provides:
  - k8s/observability/values/loki-values.yaml — Loki SingleBinary/filesystem helm values
  - k8s/observability/70-loki.yaml — rendered Loki StatefulSet + Service loki:3100 (ClusterRole stripped)
  - scripts/validate-phase-15.sh — live LOG-01/02/03 assertion harness with corrected metric names

affects: [15-02-alloy, 15-03-grafana-prometheus-extend, 15-04-apply]

tech-stack:
  added: [grafana/loki helm chart v7.0.0, loki image 3.6.11, TSDB store schema v13]
  patterns:
    - helm-template-filter: ClusterRole/ClusterRoleBinding stripped from rendered manifest (obs-ci-deployer namespace-scoped constraint, same as Phase 13 Prometheus)
    - loki-single-binary: deploymentMode SingleBinary + replication_factor 1 + filesystem PVC 10Gi
    - metric-name-correction: validation uses loki_boltdb_shipper_compactor_running / loki_write_sent_entries_total (ROADMAP names were wrong)

key-files:
  created:
    - k8s/observability/values/loki-values.yaml
    - k8s/observability/70-loki.yaml
    - scripts/validate-phase-15.sh
  modified: []

key-decisions:
  - "deploymentMode: SingleBinary + all microservice replicas: 0 — prevents chart default SimpleScalable from spawning read/write/backend OOM pods"
  - "replication_factor: 1 required — without it writes fail with ring quorum errors even in single-binary mode"
  - "chunksCache + resultsCache disabled — removed unnecessary memcached StatefulSets (9830Mi request each) that would OOM staging node"
  - "lokiCanary disabled at both monitoring.lokiCanary and top-level lokiCanary keys — chart v7.0.0 requires both to suppress DaemonSet"
  - "ClusterRole + ClusterRoleBinding stripped from 70-loki.yaml via Python doc-split filter — obs-ci-deployer is namespace-scoped (same constraint as Phase 13)"
  - "loki image pinned to 3.6.11 (chart appVersion is 3.6.7) — latest patch on same minor"
  - "PVC whenScaled/whenDeleted: Retain — prevents data loss on accidental scale-down"

patterns-established:
  - "Render-and-filter: helm template + Python YAML doc-split to strip cluster-scoped resources"
  - "Corrected metric names: loki_boltdb_shipper_compactor_running (not loki_compactor_runs_total)"
  - "Corrected metric names: loki_write_sent_entries_total (not alloy_logs_entries_total)"

requirements-completed: [LOG-01, LOG-02, LOG-03]

duration: 35min
completed: 2026-06-13
status: complete
---

# Phase 15 Plan 01: Loki SingleBinary Render + Phase-15 Validation Harness Summary

**Loki 3.6.11 rendered as SingleBinary StatefulSet on 10Gi filesystem PVC with 168h compactor retention; validate-phase-15.sh asserts LOG-01/02/03 with corrected metric names**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-13T22:30:00Z
- **Completed:** 2026-06-13T23:06:19Z
- **Tasks:** 3
- **Files created:** 3

## Accomplishments

- Authored `loki-values.yaml` with all critical knobs: SingleBinary mode, replication_factor 1, TSDB+v13+24h schema (required for retention), 168h compactor retention, fullnameOverride loki, tight obs-background resources
- Rendered `70-loki.yaml` via `helm template grafana/loki v7.0.0`: SingleBinary StatefulSet with Service `loki:3100`, ClusterRole/ClusterRoleBinding stripped, `python3 validate-obs-manifests.py` green
- Authored `validate-phase-15.sh` mirroring validate-phase-13.sh structure: `assert()` helper, `--quick` flag, LOG-01 (pod/PVC/compactor gauge/config), LOG-02 (alloy DaemonSet/sent_entries), LOG-03 (Grafana datasource health + LogQL acceptance), corrected metric names throughout

## Task Commits

1. **Task 1: Author loki-values.yaml** — `611b201` (feat)
2. **Task 2: Render 70-loki.yaml** — `47e0352` (feat)
3. **Task 3: Author validate-phase-15.sh** — `64182e2` (feat)

## Files Created

- `k8s/observability/values/loki-values.yaml` — Loki SingleBinary/filesystem/compactor helm values (114 lines)
- `k8s/observability/70-loki.yaml` — Rendered manifest: 1 StatefulSet + 3 Services + 2 ConfigMaps + 1 ServiceAccount (ClusterRole stripped)
- `scripts/validate-phase-15.sh` — Live LOG-01/02/03 assertion harness, executable, bash -n clean

## Decisions Made

- Disabled `chunksCache` and `resultsCache` in values (chart v7.0.0 enables memcached by default — each requests 9830Mi, which would OOM the 7.75Gi staging node)
- Disabled `lokiCanary` at both `monitoring.lokiCanary` and top-level `lokiCanary` keys (chart v7.0.0 requires both; setting only one left the canary DaemonSet in the render)
- Used Python YAML doc-split to strip ClusterRole/ClusterRoleBinding from rendered output (same pattern as Phase 13 Prometheus — obs-ci-deployer is namespace-scoped and cannot apply cluster-scoped resources)
- Kept Loki image at `3.6.11` (latest patch) vs chart appVersion `3.6.7` — no breaking changes on same minor

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Disabled memcached caches (chunksCache / resultsCache)**
- **Found during:** Task 2 (helm template render inspection)
- **Issue:** Chart v7.0.0 enables chunksCache and resultsCache by default. Each memcached StatefulSet requests 9830Mi RAM — both together would exceed node capacity (7.75Gi total). Not mentioned in RESEARCH pitfalls but a critical omission for staging viability.
- **Fix:** Added `chunksCache.enabled: false` and `resultsCache.enabled: false` to loki-values.yaml. Updated values file committed as part of Task 2.
- **Files modified:** `k8s/observability/values/loki-values.yaml`
- **Verification:** Re-render produces 1 StatefulSet (loki only), no memcached StatefulSets
- **Committed in:** `47e0352`

**2. [Rule 2 - Missing Critical] Added top-level `lokiCanary.enabled: false`**
- **Found during:** Task 2 (render inspection — DaemonSet without priorityClassName failed validate-obs-manifests.py)
- **Issue:** `monitoring.lokiCanary.enabled: false` (RESEARCH value) did not suppress the loki-canary DaemonSet in chart v7.0.0. The chart also reads a top-level `lokiCanary.enabled` key.
- **Fix:** Added `lokiCanary:\n  enabled: false` at top level in loki-values.yaml.
- **Files modified:** `k8s/observability/values/loki-values.yaml`
- **Verification:** Re-render produces no DaemonSet; validate-obs-manifests.py passes
- **Committed in:** `47e0352`

**3. [Rule 2 - Missing Critical] Filtered ClusterRole/ClusterRoleBinding from 70-loki.yaml**
- **Found during:** Task 2 (validate-obs-manifests.py caught ClusterRole in k8s/observability/)
- **Issue:** Loki chart always renders a ClusterRole + ClusterRoleBinding. obs-ci-deployer cannot apply cluster-scoped resources (same constraint as Phase 13 Prometheus). Plan said "if ClusterRole present, strip" but didn't specify the implementation.
- **Fix:** Python YAML doc-split filter removes documents with `kind: ClusterRole` or `kind: ClusterRoleBinding` from the rendered YAML before writing 70-loki.yaml.
- **Files modified:** `k8s/observability/70-loki.yaml`
- **Verification:** `! grep -q 'kind: ClusterRole' 70-loki.yaml`; validate-obs-manifests.py green
- **Committed in:** `47e0352`

---

**Total deviations:** 3 auto-fixed (all Rule 2 — missing critical for node safety and CI delivery)
**Impact on plan:** All fixes necessary for correctness. Fixes align with RESEARCH pitfalls (4, 9) and Phase 13 ClusterRole pattern. No scope creep.

## Issues Encountered

- Chart v7.0.0 requires BOTH `monitoring.lokiCanary.enabled: false` AND top-level `lokiCanary.enabled: false` to suppress the canary DaemonSet — the RESEARCH example only showed the nested key. Caught during render inspection.
- `helm show values` showed `chunksCache.enabled: true` / `resultsCache.enabled: true` as chart defaults — not mentioned in RESEARCH but would have OOM'd the node immediately on apply.

## Threat Surface Scan

No new threat surface introduced beyond what was documented in the plan's threat model (T-15-01..SC). ClusterRole was stripped from 70-loki.yaml — cluster RBAC for Loki will be addressed in the bootstrap file when needed (Loki SingleBinary does not require ClusterRole for basic operation).

## Known Stubs

None — this plan is authoring only (Wave 1). Live behavior (Loki actually running, Alloy shipping logs) is validated in Wave 2 (15-04).

## Next Phase Readiness

- `70-loki.yaml` ready for apply in 15-04 (Wave 2)
- `loki-values.yaml` is the canonical render input — re-render with `helm template loki grafana/loki --version 7.0.0 --namespace monitoring --values k8s/observability/values/loki-values.yaml`
- `validate-phase-15.sh` ready to run after 15-04 applies the stack live
- Push URL for Alloy (15-02): `http://loki.monitoring.svc:3100/loki/api/v1/push`
- Prometheus scrape target for 15-03: `loki.monitoring.svc:3100`

---
*Phase: 15-log-stack*
*Completed: 2026-06-13*
