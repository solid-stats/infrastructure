---
phase: 16-error-tracking-glitchtip
plan: "02"
subsystem: error-tracking
status: complete
tags: [glitchtip, kubernetes, jobs, migrate, seed, error-tracking, observability]
completed: "2026-06-14T00:46:30Z"
duration: "~6 minutes"

dependency_graph:
  requires:
    - "16-01 — glitchtip SA + glitchtip-secrets + glitchtip-postgres Service names"
    - "Phase 13 — obs-background PriorityClass"
    - "Phase 12 — error-tracking namespace + obs-ci-deployer RBAC"
  provides:
    - "k8s/observability/92-glitchtip-migrate.yaml — migrate Job (manage.py migrate) gated on postgres readiness"
    - "k8s/observability/93-glitchtip-seed.yaml — superuser seed Job (createsuperuser --noinput) gated on migrate completion"
  affects:
    - "16-03 — render-obs-secrets.py must emit GLITCHTIP_SUPERUSER_EMAIL/PASSWORD keys in glitchtip-secrets"
    - "16-04 — live apply of both Jobs in two waves; SERVER_ROLE/bin/start.sh confirmation; kubectl top tuning"

tech_stack:
  added: []
  patterns:
    - "One-shot Job with ttlSecondsAfterFinished:600 for idempotent re-apply"
    - "DB-level migrate gate via showmigrations poll (no kubectl wait, no extra RBAC — T-16-08)"
    - "pg_isready initContainer for postgres readiness before migrate (Pitfall 2 / Pattern 3)"
    - "VALKEY_URL='' explicit on every GlitchTip container (Pitfall 3 guard)"

key_files:
  created:
    - k8s/observability/92-glitchtip-migrate.yaml
    - k8s/observability/93-glitchtip-seed.yaml
  modified:
    - scripts/validate-obs-manifests.py

decisions:
  - "DB-poll migrate gate (showmigrations) instead of kubectl wait — avoids granting jobs/pods get verbs to glitchtip SA (T-16-08)"
  - "createsuperuser --noinput with DJANGO_SUPERUSER_* from secretKeyRef (A4 — standard Django pattern; GlitchTip email=USERNAME_FIELD compatible)"
  - "ttlSecondsAfterFinished:600 on both Jobs — auto-cleanup lets re-apply create a fresh Job without manual delete"
  - "SERVER_ROLE/bin/start.sh confirmation deferred to 16-04 live-apply (no docker in executor; manifest command bypasses start.sh entirely)"
  - "validate-obs-manifests.py extended to accept error-tracking alongside monitoring (Rule 3 — would have blocked verify step)"
  - "RBAC note: obs-ci-deployer in error-tracking has cronjobs verb but NOT jobs verb — operator must add batch/jobs verbs before 16-04 apply"

metrics:
  tasks_total: 2
  tasks_completed: 2
  files_created: 2
  files_modified: 1
---

# Phase 16 Plan 02: GlitchTip migrate Job + superuser seed Job Summary

**One-liner:** Two one-shot Kubernetes Jobs enforce ERR-01 first-run order: postgres-ready → migrate (92) → showmigrations DB poll → createsuperuser (93), all secrets via secretKeyRef, no extra RBAC.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | GlitchTip migrate Job + obs validator extension | ff78761 | k8s/observability/92-glitchtip-migrate.yaml, scripts/validate-obs-manifests.py |
| 2 | GlitchTip superuser seed Job | 71db18e | k8s/observability/93-glitchtip-seed.yaml |

## What Was Built

### 92-glitchtip-migrate.yaml

One-shot Job in `error-tracking` namespace:

- `initContainer wait-for-postgres`: `postgres:17-alpine` image, polls `pg_isready -h glitchtip-postgres.error-tracking.svc -U glitchtip` every 2 s (Pitfall 2 / Pattern 3)
- `container migrate`: `glitchtip/glitchtip:v6.1.8`, `command: ["./manage.py","migrate","--noinput"]` — called directly, does NOT depend on `bin/start.sh` / SERVER_ROLE dispatch
- `VALKEY_URL: ""` explicit (Pitfall 3); `DATABASE_URL` + `SECRET_KEY` via `secretKeyRef: glitchtip-secrets`
- `restartPolicy: Never`, `backoffLimit: 3`, `ttlSecondsAfterFinished: 600`
- `priorityClassName: obs-background`, `serviceAccountName: glitchtip`, `automountServiceAccountToken: false`
- `drop ALL` + `allowPrivilegeEscalation: false` + `runAsNonRoot: true` (pod-level); `readOnlyRootFilesystem` omitted (manage.py writes .pyc)
- Resources: requests 50m/128Mi, limits 200m/256Mi (ASSUMED A2 — tune in 16-04)

### 93-glitchtip-seed.yaml

One-shot Job in `error-tracking` namespace:

- `initContainer wait-for-migrate`: `glitchtip/glitchtip:v6.1.8` image, polls `./manage.py showmigrations` until all `[X]` and no `[ ]` — DB-level gate, no `kubectl wait`, no extra RBAC (T-16-08 mitigation)
  - Same `VALKEY_URL=""` + `DATABASE_URL` + `SECRET_KEY` env as main container
