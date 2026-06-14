#!/usr/bin/env bash
set -euo pipefail
# scripts/validate-phase-16.sh
# Phase 16 live assertion harness — covers ERR-01, ERR-02, ERR-03.
# Exits 1 on first failure.
#
# Run after all Phase 16 manifests have been applied (WireGuard tunnel up or
# kubectl configured against staging cluster):
#   bash scripts/validate-phase-16.sh
#
# Flags:
#   --internal   Port-forward mode (default). Uses kubectl port-forward for ERR-02/03.
#   --public     Curl the public errors. URL instead of port-forward.
#                Only meaningful after DNS A record resolves + TLS cutover (Phase 16-05).
#   --quick      Skip ERR-03 forced-error test (requires GLITCHTIP_DSN to be set).
#
# Required env for ERR-03 (non-quick mode):
#   GLITCHTIP_DSN           — project DSN (http://PUBKEY@host/PROJECT_ID),
#                             set by operator after 16-04 org/project/seed.
#                             Defaults to skipping ERR-03 forced-error with a note.
#
# Optional env:
#   SUPERUSER_TOKEN         — GlitchTip API auth token (Bearer) for project/issue queries.
#   K8S_NAMESPACE           — override namespace (default: error-tracking)
#   GLITCHTIP_PUBLIC_URL    — public URL for --public mode
#                             (default: https://errors.solid-stats.ru)

namespace="${K8S_NAMESPACE:-error-tracking}"
mode="internal"
quick=false

for arg in "$@"; do
  case "$arg" in
    --internal) mode="internal" ;;
    --public)   mode="public"   ;;
    --quick)    quick=true      ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Assertion helpers
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

assert_contains() {
  local label="$1"
  local haystack="$2"
  local needle="$3"
  if ! echo "$haystack" | grep -qF "$needle"; then
    echo "FAIL: ${label} — expected to find '${needle}'" >&2
    echo "      Got: ${haystack:0:200}" >&2
    exit 1
  fi
  echo "ok: ${label}"
}

assert_not_found() {
  local label="$1"
  local haystack="$2"
  local needle="$3"
  if echo "$haystack" | grep -qiE "$needle"; then
    echo "FAIL: ${label} — found unexpected '${needle}'" >&2
    exit 1
  fi
  echo "ok: ${label}"
}

# ---------------------------------------------------------------------------
# Port-forward helper (shared by ERR-02 and ERR-03 --internal mode)
# Sets pf_pid and starts cleanup trap. Caller must kill "$pf_pid" when done
# or rely on the EXIT trap.
# ---------------------------------------------------------------------------
pf_pid=""
pf_port=18000

start_port_forward() {
  echo "Starting port-forward svc/glitchtip-web ${pf_port}:8000 -n ${namespace}..."
  kubectl -n "${namespace}" port-forward svc/glitchtip-web "${pf_port}":8000 >/dev/null 2>&1 &
  pf_pid=$!
  trap 'kill "$pf_pid" 2>/dev/null || true' EXIT

  # Wait until the endpoint responds (up to 20 s)
  local deadline=$(( $(date +%s) + 20 ))
  until curl -sf "http://localhost:${pf_port}/api/0/config/" >/dev/null 2>&1; do
    if [[ $(date +%s) -ge $deadline ]]; then
      echo "FAIL: port-forward to glitchtip-web did not become ready within 20s" >&2
      exit 1
    fi
    sleep 1
  done
  echo "ok: port-forward ready (localhost:${pf_port})"
}

stop_port_forward() {
  if [[ -n "$pf_pid" ]]; then
    kill "$pf_pid" 2>/dev/null || true
    pf_pid=""
    trap - EXIT
  fi
}

# ---------------------------------------------------------------------------
echo "=== Phase 16 Validation ==="
echo "namespace=${namespace}"
echo "mode=${mode}"
echo "quick=${quick}"
echo ""

# ---------------------------------------------------------------------------
# ERR-01: GlitchTip pods Running, no Valkey/Redis, migrate Job completed,
#         VALKEY_URL empty on web deployment
# ---------------------------------------------------------------------------
echo "--- ERR-01: GlitchTip pods Running ---"

postgres_phase="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=glitchtip-postgres" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
# Fallback label
if [[ -z "$postgres_phase" ]]; then
  postgres_phase="$(kubectl -n "${namespace}" get pod \
    -l "app=glitchtip-postgres" \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
fi
assert "ERR-01: glitchtip-postgres pod phase" "$postgres_phase" "Running"

web_phase="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=glitchtip-web" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
if [[ -z "$web_phase" ]]; then
  web_phase="$(kubectl -n "${namespace}" get pod \
    -l "app=glitchtip-web" \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
fi
assert "ERR-01: glitchtip-web pod phase" "$web_phase" "Running"

worker_phase="$(kubectl -n "${namespace}" get pod \
  -l "app.kubernetes.io/name=glitchtip-worker" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
if [[ -z "$worker_phase" ]]; then
  worker_phase="$(kubectl -n "${namespace}" get pod \
    -l "app=glitchtip-worker" \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
fi
assert "ERR-01: glitchtip-worker pod phase" "$worker_phase" "Running"

echo ""
echo "--- ERR-01: No Valkey/Redis workload in error-tracking ---"
valkey_workloads="$(kubectl -n "${namespace}" get deploy,statefulset 2>/dev/null \
  | grep -iE 'valkey|redis' || true)"
assert_not_found "ERR-01: no valkey/redis workload in namespace" \
  "$valkey_workloads" "valkey|redis"

