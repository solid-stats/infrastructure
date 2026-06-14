# Phase 14: Public Edge & Grafana TLS - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Grafana is reachable over TLS at its public staging URL behind local-user auth via an
independent host-nginx obs-edge bootstrap, establishing the reusable edge pattern the
error-tracking vhost will later reuse.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Mirror the v2.0 Phase 07 edge pattern
A working host-nginx edge already exists on the staging VPS: `scripts/bootstrap-edge.sh`,
`scripts/teardown-edge.sh`, `scripts/validate-edge.py`, `docs/edge-bootstrap.md`, and live
nginx vhosts + certbot certs (e.g. `stats-staging.solid-stats.ru`). Phase 14 adds a dedicated
`bootstrap-obs-edge.sh` (adopt-reconcile, HTTP-first then certbot TLS) for the obs subdomains,
proxying Grafana's in-cluster ClusterIP — established as the reusable bootstrap the GlitchTip
`errors.` vhost extends in Phase 16.

### HARD external gate — DNS (EDGE-01) is operator-controlled
As of 2026-06-14, `grafana.solid-stats.ru` and `errors.solid-stats.ru`
do NOT resolve (parent `stats-staging.solid-stats.ru` → 89.223.124.200 exists). DNS A records
are operator/registrar-controlled — the agent cannot create them. certbot HTTP-01 (EDGE-03)
cannot issue until both resolve. Therefore: AUTHOR the bootstrap/vhost/validation/docs
autonomously; the live cert issuance + public-URL validation are an operator step gated on DNS.
Issue BOTH A records now (even though `errors.` is wired in Phase 16) to avoid Let's Encrypt
rate limits (Pitfall 9). Known edge caveat (operator memory): certbot full-renew can hang on the
auth cert — issue per-domain, not full-renew.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research (mirror scripts/bootstrap-edge.sh).

</code_context>

<specifics>
## Specific Ideas

Grafana runs as a ClusterIP Service in the `monitoring` namespace (Phase 13), admin/local-user
auth already enforced (no anonymous access). The edge only needs to proxy host:443 → Grafana
ClusterIP over TLS; Grafana's own auth covers MET-07's "local-user auth".

</specifics>

<deferred>
## Deferred Ideas

The `errors.` vhost upstream (GlitchTip) is wired in Phase 16 — only its DNS + cert are
provisioned here (rate-limit avoidance).

</deferred>
