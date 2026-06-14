---
phase: 16-error-tracking-glitchtip
plan: "05"
subsystem: error-tracking
status: complete
tags: [glitchtip, nginx, edge, tls, cutover, error-tracking, err-03]
completed: "2026-06-14T09:55:00Z"
duration: "~15 minutes (live)"

dependency_graph:
  requires:
    - "16-04 — live GlitchTip (glitchtip-web ClusterIP) + closed registration"
    - "Phase 14 — errors. TLS cert lineage + obs-edge bootstrap pattern + DNS apex record"
  provides:
    - "Public TLS URL https://errors.solid-stats.ru serving GlitchTip (ERR-03 public path)"
    - "bootstrap-obs-edge.sh domain-aware upstream discovery (grafana + errors)"
  affects:
    - "18 — app SDK PRs can POST to the public errors. ingest endpoint"

key_files:
  modified:
    - config/nginx/sites-available/errors-stats-staging-solid-stats.conf
    - scripts/bootstrap-obs-edge.sh

commits:
  - "82973ee feat(16-05): cut errors. edge over to GlitchTip ClusterIP (live)"

metrics:
  requirements_verified: [ERR-03]
---

# Phase 16 Plan 05: errors. Public Edge Cutover Summary

**One-liner:** Flipped the Phase 14 `errors.solid-stats.ru` 503 placeholder into a GlitchTip
reverse proxy and ran the cutover live — the public URL now serves the GlitchTip login over the
reused Phase 14 TLS cert, registration closed.

## What Changed

- **errors vhost** (`config/nginx/sites-available/errors-stats-staging-solid-stats.conf`):
  removed the `return 503;` placeholder location; added `upstream glitchtip_obs { server
  UPSTREAM_PLACEHOLDER; keepalive 8; }` and a `location /` reverse proxy with
  Host/X-Real-IP/X-Forwarded-* headers, `proxy_http_version 1.1`, sane timeouts, and
  `client_max_body_size 25m` (Sentry envelopes can exceed nginx's 1m default). Cert lineage,
  HSTS, and the ssl includes are untouched (Phase 14 reuse).
- **bootstrap-obs-edge.sh**: upstream discovery (Step 3) is now domain-aware — `errors.*`
  resolves `kubectl get svc glitchtip-web -n error-tracking`, `grafana.*` path unchanged. The
  existing generic `UPSTREAM_PLACEHOLDER` sed substitution handles both vhosts.

## Live Cutover (done — DNS + cert already in place)

The plan marked the cutover operator-gated because, at authoring time, the `errors.` DNS did not
resolve. By execution it did (operator created the apex A record in Phase 14, cert issued then),
so the cutover was performed live over SSH:

```
dig +short errors.solid-stats.ru  -> 89.223.124.200
cert lineage                      -> present (Phase 14)
glitchtip-web ClusterIP           -> 10.43.31.151:8000
bootstrap-obs-edge.sh             -> installed TLS vhost, nginx -t ok, reloaded
```

Smoke test:
```
curl -I https://errors.solid-stats.ru/   -> HTTP/2 200 (GlitchTip login, 28671 B, x-frame-options: DENY)
/api/settings/                           -> version 6.1.8, enableUserRegistration:False, enableOrganizationCreation:False
/_health/                                -> 200
validate-phase-16.sh --public            -> ERR-01/02/03 PASS (ERR-02 against public URL; forced error appeared)
```

The repo is not checked out on the edge VPS, so the bootstrap ran from a temp copy
(`/tmp/obs-edge/`) of `scripts/` + `config/` — REPO_ROOT-relative paths resolved correctly.

## Notes / minor

- `nginx -t` emits benign `protocol options redefined for [::]:443` warnings because both the
  grafana and errors vhosts use `listen 443 ssl http2;` — pre-existing (grafana already had it),
  harmless. A future cleanup could switch to the `http2 on;` directive to silence it.
- The `.bak` of the live errors vhost (the 503 placeholder) is preserved at
  `/etc/nginx/sites-available/errors-stats-staging-solid-stats.conf.bak` for rollback.

## Self-Check: PASSED

- vhost proxies to `glitchtip_obs`, no `return 503` left; bootstrap discovers the GlitchTip
  ClusterIP for `errors.*`; grafana path + cert-only fallback unchanged; `bash -n` clean.
- Public URL returns 200 over valid TLS with registration closed.
- Commit 82973ee present.
