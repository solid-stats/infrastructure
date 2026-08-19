#!/usr/bin/env bash
set -euo pipefail

# Open the staging API forward for legacy callers, or use the managed lifecycle
# modes below when a workflow must prove which process it is allowed to signal.
: "${LOCAL_PORT:=16443}"
: "${REMOTE_API_HOST:=127.0.0.1}"
: "${REMOTE_API_PORT:=6443}"
: "${REACHABILITY_TIMEOUT_SECS:=10}"

FORWARD="127.0.0.1:${LOCAL_PORT}:${REMOTE_API_HOST}:${REMOTE_API_PORT}"

required() {
  if [[ -z "${!1:-}" ]]; then
    echo "FATAL: $1 is required" >&2
    exit 64
  fi
}

require_connection_inputs() {
  required DEPLOY_SSH_PRIVATE_KEY
  required DEPLOY_SSH_KNOWN_HOSTS
  required DEPLOY_SSH_HOST
  required DEPLOY_SSH_USER
}

write_managed_pid() {
  local pid="$1" directory temporary
  required SSH_TUNNEL_PID_FILE
  directory=$(dirname "$SSH_TUNNEL_PID_FILE")
  mkdir -p "$directory"
  temporary=$(mktemp "$directory/.solidstats-memory-ssh.XXXXXX")
  chmod 600 "$temporary"
  printf '%s\n' "$pid" > "$temporary"
  mv -f "$temporary" "$SSH_TUNNEL_PID_FILE"
  chmod 600 "$SSH_TUNNEL_PID_FILE"
}

validate_managed_process() {
  local pid="$1" command
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  command=$(ps -p "$pid" -o args=) || return 1
  [[ "$command" == ssh\ -N\ * || "$command" == */ssh\ -N\ * || "$command" == *"/ssh -N "* ]] || return 1
  [[ "$command" == *" -N "* ]] || return 1
  [[ "$command" == *"-L ${FORWARD}"* ]] || return 1
  [[ "$command" == *"${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"* ]]
}

wait_for_reachability() {
  if [[ "${SSH_TUNNEL_SKIP_REACHABILITY_CHECK:-}" == "1" ]]; then
    return 0
  fi
  local start_epoch elapsed
  start_epoch=$(date +%s)
  while true; do
    if timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/${LOCAL_PORT}" 2>/dev/null; then
      return 0
    fi
    elapsed=$(( $(date +%s) - start_epoch ))
    if (( elapsed > REACHABILITY_TIMEOUT_SECS )); then
      return 1
    fi
    sleep 0.25
  done
}

stop_managed_tunnel() {
  required SSH_TUNNEL_PID_FILE
  required DEPLOY_SSH_HOST
  required DEPLOY_SSH_USER
  [[ -e "$SSH_TUNNEL_PID_FILE" ]] || return 0
  [[ ! -L "$SSH_TUNNEL_PID_FILE" ]] || { echo "FATAL: managed tunnel pidfile is a symlink" >&2; return 1; }
  local pid
  pid=$(<"$SSH_TUNNEL_PID_FILE")
  validate_managed_process "$pid" || { echo "FATAL: managed tunnel PID is stale or mismatched" >&2; return 1; }
  kill -TERM "$pid"
  local attempt
  for attempt in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$SSH_TUNNEL_PID_FILE"
      return 0
    fi
    sleep 0.25
  done
  validate_managed_process "$pid" || { echo "FATAL: refusing to kill changed tunnel process" >&2; return 1; }
  kill -KILL "$pid"
  for attempt in {1..4}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$SSH_TUNNEL_PID_FILE"
      return 0
    fi
    sleep 0.25
  done
  echo "FATAL: managed tunnel did not exit" >&2
  return 1
}

start_tunnel() {
  local managed="$1" key_file known_hosts_file pid
  require_connection_inputs
  key_file=$(mktemp)
  known_hosts_file=$(mktemp)
  trap 'rm -f "$key_file" "$known_hosts_file"' RETURN
  printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > "$key_file"
  chmod 600 "$key_file"
  printf '%s\n' "$DEPLOY_SSH_KNOWN_HOSTS" > "$known_hosts_file"
  if [[ "$managed" == "true" ]]; then
    required SSH_TUNNEL_PID_FILE
    ssh -N -L "$FORWARD" -i "$key_file" -o BatchMode=yes -o IdentitiesOnly=yes \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known_hosts_file" \
      "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}" &
    pid=$!
    write_managed_pid "$pid"
  else
    ssh -fN -L "$FORWARD" -i "$key_file" -o BatchMode=yes -o IdentitiesOnly=yes \
      -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
      -o ConnectTimeout=10 -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$known_hosts_file" \
      "${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"
  fi
  if ! wait_for_reachability; then
    echo "FATAL: SSH local-forward 127.0.0.1:${LOCAL_PORT} not reachable within ${REACHABILITY_TIMEOUT_SECS}s" >&2
    [[ "$managed" == "true" ]] && stop_managed_tunnel || true
    return 1
  fi
  echo "SSH tunnel ready — k3s API reachable at 127.0.0.1:${LOCAL_PORT}"
}

case "${1:-}" in
  --start-managed) start_tunnel true ;;
  --stop-managed) stop_managed_tunnel ;;
  "") start_tunnel false ;;
  *) echo "usage: $0 [--start-managed|--stop-managed]" >&2; exit 64 ;;
esac
