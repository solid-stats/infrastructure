#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-phase-12.sh
# Phase 12 assertion harness — wraps every PREP-01..05 kubectl assertion.
# Exits 1 on the first failure.
#
# Run after all Phase 12 manifests have been applied to the cluster:
#   bash scripts/validate-phase-12.sh
#
# Requires: kubectl configured and pointing at solid-stats-staging cluster
#           (kubectl reachable — SSH local-forward up from operator workstation or CI, or run on the staging node over SSH).
#
# PREP-02 (host swap) cannot be checked from kubectl context — a note is
# printed directing the operator to the manual SSH verification step.

namespace="${K8S_NAMESPACE:-solid-stats-staging}"

# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------
assert() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL: ${label} — got '${actual}', want '${expected}'" >&2
    exit 1
  fi
  echo "ok: ${label}"
}

echo "=== Phase 12 Validation ==="
echo "namespace=${namespace}"
echo ""

# ---------------------------------------------------------------------------
# PREP-03: PriorityClasses exist with correct values
# ---------------------------------------------------------------------------
echo "--- PREP-03: PriorityClasses ---"

kubectl get priorityclass app-critical obs-background > /dev/null

app_critical_value="$(kubectl get priorityclass app-critical \
  -o jsonpath='{.value}')"
assert "app-critical value" "$app_critical_value" "1000000"

obs_background_value="$(kubectl get priorityclass obs-background \
  -o jsonpath='{.value}')"
assert "obs-background value" "$obs_background_value" "100"

# ---------------------------------------------------------------------------
# PREP-03: App workloads carry priorityClassName: app-critical
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-03: App pod priorityClassName ---"

for workload in postgres server-2 replay-parser-2 rabbitmq; do
  pc="$(kubectl -n "${namespace}" get pods \
    -l "app.kubernetes.io/name=${workload}" \
    -o jsonpath='{.items[0].spec.priorityClassName}' 2>/dev/null || true)"
  # postgres uses the StatefulSet pod name directly; fall back to pod name prefix
  if [[ -z "$pc" ]]; then
    pc="$(kubectl -n "${namespace}" get pod "${workload}-0" \
      -o jsonpath='{.spec.priorityClassName}' 2>/dev/null || true)"
  fi
  assert "${workload} priorityClassName" "$pc" "app-critical"
done

# web runs as a Deployment that may be scaled to 0 (no pod to inspect), so assert
# the controller's pod template carries the priorityClassName. A runtime workload
# without it would default to priority 0 — BELOW obs-background (100) — and be
# evicted before observability pods, inverting the protection (CR-01).
web_pc="$(kubectl -n "${namespace}" get deployment web \
  -o jsonpath='{.spec.template.spec.priorityClassName}' 2>/dev/null || true)"
assert "web priorityClassName (deployment template)" "$web_pc" "app-critical"

# ---------------------------------------------------------------------------
# PREP-04: postgres pod QoS == Guaranteed
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-04: QoS class ---"

postgres_qos="$(kubectl -n "${namespace}" get pod postgres-0 \
  -o jsonpath='{.status.qosClass}')"
assert "postgres-0 qosClass" "$postgres_qos" "Guaranteed"

server2_qos="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=server-2" \
  -o jsonpath='{.items[0].status.qosClass}')"
assert "server-2 qosClass" "$server2_qos" "Guaranteed"

# ---------------------------------------------------------------------------
# PREP-05: Observability namespaces exist
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-05: Namespaces ---"

kubectl get namespace monitoring error-tracking > /dev/null
echo "ok: monitoring and error-tracking namespaces exist"

# ---------------------------------------------------------------------------
# PREP-05: obs-ci-deployer SA exists in each namespace
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-05: ServiceAccounts ---"

kubectl -n monitoring get serviceaccount obs-ci-deployer > /dev/null
echo "ok: obs-ci-deployer SA exists in monitoring"

kubectl -n error-tracking get serviceaccount obs-ci-deployer > /dev/null
echo "ok: obs-ci-deployer SA exists in error-tracking"

# ---------------------------------------------------------------------------
# PREP-05: Positive RBAC — obs-ci-deployer CAN create deployments in monitoring
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-05: RBAC isolation ---"

# `kubectl auth can-i` signals the answer via exit code (0 for "yes", 1 for "no"),
# which trips `set -e` on the command substitution. Capture stdout and swallow the
# exit code with `|| true` so the assert below — not the exit code — is the gate.
can_deploy="$(kubectl auth can-i create deployments \
  --as=system:serviceaccount:monitoring:obs-ci-deployer \
  -n monitoring 2>/dev/null || true)"
assert "obs-ci-deployer can create deployments in monitoring" "$can_deploy" "yes"

# ---------------------------------------------------------------------------
# PREP-05: Negative RBAC — obs-ci-deployer CANNOT access solid-stats-staging
# ---------------------------------------------------------------------------

cannot_access="$(kubectl auth can-i get pods \
  --as=system:serviceaccount:monitoring:obs-ci-deployer \
  -n "${namespace}" 2>/dev/null || true)"
assert "obs-ci-deployer cannot get pods in ${namespace}" "$cannot_access" "no"

# ---------------------------------------------------------------------------
# PREP-02: Host swap — manual SSH check required (cannot assert over kubectl)
# ---------------------------------------------------------------------------
echo ""
echo "--- PREP-02: Host swap (manual check) ---"
echo "note: swap verification requires SSH access to the VPS."
echo "      Run manually: ssh root@89.223.124.200 'free -h && grep swapfile /proc/swaps && grep swap /etc/fstab && systemctl is-active k3s'"

# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 12 validation PASSED ==="
