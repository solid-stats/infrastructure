---
status: complete
phase: 07-edge-automation
source: [07-VERIFICATION.md]
started: 2026-06-13T00:00:00Z
updated: 2026-06-13T01:15:00Z
---

## Current Test

number: 6
name: all live verification complete
expected: all 6 items verified on the live VPS
awaiting: none — all passed 2026-06-13 @ root@89.223.124.200

## Tests

### 1. nginx config syntax validation
expected: After bootstrap, `nginx -t` → "syntax is ok" / "test is successful" (live certs at /etc/letsencrypt/live/stats-staging.solid-stats.ru/).
result: [PASS — 2026-06-13 @ root@89.223.124.200] After `bootstrap-edge.sh`, `nginx -t` = "syntax is ok / test is successful" (warnings only from operator-owned sg-stats-relay.conf, not ours). Repo vhost drift (dropped X-Forwarded-Host; connect_timeout 5s→60s) was found and fixed (commit 03521f5) BEFORE applying, so the adopted vhost == live + intended HSTS.

### 2. certbot renewal pipeline (dry-run)
expected: `certbot renew --dry-run` → "all simulated renewals succeeded" (ACME webroot + deploy-hook reload nginx).
result: [PASS — 2026-06-13] `certbot renew --cert-name stats-staging.solid-stats.ru --dry-run` → "Congratulations, all simulated renewals succeeded: /etc/letsencrypt/live/stats-staging.solid-stats.ru/fullchain.pem (success)". HTTP-01 webroot challenge served from /var/www/html/.well-known/acme-challenge/ via our vhost. NOTE: the *unscoped* `certbot renew --dry-run` hangs on the operator-owned `auth.solid-stats.ru` cert (relay/auth vhost — outside Phase 7 scope, §D); the Phase 7 cert renews cleanly when scoped.

### 3. systemd OnFailure= drop-in wiring
expected: `systemctl show -p OnFailure certbot.service` shows certbot-renew-failure.service; a forced failure writes user.crit to journald.
result: [PASS — 2026-06-13] After bootstrap: `systemctl show -p OnFailure certbot.service` → `OnFailure=certbot-renew-failure.service`. Files present: /etc/systemd/system/certbot.service.d/onfailure.conf, /etc/systemd/system/certbot-renew-failure.service, /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh (executable). Stock certbot.timer preserved.

### 4. ufw split-tunnel rule (wg0 → 6443)
expected: `ufw status verbose` shows `6443 on wg0 ALLOW IN` (interface-qualified), and no blanket 6443 exposure.
result: [PASS — 2026-06-13] `6443/tcp on wg0 ALLOW IN # k3s API via WireGuard only` (v4 + v6), interface-qualified, no blanket 6443. NOTE: the original bootstrap used the invalid `to any port 6443/tcp` form (ufw: "Bad port '6443/tcp'") — fixed to `port 6443 proto tcp` (commit cfa2485) and validator marker tightened. wg0 up (10.8.0.1/24).

### 5. live TLS + upstream reachability
expected: `curl -I https://stats-staging.solid-stats.ru/` → valid TLS handshake, HSTS header, response from server-2 upstream (10.43.94.103:3000).
result: [PASS — 2026-06-13] `curl -I https://stats-staging.solid-stats.ru/` → HTTP/2, TLS ok, `strict-transport-security: max-age=31536000; includeSubDomains` present (after adopt), `application/json` 404 from the server-2 upstream (app's own response). TLS + http2 + HSTS + upstream proxy all proven.

### 6. teardown reversibility proof
expected: `scripts/teardown-edge.sh` restores the pre-adoption edge state (.bak vhost restored or repo-identical vhost removed, drop-in/hook/ufw rule removed) with no broken nginx; re-running bootstrap reproduces the adopted state (idempotency).
result: [PASS — 2026-06-13] Full cycle on live host: teardown (RC=0) restored the original vhost from .bak (HSTS gone, 1142 bytes), removed drop-in/failure-unit/deploy-hook (OnFailure= empty), removed plain 80/443/6443-wg0 ufw rules (profile Nginx Full/HTTP + SSH preserved), nginx kept serving HTTP/2 — NO outage. Then re-bootstrap (RC=0) restored HSTS, drop-in, hook, OnFailure, and the 6443/wg0 rule; HSTS live again. Idempotency + reversibility (EDGE-05) proven. NOTE: teardown removes the 6443/wg0 rule which Phase 6 originally owns (Phase 7 bootstrap adopts/updates it) — re-bootstrap restores it; minor cross-phase coupling, end state correct.

## Summary

total: 6
passed: 6
issues: 0
pending: 0
partial: 0
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

### G-2 (RESOLVED): bootstrap ufw 6443/wg0 rule used invalid port syntax
status: resolved
found: 2026-06-13 during live bootstrap run (step 7 FATAL)
detail: |
  bootstrap-edge.sh used `ufw allow in on wg0 to any port 6443/tcp` — in ufw's
  extended `to any port N` syntax the `/tcp` suffix is rejected ("Bad port
  '6443/tcp'"), so the bootstrap aborted at step 7 with "FATAL: ufw 6443/wg0 rule
  failed". The offline validator's marker `...port 6443` matched the buggy form as
  a substring, so it passed — a class of bug only live execution catches.
resolution: commit cfa2485 — bootstrap-edge.sh + teardown-edge.sh now use `port 6443 proto tcp`; validate-edge.py marker tightened to require the full `proto tcp` literal. Re-run of bootstrap completed RC=0 ("Rule updated"); teardown delete + re-bootstrap round-trip both clean.
