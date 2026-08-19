---
phase: 19-solidstats-memory-foundation
plan: "04"
subsystem: memory-network-and-monitoring-contracts
tags: [kubernetes, networkpolicy, prometheus, cronjob, offline-validation]
requires:
  - phase: 19-03
    provides: memory observer, Prometheus rules, and offline contract tests
provides:
  - Exact reciprocal observer-to-MemPalace ingress under namespace default deny.
  - Backup-CronJob-derived snapshot alert validation across source and render.
affects: [19-verification, 20-local-corpus-migration, 21-restore-cutover-recovery]
tech-stack:
  added: []
  patterns: [exact-policy-spec-gate, manifest-derived-prometheus-selector]
key-files:
  created: []
  modified:
    - k8s/memory/30-network-policy.yaml
    - k8s/observability/values/prometheus-values.yaml
    - k8s/observability/10-prometheus.yaml
    - scripts/validate-memory-manifests.py
    - scripts/validate-obs-manifests.py
    - tests/test-memory-runtime-contract.py
key-decisions:
  - Observer ingress remains a distinct same-namespace NetworkPolicy rather than sharing host-nginx CIDR evidence.
  - Snapshot alert identity is extracted from the sole backup CronJob instead of duplicated in monitoring code.
requirements-completed: [ISO-04, OPS-04]
coverage:
  - id: D1
    description: Exact reciprocal observer-to-MemPalace TCP 8765 NetworkPolicy path.
    requirement: ISO-04
    verification:
      - kind: unit
        ref: tests/test-memory-runtime-contract.py#MemoryObserverContractTests
        status: pass
      - kind: other
        ref: scripts/validate-memory-manifests.py --allow-operator-placeholders
        status: pass
    human_judgment: false
  - id: D2
    description: Snapshot alert selector derived from the sole memory backup CronJob in source and render.
    requirement: OPS-04
    verification:
      - kind: unit
        ref: tests/test-memory-runtime-contract.py#PrometheusMemoryContractTests
        status: pass
      - kind: other
        ref: scripts/validate-obs-manifests.py
        status: pass
    human_judgment: false
actuals:
  tokens: 4383
  tasks: 2
  commits: 1
metrics:
  duration: 15m
  completed: 2026-08-19
status: complete
---

# Phase 19 Plan 04: Close Network and Snapshot Contract Gaps Summary

Observer MCP probing has an exact reciprocal TCP 8765 path. Snapshot freshness
follows the backup CronJob declared in the memory manifest.

## Accomplishments

- Added an Ingress-only MemPalace policy that admits only the labeled observer
  on TCP 8765.
- Made the memory validator fail closed on a changed observer ingress or
  broadened observer egress policy.
- Bound source and committed Prometheus snapshot alerts to the sole backup
  CronJob and enforced source/render parity.
- Added parsed YAML regression tests for policy breadth, reciprocal flow,
  missing or duplicate CronJobs, and alert selector drift.

## Verification

- `timeout 30s python3 tests/test-memory-runtime-contract.py` — passed (15 tests).
- `timeout 10s python3 scripts/validate-memory-manifests.py`
  `--allow-operator-placeholders` — passed (27 resources).
- `timeout 10s python3 scripts/validate-obs-manifests.py` — passed (22 manifests).
- `timeout 10s python3 -m py_compile scripts/validate-memory-manifests.py`
  `scripts/validate-obs-manifests.py tests/test-memory-runtime-contract.py` —
  passed.
- PyYAML parse and `git diff --check` — passed.

## Decisions Made

- Kept observer ingress separate from host-nginx ingress so the unverified
  kube-router CIDR stays independently operator-gated.
- Used the sole parsed CronJob name as the monitoring selector source of truth.
  Source-only or render-only selector drift now fails offline.

## Deviations from Plan

### Auto-fixed Issues

1. [Rule 1 - Bug] Corrected the RED test's authoritative values parser.
   - **Found during:** Task 2
   - **Issue:** Helm values already deserialize `alerting_rules.yml` as a
     mapping, not a YAML string.
   - **Fix:** Inspected the parsed structure and consumed the mapping directly.
   - **Files modified:** `tests/test-memory-runtime-contract.py`
   - **Verification:** The full 15-test suite passes.

## Deferred Operator Gates

- Kube-router runtime enforcement remains unverified: an operator must prove
  the observer-to-MemPalace TCP 8765 allowance and all declared denials with
  real network substitutions.
- Fresh pinned-chart Helm render parity remains unverified: an approved
  networked CI/operator context must render chart v29.11.0 and compare it with
  committed `10-prometheus.yaml`.

## Self-Check: PASSED

- All six implementation files exist and were changed only within plan ownership.
- Required offline tests, validators, compilation, YAML parsing, and whitespace
  checks passed.
