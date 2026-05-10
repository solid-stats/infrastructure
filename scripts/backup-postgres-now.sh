#!/usr/bin/env bash
set -euo pipefail

namespace="${K8S_NAMESPACE:-solid-stats-staging}"
timeout="${BACKUP_TIMEOUT:-900s}"
job_name="${1:-postgres-backup-manual-$(date -u +%Y%m%d%H%M%S)}"

kubectl -n "$namespace" delete "job/$job_name" --ignore-not-found
kubectl -n "$namespace" create job "$job_name" --from=cronjob/postgres-backup

if ! kubectl -n "$namespace" wait --for=condition=complete "job/$job_name" --timeout="$timeout"; then
  kubectl -n "$namespace" describe "job/$job_name" || true
  kubectl -n "$namespace" logs "job/$job_name" --all-containers=true || true
  exit 1
fi

kubectl -n "$namespace" logs "job/$job_name" --all-containers=true
logs="$(kubectl -n "$namespace" logs "job/$job_name" --all-containers=true)"

backup_id="$(printf '%s\n' "$logs" | awk -F= '/^backup_id=/{print $2}' | tail -1)"
dump_object="$(printf '%s\n' "$logs" | awk -F= '/^dump_object=/{print $2}' | tail -1)"
dump_size_bytes="$(printf '%s\n' "$logs" | awk -F= '/^dump_size_bytes=/{print $2}' | tail -1)"

echo
echo "Backup gate summary"
echo "backup_id=${backup_id:-MISSING}"
echo "dump_object=${dump_object:-MISSING}"
echo "dump_size_bytes=${dump_size_bytes:-MISSING}"

if [[ -z "$backup_id" || -z "$dump_object" || -z "$dump_size_bytes" ]]; then
  echo "Backup gate failed: backup evidence is incomplete" >&2
  exit 1
fi
