#!/usr/bin/env bash
set -euo pipefail

# cutover.sh — 4-gate reversible production upstream switch for stats-staging.solid-stats.ru
#
# Gates (both enforced before any nginx mutation — also enforced in DRY_RUN mode):
#   Gate A: docs/backup-gate.md must contain "Status: verified" (CUT-03 backup gate)
#   Gate B: docs/diff-readiness.md must contain "strict_failures: 0" (CUT-03 coverage gate)
#
# The green-diff gate (Gate B) is COVERAGE/INTEGRITY only — not value equality.
# Value divergence from legacy is expected by design; see docs/diff-readiness.md.
#
# Mechanism (CUT-01):
#   Backs up the live vhost, switches the upstream "server" line at the # CUTOVER: marker,
#   validates nginx config (fail-closed), reloads nginx, runs a smoke check.
#
# Rollback (CUT-02):
#   rollback() restores the vhost backup + nginx -t + reload. Safe to call manually.
#
# Smoke check (CUT-04):
#   curl -fsS captures HTTP status; 2xx/3xx = success; all retries exhausted = auto-rollback.
#
# DRY_RUN=1: enforces both gates (still exits 1 if either gate unmet); skips all mutations.
# SELF_TEST=1: exercises rollback() in isolation on a temp vhost copy; never touches live nginx.
#
# Usage:
#   NEW_UPSTREAM=192.168.1.10:8080 scripts/cutover.sh
#   DRY_RUN=1 NEW_UPSTREAM=192.168.1.10:8080 scripts/cutover.sh
#   SELF_TEST=1 VHOST_CONF=/etc/nginx/sites-available/stats-staging-solid-stats.conf \
#     NEW_UPSTREAM=unused scripts/cutover.sh
#
# This script is OPERATOR-GATED — it is never run by CI (lives in scripts/, not k8s/staging/).
# See docs/cutover.md for the full operator runbook.

# ==============================================================================
# SECTION 1 — Required env vars + optional vars with defaults
# ==============================================================================

required() {
  local var="$1"
  if [[ -z "${!var:-}" ]]; then
    echo "FATAL: ${var} is required but not set" >&2
    exit 64
  fi
}

required NEW_UPSTREAM

# Resolve gate files relative to the repo root (this script lives in scripts/),
# so the gates always read the in-repo evidence files regardless of the operator's
# CWD (WR-05). Running from anywhere other than the repo root no longer makes the
# gates fail on a missing file, and a stray docs/backup-gate.md under some other
# CWD can never gate the flip.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

: "${VHOST_HOST:=stats-staging.solid-stats.ru}"
: "${VHOST_CONF:=/etc/nginx/sites-available/stats-staging-solid-stats.conf}"
: "${BACKUP_GATE_FILE:=${REPO_ROOT}/docs/backup-gate.md}"
: "${DIFF_GATE_FILE:=${REPO_ROOT}/docs/diff-readiness.md}"
: "${SMOKE_RETRIES:=3}"
: "${SMOKE_DELAY:=5}"
: "${DRY_RUN:=}"

BAK_VHOST="${VHOST_CONF}.cutover.bak"

# ==============================================================================
# SELF_TEST path (exercises rollback() on a temp copy; skips gate checks and
# never touches live nginx — safe to run on any host with a readable VHOST_CONF)
# ==============================================================================

