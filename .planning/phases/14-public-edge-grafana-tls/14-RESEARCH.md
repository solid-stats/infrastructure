# Phase 14: Public Edge & Grafana TLS — Research

**Researched:** 2026-06-14
**Domain:** Host-nginx edge bootstrap, certbot TLS, k3s ClusterIP wiring
**Confidence:** HIGH (all key findings from codebase direct read — no external lookup needed)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Mirror the v2.0 Phase 07 adopt-reconcile edge pattern exactly (`bootstrap-edge.sh` is the
  canonical model). Produce a dedicated `bootstrap-obs-edge.sh` for the obs subdomains.
- The bootstrap is reusable: Phase 16 (GlitchTip) extends it for the `errors.` vhost without
  modifications to the script — just a second invocation with different domain/upstream args.
- `errors.stats-staging.solid-stats.ru` DNS + cert must be provisioned NOW in Phase 14 even
  though the upstream is wired in Phase 16 (rate-limit avoidance).
- certbot per-domain issuance only (`certbot certonly -d <domain>`). NEVER `certbot --full-renew`
  (known operator caveat: hangs on the auth cert on this VPS).
- Grafana's own auth = MET-07. No extra auth layer at the nginx level.

### Claude's Discretion
All implementation details are at Claude's discretion — discuss phase was skipped.

### Deferred Ideas (OUT OF SCOPE)
- `errors.` upstream (GlitchTip ClusterIP) — wired in Phase 16.
- NetworkPolicies — Phase 17.
- Any Grafana config changes — Phase 13 shipped Grafana already.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EDGE-01 | DNS A records for `grafana.` and `errors.` subdomains resolve to 89.223.124.200 | Operator-gated; bootstrap script includes DNS wait guard and clear operator instructions |
| EDGE-02 | Host nginx vhosts proxy each public host to its ClusterIP Service, reusing Phase 07 pattern via `bootstrap-obs-edge.sh` | Covered: ClusterIP wiring mechanism, vhost template, adopt-reconcile pattern |
| EDGE-03 | Valid certbot TLS certs issued and served for both public hosts | Covered: per-domain `certbot certonly` webroot flow, SKIP_CERTBOT guard, renewal hook reuse |
| MET-07 | Operator reaches Grafana at public staging URL behind local-user auth | Covered: Grafana's own login page is the auth; nginx proxy_pass + WebSocket upgrade headers |
</phase_requirements>

---

## Summary

Phase 14 extends the existing host-nginx edge — already live for `stats-staging.solid-stats.ru`
(Phase 07) — with a second independent bootstrap for the observability subdomains. The pattern is
fully understood from the codebase: `bootstrap-edge.sh` provides the complete canonical model.

The critical technical question — **how does host nginx reach a k3s ClusterIP?** — is answered by
the existing live vhost: k3s (using kube-router/flannel) programs the VPS host's routing table to
include the cluster service CIDR (10.43.x.x), making ClusterIP addresses directly routable from
the host. The Phase 07 vhost hard-codes `server 10.43.94.103:3000` and it works. The obs bootstrap
must discover Grafana's ClusterIP at runtime (it is dynamically assigned — no static IP in the
manifest) via `kubectl get svc grafana -n monitoring -o jsonpath=`.

The DNS gate is hard: both A records are operator/registrar-controlled and do not currently exist.
All autonomous work (script authoring, vhost templates, validation, docs) can proceed; certbot
issuance and public-URL smoke-test are operator-gated on DNS resolution.

**Primary recommendation:** Author `bootstrap-obs-edge.sh` as a parameterized variant of
`bootstrap-edge.sh` accepting `DOMAIN` and `UPSTREAM` env vars; one script handles both
`grafana.` and `errors.` domains sequentially or via two invocations. Mirror every idempotency
pattern exactly: backup-before-overwrite, `nginx -t` gate, SKIP_CERTBOT guard, deploy-hook reuse.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| TLS termination | Host Edge (nginx) | — | Host nginx terminates TLS; k3s pods never see raw HTTPS |
| HTTP→HTTPS redirect | Host Edge (nginx) | — | Same vhost, HTTP server block, `return 301` |
| ACME HTTP-01 challenge | Host Edge (nginx) | — | Webroot at `/var/www/html`, served by nginx HTTP block |
| cert issuance/renewal | Host (certbot) | systemd timer | `certbot certonly --webroot`; stock `certbot.timer` handles renewal |
| Proxy to Grafana | Host Edge (nginx) | — | `proxy_pass` to Grafana ClusterIP:80 (host routing table covers k3s CIDR) |
| Grafana authentication | In-cluster (Grafana pod) | — | `GF_SECURITY_ADMIN_*` from Secret; no anonymous access; nginx passes through |
| DNS record creation | External (registrar) | — | Operator-controlled; agent cannot create DNS records |
| ClusterIP discovery | Host (kubectl at bootstrap time) | — | `kubectl get svc grafana -n monitoring -o jsonpath=` called inside bootstrap script |

