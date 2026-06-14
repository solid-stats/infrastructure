# Obs-Edge Bootstrap: Grafana TLS and errors. Placeholder Vhosts

This is the operator runbook for bootstrapping the observability edge subdomains
(`grafana.solid-stats.ru` and `errors.solid-stats.ru`) on
the existing Phase 07 staging host. The bootstrap extends the live edge **additively** —
it does NOT touch the existing `stats-staging-solid-stats.conf` vhost or its certificate.

The script is idempotent (adopt-reconcile pattern): re-running it produces the same final
state. Offline structural checks run in CI via `scripts/validate-obs-edge.py` at every
commit; the live bootstrap is operator-gated on DNS resolution.

## Context: Additive to the Existing Phase 07 Edge

The staging VPS already serves `stats-staging.solid-stats.ru` via nginx + certbot (Phase 07).
Phase 14 adds two independent nginx vhosts and TLS certs:

| Domain | Upstream | Phase wired |
|--------|----------|-------------|
| `grafana.solid-stats.ru` | Grafana ClusterIP (discovered at runtime) | Phase 14 |
| `errors.solid-stats.ru` | GlitchTip ClusterIP | Phase 16 (cert issued now) |

**Do NOT touch** `stats-staging-solid-stats.conf` or its cert (`stats-staging.solid-stats.ru`)
at any point during this bootstrap. The obs-edge script does not modify the Phase 07 vhost.

Shared systemd artifacts (deploy hook, OnFailure drop-in, failure handler) are refreshed via
idempotent `cp` — they are the same files as Phase 07 and the `cp` is a no-op if already current.

## DNS Prerequisite — Hard Gate (EDGE-01)

> **The operator MUST create both A records before running certbot.** certbot HTTP-01 challenge
> fails with NXDOMAIN if DNS is not resolving. `SKIP_CERTBOT=1` bypasses cert issuance for
> script testing without live DNS.

Create the following DNS A records with your registrar or DNS provider:

```
grafana.solid-stats.ru  A  89.223.124.200
errors.solid-stats.ru   A  89.223.124.200
```

Both records point to the same VPS public IP. The agent cannot create DNS records — this is a
registrar-controlled action.

### Verify DNS Propagation Before Running certbot

DNS propagation can take 5–60 minutes after record creation. Verify with:

```bash
dig +short grafana.solid-stats.ru A @8.8.8.8
dig +short errors.solid-stats.ru A @8.8.8.8
```

Both commands must return `89.223.124.200` before proceeding. If either returns empty or
`NXDOMAIN`, wait and retry. Do NOT run the bootstrap with certbot enabled until both resolve.

## Offline Checks (CI — no VPS required)

> **OFFLINE-VERIFIABLE.** These checks run in CI without touching the VPS. They validate
> repo artifact structure but NOT live nginx or certbot behavior.

```bash
python3 scripts/validate-obs-edge.py
```

Expected output: four `ok:` lines (bootstrap script, grafana vhost, errors vhost, docs and
shared artifacts) and one `warn:` line about live checks being operator-only.

## Step 1: Clone / Update the Repo on the VPS

```bash
git pull   # or: git clone https://github.com/solid-stats/infrastructure
```

The repo must be current so `bootstrap-obs-edge.sh` installs the latest vhost templates and
shared systemd artifacts.

## Step 2: Bootstrap grafana. (discovers Grafana ClusterIP at runtime)

The Grafana ClusterIP is dynamically assigned by k3s. The script discovers it at bootstrap
time via `kubectl get svc`. Run from the repo root on the VPS:

```bash
DOMAIN=grafana.solid-stats.ru \
ADMIN_EMAIL=your@email.com \
scripts/bootstrap-obs-edge.sh
```

What the bootstrap does for grafana.:

1. Package check: `apt-get install -y certbot nginx curl openssl` (idempotent).
2. Webroot: `mkdir -p /var/www/html/.well-known/acme-challenge` (idempotent).
3. Discovers Grafana ClusterIP: `kubectl get svc grafana -n monitoring -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}'`.
4. Backs up any existing live vhost to `.bak` (only on first run).
5. Installs HTTP-only temp vhost → runs `nginx -t` gate → reloads nginx (ACME challenge now reachable).
6. Issues TLS cert: `certbot certonly -d grafana.solid-stats.ru`.
7. Swaps HTTP-only temp vhost for final TLS vhost → `nginx -t` gate → reloads nginx.
8. Installs certbot deploy hook and OnFailure drop-in (idempotent `cp`).
9. Skips UFW — ports 80/443 are already open from Phase 07.

The script is safe to re-run. On second run: backup already exists (skipped), cert lineage
exists (issuance skipped), vhost is up to date (overwritten and reloaded idempotently).

## Step 3: Bootstrap errors. (no upstream; cert-only for rate-limit safety)

The `errors.` domain has no upstream yet (GlitchTip is wired in Phase 16). Issue the cert now
to avoid hitting Let's Encrypt rate limits later (both certs share the registered domain
`stats-staging.solid-stats.ru`). The `SKIP_UPSTREAM_CHECK=1` flag tells the script to skip
ClusterIP discovery and install a placeholder vhost that returns 503.

```bash
DOMAIN=errors.solid-stats.ru \
ADMIN_EMAIL=your@email.com \
SKIP_UPSTREAM_CHECK=1 \
scripts/bootstrap-obs-edge.sh
```

The errors. vhost returns `503 Service Unavailable` for all HTTPS requests until Phase 16 wires
the GlitchTip ClusterIP. This is expected behavior.

