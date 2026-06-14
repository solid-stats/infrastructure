---
phase: 16-error-tracking-glitchtip
plan: "01"
subsystem: error-tracking
status: complete
tags: [glitchtip, kubernetes, postgres, error-tracking, observability]
completed: "2026-06-14T00:40:58Z"
duration: "~3 minutes"

dependency_graph:
  requires:
    - "Phase 12 — error-tracking namespace + obs-ci-deployer RBAC"
    - "Phase 13 — obs-background PriorityClass"
  provides:
    - "k8s/observability/90-glitchtip-postgres.yaml — GlitchTip dedicated PostgreSQL StatefulSet"
    - "k8s/observability/91-glitchtip.yaml — GlitchTip web + worker Deployments + ClusterIP Service"
  affects:
    - "16-02 — migrate Job uses glitchtip-postgres.error-tracking.svc DNS from 90-glitchtip-postgres.yaml"
    - "16-03 — render-obs-secrets.py extension provides glitchtip-postgres-auth + glitchtip-secrets consumed here"
    - "16-03 — validate-obs-manifests.py extension unblocks static gate for error-tracking namespace"
    - "16-04 — live apply of these manifests; kubectl top tuning"
    - "16-05 — operator-gated nginx vhost cutover to glitchtip-web ClusterIP:8000"

tech_stack:
  added:
    - "glitchtip/glitchtip:v6.1.8 — Granian ASGI web + django-vtasks worker (no Celery/Redis)"
    - "postgres:17-alpine — GlitchTip's own dedicated DB, separate from app DB"
  patterns:
    - "PostgreSQL-only mode: VALKEY_URL='' disables Valkey/Redis via django-vtasks/vcache"
    - "SERVER_ROLE dispatch: single image, web vs worker via ./bin/start.sh + env var"
    - "StatefulSet mirrors k8s/staging/10-postgres.yaml pattern (headless Service + PVC template)"
    - "runAsNonRoot + drop-ALL securityContext + automountServiceAccountToken:false on all pods"

key_files:
  created:
    - k8s/observability/90-glitchtip-postgres.yaml
    - k8s/observability/91-glitchtip.yaml
  modified: []

decisions:
  - "GlitchTip postgres uid=70 (postgres Alpine default): set runAsUser/runAsGroup/fsGroup=70 + PGDATA subdir to avoid permission errors on first PVC bind"
  - "VALKEY_URL='' set explicitly on all containers (not absent) to prevent redis:// default in worker (Pitfall 3)"
  - "ENABLE_USER_REGISTRATION (not ENABLE_OPEN_USER_REGISTRATION) — v6 name; old name silently ignored (Pitfall 1)"
  - "readOnlyRootFilesystem omitted on postgres and glitchtip containers — both write runtime files"
  - "glitchtip Deployment omits runAsUser to let image default apply; runAsNonRoot:true enforced"
  - "Readiness probe: /api/0/config/ (returns 200 without auth, proves app+DB up; also verifies ERR-02)"
  - "kubectl apply --dry-run=client passes cleanly for all 7 resources"

metrics:
  tasks_total: 2
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 16 Plan 01: GlitchTip Workload Manifests Summary

**One-liner:** GlitchTip v6.1.8 PostgreSQL-only mode (VALKEY_URL="") with dedicated postgres StatefulSet (uid 70) and web/worker Deployments in error-tracking namespace, all secrets via secretKeyRef.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | GlitchTip dedicated PostgreSQL StatefulSet | faa15bb | k8s/observability/90-glitchtip-postgres.yaml |
| 2 | GlitchTip web + worker Deployments + Service | dd186ff | k8s/observability/91-glitchtip.yaml |

## What Was Built

### 90-glitchtip-postgres.yaml
Three-document YAML: ServiceAccount `glitchtip-postgres` + headless Service `glitchtip-postgres` + StatefulSet `glitchtip-postgres` — all in `error-tracking` namespace.

Key decisions:
- `postgres:17-alpine` uid 70; `runAsUser/runAsGroup/fsGroup: 70` + `PGDATA=/var/lib/postgresql/data/pgdata` (subdir avoids lost+found permission error on first PVC mount)
- `POSTGRES_PASSWORD` via `secretKeyRef: glitchtip-postgres-auth/POSTGRES_PASSWORD` — rendered by 16-03
- `pg_isready -U glitchtip -d glitchtip` readiness (5s initial, 10s period) + liveness (30s initial, 20s period)
- `automountServiceAccountToken: false`, `allowPrivilegeEscalation: false`, `capabilities drop ALL`
- `readOnlyRootFilesystem` intentionally omitted (postgres writes socket + pidfile to data dir)
- `obs-background` priorityClassName; 5Gi PVC `ReadWriteOnce`
- Resources: requests 100m/128Mi, limits 250m/256Mi (ASSUMED — tune in 16-04)

