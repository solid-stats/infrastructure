---
phase: 14-public-edge-grafana-tls
plan: "02"
subsystem: infra
tags: [nginx, tls, grafana, certbot, websocket, hsts, vhost]

requires:
  - phase: 14-01
    provides: bootstrap-obs-edge.sh that installs these vhosts
  - phase: 13-deploy-pipeline-metrics-stack
    provides: Grafana ClusterIP Service in monitoring namespace (port 80)

provides:
  - Grafana public TLS vhost with WebSocket-capable proxy to obs ClusterIP (UPSTREAM_PLACEHOLDER token)
  - errors. placeholder TLS vhost returning 503 (no upstream; Phase 16 wires GlitchTip)

affects:
  - 14-03 (offline validator checks exact structure of these two files)
  - 14-04 (operator runbook references these vhosts)
  - 16 (GlitchTip phase re-runs bootstrap with errors. vhost wired to real upstream)

tech-stack:
  added: []
  patterns:
    - "nginx named-upstream UPSTREAM_PLACEHOLDER token: bootstrap sed-substitutes runtime ClusterIP; repo never stores hardcoded IP"
    - "WebSocket upgrade pair (Upgrade + Connection upgrade) in Grafana proxy block for Grafana Live"
    - "errors. placeholder vhost: return 503 only, no upstream block — avoids nginx startup failure on missing backend (RESEARCH Pitfall 7)"

key-files:
  created:
    - config/nginx/sites-available/grafana-stats-staging-solid-stats.conf
    - config/nginx/sites-available/errors-stats-staging-solid-stats.conf
  modified: []

key-decisions:
  - "UPSTREAM_PLACEHOLDER token in grafana vhost upstream block — sed-substituted by bootstrap-obs-edge.sh at install time; offline validator (14-03) asserts no hardcoded ClusterIP"
  - "WebSocket upgrade headers (Upgrade + Connection upgrade) in Grafana proxy block — Grafana Live requires them; harmless if Live disabled"
  - "errors. vhost: return 503 only in HTTPS location / — no upstream block, no proxy_pass prevents nginx reload failure when GlitchTip does not yet exist (Pitfall 7)"
  - "Both vhosts mirror stats-staging-solid-stats.conf exactly: head comment, named upstream, HTTP ACME+301 block, HTTPS certbot TLS + HSTS + proxy block"

patterns-established:
  - "Pattern: vhost upstream block uses substitutable placeholder token; bootstrap discovers and injects runtime IP"
  - "Pattern: placeholder vhost for cert-pre-issued domain returns 503 with no upstream until the real backend is deployed"

requirements-completed: [EDGE-02, MET-07]

duration: 2min
completed: 2026-06-14
status: complete
---

# Phase 14 Plan 02: Grafana TLS Proxy Vhost + errors. 503 Placeholder Vhost Summary

**Two nginx vhost templates: Grafana TLS+WebSocket reverse proxy to ClusterIP with UPSTREAM_PLACEHOLDER token, and errors. TLS placeholder returning 503 pending Phase 16 GlitchTip wiring.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-14T05:04:02Z
- **Completed:** 2026-06-14T05:06:02Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Grafana vhost: named upstream `grafana_obs` with `UPSTREAM_PLACEHOLDER` token (sed-substituted by bootstrap-obs-edge.sh), HTTP ACME+redirect block, HTTPS TLS block with HSTS and WebSocket upgrade headers (Grafana Live)
- errors. vhost: same TLS/ACME structure but `location / { return 503; }` only — no upstream, no proxy_pass (prevents nginx reload failure per RESEARCH Pitfall 7)
- Both mirror `stats-staging-solid-stats.conf` structure exactly (head comment, keepalive upstream, certbot includes, HSTS)

## Task Commits

1. **Task 1: Grafana public TLS vhost with WebSocket proxy** - `167d27c` (feat)
2. **Task 2: errors. placeholder TLS vhost returning 503** - `3094127` (feat)

## Files Created/Modified

- `config/nginx/sites-available/grafana-stats-staging-solid-stats.conf` — TLS vhost: grafana_obs upstream (UPSTREAM_PLACEHOLDER), HTTP ACME+301, HTTPS TLS+HSTS+WebSocket proxy
- `config/nginx/sites-available/errors-stats-staging-solid-stats.conf` — TLS placeholder: HTTP ACME+301, HTTPS TLS+HSTS, location / returns 503

## Decisions Made

- `UPSTREAM_PLACEHOLDER` as the sed token: allows the offline validator (14-03) to assert no hardcoded IP is present, and lets bootstrap-obs-edge.sh do a single `sed -i` substitution
- `proxy_set_header Connection "upgrade"` (not `""`) for Grafana: WebSocket upgrade path required for Grafana Live streaming; standard keepalive (`Connection ""`) is correct for non-WS upstreams (stats-staging) but not for Grafana
- `return 503` with no upstream block for errors.: cleanest approach per RESEARCH Pitfall 7; avoids nginx upstream resolution failure at reload time

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed `proxy_pass` word from comment in errors. vhost**
- **Found during:** Task 2 verification (`! grep -q "proxy_pass"` check)
- **Issue:** Plan verification asserts `! grep -q "proxy_pass"` — the comment `# No upstream, no proxy_pass` caused the check to fail
- **Fix:** Reworded comment to `# No upstream wired — Phase 16 replaces this block with the GlitchTip reverse-proxy`
- **Files modified:** config/nginx/sites-available/errors-stats-staging-solid-stats.conf
- **Verification:** `! grep -q "proxy_pass"` passes after fix
- **Committed in:** 3094127 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug: comment text broke grep assertion)
**Impact on plan:** Trivial wording fix; no functional change to vhost behavior.

## Issues Encountered

None beyond the comment grep fix above.

## Threat Surface Scan

No new trust boundaries introduced beyond those in the plan's threat model. Both files are static config templates; no network endpoints exist until bootstrap-obs-edge.sh installs them on the VPS. T-14-05 through T-14-08 are all addressed:

- T-14-05 (Grafana info disclosure): Grafana's own local-user auth enforced; no nginx-level auth layer
- T-14-06 (HTTP downgrade): `return 301` in HTTP block + HSTS on both vhosts
- T-14-07 (nginx reload failure): errors. uses `return 503` only, no upstream block
- T-14-08 (hardcoded ClusterIP): `UPSTREAM_PLACEHOLDER` token in grafana vhost; validator (14-03) rejects bare IPs

## Next Phase Readiness

- 14-03 (offline structural validator) can now run checks against both vhost files
- 14-04 (operator runbook) can reference the exact file paths and placeholder token
- Phase 16 (GlitchTip): re-run bootstrap-obs-edge.sh with `DOMAIN=errors.stats-staging.solid-stats.ru UPSTREAM=<glitchtip-clusterip>:80` to wire the real upstream

---
*Phase: 14-public-edge-grafana-tls*
*Completed: 2026-06-14*
