#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-phase-15.sh
# Phase 15 live assertion harness — covers LOG-01, LOG-02, LOG-03.
# Exits 1 on first failure.
#
# Run after all Phase 15 obs manifests have been applied to the cluster
# (WireGuard tunnel up from operator workstation or CI):
#   bash scripts/validate-phase-15.sh
#
# Flags:
#   --quick    Skip Grafana port-forward checks (LOG-03 datasource health).
#              Use when cluster access is available but operator cannot port-forward.
#
# Prerequisites:
#   - kubectl configured and pointing at staging cluster
#   - GRAFANA_ADMIN_PASSWORD env var set (for LOG-03 Grafana API checks)
#
# Metric names used (CORRECTED — see 15-RESEARCH.md § Pitfall 2):
#   LOG-01 compactor: loki_boltdb_shipper_compactor_running  (gauge, 1=active)
#   LOG-02 entries:   loki_write_sent_entries_total           (Alloy loki.write counter)
#   NOTE: names listed in the ROADMAP brief do NOT exist in Loki/Alloy source; see RESEARCH.
#
# LOG-03 Grafana datasource check and LogQL acceptance query are skipped under --quick.

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

assert_not() {
  local label="$1"
  local actual="$2"
  local not_expected="$3"
  if [[ "$actual" == "$not_expected" ]]; then
    echo "FAIL: ${label} — got '${actual}', want anything except '${not_expected}'" >&2
    exit 1
  fi
  echo "ok: ${label} (value=${actual})"
}

echo "=== Phase 15 Validation ==="
echo "namespace=${namespace}"
echo "quick=${quick}"
echo ""

# ---------------------------------------------------------------------------
# LOG-01: Loki pod Running
# ---------------------------------------------------------------------------
echo "--- LOG-01: Loki pod Running ---"

loki_phase="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=loki,app.kubernetes.io/component=single-binary" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"

# Fallback: any loki pod
if [[ -z "$loki_phase" ]]; then
  loki_phase="$(kubectl -n "${namespace}" get pod \
    -l "app.kubernetes.io/name=loki" \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
fi

assert "LOG-01: loki pod phase" "$loki_phase" "Running"

# ---------------------------------------------------------------------------
# LOG-01: Loki PVC Bound
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-01: Loki PVC Bound ---"

loki_pvc_phase="$(kubectl -n "${namespace}" get pvc \
  -l "app.kubernetes.io/name=loki" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"

assert "LOG-01: loki PVC phase" "$loki_pvc_phase" "Bound"

# ---------------------------------------------------------------------------
# LOG-01: Compactor active (loki_boltdb_shipper_compactor_running == 1)
# Correct metric name verified from Loki source pkg/compactor/metrics.go
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-01: Loki compactor active ---"

compactor_result="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=loki_boltdb_shipper_compactor_running' \
  2>/dev/null || true)"

compactor_running="$(echo "$compactor_result" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '0')" \
  2>/dev/null || echo "0")"

assert "LOG-01: loki_boltdb_shipper_compactor_running" "$compactor_running" "1"

# ---------------------------------------------------------------------------
# LOG-01: Loki config contains retention_period 168h
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-01: Loki retention config ---"

# Read the live Loki ConfigMap (source of truth) rather than the /config HTTP endpoint:
# the loki image is distroless (no wget/sh to exec), and Loki normalizes 168h -> "1w"
# in /config output. The ConfigMap carries the literal limits_config.retention_period.
loki_config="$(kubectl -n "${namespace}" get configmap loki \
  -o jsonpath='{.data.config\.yaml}' 2>/dev/null || true)"

if echo "$loki_config" | grep -qE 'retention_period:[[:space:]]*(168h|1w)'; then
  echo "ok: LOG-01: loki ConfigMap has retention_period 168h (~7d)"
else
  echo "FAIL: LOG-01: loki ConfigMap retention_period is not 168h/1w" >&2
  echo "      Config excerpt: $(echo "$loki_config" | grep -i retention | head -5 || echo '(none)')" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# LOG-02: Alloy DaemonSet numberReady == 1
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-02: Alloy DaemonSet ready ---"

alloy_ready="$(kubectl -n "${namespace}" get ds alloy \
  -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")"

assert "LOG-02: alloy DaemonSet numberReady" "$alloy_ready" "1"

# ---------------------------------------------------------------------------
# LOG-02: Log entries being pushed (loki_write_sent_entries_total > 0)
# Correct metric name from Alloy loki.write component docs
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-02: Alloy entries shipped to Loki ---"

