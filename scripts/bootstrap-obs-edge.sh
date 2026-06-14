#!/usr/bin/env bash
set -euo pipefail

# bootstrap-obs-edge.sh — env-parameterized obs-edge adopt-reconcile bootstrap
# Idempotent script that wires a public observability subdomain into the host nginx edge.
# Run on the VPS as root (or with sudo). Safe to re-run — all ops are idempotent.
#
# Usage — grafana (discovers upstream from k3s at runtime):
#   DOMAIN=grafana.solid-stats.ru \
#   ADMIN_EMAIL=ops@example.com \
#   scripts/bootstrap-obs-edge.sh
#
# Usage — errors placeholder (no upstream; cert-only):
#   DOMAIN=errors.solid-stats.ru \
#   ADMIN_EMAIL=ops@example.com \
#   SKIP_UPSTREAM_CHECK=1 \
#   scripts/bootstrap-obs-edge.sh
#
# See docs/obs-edge-bootstrap.md for the full operator runbook.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Required vars (exit 64 if missing) ------------------------------------
if [[ -z "${DOMAIN:-}" ]]; then
  echo "FATAL: DOMAIN is required (e.g. grafana.solid-stats.ru)" >&2
  exit 64
fi
if [[ -z "${ADMIN_EMAIL:-}" ]]; then
  echo "FATAL: ADMIN_EMAIL is required (Let's Encrypt registration email)" >&2
  exit 64
fi

# --- Optional vars with defaults -------------------------------------------
: "${UPSTREAM:=}"                                    # empty = discover via kubectl (grafana); or placeholder for errors.
: "${WEBROOT_PATH:=/var/www/html}"
: "${NGINX_SITES_DIR:=/etc/nginx/sites-available}"
: "${NGINX_SITES_ENABLED:=/etc/nginx/sites-enabled}"
: "${SKIP_CERTBOT:=0}"
: "${SKIP_UFW:=1}"                                   # default 1 — ports 80/443 already open from Phase 07
: "${SKIP_UPSTREAM_CHECK:=0}"                        # set to 1 for errors. placeholder (no k3s upstream)

# ---------------------------------------------------------------------------
echo "=== bootstrap-obs-edge: DOMAIN=$DOMAIN ==="
echo "=== 1. Package check ==="

apt-get update -qq
apt-get install -y certbot nginx curl openssl

echo "Package versions:"
nginx -v 2>&1 || true
certbot --version 2>&1 || true

# ---------------------------------------------------------------------------
echo "=== 2. Webroot directory ==="

mkdir -p "$WEBROOT_PATH/.well-known/acme-challenge"
# Scope chmod to the dirs the ACME webroot flow needs — do NOT recurse over the
# whole webroot, which on a shared host may hold unrelated site content.
chmod 755 "$WEBROOT_PATH" "$WEBROOT_PATH/.well-known" "$WEBROOT_PATH/.well-known/acme-challenge"
echo "Webroot ready at $WEBROOT_PATH"

# ---------------------------------------------------------------------------
echo "=== 3. Upstream resolution ==="

if [[ -z "$UPSTREAM" && "${SKIP_UPSTREAM_CHECK}" != "1" ]]; then
  echo "Discovering Grafana ClusterIP from k3s..."
  UPSTREAM=$(kubectl get svc grafana -n monitoring \
    -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}')
  if [[ -z "$UPSTREAM" || "$UPSTREAM" == ":" ]]; then
    echo "FATAL: Could not discover Grafana Service ClusterIP — is Grafana deployed in namespace monitoring?" >&2
    exit 1
  fi
  echo "Grafana upstream: $UPSTREAM"
elif [[ "${SKIP_UPSTREAM_CHECK}" == "1" ]]; then
  echo "SKIP_UPSTREAM_CHECK=1 — skipping upstream discovery (errors. placeholder path, no proxy_pass needed)"
fi

# ---------------------------------------------------------------------------
echo "=== 3a. Vhost adopt / reconcile (HTTP-first, cert-lineage aware) ==="

# Select repo vhost file by domain prefix.
# The repo ships one TLS-complete vhost per domain; the bootstrap installs
# an inline HTTP-only temp vhost first when no cert lineage exists yet.
case "$DOMAIN" in
  grafana.*)
    REPO_VHOST_NAME="grafana-stats-staging-solid-stats.conf"
    ;;
  errors.*)
    REPO_VHOST_NAME="errors-stats-staging-solid-stats.conf"
    ;;
  *)
    echo "FATAL: Unsupported DOMAIN prefix '$DOMAIN' — add a case entry for this domain" >&2
    exit 1
    ;;
esac

REPO_VHOST="$REPO_ROOT/config/nginx/sites-available/$REPO_VHOST_NAME"
VHOST_CONF="$NGINX_SITES_DIR/$REPO_VHOST_NAME"
BAK_VHOST="${VHOST_CONF}.bak"

if [[ ! -f "$REPO_VHOST" ]]; then
  echo "FATAL: Repo vhost not found at $REPO_VHOST — was it created in this phase?" >&2
  exit 1
fi

# Backup the live vhost before overwriting (only if no .bak exists yet)
if [[ -f "$VHOST_CONF" && ! -f "$BAK_VHOST" ]]; then
  echo "Backing up live vhost to $BAK_VHOST..."
  cp "$VHOST_CONF" "$BAK_VHOST"
elif [[ -f "$BAK_VHOST" ]]; then
  echo "Backup already exists at $BAK_VHOST — skipping backup step"
else
  echo "No existing vhost at $VHOST_CONF — no backup needed"
fi

