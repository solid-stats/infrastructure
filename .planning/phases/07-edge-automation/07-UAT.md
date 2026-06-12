---
status: testing
phase: 07-edge-automation
source: [07-VERIFICATION.md]
started: 2026-06-13T00:00:00Z
updated: 2026-06-13T00:00:00Z
---

## Current Test

number: 2
name: certbot renewal pipeline (dry-run) — requires bootstrap (deploy-hook install)
expected: |
  After bootstrap installs the deploy-hook, `certbot renew --dry-run` reports
  "all simulated renewals succeeded".
awaiting: bootstrap (mutating step, deferred — read-only verification only so far)

## Tests

### 1. nginx config syntax validation
expected: After bootstrap, `nginx -t` → "syntax is ok" / "test is successful" (live certs at /etc/letsencrypt/live/stats-staging.solid-stats.ru/).
result: [partial — verified read-only 2026-06-13 @ root@89.223.124.200] Live `nginx -t` on the EXISTING config = "syntax is ok / test is successful" (warnings only from operator-owned sg-stats-relay.conf, not ours). The repo vhost was found to have DRIFTED from live (dropped X-Forwarded-Host header; proxy_connect_timeout 5s→60s) — reconciled in commit 03521f5 so the repo mirror == live + intended HSTS. Full post-bootstrap `nginx -t` still pending the bootstrap (mutating) step.

### 2. certbot renewal pipeline (dry-run)
expected: `certbot renew --dry-run` → "all simulated renewals succeeded" (ACME webroot + deploy-hook reload nginx).
result: [pending — requires bootstrap] Live cert lineage `stats-staging.solid-stats.ru` exists and is VALID (56 days). The repo deploy-hook is NOT yet installed on the host (read-only scope). Run after bootstrap.

### 3. systemd OnFailure= drop-in wiring
expected: `systemctl show -p OnFailure certbot.service` shows certbot-renew-failure.service; a forced failure writes user.crit to journald.
result: [pending — requires bootstrap] Confirmed read-only that the drop-in is NOT yet present (`OnFailure=` empty, no certbot.service.d, no certbot-renew-failure.service). Run after bootstrap.

### 4. ufw split-tunnel rule (wg0 → 6443)
expected: `ufw status verbose` shows `6443 on wg0 ALLOW IN` (interface-qualified), and no blanket 6443 exposure.
result: [PASS — verified read-only 2026-06-13] `ufw status verbose` shows `6443/tcp on wg0 ALLOW IN # k3s API via WireGuard` (both v4 and v6, interface-qualified). No blanket 6443 exposure. Rule already present from Phase 6 operator bootstrap. wg0 up (10.8.0.1/24).

### 5. live TLS + upstream reachability
expected: `curl -I https://stats-staging.solid-stats.ru/` → valid TLS handshake, HSTS header, response from server-2 upstream (10.43.94.103:3000).
result: [PASS (TLS+upstream) — verified read-only 2026-06-13] `curl -I https://stats-staging.solid-stats.ru/` → HTTP/2, TLS handshake ok, `application/json` 404 from the server-2 upstream (the app's own response). Note: HSTS header is NOT present on the live edge yet (live vhost lacks add_header HSTS); it will appear only after bootstrap applies the repo vhost. TLS + http2 + upstream proxy proven.

### 6. teardown reversibility proof
expected: `scripts/teardown-edge.sh` restores the pre-adoption edge state (.bak vhost restored or repo-identical vhost removed, drop-in/hook/ufw rule removed) with no broken nginx; re-running bootstrap reproduces the adopted state (idempotency).
result: [pending — requires bootstrap] Cannot be proven without first running bootstrap (mutating). Deferred.

## Summary

total: 6
passed: 2
issues: 0
pending: 3
partial: 1
skipped: 0
blocked: 0

## Gaps

### G-1 (RESOLVED): repo vhost drifted from live "verbatim mirror"
status: resolved
found: 2026-06-13 during live read-only verification
detail: |
  The repo config/nginx/sites-available/stats-staging-solid-stats.conf was NOT a
  byte-faithful mirror of the live /etc/nginx/sites-available/stats-staging-solid-stats.conf.
  Two unintended deviations: (1) dropped `proxy_set_header X-Forwarded-Host $host`
  (live sends it to server-2 — a cross-app proxy-contract regression), (2)
  `proxy_connect_timeout` 5s→60s. The HSTS add_header is an INTENDED addition per
  EDGE must_haves (live lacks it). Running bootstrap as-was would have silently
  removed X-Forwarded-Host from the live edge.
resolution: commit 03521f5 — restored X-Forwarded-Host and connect_timeout 5s; kept HSTS. Repo now == live + intended HSTS. validate-edge.py still exit 0.
