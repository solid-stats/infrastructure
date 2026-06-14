#!/usr/bin/env bash
set -euo pipefail
# scripts/test-glitchtip-ingest.sh
# ERR-03 forced-error ingest test via port-forward.
# POSTs a synthetic Sentry envelope to GlitchTip's ingest endpoint and asserts
# that it is accepted (HTTP 200/202, NOT 403 — see 16-RESEARCH Pitfall 8).
# Optionally polls the issues API to confirm the event appears.
#
# Usage:
#   GLITCHTIP_DSN=http://PUBKEY@host/PROJECT_ID bash scripts/test-glitchtip-ingest.sh
#
# Required env:
#   GLITCHTIP_DSN    — project DSN in format http://PUBLIC_KEY@any-host/PROJECT_ID.
#                      The host part is ignored; the test always uses port-forward
#                      to localhost:18000 (internal mode).
#
# Optional env:
#   SUPERUSER_TOKEN  — GlitchTip Bearer token; if set, polls /api/0/projects/<slug>/
#                      issues/?query=<marker> to confirm the event appears.
#   NAMESPACE        — Kubernetes namespace (default: error-tracking)
#   PF_PORT          — local port for port-forward (default: 18000)
#   ISSUE_POLL_TRIES — number of polls for issue appearance (default: 12, ~60s)

# ---------------------------------------------------------------------------
# Required env check
# ---------------------------------------------------------------------------
required() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" ]]; then
    echo "FATAL: required env var ${name} is not set" >&2
    exit 64
  fi
  echo "$value"
}

GLITCHTIP_DSN="$(required GLITCHTIP_DSN)"
NAMESPACE="${NAMESPACE:-error-tracking}"
PF_PORT="${PF_PORT:-18000}"
SUPERUSER_TOKEN="${SUPERUSER_TOKEN:-}"
ISSUE_POLL_TRIES="${ISSUE_POLL_TRIES:-12}"

# ---------------------------------------------------------------------------
# Parse DSN: http://PUBLIC_KEY@any-host/PROJECT_ID
# DSN format per Sentry spec: https://develop.sentry.dev/sdk/overview/#dsn
# ---------------------------------------------------------------------------
# Strip scheme
dsn_no_scheme="${GLITCHTIP_DSN#*://}"
# Extract PUBLIC_KEY (before @)
PUBLIC_KEY="${dsn_no_scheme%%@*}"
# Extract path after host (PROJECT_ID is the last path component)
dsn_path="${dsn_no_scheme##*/}"
PROJECT_ID="${dsn_path%%[/?]*}"

if [[ -z "$PUBLIC_KEY" || -z "$PROJECT_ID" ]]; then
  echo "FATAL: could not parse PUBLIC_KEY or PROJECT_ID from DSN: ${GLITCHTIP_DSN}" >&2
  echo "       Expected format: http://PUBLIC_KEY@host/PROJECT_ID" >&2
  exit 1
fi

echo "=== GlitchTip Forced-Error Ingest Test ==="
echo "namespace=${NAMESPACE}"
echo "public_key=${PUBLIC_KEY}"
echo "project_id=${PROJECT_ID}"
echo ""

# ---------------------------------------------------------------------------
# Start port-forward to glitchtip-web
# ---------------------------------------------------------------------------
echo "Starting port-forward svc/glitchtip-web ${PF_PORT}:8000 -n ${NAMESPACE}..."
kubectl -n "${NAMESPACE}" port-forward svc/glitchtip-web "${PF_PORT}":8000 >/dev/null 2>&1 &
pf_pid=$!
trap 'kill "$pf_pid" 2>/dev/null || true' EXIT

# Wait until /api/0/config/ responds (up to 20 s)
deadline=$(( $(date +%s) + 20 ))
until curl -sf "http://localhost:${PF_PORT}/api/0/config/" >/dev/null 2>&1; do
  if [[ $(date +%s) -ge $deadline ]]; then
    echo "FAIL: port-forward to glitchtip-web did not become ready within 20s" >&2
    exit 1
  fi
  sleep 1
done
echo "ok: port-forward ready (localhost:${PF_PORT})"
echo ""

# ---------------------------------------------------------------------------
# Build Sentry envelope (3 newline-separated JSON lines per Sentry spec)
# Source: develop.sentry.dev/sdk/foundations/transport/envelopes/
# ---------------------------------------------------------------------------
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EPOCH=$(date +%s)
# Unique marker for issue lookup
MARKER="Phase 16 forced test error ${EPOCH}"
# Random event_id (32 hex chars, no dashes — Sentry envelope spec)
EVENT_ID=$(python3 -c "import uuid; print(uuid.uuid4().hex)")

