# Phase 16: Error Tracking (GlitchTip) - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

GlitchTip captures errors with its own PostgreSQL and closed registration, is reachable over TLS
at its public staging URL on the reused obs-edge bootstrap, and a forced staging test error is
visible with a project DSN issued for the app-SDK track.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Deploy into error-tracking namespace, reuse the obs secret/deploy pattern
GlitchTip runs in the `error-tracking` namespace (created in Phase 12, with its own obs-ci-deployer
RBAC), `priorityClassName: obs-background`, TIGHT limits. Manifests are helm-rendered (or
hand-authored) into `k8s/observability/` (or a sibling dir) and applied via the obs deploy path.
Secrets (Django SECRET_KEY, GlitchTip postgres password, superuser email/password) are rendered
from env into k8s Secrets (extend render-obs-secrets.py or a sibling renderer) — no values in git.

### Own PostgreSQL, separate from the app DB (ERR-01)
GlitchTip gets its OWN PostgreSQL StatefulSet in error-tracking — NOT the app's
solid-stats-staging postgres. PostgreSQL-only mode: GlitchTip 4.x can use Postgres as the
Celery broker/result backend, so Valkey/Redis is disabled. Components: web (gunicorn), worker
(celery), beat (scheduler), migrate (one-shot), + the dedicated postgres.

### Strict first-run order (ERR-01)
migrate → close registration → create superuser. ENABLE_OPEN_USER_REGISTRATION=false (ERR-02).
The superuser is seeded non-interactively (env-driven createsuperuser / management command), and
self-registration is disabled so only that superuser can log in.

### Public errors. URL is DNS-gated (operator) — like Phase 14
ERR-03's public TLS (`errors.solid-stats.ru`) reuses the Phase 14 obs-edge bootstrap
(errors. vhost placeholder already authored; just swap the 503 for GlitchTip's ClusterIP and
issue the cert). The DNS A record does NOT resolve yet (operator-controlled). So: AUTHOR + deploy
GlitchTip internally (ClusterIP) and run the forced-error test via port-forward / the internal DSN
(ClusterIP) — autonomous. The public errors. vhost cutover + cert is the operator step (DNS-gated).

</decisions>

<code_context>
## Existing Code Insights

Mirror Phase 13/15 obs pipeline (helm-render or hand-authored manifests, render-obs-secrets.py for
secrets, validate-obs-manifests.py static gate). The Phase 14 errors. vhost placeholder + obs-edge
bootstrap already exist for the public cutover.

</code_context>

<specifics>
## Specific Ideas

ERR-03 acceptance: a project + DSN exist and a deliberately forced test error appears in GlitchTip.
Internally provable: port-forward the GlitchTip web Service, create an org/project (or seed via
management command), grab the DSN, POST a synthetic Sentry event to the ingest endpoint
(ClusterIP), confirm it appears. Node headroom is tight (~2.6Gi) — GlitchTip web+worker+beat+postgres
must run with tight limits.

</specifics>

<deferred>
## Deferred Ideas

App-side Sentry SDK wiring (using this DSN) is Phase 18 (separate app-repo PRs). GlitchTip
application-log ingestion is explicitly out of scope (errors only; logs live in Loki).

</deferred>
