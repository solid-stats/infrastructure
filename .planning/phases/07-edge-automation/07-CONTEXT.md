# Phase 7: Edge Automation - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — smart discuss skipped per autonomous infrastructure detection)

<domain>
## Phase Boundary

The public staging edge — host nginx vhost, TLS renewal, and firewall — is
repo-managed, idempotently re-runnable, and proven reversible in isolation before
it becomes the cutover lever (Phase 11).

In scope (EDGE-01..05):
- Host nginx vhost config for staging, stored in the repo.
- An idempotent, re-runnable bootstrap script that applies the edge config the
  same way on every run.
- Automatic TLS renewal via host `certbot` on a systemd timer, with an
  `nginx -t`-gated reload hook; `certbot renew --dry-run` passes.
- Certificate-renewal failure surfacing (alert or log entry, not silent).
- Host firewall: allow 80/443 inbound; keep `6443` (k3s API) reachable only
  through the WireGuard tunnel.

Out of scope: the actual production-traffic cutover (Phase 11 — the single
reversible nginx-upstream switch). This phase only proves the edge is
repo-managed and reversible in isolation.

</domain>

<decisions>
## Implementation Decisions

### LOCKED — Revised after live SSH inspection (2026-06-12)
The first research/plan treated this as greenfield. **It is NOT.** SSH inspection
of the live host (`deploy@89.223.124.200`, Ubuntu 24.04.4, nginx 1.24.0, certbot
2.9.0) shows the staging edge already exists and serves live traffic. Phase 7 is
**ADOPT-the-existing-edge-into-the-repo + add firewall / renewal-hook / failure
surfacing / reversibility**, NOT build-from-scratch. Locked decisions:

1. **Scope = ONLY the `stats-staging-solid-stats.conf` vhost.** The same nginx also
   serves `sg-stats-relay.conf` (auth.solid-stats.ru + relay.solid-stats.ru) and
   `default`. Those are operator-owned, OUT OF PHASE-7 SCOPE, and the relay vhost
   contains an unrelated auth secret — they MUST NOT be copied into the repo (git
   secret-leak risk). Capture/manage only the stats-staging vhost.
2. **Repo vhost = a verbatim mirror of the live `stats-staging-solid-stats.conf`**
   (filename kept as `stats-staging-solid-stats.conf`). Real shape: a named
   `upstream solid_stats_staging_server2 { server 10.43.94.103:3000; keepalive 16; }`
   block with `proxy_pass http://solid_stats_staging_server2`; ACME webroot at
   `/var/www/html`; HTTP→HTTPS redirect; TLS via
   `/etc/letsencrypt/live/stats-staging.solid-stats.ru/` + `options-ssl-nginx.conf`
   + `ssl-dhparams.pem`. The **CUTOVER lever (Phase 11)** is the single
   `server 10.43.94.103:3000;` line inside the upstream block — mark it.
3. **Real upstream is the server-2 ClusterIP `10.43.94.103:3000`** (k3s routes
   ClusterIPs on the node), NOT a `127.0.0.1:3000` placeholder.
4. **TLS renewal already runs via the stock `certbot.timer`** (systemd, twice
   daily; cert already issued for lineage `stats-staging.solid-stats.ru`). **DO NOT
   create a custom `certbot-renew.timer`/`.service`** — that would double-renew /
   conflict. EDGE-02's repo value-add is ONLY: a repo-stored `nginx -t`-gated
   **deploy-hook** installed idempotently at
   `/etc/letsencrypt/renewal-hooks/deploy/` (reload nginx only after `nginx -t`).
5. **EDGE-03 surfacing = an `OnFailure=` systemd drop-in on the STOCK
   `certbot.service`** (`/etc/systemd/system/certbot.service.d/onfailure.conf`) →
   a small failure-handler unit that logs to journald (`logger -p user.crit`). Do
   not invent a parallel renewal service.
6. **certbot authenticator = webroot** with webroot path `/var/www/html` (matches
   the live ACME location). Do not re-issue the existing cert — bootstrap must
   detect the existing lineage and skip issuance (idempotent).
7. **EDGE-04 firewall = ufw.** The k3s API `6443` currently LISTENS on all
   interfaces (`*:6443` per live `ss`); allow 80/443 inbound, allow 6443 only on
   `wg0` (10.8.0.1/24), deny 6443 on the public interface, never lock out
   WireGuard/SSH. Idempotent (re-run adds no dup rules). Operator confirms current
   ufw state during bootstrap (deploy user lacks sudo, ufw status not yet read).
8. **EDGE-05 bootstrap = adopt/reconcile, not create.** Before overwriting the
   live vhost, back it up so `teardown-edge.sh` can restore the exact original.
   Idempotent ops only (`install`/`ln -sf`/guarded `ufw`); no cert re-issue.
9. **Offline validator (`scripts/validate-edge.py`)** stays — validates the repo
   vhost + scripts + systemd units offline; live `nginx -t` / `certbot renew
   --dry-run` / `ufw status` remain OPERATOR-ONLY (per 07-VALIDATION.md).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/wg-tunnel-up.sh`, `scripts/kubeconfig-setup.sh` — Phase 6 bash
  conventions to mirror: handshake/precondition gating, `set -euo pipefail`,
  explicit required-env validation, no secret echoing.
- `docs/wireguard-access.md`, `docs/operator-bootstrap.md` — existing
  operator-runbook style and the WireGuard interface (`10.8.0.1`, tunnel) the
  `6443`-only-via-WG firewall rule must align with.
- `scripts/validate-staging.py` — repo validation harness; edge artifacts should
  be validatable in the same spirit (syntax / shape checks runnable in CI without
  touching the live host).

### Established Patterns / Live Host State (verified via SSH 2026-06-12)
- **NOT greenfield.** Host already runs: nginx 1.24.0 with sites-enabled
  `default`, `sg-stats-relay.conf`, `stats-staging-solid-stats.conf`; certbot
  2.9.0 with the stock `certbot.timer` auto-renewing twice daily; certs under
  `/etc/letsencrypt/live/{stats-staging.solid-stats.ru,auth...,relay...}`; `wg0`
  up at `10.8.0.1/24`; ports 80/443 (nginx) and 6443 (k3s, all interfaces)
  listening.
- Phase 7 captures ONLY the stats-staging vhost into the repo and adds firewall +
  deploy-hook + failure surfacing + reversibility, idempotently, without
  disrupting the live edge or the operator-owned relay/auth/default vhosts.
- Idempotent re-runnable bootstrap scripts; configs pinned in-repo; one
  environment per directory; explicit host boundaries.

### Integration Points
- The k3s API (`6443`) is reached only over the WireGuard tunnel from Phase 6 —
  the firewall rule must preserve that and not expose `6443` publicly.
- The edge nginx upstream is the future Phase 11 cutover lever — config must be
  structured so the upstream switch is a single reversible edit.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase. Refer to EDGE-01..05 and the
ROADMAP success criteria. Live application to the VPS host is out of band for
this environment (VPN-isolated); the phase delivers repo-managed, validatable
artifacts plus an operator runbook, with live apply deferred like the Phase 6
live deploy.

</specifics>

<deferred>
## Deferred Ideas

- Weighted / blue-green nginx cutover with gradual traffic shift (CUT-05) — out
  of scope, deferred to v2.x.
- The actual production cutover (Phase 11).

</deferred>
