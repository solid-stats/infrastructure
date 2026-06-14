---
phase: quick-260614-ij3
plan: 01
subsystem: observability / error-tracking
tags: [kubernetes, networkpolicy, glitchtip, jobs, labels]
status: complete
requires:
  - 91-glitchtip.yaml (glitchtip ServiceAccount, web/worker pod-template labels)
  - 96-netpol-error-tracking.yaml (allow-glitchtip-db-egress / allow-glitchtip-postgres-ingress selectors)
provides:
  - glitchtip-migrate Job pods carrying netpol-matching labels
  - glitchtip-seed Job pods carrying netpol-matching labels
affects:
  - k8s/observability/92-glitchtip-migrate.yaml
  - k8s/observability/93-glitchtip-seed.yaml
tech-stack:
  added: []
  patterns:
    - pod labels sourced from template.metadata.labels (not Job-object metadata.labels)
key-files:
  created: []
  modified:
    - k8s/observability/92-glitchtip-migrate.yaml
    - k8s/observability/93-glitchtip-seed.yaml
decisions:
  - "Fix lives on the pods (add template.metadata.labels), not the NetworkPolicies — preserves NET-02 least-privilege"
metrics:
  duration: ~3m
  completed: 2026-06-14
  tasks: 1
  files: 2
requirements: [ERR-01, NET-02]
---

# Phase quick-260614-ij3 Plan 01: Fix GlitchTip migrate/seed Jobs blocked by NetworkPolicies Summary

Added `template.metadata.labels` (carrying `app.kubernetes.io/name: glitchtip`) to the GlitchTip `migrate` and `seed` Job pod templates so their pods match the additive-allow NetworkPolicies and can reach `glitchtip-postgres:5432`.

## What Was Done

- **Task 1** — Inserted a `template.metadata.labels` block above the pod `spec:` in both Job manifests, matching the 8-space-indented label style of the web/worker Deployments in 91-glitchtip.yaml:
  - 92-glitchtip-migrate.yaml: `app.kubernetes.io/name=glitchtip`, `component=migrate`, `part-of=solid-stats`
  - 93-glitchtip-seed.yaml: `app.kubernetes.io/name=glitchtip`, `component=seed`, `part-of=solid-stats`
  - Added one English comment above each `labels:` block documenting that `app.kubernetes.io/name: glitchtip` is the sole selector for `allow-glitchtip-db-egress` (egress to postgres:5432) and `allow-glitchtip-postgres-ingress`.

Root cause: pods inherit labels only from `template.metadata.labels`; the Job-object `metadata.labels` do not propagate to pods. Under the Phase 17 default-deny egress/ingress regime, the label-less migrate/seed pods were denied postgres access, so `pg_isready` / `showmigrations` never succeeded and the Jobs timed out.

## Verification

- `python3 scripts/validate-obs-manifests.py` → `=== obs manifest validation PASSED ===` (exit 0; priorityClassName, namespace, no-secret checks intact).
- `app.kubernetes.io/name: glitchtip` present at 8-space indent under `template.metadata.labels` in both manifests (migrate line 35, seed line 51).
- `git diff --stat` shows ONLY 92-glitchtip-migrate.yaml and 93-glitchtip-seed.yaml changed (10 insertions each).
- `git diff --quiet -- k8s/observability/96-netpol-error-tracking.yaml` → UNCHANGED (NET-02 least-privilege preserved).

Note: `grep -c 'app.kubernetes.io/name: glitchtip'` returns 3 per file, not 2 — the added comment line also contains the literal string. The load-bearing label line itself is present once at the correct 8-space indent (confirmed via `grep -nE '^        app.kubernetes.io/name: glitchtip$'`).

## Deviations from Plan

None - plan executed exactly as written.

## Re-deploy Note (orchestrator, outside this plan)

A Job's `spec` is immutable, so the currently blocked `glitchtip-migrate` (and any pending `glitchtip-seed`) Job must be deleted before re-apply:
`kubectl delete job glitchtip-migrate glitchtip-seed -n error-tracking --ignore-not-found`
so the edited templates take effect on a fresh Job. This plan only edited manifests.

## Commits

- `08da0aa`: fix(quick-260614-ij3): add pod-template labels to glitchtip migrate/seed Jobs

## Self-Check: PASSED

- FOUND: k8s/observability/92-glitchtip-migrate.yaml (template label present)
- FOUND: k8s/observability/93-glitchtip-seed.yaml (template label present)
- FOUND: commit 08da0aa