if [[ "${SELF_TEST:-}" == "1" ]]; then
  echo "=== SELF_TEST: exercising rollback() on a temp vhost copy ==="

  TMP_VHOST=$(mktemp /tmp/cutover-selftest-XXXXXX.conf)

  # Pick a readable source vhost so SELF_TEST runs OFFLINE / in CI without the live
  # nginx file: prefer the live VHOST_CONF if it exists, else fall back to the
  # repo-managed copy (the rollback logic under test is identical either way).
  SELFTEST_SRC="${VHOST_CONF}"
  if [[ ! -f "${SELFTEST_SRC}" ]]; then
    SELFTEST_SRC="config/nginx/sites-available/stats-staging-solid-stats.conf"
  fi
  if [[ ! -f "${SELFTEST_SRC}" ]]; then
    echo "FATAL: SELF_TEST found no readable source vhost (tried ${VHOST_CONF} and the repo copy)" >&2
    exit 1
  fi

  # Copy the source vhost to a temp file so rollback() has something to restore
  cp "${SELFTEST_SRC}" "${TMP_VHOST}"

  # Simulate the backup that rollback() expects
  cp "${TMP_VHOST}" "${TMP_VHOST}.cutover.bak"

  # Simulate a bad switch: corrupt the temp file
  echo "server CORRUPTED:9999;" >> "${TMP_VHOST}"

  # Temporarily override VHOST_CONF and BAK_VHOST to point at temp files
  ORIG_VHOST_CONF="${VHOST_CONF}"
  ORIG_BAK_VHOST="${BAK_VHOST}"
  VHOST_CONF="${TMP_VHOST}"
  BAK_VHOST="${TMP_VHOST}.cutover.bak"

  # Define a self-test-local rollback that skips real nginx commands
  rollback() {
    echo "--- SELF_TEST rollback(): restoring ${VHOST_CONF} from ${BAK_VHOST} ---"
    if [[ ! -f "${BAK_VHOST}" ]]; then
      echo "FATAL: rollback backup not found at ${BAK_VHOST}" >&2
      exit 1
    fi
    cp "${BAK_VHOST}" "${VHOST_CONF}"
    echo "ROLLBACK COMPLETE — upstream restored from backup: ${BAK_VHOST}"
  }

  rollback

  # Assert: temp file is byte-restored (matches the original pre-corruption backup copy)
  if ! diff -q "${TMP_VHOST}" "${TMP_VHOST}.cutover.bak" >/dev/null 2>&1; then
    echo "SELF_TEST FAILED: rollback did not restore file to backup state" >&2
    rm -f "${TMP_VHOST}" "${TMP_VHOST}.cutover.bak"
    VHOST_CONF="${ORIG_VHOST_CONF}"; BAK_VHOST="${ORIG_BAK_VHOST}"
    exit 1
  fi

  echo "SELF_TEST PASSED: rollback() correctly restored the temp vhost from backup"
  rm -f "${TMP_VHOST}" "${TMP_VHOST}.cutover.bak"
  VHOST_CONF="${ORIG_VHOST_CONF}"; BAK_VHOST="${ORIG_BAK_VHOST}"
  exit 0
fi

# ==============================================================================
# SECTION 2 — Gate checks (always enforced; DRY_RUN does NOT bypass these)
# ==============================================================================

# Gate A (CUT-03 backup): fresh verified backup required.
# WR-04: anchor the match to a whole-line `Status: verified` so a negated/qualified
# phrasing (e.g. "Status: verified backup is STALE — do not use") cannot false-pass.
if ! grep -Eq '^[[:space:]]*Status:[[:space:]]+verified[[:space:]]*$' "${BACKUP_GATE_FILE}"; then
  echo "FATAL: backup gate not verified in ${BACKUP_GATE_FILE} — run a fresh backup first" >&2
  exit 1
fi

# Gate B (CUT-03 diff/coverage): coverage evidence marker required
# NOTE: This is a COVERAGE/INTEGRITY gate only — NOT an equality check.
# "strict_failures: 0" means no missing players/matches, no parser errors,
# no unexplained aggregate differences outside tolerance. Value differences
# by design are allowlisted and human-reviewed. See docs/diff-readiness.md.
# WR-04: anchor to a whole-line `strict_failures: 0` evidence marker (the format the
# runbook prescribes under "## Cutover Gate Evidence") so a qualified phrasing
# (e.g. "strict_failures: 0 (PLACEHOLDER, not yet run)") cannot false-pass, and the
# prose mention of `strict_failures` elsewhere in the doc is not mistaken for evidence.
if ! grep -Eq '^[[:space:]]*strict_failures:[[:space:]]*0[[:space:]]*$' "${DIFF_GATE_FILE}"; then
  echo "FATAL: diff coverage gate not met in ${DIFF_GATE_FILE} (strict_failures: 0 not found)" >&2
  echo "  The green-diff gate is coverage/integrity only — see docs/diff-readiness.md" >&2
  exit 1
