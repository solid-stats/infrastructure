---
phase: 16
slug: error-tracking-glitchtip
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-14
---

# Phase 16 — Validation Strategy

> GlitchTip in error-tracking ns. Internal deploy + forced-error test are autonomous (port-forward);
> the public errors. TLS cutover is operator-gated on DNS (Phase 14 obs-edge).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Static** | `validate-obs-manifests.py`-style (namespace=error-tracking, obs-background, no secrets); a `validate-phase-16.sh` live harness |
| **Live** | `scripts/validate-phase-16.sh` (created Wave 0) |

---

## Per-Requirement Verification Map

| Req | Behavior | Type | Check |
|-----|----------|------|-------|
| ERR-01 | GlitchTip own PostgreSQL Running (separate from app DB), postgres-only (no Valkey/Redis pod) | live | glitchtip-postgres pod Running in error-tracking; no redis/valkey workload; web env `VALKEY_URL=""` |
| ERR-01 | first-run order migrate → close-registration → create-superuser | live | migrate Job Completed before web Ready; superuser exists; web up |
| ERR-01 | GlitchTip web + worker Running | live | glitchtip-web + glitchtip-worker pods Running |
| ERR-02 | self-registration disabled | live | `GET /api/0/config/` → `user_registration_enabled:false`; POST register → rejected |
| ERR-02 | only seeded superuser can log in | live | superuser login succeeds; no open signup |
| ERR-03 | project + DSN exist | live | org/project seeded; DSN retrievable (management cmd / API w/ superuser) |
| ERR-03 | forced test error appears | live | POST a synthetic Sentry envelope to the ingest endpoint (port-forward ClusterIP) → the issue appears via API query |
| ERR-03 | public errors. TLS | OPERATOR | swap errors. vhost 503→GlitchTip ClusterIP, re-run bootstrap-obs-edge.sh (cert exists); curl https://errors.… (DNS-gated) |

---

## Wave 0 Requirements

- [ ] `scripts/validate-phase-16.sh` — live ERR-01..03 (pods, registration-closed, project/DSN, forced-error appears)
- [ ] obs secret renderer extended for GlitchTip (SECRET_KEY, DATABASE_URL/pg password, DJANGO_SUPERUSER_*) — no values in git
- [ ] confirm GlitchTip `bin/start.sh` SERVER_ROLE dispatch (image bootstrap check) with command fallback

---

## Manual / Operator-Gated

| Behavior | Req | Why | Instructions |
|----------|-----|-----|--------------|
| Public errors. URL over TLS | ERR-03 | DNS A record operator-controlled (not resolving yet) | operator creates DNS, swaps errors. vhost upstream, re-runs bootstrap-obs-edge.sh; the Phase 14 cert is reused |

---

## Security

- GlitchTip secrets (SECRET_KEY, DB password, superuser password) from env → k8s Secrets only.
- Registration CLOSED from first boot (ENABLE_USER_REGISTRATION=False) — no open signup window.
- Own PostgreSQL, isolated from the app DB; error-tracking ns; NetworkPolicy isolation in Phase 17.
- ClusterIP only until the operator does the public cutover.

---

## Validation Sign-Off

- [ ] GlitchTip web+worker+own-postgres Running, postgres-only (no Redis), registration closed, superuser-only
- [ ] project+DSN exist; forced test error appears (internal ingest)
- [ ] static gate green; `nyquist_compliant: true` once plans wire all checks
- [ ] public errors. cutover documented as operator step

**Approval:** pending
