#!/usr/bin/env bash
set -euo pipefail
# scripts/resource-preflight.sh
# Re-runnable snapshot of node CPU/memory/disk and existing pod allocations.
# Run before applying any observability workload to record headroom.
#
# Usage: KUBECONFIG=/path/to/kubeconfig bash scripts/resource-preflight.sh
#        (kubectl reachable via the SSH local-forward, or run on the k3s node over SSH)
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
  # Each probe is independently fault-tolerant: a single failing query must not abort
  # the whole snapshot under `set -e` (the snapshot is the deliverable).
  kubectl describe node || echo "(kubectl describe node failed)"
  echo ""
  echo "--- Node resource usage (live) ---"
  kubectl top nodes || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource usage (live, all namespaces) ---"
  kubectl top pods --all-namespaces || echo "(metrics-server not available)"
  echo ""
  echo "--- Pod resource requests/limits (namespace) ---"
  kubectl -n "${NAMESPACE}" get pods \
    -o custom-columns='NAME:.metadata.name,QOS:.status.qosClass,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory' \
    || echo "(pod query failed)"
  echo ""
  # NOTE: df -h / free -h report the host *where this script runs*. Run it ON the
  # k3s node (e.g. over SSH) for the node's real disk/memory; run from a WireGuard
  # operator workstation and these reflect the workstation, not the node.
  echo "--- Disk usage (host running this script) ---"
  df -h
  echo ""
  echo "--- Memory and swap (host running this script) ---"
  free -h
} | tee "${out_file}"

echo ""
echo "Snapshot written to: ${out_file}"
