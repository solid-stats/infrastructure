# Edge Bootstrap: nginx Vhost, TLS Renewal Hook, and Firewall

This is the operator runbook for adopting the existing staging host edge (nginx vhost,
certbot renewal hook, host firewall) into the infrastructure repo. The bootstrap script
is idempotent and backs up the live vhost before applying the repo copy. Live verification
steps require SSH access to the VPS; offline structural checks run in CI via
`scripts/validate-edge.py`.

## Context: Adopt, Not Rebuild

The staging edge (`stats-staging.solid-stats.ru`) is already live and serving traffic.
Phase 7 does **NOT** rebuild it — it:

1. Stores the live vhost config verbatim in the repo (`config/nginx/sites-available/stats-staging-solid-stats.conf`).
2. Adds a certbot deploy hook (nginx -t gate before reload, installed to `/etc/letsencrypt/renewal-hooks/deploy/`).
3. Adds an `OnFailure=` drop-in on the stock `certbot.service` to surface renewal failures to journald.
4. Applies ufw firewall rules (22/80/443 public; 6443 is NOT exposed externally — reached only via the SSH local-forward to 127.0.0.1:6443).
5. Keeps the existing `certbot.timer` — no new renewal timer is created.

## Prerequisites

- SSH access to the staging VPS as root or with sudo.
- Git clone of this repository on the VPS (or copy `scripts/` and `config/` to the host).
- `ADMIN_EMAIL` — a valid email for Let's Encrypt (used only if no cert lineage exists; the
  cert is already issued, so bootstrap skips issuance by default).
- Port 80 and 443 inbound reachable from the public internet.

## Offline Checks (CI — no VPS required)

> **OFFLINE-VERIFIABLE.** These checks run in CI without touching the VPS. They validate
> repo artifact structure but NOT live nginx or certbot behavior.

```bash
python3 scripts/validate-edge.py
```

Expected output: five `ok:` lines (nginx vhost shape, shell scripts, systemd drop-in shape,
bootstrap idempotency markers, teardown script). One `warn:` about nginx -t being
operator-only.

## Step 1: Clone / Update the Repo on the VPS

```bash
git pull   # or: git clone https://github.com/solid-stats/infrastructure
```

The repo must be current so `bootstrap-edge.sh` installs the latest config files.

## Step 2: Run the Bootstrap Script

```bash
ADMIN_EMAIL=your@email.com scripts/bootstrap-edge.sh
```

What the bootstrap does:

- Installs packages (`certbot`, `nginx`, `ufw`, `curl`, `openssl`).
- Backs up the live `/etc/nginx/sites-available/stats-staging-solid-stats.conf` to a `.bak` file
  (backup is skipped on subsequent runs if `.bak` already exists).
- Installs the repo vhost, runs `nginx -t` gate, reloads nginx. If `nginx -t` fails, the `.bak`
  is restored automatically before any reload.
- Skips cert issuance if the `/etc/letsencrypt/live/stats-staging.solid-stats.ru` lineage already
  exists (it does — bootstrap is safe to run without re-issuing the cert).
- Installs the certbot deploy hook to `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`.
- Installs the `OnFailure=` drop-in to `/etc/systemd/system/certbot.service.d/onfailure.conf`
  and the failure handler service; runs `systemctl daemon-reload`.
- Applies ufw rules: `22/tcp`, `80/tcp`, `443/tcp` public. It adds NO 6443 rule — the k3s API
  stays private behind the `default deny incoming` policy and is reached only via the SSH
  local-forward (`scripts/ssh-tunnel-up.sh` -> 127.0.0.1:16443 -> 127.0.0.1:6443 on the VPS).

To skip ufw changes (e.g. ufw is already configured to your satisfaction):

```bash
ADMIN_EMAIL=your@email.com SKIP_UFW=1 scripts/bootstrap-edge.sh
```

The script is safe to re-run. A second run produces the same final state as the first.

## Step 3: Operator-Only Live Verification

> **OPERATOR-ONLY.** All checks in this section require live VPS access. They cannot be run
> in CI or from a local machine without direct host access.

### 3a. nginx config syntax — OPERATOR-ONLY

```bash
nginx -t
```

Expected: `syntax is ok` and `test is successful`.

### 3b. Certbot renewal dry-run — OPERATOR-ONLY

```bash
certbot renew --dry-run
```

Expected: `Congratulations, all simulated renewals succeeded` or `No renewals were attempted`
(if the cert is not due for renewal yet). This confirms the webroot path, the deploy hook, and
ACME connectivity all work correctly.

### 3c. OnFailure= drop-in wired — OPERATOR-ONLY

```bash
systemctl show -p OnFailure certbot.service
```

