#!/usr/bin/env bash
set -euo pipefail

# bootstrap-edge.sh — idempotent adopt-reconcile for the staging host edge
# Backs up the live vhost, installs the repo vhost + certbot drop-in + deploy hook + ufw rules.
# Run on the VPS as root (or with sudo). Safe to re-run — all ops are idempotent.
# Usage:
#   ADMIN_EMAIL=ops@example.com scripts/bootstrap-edge.sh
#   ADMIN_EMAIL=ops@example.com SKIP_UFW=1 scripts/bootstrap-edge.sh   # skip ufw changes
# See docs/edge-bootstrap.md for the full operator runbook.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Optional vars with defaults -------------------------------------------
: "${DOMAIN:=stats-staging.solid-stats.ru}"
: "${WEBROOT_PATH:=/var/www/html}"
: "${NGINX_SITES_DIR:=/etc/nginx/sites-available}"
: "${NGINX_SITES_ENABLED:=/etc/nginx/sites-enabled}"
: "${SKIP_UFW:=0}"
: "${SKIP_CERTBOT:=0}"

# --- Required vars (exit 64 if missing) ------------------------------------
if [[ -z "${ADMIN_EMAIL:-}" ]]; then
  echo "FATAL: ADMIN_EMAIL is required (Let's Encrypt registration email)" >&2
  exit 64
fi

# ---------------------------------------------------------------------------
echo "=== 1. Package check ==="

apt-get update -qq
apt-get install -y certbot nginx ufw curl openssl

echo "Package versions:"
nginx -v 2>&1 || true
certbot --version 2>&1 || true
ufw --version 2>&1 || true

# ---------------------------------------------------------------------------
echo "=== 2. Webroot directory ==="

mkdir -p "$WEBROOT_PATH/.well-known/acme-challenge"
# Scope chmod to the dirs the ACME webroot flow needs — do NOT recurse over the
# whole webroot, which on a shared host may hold unrelated site content.
chmod 755 "$WEBROOT_PATH" "$WEBROOT_PATH/.well-known" "$WEBROOT_PATH/.well-known/acme-challenge"
echo "Webroot ready at $WEBROOT_PATH"

# ---------------------------------------------------------------------------
echo "=== 3. Adopt / reconcile nginx vhost (per D-8) ==="

VHOST_CONF="$NGINX_SITES_DIR/stats-staging-solid-stats.conf"
REPO_VHOST="$REPO_ROOT/config/nginx/sites-available/stats-staging-solid-stats.conf"
BAK_VHOST="${VHOST_CONF}.bak"

# Back up the live file before overwriting (only if not already backed up)
if [[ -f "$VHOST_CONF" && ! -f "$BAK_VHOST" ]]; then
  echo "Backing up live vhost to $BAK_VHOST..."
  cp "$VHOST_CONF" "$BAK_VHOST"
elif [[ -f "$BAK_VHOST" ]]; then
  echo "Backup already exists at $BAK_VHOST — skipping backup step"
else
  echo "No existing vhost at $VHOST_CONF — no backup needed"
fi

# Install repo vhost (idempotent: cp overwrites)
cp "$REPO_VHOST" "$VHOST_CONF"

# Symlink into sites-enabled (idempotent: ln -sf)
ln -sf "$VHOST_CONF" "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"

# nginx -t gate — fail closed; never reload on invalid config
echo "Validating nginx configuration..."
if ! nginx -t 2>&1; then
  echo "FATAL: nginx config invalid after vhost install" >&2
  if [[ -f "$BAK_VHOST" ]]; then
    echo "Restoring backup from $BAK_VHOST..." >&2
    cp "$BAK_VHOST" "$VHOST_CONF"
  else
    # No prior config to restore — remove the broken artifact AND its symlink so a
    # later manual reload or a host reboot can never load this invalid config.
    echo "No backup to restore — removing the broken repo vhost and its symlink" >&2
    rm -f "$VHOST_CONF" "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"
  fi
  # Re-validate AFTER restore/removal before any reload — never reload an unvalidated config
  if ! nginx -t 2>&1; then
    echo "FATAL: nginx config still invalid after restore/removal — refusing reload to avoid breaking the live edge" >&2
    exit 1
  fi
  exit 1
