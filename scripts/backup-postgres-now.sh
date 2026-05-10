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
