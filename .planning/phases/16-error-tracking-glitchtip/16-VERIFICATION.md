---
phase: 16-error-tracking-glitchtip
status: passed
verified: "2026-06-14"
method: live (staging k3s + public edge; validate-phase-16.sh --internal AND --public green)
requirements: [ERR-01, ERR-02, ERR-03]
note: Backfilled during the v3.0 milestone audit — the phase shipped + was live-proven in 16-04/16-05 (see those SUMMARYs); this records the verification artifact.
---

# Phase 16 Verification — PASSED

| # | Success criterion | Evidence | Verdict |
|---|-------------------|----------|---------|
| 1 | GlitchTip runs with its own PostgreSQL (PostgreSQL-only, Valkey/Redis disabled) following the strict first-run order (migrate → close registration → create superuser) | glitchtip-postgres + web + worker Running; no valkey/redis; migrate Job (migrate + createcachetable) then seed Job ("Superuser created successfully"); `VALKEY_URL=""` live | ✓ ERR-01 |
| 2 | Self-registration disabled; only the seeded superuser can log in | `/api/settings/ → enableUserRegistration:false` (after seed); registration POST → 404; superuser logs in | ✓ ERR-02 |
| 3 | errors.solid-stats.ru serves GlitchTip over valid TLS; a project + DSN exist and a forced test error appears | org `solidstats`/project `staging`/PROJECT_ID 1/DSN issued; forced Sentry envelope → 200 → worker processed → issue visible; `curl -I https://errors.solid-stats.ru/` → 200 (non-502) | ✓ ERR-03 |

`scripts/validate-phase-16.sh` ran green in BOTH `--internal` and `--public` modes, and again as part of
`validate-stack.sh` after the Phase 17 NetworkPolicies were applied (forced error still ingested + visible).

Eight Wave-1 assumptions were corrected against live behavior (image tag `6.1.8` no `v`-prefix; uid 5000;
`createcachetable`; `/api/settings/`; first-user registration caveat; `?sentry_key=` ingest auth;
worker-cache-crash; org/project via manage.py shell) — see 16-04-SUMMARY.md.

Evidence: `16-04-SUMMARY.md`, `16-05-SUMMARY.md`, `docs/glitchtip.md`.
