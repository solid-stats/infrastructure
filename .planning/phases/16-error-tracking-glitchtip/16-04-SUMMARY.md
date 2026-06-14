---
phase: 16-error-tracking-glitchtip
plan: "04"
subsystem: error-tracking
status: complete
tags: [glitchtip, kubernetes, live-deploy, error-tracking, observability, err-01, err-02, err-03]
completed: "2026-06-14T09:40:00Z"
duration: "~70 minutes (live)"

dependency_graph:
  requires:
    - "16-01/02/03 — GlitchTip manifests, Jobs, validator, ingest harness, deploy pipeline"
    - "Phase 12 — error-tracking namespace + obs-ci-deployer RBAC (live)"
    - "Phase 13 — obs-background PriorityClass"
  provides:
    - "Live GlitchTip 6.1.8 in error-tracking: postgres + web + worker Running, migrate+seed done"
    - "org=solidstats / project=staging / PROJECT_ID=1 / ProjectKey (DSN public key) — handoff for Phase 18"
    - "Green validate-phase-16.sh --internal (ERR-01/02/03 all PASS, incl. issue appearance)"
  affects:
    - "16-05 — errors. public TLS cutover reuses GlitchTip ClusterIP"
    - "18 — app SDK PRs consume the project DSN"

tech_stack:
  added: []
  patterns:
    - "Live SSH-to-node kubectl apply in first-run order (postgres -> web/worker+migrate -> seed)"
    - "manage.py shell model-level org/project/DSN creation (REST org API gated by enableOrganizationCreation=false)"
    - "Sentry envelope ingest authenticated by ?sentry_key= query param"

key_files:
  modified:
    - k8s/observability/90-glitchtip-postgres.yaml
    - k8s/observability/91-glitchtip.yaml
    - k8s/observability/92-glitchtip-migrate.yaml
    - k8s/observability/93-glitchtip-seed.yaml
    - scripts/validate-phase-16.sh
    - scripts/test-glitchtip-ingest.sh
    - docs/glitchtip.md

commits:
  - "321238e fix(16-04): GlitchTip manifests for live v6.1.8 deploy"
  - "75df7c2 fix(16-04): GlitchTip validation scripts + runbook for v6 live behavior"

metrics:
  requirements_verified: [ERR-01, ERR-02, ERR-03]
---

# Phase 16 Plan 04: Live GlitchTip Deploy + ERR-01/02/03 Summary

**One-liner:** GlitchTip 6.1.8 deployed live into `error-tracking`, migrate+seed in first-run
order, org/project/DSN created, forced Sentry error ingested and visible as an issue —
`validate-phase-16.sh --internal` green for ERR-01/02/03. Eight Wave-1 assumptions were wrong
and got corrected against live behavior.

## What's Live

```
glitchtip-postgres-0   1/1 Running   (own PostgreSQL, no Valkey/Redis)
glitchtip-web          1/1 Running   (Granian, SERVER_ROLE=web)
glitchtip-worker       1/1 Running   (runworker --scheduler, SERVER_ROLE=worker)
migrate Job  -> Complete (migrate + createcachetable)
seed Job     -> Complete ("Superuser created successfully")
```

DSN handoff (non-secret client key): `http://<ProjectKey.public_key>@errors.solid-stats.ru/1`
— org `solidstats`, project `staging`, PROJECT_ID `1`. The full DSN public key is recorded in
the live cluster ProjectKey; not committed. Phase 18 wires it via a `SENTRY_DSN` secret per app.

## Wave-1 Assumptions Corrected Live (root-caused, not patched blindly)

| # | Assumed | Reality (verified live) | Fix |
|---|---------|------------------------|-----|
| 1 | image `glitchtip/glitchtip:v6.1.8` | `v`-prefix dropped after v6.0.3 → 404 | tag `6.1.8` |
| 2 | runAsNonRoot + no uid OK | image user `app` is uid/gid **5000**, named not numeric → `CreateContainerConfigError` | `runAsUser/Group: 5000` on all glitchtip-image pods; migrate init keeps uid 70 |
| 3 | readiness `/api/0/config/` | 404 in v6 | probes → `/_health/`; config → `/api/settings/` |
| 4 | ERR-02 key `user_registration_enabled` | v6 key is camelCase `enableUserRegistration` at `/api/settings/` | validator updated |
| 5 | reg closed shows false immediately | reports `true` while **0 users** (first-user bootstrap) | seed first, then assert — `Django setting was False the whole time` |
| 6 | migrate is enough | PostgreSQL-only cache needs `django_cache` table or worker consumer crashes → queue never drains | migrate Job runs `createcachetable`; restart worker on existing clusters |
| 7 | envelope `dsn` header authenticates ingest | returns 403; real SDKs use `?sentry_key=` | ingest harness appends `?sentry_key=PUBLIC_KEY` |
| 8 | REST org-creation API | gated by `enableOrganizationCreation=false` | create org/team/project/DSN via `manage.py shell` model calls |

## bin/start.sh / SERVER_ROLE finding (A1 — RESOLVED)

`bin/start.sh` **does** dispatch on `SERVER_ROLE`: `web → bin/run-web.sh` (Granian),
`worker → bin/run-worker.sh` (`exec ./manage.py runworker --scheduler`, which processes
`VTASKS_QUEUES = ["default","ingest"]` + the scheduler). No command fallback needed — the
manifests keep `command: ["./bin/start.sh"]`.

## createsuperuser path (A4 — RESOLVED)

Standard `createsuperuser --noinput` with `DJANGO_SUPERUSER_EMAIL/PASSWORD` from the Secret
worked — GlitchTip's email-as-USERNAME_FIELD user model is compatible. The shell fallback
documented in 93 was not needed.

## kubectl top — right-size (before → after)

| Pod | Observed | Old limits | New limits | Action |
|-----|----------|-----------|-----------|--------|
| postgres | 66Mi / 77m | 256Mi / 250m | unchanged | fit |
| web | 198Mi / 57m | 384Mi / 300m | unchanged | fit (request 192Mi ≈ observed) |
| worker | 118Mi / **200m (pegged at limit)** | 256Mi / 200m | 256Mi / **500m**, req cpu 50m→100m | raise CPU ceiling so ingest isn't throttled |

Node after deploy: 64% mem (5116Mi/8GB), 69% CPU — comfortable headroom; GlitchTip total ~382Mi.

## ERR proof

- **ERR-01**: postgres/web/worker Running, no Valkey/Redis, migrate+seed Complete, `VALKEY_URL=""` live.
- **ERR-02**: `/api/settings/ → enableUserRegistration:false` (after seed); registration POST → 404.
- **ERR-03**: forced Sentry envelope POST → HTTP 200 → worker processed → issue
  `"Phase 16 forced test error …"` visible (`appeared after 1 poll`). 2 issues / 2 events in DB.

## Operator / follow-up notes

- 4 `GLITCHTIP_*` secrets set in the GitHub `staging` environment (values generated, never in git).
- A full-scope `phase16` APIToken exists in the cluster for validation re-runs (Phase 17). It is a
  live credential, not committed; operators may delete + regenerate it. Phase 18 needs only the DSN.
- `ALLOWED_HOSTS` is the wildcard default (warning in logs) — acceptable for internal/port-forward;
  consider restricting to `errors.solid-stats.ru` during the 16-05 public cutover.

## Self-Check: PASSED

- Live pods Running; migrate+seed Complete; no Valkey/Redis.
- validate-phase-16.sh --internal → "Phase 16 validation PASSED" (ERR-01/02/03).
- Forced error visible as a GlitchTip issue.
- Commits 321238e + 75df7c2 present.
