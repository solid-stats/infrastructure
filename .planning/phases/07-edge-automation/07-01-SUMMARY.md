---
phase: "07-edge-automation"
plan: 1
subsystem: edge
tags: [nginx, vhost, validator, offline-ci, tls, edge-automation]
dependency_graph:
  requires: []
  provides:
    - scripts/validate-edge.py
    - config/nginx/sites-available/stats-staging-solid-stats.conf
  affects:
    - scripts/validate-staging.py
tech_stack:
  added:
    - Python 3 stdlib (re, subprocess, pathlib, sys) — offline validator
    - nginx vhost config (named upstream, certbot TLS includes, http2)
  patterns:
    - Offline structural validation (same style as validate-staging.py)
    - Named upstream block as Phase 11 cutover lever
    - ACME webroot location separated from proxy_pass
key_files:
  created:
    - scripts/validate-edge.py
    - config/nginx/sites-available/stats-staging-solid-stats.conf
  modified:
    - scripts/validate-staging.py
decisions:
  - "D-1: vhost filename kept as stats-staging-solid-stats.conf matching live host exactly"
  - "D-2: certbot-managed includes (options-ssl-nginx.conf, ssl-dhparams.pem) — no hand-rolled ssl_protocols"
  - "D-3: real ClusterIP 10.43.94.103:3000 used as upstream, not 127.0.0.1 placeholder"
  - "Validator checks named upstream, http2 on 443 listen, CUTOVER marker, interface-qualified ufw rule literal"
metrics:
  duration: "150s"
  completed: "2026-06-13"
  tasks: 2
  files: 3
status: complete
---

# Phase 07 Plan 01: Offline Edge Validator + nginx Vhost Summary

**One-liner:** Offline validator (validate-edge.py) for all five EDGE-* artifact checks + verbatim nginx vhost mirror (named upstream solid_stats_staging_server2 → 10.43.94.103:3000, certbot TLS includes, http2, CUTOVER marker).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Offline edge validator — scripts/validate-edge.py | ca6a0a8 | scripts/validate-edge.py, scripts/validate-staging.py |
| 2 | nginx vhost verbatim mirror | d80780c | config/nginx/sites-available/stats-staging-solid-stats.conf |

## What Was Built

### scripts/validate-edge.py
Five offline validation functions covering EDGE-01..05 structural checks:
1. `validate_nginx_vhost()` — checks 12 structural properties of the vhost config including named upstream, real ClusterIP, keepalive, proxy_pass, ACME path, HTTP redirect, TLS cert paths, certbot includes, HSTS, CUTOVER marker, and http2 on 443 listen directives
2. `validate_shell_scripts()` — bash -n syntax check + `set -euo pipefail` + `exit 64` marker + deploy hook validation
3. `validate_systemd_units()` — drop-in shape (OnFailure=certbot-renew-failure.service), failure handler unit ([Unit]+[Service]+ExecStart+logger+user.crit)
4. `validate_bootstrap_idempotency_markers()` — mkdir -p, ln -sf, backup step, exact `ufw allow in on wg0 to any port 6443` literal, ufw 80/443, nginx -t, letsencrypt/live lineage guard
5. `validate_teardown_script()` — rm -f/unlink, bak/restore, systemctl disable, ufw delete

Also added `py_compile.compile('scripts/validate-edge.py')` call to `validate_scripts()` in validate-staging.py so CI catches syntax errors in the edge validator itself.

### config/nginx/sites-available/stats-staging-solid-stats.conf
Verbatim mirror of `/etc/nginx/sites-available/stats-staging-solid-stats.conf` on the live VPS:
- Named upstream block `solid_stats_staging_server2 { server 10.43.94.103:3000; keepalive 16; }` — the Phase 11 cutover lever is this single server line, marked `# CUTOVER:`
- HTTP server block: ACME `/.well-known/acme-challenge/` → `/var/www/html` (static, NOT proxy_pass), `return 301` redirect
- HTTPS server block: `listen 443 ssl http2` + `listen [::]:443 ssl http2` (mirrors live vhost exactly per FIX 5), certbot-managed `include /etc/letsencrypt/options-ssl-nginx.conf` + `ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem`, HSTS `max-age=31536000; includeSubDomains`

## Verification Results

All checks passed:
- `python3 -c "import py_compile; py_compile.compile('scripts/validate-edge.py', doraise=True)"` → exit 0
- `python3 scripts/validate-staging.py` → all 5 checks OK (py_compile for validate-edge.py passes)
- All grep checks on the vhost file: solid_stats_staging_server2, 10.43.94.103:3000, CUTOVER:, options-ssl-nginx.conf, 443 ssl http2, Strict-Transport-Security, .well-known/acme-challenge, return 301

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new threat surface introduced. The vhost file is a static config stored in the repo; it contains no secrets, no auth headers, and no credentials. The CUTOVER marker comment on the upstream server line is the intended mechanism for Phase 11. All items from the plan's `<threat_model>` are addressed:

- T-7-01-01: `# CUTOVER:` marker present; HSTS checked by validator
- T-7-01-02: ACME location block uses `root /var/www/html`, not `proxy_pass`
- T-7-01-03: HSTS header present and checked by validator
- T-7-01-04: Only stats-staging vhost captured; no relay/auth/default vhosts
- T-7-01-SC: No package installs; stdlib Python only

## Self-Check: PASSED

- FOUND: scripts/validate-edge.py
- FOUND: config/nginx/sites-available/stats-staging-solid-stats.conf
- FOUND: commit ca6a0a8 (Task 1)
- FOUND: commit d80780c (Task 2)
