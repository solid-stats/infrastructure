#!/usr/bin/env bash
set -euo pipefail

# teardown-edge.sh — reverses bootstrap-edge.sh; restores host to pre-Phase-7 state
# Restores the backed-up original vhost, removes drop-in/hook/ufw edge rules.
# IMPORTANT: Does NOT remove /etc/letsencrypt/ certs (preserved for re-bootstrap).
#            Does NOT remove ufw allow 22/tcp (would lock out operator).
#            Does NOT disable ufw itself (firewall remains enabled).
# Usage: scripts/teardown-edge.sh
#        DOMAIN=stats-staging.solid-stats.ru scripts/teardown-edge.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Optional vars with defaults -------------------------------------------
: "${DOMAIN:=stats-staging.solid-stats.ru}"
: "${NGINX_SITES_DIR:=/etc/nginx/sites-available}"
: "${NGINX_SITES_ENABLED:=/etc/nginx/sites-enabled}"

VHOST_CONF="$NGINX_SITES_DIR/stats-staging-solid-stats.conf"
REPO_VHOST="$REPO_ROOT/config/nginx/sites-available/stats-staging-solid-stats.conf"
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
  # No .bak to restore. Only remove the live vhost if it is byte-identical to the
  # repo copy this teardown owns — otherwise it may be a hand-authored vhost (or a
  # post-bootstrap edit) whose removal would be irreversible config loss.
  if [[ -f "$VHOST_CONF" ]] && cmp -s "$REPO_VHOST" "$VHOST_CONF"; then
    echo "No backup found at $BAK_VHOST — live vhost matches repo copy, removing it"
    rm -f "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"
    rm -f "$VHOST_CONF"
  elif [[ -f "$VHOST_CONF" ]]; then
    echo "warn: no .bak and live vhost differs from repo copy — leaving it in place (manual review)" >&2
  else
    echo "No backup and no live vhost at $VHOST_CONF — nothing to restore"
  fi
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

# delete_rule <grep-needle> <ufw-delete-args...>
# Distinguishes "rule absent" (benign skip) from "delete failed" (FATAL). Blanket
# '2>/dev/null || echo skipping' previously reported a failed delete as a clean
# absence, masking a real reversibility gap.
delete_rule() {
  local needle="$1"
  shift
  if ufw status | grep -qF "$needle"; then
    ufw delete "$@" || { echo "FATAL: failed to delete ufw rule: $needle" >&2; exit 1; }
  else
    echo "ufw rule '$needle' not present — skipping"
  fi
}

delete_rule "80/tcp" allow 80/tcp
delete_rule "443/tcp" allow 443/tcp
echo "ufw edge rules removed (SSH rule preserved, firewall remains enabled)"
ufw status verbose

# ---------------------------------------------------------------------------
echo "=== Teardown complete ==="
echo "Removed: certbot.service.d drop-in, failure handler, deploy hook, ufw 80/443"
echo "Restored: original nginx vhost from .bak (or removed if no backup)"
echo "Preserved: /etc/letsencrypt/ certs, ufw 22/tcp SSH rule, ufw enabled"
echo "OPERATOR VERIFICATION:"
echo "  1. nginx -t                    (config valid without repo vhost)"
echo "  2. ufw status verbose          (confirm 80/443/6443 rules removed)"
echo "  3. systemctl list-timers       (stock certbot.timer still present)"
echo "  4. systemctl show -p OnFailure certbot.service  (drop-in removed; OnFailure empty)"
