---
phase: quick-260614-hvq
plan: 01
subsystem: observability-cd
status: complete
tags: [rbac, observability, ci-deploy, validator]
requires:
  - k8s/staging/01-obs-rbac.yaml (operator-bootstrap RBAC file)
  - scripts/validate-obs-manifests.py (obs static gate)
provides:
  - Green obs CD apply (no 403 on namespaced roles/rolebindings)
  - Validator coverage forbidding all RBAC kinds in k8s/observability/
affects:
  - .github/workflows/deploy-observability.yml (Apply obs manifests step)
key-files:
  modified:
    - k8s/observability/40-postgres-exporter.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/staging/01-obs-rbac.yaml
    - scripts/validate-obs-manifests.py
decisions:
  - "Move empty namespaced Role/RoleBinding out of CI-applied obs dir into operator-bootstrap, not widen obs-ci-deployer (CI self-escalation rejected)"
  - "Validator forbids namespaced RBAC in obs dir alongside cluster RBAC so future helm re-render fails CI before breaking deploy"
metrics:
  duration: 8m
  completed: 2026-06-14
  tasks: 3
  files: 4
---

# Phase quick-260614-hvq Plan 01: Fix obs CD — move empty namespaced Role/RoleBinding Summary

Moved two empty, helm-rendered namespaced Role+RoleBinding pairs (postgres-exporter, grafana) out of the CI-applied `k8s/observability/` glob into the operator-bootstrap `k8s/staging/01-obs-rbac.yaml`, and extended the validator to forbid namespaced RBAC there — eliminating the 403 that turned the obs CD red without widening the least-privilege deployer Role.

## What Changed

- **Task 1** (`42b8cb2`): Removed the postgres-exporter Role+RoleBinding from `40-postgres-exporter.yaml` and the grafana Role+RoleBinding (`rules: []`) from `50-grafana.yaml`, cleanly dropping the `---` separators. Both files flow correctly (SA→Service, PVC→Service); Deployments and `serviceAccountName` references untouched.
- **Task 2** (`4c9c4c4`): Appended both pairs verbatim to `01-obs-rbac.yaml` (after the grafana ClusterRoleBinding), each preceded by an operator-applied banner tailored to namespaced RBAC and preserving the `# Source:` helm comments + chart labels. The `obs-ci-deployer` Role is unchanged — no roles/rolebindings verbs added.
- **Task 3** (`36b03fc`): Added `Role`/`RoleBinding` to `_FORBIDDEN_OBS_KINDS` and generalized the comment, `_check_no_clusterrole` docstring, and error message to cover namespaced RBAC. A future re-render that reintroduces RBAC into `k8s/observability/` now fails CI.

## Verification

1. `python3 scripts/validate-obs-manifests.py` → exit 0, "obs manifest validation PASSED" (22 files).
2. `grep -rE '^kind: (Role|RoleBinding)$' k8s/observability/` → no matches.
3. `grep -cE '^kind: (Role|RoleBinding)$' k8s/staging/01-obs-rbac.yaml` → 8 (≥4; both new pairs plus pre-existing matches).
4. `obs-ci-deployer` Role rules byte-identical (diff HEAD~3..HEAD shows no roles/rolebindings verb changes).
5. PyYAML parse of `01-obs-rbac.yaml` succeeds (multi-doc load, no error).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- Files modified exist: 40-postgres-exporter.yaml, 50-grafana.yaml, 01-obs-rbac.yaml, validate-obs-manifests.py — all present.
- Commits exist: 42b8cb2, 4c9c4c4, 36b03fc — confirmed in git log.
