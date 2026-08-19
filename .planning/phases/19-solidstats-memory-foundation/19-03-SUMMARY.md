---
phase: 19-solidstats-memory-foundation
plan: "03"
subsystem: isolated-memory-runtime
tags: [kubernetes, github-actions, prometheus, networkpolicy, qdrant]
dependency_graph:
  requires: [19-01, 19-02]
  provides: [memory-deploy-path, memory-observer, memory-prometheus-rules]
  affects: [20-memory-migration, solidstats-memory-cutover]
tech_stack:
  added: [standard-library Python observer]
  patterns: [exact-serviceaccount-gate, managed-ssh-pid, observer-owned-metrics]
key_files:
  created: [tests/test-memory-runtime-contract.py]
  modified:
    - .github/workflows/deploy-memory.yml
    - k8s/memory/50-monitoring.yaml
    - k8s/observability/10-prometheus.yaml
decisions:
  - Memory CD proves its exact namespace-scoped ServiceAccount before any mutation.
  - Prometheus consumes observer-owned metrics instead of undocumented application metrics.
metrics:
  duration: 20m
  completed: 2026-08-20
status: complete
actuals:
  tokens: 33400
  tasks: 3
  commits: 6
---

# Phase 19 Plan 03: Close CD and Monitoring Gaps Summary

The isolated memory boundary now has an authenticated deploy path and active
Prometheus coverage for MCP, Qdrant, snapshots, and PVC capacity.

## Accomplishments

- Added exact `memory-ci-deployer` identity and authorization checks before
  memory-only dry-run/apply operations.
- Added validated managed SSH tunnel lifecycle handling that preserves legacy
  no-argument callers.
- Added a restricted namespace-local observer that derives stable metrics from
  MCP and documented Qdrant HTTP endpoints.
- Added observer-only cross-namespace NetworkPolicies, Prometheus scrape jobs,
  recording rules, and alerts.
- Added offline regression tests and validator checks for the deployment and
  monitoring contracts.

## Task Commits

1. `b90a98f` — test(19-03): add memory deploy contract tests
2. `7530fd5` — feat(19-03): add scoped memory deployment path
3. `fdf857c` — fix(19-03): preserve tunnel helper executable mode
4. `094b976` — feat(19-03): add memory metrics observer
5. `6cae3d9` — feat(19-03): wire Prometheus memory monitoring

## Verification

- `timeout 30s python3 tests/test-memory-runtime-contract.py` — passed (8 tests).
- `timeout 10s python3 scripts/validate-memory-manifests.py`
  `--allow-operator-placeholders` — passed (26 resources).
- `timeout 10s python3 scripts/validate-obs-manifests.py` — passed.
- `timeout 10s python3 -m py_compile ...` — passed.
- `timeout 10s bash -n scripts/ssh-tunnel-up.sh` — passed.
- YAML parsing with PyYAML and `git diff --check` — passed.

## Deferred Operator UAT

Kube-router default-deny behavior remains unverified until an operator supplies
real substitutions and probes the live cluster. The required UAT must prove
that only Prometheus reaches observer TCP 9108, only the observer reaches
MCP/Qdrant, and all other relevant traffic is denied.

## Deviations from Plan

### Auto-fixed Issues

1. [Rule 1 - Bug] Restored executable mode on `scripts/ssh-tunnel-up.sh` after
   the managed-lifecycle rewrite.
   - Commit: `fdf857c`

2. [Unrun verification] The committed Prometheus manifest was synchronized with
   the authoritative values under the repository-local offline constraint. A
   fresh Helm rerender remains an operator/CI verification because the pinned
   chart was not fetched during this execution.

## Known Stubs

The remaining `MEMORY_OPERATOR_*` values are intentional fail-closed deployment
gates for real image digests, collection name, storage sizes, and network CIDRs.
They are rejected in strict rendered validation until supplied by the operator.

## Self-Check: PASSED

- All plan-owned runtime, observability, validator, workflow, and test files exist.
- All five task commits are present in Git history.