---

## Standard Stack

### Core (all already present on staging VPS — no install needed)

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| nginx | host-installed | TLS termination, HTTP proxy, ACME webroot | Already managing `stats-staging.solid-stats.ru` |
| certbot | host-installed | Let's Encrypt cert issuance + auto-renewal | Phase 07 established it; deploy hook already in place |
| ufw | host-installed | Host firewall; 80/443 already open from Phase 07 | Rules are idempotent (`ufw allow` is a no-op if rule exists) |
| kubectl | host-installed (k3s bundle) | ClusterIP discovery at bootstrap time | Already used by operator for staging ops |

[ASSUMED] — Tool versions on the VPS not verified in this session (tools are host-installed from
Phase 07; version specifics are not material since the existing bootstrap already uses them).

### No External Packages

This phase installs nothing new. All tooling is already on the host. No npm/pip/cargo audit needed.

---

## Package Legitimacy Audit

**Not applicable** — Phase 14 installs no external packages. All tooling (nginx, certbot, ufw,
kubectl) is already installed on the staging VPS from Phase 07 operations.

---

## Architecture Patterns

### System Architecture Diagram

```
Internet (HTTPS :443)
        |
        v
[Host nginx — obs-edge vhost]
  grafana.stats-staging.solid-stats.ru
  errors.stats-staging.solid-stats.ru (cert-only; no upstream yet)
        |
        | TLS terminated by /etc/letsencrypt/live/<domain>/fullchain.pem
        | proxy_pass to ClusterIP:port (host routing table covers k3s 10.43.x.x CIDR)
        |
        v
[k3s ClusterIP — grafana.monitoring.svc.cluster.local :80]
        |
        v
[Grafana pod :3000 — login page; Grafana auth enforces local-user]
        |
        v
[Prometheus ClusterIP — prometheus-server.monitoring.svc :80]
        |
        v
[Dashboards rendered live]

ACME challenge flow (HTTP :80):
  /.well-known/acme-challenge/* → /var/www/html (nginx serves static file)
  certbot HTTP-01 → Let's Encrypt verifies → issues cert

DNS gate (operator action, before certbot can run):
  grafana.stats-staging.solid-stats.ru  A  89.223.124.200
  errors.stats-staging.solid-stats.ru   A  89.223.124.200
```

### Recommended Project Structure (new artifacts)

```
scripts/
└── bootstrap-obs-edge.sh        # NEW — parameterized obs-edge adopt-reconcile bootstrap

config/nginx/sites-available/
├── stats-staging-solid-stats.conf         # existing (Phase 07, DO NOT TOUCH)
├── grafana-stats-staging-solid-stats.conf # NEW — Grafana vhost (HTTP-first then TLS)
└── errors-stats-staging-solid-stats.conf  # NEW — errors vhost (HTTP-first then TLS)

scripts/
└── validate-obs-edge.py         # NEW — offline structural validator (mirrors validate-edge.py)

docs/
└── obs-edge-bootstrap.md        # NEW — operator runbook for obs-edge bootstrap
```

### Pattern 1: Adopt-Reconcile Bootstrap (mirroring bootstrap-edge.sh exactly)

**What:** Idempotent script that:
1. Checks packages (nginx, certbot, curl, openssl present — `apt-get install -y` is idempotent)
2. Ensures ACME webroot dir exists (`mkdir -p /var/www/html/.well-known/acme-challenge`)
3. **Backs up live vhost** if it exists and no `.bak` yet
4. Installs repo vhost, runs `nginx -t` gate (restores `.bak` on failure), reloads nginx
5. Issues cert via `certbot certonly --authenticator webroot` IF no lineage exists AND SKIP_CERTBOT!=1
6. Installs/updates the shared deploy hook (idempotent `cp`)
7. Installs/updates the OnFailure drop-in (shared with Phase 07; idempotent `cp` + daemon-reload)
8. Skips UFW — ports 80/443 already open from Phase 07

