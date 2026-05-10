#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="${K8S_NAMESPACE:-solid-stats-staging}"
ssh_port="${CD_SSH_PORT:-22}"
target="${CD_SSH_USER:?CD_SSH_USER is required}@${CD_SSH_HOST:?CD_SSH_HOST is required}"
ssh_key="${CD_SSH_KEY_PATH:-}"

ssh_args=(-p "$ssh_port")
scp_args=(-P "$ssh_port")
if [[ -n "$ssh_key" ]]; then
  ssh_args=(-i "$ssh_key" "${ssh_args[@]}")
  scp_args=(-i "$ssh_key" "${scp_args[@]}")
fi

tmp_secrets="$(mktemp)"
trap 'rm -f "$tmp_secrets"' EXIT

K8S_NAMESPACE="$namespace" "$repo_root/scripts/render-staging-secrets.py" > "$tmp_secrets"

ssh "${ssh_args[@]}" "$target" "kubectl get namespace '$namespace' >/dev/null 2>&1 || kubectl create namespace '$namespace'"
scp "${scp_args[@]}" "$tmp_secrets" "$target:/tmp/solid-stats-staging-secrets.yaml"
ssh "${ssh_args[@]}" "$target" "kubectl apply -f /tmp/solid-stats-staging-secrets.yaml && rm -f /tmp/solid-stats-staging-secrets.yaml"

awk 'FNR == 1 { print "---" } { print }' "$repo_root"/k8s/staging/*.yaml \
  | ssh "${ssh_args[@]}" "$target" "kubectl apply -f -"

ssh "${ssh_args[@]}" "$target" "kubectl -n '$namespace' rollout status statefulset/postgres --timeout=300s"
ssh "${ssh_args[@]}" "$target" "kubectl -n '$namespace' rollout status statefulset/rabbitmq --timeout=300s"
ssh "${ssh_args[@]}" "$target" "kubectl -n '$namespace' rollout status deployment/server-2 --timeout=300s"
ssh "${ssh_args[@]}" "$target" "kubectl -n '$namespace' rollout status deployment/replay-parser-2 --timeout=300s"
ssh "${ssh_args[@]}" "$target" "kubectl -n '$namespace' get cronjob replays-fetcher postgres-backup -o wide"