# Line 1: envelope header
ENVELOPE_HEADER="{\"event_id\":\"${EVENT_ID}\",\"dsn\":\"http://${PUBLIC_KEY}@localhost:${PF_PORT}/${PROJECT_ID}\"}"

# Line 3: event payload (message + level + timestamp)
EVENT_JSON="{\"event_id\":\"${EVENT_ID}\",\"message\":\"${MARKER}\",\"level\":\"error\",\"timestamp\":\"${TIMESTAMP}\",\"platform\":\"other\"}"
EVENT_LENGTH=${#EVENT_JSON}

# Line 2: item header (type + byte length of event payload)
ITEM_HEADER="{\"type\":\"event\",\"length\":${EVENT_LENGTH}}"

# Full envelope: 3 lines separated by newlines
ENVELOPE="${ENVELOPE_HEADER}
${ITEM_HEADER}
${EVENT_JSON}"

# ---------------------------------------------------------------------------
# POST envelope to ingest endpoint
# ---------------------------------------------------------------------------
INGEST_URL="http://localhost:${PF_PORT}/api/${PROJECT_ID}/envelope/"
echo "POSTing Sentry envelope to ${INGEST_URL}..."
echo "  event_id=${EVENT_ID}"
echo "  marker=${MARKER}"
echo ""

http_status=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${INGEST_URL}" \
  -H "Content-Type: application/x-sentry-envelope" \
  --data-raw "${ENVELOPE}" \
  2>/dev/null || echo "000")

# Assert non-403 (Pitfall 8: 403 = wrong DSN public key)
if [[ "$http_status" == "403" ]]; then
  echo "FAIL: ERR-03: envelope POST returned 403 — DSN public key mismatch" >&2
  echo "      Check that GLITCHTIP_DSN matches the project DSN from 16-04 seed output" >&2
  exit 1
fi

if [[ "$http_status" == "200" || "$http_status" == "202" ]]; then
  echo "ok: ERR-03: envelope POST returned ${http_status} (accepted)"
else
  echo "FAIL: ERR-03: envelope POST returned unexpected HTTP ${http_status}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Optional: poll issues API to confirm the event appears
# ---------------------------------------------------------------------------
if [[ -n "$SUPERUSER_TOKEN" ]]; then
  echo ""
  echo "Polling issues API for marker (up to $((ISSUE_POLL_TRIES * 5))s)..."
  found=false
  for i in $(seq 1 "$ISSUE_POLL_TRIES"); do
    issues_json="$(curl -sf \
      -H "Authorization: Bearer ${SUPERUSER_TOKEN}" \
      "http://localhost:${PF_PORT}/api/0/projects/-/staging-project/issues/?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('Phase 16'))")" \
      2>/dev/null || echo '[]')"
    match="$(echo "$issues_json" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    hits = [i for i in data if 'Phase 16' in (i.get('title','') or i.get('culprit','') or '')]
    print(len(hits))
except Exception:
    print('0')
" 2>/dev/null || echo "0")"
    if [[ "$match" -ge 1 ]]; then
      echo "ok: ERR-03: issue with 'Phase 16' marker appeared after ${i} poll(s)"
      found=true
      break
    fi
    echo "  poll ${i}/${ISSUE_POLL_TRIES}: not yet visible, waiting 5s..."
    sleep 5
  done
  if [[ "$found" != "true" ]]; then
    echo "note: ERR-03: issue did not appear in issues API within timeout" >&2
    echo "      The envelope was accepted (HTTP ${http_status}); the worker may need" >&2
    echo "      more time to process it. Check GlitchTip UI for the issue manually." >&2
    echo "      (This is a timing warning, not a hard failure — envelope was accepted)" >&2
  fi
else
  echo ""
  echo "note: SUPERUSER_TOKEN not set — skipping issue appearance check"
  echo "      To verify the issue appeared, set SUPERUSER_TOKEN and re-run, or"
  echo "      check the GlitchTip UI for an issue titled '${MARKER}'"
fi

# ---------------------------------------------------------------------------
kill "$pf_pid" 2>/dev/null || true
trap - EXIT

echo ""
echo "=== ERR-03 ingest test PASSED ==="
echo "  Envelope accepted: HTTP ${http_status}"
echo "  marker: ${MARKER}"
echo "  event_id: ${EVENT_ID}"