# nginx -t gate with auto-restore (shared helper used after every vhost install).
# Call: _nginx_gate_reload <vhost_conf> <vhost_symlink_path> [<bak_vhost>]
_nginx_gate_reload() {
  local vhost_conf="$1"
  local vhost_sym="$2"
  local bak="${3:-}"

  echo "Validating nginx configuration..."
  if ! nginx -t 2>&1; then
    echo "FATAL: nginx config invalid after vhost install" >&2
    if [[ -n "$bak" && -f "$bak" ]]; then
      echo "Restoring backup from $bak..." >&2
      cp "$bak" "$vhost_conf"
    else
      echo "No backup to restore — removing the broken vhost and its symlink" >&2
      rm -f "$vhost_conf" "$vhost_sym"
    fi
    if ! nginx -t 2>&1; then
      echo "FATAL: nginx config still invalid after restore/removal — refusing reload to avoid breaking the live edge" >&2
      exit 1
    fi
    exit 1
  fi
  if ! systemctl reload nginx; then
    echo "FATAL: nginx reload failed despite passing nginx -t — the new vhost is NOT live; investigate manually" >&2
    systemctl status nginx --no-pager >&2 || true
    exit 1
  fi
  echo "nginx vhost installed and reloaded"
}

VHOST_SYM="$NGINX_SITES_ENABLED/$REPO_VHOST_NAME"

if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  # Cert lineage already exists — install the final TLS vhost directly.
  echo "Cert lineage found for $DOMAIN — installing final TLS vhost directly"
  sed "s|UPSTREAM_PLACEHOLDER|${UPSTREAM}|g" "$REPO_VHOST" > "$VHOST_CONF"
  ln -sf "$VHOST_CONF" "$VHOST_SYM"
  _nginx_gate_reload "$VHOST_CONF" "$VHOST_SYM" "$BAK_VHOST"
else
  # No cert yet — install HTTP-only temp vhost so nginx can serve the ACME challenge.
  # The final TLS vhost is installed AFTER certbot succeeds (Step 4 below).
  echo "No cert lineage for $DOMAIN — installing HTTP-only temp vhost for ACME challenge..."
  TEMP_VHOST=$(mktemp)
  # Write inline HTTP-only block; sed substitutes the domain placeholder.
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
  cp "$TEMP_VHOST" "$VHOST_CONF"
  rm -f "$TEMP_VHOST"
  ln -sf "$VHOST_CONF" "$VHOST_SYM"
  _nginx_gate_reload "$VHOST_CONF" "$VHOST_SYM" "$BAK_VHOST"
fi

# ---------------------------------------------------------------------------
echo "=== 4. TLS certificate (per-domain certbot certonly -d; never certbot renew for new issuance) ==="

CERT_INSTALLED=0

if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  echo "Certificate lineage already exists for $DOMAIN — skipping issuance (rate-limit safety)"
elif [[ "${SKIP_CERTBOT}" == "1" ]]; then
  echo "SKIP_CERTBOT=1 — skipping certbot issuance (DNS not live yet; set SKIP_CERTBOT=0 after DNS resolves)"
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
  CERT_INSTALLED=1
fi

# If we just issued a cert on first run (came from the HTTP-only temp vhost path),
# swap in the final repo TLS vhost now that the cert files exist.
if [[ "$CERT_INSTALLED" == "1" ]]; then
  echo "Cert issued — swapping HTTP-only temp vhost for final TLS vhost..."
  sed "s|UPSTREAM_PLACEHOLDER|${UPSTREAM}|g" "$REPO_VHOST" > "$VHOST_CONF"
  ln -sf "$VHOST_CONF" "$VHOST_SYM"
  _nginx_gate_reload "$VHOST_CONF" "$VHOST_SYM" "$BAK_VHOST"
fi

# ---------------------------------------------------------------------------
echo "=== 5. certbot deploy hook ==="

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cp "$REPO_ROOT/config/systemd/certbot-deploy-hook.sh" \
   /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
echo "certbot deploy hook installed at /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh"

# ---------------------------------------------------------------------------
echo "=== 6. systemd OnFailure drop-in ==="

mkdir -p /etc/systemd/system/certbot.service.d
cp "$REPO_ROOT/config/systemd/certbot.service.d/onfailure.conf" \
   /etc/systemd/system/certbot.service.d/onfailure.conf
cp "$REPO_ROOT/config/systemd/certbot-renew-failure.service" \
   /etc/systemd/system/certbot-renew-failure.service
systemctl daemon-reload || { echo "FATAL: systemctl daemon-reload failed — OnFailure drop-in not wired" >&2; exit 1; }
systemctl is-enabled certbot.timer 2>/dev/null && echo "Stock certbot.timer is active — renewal schedule preserved" || true
echo "certbot.service.d drop-in and failure handler installed"

# ---------------------------------------------------------------------------
echo "=== 7. ufw firewall rules ==="

if [[ "${SKIP_UFW}" == "1" ]]; then
  echo "SKIP_UFW=1 — skipping ufw changes (ports 80/443 already open from Phase 07 bootstrap-edge.sh)"
else
  ufw allow 80/tcp comment 'HTTP public + ACME challenges' || true
  ufw allow 443/tcp comment 'HTTPS public' || true
  echo "ufw rules for 80/443 applied"
  ufw status verbose
fi

# ---------------------------------------------------------------------------
echo "=== Bootstrap complete for $DOMAIN ==="
echo "OPERATOR VERIFICATION REQUIRED (live host only — not CI):"
echo "  1. nginx -t                                    (validate nginx config)"
echo "  2. certbot certificates                        (confirm cert lineage for $DOMAIN)"
echo "  3. curl -I https://$DOMAIN/                   (smoke check public HTTPS)"
echo "  4. certbot renew --dry-run --cert-name $DOMAIN (verify renewal pipeline; use --cert-name, NOT unscoped renew)"
echo "  See: docs/obs-edge-bootstrap.md for full runbook"