**When to use:** Any new public obs subdomain. Called once per domain.

**Script signature:**
```bash
# Required:
DOMAIN=grafana.stats-staging.solid-stats.ru
UPSTREAM=<ClusterIP>:80          # discovered at runtime via kubectl
ADMIN_EMAIL=ops@example.com

# Optional:
SKIP_CERTBOT=0                   # set to 1 before DNS exists
NGINX_SITES_DIR=/etc/nginx/sites-available
NGINX_SITES_ENABLED=/etc/nginx/sites-enabled
WEBROOT_PATH=/var/www/html

# Phase 16 reuse (example):
DOMAIN=errors.stats-staging.solid-stats.ru
UPSTREAM=<glitchtip-clusterip>:80
```

**ClusterIP discovery pattern (called inside bootstrap):**
```bash
# Run on VPS where kubectl talks to local k3s (no WireGuard needed on the host)
GRAFANA_UPSTREAM=$(kubectl get svc grafana -n monitoring \
  -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}')
# Result: e.g. 10.43.17.52:80
```

[VERIFIED: k8s/observability/50-grafana.yaml — Service type ClusterIP, port 80]
[VERIFIED: config/nginx/sites-available/stats-staging-solid-stats.conf — upstream uses
10.43.94.103:3000, confirming k3s ClusterIPs are directly routable on the VPS host]

### Pattern 2: HTTP-First Vhost, Then TLS Overlay

The adopt-reconcile loop requires a working HTTP vhost BEFORE certbot can issue:

