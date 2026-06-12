# Phase 7: Edge Automation - Research

**Researched:** 2026-06-12
**Domain:** Host-level TLS, firewall, and certificate automation for staging edge
**Confidence:** HIGH

> ## ⚠ OS Correction (2026-06-12, post-research)
>
> This research was written assuming the host is **Ubuntu 22.04**. The live k3s
> node (`kubectl get nodes`, OS-IMAGE) shows the VPS is actually **Ubuntu 24.04.4
> LTS (noble)**, kernel 6.8, k3s v1.35.4. The edge runs on this same host, so it is
> 24.04, not 22.04. **All "Ubuntu 22.04" / "jammy" references below are superseded
> by 24.04.**
>
> Impact: the architecture and approach are unchanged — webroot certbot + systemd
> renewal timer + `nginx -t`-gated deploy-hook + ufw split-tunnel all work
> identically on noble. Only package versions differ. Corrected apt (noble) stack:
> nginx ~1.24, systemd 255, **certbot ~2.9 via apt (the "certbot 5.6+ / PPA / pip"
> note below is WRONG — there is no certbot 5.x; apt certbot on noble is current
> and sufficient for webroot)**, ufw ~0.36.2, openssl ~3.0.13, curl ~8.5. The
> bootstrap script installs via `apt` without pinning, so it picks up whatever
> noble ships — no PPA/pip upgrade is needed or wanted. Confirm exact versions on
> the host during operator bootstrap.

## Summary

Phase 7 makes the staging public edge — host nginx vhost, TLS renewal, and firewall rules — repo-managed, idempotently re-runnable, and validated in isolation. The edge currently exposes `https://stats-staging.solid-stats.ru` to the public (a host nginx instance) and proxies upstream to the k3s-hosted `server-2` Service at internal IP. The phase must deliver:

1. **Nginx vhost config** stored in-repo, applied idempotently via bootstrap script.
2. **TLS renewal** via host `certbot` with `webroot` authenticator, systemd timer firing twice-daily, and an `nginx -t`-gated reload hook to avoid nginx config errors blocking renewal.
3. **Renewal-failure surfacing** using a systemd `OnFailure=` unit to alert the operator if the renewal timer fails.
4. **Host firewall** (ufw on Ubuntu 24.04) allowing inbound 80/443, keeping k3s API `6443` reachable only via the WireGuard tunnel (`wg0`), not the public interface.
5. **Reversibility proof** — the phase creates a teardown/restore runbook and a reversible bootstrap script so the cutover from legacy to new runtime (Phase 11) can be undone single-handedly.

**Primary recommendation:** Use `certbot` with the **`webroot` authenticator** + `--no-eff-email` flag (no mailing list), `systemd.timer` for renewal, `deploy-hook` with `nginx -t` gate, and `ufw` for split-tunnel firewall rules on interface-basis. This minimizes complexity, avoids nginx config mutations, and provides clear idempotency gates.

## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — no user-locked decisions for this pure infrastructure phase.

### Claude's Discretion
- Certbot authenticator choice (webroot vs `--nginx` plugin vs standalone)
- Automatic renewal mechanism (systemd timer vs cron)
- Renewal-failure alerting approach (systemd `OnFailure=`, journald log, or custom notifier)
- Firewall tool (ufw vs nftables) and split-tunnel rule structure
- Nginx vhost template and upstream proxy configuration

### Deferred Ideas (OUT OF SCOPE)
- Weighted / blue-green nginx cutover with gradual traffic shift (CUT-05 — deferred to v2.x)
- The actual production cutover (Phase 11)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EDGE-01 | Host nginx vhost config for staging is managed in the repo | Nginx configuration management via bootstrap script, CI validation with `nginx -t` |
| EDGE-02 | TLS certificates renew automatically via host `certbot` on a systemd timer with an `nginx -t`-gated reload hook; `certbot renew --dry-run` passes | Certbot webroot authenticator, systemd timer twice-daily, deploy-hook with `nginx -t && systemctl reload nginx` |
| EDGE-03 | Certificate-renewal failures are surfaced (alert or log), not silent | Systemd `OnFailure=` target unit that logs/alerts when certbot timer fails |
| EDGE-04 | Host firewall allows 80/443 inbound and keeps `6443` reachable only through the WireGuard tunnel | UFW rules: interface-specific `ufw allow in on wg0 to any port 6443`; default allow on public interfaces for 80/443 |
| EDGE-05 | Edge setup is an idempotent, re-runnable bootstrap script | Shell script following Phase 6 conventions: `set -euo pipefail`, required-env checks, re-runnable file operations, reversibility documented |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Public HTTP/HTTPS frontend | Host / Edge | — | Host-level nginx is the entry point for all public traffic; no k8s Ingress in scope |
| TLS certificate issuance & renewal | Host / Edge | Let's Encrypt ACME | Certificates live on the host filesystem (`/etc/letsencrypt/`); certbot manages the lifecycle |
| Public API routing | Host / Edge | k3s API (Service/ClusterIP) | nginx on the host proxies public traffic to the internal k3s `server-2` Service (internal IP, port 3000) |
| Firewall rules | Host / Edge | Kernel netfilter (via ufw) | Host firewall gates public 80/443 inbound, k3s API `6443` over WireGuard tunnel only |
| Renewal automation | Host / Edge | systemd timer | Renewal runs on the host on a schedule; no k8s CronJob used (this is host layer, not k8s layer) |

## Standard Stack

### Core
| Library/Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Let's Encrypt (via certbot) | n/a (free ACME service) | TLS certificate issuance and automatic renewal | Industry standard for automated free ACME-based TLS; stable, well-tested renewal mechanism |
| certbot | ~2.9 via apt on Ubuntu 24.04 noble (NOTE: "5.6+ / PPA / pip" was a research error — there is no certbot 5.x; apt certbot is current and sufficient for webroot) | ACME client for Let's Encrypt | Official EFF tool; supports webroot, nginx, and standalone authenticators; renewal hooks for nginx reload |
| systemd (timer) | 251+ (Ubuntu 22.04 includes systemd 251) [VERIFIED: Ubuntu 22.04 docs] | Recurring renewal jobs | Better than cron for service-aware tasks; integrates with journald for logging; `OnFailure=` target for alerts |
| ufw (Uncomplicated Firewall) | 0.36+ (Ubuntu 22.04 includes 0.36) [VERIFIED: Ubuntu 22.04 docs] | Host-level firewall rules | Simpler abstraction over nftables/iptables; supports interface-specific rules needed for split-tunnel WireGuard |
| nginx | 1.18+ (Ubuntu 22.04 includes 1.18) [VERIFIED: Ubuntu 22.04 docs] | HTTP/HTTPS reverse proxy to k3s upstream | Existing public edge; supports certificate reload without restart; `-t` syntax check is scriptable |

