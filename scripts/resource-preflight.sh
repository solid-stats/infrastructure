#!/usr/bin/env bash
set -euo pipefail
# scripts/resource-preflight.sh
# Re-runnable snapshot of node CPU/memory/disk and existing pod allocations.
# Run before applying any observability workload to record headroom.
#
# Usage: KUBECONFIG=/path/to/kubeconfig bash scripts/resource-preflight.sh
#        (or from operator workstation with WireGuard tunnel up)
#
# Output: timestamped snapshot written to OUTPUT_DIR (default /tmp).
# Environment variables:
#   NAMESPACE           — target namespace (default: solid-stats-staging)
#   OUTPUT_DIR          — output directory for snapshot file (default: /tmp)
#   PREFLIGHT_OUTPUT_DIR — alias for OUTPUT_DIR (lower priority)

: "${NAMESPACE:=solid-stats-staging}"
: "${OUTPUT_DIR:=${PREFLIGHT_OUTPUT_DIR:-/tmp}}"

snapshot_ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="${OUTPUT_DIR}/resource-preflight-${snapshot_ts}.txt"

{
  echo "=== Resource Preflight Snapshot ==="
  echo "timestamp=${snapshot_ts}"
  echo "namespace=${NAMESPACE}"
  echo ""
  echo "--- Node allocatable vs allocated ---"
  kubectl describe node
  echo ""
  echo "--- Node resource usage (live) ---"
  kubectl top nodes || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource usage (live, all namespaces) ---"
  kubectl top pods --all-namespaces || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource requests/limits (namespace) ---"
  kubectl -n "${NAMESPACE}" get pods \
    -o custom-columns='NAME:.metadata.name,QOS:.status.qosClass,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory'
  echo ""
  echo "--- Node disk usage ---"
  df -h
  echo ""
  echo "--- Host memory and swap ---"
  free -h
} | tee "${out_file}"

echo ""
echo "Snapshot written to: ${out_file}"
