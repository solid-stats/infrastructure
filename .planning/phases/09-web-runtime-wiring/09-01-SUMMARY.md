---
phase: 09-web-runtime-wiring
plan: "01"
subsystem: k8s-staging
tags: [kubernetes, web, staging, wiring]
status: complete

dependency_graph:
  requires: []
  provides: [web-k8s-slot]
  affects: [scripts/validate-staging.py, .github/workflows/deploy-staging.yml]

tech_stack:
  added: []
  patterns:
    - "0-replica placeholder Deployment with registry.k8s.io/pause:3.9 for image-pending workloads"

key_files:
  created:
    - k8s/staging/36-web.yaml
    - k8s/staging/37-web-deployment.yaml
  modified:
    - scripts/validate-staging.py
    - .github/workflows/deploy-staging.yml

decisions:
  - "Used registry.k8s.io/pause:3.9 as placeholder image: inert (no ports/code), invisible to GHCR pin check, future swap is one-line (image + replicas)"
  - "replicas: 0 ensures zero pod scheduling — rollout status exits 0 immediately (0/0 desired)"
  - "web entry added to EXPECTED_WORKLOADS with long_running: True; probes defined in manifest satisfy the safety check"
  - "APP_IMAGES unchanged — pause placeholder must not be checked for GHCR pinning"

metrics:
  duration: "~10 minutes"
  completed: "2026-06-13"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 2
---

# Phase 9 Plan 01: web Runtime Wiring Summary

Conventions-compliant Kubernetes slot for the future `web` app: 0-replica pause-placeholder Deployment, wired into validation and rollout-status gate.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Create web manifests (ConfigMap + Service + SA + Deployment) | 35e73c0 | k8s/staging/36-web.yaml, k8s/staging/37-web-deployment.yaml |
| 2 | Wire web into validate-staging.py and deploy-staging.yml | d2bae35 | scripts/validate-staging.py, .github/workflows/deploy-staging.yml |

## Verification

`python3 scripts/validate-staging.py` exits 0, all six checks pass:
```
ok: script syntax
ok: manifest shape
ok: drill manifest safety
ok: workload safety
ok: app image pins
ok: rendered secret structure
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

The Deployment is intentionally stubbed at `replicas: 0` with `registry.k8s.io/pause:3.9`. This is by design (WEB-02): the slot exists but no pod runs until the real web image is published. Activation requires only:
1. Set `replicas: N` in `k8s/staging/37-web-deployment.yaml`
2. Replace `image: registry.k8s.io/pause:3.9` with `image: ghcr.io/solid-stats/web@sha256:<digest>`

No other manifest changes required.

## Threat Flags

No new trust boundaries beyond those in the plan's threat model. T-09-01 through T-09-05 mitigations are all present in the manifests.

## Self-Check: PASSED

- k8s/staging/36-web.yaml: exists
- k8s/staging/37-web-deployment.yaml: exists
- Commit 35e73c0: exists
- Commit d2bae35: exists