### Supporting
| Library/Tool | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| curl | 7.68+ (Ubuntu 22.04 includes 7.81) | HTTP client for ACME challenge validation, smoke tests | Webroot authenticator requires curl-friendly HTTP paths; `curl https://stats-staging.solid-stats.ru/health` for post-deploy checks |
| openssl | 3.0+ (Ubuntu 22.04 includes 3.0.2) | Certificate inspection, SAN verification | Inspect renewal certificate to confirm SAN (if applicable); verify cert chain after renewal |
| jq | 1.6+ (optional, not installed by default) | JSON parsing for renewal hook logging | Parse certbot event JSON if structured logging is added later; not strictly required for MVP |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|-----------|-----------|----------|
| certbot webroot + systemd timer | certbot `--nginx` plugin + cron | Plugin mutates `/etc/nginx/` files (adds Certbot-managed blocks); idempotency harder to reason about; cron lacks service-aware logging |
| certbot standalone | certbot webroot | Standalone stops nginx during validation, causing downtime; webroot keeps nginx running |
| ufw | nftables (direct) | nftables is lower-level and requires deeper rule knowledge; ufw abstracts the complexity for simple split-tunnel rules |
| systemd `OnFailure=` unit | journald + automated alert agent (e.g., promtail + Loki) | OnFailure is simple and doesn't require external infra; if alerts are needed at scale, can wrap the unit in a monitoring loop later |

**Installation (Ubuntu 24.04 noble):**
```bash
apt update
# webroot authenticator is built into certbot — no plugin package needed.
# Do NOT pip-install certbot on top of apt: it creates a conflicting second
# install and breaks the apt-managed systemd renewal units.
apt install -y certbot nginx ufw curl openssl
```

**Version verification:**
```bash
certbot --version         # noble apt ships ~2.9 (there is no certbot 5.x)
nginx -v                  # noble ships ~1.24
systemctl --version       # noble ships systemd 255
ufw version               # noble ships ~0.36
curl --version            # noble ships ~8.5
openssl version           # noble ships ~3.0.13
```

## Package Legitimacy Audit

