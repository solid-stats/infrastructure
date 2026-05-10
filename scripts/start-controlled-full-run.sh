#!/usr/bin/env bash
set -euo pipefail

namespace="${K8S_NAMESPACE:-solid-stats-staging}"
timeout="${FULL_RUN_TIMEOUT:-21600s}"
job_name="${1:-replays-fetcher-manual-$(date -u +%Y%m%d%H%M%S)}"
gate_file="${BACKUP_GATE_FILE:-docs/backup-gate.md}"

if ! grep -q "Status: verified" "$gate_file"; then
  echo "Backup gate is not verified in $gate_file; refusing to start full run." >&2
  exit 1
fi

kubectl -n "$namespace" delete "job/$job_name" --ignore-not-found
kubectl -n "$namespace" create job "$job_name" --from=cronjob/replays-fetcher

if ! kubectl -n "$namespace" wait --for=condition=complete "job/$job_name" --timeout="$timeout"; then
  kubectl -n "$namespace" describe "job/$job_name" || true
  kubectl -n "$namespace" logs "job/$job_name" --all-containers=true || true
  exit 1
fi

kubectl -n "$namespace" logs "job/$job_name" --all-containers=true
