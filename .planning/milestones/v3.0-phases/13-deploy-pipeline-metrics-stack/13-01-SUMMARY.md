---
phase: 13-deploy-pipeline-metrics-stack
plan: "01"
subsystem: observability
status: complete
tags: [observability, secrets, validation, ci]
completed: "2026-06-14"
duration_minutes: 5
tasks_completed: 3
files_created: 3
files_modified: 0

dependency_graph:
  requires: []
  provides:
    - scripts/render-obs-secrets.py
    - scripts/validate-obs-manifests.py
    - scripts/validate-phase-13.sh
  affects:
    - .github/workflows/deploy-observability.yml (Wave 2 — consumes render-obs-secrets.py)
    - scripts/validate-staging.py (Wave 3 — should add validate-obs-manifests.py to validate_scripts())

tech_stack:
  added: []
  patterns:
    - required()/secret() pattern from render-staging-secrets.py (mirrored exactly)
    - assert label/actual/expected helper from validate-phase-12.sh (mirrored exactly)
    - stdlib-only Python line scan (no PyYAML dependency)
    - || true capture-then-assert for kubectl commands whose exit code signals state

key_files:
  created:
    - scripts/render-obs-secrets.py
    - scripts/validate-obs-manifests.py
    - scripts/validate-phase-13.sh
  modified: []

decisions:
  - "Forbidden-token strings stored as Python variables not comments (T-13-03 discipline)"
  - "validate-obs-manifests.py exits 0 on absent k8s/observability so CI passes before Wave 1 manifests land"
  - "validate-phase-13.sh uses port 13000 for Grafana port-forward to avoid conflicts with common local Grafana"
  - "f-string slice syntax fixed for Python <3.12 compatibility (repr() + slice before interpolation)"

commits:
  - hash: aefb435
    message: "feat(13-01): add render-obs-secrets.py (DEP-04)"
  - hash: 5a802b0
    message: "feat(13-01): add validate-obs-manifests.py (static DEP-04 gate)"
  - hash: 19c1273
    message: "feat(13-01): add validate-phase-13.sh (live MET-01..06 harness)"
---

# Phase 13 Plan 01: Validation Scaffold & Obs Secret Renderer Summary

**One-liner:** Wave 0 gap-closure — obs secret renderer (DEP-04) + static manifest gate + live MET-01..06 bash harness, mirroring phase-12/render-staging patterns exactly.

## What Was Built

Three Wave 0 scripts that every later Phase 13 authoring plan commits against:

| Script | Purpose | Lines |
|--------|---------|-------|
| `scripts/render-obs-secrets.py` | Renders `grafana-secrets` + `postgres-monitor-secret` from env into Secret YAML; never commits values | 74 |
| `scripts/validate-obs-manifests.py` | Static CI gate: no secret values, namespace=monitoring, obs-background on all pod specs | 203 |
| `scripts/validate-phase-13.sh` | Live MET-01..06 assertion harness; `--quick` skips Grafana port-forward | 248 |

## Tasks

### Task 1 — render-obs-secrets.py (DEP-04)
Mirrors `render-staging-secrets.py` exactly: `required()` helper appends to `missing` list, `secret()` emits `stringData` YAML, exits 64 on missing env, prints `\n---\n`-joined documents. Emits:
- `grafana-secrets` key `admin-password` (consumed by Grafana chart `adminExistingSecret/adminPasswordKey`)
- `postgres-monitor-secret` key `dsn` (consumed by postgres-exporter `DATA_SOURCE_NAME`; uses `pg_monitor` non-superuser role)

DSN template: `postgresql://solid_monitor:{quote(pw)}@postgres.solid-stats-staging.svc:5432/solid_stats?sslmode=disable`

**Verified:** exits 64 with correct stderr on missing vars; emits valid YAML with both vars set.

### Task 2 — validate-obs-manifests.py (static gate)
Three checks via stdlib line scan (no PyYAML):
1. **No secret values** — detects populated `stringData`/`data` keys by credential name regex + long base64 heuristic
2. **Namespace** — every namespaced resource must declare `namespace: monitoring`
3. **PriorityClass** — every pod-bearing kind must carry `priorityClassName: obs-background`

Exits 0 with note when `k8s/observability/` absent (safe to run in CI before Wave 1). T-13-03: forbidden token patterns stored as module-level variables.

**Verified:** all three crafted violations (wrong-ns, missing-priorityClass, Secret-with-value) correctly exit 1.

### Task 3 — validate-phase-13.sh (live harness)
Mirrors `validate-phase-12.sh`: `assert label actual expected` helper, `--quick` flag gates port-forward section, `|| true` on commands whose exit code signals state.

| Check | Command |
|-------|---------|
| MET-01 pod Running | `kubectl get pod -l app.kubernetes.io/name=prometheus -o jsonpath .status.phase` |
| MET-01 retention | `kubectl exec deploy/prometheus-server -- wget /api/v1/status/config` contains `15d` |
| MET-02/03/04 targets | `wget /api/v1/targets` + python3 parse activeTargets per job |
| MET-03 pg_up | `wget /api/v1/query?query=pg_up` value == 1 |
| MET-04 rmq metric | `wget /api/v1/query?query=rabbitmq_identity_info` result non-empty |
| MET-05 datasource | port-forward 13000, curl Grafana `/api/datasources/1/health` status=OK |
| MET-06 dashboards | curl `/api/search?query=` count >= 4 |
| MET-06 panels | manual operator note only |

**Verified:** `bash -n` clean; all MET-01..MET-06 markers present; `--quick` gates port-forward.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python f-string slice syntax incompatible with Python < 3.12**
- **Found during:** Task 2 AST parse verification
- **Issue:** `f"...{line.strip()!r[:40]}..."` is invalid syntax before Python 3.12 (`!r` conversion followed by slice)
- **Fix:** Extracted `snippet = repr(line.strip()[:40])` before interpolation
- **Files modified:** `scripts/validate-obs-manifests.py`
- **Commit:** 5a802b0

## Known Stubs

None — this plan creates authoring-only scripts (no data flow to UI or live cluster).

## Threat Flags

None — scripts are authoring-only; no new network endpoints or trust boundaries introduced.

## Self-Check

- [x] `scripts/render-obs-secrets.py` exists (74 lines, > 40 min)
- [x] `scripts/validate-obs-manifests.py` exists (203 lines, > 40 min)
- [x] `scripts/validate-phase-13.sh` exists (248 lines, > 60 min)
- [x] Commits aefb435, 5a802b0, 19c1273 exist in git log
- [x] render-obs-secrets.py exits 64 on missing env, emits valid YAML with both set
- [x] validate-obs-manifests.py exits 0 on empty dir; exits 1 on wrong-ns/missing-pc/secret-value
- [x] validate-phase-13.sh passes bash -n; all MET-01..06 markers present

## Self-Check: PASSED
