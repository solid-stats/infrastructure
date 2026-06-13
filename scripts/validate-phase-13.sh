#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-phase-13.sh
# Phase 13 live assertion harness — covers MET-01..06.
# Exits 1 on first failure.
#
# Run after all Phase 13 obs manifests have been applied to the cluster
# (WireGuard tunnel up from operator workstation or CI):
#   bash scripts/validate-phase-13.sh
#
# Flags:
#   --quick    Skip Grafana port-forward checks (MET-05, MET-06).
#              Use when cluster access is available but operator cannot port-forward.
#
# Prerequisites:
#   - kubectl configured and pointing at staging cluster
#   - GRAFANA_ADMIN_PASSWORD env var set (for MET-05/06 Grafana API checks)
#
# MET-06 panels rendering live data is a manual operator confirmation (printed
# as a note at the end, not asserted automatically).

namespace="${K8S_NAMESPACE:-monitoring}"
quick=false

for arg in "$@"; do
  case "$arg" in
    --quick) quick=true ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

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

echo "=== Phase 13 Validation ==="
echo "namespace=${namespace}"
echo "quick=${quick}"
echo ""

# ---------------------------------------------------------------------------
# MET-01: Prometheus pod Running + retention bounded
# ---------------------------------------------------------------------------
echo "--- MET-01: Prometheus Running ---"

prometheus_phase="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=prometheus,app.kubernetes.io/component=server" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"

# Fallback label selector used by the community chart (release=prometheus)
if [[ -z "$prometheus_phase" ]]; then
  prometheus_phase="$(kubectl -n "${namespace}" get pod \
    -l "app=prometheus,component=server" \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
fi

assert "MET-01: prometheus-server pod phase" "$prometheus_phase" "Running"

echo "--- MET-01: Prometheus retention config ---"
# Query Prometheus config API via exec into the server pod.
# wget -qO- exits nonzero on HTTP error; capture with || true and assert below.
prometheus_config="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- http://localhost:9090/api/v1/status/config 2>/dev/null || true)"

if echo "$prometheus_config" | grep -q '"status":"success"'; then
  if echo "$prometheus_config" | grep -q '15d'; then
    echo "ok: MET-01: Prometheus retention config contains '15d'"
  else
    echo "FAIL: MET-01: Prometheus config does not contain '15d' retention" >&2
    exit 1
  fi
else
  echo "FAIL: MET-01: Prometheus /api/v1/status/config did not return success" >&2
  echo "      Response: ${prometheus_config:0:200}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# MET-02/03/04: Scrape targets UP (kube-state-metrics, node-exporter,
#               postgres-exporter, rabbitmq)
# ---------------------------------------------------------------------------
echo ""
echo "--- MET-02/03/04: Scrape targets ---"

targets_json="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/targets' 2>/dev/null || true)"

if ! echo "$targets_json" | grep -q '"status":"success"'; then
  echo "FAIL: MET-02: Prometheus /api/v1/targets did not return success" >&2
  echo "      Response: ${targets_json:0:200}" >&2
  exit 1
fi

# Parse target health per job using a stdlib python3 one-liner.
check_target_health() {
  local job_pattern="$1"
  local label="$2"
  local health
  health="$(echo "$targets_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
targets = data.get('data', {}).get('activeTargets', [])
matches = [t for t in targets if '${job_pattern}' in t.get('labels', {}).get('job', '')]
if not matches:
    print('no_targets')
elif all(t.get('health') == 'up' for t in matches):
    print('up')
else:
    statuses = [t.get('health','?') for t in matches]
    print('down:' + ','.join(statuses))
" 2>/dev/null || echo "parse_error")"
  assert "${label} target health" "$health" "up"
}

# MET-02: kube-state-metrics
check_target_health "kube-state" "MET-02: kube-state-metrics"

# MET-02: node-exporter
check_target_health "node-exporter" "MET-02: node-exporter"

# MET-03: postgres-exporter
check_target_health "postgres-exporter" "MET-03: postgres-exporter"

# MET-04: rabbitmq native plugin
check_target_health "rabbitmq" "MET-04: rabbitmq"

