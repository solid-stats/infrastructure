---
phase: 14-public-edge-grafana-tls
plan: "04"
subsystem: host-edge-live
status: complete
tags: [live, nginx, certbot, tls, edge-01, edge-02, edge-03, met-07]

dependency_graph:
  requires: ["14-01", "14-02", "14-03"]
  provides:
    - "grafana.solid-stats.ru live over TLS, proxying the in-cluster Grafana"
    - "errors.solid-stats.ru cert pre-issued + 503 placeholder vhost (GlitchTip wired in Phase 16)"
  affects:
    - "live staging VPS: nginx vhosts + Let's Encrypt certs for grafana./errors.solid-stats.ru"
    - config/nginx/sites-available/*
    - scripts/bootstrap-obs-edge.sh

key_files:
  modified:
    - scripts/bootstrap-obs-edge.sh
    - config/nginx/sites-available/grafana-stats-staging-solid-stats.conf
    - config/nginx/sites-available/errors-stats-staging-solid-stats.conf

decisions:
  - "Public hostnames are grafana.solid-stats.ru / errors.solid-stats.ru (apex, matching the operator's existing auth./relay. convention), NOT the planner's longer grafana.stats-staging.solid-stats.ru. The operator created the apex A records; the authored config (vhosts, validator, runbook, requirements) was renamed to match."
  - "Both certs issued now (grafana live; errors placeholder) to avoid Let's Encrypt rate limits — errors. upstream is wired in Phase 16."
  - "vhost filenames keep the *-stats-staging-* name (internal artifact); server_name + cert paths use the short hostnames. Cosmetic-only inconsistency."

requirements: [EDGE-01, EDGE-02, EDGE-03, MET-07]
---

# Plan 14-04 — Live Public Edge (operator gate, completed with operator present)

## What is live (verified)

- `https://grafana.solid-stats.ru/login` → **HTTP 200**, valid Let's Encrypt cert
  (CN=grafana.solid-stats.ru, expires 2026-09-12), nginx proxies to the in-cluster Grafana
  ClusterIP (10.43.192.173:80) behind Grafana's own local-user login (MET-07).
- `https://errors.solid-stats.ru/` → **HTTP 503** placeholder, valid cert (CN=errors.solid-stats.ru) —
  the upstream is swapped to GlitchTip in Phase 16.
- certbot deploy hook (nginx reload on renewal) + OnFailure drop-in installed; ufw already open (Phase 07).

## Defects found and fixed during the live bring-up

1. **Hostname mismatch** — the operator created `grafana.solid-stats.ru` / `errors.solid-stats.ru`
   (apex), but the authored config used `*.stats-staging.solid-stats.ru`. Renamed all references to
   the operator's actual records.
2. **bootstrap-obs-edge.sh UPSTREAM bug** — the TLS-vhost install `cp`'d the repo vhost verbatim,
   leaving `UPSTREAM_PLACEHOLDER` in place → nginx `host not found in upstream`. Fixed to
   `sed UPSTREAM_PLACEHOLDER → <discovered ClusterIP>` on install (both the lineage and post-cert paths).
3. **config/systemd not transferred** — the deploy-hook/OnFailure step needs config/systemd/; transferred
   and re-ran (idempotent) to install the hooks.

## Requirements
- EDGE-01 both A records resolve to 89.223.124.200. ✓
- EDGE-02 obs-edge bootstrap serves HTTP→TLS, proxies Grafana ClusterIP (reusable for errors.). ✓
- EDGE-03 per-domain certbot certs issued + served (never full-renew). ✓
- MET-07 Grafana reachable at the public HTTPS URL behind local-user auth. ✓
