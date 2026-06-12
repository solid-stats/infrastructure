#!/usr/bin/env bash
set -euo pipefail

# Usage: K8S_NAMESPACE=solid-stats-staging bash scripts/restore-drill.sh
# Applies the restore drill Job, tails logs, confirms PASS/FAIL evidence, then cleans up.
# Requires: kubectl in PATH, WireGuard tunnel up (if running against remote cluster).

namespace="${K8S_NAMESPACE:-solid-stats-staging}"
timeout="${DRILL_TIMEOUT:-900s}"
job_name="restore-drill"
manifest="k8s/staging/restore-drill/70-restore-drill.yaml"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "error: kubectl not found in PATH" >&2; exit 64; fi

kubectl -n "$namespace" delete job "$job_name" --ignore-not-found
kubectl -n "$namespace" apply -f "$manifest"

if ! kubectl -n "$namespace" wait \
    --for=condition=complete "job/$job_name" --timeout="$timeout" 2>/dev/null; then
  echo "Drill Job did not complete — checking for failure..." >&2
  kubectl -n "$namespace" describe "job/$job_name" || true
  kubectl -n "$namespace" logs "job/$job_name" --all-containers=true || true
  exit 1
fi

logs="$(kubectl -n "$namespace" logs "job/$job_name" --all-containers=true)"
printf '%s\n' "$logs"

result_line="$(printf '%s\n' "$logs" | grep '^DRILL_RESULT=' | tail -1)"
if [ -z "$result_line" ]; then
  echo "error: no DRILL_RESULT line found in job logs" >&2; exit 1; fi

echo ""
echo "=== Restore Drill Evidence ==="
echo "$result_line"

if printf '%s\n' "$result_line" | grep -q 'DRILL_RESULT=FAIL'; then
  echo "RESTORE DRILL FAILED" >&2; exit 1; fi

echo "RESTORE DRILL PASSED"

kubectl -n "$namespace" delete "job/$job_name" --ignore-not-found