fi
# Reload must succeed — do NOT fall back to a no-op 'start' on an already-running
# nginx, which returns 0 and would mask a failed reload, falsely reporting the
# new vhost as live when it is not.
if ! systemctl reload nginx; then
  echo "FATAL: nginx reload failed despite passing nginx -t — the new vhost is NOT live; investigate manually" >&2
  systemctl status nginx --no-pager >&2 || true
  exit 1
fi
echo "nginx vhost installed and reloaded"

# ---------------------------------------------------------------------------
echo "=== 4. TLS certificate (per D-6, D-8) ==="

if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  echo "Certificate lineage already exists for $DOMAIN — skipping issuance (per D-6)"
elif [[ "${SKIP_CERTBOT}" == "1" ]]; then
  echo "SKIP_CERTBOT=1 — skipping certbot issuance"
else
  echo "Requesting initial TLS certificate for $DOMAIN..."
  certbot certonly \
    --authenticator webroot \
    --installer none \
    --no-eff-email \
    --agree-tos \
    --email "$ADMIN_EMAIL" \
    --webroot-path "$WEBROOT_PATH" \
    -d "$DOMAIN"
fi

# ---------------------------------------------------------------------------
echo "=== 5. certbot deploy hook (per D-4) ==="

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cp "$REPO_ROOT/config/systemd/certbot-deploy-hook.sh" \
   /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
echo "certbot deploy hook installed at /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh"

# ---------------------------------------------------------------------------
echo "=== 6. systemd OnFailure drop-in (per D-5) ==="

mkdir -p /etc/systemd/system/certbot.service.d
cp "$REPO_ROOT/config/systemd/certbot.service.d/onfailure.conf" \
   /etc/systemd/system/certbot.service.d/onfailure.conf
cp "$REPO_ROOT/config/systemd/certbot-renew-failure.service" \
   /etc/systemd/system/certbot-renew-failure.service
systemctl daemon-reload || { echo "FATAL: systemctl daemon-reload failed — OnFailure drop-in not wired" >&2; exit 1; }
systemctl is-enabled certbot.timer 2>/dev/null && echo "Stock certbot.timer is active — renewal schedule preserved" || true
echo "certbot.service.d drop-in and failure handler installed"

# ---------------------------------------------------------------------------
echo "=== 7. ufw firewall rules (per D-7, EDGE-04) ==="

if [[ "${SKIP_UFW}" == "1" ]]; then
  echo "SKIP_UFW=1 — skipping ufw changes"
else
  ufw default deny incoming || true
  ufw default allow outgoing || true
  ufw allow 22/tcp comment 'SSH operator access' || true
  ufw allow 80/tcp comment 'HTTP public + ACME challenges' || true
  ufw allow 443/tcp comment 'HTTPS public' || true

  # wg0 pre-check: refuse to apply the 6443 rule if WireGuard tunnel is not up.
  # Without the interface qualifier the k3s API would be exposed on the public interface.
  if ip link show wg0 >/dev/null 2>&1; then
    ufw allow in on wg0 to any port 6443/tcp comment 'k3s API via WireGuard only' || { echo "FATAL: ufw 6443/wg0 rule failed" >&2; exit 1; }
  else
    echo "FATAL: wg0 not found — refusing to apply firewall (6443 would be publicly exposed); bring up the WireGuard tunnel first" >&2
    exit 1
  fi

  ufw --force enable || { echo "FATAL: ufw --force enable failed" >&2; exit 1; }
  echo "Firewall rules:"
  ufw status verbose
fi

# ---------------------------------------------------------------------------
echo "=== Bootstrap complete ==="
echo "OPERATOR VERIFICATION REQUIRED (live host only — not CI):"
echo "  1. nginx -t                             (validate nginx config)"
echo "  2. certbot renew --dry-run              (verify renewal pipeline)"
echo "  3. systemctl show -p OnFailure certbot.service  (confirm drop-in wired)"
echo "  4. ufw status verbose                   (confirm split-tunnel rules)"
echo "  5. curl -I https://$DOMAIN/             (smoke check public HTTPS)"
echo "  See: docs/edge-bootstrap.md for full runbook"