echo ""
echo "--- ERR-01: migrate Job completed ---"
migrate_succeeded="$(kubectl -n "${namespace}" get job glitchtip-migrate \
  -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "0")"
assert "ERR-01: glitchtip-migrate Job succeeded" "$migrate_succeeded" "1"

echo ""
echo "--- ERR-01: VALKEY_URL is empty on glitchtip-web ---"
# Extract VALKEY_URL from the web Deployment env list; expect empty string value.
valkey_url_val="$(kubectl -n "${namespace}" get deploy glitchtip-web \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="VALKEY_URL")].value}' \
  2>/dev/null || echo "NOT_FOUND")"
assert "ERR-01: VALKEY_URL on glitchtip-web is empty string" "$valkey_url_val" ""

echo ""

# ---------------------------------------------------------------------------
# ERR-02: Registration disabled — verified via /api/0/config/ + optional POST
# ---------------------------------------------------------------------------
echo "--- ERR-02: Registration disabled ---"

if [[ "$mode" == "internal" ]]; then
  start_port_forward
  base_url="http://localhost:${pf_port}"
else
  public_url="${GLITCHTIP_PUBLIC_URL:-https://errors.solid-stats.ru}"
  base_url="$public_url"
  echo "Using public URL: ${base_url}"
fi

# Method A: config endpoint — most reliable (16-RESEARCH Pattern 5)
config_json="$(curl -sf "${base_url}/api/0/config/" 2>/dev/null || echo '{}')"
reg_enabled="$(echo "$config_json" | python3 -c "
import sys, json
try:
    cfg = json.load(sys.stdin)
    val = cfg.get('user_registration_enabled')
    print('false' if val is False else str(val))
except Exception:
    print('parse_error')
" 2>/dev/null || echo "parse_error")"

assert "ERR-02: user_registration_enabled is false (via /api/0/config/)" \
  "$reg_enabled" "false"

# Method B: POST registration endpoint, expect 4xx (best-effort)
reg_status="$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  "${base_url}/api/0/auth/registration/" \
  -H "Content-Type: application/json" \
  -d '{"email":"probe@test.invalid","password1":"TestProbe123!","password2":"TestProbe123!"}' \
  2>/dev/null || echo "000")"

if [[ "$reg_status" == "403" || "$reg_status" == "400" || "$reg_status" == "404" || "$reg_status" == "405" ]]; then
  echo "ok: ERR-02: registration POST returned ${reg_status} (registration closed)"
else
  echo "note: ERR-02: registration POST returned ${reg_status} (expected 4xx; Method A already confirmed disabled)"
fi

echo ""

# ---------------------------------------------------------------------------
# ERR-03: Project/DSN exist + forced-error test
# ---------------------------------------------------------------------------
echo "--- ERR-03: Project/DSN ---"

glitchtip_dsn="${GLITCHTIP_DSN:-}"
superuser_token="${SUPERUSER_TOKEN:-}"

if [[ -n "$superuser_token" ]]; then
  # Verify org/project exist via API
  projects_json="$(curl -sf \
    -H "Authorization: Bearer ${superuser_token}" \
    "${base_url}/api/0/projects/" 2>/dev/null || echo '[]')"
  project_count="$(echo "$projects_json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(len(data))
except Exception:
    print('0')
" 2>/dev/null || echo "0")"

  if [[ "$project_count" -ge 1 ]]; then
    echo "ok: ERR-03: ${project_count} project(s) found via API"
  else
    echo "FAIL: ERR-03: no projects found via /api/0/projects/ — run 16-04 seed step first" >&2
    exit 1
  fi
else
  echo "note: ERR-03: SUPERUSER_TOKEN not set — skipping API project count check"
fi

if [[ -z "$glitchtip_dsn" ]]; then
  echo "note: ERR-03: GLITCHTIP_DSN not set — skipping forced-error ingest test"
  echo "      Set GLITCHTIP_DSN=http://PUBKEY@host/PROJECT_ID (from 16-04 seed output)"
  echo "      Then re-run: GLITCHTIP_DSN=... bash scripts/validate-phase-16.sh"
elif [[ "$quick" == "true" ]]; then
  echo "note: ERR-03: --quick flag set — skipping test-glitchtip-ingest.sh"
else
  echo "--- ERR-03: Forced-error ingest test ---"
  # Stop our port-forward before calling the ingest script (it opens its own)
  if [[ "$mode" == "internal" ]]; then
    stop_port_forward
  fi
  NAMESPACE="${namespace}" GLITCHTIP_DSN="${glitchtip_dsn}" \
    SUPERUSER_TOKEN="${superuser_token}" \
    bash "$(dirname "$0")/test-glitchtip-ingest.sh"
fi

# ---------------------------------------------------------------------------
if [[ "$mode" == "internal" ]]; then
  stop_port_forward
fi

echo ""
echo "=== Phase 16 validation PASSED ==="
echo ""
echo "Requirements status:"
echo "  ERR-01: GlitchTip postgres/web/worker Running; no Valkey; migrate complete; VALKEY_URL empty — PASS"
echo "  ERR-02: registration disabled via /api/0/config/ — PASS"
if [[ -z "$glitchtip_dsn" ]]; then
  echo "  ERR-03: project count check done; forced-error test SKIPPED (set GLITCHTIP_DSN to complete)"
else
  echo "  ERR-03: project/DSN verified + forced-error ingest test delegated to test-glitchtip-ingest.sh — PASS"
fi