entries_result="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=loki_write_sent_entries_total' \
  2>/dev/null || true)"

entries_total="$(echo "$entries_result" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('data',{}).get('result',[]); print(r[0]['value'][1] if r else '0')" \
  2>/dev/null || echo "0")"

assert_not "LOG-02: loki_write_sent_entries_total" "$entries_total" "0"

# ---------------------------------------------------------------------------
# LOG-03: Loki datasource healthy in Grafana + LogQL acceptance query
# (skipped under --quick)
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-03: Loki datasource + LogQL ---"

if [[ "$quick" == "true" ]]; then
  echo "skip: LOG-03: Grafana port-forward checks skipped (--quick)"
else
  grafana_password="${GRAFANA_ADMIN_PASSWORD:-}"
  if [[ -z "$grafana_password" ]]; then
    echo "FAIL: LOG-03: GRAFANA_ADMIN_PASSWORD env var not set" >&2
    exit 1
  fi

  # Start port-forward in background
  kubectl -n "${namespace}" port-forward svc/grafana 13000:80 >/dev/null 2>&1 &
  pf_pid=$!
  trap 'kill "$pf_pid" 2>/dev/null || true' EXIT

  sleep 3

  # Find the Loki datasource ID
  datasources_json="$(curl -s -u "admin:${grafana_password}" \
    "http://localhost:13000/api/datasources" 2>/dev/null || echo '[]')"

  loki_ds_id="$(echo "$datasources_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
matches = [d for d in data if d.get('type') == 'loki']
print(matches[0]['id'] if matches else '')
" 2>/dev/null || echo "")"

  if [[ -z "$loki_ds_id" ]]; then
    echo "FAIL: LOG-03: no Loki datasource found in Grafana /api/datasources" >&2
    exit 1
  fi
  echo "ok: LOG-03: found Loki datasource id=${loki_ds_id}"

  ds_health="$(curl -s -u "admin:${grafana_password}" \
    "http://localhost:13000/api/datasources/${loki_ds_id}/health" 2>/dev/null || echo '{}')"

  ds_status="$(echo "$ds_health" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('status', 'unknown'))
" 2>/dev/null || echo "parse_error")"

  assert "LOG-03: Loki datasource health" "$ds_status" "OK"

  # LOG-03: LogQL acceptance query — exec from prometheus pod to hit Loki directly
  echo ""
  echo "--- LOG-03: LogQL query for server-2 logs ---"

  now_ns="$(date +%s)000000000"
  start_ns="$(( $(date +%s) - 3600 ))000000000"   # last 1 hour

  logql_result="$(kubectl -n "${namespace}" exec deploy/prometheus-server -- \
    wget -qO- \
    "http://loki.monitoring.svc:3100/loki/api/v1/query_range?query=%7Bnamespace%3D%22solid-stats-staging%22%2Capp%3D~%22server-2.*%22%7D&limit=5&start=${start_ns}&end=${now_ns}" \
    2>/dev/null || echo '{}')"

  logql_count="$(echo "$logql_result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
streams = data.get('data', {}).get('result', [])
total = sum(len(s.get('values', [])) for s in streams)
print(total)
" 2>/dev/null || echo "0")"

  if [[ "$logql_count" -lt 1 ]]; then
    echo "FAIL: LOG-03: LogQL {namespace=\"solid-stats-staging\",app=~\"server-2.*\"} returned 0 entries" >&2
    echo "      (Loki may still be ingesting; retry after Alloy has been running >1 min)" >&2
    exit 1
  fi
  echo "ok: LOG-03: LogQL returned ${logql_count} log entries for server-2"

  kill "$pf_pid" 2>/dev/null || true
  trap - EXIT
fi

# ---------------------------------------------------------------------------
# Manual note: LOG-03 visual check in Grafana Explore (operator action required)
# ---------------------------------------------------------------------------
echo ""
echo "--- LOG-03: Manual LogQL visual check (operator action required) ---"
echo "note: To confirm logs render in Grafana Explore:"
echo "      kubectl -n monitoring port-forward svc/grafana 3000:80"
echo "      Then open http://localhost:3000 (admin / GRAFANA_ADMIN_PASSWORD)."
echo "      Navigate to Explore -> Loki datasource -> run:"
echo "        {namespace=\"solid-stats-staging\", app=~\"server-2.*\"}"
echo "      Confirm that recent log lines from server-2 appear (non-empty result)."

# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 15 validation PASSED ==="