# ---------------------------------------------------------------------------
# MET-03: pg_up == 1 (postgres-exporter actually connected to DB)
# ---------------------------------------------------------------------------
echo ""
echo "--- MET-03: pg_up metric ---"

pg_up_result="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=pg_up' 2>/dev/null || true)"

pg_up_value="$(echo "$pg_up_result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('data', {}).get('result', [])
if not results:
    print('no_data')
else:
    # Take the first result value (index 1 of the [timestamp, value] pair)
    print(results[0].get('value', [None, 'no_value'])[1])
" 2>/dev/null || echo "parse_error")"

assert "MET-03: pg_up" "$pg_up_value" "1"

# ---------------------------------------------------------------------------
# MET-04: rabbitmq_identity_info metric present
# ---------------------------------------------------------------------------
echo ""
echo "--- MET-04: rabbitmq_identity_info metric ---"

rmq_result="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=rabbitmq_identity_info' 2>/dev/null || true)"

rmq_has_data="$(echo "$rmq_result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('data', {}).get('result', [])
print('present' if results else 'absent')
" 2>/dev/null || echo "parse_error")"

assert "MET-04: rabbitmq_identity_info" "$rmq_has_data" "present"

# ---------------------------------------------------------------------------
# MET-05: Grafana datasource healthy (skipped under --quick)
# ---------------------------------------------------------------------------
echo ""
echo "--- MET-05: Grafana datasource ---"

if [[ "$quick" == "true" ]]; then
  echo "skip: MET-05: Grafana port-forward checks skipped (--quick)"
else
  grafana_password="${GRAFANA_ADMIN_PASSWORD:-}"
  if [[ -z "$grafana_password" ]]; then
    echo "FAIL: MET-05: GRAFANA_ADMIN_PASSWORD env var not set" >&2
    exit 1
  fi

  # Start port-forward in background; give it a moment to bind.
  kubectl -n "${namespace}" port-forward svc/grafana 13000:80 >/dev/null 2>&1 &
  pf_pid=$!
  trap 'kill "$pf_pid" 2>/dev/null || true' EXIT

  sleep 3

  ds_health="$(curl -s -u "admin:${grafana_password}" \
    "http://localhost:13000/api/datasources/1/health" 2>/dev/null || echo '{}')"

  ds_status="$(echo "$ds_health" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('status', 'unknown'))
" 2>/dev/null || echo "parse_error")"

  assert "MET-05: Grafana datasource health" "$ds_status" "OK"

  # ---------------------------------------------------------------------------
  # MET-06: >=4 dashboards provisioned
  # ---------------------------------------------------------------------------
  echo ""
  echo "--- MET-06: Grafana dashboards provisioned ---"

  dashboards_json="$(curl -s -u "admin:${grafana_password}" \
    "http://localhost:13000/api/search?query=" 2>/dev/null || echo '[]')"

  dashboard_count="$(echo "$dashboards_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(len([d for d in data if d.get('type') == 'dash-db']))
" 2>/dev/null || echo "0")"

  if [[ "$dashboard_count" -lt 4 ]]; then
    echo "FAIL: MET-06: expected >=4 dashboards, got ${dashboard_count}" >&2
    exit 1
  fi
  echo "ok: MET-06: ${dashboard_count} dashboards provisioned (>= 4 required)"

  kill "$pf_pid" 2>/dev/null || true
  trap - EXIT
fi

# ---------------------------------------------------------------------------
# Manual note: MET-06 panel data (cannot be asserted automatically)
# ---------------------------------------------------------------------------
echo ""
echo "--- MET-06: Manual panel data check (operator action required) ---"
echo "note: To confirm dashboards render live non-zero data:"
echo "      kubectl -n monitoring port-forward svc/grafana 3000:80"
echo "      Then open http://localhost:3000 in a browser (admin / GRAFANA_ADMIN_PASSWORD)."
echo "      Confirm that Node Exporter, PostgreSQL, RabbitMQ, and kube-state dashboards"
echo "      show non-zero metric values (not empty/no-data panels)."

# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 13 validation PASSED ==="
