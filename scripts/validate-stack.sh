#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-stack.sh
# VAL-01: Full observability stack validation orchestrator.
# Composes validate-phase-13.sh (metrics), validate-phase-15.sh (logs),
# validate-phase-16.sh (error-tracking). Fails loudly on first sub-script failure.
#
# Usage:
#   bash scripts/validate-stack.sh [--quick] [--public]
#
# Flags:
#   --quick    Pass to all three sub-scripts.
#              Skips Grafana port-forward checks (metrics + logs datasource health)
#              and the forced GlitchTip error-ingest test. Intended for the
#              pre-NetworkPolicy baseline pass (17-03 step 1).
#   --public   Pass only to validate-phase-16.sh (GlitchTip checks via the public
#              errors.solid-stats.ru URL instead of port-forward).
#
# Required env (full / non-quick run):
#   GRAFANA_ADMIN_PASSWORD  — Grafana API auth for datasource + dashboard checks
#                             (validate-phase-13.sh MET-05/06, validate-phase-15.sh LOG-03)
#   GLITCHTIP_DSN           — Project DSN for forced-error ingest test
#                             (validate-phase-16.sh ERR-03). If unset, that test is
#                             noted as skipped (NOT a failure) — matches the sub-script.
#
# Optional env:
#   SUPERUSER_TOKEN           — GlitchTip Bearer token for project/issue queries
#                               (validate-phase-16.sh ERR-03)
#   GLITCHTIP_PUBLIC_URL      — Public URL for --public mode
#                               (default: https://errors.solid-stats.ru)
#   K8S_NAMESPACE_MONITORING  — Override the monitoring namespace (default: monitoring)
#   K8S_NAMESPACE_ERROR       — Override the error-tracking namespace (default: error-tracking)
#
# Notes:
#   - The --quick flag is the intended pre-policy pass: proves Prometheus targets UP
#     and pods are Running without requiring a port-forward or a live GlitchTip DSN.
#   - The full (non-quick) run is the intended post-policy pass: exercises Grafana
#     port-forward (traverses allow-grafana-ingress), Loki LogQL, and GlitchTip ingest.
#   - Secret env values (GRAFANA_ADMIN_PASSWORD, GLITCHTIP_DSN, SUPERUSER_TOKEN) are
#     never echoed; they are passed through to the sub-scripts which own that contract.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------
quick=false
public_flag=""

for arg in "$@"; do
  case "$arg" in
    --quick)  quick=true ;;
    --public) public_flag="--public" ;;
    *) echo "FATAL: unknown flag: ${arg}" >&2; exit 1 ;;
  esac
done

# Build the common flags string for phase-13 and phase-15 (do NOT include --public)
common_flags=""
if [[ "$quick" == "true" ]]; then
  common_flags="--quick"
fi

# Build the flags string for phase-16 (accepts both --quick and --public)
phase16_flags=""
if [[ "$quick" == "true" ]]; then
  phase16_flags="--quick"
fi
if [[ -n "$public_flag" ]]; then
  phase16_flags="${phase16_flags:+${phase16_flags} }${public_flag}"
fi

# ---------------------------------------------------------------------------
# Preflight: cluster must be reachable before any sub-script runs
# ---------------------------------------------------------------------------
echo "================================================================"
echo "=== Full Stack Validation — Preflight ==="
echo "================================================================"
echo ""
echo "Checking cluster reachability..."

if ! kubectl cluster-info --request-timeout=5s >/dev/null 2>&1; then
  echo "FATAL: kubectl cluster-info failed — cluster is unreachable or kubectl is not configured." >&2
  echo "       Ensure the SSH local-forward to the k3s API is up (scripts/ssh-tunnel-up.sh, or" >&2
  echo "       an operator 'ssh -L 16443:127.0.0.1:6443') and KUBECONFIG points at the staging cluster." >&2
  exit 1
fi
echo "ok: cluster is reachable"
echo ""

# ---------------------------------------------------------------------------
# Phase 13 — Metrics (Prometheus + Grafana datasource + dashboards)
# ---------------------------------------------------------------------------
echo "================================================================"
echo "=== Phase 13: Metrics (Prometheus + Grafana) ==="
echo "================================================================"
echo ""

K8S_NAMESPACE="${K8S_NAMESPACE_MONITORING:-monitoring}" \
  bash "${SCRIPT_DIR}/validate-phase-13.sh" ${common_flags}

echo ""

# ---------------------------------------------------------------------------
# Phase 15 — Logs (Loki + Alloy + Grafana Loki datasource)
# ---------------------------------------------------------------------------
echo "================================================================"
echo "=== Phase 15: Logs (Loki + Alloy) ==="
echo "================================================================"
echo ""

K8S_NAMESPACE="${K8S_NAMESPACE_MONITORING:-monitoring}" \
  bash "${SCRIPT_DIR}/validate-phase-15.sh" ${common_flags}

echo ""

# ---------------------------------------------------------------------------
# Phase 16 — Error Tracking (GlitchTip)
# ---------------------------------------------------------------------------
echo "================================================================"
echo "=== Phase 16: Error Tracking (GlitchTip) ==="
echo "================================================================"
echo ""

K8S_NAMESPACE="${K8S_NAMESPACE_ERROR:-error-tracking}" \
  bash "${SCRIPT_DIR}/validate-phase-16.sh" ${phase16_flags}

echo ""

# ---------------------------------------------------------------------------
# All sub-scripts passed (set -euo pipefail aborts on any non-zero exit above)
# ---------------------------------------------------------------------------
echo "================================================================"
echo "=== FULL STACK VALIDATION PASSED ==="
echo "================================================================"