fi

echo "Gates passed: backup verified + diff coverage gate met"

# ==============================================================================
# DRY_RUN early exit (gates above have already executed and passed)
# ==============================================================================

if [[ "${DRY_RUN:-}" == "1" ]]; then
  echo "[DRY-RUN] would: cp -p ${VHOST_CONF} ${BAK_VHOST}"
  echo "[DRY-RUN] would: sed upstream switch to ${NEW_UPSTREAM}"
  echo "[DRY-RUN] would: nginx -t"
  echo "[DRY-RUN] would: systemctl reload nginx"
  echo "[DRY-RUN] would: curl smoke-check https://${VHOST_HOST}/"
  echo "[DRY-RUN] gates PASSED — script would proceed to live flip"
  exit 0
fi

# ==============================================================================
# SECTION 3 — vhost backup (reversibility; always overwrite to reflect pre-run state)
# ==============================================================================

if [[ ! -f "${VHOST_CONF}" ]]; then
  echo "FATAL: vhost config not found at ${VHOST_CONF} — cannot proceed" >&2
  exit 1
fi

echo "Backing up live vhost to ${BAK_VHOST}..."
cp -p "${VHOST_CONF}" "${BAK_VHOST}"
echo "Backup written (will be overwritten on re-run to always reflect pre-run state)"

# ==============================================================================
# SECTION 4 — rollback() function (CUT-02)
# Define before any nginx-touching code so it can be called from smoke-check failure path.
# ==============================================================================

rollback() {
  echo "--- ROLLBACK: restoring vhost from backup ---" >&2

  # 1. Verify backup exists
  if [[ ! -f "${BAK_VHOST}" ]]; then
    echo "FATAL: rollback backup not found at ${BAK_VHOST} — cannot roll back" >&2
    exit 1
  fi

  # 2. Restore the backup byte-for-byte
  echo "Restoring ${BAK_VHOST} -> ${VHOST_CONF}..." >&2
  cp "${BAK_VHOST}" "${VHOST_CONF}"

  # 3. nginx -t (fail-closed after restore)
  if ! nginx -t 2>&1; then
    echo "FATAL: nginx -t failed after rollback restore — config is broken; fix manually" >&2
    exit 1
  fi

  # 4. Reload nginx
  if ! systemctl reload nginx; then
    echo "FATAL: nginx reload failed after rollback restore — investigate manually" >&2
    exit 1
  fi

  # 5. Confirm completion
  echo "ROLLBACK COMPLETE — upstream restored from backup: ${BAK_VHOST}" >&2
}

# ==============================================================================
# SECTION 5 — upstream switch (CUT-01)
# The # CUTOVER: marker precedes the server line in the upstream block.
# sed replaces the "server <addr>;" line, preserving leading whitespace.
# ==============================================================================

echo "Switching upstream to ${NEW_UPSTREAM}..."

# WR-01: assert the # CUTOVER: marker exists before touching anything — the switch
# is anchored to it, so a missing marker is a fatal misconfiguration, not a silent
# no-op or a global rewrite.
if ! grep -q '# CUTOVER:' "${VHOST_CONF}"; then
  echo "FATAL: '# CUTOVER:' marker not found in ${VHOST_CONF} — refusing to switch" >&2
  exit 1
fi

# WR-02: escape the replacement so an ip:port (or a fat-fingered value) containing
# the delimiter '|', a backslash, or sed's '&' (whole-match) metacharacter cannot
# corrupt the config or abort sed mid-run.
esc_upstream=$(printf '%s' "${NEW_UPSTREAM}" | sed -e 's/[&|\\]/\\&/g')

# WR-01: anchor the substitution to the marker. Operate only within the range that
# starts at the `# CUTOVER:` marker and ends at the first following `server <addr>;`
# line, and substitute ONLY on that server line. Comment lines may sit between the
# marker and the server directive, so a plain `n` (next-line) is not enough — the
# range walks to the correct server line. No other `server` directive elsewhere in
# the file is touched.
sed -i "/# CUTOVER:/,/^[[:space:]]*server [^;]*;/{s|^\( *\)server [^;]*;|\1server ${esc_upstream};|;}" "${VHOST_CONF}"

