---
status: testing
phase: 19-solidstats-memory-foundation
source: [19-VERIFICATION.md]
started: 2026-08-20
updated: 2026-08-20
---

# Phase 19 Operator Verification

## Current Test

number: 1
name: kube-router policy enforcement
expected: |
  Every documented permitted path works, while all non-allowed ingress and
  egress traffic is denied.
awaiting: operator evidence

## Tests

### 1. kube-router policy enforcement

expected: Render approved values in an isolated cluster and prove the documented
observer, Qdrant, Prometheus, host-nginx, DNS, and denied traffic paths.
result: pending

### 2. Pinned-chart render parity

expected: Render Prometheus chart v29.11.0 in the approved networked environment
and confirm the observer jobs, node-volume job, recording rules, and alerts match
the committed manifest.
result: passed
observed: A fresh Helm v29.11.0 render is byte-identical to the committed
  manifest. Memory alerts load from `data.alerting_rules.yml` and recording
  rules load from `data.recording_rules.yml`.

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

- truth: The committed Prometheus manifest is an exact render of pinned chart
  v29.11.0 and loads the memory alert rules through the chart-owned key.
  status: resolved
  reason: Plan 19-05 mechanically regenerated the manifest and added offline
    source/render ownership checks; fresh Helm parity now passes.
