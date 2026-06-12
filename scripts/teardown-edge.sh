#!/usr/bin/env bash
set -euo pipefail

# teardown-edge.sh — reverses bootstrap-edge.sh; restores host to pre-Phase-7 state
# Restores the backed-up original vhost, removes drop-in/hook/ufw edge rules.
# IMPORTANT: Does NOT remove /etc/letsencrypt/ certs (preserved for re-bootstrap).
#            Does NOT remove ufw allow 22/tcp (would lock out operator).
#            Does NOT disable ufw itself (firewall remains enabled).
# Usage: scripts/teardown-edge.sh
#        DOMAIN=stats-staging.solid-stats.ru scripts/teardown-edge.sh

# --- Optional vars with defaults -------------------------------------------
: "${DOMAIN:=stats-staging.solid-stats.ru}"
: "${NGINX_SITES_DIR:=/etc/nginx/sites-available}"
: "${NGINX_SITES_ENABLED:=/etc/nginx/sites-enabled}"

VHOST_CONF="$NGINX_SITES_DIR/stats-staging-solid-stats.conf"
BAK_VHOST="${VHOST_CONF}.bak"

# ---------------------------------------------------------------------------
echo "=== 1. Remove systemd OnFailure drop-in (per D-5) ==="

systemctl stop certbot-renew-failure.service 2>/dev/null || true
rm -f /etc/systemd/system/certbot.service.d/onfailure.conf
rm -f /etc/systemd/system/certbot-renew-failure.service
# Remove the drop-in dir if empty
rmdir /etc/systemd/system/certbot.service.d 2>/dev/null || true
systemctl daemon-reload
echo "certbot.service.d drop-in and failure handler removed"

# ---------------------------------------------------------------------------
echo "=== 2. Remove certbot deploy hook ==="

rm -f /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
echo "certbot deploy hook removed"

# ---------------------------------------------------------------------------
echo "=== 3. Restore original nginx vhost (per D-8) ==="

if [[ -f "$BAK_VHOST" ]]; then
  echo "Restoring original vhost from $BAK_VHOST..."
  cp "$BAK_VHOST" "$VHOST_CONF"
  rm -f "$BAK_VHOST"
  echo "Original vhost restored; backup removed"
else
  echo "No backup found at $BAK_VHOST — removing repo vhost"
  rm -f "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"
  rm -f "$VHOST_CONF"
fi

# Re-enable symlink if vhost still present (backup was restored)
if [[ -f "$VHOST_CONF" ]]; then
  ln -sf "$VHOST_CONF" "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"
fi

if nginx -t 2>/dev/null; then
  systemctl reload nginx
  echo "nginx reloaded with restored config"
else
  echo "warn: nginx -t failed after vhost restore — reload skipped; fix manually"
fi

# ---------------------------------------------------------------------------
echo "=== 4. Remove ufw edge rules ==="

# DO NOT remove ufw allow 22/tcp (operator lockout risk)
# DO NOT run ufw disable (firewall remains enabled with remaining rules)
ufw delete allow 80/tcp 2>/dev/null || echo "ufw rule 80/tcp not found — skipping"
ufw delete allow 443/tcp 2>/dev/null || echo "ufw rule 443/tcp not found — skipping"
ufw delete allow in on wg0 to any port 6443/tcp 2>/dev/null || echo "ufw rule 6443/wg0 not found — skipping"
echo "ufw edge rules removed (SSH rule preserved, firewall remains enabled)"
ufw status verbose

# ---------------------------------------------------------------------------
echo "=== Teardown complete ==="
echo "Removed: certbot.service.d drop-in, failure handler, deploy hook, ufw 80/443/6443-wg0"
echo "Restored: original nginx vhost from .bak (or removed if no backup)"
echo "Preserved: /etc/letsencrypt/ certs, ufw 22/tcp SSH rule, ufw enabled"
echo "OPERATOR VERIFICATION:"
echo "  1. nginx -t                    (config valid without repo vhost)"
echo "  2. ufw status verbose          (confirm 80/443/6443 rules removed)"
echo "  3. systemctl list-timers       (stock certbot.timer still present)"
echo "  4. systemctl show -p OnFailure certbot.service  (drop-in removed; OnFailure empty)"
