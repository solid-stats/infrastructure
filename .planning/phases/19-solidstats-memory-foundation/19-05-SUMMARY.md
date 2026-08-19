---
phase: 19-solidstats-memory-foundation
plan: "05"
subsystem: observability-prometheus-contract
tags: [prometheus, helm, kubernetes, offline-validation, tdd]
requires:
  - phase: 19-04
    provides: backup CronJob-derived memory monitoring contract
provides:
  - A byte-identical pinned Helm render for the deployed Prometheus manifest.
  - Fail-closed ownership checks for memory rule ConfigMap data keys.
affects: [19-verification, 20-local-corpus-migration, 21-restore-cutover-recovery]
tech-stack:
  added: []
  patterns: [pinned-helm-render-parity, chart-owned-rule-files, offline-semantic-validation]
key-files:
  created: []
  modified:
    - k8s/observability/10-prometheus.yaml
    - scripts/validate-obs-manifests.py
    - tests/test-memory-runtime-contract.py
decisions:
  - The chart-owned alerting_rules.yml and recording_rules.yml files are the only accepted homes for SolidStats memory rules.
  - Helm serialization order and line wrapping are normalized semantically, while rule declarations and expressions remain exact.
metrics:
  duration: 25m
  completed: 2026-08-20
status: complete
actuals:
  tokens: 5489
  tasks: 2
  commits: 2
---

# Phase 19 Plan 05: Prometheus Rule-File Contract Summary

Pinned Prometheus v29.11.0 output now loads every memory alert and recording
rule from its chart-owned ConfigMap files.

## Accomplishments

- Replaced the deployed manifest with stdout from the exact pinned Helm
  template command.
- Added offline ConfigMap extraction scoped to `prometheus-server` and its
  consumed files.
- Enforced exact declaration sets, source/render expressions, and the
  CronJob-derived selector.
- Added semantic source/render, wrong-key, duplicate, missing-rule, and
  drift coverage.

## Verification

<!-- markdownlint-disable MD013 -->

- `timeout 30s python3 tests/test-memory-runtime-contract.py` — passed, 16 tests.
- `timeout 10s python3 scripts/validate-obs-manifests.py` — passed, 22 manifest files validated.
- `timeout 10s python3 -m py_compile scripts/validate-obs-manifests.py tests/test-memory-runtime-contract.py` — passed.
- `timeout 10s git diff --check -- k8s/observability/10-prometheus.yaml scripts/validate-obs-manifests.py tests/test-memory-runtime-contract.py` — passed.
- Fresh `helm template prometheus prometheus-community/prometheus --version 29.11.0 --namespace monitoring --values k8s/observability/values/prometheus-values.yaml` plus `cmp -s` — passed byte-for-byte.

<!-- markdownlint-enable MD013 -->

## TDD Gate Compliance

- RED: `fb96a58` added ownership tests; the old `alerting_rules.yml` was empty.
- GREEN: `31419c4` regenerated the manifest and added the offline validator.

## Decisions Made

- Rule declarations belong only in `alerting_rules.yml` or `recording_rules.yml`.
- Chart-default `rules` and `alerts` are allowed only without memory definitions.
- Rule maps are semantic, so Helm wrapping and key order do not create false failures.

## Deviations from Plan

### Auto-fixed Issues

1. [Rule 1 - Bug] Normalized Helm multiline expressions and reordered mappings.
   - **Found during:** Task 1
   - **Issue:** Text matching rejected valid chart v29.11.0 expression wrapping.
   - **Fix:** Compare parsed mappings and normalized expressions with exact ownership.
   - **Files modified:** Validator and runtime contract tests.
   - **Commit:** `31419c4`

## Deferred Operator Gates

- kube-router enforcement remains pending isolated-cluster operator evidence.

## Self-Check: PASSED

- All three implementation artifacts exist.
- RED commit `fb96a58` and GREEN commit `31419c4` exist in Git history.
- The generated manifest has fresh byte-for-byte parity with the pinned Helm render.