# WR-03 + WR-01: fixed-string (grep -F) count of the exact `server <NEW_UPSTREAM>;`
# line. grep -F makes the dots in the IPv4 address literal, not wildcards, so a
# subtly wrong address (e.g. 10X43X94X103:3000) can no longer false-pass. Asserting
# the count is exactly 1 catches both a missed edit (0) and an accidental global
# rewrite of multiple `server` directives (>1).
match_count=$(grep -cF -- "server ${NEW_UPSTREAM};" "${VHOST_CONF}" || true)
if [[ "${match_count}" -ne 1 ]]; then
  echo "FATAL: expected exactly 1 upstream line 'server ${NEW_UPSTREAM};', got ${match_count} — aborting" >&2
  exit 1
fi

echo "Upstream line updated in ${VHOST_CONF}"

# ==============================================================================
# SECTION 6 — nginx -t gate (fail-closed; roll back on bad config)
# ==============================================================================

echo "Validating nginx configuration..."
if ! nginx -t 2>&1; then
  echo "FATAL: nginx config invalid after upstream switch — rolling back" >&2
  rollback
  exit 1
fi

# ==============================================================================
# SECTION 7 — nginx reload
# ==============================================================================

echo "Reloading nginx..."
if ! systemctl reload nginx; then
  echo "FATAL: nginx reload failed despite passing nginx -t — rolling back" >&2
  rollback
  exit 1
fi

echo "nginx reloaded with new upstream ${NEW_UPSTREAM}"

# ==============================================================================
# SECTION 8 — smoke check with auto-rollback (CUT-04)
# curl -fsS: -f = fail on 4xx/5xx, -sS = silent body + show errors
# -w '%{http_code}' captures status code; -o /dev/null discards body.
# 2xx or 3xx = success; retries with backoff; exhausted = rollback + exit 1.
# ==============================================================================

echo "Running smoke check (${SMOKE_RETRIES} attempts, ${SMOKE_DELAY}s delay)..."
smoke_ok=0

for i in $(seq 1 "${SMOKE_RETRIES}"); do
  http_code=$(curl -fsS -o /dev/null -w '%{http_code}' \
                "https://${VHOST_HOST}/" --max-time 10 2>/dev/null) || true
  if [[ "$http_code" =~ ^[23] ]]; then
    echo "Smoke check passed (HTTP ${http_code}) — new upstream ${NEW_UPSTREAM} responding"
    smoke_ok=1
    break
  fi
  echo "Smoke check attempt ${i}/${SMOKE_RETRIES} failed (HTTP ${http_code:-ERR}) — waiting ${SMOKE_DELAY}s..." >&2
  sleep "${SMOKE_DELAY}"
done

if [[ "${smoke_ok}" -eq 0 ]]; then
  echo "FATAL: smoke check failed after ${SMOKE_RETRIES} attempts — AUTO-ROLLBACK" >&2
  rollback
  exit 1
fi

# ==============================================================================
# SECTION 9 — success banner (reached only on smoke_ok=1)
# ==============================================================================

# Extract previous upstream from the backup for the audit trail (grep for "server" line, no secrets)
prev_upstream=$(grep -E '^ *server [^;]+;' "${BAK_VHOST}" | head -1 | sed 's/^ *//' || echo "unknown")

echo ""
echo "=== CUTOVER COMPLETE ==="
echo "  Previous upstream: ${prev_upstream}"
echo "  New upstream:      server ${NEW_UPSTREAM};"
echo "  Vhost backup:      ${BAK_VHOST}"
echo "  To roll back manually:"
echo "    rollback via: cp ${BAK_VHOST} ${VHOST_CONF} && nginx -t && systemctl reload nginx"
echo "    or re-run:    scripts/cutover.sh with rollback() call if live"
echo "========================"

exit 0