### 91-glitchtip.yaml
Four-document YAML: ServiceAccount `glitchtip` + ClusterIP Service `glitchtip-web:8000` + Deployment `glitchtip-web` + Deployment `glitchtip-worker`.

Web Deployment:
- `SERVER_ROLE=web`, `PORT=8000`, `command: ["./bin/start.sh"]`
- Readiness: `httpGet /api/0/config/:8000` (20s initial, 10s period) — proves app+DB up; verifiable for ERR-02
- Liveness: `httpGet /:8000` (60s initial, 30s period)
- Resources: requests 100m/192Mi, limits 300m/384Mi

Worker Deployment:
- `SERVER_ROLE=worker`, `command: ["./bin/start.sh"]`, no ports/HTTP probes
- Fallback commands documented in comments (Pitfall 4 / Assumption A1)
- Resources: requests 50m/128Mi, limits 200m/256Mi

Both Deployments share:
- `VALKEY_URL=""` explicit (Pitfall 3 guard — absent var defaults to redis://)
- `ENABLE_USER_REGISTRATION=False` (v6 name; NOT the old ENABLE_OPEN_USER_REGISTRATION — Pitfall 1)
- `DATABASE_URL` + `SECRET_KEY` via `secretKeyRef: glitchtip-secrets` (rendered by 16-03)
- `GLITCHTIP_DOMAIN`, `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `TRUSTED_PROXIES="*"`
- `GRANIAN_WORKERS=1`, `VTASKS_CONCURRENCY=2`, `DATABASE_POOL_MAX_SIZE=5`
- `runAsNonRoot: true`, `fsGroup: 1000`, `automountServiceAccountToken: false`
- `allowPrivilegeEscalation: false`, `capabilities drop ALL`

## Verification

```
kubectl apply --dry-run=client -f k8s/observability/90-glitchtip-postgres.yaml \
  -f k8s/observability/91-glitchtip.yaml
# → 7 resources created (dry run) — all parse cleanly

grep -q "namespace: error-tracking" + "priorityClassName: obs-background" + "automountServiceAccountToken: false"
# → all pass

python3 scripts/validate-obs-manifests.py
# → namespace:error-tracking errors expected (gate accepts only monitoring until 16-03 extends it)
# → no priorityClass / secret-value / ClusterRole errors
```

## Deviations from Plan

### Auto-added: PGDATA env var on postgres container
- **Found during:** Task 1
- **Issue:** `postgres:17-alpine` running as uid 70 with fsGroup 70 will fail on first startup if the PVC is mounted at `/var/lib/postgresql/data` directly — Postgres refuses to start in a directory that may contain a `lost+found` from the filesystem. Standard mitigation is setting `PGDATA` to a subdirectory.
- **Fix:** Added `PGDATA=/var/lib/postgresql/data/pgdata` env var (Rule 2 — missing critical correctness detail)
- **Files modified:** k8s/observability/90-glitchtip-postgres.yaml

None of the plan's core requirements were changed. This was an additive correctness fix.

## Known Stubs

None — no hardcoded empty values or placeholder data flows to UI rendering in these manifests.

## Threat Flags

No new threat surface beyond what the plan's `<threat_model>` covers. All T-16-0x mitigations implemented:
- T-16-01: `ENABLE_USER_REGISTRATION=False` on both web and worker
- T-16-02: all secrets via `secretKeyRef`; no literal values in YAML
- T-16-04: `automountServiceAccountToken: false` on all pods, dedicated SAs
- T-16-05: `runAsNonRoot: true` + `drop ALL` + `allowPrivilegeEscalation: false`

T-16-03 (cross-namespace postgres access) and T-16-SC (image trust) are accepted gaps per plan.

## Self-Check: PASSED

- FOUND: k8s/observability/90-glitchtip-postgres.yaml
- FOUND: k8s/observability/91-glitchtip.yaml
- FOUND: .planning/phases/16-error-tracking-glitchtip/16-01-SUMMARY.md
- FOUND commit: faa15bb (90-glitchtip-postgres.yaml)
- FOUND commit: dd186ff (91-glitchtip.yaml)
