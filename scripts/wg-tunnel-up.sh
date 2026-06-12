#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# wg-tunnel-up.sh — WireGuard handshake gate for CI
#
# Brings up a WireGuard interface, waits for handshake completion, and
# verifies TCP reachability of the k3s API server.  Exits 64 on missing
# required configuration; exits 1 if the handshake does not complete within
# HANDSHAKE_TIMEOUT_SECS (fail-closed gate — no kubectl runs without a
# confirmed handshake).
#
# Usage (called from GitHub Actions step with env vars from secrets):
#   WG_PRIVATE_KEY=<key> WG_PEER_PUBLIC_KEY=<key> WG_ENDPOINT=<host:port> \
#     scripts/wg-tunnel-up.sh
# ---------------------------------------------------------------------------

# --- Optional vars with defaults -------------------------------------------
: "${WG_INTERFACE:=wg0}"
: "${WG_LOCAL_IP:=10.8.0.2/32}"
: "${WG_ALLOWED_IPS:=10.8.0.1/32}"
: "${HANDSHAKE_TIMEOUT_SECS:=10}"
: "${K8S_API_HOST:=10.8.0.1}"
: "${K8S_API_PORT:=6443}"

# --- Required vars (exit 64 if missing) ------------------------------------
if [[ -z "${WG_PRIVATE_KEY:-}" ]]; then
  echo "FATAL: WG_PRIVATE_KEY is required" >&2
  exit 64
fi
if [[ -z "${WG_PEER_PUBLIC_KEY:-}" ]]; then
  echo "FATAL: WG_PEER_PUBLIC_KEY is required" >&2
  exit 64
fi
if [[ -z "${WG_ENDPOINT:-}" ]]; then
  echo "FATAL: WG_ENDPOINT is required (format: HOST:PORT)" >&2
  exit 64
fi

echo "=== WireGuard Pre-flight Gate ==="

# --- 1. Ensure wireguard-tools installed ------------------------------------
if ! command -v wg &>/dev/null; then
  echo "Installing wireguard-tools..."
  sudo apt-get update >/dev/null 2>&1
  sudo apt-get install -y wireguard-tools >/dev/null 2>&1
fi

# --- 2. Create WireGuard interface ------------------------------------------
echo "Creating interface $WG_INTERFACE..."
sudo ip link add dev "$WG_INTERFACE" type wireguard

echo "Assigning local IP $WG_LOCAL_IP..."
sudo ip address add "$WG_LOCAL_IP" dev "$WG_INTERFACE"

# --- 3. Configure peer (private key via process substitution — never on disk)
echo "Configuring peer $WG_PEER_PUBLIC_KEY..."
sudo wg set "$WG_INTERFACE" \
  private-key <(printf '%s' "$WG_PRIVATE_KEY") \
  peer "$WG_PEER_PUBLIC_KEY" \
  endpoint "$WG_ENDPOINT" \
  allowed-ips "$WG_ALLOWED_IPS"

# --- 4. Bring interface up --------------------------------------------------
echo "Bringing up $WG_INTERFACE..."
sudo ip link set up dev "$WG_INTERFACE"

# --- 5. Handshake polling loop (fail-closed) --------------------------------
# latest-handshakes output: "<peer_pubkey>\t<timestamp_epoch>"
# Handshake is complete when timestamp_epoch is non-zero (> 0).
# We detect this by looking for a tab followed by a digit 1-9 (non-zero epoch).
echo "Waiting for handshake (timeout: ${HANDSHAKE_TIMEOUT_SECS}s)..."
start_epoch=$(date +%s)
while true; do
  if sudo wg show "$WG_INTERFACE" latest-handshakes | grep -qP '\t[1-9][0-9]*$'; then
    echo "Handshake complete."
    break
  fi

  elapsed=$(( $(date +%s) - start_epoch ))
  if (( elapsed > HANDSHAKE_TIMEOUT_SECS )); then
    echo "FATAL: WireGuard handshake did not complete within ${HANDSHAKE_TIMEOUT_SECS}s" >&2
    echo "Interface status:" >&2
    sudo wg show "$WG_INTERFACE" >&2 || true
    exit 1
  fi

  sleep 0.25
done

# --- 6. API server TCP reachability check -----------------------------------
echo "Checking API server reachability at $K8S_API_HOST:$K8S_API_PORT..."
if ! timeout 5 bash -c "echo > /dev/tcp/$K8S_API_HOST/$K8S_API_PORT" 2>/dev/null; then
  echo "FATAL: API server not reachable at $K8S_API_HOST:$K8S_API_PORT" >&2
  exit 1
fi

# --- 7. Success -------------------------------------------------------------
echo "WireGuard tunnel ready — API server reachable at $K8S_API_HOST:$K8S_API_PORT"