- `container seed`: `command: ["./manage.py","createsuperuser","--noinput"]`
  - `DJANGO_SUPERUSER_EMAIL` via `secretKeyRef: glitchtip-secrets/GLITCHTIP_SUPERUSER_EMAIL`
  - `DJANGO_SUPERUSER_PASSWORD` via `secretKeyRef: glitchtip-secrets/GLITCHTIP_SUPERUSER_PASSWORD`
  - `VALKEY_URL: ""`, `DATABASE_URL`, `SECRET_KEY` via secretKeyRef
- Same Job-level settings as migrate Job (restartPolicy, backoffLimit, ttl, priority, SA, securityContext, resources)
- Shell-based `create_superuser` fallback documented as comment in the file for 16-04 (Open Question #2 / Assumption A4)

### scripts/validate-obs-manifests.py (Rule 3 auto-fix)

Extended `_check_namespace` to accept `error-tracking` alongside `monitoring` as valid obs namespaces. Without this fix the validator would have rejected both Jobs (Pitfall 5). Change is backward-compatible: all existing `monitoring` manifests still pass.

## SERVER_ROLE / bin/start.sh Finding

**Status: Deferred to 16-04 (live-apply gate)**

The `bin/start.sh` + `SERVER_ROLE` dispatch (Assumption A1, Open Question #1) cannot be confirmed in an offline executor without docker or a live cluster connection. This finding is not a blocker for this plan because:

1. The migrate Job uses `command: ["./manage.py","migrate","--noinput"]` — bypasses `bin/start.sh` entirely; not affected by SERVER_ROLE.
2. The seed Job uses `command: ["./manage.py","createsuperuser","--noinput"]` — same bypass.
3. Only the web/worker Deployments (91-glitchtip.yaml, 16-01) depend on `bin/start.sh`; their fallback commands are already documented in comments.

**16-04 action required:** Before declaring web/worker pods healthy, inspect `bin/start.sh` inside the running container:
```bash
kubectl exec -n error-tracking deploy/glitchtip-web -- cat bin/start.sh
```
If `SERVER_ROLE` dispatch is absent, switch web to `command: ["python","-m","granian","glitchtip.asgi:application","--port","8000"]` and worker to `command: ["./manage.py","runworker","--scheduler"]`.

## RBAC Gap — operator action required before 16-04

`obs-ci-deployer` Role in `error-tracking` (01-obs-rbac.yaml) currently grants `batch/cronjobs` but **not** `batch/jobs`. The migrate and seed Jobs cannot be applied by CI until the operator adds `jobs` to the Role's `batch` resources list. This is an operator-bootstrap file (NOT CI-applied). Update before running 16-04.

Recommended addition to 01-obs-rbac.yaml (error-tracking Role, batch rule):
```yaml
  - apiGroups: ["batch"]
    resources: ["cronjobs", "jobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
```

## Verification

```
python3 scripts/validate-obs-manifests.py
# → ok: validated 19 manifest file(s) — PASSED

kubectl apply --dry-run=client \
  -f k8s/observability/92-glitchtip-migrate.yaml \
  -f k8s/observability/93-glitchtip-seed.yaml
# → job.batch/glitchtip-migrate created (dry run)
# → job.batch/glitchtip-seed created (dry run)

grep checks: manage.py migrate, pg_isready, priorityClassName obs-background (92) ✓
grep checks: createsuperuser, showmigrations, DJANGO_SUPERUSER_EMAIL (93) ✓
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] Extended validate-obs-manifests.py to accept error-tracking namespace**
- **Found during:** Task 1 verify step
- **Issue:** `_check_namespace` in `validate-obs-manifests.py` accepted only `monitoring`; both Jobs declare `error-tracking`, causing FAIL. This would have blocked the `grep -q "PASSED"` verify condition.
- **Fix:** Added `error-tracking` to `_ALLOWED_OBS_NAMESPACES` set in `_check_namespace`. Backward-compatible.
- **Files modified:** scripts/validate-obs-manifests.py (committed in ff78761)
- **Note:** This fix is a subset of what 16-03 was expected to do for the validator. 16-03 may still need to extend it for additional checks (secret rendering, etc.).

### Deferred to 16-04

- SERVER_ROLE / `bin/start.sh` live confirmation (no docker in executor)
- `kubectl top` resource tuning for both Jobs (ASSUMED A2 values used)
- RBAC gap: `batch/jobs` verb missing from obs-ci-deployer Role in error-tracking (operator action)

## Known Stubs

None — no hardcoded empty values or placeholder data. All secret values are `secretKeyRef` references.

## Threat Flags

No new threat surface beyond the plan's `<threat_model>`. All mitigations implemented:
- T-16-06: `DJANGO_SUPERUSER_EMAIL/PASSWORD` via `secretKeyRef` only; no inline values
- T-16-07: showmigrations DB poll blocks createsuperuser until all migrations applied
- T-16-08: DB-level poll (no `kubectl wait`) — no `jobs/pods get` verbs added to glitchtip SA
- T-16-09: `automountServiceAccountToken: false` on both Jobs

## Self-Check: PASSED

- FOUND: k8s/observability/92-glitchtip-migrate.yaml
- FOUND: k8s/observability/93-glitchtip-seed.yaml
- FOUND: scripts/validate-obs-manifests.py (modified)
- FOUND commit: ff78761 (migrate Job + validator)
- FOUND commit: 71db18e (seed Job)