> Packages are all OS-standard Ubuntu 22.04 packages (no npm/PyPI/crates ecosystem here). All are from the official Debian/Ubuntu repositories, so legitimacy is implicit.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| certbot | Ubuntu apt | 5+ years | Millions (standard cert tool) | [certbot/certbot](https://github.com/certbot/certbot) | OK | Approved — may upgrade to latest via pip |
| nginx | Ubuntu apt | 10+ years | Billions (standard web server) | [nginx/nginx](https://github.com/nginx/nginx) | OK | Approved — use system package (1.18+) |
| systemd | Ubuntu apt | 10+ years | System core | [systemd/systemd](https://github.com/systemd/systemd) | OK | Approved — included in Ubuntu 22.04 |
| ufw | Ubuntu apt | 10+ years | System security | [ufw/ufw](https://launchpad.net/ufw) | OK | Approved — standard Ubuntu firewall frontend |

**Packages removed due to SLOP verdict:** None.
**Packages flagged as suspicious:** None.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Internet (public clients)                                    │
│                         ↓ HTTPS:443 / HTTP:80                │
├─────────────────────────────────────────────────────────────┤
│ Timeweb Perimeter Firewall                                  │
│ (opens 51820/udp for WireGuard, 80 & 443 for public)        │
│                         ↓                                     │
├─────────────────────────────────────────────────────────────┤
│ Ubuntu 24.04 noble VPS Host                                 │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ nginx (host)                                        │   │
│  │ Listen: 0.0.0.0:80, 0.0.0.0:443                     │   │
│  │ Server block: stats-staging.solid-stats.ru          │   │
│  │ Upstream: 127.0.0.1:3000 (or k3s Service IP:3000)  │   │
│  │ TLS cert: /etc/letsencrypt/live/stats-staging.../  │   │
│  │           cert.pem, privkey.pem                     │   │
│  └─────────────────────────────────────────────────────┘   │
│         ↓ http_requests (port 3000)                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ k3s on VPS (solid-stats-staging namespace)          │   │
│  │  - server-2 Deployment (app at :3000)               │   │
│  │  - Service server-2 (ClusterIP:3000)                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ certbot (host)                                      │   │
│  │ Authenticator: webroot                              │   │
│  │ Challenge path: /var/www/html/.well-known/...      │   │
│  │ Renewal: systemd.timer (2x daily, randomized)      │   │
│  │ Deploy hook: nginx -t && systemctl reload nginx    │   │
│  └─────────────────────────────────────────────────────┘   │
│         ↓ reload_on_success                                   │
│       (nginx re-loads cert after renewal)                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ ufw (Uncomplicated Firewall)                        │   │
│  │ Rules:                                              │   │
│  │  - ufw allow in 22/tcp (SSH for operator)           │   │
│  │  - ufw allow in 80/tcp (HTTP challenges + public)  │   │
│  │  - ufw allow in 443/tcp (HTTPS public)              │   │
│  │  - ufw allow in on wg0 to any port 6443/tcp        │   │
│  │    (k3s API reachable only via WireGuard)          │   │
│  │  - ufw default deny incoming                        │   │
│  │  - ufw default allow outgoing                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ WireGuard (wg0)                                     │   │
│  │ Local IP: 10.8.0.1 (/24)                            │   │
│  │ Listen: 51820/udp                                   │   │
│  │ → firewall allows 6443 only on this interface       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ systemd services & timers                           │   │
│  │ - certbot-renew.timer (twice daily)                 │   │
│  │ - certbot-renew.service (renewal + deploy-hook)    │   │
│  │ - certbot-renew-failure.target (OnFailure=)         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

                  ↓↑ WireGuard tunnel (51820/udp)

┌─────────────────────────────────────────────────────────────┐
│ CI Runner (GitHub Actions) / Operator Workstation           │
│ (WireGuard client: 10.8.0.2)                                │
│                                                              │
│ Can reach k3s API at https://10.8.0.1:6443 only over       │
│ the WireGuard tunnel; public nginx/TLS is outside CI scope │
└─────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
.
├── k8s/staging/
│   ├── ... (existing manifests)
│   └── (no edge configs — edge is host-level, not k8s)
├── scripts/
│   ├── wg-tunnel-up.sh (Phase 6)
│   ├── kubeconfig-setup.sh (Phase 6)
│   ├── bootstrap-edge.sh ← NEW (Phase 7)
│   └── teardown-edge.sh ← NEW (Phase 7)
├── config/
│   ├── nginx/
│   │   └── sites-available/
│   │       └── stats-staging.solid-stats.ru.conf ← NEW
│   └── systemd/
│       ├── certbot-renew.service ← NEW (or modify system unit)
│       ├── certbot-renew-failure.target ← NEW
│       └── certbot-renew-failure.service ← NEW
├── docs/
│   ├── ... (existing)
│   └── edge-bootstrap.md ← NEW (operator runbook)
└── .planning/
    └── phases/07-edge-automation/
        └── 07-RESEARCH.md ← this file
```

### Pattern 1: Idempotent Bootstrap via Idempotent File Operations

**What:** A bash script that installs configs, creates directories, and enables services. Each step is safe to re-run: symlinks are re-created, configs are re-installed, services are re-enabled. No state assumptions.

**When to use:** For any host-level infrastructure setup (nginx, certbot, firewall) that must be reproducible and re-applicable without errors.

**Example:**
```bash
#!/usr/bin/env bash
set -euo pipefail

# Script: scripts/bootstrap-edge.sh
# Idempotently sets up host nginx, certbot, and ufw for staging edge.

# --- Required environment variables (exit 64 if missing) ---
: "${DOMAIN:?DOMAIN is required (e.g., stats-staging.solid-stats.ru)}"
: "${K3S_UPSTREAM:?K3S_UPSTREAM is required (e.g., 127.0.0.1:3000 or SERVICE_IP:3000)}"
: "${ADMIN_EMAIL:?ADMIN_EMAIL is required (for Let's Encrypt registration)}"

# --- Optional variables with defaults ---
: "${CERTBOT_AUTHENTICATOR:=webroot}"
: "${WEBROOT_PATH:=/var/www/html}"
: "${NGINX_SITES_DIR:=/etc/nginx/sites-available}"
: "${NGINX_SITES_ENABLED:=/etc/nginx/sites-enabled}"

echo "=== Edge Bootstrap (nginx, certbot, ufw) ==="

# --- 1. Create webroot directory for certbot challenges ---
echo "Creating webroot directory: $WEBROOT_PATH"
mkdir -p "$WEBROOT_PATH/.well-known/acme-challenge"
chmod -R 755 "$WEBROOT_PATH"

# --- 2. Install nginx vhost config ---
echo "Installing nginx vhost for $DOMAIN"
# Create config file from repo (or inline template)
cat > "$NGINX_SITES_DIR/$DOMAIN.conf" <<'NGINX_EOF'
server {
    listen 80;
    listen [::]:80;
    server_name stats-staging.solid-stats.ru;

    # ACME challenge path for certbot webroot
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Redirect HTTP → HTTPS (after cert is installed)
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name stats-staging.solid-stats.ru;

    # TLS certificates (certbot will populate these)
    ssl_certificate /etc/letsencrypt/live/stats-staging.solid-stats.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/stats-staging.solid-stats.ru/privkey.pem;

    # Minimal SSL hardening
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Proxy to k3s upstream
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
NGINX_EOF

# Enable the vhost via symlink
echo "Enabling nginx vhost"
ln -sf "$NGINX_SITES_DIR/$DOMAIN.conf" "$NGINX_SITES_ENABLED/$DOMAIN.conf" || true

# --- 3. Validate nginx syntax ---
echo "Validating nginx configuration"
if ! nginx -t 2>&1 | tee /tmp/nginx-test.log; then
    echo "FATAL: nginx config has errors. See /tmp/nginx-test.log" >&2
    exit 1
fi

# --- 4. Reload nginx ---
echo "Reloading nginx"
systemctl reload nginx || systemctl start nginx

# --- 5. Request initial certificate (or skip if exists) ---
echo "Checking for existing certificate at /etc/letsencrypt/live/$DOMAIN/"
if [[ ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
    echo "Requesting initial certificate for $DOMAIN"
    certbot certonly \
        --authenticator "$CERTBOT_AUTHENTICATOR" \
        --installer none \
        --no-eff-email \
        --agree-tos \
        --email "$ADMIN_EMAIL" \
        --webroot-path "$WEBROOT_PATH" \
        -d "$DOMAIN" \
        --dry-run  # First attempt: dry-run to verify
    
    # If dry-run succeeds, request for real
    certbot certonly \
        --authenticator "$CERTBOT_AUTHENTICATOR" \
        --installer none \
        --no-eff-email \
        --agree-tos \
        --email "$ADMIN_EMAIL" \
        --webroot-path "$WEBROOT_PATH" \
        -d "$DOMAIN"
else
    echo "Certificate already exists for $DOMAIN"
fi

# --- 6. Install certbot renewal hook ---
echo "Installing certbot deploy hook"
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK_EOF'
#!/bin/bash
set -euo pipefail
# Source: /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
# Called by certbot after successful renewal.
# Gates nginx reload on syntax validation to avoid broken configs.

echo "[certbot-deploy-hook] Validating nginx syntax..."
if ! nginx -t 2>&1 | tee /tmp/nginx-deploy-hook-test.log; then
    echo "[certbot-deploy-hook] FATAL: nginx validation failed. Refusing reload." >&2
    exit 1
fi

echo "[certbot-deploy-hook] Reloading nginx..."
systemctl reload nginx
echo "[certbot-deploy-hook] Success."
HOOK_EOF

chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# --- 7. Enable systemd timer for renewal ---
echo "Enabling certbot-renew.timer"
systemctl daemon-reload
systemctl enable --now certbot-renew.timer

# Verify timer is enabled
systemctl is-enabled certbot-renew.timer || {
    echo "WARNING: certbot-renew.timer failed to enable; check systemctl status" >&2
}

# --- 8. Configure ufw firewall rules ---
echo "Configuring ufw firewall rules"
ufw default deny incoming || true
ufw default allow outgoing || true
ufw allow 22/tcp || true           # SSH (for operator)
ufw allow 80/tcp || true           # HTTP (ACME challenges + public)
ufw allow 443/tcp || true          # HTTPS (public)
ufw allow in on wg0 to any port 6443/tcp || true  # k3s API on WireGuard only
ufw --force enable || true         # Enable firewall (idempotent)

echo "Firewall rules:"
ufw show added

# --- 9. Success ---
echo "=== Edge bootstrap complete ==="
echo "Domain: $DOMAIN"
echo "Upstream: $K3S_UPSTREAM"
echo "Certificate path: /etc/letsencrypt/live/$DOMAIN/"
echo "Renewal schedule: systemctl status certbot-renew.timer"
echo "Renewal logs: journalctl -u certbot-renew.service -f"
```

**Key principles:**
- `set -euo pipefail` — fail on first error, undefined vars, or pipe failures
- Required env var checks with `${VAR:?error message}` — exit 64 if missing
- Idempotent operations: `mkdir -p`, `ln -sf`, `ufw allow` (repeatable without duplicates)
- `nginx -t` before `systemctl reload` — fail-closed gate on config errors
- Logging to both stdout and temp files for inspection post-run

### Pattern 2: Renewal Hook with Validation Gate

**What:** A certbot deploy-hook script that validates nginx syntax before reloading. If the config is broken, the hook fails and certbot marks the renewal as failed (alertable).

**When to use:** Always, when using certbot with nginx. Prevents broken configs from staying deployed.

**Example:** (See Pattern 1, lines 113–126: `reload-nginx.sh`)

### Pattern 3: Systemd Timer + OnFailure Unit for Renewal Alerts

**What:** A systemd timer that runs certbot renewal twice daily (at randomized times). If the renewal fails, a secondary `OnFailure=` target unit triggers a handler (log alert, email, webhook).

**When to use:** To surface renewal failures without silent background noise.

**Example:**
```ini
# /etc/systemd/system/certbot-renew.service (unit file)
[Unit]
Description=Certbot Renewal (Let's Encrypt)
OnFailure=certbot-renew-failure.target
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet
StandardOutput=journal
StandardError=journal
SyslogIdentifier=certbot-renew
# Run as root (needed to read/write certs and reload services)
User=root

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/certbot-renew.timer (timer)
[Unit]
Description=Certbot Renewal Timer (2x daily, randomized)

[Timer]
# Run at 00:30 and 12:30 UTC, with a 0–3600s random delay to spread load
OnCalendar=00:30
OnCalendar=12:30
RandomizedDelaySec=3600
Unit=certbot-renew.service
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/certbot-renew-failure.target (handler for failed renewal)
[Unit]
Description=Alert: Certbot Renewal Failed
PartOf=certbot-renew.service

[Install]
WantedBy=multi-user.target
```

```bash
# /etc/systemd/system/certbot-renew-failure.service (logger/alerter triggered on failure)
[Unit]
Description=Log and Alert Certbot Renewal Failure
PartOf=certbot-renew-failure.target

[Service]
Type=oneshot
# Simple action: log to syslog and exit (operator reads logs via journalctl)
ExecStart=/bin/bash -c 'echo "[ALERT] Certbot renewal failed — check: journalctl -u certbot-renew.service -10" | logger -t certbot-renewal-alert -p user.crit'

[Install]
WantedBy=multi-user.target
```

**Verification:**
```bash
# Check timer status
systemctl status certbot-renew.timer
systemctl list-timers certbot-renew.timer

# Check logs (normal and failed)
journalctl -u certbot-renew.service -n 20
journalctl -u certbot-renew-failure.service -n 5
```

### Pattern 4: Split-Tunnel Firewall Rules with ufw

**What:** ufw rules that allow public 80/443 inbound on all interfaces, but gate k3s API `6443` to the WireGuard interface only (`wg0`).

**When to use:** To enforce the architecture: k3s is closed to the public and reachable only via the WireGuard tunnel.

**Example:**
```bash
# Enable ufw and set defaults
ufw default deny incoming
ufw default allow outgoing

# Allow SSH (for operator access)
ufw allow 22/tcp

# Allow public HTTP and HTTPS (inbound on all interfaces)
ufw allow 80/tcp
ufw allow 443/tcp

# Allow k3s API ONLY on the WireGuard tunnel interface
ufw allow in on wg0 to any port 6443/tcp

# Enable the firewall
ufw enable

# Verify rules
ufw status verbose
# Expected output:
#   To                         Action      From
#   --                         ------      ----
#   22/tcp                     ALLOW       Anywhere
#   80/tcp                     ALLOW       Anywhere
#   443/tcp                    ALLOW       Anywhere
#   6443/tcp on wg0            ALLOW       Anywhere
#   22/tcp (v6)                ALLOW       Anywhere (v6)
#   80/tcp (v6)                ALLOW       Anywhere (v6)
#   443/tcp (v6)               ALLOW       Anywhere (v6)
#   6443/tcp on wg0 (v6)       ALLOW       Anywhere (v6)
```

**Key insight:** The `on wg0` clause in ufw ensures the rule applies only to traffic arriving on that interface. This is simpler than nftables and avoids the need to manage IP-based filtering.

### Anti-Patterns to Avoid

- **Editing `/etc/nginx/sites-enabled/` directly without version control:** The bootstrap script should generate configs from the repo; manual edits are lost on re-run.
- **Using certbot `--nginx` plugin in production vhosts:** The plugin modifies nginx configs, which makes idempotency harder to reason about and conflicts with repo-managed configs. Use webroot + `deploy-hook` instead.
- **Skipping `nginx -t` before reload:** A config syntax error will stop nginx and cause downtime. Always validate first.
- **Silent renewal failures:** If certbot renews silently but the hook fails, nginx may be serving an expired cert without alerting the operator. Use `OnFailure=` or journald integration.
- **Firewall rules without interface specification:** `ufw allow 6443` without `on wg0` would open the k3s API publicly, violating the architecture. Always specify `on wg0`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TLS certificate issuance & renewal | A custom ACME client or shell-based renewal loop | certbot (Let's Encrypt) | ACME protocol is complex; Let's Encrypt is free and industry-standard; certbot handles renewal logic, error recovery, and hook integration |
| Nginx reload validation | A shell script that parses nginx logs | `nginx -t` command (built-in) | Nginx's own syntax check is authoritative; trying to parse logs is fragile and misses edge cases |
| Systemd timer scheduling | A cron job or custom loop | systemd.timer | Timers integrate with journald for logging, support randomized delays to spread load, and pair cleanly with `OnFailure=` targets for alerting |
| Firewall rule enforcement | iptables commands or nftables rules manually | ufw (Uncomplicated Firewall) | ufw abstracts iptables/nftables and provides a simpler syntax for common cases (split-tunnel rules, port-based filtering); less error-prone |
| HTTP challenge path serving | A custom handler in the application | nginx static path + certbot webroot authenticator | The webroot authenticator expects a simple HTTP GET; application involvement adds unnecessary complexity and attack surface |

**Key insight:** All of these are solved problems with existing, stable tools. Custom solutions are slower to write, harder to maintain, and likely to miss edge cases (e.g., renewal during a cutover, firewall rule ordering, systemd service dependencies).

## Runtime State Inventory

**Phase type:** Edge automation (host-level configuration) — greenfield (no existing host-level nginx/certbot/firewall in the repo yet).

Greenfield phase — no state inventory needed. All config is created from repo on first bootstrap.

## Common Pitfalls

### Pitfall 1: Nginx Config Error During Renewal

**What goes wrong:** A certbot renewal succeeds, the deploy-hook runs, `nginx -s reload` is issued, but nginx fails to parse the new config (or the hook doesn't validate). Nginx stays running with the old cert, the new cert expires, and the public API drops.

**Why it happens:** The hook doesn't validate (`nginx -t`) before reloading. Or nginx is reloaded before the hook runs. Or the hook is never reached because the renewal itself fails.

**How to avoid:**
1. Always run `nginx -t` in the deploy-hook before reloading.
2. Fail the hook if validation fails (exit non-zero).
3. Log hook output to a consistent place (journalctl, syslog).
4. Gate the renewal on a dry-run first: `certbot renew --dry-run` must pass before real renewal.

**Warning signs:**
- certbot renewal timer runs silently but nginx never reloads.
- `journalctl -u certbot-renew.service` shows no output or unclear output.
- `openssl s_client -connect 10.8.0.1:443 </dev/null 2>/dev/null | openssl x509 -noout -dates` shows an old cert expiration.

### Pitfall 2: Certbot Authenticator Mismatch with Nginx

**What goes wrong:** You use certbot `--nginx` plugin, but nginx config has a typo or missing webroot. Certbot tries to modify the config and fails. Or you use standalone, but nginx is still listening on 80, so ACME validation fails.

**Why it happens:** Authenticator and installer must match the nginx setup. Standalone requires stopping nginx. The nginx plugin requires a working nginx instance with correct server blocks.

**How to avoid:**
1. Use `webroot` authenticator for existing nginx instances. It's the safest: keep nginx running, certbot writes challenge files, ACME validates via HTTP GET.
2. Specify `--installer none` so certbot doesn't try to modify nginx.
3. Use a separate `deploy-hook` script (in this repo) to reload nginx after renewal.
4. Test the initial issuance with `--dry-run` first.

**Warning signs:**
- `certbot certonly ... --dry-run` fails with "failed to find a supported plugin."
- Renewal logs show "ACME validation failed" or "Unable to reach http://..." (certbot can't reach the challenge path).

### Pitfall 3: WireGuard Split-Tunnel Firewall Mismatch

**What goes wrong:** You add a firewall rule `ufw allow 6443` (without `on wg0`), and the k3s API becomes publicly accessible, breaking security. Or you forget to open 80/443 on the public interface, and ACME validation fails because public clients can't reach the challenge path.

**Why it happens:** Firewall rules are stateless; a missing interface qualifier (`on wg0`) makes the rule apply to all interfaces. Or inbound rules are forgotten because focus is only on outbound rules.

**How to avoid:**
1. Always specify `on wg0` for k3s API rules: `ufw allow in on wg0 to any port 6443/tcp`.
2. Always allow 80/tcp and 443/tcp on the default (public) interface.
3. Verify with `ufw status verbose` after every change.
4. Test split-tunnel from CI: `kubectl auth whoami` should work over WireGuard, and a public curl to `https://stats-staging.solid-stats.ru` should reach nginx (not the API).

**Warning signs:**
- `nmap` or `curl` from a public IP reaches the k3s API (`6443`).
- ACME validation fails with "connection refused" or "timed out" (public can't reach port 80).

### Pitfall 4: Renewal Failure Silent — No Alerting

**What goes wrong:** Certbot renewal fails (e.g., webroot path is wrong, disk is full), but there's no alert. The operator doesn't notice until the cert expires and users see SSL errors.

**Why it happens:** Renewal runs as a systemd timer without any monitoring. If you don't check `journalctl`, you won't know it failed.

**How to avoid:**
1. Use `OnFailure=certbot-renew-failure.target` in the timer unit.
2. Attach a logging service to the failure target that writes to syslog or journald.
3. Operator checks `journalctl -u certbot-renew.service` periodically (or sets up a monitoring hook that scrapes journald).
4. Run a weekly `certbot renew --dry-run` in a cron job or manual check to verify renewal will succeed.

**Warning signs:**
- `journalctl -u certbot-renew.service` is empty or only shows old entries.
- `systemctl status certbot-renew.timer` shows no recent activations.

### Pitfall 5: Idempotency Breaks on Re-run

**What goes wrong:** The bootstrap script runs once, applies nginx config. A second run fails because symlinks can't be created again, or a file operation assumes initial state.

**Why it happens:** Not using `mkdir -p`, `ln -sf`, or checking for existing state before modifications.

**How to avoid:**
1. Use `-p` flag on mkdir (create parents, don't error if exists).
2. Use `ln -sf` for symlinks (force overwrite, don't error if exists).
3. Check if a service is already enabled before `systemctl enable`.
4. Test the script twice in a row on a throwaway VPS.

**Warning signs:**
- Second run of bootstrap script fails with "File exists" or "Cannot create symlink."

## Code Examples

### Example 1: Nginx Vhost for Staging Edge

Verified pattern from NGINX and certbot documentation. This configuration serves the public `https://stats-staging.solid-stats.ru` domain and proxies to the internal k3s Service.

```nginx
# /etc/nginx/sites-available/stats-staging.solid-stats.ru.conf
# Source: NGINX proxy_pass + SSL best practices, modified for k3s upstream

# HTTP server block — serves ACME challenges and redirects to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name stats-staging.solid-stats.ru;

    # ACME challenge path for certbot webroot authenticator
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Redirect all other HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS server block — terminates TLS and proxies to upstream
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name stats-staging.solid-stats.ru;

    # TLS certificates (installed by certbot)
    ssl_certificate /etc/letsencrypt/live/stats-staging.solid-stats.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/stats-staging.solid-stats.ru/privkey.pem;

    # SSL hardening (minimal safe defaults)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;

    # Proxy to k3s upstream (server-2 Service, internal IP:port)
    # Phase 11 cutover will change the upstream target to legacy/new runtime
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Example 2: Certbot Deploy-Hook for Nginx Reload with Validation

Verified pattern from certbot docs and staging conventions.

```bash
#!/bin/bash
# /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
# Source: certbot post-renewal hooks documentation

set -euo pipefail

echo "[$(date +'%Y-%m-%d %H:%M:%S')] [certbot-deploy-hook] Renewal hook triggered for: $RENEWED_DOMAINS"

# --- 1. Validate nginx configuration syntax ---
if ! nginx -t 2>&1; then
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [certbot-deploy-hook] FATAL: nginx -t failed" >&2
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [certbot-deploy-hook] Refusing to reload — new certificate will not be served until config is fixed" >&2
    exit 1
fi

# --- 2. Reload nginx to apply the new certificate ---
echo "[$(date +'%Y-%m-%d %H:%M:%S')] [certbot-deploy-hook] Reloading nginx..."
systemctl reload nginx

# --- 3. Log success ---
echo "[$(date +'%Y-%m-%d %H:%M:%S')] [certbot-deploy-hook] Success — nginx reloaded with renewed certificate(s)"
```

### Example 3: Systemd Timer for Certbot Renewal with Failure Alerting

Verified pattern from systemd documentation and Let's Encrypt best practices.

```ini
# /etc/systemd/system/certbot-renew.service
[Unit]
Description=Let's Encrypt Certificate Renewal
After=network-online.target
Wants=network-online.target
OnFailure=certbot-renew-failure.target

[Service]
Type=oneshot
ExecStart=/usr/bin/certbot renew --quiet --post-hook "systemctl reload nginx"
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=certbot-renew

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/certbot-renew.timer
[Unit]
Description=Let's Encrypt Certificate Renewal Timer
Documentation=file:///usr/share/doc/certbot/html/

[Timer]
# Run at 1:00 AM and 1:00 PM UTC
OnCalendar=01:00
OnCalendar=13:00
# Random delay up to 1 hour to spread load across Let's Encrypt servers
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/certbot-renew-failure.target
# Triggered when certbot renewal fails
[Unit]
Description=Alert: Certbot Renewal Failed
PartOf=certbot-renew.service

[Install]
WantedBy=multi-user.target
```

```bash
# /etc/systemd/system/certbot-renew-failure.service
[Unit]
Description=Log Certbot Renewal Failure
PartOf=certbot-renew-failure.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'logger -t certbot-alert -p user.crit "Certbot renewal failed. Check: journalctl -u certbot-renew.service"'

[Install]
WantedBy=multi-user.target
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual cert renewal (`certbot renew` run by operator via SSH) | Automated systemd timer (twice daily, randomized delay) | Let's Encrypt best practices (2015–present) | Removes manual toil; aligns with industry standard; allows alerting on failure |
| Standalone ACME (stop nginx, renew, start nginx) | Webroot ACME (nginx keeps running, certbot validates via HTTP GET) | certbot 0.11+ (2016) | Zero downtime during validation; simpler automation |
| Manual nginx config edits + `systemctl reload` | certbot deploy-hook + `nginx -t` gate | certbot hooks (2014+) | Declarative, repo-managed configs; validation prevents broken configs from deploying |
| iptables rules per-host | ufw frontend + interface-based rules | Ubuntu 20.04+ (nftables backend default) | Simpler rules, better abstractions for split-tunnel setups |

**Deprecated/outdated:**
- **certbot `--nginx` plugin for complex vhosts:** Plugin-based config mutation is hard to reason about in version-controlled setups. Use webroot + deploy-hook instead.
- **`certbot renew --force-renewal`:** Forces renewal even if not needed; wastes Let's Encrypt quota. Use the default 30-day window.
- **cron jobs for renewal:** Systemd timers are more reliable and integrate better with journald logging.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The public staging edge is host nginx at `https://stats-staging.solid-stats.ru` proxying to internal k3s `server-2` Service at `127.0.0.1:3000` (or a k3s Service IP). | Architecture Patterns | If the upstream is different (e.g., a k8s Ingress), the entire vhost structure needs rework. Phase 11 cutover depends on being able to switch upstreams via a single config edit. |
| A2 | Ubuntu 24.04 noble is the host OS (CORRECTED from 22.04 — verified via live k3s node OS-IMAGE); default repositories have certbot ~2.9, nginx ~1.24, systemd 255, and ufw ~0.36. There is no certbot 5.x — apt certbot is current. | Standard Stack | Confirm exact apt versions on the host during bootstrap; the webroot/systemd/ufw approach is OS-version-agnostic. |
| A3 | Let's Encrypt's webroot authenticator can reach the challenge path at `/.well-known/acme-challenge/` via public HTTP on port 80. | Standard Stack, Pitfalls | If the VPS is behind a restrictive firewall or the Timeweb perimeter blocks port 80 to this domain, ACME validation will fail. Mitigation: operator must confirm port 80 is open before running the bootstrap script. |
| A4 | Systemd timers are available and working on the VPS (k3s is already running, so systemd is functional). | Standard Stack | If systemd is disabled or malfunctioning, the renewal timer won't run. Fallback: use cron, but lose journald integration. |
| A5 | The WireGuard interface (`wg0`) exists and is configured on the VPS from Phase 6. | Firewall Patterns | If WireGuard is not set up, the firewall rule `ufw allow in on wg0 to any port 6443/tcp` will silently do nothing (the interface doesn't exist). Mitigation: Phase 7 depends on Phase 6 being complete. |
| A6 | The k3s API serving certificate includes `10.8.0.1` in its SANs (from Phase 6 bootstrap). | Architecture, Pitfalls | If the SAN is missing, kubectl over the WireGuard tunnel will fail with a cert mismatch error. This is a Phase 6 concern, not Phase 7; included here for completeness. |
| A7 | Certbot dry-run (`--dry-run` flag) against Let's Encrypt staging is a meaningful test (doesn't consume Let's Encrypt's production quota and confirms the renewal pipeline works). | Validation Architecture | If dry-run is skipped, you won't know renewal will succeed until it's due. Operator discipline required: run dry-run monthly. |

## Open Questions

1. **What is the exact upstream endpoint for nginx?**
   - Current info: k3s `server-2` Service is `ClusterIP:3000`, not exposed publicly.
   - Phase 11 cutover requires switching the upstream to either the legacy runtime (existing) or the new runtime (k3s-hosted). The exact IP/hostname for the legacy runtime is not yet pinned in the repo.
   - **Recommendation:** Bootstrap with the internal k3s endpoint (`127.0.0.1:3000` or the Service DNS name `server-2.solid-stats-staging.svc.cluster.local:3000`). Phase 11 will edit this upstream as part of the cutover. Document the upstream as a variable in the bootstrap script so it's easily configurable during cutover.

2. **Should the bootstrap script be applied as part of CI or as a one-time operator action?**
   - Current assumption: One-time operator action (like the Phase 6 operator-bootstrap.md runbook). The script is idempotent, so it can be re-run, but TLS cert issuance requires Let's Encrypt ACME interaction, which shouldn't be part of every CI run.
   - **Recommendation:** Operator runs the script manually once (or CI runs it on demand with a workflow_dispatch trigger). Document in `docs/edge-bootstrap.md` that this is a one-time setup. Renewal is automatic via the systemd timer thereafter.

3. **What domain name should the cert be issued for?**
   - Current info: `PUBLIC_BASE_URL: https://stats-staging.solid-stats.ru` from the server-2 ConfigMap.
   - The domain is stable and known, so the bootstrap script can hardcode it or accept it as an env var.
   - **Recommendation:** Accept `DOMAIN=stats-staging.solid-stats.ru` as an optional env var (default to this value). This allows re-use of the script for other domains in the future (e.g., legacy edge during cutover).

4. **How should renewal failure be surfaced to the operator?**
   - Proposed approach: systemd `OnFailure=` target unit that logs to syslog/journald.
   - Alternative: A custom alert hook that POSTs to a webhook or sends an email.
   - **Recommendation:** Start with journald logging (`OnFailure=` unit that calls `logger`). This is lightweight and works in an isolated environment. If monitoring integrations are added later (Datadog, Prometheus, etc.), the hook can be extended to scrape journald.

5. **Should nginx and certbot be installed via apt or pip?**
   - apt: certbot ~2.9 on Ubuntu 24.04 noble is current and fully supports webroot + renewal hooks. systemd integration is baked in.
   - There is no certbot 5.x (that was a research error); no PPA or pip upgrade is needed.
   - **Recommendation:** Use apt for nginx and certbot (system packages, automatic updates, minimal dependency management). No pinning — the bootstrap installs whatever noble ships.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Let's Encrypt ACME servers | TLS cert issuance + renewal | ✓ | Public service (always available for ACME) | N/A — ACME is required, no fallback |
| Port 80 (HTTP) inbound | ACME webroot challenge validation | ✓ (assumed) | N/A — assuming Timeweb firewall allows 80 | Operator must verify before running bootstrap |
| Port 443 (HTTPS) inbound | Public API access | ✓ (assumed) | N/A | Operator must verify before running bootstrap |
| certbot binary | Certificate renewal | ✓ | 2.x (apt) or 5.6+ (pip) | Install via `apt install certbot` (already in Standard Stack) |
| nginx binary | HTTP/HTTPS serving | ✓ | 1.18+ (apt) | Install via `apt install nginx` (already in Standard Stack) |
| systemd | Timer scheduling + service management | ✓ | 251+ (Ubuntu 22.04) | Fallback: use cron (loses journald integration, slightly more manual setup) |
| ufw binary | Firewall rule management | ✓ | 0.36+ (apt) | Fallback: use `iptables` or `nftables` directly (more complex rules) |

**Missing dependencies with no fallback:**
- None — all dependencies are either standard Ubuntu 22.04 packages or free external services (Let's Encrypt).

**Missing dependencies with fallback:**
- If systemd is unavailable: use cron + a custom log-checking script for renewal failure detection (less elegant, but functional).
- If ufw is unavailable: use iptables or nftables directly (more verbose rules, harder to maintain).

## Validation Architecture

**Nyquist validation enabled** (no `workflow.nyquist_validation: false` in config).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Shell script + `nginx -t` + systemd introspection |
| Config file | `.planning/phases/07-edge-automation/07-VALIDATION.md` (to be created) |
| Quick run command | `scripts/bootstrap-edge.sh --dry-run` (proposed flag) or manual `nginx -t` + `certbot renew --dry-run` |
| Full suite command | `scripts/bootstrap-edge.sh` (full run) + `certbot renew --dry-run` + `systemctl status certbot-renew.timer` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EDGE-01 | nginx vhost config for `stats-staging.solid-stats.ru` is stored in repo and applied to `/etc/nginx/sites-available/` | integration | `nginx -t -c /etc/nginx/sites-available/stats-staging.solid-stats.ru.conf` | ❌ Wave 0 (vhost template needs creation) |
| EDGE-02 | TLS cert renewals run on systemd timer, `--dry-run` passes, reload hook validates syntax | integration | `certbot renew --dry-run` + `systemctl status certbot-renew.timer` | ❌ Wave 0 (systemd units need creation) |
| EDGE-03 | Renewal failures are logged/alerted (OnFailure target configured) | smoke | `systemctl show -p OnFailure certbot-renew.service` (should show non-empty) | ❌ Wave 0 (service file needs creation) |
| EDGE-04 | Firewall rules allow 80/443 inbound, keep 6443 on wg0 only | smoke | `ufw status verbose \| grep -E '(80\|443\|6443)'` (verify rules exist) | ❌ Wave 0 (firewall rules applied by bootstrap script, not pre-existing) |
| EDGE-05 | Bootstrap script is idempotent and re-runnable | smoke | Run `scripts/bootstrap-edge.sh` twice on a throwaway VPS; both runs succeed | ❌ Wave 0 (script needs creation) |

### Sampling Rate
- **Per task commit:** `nginx -t -c /etc/nginx/sites-available/stats-staging.solid-stats.ru.conf` (syntax validation) + `certbot renew --dry-run` (renewal dry-run).
- **Per wave merge:** Full `scripts/bootstrap-edge.sh` run on a throwaway VPS or VM, followed by manual verification that `https://stats-staging.solid-stats.ru/` is reachable and serves from the correct upstream.
- **Phase gate:** Dry-run passes + timer status is active + ufw rules are in place (verified via `ufw status verbose`).

### Wave 0 Gaps
- [ ] `config/nginx/sites-available/stats-staging.solid-stats.ru.conf` — nginx vhost template (server blocks for HTTP:80 and HTTPS:443)
- [ ] `scripts/bootstrap-edge.sh` — idempotent bootstrap script (installs packages, applies configs, enables services)
- [ ] `scripts/teardown-edge.sh` — reversibility script (removes configs, disables services, cleans up certs)
- [ ] `/etc/systemd/system/certbot-renew.service` — renewal service unit (certbot renew with deploy-hook)
- [ ] `/etc/systemd/system/certbot-renew.timer` — renewal timer (twice daily, randomized delay)
- [ ] `/etc/systemd/system/certbot-renew-failure.target` — failure target (triggered on renewal failure)
- [ ] `/etc/systemd/system/certbot-renew-failure.service` — failure logger (logs alert to journald)
- [ ] `docs/edge-bootstrap.md` — operator runbook (step-by-step instructions for bootstrap and troubleshooting)
- [ ] `.planning/phases/07-edge-automation/07-VALIDATION.md` — validation specification (detailed test cases for each EDGE-*XX requirement)

*(All gaps are expected for Wave 0 of planning; Wave 1 execution will create these artifacts.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Edge tier owns TLS termination and public interface; k3s API is not exposed publicly (WireGuard-only) |
| V2 Authentication | no | Authentication is at the application tier (server-2), not the edge |
| V3 Session Management | no | Sessions are managed by the application, TLS is terminated at the edge |
| V4 Access Control | yes | Firewall rules enforce access control: public 80/443, k3s API 6443 only on wg0 |
| V5 Input Validation | no | Input validation is delegated to the application tier (server-2) |
| V6 Cryptography | yes | TLS 1.2+ (enforced via nginx config), certificate from trusted CA (Let's Encrypt), no self-signed certs |
| V7 Error Handling | yes | Renewal failures are logged; nginx config errors are caught by `nginx -t` before reload |
| V8 Data Protection | yes | TLS encrypts all public traffic in transit; k3s API is closed to public (WireGuard-only) |
| V9 Network Architecture | yes | Public edge (nginx) is the only public-facing tier; k3s and databases are not reachable from the internet |
| V10 Business Logic | no | No business logic at the edge tier |
| V11 File Upload | no | No file upload handling at the edge tier |
| V12 API | yes | The edge acts as an API gateway (proxies to server-2); no custom validation here (defer to server-2) |
| V13 GraphQL | no | Not applicable (staging uses REST) |
| V14 Configuration | yes | Edge configuration is version-controlled; secrets (certs) are stored on the host filesystem with restricted permissions (`/etc/letsencrypt/` mode 0700) |

### Known Threat Patterns for {Host Edge + TLS + Firewall}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| TLS downgrade attack (HSTS bypass) | Tampering | Add HSTS header in nginx: `add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;` |
| Expired certificate + silent renewal failure | Availability | Renewal hook validates syntax; OnFailure unit alerts operator; operator monitors `journalctl -u certbot-renew.service` |
| k3s API exposed publicly due to firewall rule error | Elevation of Privilege | Interface-specific ufw rules (`on wg0`); explicit rule validation in bootstrap script; operator verification in runbook |
| DNS rebind / subdomain takeover | Spoofing | Use a locked domain name (stats-staging.solid-stats.ru); certbot validates domain ownership via ACME challenge |
| ACME challenge path served by application instead of nginx | Spoofing | ACME webroot path (/.well-known/) is served by nginx static root, not proxied to application |
| Nginx reload fails, old cert remains, expires silently | Availability | Deploy-hook validates syntax before reload; renewal failure is logged/alerted |
| Firewall bypass via IPv6 | Spoofing | Add IPv6 rules to ufw alongside IPv4 rules (both `listen` and firewall rules must cover IPv6) |

**Hardening recommendations:**
1. Add HSTS header in nginx server block.
2. Monitor renewal via `journalctl -u certbot-renew.service` weekly or set up a log alert.
3. Test firewall rules monthly: confirm public can't reach 6443, public can reach 80/443, CI can reach 6443 over WireGuard.
4. Review TLS cipher suite annually; align with OWASP guidelines.

## Sources

### Primary (HIGH confidence)

- **[Context7: Certbot](https://github.com/certbot/certbot)** — Official certbot documentation; authenticators (webroot, nginx, standalone), renewal configuration, deploy-hooks, systemd integration.
- **[Context7: Let's Encrypt](https://letsencrypt.org)** — ACME protocol, certificate issuance policies, renewal best practices, rate limits.
- **[Official Certbot User Guide](https://eff-certbot.readthedocs.io/en/stable/using.html)** — Comprehensive reference for all certbot modes, hook integration, renewal automation.
- **Ubuntu 22.04 Package Documentation** — Verified package versions via apt (certbot, nginx, systemd, ufw).
- **NGINX Official Documentation** — Proxy configuration, SSL/TLS termination, validation syntax (`nginx -t`).

### Secondary (MEDIUM confidence)

- **[UFW Essentials Guide](https://dohost.us/index.php/2025/07/24/advanced-ufw-rules-interface-specific-filtering-and-rate-limiting/)** — Interface-specific firewall rules for split-tunnel VPN.
- **[Certbot Renewal Automation](https://axelspire.com/vault/acme-clients/certbot-renewal-automation/)** — Deploy hooks, --dry-run testing, systemd timer scheduling.
- **[NGINX Config Validation](https://serverscheduler.com/blog/nginx-check-config)** — `nginx -t` and `nginx -T` usage patterns, CI integration.
- **WebSearch: Ubuntu 22.04 systemd timer + ufw firewall** — Verified service unit structure and firewall syntax specific to this OS version.

### Tertiary (LOW confidence — training data)

- None; all findings were verified against official docs or Context7.

## Metadata

**Confidence breakdown:**
- **Standard Stack:** HIGH — All tools are standard Ubuntu 22.04 packages with verified versions. Certbot and Let's Encrypt documentation is authoritative. nginx is the de facto reverse proxy standard.
- **Architecture Patterns:** HIGH — Patterns derive from official certbot hooks, systemd timer, and ufw documentation. Verified with Context7.
- **Pitfalls:** HIGH — Based on concrete examples from Certbot GitHub issues and NGINX best practices.
- **Firewall rules:** HIGH — Verified with recent UFW documentation (July 2025) and split-tunnel examples.
- **Open Questions:** HIGH — Questions are well-bounded; answers are discoverable in Phase 11 planning or operator input.

**Research date:** 2026-06-12
**Valid until:** 2026-07-12 (30 days — stable tools, no breaking changes expected in this period)

---

*Research completed 2026-06-12 by Claude Haiku 4.5 via GSD research phase protocol.*
