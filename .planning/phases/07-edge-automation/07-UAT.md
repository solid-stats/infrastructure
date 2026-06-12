---
status: testing
phase: 07-edge-automation
source: [07-VERIFICATION.md]
started: 2026-06-13T00:00:00Z
updated: 2026-06-13T00:00:00Z
---

## Current Test

number: 1
name: nginx config syntax validation on live VPS
expected: |
  After `ADMIN_EMAIL=... scripts/bootstrap-edge.sh`, `nginx -t` reports
  "syntax is ok" and "test is successful".
awaiting: user response

## Tests

### 1. nginx config syntax validation
expected: After bootstrap, `nginx -t` → "syntax is ok" / "test is successful" (live certs at /etc/letsencrypt/live/stats-staging.solid-stats.ru/).
result: [pending]

### 2. certbot renewal pipeline (dry-run)
expected: `certbot renew --dry-run` → "all simulated renewals succeeded" (ACME webroot + deploy-hook reload nginx).
result: [pending]

### 3. systemd OnFailure= drop-in wiring
expected: `systemctl show -p OnFailure certbot.service` shows certbot-renew-failure.service; a forced failure writes user.crit to journald.
result: [pending]

### 4. ufw split-tunnel rule (wg0 → 6443)
expected: `ufw status verbose` shows `6443 on wg0 ALLOW IN` (interface-qualified), and no blanket 6443 exposure.
result: [pending]

### 5. live TLS + upstream reachability
expected: `curl -I https://stats-staging.solid-stats.ru/` → valid TLS handshake, HSTS header, response from server-2 upstream (10.43.94.103:3000).
result: [pending]

### 6. teardown reversibility proof
expected: `scripts/teardown-edge.sh` restores the pre-adoption edge state (.bak vhost restored or repo-identical vhost removed, drop-in/hook/ufw rule removed) with no broken nginx; re-running bootstrap reproduces the adopted state (idempotency).
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
