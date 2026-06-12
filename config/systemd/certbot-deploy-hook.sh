#!/usr/bin/env bash
set -euo pipefail

# certbot-deploy-hook.sh — post-renewal nginx reload gate
# Source: config/systemd/certbot-deploy-hook.sh — managed by infrastructure repo
# Installed by: scripts/bootstrap-edge.sh to /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
# Called by: certbot (stock certbot.timer) after each successful certificate renewal.
# certbot sets $RENEWED_DOMAINS before calling this hook.

TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')
RENEWED="${RENEWED_DOMAINS:-unknown}"
echo "[$TIMESTAMP] [certbot-deploy-hook] Renewal hook triggered for: $RENEWED"

# --- Section 1: nginx config validation (fail-closed gate, per EDGE-02) ---
echo "[$TIMESTAMP] [certbot-deploy-hook] Validating nginx configuration..."
if ! nginx -t 2>&1; then
  echo "[$TIMESTAMP] [certbot-deploy-hook] FATAL: nginx -t failed — refusing reload" >&2
  echo "[$TIMESTAMP] [certbot-deploy-hook] New certificate installed but nginx NOT reloaded" >&2
  echo "[$TIMESTAMP] [certbot-deploy-hook] Fix nginx config and run: systemctl reload nginx" >&2
  exit 1
fi

# --- Section 2: nginx reload ---
echo "[$TIMESTAMP] [certbot-deploy-hook] Reloading nginx..."
# Surface a reload failure that happens AFTER a passing nginx -t — otherwise the
# bare command dies under set -e with no actionable line, leaving the operator
# unsure whether validation or the reload itself failed (the renewed cert is
# already on disk; only the reload is missing).
if ! systemctl reload nginx; then
  echo "[$TIMESTAMP] [certbot-deploy-hook] FATAL: nginx reload failed AFTER passing nginx -t" >&2
  echo "[$TIMESTAMP] [certbot-deploy-hook] Renewed cert is installed; reload manually: systemctl reload nginx" >&2
  exit 1
fi

# --- Section 3: success log ---
TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')
echo "[$TIMESTAMP] [certbot-deploy-hook] Success — nginx reloaded with renewed certificate(s)"
