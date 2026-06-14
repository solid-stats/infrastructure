#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# ssh-tunnel-up.sh — SSH Tunnel Pre-flight Gate for CI
#
# Opens a background SSH local-forward (LOCAL_PORT -> REMOTE_API_HOST:REMOTE_API_PORT)
# and fail-closed verifies TCP reachability of the forwarded port.  Exits 64 on
# missing required configuration; exits 1 if the forward is not reachable within
# REACHABILITY_TIMEOUT_SECS (fail-closed gate — analogous to wg-tunnel-up.sh's
# handshake-timeout gate — no kubectl runs without a confirmed reachable port).
#
# Usage (called from GitHub Actions step with env vars from secrets):
#   DEPLOY_SSH_PRIVATE_KEY=<key> DEPLOY_SSH_KNOWN_HOSTS=<known_hosts> \
#   DEPLOY_SSH_HOST=<host> DEPLOY_SSH_USER=<user> \
#     scripts/ssh-tunnel-up.sh
# ---------------------------------------------------------------------------

# --- Optional vars with defaults -------------------------------------------
: "${LOCAL_PORT:=16443}"
: "${REMOTE_API_HOST:=127.0.0.1}"
: "${REMOTE_API_PORT:=6443}"
: "${REACHABILITY_TIMEOUT_SECS:=10}"

# --- Required vars (exit 64 if missing) ------------------------------------
if [[ -z "${DEPLOY_SSH_PRIVATE_KEY:-}" ]]; then
  echo "FATAL: DEPLOY_SSH_PRIVATE_KEY is required" >&2
  exit 64
fi
if [[ -z "${DEPLOY_SSH_KNOWN_HOSTS:-}" ]]; then
  echo "FATAL: DEPLOY_SSH_KNOWN_HOSTS is required" >&2
  exit 64
fi
if [[ -z "${DEPLOY_SSH_HOST:-}" ]]; then
  echo "FATAL: DEPLOY_SSH_HOST is required" >&2
  exit 64
fi
if [[ -z "${DEPLOY_SSH_USER:-}" ]]; then
  echo "FATAL: DEPLOY_SSH_USER is required" >&2
  exit 64
fi

echo "=== SSH Tunnel Pre-flight Gate ==="

# --- 1. Write key and known_hosts to secure temp files ---------------------
# ssh requires the identity file on disk; a chmod-600 temp file removed on EXIT
# is the closest analogue to wg-tunnel-up.sh's /dev/stdin discipline — the
# key is on disk only for the lifetime of this script and never printed.
key_file=$(mktemp)
known_hosts_file=$(mktemp)
trap 'rm -f "$key_file" "$known_hosts_file"' EXIT

# Trailing newline is REQUIRED: OpenSSH private keys must end with a newline
# after the "-----END ... PRIVATE KEY-----" line, and a secret round-tripped
# through a GitHub Actions env var arrives without one — writing it with a bare
# `printf '%s'` yields "Load key: error in libcrypto" + publickey auth failure.
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > "$key_file"
chmod 600 "$key_file"
printf '%s\n' "$DEPLOY_SSH_KNOWN_HOSTS" > "$known_hosts_file"

# --- 2. Open background SSH local-forward ----------------------------------
# ExitOnForwardFailure=yes: ssh exits non-zero if the listener cannot bind,
# rather than silently succeeding with no active forward.
# StrictHostKeyChecking=yes + UserKnownHostsFile: pin the host key via the
# temp known_hosts; NEVER set StrictHostKeyChecking to no or accept-new.
echo "Opening SSH local-forward 127.0.0.1:${LOCAL_PORT} -> k3s API..."
ssh -fN \
  -L "${LOCAL_PORT}:${REMOTE_API_HOST}:${REMOTE_API_PORT}" \
  -i "$key_file" \
  -o BatchMode=yes \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="$known_hosts_file" \
  "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"

# --- 3. Fail-closed TCP reachability probe ----------------------------------
# ssh -fN backgrounds before the listener is necessarily bound, so poll until
# the port is reachable or REACHABILITY_TIMEOUT_SECS elapses (fail-closed).
echo "Waiting for local-forward to become reachable (timeout: ${REACHABILITY_TIMEOUT_SECS}s)..."
start_epoch=$(date +%s)
while true; do
  if timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/${LOCAL_PORT}" 2>/dev/null; then
    echo "Local-forward reachable."
    break
  fi

  elapsed=$(( $(date +%s) - start_epoch ))
  if (( elapsed > REACHABILITY_TIMEOUT_SECS )); then
    echo "FATAL: SSH local-forward 127.0.0.1:${LOCAL_PORT} not reachable within ${REACHABILITY_TIMEOUT_SECS}s" >&2
    exit 1
  fi

  sleep 0.25
done

# --- 4. Success -------------------------------------------------------------
echo "SSH tunnel ready — k3s API reachable at 127.0.0.1:${LOCAL_PORT}"