**Phase A — HTTP-only vhost** (installed first, before cert exists):
```nginx
# grafana-stats-staging-solid-stats.conf — HTTP phase (before cert)
server {
    listen 80;
    listen [::]:80;
    server_name grafana.stats-staging.solid-stats.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

**Phase B — Full TLS vhost** (installed after cert exists):
The bootstrap script detects `/etc/letsencrypt/live/$DOMAIN` and installs the TLS-complete vhost.

**Implementation approach:** The repo ships only ONE vhost file per domain. The bootstrap script
uses the single file which already contains BOTH server blocks (HTTP redirect + HTTPS TLS), same
as `stats-staging-solid-stats.conf`. certbot `--pre-hook` / `--post-hook` are NOT needed — the
deploy hook is shared. The key: on first run without a cert, `nginx -t` will FAIL if the TLS vhost
references a non-existent cert path. Therefore the script must either:

**Option A (recommended, mirrors bootstrap-edge.sh behavior):** Ship the vhost WITH TLS blocks.
The script installs it only AFTER cert issuance. On first run:
1. Install HTTP-only temp vhost → reload → certbot certonly → then overwrite with full TLS vhost → reload.

**Option B:** Ship two vhost files (http-only and tls). The script installs the http-only first,
runs certbot, then installs the full TLS file.

**Recommendation: Option A** — single vhost file per domain (same as existing pattern). The
bootstrap installs an inline HTTP-only block first (written by the script to a temp path), runs
certbot, then installs the final repo vhost. This avoids shipping two files per domain.

### Pattern 3: Grafana nginx vhost — Proxy Headers + WebSocket

Grafana 12.x uses WebSocket for its "Grafana Live" streaming feature (dashboard auto-refresh).
The proxy block must include upgrade headers:

```nginx
# Source: Phase 07 vhost (stats-staging-solid-stats.conf) + Grafana docs
upstream grafana_obs {
    server <GRAFANA_CLUSTERIP>:80;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name grafana.stats-staging.solid-stats.ru;

    ssl_certificate /etc/letsencrypt/live/grafana.stats-staging.solid-stats.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grafana.stats-staging.solid-stats.ru/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        proxy_pass http://grafana_obs;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_http_version 1.1;
        # WebSocket upgrade (Grafana Live)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

[ASSUMED] — Grafana Live WebSocket requirement. The existing stats-staging vhost uses
`proxy_set_header Connection ""` (HTTP/1.1 keepalive). For Grafana, the WebSocket upgrade path
is needed. If Grafana Live is disabled in grafana.ini this is still harmless (nginx passes through).

**Note on Grafana server.domain:** The Grafana ConfigMap sets `domain = ''` (empty). For correct
cookie handling behind a reverse proxy, Grafana needs `root_url` set OR the proxy must pass the
correct `Host` header. The vhost already sends `proxy_set_header Host $host` which is correct.
No change to the Grafana ConfigMap is needed for basic operation.

[ASSUMED] — `root_url` not required when `Host` header is proxied correctly and Grafana `domain`
is empty. If redirect loops occur post-deployment, add `root_url = https://grafana.stats-staging.solid-stats.ru`
to grafana.ini ConfigMap — but do NOT preemptively change Phase 13 config.

### Pattern 4: errors. vhost — Placeholder Only (no upstream yet)

For Phase 14, `errors.stats-staging.solid-stats.ru` gets:
- DNS A record (operator, same time as grafana.)
- certbot cert issuance (`SKIP_CERTBOT=0` once DNS exists)
- A placeholder vhost returning 503 (or a "coming soon" static response)
- NO upstream (GlitchTip ClusterIP) — wired in Phase 16

The placeholder vhost avoids certbot complaining about a missing upstream during cert issuance.

### Anti-Patterns to Avoid

- **`certbot --full-renew` or `certbot renew` for new domain issuance:** Hangs on auth cert on
  this VPS. Always use `certbot certonly -d <domain>` for new issuance.
- **Hard-coding ClusterIP in repo vhost:** Grafana ClusterIP is dynamically assigned. The bootstrap
  script must discover it at runtime via `kubectl get svc` and substitute it into the vhost.
  The validate script checks the discovered IP, not a hardcoded value (unlike validate-edge.py
  which checks for the known `10.43.94.103`).
- **Skipping `nginx -t` before reload:** The bootstrap MUST run `nginx -t` after every vhost
  change and restore `.bak` on failure. Never `systemctl reload nginx` without this gate.
- **Custom certbot.timer:** The stock certbot.timer already runs twice daily. Do NOT create a new
  timer. The deploy hook at `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` already handles
  cert rotation — the obs bootstrap reuses the same hook file (idempotent `cp`).
- **Running certbot before DNS resolves:** certbot HTTP-01 will fail with `Connection refused` or
  `NXDOMAIN`. Bootstrap must accept `SKIP_CERTBOT=1` env to author the vhost without cert issuance.
- **Not backing up the live vhost:** If a vhost already exists at the target path (e.g. from a
  previous attempt), bootstrap must back it up before overwriting.
- **Separate UFW rule changes:** Ports 80 and 443 are already open from Phase 07. Do NOT add
  duplicate `ufw allow 80` rules. Bootstrap should `SKIP_UFW=1` by default (or check if rules
  exist first).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TLS certificate issuance | Custom ACME client | certbot (already installed) | Rate-limit tracking, auto-renewal, webroot plugin, hooks |
| TLS cert renewal hook | Custom systemd timer | Stock `certbot.timer` + deploy hook | Phase 07 already wired this; adding a new timer creates dual-renewal risk |
| Nginx WebSocket proxying | Custom TCP tunnel | `proxy_set_header Upgrade` + `Connection "upgrade"` | Standard nginx WebSocket proxy pattern |
| Grafana authentication | nginx `auth_basic` / IP allow-list | Grafana's own login (GF_SECURITY_ADMIN_*) | MET-07 explicitly says "local-user auth"; Grafana secret already deployed |
| ClusterIP resolution | Static IP in repo | `kubectl get svc -o jsonpath` at bootstrap time | Grafana Service has no static clusterIP; dynamic assignment |

---

## Common Pitfalls

### Pitfall 1: certbot --full-renew hangs
**What goes wrong:** Running `certbot renew` or `certbot --full-renew` on this VPS hangs
indefinitely on the auth cert challenge.
**Why it happens:** Known VPS-specific issue (operator memory note `staging-vps-access`).
**How to avoid:** Always use `certbot certonly -d <domain>` for initial issuance. Dry-run
with `certbot renew --dry-run` is safe (doesn't actually issue). NEVER use full-renew.
**Warning signs:** certbot process doesn't exit after 60 seconds.

### Pitfall 2: Grafana ClusterIP is dynamic
**What goes wrong:** If the vhost hard-codes a Grafana ClusterIP that later changes (pod restart
doesn't change it, but if the Service is deleted/recreated it will), or if a wrong IP is used.
**Why it happens:** The `monitoring/grafana` Service has no `spec.clusterIP` in the manifest —
IP is assigned dynamically by k3s on first apply.
**How to avoid:** Bootstrap script discovers IP at runtime: `kubectl get svc grafana -n monitoring
-o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}'`. Validate script checks it's a reachable
10.43.x.x address, not a placeholder.
**Warning signs:** Nginx returns 502 Bad Gateway; `curl http://<discovered-ip>:80` from VPS host
returns Grafana HTML.

### Pitfall 3: nginx -t fails because TLS cert doesn't exist yet
**What goes wrong:** The full TLS vhost references `/etc/letsencrypt/live/<domain>/fullchain.pem`.
If installed before certbot runs, `nginx -t` fails with "cannot load certificate".
**Why it happens:** nginx validates SSL file paths at config test time.
**How to avoid:** Bootstrap logic: install HTTP-only temp vhost first → reload → run certbot →
replace with full TLS vhost → reload. The script must detect whether a cert lineage exists and
branch accordingly.
**Warning signs:** bootstrap fails at step 3 (vhost install) on first run with SKIP_CERTBOT=0.

### Pitfall 4: Let's Encrypt rate limits
**What goes wrong:** Issuing 5+ certs for the same registered domain within a week hits LE limits.
**Why it happens:** `stats-staging.solid-stats.ru` is the registered domain; all staging subdomains
share the 50-certs-per-registered-domain-per-week limit.
**How to avoid:** Issue both `grafana.` and `errors.` certs in the same bootstrap run (Phase 14).
Never re-issue unnecessarily. The lineage existence check (`[[ -d /etc/letsencrypt/live/$DOMAIN ]]`)
skips re-issuance on subsequent bootstrap runs.
**Warning signs:** certbot exits with "too many certificates already issued".

### Pitfall 5: ufw duplicate rule confusion
**What goes wrong:** Attempting to add `ufw allow 80/tcp` when the rule already exists doesn't
fail, but `ufw status` shows duplicates; `ufw delete` then becomes ambiguous.
**Why it happens:** ufw adds rules even if duplicates exist.
**How to avoid:** Bootstrap for obs-edge should set `SKIP_UFW=1` by default since ports 80/443
are already open from Phase 07. Or check before adding.

### Pitfall 6: DNS not propagated when certbot runs
**What goes wrong:** Operator runs bootstrap immediately after creating DNS A records; certbot
HTTP-01 check fails because DNS hasn't propagated yet.
**Why it happens:** DNS TTL + resolver caches; new records can take 5-60 minutes.
**How to avoid:** Bootstrap runbook must instruct operator to verify DNS with `dig grafana.stats-staging.solid-stats.ru A`
or `curl http://grafana.stats-staging.solid-stats.ru/.well-known/acme-challenge/test` before running
certbot. Script can include a DNS pre-check that exits with a clear message if not resolved.

### Pitfall 7: errors. vhost without upstream causes nginx error
**What goes wrong:** If the errors. vhost's TLS server block has a `proxy_pass` to a non-existent
upstream, nginx may fail to start/reload.
**Why it happens:** nginx resolves upstream addresses at start time.
**How to avoid:** errors. placeholder vhost returns `503 Service Unavailable` with a static
`return 503` directive (no proxy_pass). Or uses `proxy_pass` to a localhost:65535 with
`proxy_connect_timeout 1s` — but the simpler `return 503` is cleaner.

---

## Autonomous vs Operator-Gated Work

### AUTONOMOUS (agent can author without DNS):

| Artifact | Path | Status |
|----------|------|--------|
| `bootstrap-obs-edge.sh` | `scripts/bootstrap-obs-edge.sh` | NEW |
| Grafana nginx vhost | `config/nginx/sites-available/grafana-stats-staging-solid-stats.conf` | NEW |
| errors. placeholder vhost | `config/nginx/sites-available/errors-stats-staging-solid-stats.conf` | NEW |
| Offline validator | `scripts/validate-obs-edge.py` | NEW |
| Operator runbook | `docs/obs-edge-bootstrap.md` | NEW |
| certbot deploy hook | `config/systemd/certbot-deploy-hook.sh` | EXISTING (shared, reused) |
| certbot OnFailure drop-in | `config/systemd/certbot.service.d/onfailure.conf` | EXISTING (shared, reused) |
| certbot failure handler | `config/systemd/certbot-renew-failure.service` | EXISTING (shared, reused) |

### OPERATOR-GATED (requires live VPS + DNS):

| Step | Gate | Instruction |
|------|------|-------------|
| Create DNS A records | Registrar access | `grafana. A 89.223.124.200`, `errors. A 89.223.124.200` |
| Verify DNS propagation | DNS resolution | `dig grafana.stats-staging.solid-stats.ru A @8.8.8.8` returns 89.223.124.200 |
| Run bootstrap (grafana) | DNS resolved | `DOMAIN=grafana.stats-staging.solid-stats.ru UPSTREAM=$(kubectl get svc grafana -n monitoring -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}') ADMIN_EMAIL=... scripts/bootstrap-obs-edge.sh` |
| Run bootstrap (errors) | DNS resolved | `DOMAIN=errors.stats-staging.solid-stats.ru UPSTREAM=placeholder ADMIN_EMAIL=... SKIP_UPSTREAM_CHECK=1 scripts/bootstrap-obs-edge.sh` |
| Smoke-test Grafana HTTPS | Certs issued | `curl -I https://grafana.stats-staging.solid-stats.ru/` → HTTP 200 |
| Verify Grafana login page | HTTPS up | Browser: navigate to URL, confirm login page renders |

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Python 3 stdlib (mirrors `validate-edge.py` pattern) |
| Config file | none — standalone script |
| Quick run command | `python3 scripts/validate-obs-edge.py` |
| Full suite command | `python3 scripts/validate-obs-edge.py` (same — offline only) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| EDGE-01 | DNS A records resolve to 89.223.124.200 | smoke/manual | `dig grafana.stats-staging.solid-stats.ru A` | Operator-run; DNS is external |
| EDGE-02 | Vhost structure: ACME block, HTTP redirect, TLS block, proxy_pass, HSTS | offline structural | `python3 scripts/validate-obs-edge.py` | Fully automated offline |
| EDGE-03 | Cert issued, cert valid, cert CN matches domain | operator-run | `certbot certificates`, `openssl s_client -connect ...` | Post-DNS only |
| MET-07 | Grafana login page served over HTTPS (200 + login form) | smoke/manual | `curl -s https://grafana.stats-staging.solid-stats.ru/login` | Post-cert only |

### Validation Stages

**Stage 1 — OFFLINE (autonomous, before DNS exists):**
`python3 scripts/validate-obs-edge.py` checks:
- `scripts/bootstrap-obs-edge.sh` exists, passes `bash -n`, has `set -euo pipefail`, has `exit 64`
- `config/nginx/sites-available/grafana-stats-staging-solid-stats.conf` exists and contains:
  - `upstream grafana_obs` block with `keepalive`
  - `location /.well-known/acme-challenge/`
  - `return 301` in HTTP block
  - `ssl_certificate`, `options-ssl-nginx.conf`, `ssl-dhparams.pem`
  - `Strict-Transport-Security` HSTS header
  - `proxy_set_header Upgrade` (WebSocket support)
  - NOT a localhost placeholder upstream (must be a 10.x.x.x pattern or UPSTREAM_PLACEHOLDER)
- `config/nginx/sites-available/errors-stats-staging-solid-stats.conf` exists and contains:
  - ACME block, HTTP redirect, TLS block
  - `return 503` (no proxy_pass — placeholder)
- `docs/obs-edge-bootstrap.md` exists
- Shared systemd artifacts still in place (inherited from Phase 07 check)

**Stage 2 — LIVE (operator, post-DNS + post-certbot):**
Documented in `docs/obs-edge-bootstrap.md` as operator-only steps:
- `dig grafana.stats-staging.solid-stats.ru A` → 89.223.124.200
- `nginx -t` on VPS
- `curl -I https://grafana.stats-staging.solid-stats.ru/` → HTTP 200
- `curl -s https://grafana.stats-staging.solid-stats.ru/login | grep -i "grafana"` → login page
- `certbot renew --dry-run` (renewal pipeline smoke-test)

### Wave 0 Gaps

- [ ] `scripts/validate-obs-edge.py` — covers EDGE-02 offline structural validation
- [ ] No test framework install needed (Python 3 stdlib only)

---

## Security Domain

`security_enforcement: true`, ASVS level 2.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (Grafana) | Grafana local-user auth via GF_SECURITY_ADMIN_*; already deployed in Phase 13 |
| V3 Session Management | partial | Grafana manages its own sessions; nginx passes cookies transparently |
| V4 Access Control | no | Not applicable to nginx proxy |
| V5 Input Validation | no | nginx proxies requests; Grafana validates inputs |
| V6 Cryptography | yes | TLS via certbot (Let's Encrypt); options-ssl-nginx.conf enforces TLS 1.2+ |
| V9 Communications Security | yes | HSTS header (`max-age=31536000; includeSubDomains`), TLS only |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cert expired, plain HTTP served | Spoofing | HSTS + `certbot.timer` renewal + OnFailure handler already wired |
| k3s API exposed on public interface | Elevation | wg0-qualified ufw 6443 rule from Phase 07 (not changed here) |
| Grafana anonymous access | Information Disclosure | `GF_AUTH_ANONYMOUS_ENABLED` default is false; no config change needed |
| HTTP serving without redirect | Spoofing | HTTP server block has `return 301`; ACME exception is path-scoped only |

---

## Code Examples

### ClusterIP Discovery (inside bootstrap script)
```bash
# Source: kubectl docs + existing pattern in config/nginx/sites-available/stats-staging-solid-stats.conf
GRAFANA_UPSTREAM=$(kubectl get svc grafana -n monitoring \
  -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}')
if [[ -z "$GRAFANA_UPSTREAM" || "$GRAFANA_UPSTREAM" == ":" ]]; then
  echo "FATAL: Could not discover Grafana Service ClusterIP — is Grafana deployed?" >&2
  exit 1
fi
echo "Grafana upstream: $GRAFANA_UPSTREAM"
```

### HTTP-Only Temp Vhost (written to disk before cert issuance)
```bash
# Written by bootstrap script to a temp file, then installed and reloaded
# so nginx serves the ACME challenge endpoint
TEMP_VHOST=$(mktemp)
cat > "$TEMP_VHOST" <<'VHOST'
server {
    listen 80;
    listen [::]:80;
    server_name DOMAIN_PLACEHOLDER;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}
VHOST
sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN/g" "$TEMP_VHOST"
```

### Certbot Per-Domain Issuance (safe pattern)
```bash
# Source: bootstrap-edge.sh pattern, adapted
if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  echo "Certificate lineage already exists for $DOMAIN — skipping issuance"
elif [[ "${SKIP_CERTBOT}" == "1" ]]; then
  echo "SKIP_CERTBOT=1 — skipping certbot issuance (set to 0 after DNS resolves)"
else
  certbot certonly \
    --authenticator webroot \
    --installer none \
    --no-eff-email \
    --agree-tos \
    --email "$ADMIN_EMAIL" \
    --webroot-path "$WEBROOT_PATH" \
    -d "$DOMAIN"
fi
```

### nginx -t Gate with Auto-Restore (exact pattern from bootstrap-edge.sh)
```bash
if ! nginx -t 2>&1; then
  echo "FATAL: nginx config invalid after vhost install" >&2
  if [[ -f "$BAK_VHOST" ]]; then
    cp "$BAK_VHOST" "$VHOST_CONF"
  else
    rm -f "$VHOST_CONF" "$NGINX_SITES_ENABLED/$(basename $VHOST_CONF)"
  fi
  if ! nginx -t 2>&1; then
    echo "FATAL: nginx config still invalid after restore — refusing reload" >&2
    exit 1
  fi
  exit 1
fi
if ! systemctl reload nginx; then
  echo "FATAL: nginx reload failed despite passing nginx -t" >&2
  exit 1
fi
```

---

## Runtime State Inventory

Not applicable — Phase 14 is greenfield bootstrap of new nginx vhosts. No rename/refactor.

Existing state to be aware of (NOT modified):
- `/etc/nginx/sites-available/stats-staging-solid-stats.conf` — DO NOT TOUCH
- `/etc/letsencrypt/live/stats-staging.solid-stats.ru/` — DO NOT TOUCH
- `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` — shared; obs bootstrap refreshes it via idempotent `cp`
- `/etc/systemd/system/certbot.service.d/onfailure.conf` — shared; obs bootstrap refreshes it

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| nginx | vhost install, reload | ✓ (Phase 07) | host-installed | — |
| certbot | TLS cert issuance | ✓ (Phase 07) | host-installed | — |
| ufw | firewall rules | ✓ (Phase 07) | host-installed | SKIP_UFW=1 (rules already open) |
| kubectl | ClusterIP discovery | ✓ (k3s bundle on VPS) | host k3s | — |
| DNS resolution | certbot HTTP-01 | ✗ (currently NXDOMAIN) | — | SKIP_CERTBOT=1 until DNS exists |
| Port 80 public | ACME challenge | ✓ (Phase 07 ufw rule) | open | — |
| Port 443 public | HTTPS serving | ✓ (Phase 07 ufw rule) | open | — |

**Missing dependencies with no fallback:**
- DNS A records — blocks certbot; entire operator live-run is gated on this

**Missing dependencies with fallback:**
- DNS not resolved → `SKIP_CERTBOT=1` allows full script authoring and offline validation

---

## Open Questions

1. **Grafana `root_url` configuration**
   - What we know: Grafana ConfigMap has `domain = ''` (empty); nginx sends correct `Host` header
   - What's unclear: Whether Grafana redirects to HTTP after login when behind a reverse proxy
   - Recommendation: Don't pre-emptively change Phase 13 config. If post-deployment the login
     redirect goes to `http://` instead of `https://`, add `root_url = https://grafana.stats-staging.solid-stats.ru`
     to the Grafana ConfigMap and redeploy. Flag this as a known post-deploy check in the runbook.

2. **errors. placeholder vhost: `return 503` vs HTTP-only redirect**
   - What we know: TLS vhost with no backend needs a valid response to avoid confusion
   - What's unclear: Whether certbot dry-run is affected by a 503 response from the vhost
   - Recommendation: `return 503` in TLS block is correct (certbot checks /.well-known/acme-challenge,
     not `/`). ACME block in HTTP serves the challenge file; root redirect goes to HTTPS which
     returns 503 — this is acceptable for a placeholder.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | nginx, certbot, kubectl are already installed on the staging VPS from Phase 07 | Environment Availability | Low — Phase 07 bootstrap is complete; bootstrap-obs-edge.sh includes `apt-get install -y` idempotent fallback |
| A2 | Grafana WebSocket (Grafana Live) requires `proxy_set_header Upgrade` + `Connection "upgrade"` | Patterns — vhost | Low — at worst Grafana Live streaming fails; main UI unaffected; headers are harmless if unused |
| A3 | Grafana `domain = ''` + `proxy_set_header Host $host` is sufficient for correct redirect behavior | Open Questions | Low-Medium — if login redirects to HTTP, add root_url to ConfigMap (1-line fix) |
| A4 | k3s ClusterIPs in the 10.43.x.x CIDR are routable from the VPS host without additional routing config | Architecture — ClusterIP wiring | HIGH risk if wrong, LOW probability: the existing vhost at 10.43.94.103:3000 is live and serving traffic, confirming this is true |

---

## Sources

### Primary (codebase direct read — HIGH confidence for this codebase's patterns)
- `scripts/bootstrap-edge.sh` — canonical adopt-reconcile implementation, all 7 steps verified
- `scripts/teardown-edge.sh` — reversibility pattern
- `scripts/validate-edge.py` — offline validator pattern (structural checks, `bash -n`, idempotency markers)
- `config/nginx/sites-available/stats-staging-solid-stats.conf` — live vhost proving ClusterIP routing works
- `config/systemd/certbot-deploy-hook.sh` — deploy hook (nginx -t gate + reload)
- `config/systemd/certbot.service.d/onfailure.conf` — OnFailure drop-in
- `config/systemd/certbot-renew-failure.service` — failure handler
- `docs/edge-bootstrap.md` — operator runbook, all design decisions documented
- `k8s/observability/50-grafana.yaml` — Grafana Service (ClusterIP, port 80 → container 3000)
- `.planning/phases/14-public-edge-grafana-tls/14-CONTEXT.md` — locked decisions, DNS gate
- `.planning/REQUIREMENTS.md` — EDGE-01..03, MET-07
- `AGENTS.md` / `.planning/codebase/ARCHITECTURE.md` — script conventions, ClusterIP routing confirmation

### Secondary (operator memory)
- `staging-vps-access` memory note — `certbot --full-renew` hangs on auth cert (Pitfall 1)

---

## Metadata

**Confidence breakdown:**
- Adopt-reconcile bootstrap pattern: HIGH — full source available; mirrors existing working code exactly
- ClusterIP host routing mechanism: HIGH — confirmed by live vhost using 10.43.94.103:3000
- Grafana WebSocket headers: ASSUMED — reasonable inference from Grafana docs knowledge
- certbot per-domain flow: HIGH — mirrors working Phase 07 pattern
- DNS operator gate: HIGH — CONTEXT.md documents current NXDOMAIN state

**Research date:** 2026-06-14
**Valid until:** 2026-07-14 (stable tech; nginx/certbot/k3s patterns don't change)