Expected: `OnFailure=certbot-renew-failure.service`. If the field is empty, the drop-in was not
loaded — run `systemctl daemon-reload` and check again.

### 3d. Firewall edge rules — OPERATOR-ONLY

```bash
ufw status verbose
```

Expected rules present:

- `22/tcp ALLOW Anywhere` (SSH — operator access)
- `80/tcp ALLOW Anywhere` (HTTP public + ACME challenges)
- `443/tcp ALLOW Anywhere` (HTTPS public)

`6443` is intentionally absent from `ufw status` — the k3s API is private, kept closed by
the `default deny incoming` policy and reached only via the SSH local-forward
(`scripts/ssh-tunnel-up.sh` -> `127.0.0.1:16443` -> `127.0.0.1:6443` on the VPS).
If any `6443` allow rule appears, remove it with `ufw delete allow 6443/tcp` — it must not
be publicly reachable.

### 3e. Public HTTPS smoke check — OPERATOR-ONLY

```bash
curl -I https://stats-staging.solid-stats.ru/
```

Expected: `HTTP/1.1 200` or `HTTP/2 200` with a valid TLS handshake (no certificate errors).

## Step 4: Certificate Renewal Verification

> **OPERATOR-ONLY.** The stock `certbot.timer` already runs twice daily — no new timer is
> needed.

To verify the renewal pipeline end-to-end:

```bash
certbot renew --dry-run
```

To check for past renewal failures since today:

```bash
journalctl -t certbot-alert --since today
```

No output means no failures. Any entry indicates a renewal failure — inspect the certbot logs:

```bash
journalctl -u certbot.service -n 20
```

> **Do NOT create a custom `certbot-renew.timer`** — the stock `certbot.timer` is already
> running and is the correct renewal mechanism (decision D-4). Phase 7 extends it only with
> a deploy hook and an `OnFailure=` drop-in; it does not replace or duplicate the timer.

## Phase 11 Cutover Lever

The nginx upstream is the Phase 11 traffic cutover lever. The exact location is:

```
config/nginx/sites-available/stats-staging-solid-stats.conf
```

The upstream block:

```nginx
upstream solid_stats_staging_server2 {
    # CUTOVER: change this server address to switch production traffic (Phase 11 lever)
    server 10.43.94.103:3000;
    keepalive 16;
}
```

To switch traffic to a different runtime: edit the `server` line inside the upstream block
(the line marked `# CUTOVER:`), then re-run `bootstrap-edge.sh` (or run `nginx -t && systemctl
reload nginx` manually on the host). Phase 11 documents this step in detail.

## Reversibility: Teardown

Before Phase 11, the operator must prove the edge is reversible in isolation. Run teardown
on the VPS to undo all bootstrap steps:

```bash
scripts/teardown-edge.sh
```

This removes:

- The `certbot.service.d/onfailure.conf` drop-in and `certbot-renew-failure.service`.
- The certbot deploy hook at `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`.
- The repo vhost from `sites-available` and `sites-enabled`; restores the original from the
  `.bak` backup created during bootstrap.
- ufw rules for `80/tcp` and `443/tcp`.

Preserved (NOT removed by teardown):

- `/etc/letsencrypt/` certificates (run `certbot delete -d stats-staging.solid-stats.ru`
  explicitly if removal is needed).
- `ufw allow 22/tcp` SSH rule.
- ufw firewall itself (remains enabled with remaining rules).

After teardown, verify on the host (OPERATOR-ONLY):

```bash
ufw status verbose                            # 80/443 rules absent; 22 present
systemctl list-timers                         # stock certbot.timer still active (not removed by teardown)
systemctl show -p OnFailure certbot.service   # OnFailure field now empty
nginx -t                                      # nginx config valid with restored original vhost
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `FATAL: ADMIN_EMAIL is required` | `ADMIN_EMAIL` env var not set | Set `ADMIN_EMAIL=your@email.com` before running the script |
| `FATAL: nginx config invalid after vhost install` | Repo vhost has a syntax error or certbot TLS files are missing | Script restores `.bak` automatically; fix the vhost and re-run |
| `certbot renew --dry-run` fails to connect | Port 80 not reachable from the internet | Verify Timeweb perimeter firewall allows port 80 inbound |
| `ufw status` shows any `6443` allow rule | 6443 must not be publicly reachable | Remove with `ufw delete allow 6443/tcp` — 6443 must stay private behind the SSH local-forward |
| `OnFailure= field empty after daemon-reload` | Drop-in directory name mismatch | Check that `/etc/systemd/system/certbot.service.d/onfailure.conf` exists (dir must be `certbot.service.d`, not `certbot-renew.service.d`) |

See also: [`docs/operator-bootstrap.md`](operator-bootstrap.md) (Phase 6 RBAC + SSH-tunnel bootstrap).