## certbot Caveat — Per-Domain certonly Only (NEVER full-renew)

> **IMPORTANT:** On this VPS, `certbot renew` (unscoped) or any full-renew flow hangs
> indefinitely on the auth cert. Always use the forms below.

| Safe | Dangerous (DO NOT USE) |
|------|------------------------|
| `certbot certonly -d <domain>` — initial issuance | `certbot renew` (unscoped) — hangs on this VPS |
| `certbot renew --dry-run` — dry-run is safe | `certbot --full-renew` — also hangs |
| `certbot renew --cert-name <domain>` — scoped renewal | |

The `certbot certonly -d <domain>` form is safe for new issuance. The stock `certbot.timer`
handles automated renewal via the deploy hook — do not create a custom timer.

## Step 4: Operator-Only Live Verification

> **OPERATOR-ONLY.** All checks below require live VPS access and DNS resolution. They cannot
> run in CI.

### 4a. nginx config syntax

```bash
nginx -t
```

Expected: `syntax is ok` and `test is successful`.

### 4b. Certificate inventory

```bash
certbot certificates
```

Expected: lineages for both `grafana.solid-stats.ru` and
`errors.solid-stats.ru` are listed with a valid expiry date.

### 4c. TLS handshake — grafana.

```bash
openssl s_client -connect grafana.solid-stats.ru:443 -servername grafana.solid-stats.ru </dev/null 2>/dev/null | grep -E "subject|issuer|expire"
```

Expected: subject includes `grafana.solid-stats.ru`; issuer is `Let's Encrypt`.

### 4d. HTTP → HTTPS redirect

```bash
curl -sI http://grafana.solid-stats.ru/ | head -5
```

Expected: `301 Moved Permanently` with `Location: https://grafana.solid-stats.ru/`.

### 4e. Grafana HTTPS reachability (MET-07)

```bash
curl -sI https://grafana.solid-stats.ru/
```

Expected: `200 OK` or `302` redirect to `/login`. Then open the URL in a browser and confirm the
Grafana login page renders (local-user auth — no anonymous access).

### 4f. Renewal pipeline smoke-test

```bash
certbot renew --dry-run --cert-name grafana.solid-stats.ru
certbot renew --dry-run --cert-name errors.solid-stats.ru
```

Expected: `Simulating renewal of an existing certificate` → `Congratulations, all simulated
renewals succeeded`. This confirms webroot, deploy hook, and ACME connectivity all work.

## Known Post-Deploy Check: Grafana Login Redirect

If the Grafana login page redirects back to `http://` (not `https://`) after submitting credentials,
the Grafana ConfigMap needs `root_url` set:

```yaml
# k8s/observability/50-grafana.yaml — grafana.ini ConfigMap key
root_url = https://grafana.solid-stats.ru
```

Add this line to the Grafana ConfigMap and redeploy (`kubectl rollout restart deployment/grafana -n monitoring`).
Do NOT preemptively change the Phase 13 ConfigMap — only add `root_url` if the redirect loop
actually occurs post-deployment.

## Phase 16 Reuse: Wiring the errors. Upstream

When Phase 16 deploys GlitchTip, wire the `errors.` upstream by re-running the bootstrap with
the GlitchTip Service ClusterIP. No script change is needed:

```bash
DOMAIN=errors.solid-stats.ru \
UPSTREAM=$(kubectl get svc glitchtip-web -n monitoring -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}') \
ADMIN_EMAIL=your@email.com \
scripts/bootstrap-obs-edge.sh
```

The script detects that the cert lineage already exists (skips re-issuance) and swaps the
placeholder 503 vhost for the full TLS proxy vhost wired to the GlitchTip ClusterIP.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `dig` returns `NXDOMAIN` for grafana. or errors. | DNS A records not created or not yet propagated | Create the two A records with your registrar; wait for propagation (up to 60 min); verify with `dig +short ... @8.8.8.8` |
| certbot exits with `Connection refused` or NXDOMAIN error | DNS not propagated when certbot ran | Wait for DNS propagation and re-run with `SKIP_CERTBOT=0` |
| certbot exits with `too many certificates already issued` | Let's Encrypt rate limit hit | Wait one week or use the `--staging` flag for testing; do not re-issue unnecessarily |
| nginx returns 502 Bad Gateway for grafana. | Wrong ClusterIP or Grafana pod not running | Run `kubectl get svc grafana -n monitoring` to verify ClusterIP; check `kubectl get pods -n monitoring` |
| `nginx -t` fails after bootstrap | TLS vhost installed before cert existed | bootstrap restores `.bak` automatically; check bootstrap log for `FATAL`; re-run after cert issuance |
| `FATAL: nginx config invalid after vhost install` | Repo vhost syntax error or cert file not found | Bootstrap auto-restores `.bak`; fix the vhost or ensure cert was issued first and re-run |
| `FATAL: DOMAIN is required` | `DOMAIN` env var not set | Set `DOMAIN=grafana.solid-stats.ru` (or errors.) before running the script |
| `FATAL: ADMIN_EMAIL is required` | `ADMIN_EMAIL` env var not set | Set `ADMIN_EMAIL=your@email.com` |
| `FATAL: Could not discover Grafana Service ClusterIP` | Grafana not deployed in `monitoring` namespace | Complete Phase 13 first; verify with `kubectl get svc grafana -n monitoring` |

See also: [`docs/edge-bootstrap.md`](edge-bootstrap.md) (Phase 07 main edge runbook).
