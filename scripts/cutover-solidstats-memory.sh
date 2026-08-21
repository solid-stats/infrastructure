#!/usr/bin/env bash
set -Eeuo pipefail

# Reversible Phase 21 operator orchestrator. This file never runs from CI.
# The remote operator is invoked in coarse SSH batches and must implement:
#   capture-prestate       record nginx bytes/symlink and workload state
#   stop-legacy-start-new  stop legacy, start new, wait for private readiness
#   install-nginx          read template on stdin; backup, install, nginx -t,
#                          and reload in one batch
#   rollback-nginx         restore exact bytes/symlink, nginx -t, reload
#   stop-new               restore the recorded new-workload pre-state
#   start-legacy           restore the exact legacy-workload pre-state
# No acknowledged stage is recorded until the corresponding batch exits zero.

STAGES=(PREPARED PRIVATE_LIVE DATA_SWITCHED PUBLIC_LIVE CLIENT_ADDED)
ROLLBACK_ORDER="client nginx alias workload legacy"

required() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "FATAL: ${name} is required" >&2
    exit 64
  fi
}

stage_index() {
  local candidate="$1"
  local index
  for index in "${!STAGES[@]}"; do
    if [[ "${STAGES[$index]}" == "${candidate}" ]]; then
      printf '%s\n' "${index}"
      return 0
    fi
  done
  return 1
}

journal_write() {
  local stage="$1"
  local pending="$2"
  local temporary="${JOURNAL_PATH}.tmp"
  umask 077
  {
    printf 'schema=solidstats-memory-cutover-journal/v1\n'
    printf 'run_id_sha256=%s\n' "${RUN_ID_SHA256}"
    printf 'stage=%s\n' "${stage}"
    printf 'pending=%s\n' "${pending}"
    printf 'legacy_transition=preserved_until_plan_21_04\n'
  } >"${temporary}"
  chmod 600 "${temporary}"
  sync "${temporary}"
  mv "${temporary}" "${JOURNAL_PATH}"
  sync "${JOURNAL_PATH}"
}

record_stage() {
  local stage="$1"
  stage_index "${stage}" >/dev/null || {
    echo "FATAL: invalid journal stage" >&2
    return 1
  }
  journal_write "${stage}" "none"
  CURRENT_STAGE="${stage}"
  PENDING_MUTATION="none"
}

record_pending() {
  local boundary="$1"
  case "${boundary}" in
    legacy|workload|alias|nginx|client) ;;
    *) echo "FATAL: invalid pending mutation" >&2; return 1 ;;
  esac
  journal_write "${CURRENT_STAGE}" "${boundary}"
  PENDING_MUTATION="${boundary}"
}

load_journal() {
  [[ -f "${JOURNAL_PATH}" && ! -L "${JOURNAL_PATH}" ]] || {
    echo "FATAL: resume journal is unavailable" >&2
    return 1
  }
  local mode
  mode=$(stat -c '%a' "${JOURNAL_PATH}")
  [[ "${mode}" == "600" ]] || {
    echo "FATAL: resume journal mode is unsafe" >&2
    return 1
  }
  local schema stored_run stage pending legacy_transition
  schema=$(sed -n 's/^schema=//p' "${JOURNAL_PATH}")
  stored_run=$(sed -n 's/^run_id_sha256=//p' "${JOURNAL_PATH}")
  stage=$(sed -n 's/^stage=//p' "${JOURNAL_PATH}")
  pending=$(sed -n 's/^pending=//p' "${JOURNAL_PATH}")
  legacy_transition=$(sed -n 's/^legacy_transition=//p' "${JOURNAL_PATH}")
  [[ "${schema}" == "solidstats-memory-cutover-journal/v1" ]] || return 1
  [[ "${stored_run}" == "${RUN_ID_SHA256}" ]] || {
    echo "FATAL: resume run identity does not match" >&2
    return 1
  }
  stage_index "${stage}" >/dev/null || return 1
  [[ "${pending}" =~ ^(none|legacy|workload|alias|nginx|client)$ ]] || return 1
  [[ "${legacy_transition}" == "preserved_until_plan_21_04" ]] || return 1
  CURRENT_STAGE="${stage}"
  PENDING_MUTATION="${pending}"
}

run_remote_batch() {
  local operation="$1"
  shift
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    case "${operation}" in
      rollback-nginx) printf 'nginx ' >>"${EVENT_LOG}" ;;
      stop-new) printf 'workload ' >>"${EVENT_LOG}" ;;
      start-legacy) printf 'legacy ' >>"${EVENT_LOG}" ;;
      *) printf '%s ' "${operation}" >>"${EVENT_LOG}" ;;
    esac
    return 0
  fi
  required SOLIDSTATS_MEMORY_SSH_TARGET
  required SOLIDSTATS_MEMORY_REMOTE_OPERATOR
  required SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE
  required SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE
  [[ "${SOLIDSTATS_MEMORY_REMOTE_OPERATOR}" =~ ^/[A-Za-z0-9_./:@+-]+$ &&
    "${SOLIDSTATS_MEMORY_REMOTE_OPERATOR}" != *".."* ]] || {
    echo "FATAL: remote operator path is invalid" >&2
    return 1
  }
  [[ "${SOLIDSTATS_MEMORY_SSH_TARGET}" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+$ ]] || {
    echo "FATAL: SSH target is invalid" >&2
    return 1
  }
  local ssh_file ssh_mode
  for ssh_file in "${SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE}" "${SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE}"; do
    [[ "${ssh_file}" =~ ^/[A-Za-z0-9_./:@+-]+$ && "${ssh_file}" != *".."* &&
      -s "${ssh_file}" && -f "${ssh_file}" && ! -L "${ssh_file}" &&
      "$(stat -c '%u' "${ssh_file}")" == "$(id -u)" ]] || {
      echo "FATAL: SSH binding is unavailable or unsafe" >&2
      return 1
    }
  done
  ssh_mode=$(stat -c '%a' "${SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE}")
  [[ "${ssh_mode}" == "600" ]] || {
    echo "FATAL: SSH identity mode is unsafe" >&2
    return 1
  }
  ssh_mode=$(stat -c '%a' "${SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE}")
  [[ "${ssh_mode}" =~ ^(600|640|644)$ ]] || {
    echo "FATAL: SSH known-hosts mode is unsafe" >&2
    return 1
  }
  local input_path="/dev/null"
  if [[ "${operation}" == "install-nginx" ]]; then
    input_path="${1:-}"
    shift || true
    [[ -f "${input_path}" && ! -L "${input_path}" ]] || {
      echo "FATAL: nginx template input is unavailable" >&2
      return 1
    }
  fi
  local attempt
  for attempt in 1 2 3; do
    if timeout "${REMOTE_TIMEOUT}" ssh \
      -F /dev/null \
      -i "${SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE}" \
      -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=yes \
      -o "UserKnownHostsFile=${SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE}" \
      -o BatchMode=yes \
      -o ConnectTimeout=10 \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=2 \
      "${SOLIDSTATS_MEMORY_SSH_TARGET}" \
      "${SOLIDSTATS_MEMORY_REMOTE_OPERATOR}" \
      "${operation}" "${RUN_ID_SHA256}" "$@" \
      <"${input_path}" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

run_alias() {
  local operation="$1"
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'alias ' >>"${EVENT_LOG}"
    return 0
  fi
  timeout "${LOCAL_TIMEOUT}" python3 "${RESTORE_SCRIPT}" "${operation}" >/dev/null
}

run_runtime_bootstrap() {
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'runtime-bootstrap ' >>"${EVENT_LOG}"
    return 0
  fi
  required SOLIDSTATS_MEMORY_OPERATOR_CONFIG
  local request="${STATE_DIR}/runtime-bootstrap.request.json"
  local response="${STATE_DIR}/runtime-bootstrap.response.json"
  if [[ ! -e "${request}" ]]; then
    printf '{}\n' >"${request}"
    chmod 600 "${request}"
  fi
  [[ -f "${request}" && ! -L "${request}" && "$(stat -c '%a' "${request}")" == "600" ]] || {
    echo "FATAL: runtime bootstrap request is unsafe" >&2
    return 1
  }
  if [[ -e "${response}" ]]; then
    [[ -f "${response}" && ! -L "${response}" && "$(stat -c '%a' "${response}")" == "600" ]] || {
      echo "FATAL: runtime bootstrap response is unsafe" >&2
      return 1
    }
    rm -f "${response}"
  fi
  SOLIDSTATS_MEMORY_OPERATOR_CONFIG="${SOLIDSTATS_MEMORY_OPERATOR_CONFIG}" \
    timeout "${PROBE_TIMEOUT}" python3 "${PRIVATE_OPERATOR_SCRIPT}" \
      bootstrap-runtime-palace "${request}" "${response}" >/dev/null
  [[ -s "${response}" && -f "${response}" && ! -L "${response}" &&
    "$(stat -c '%a' "${response}")" == "600" ]] || {
    echo "FATAL: runtime bootstrap evidence is unavailable" >&2
    return 1
  }
}

register_client() {
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'client-add ' >>"${EVENT_LOG}"
    [[ "${CUTOVER_SELF_TEST_POLICY_FAIL:-}" != "1" ]] || return 1
    return 0
  fi
  required SOLIDSTATS_MEMORY_PUBLIC_URL
  required SOLIDSTATS_MEMORY_TOKEN_ENV
  required SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH
  [[ "${SOLIDSTATS_MEMORY_PUBLIC_URL}" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/solidstats/mcp$ ]] || {
    echo "FATAL: public MCP URL must end at exact /solidstats/mcp" >&2
    return 1
  }
  [[ "${SOLIDSTATS_MEMORY_TOKEN_ENV}" =~ ^[A-Z][A-Z0-9_]{0,127}$ ]] || {
    echo "FATAL: token environment name is invalid" >&2
    return 1
  }
  if timeout "${LOCAL_TIMEOUT}" codex mcp get solidstats_memory \
    >/dev/null 2>&1; then
    echo "FATAL: solidstats_memory already exists; exact pre-state is not absent" >&2
    return 1
  fi
  timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" capture \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --prestate "${CLIENT_CONFIG_PRESTATE}" >/dev/null
  timeout "${LOCAL_TIMEOUT}" codex mcp add solidstats_memory \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --bearer-token-env-var "${SOLIDSTATS_MEMORY_TOKEN_ENV}" \
    >/dev/null
  timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" apply \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --prestate "${CLIENT_CONFIG_PRESTATE}" \
    --name solidstats_memory \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" >/dev/null
  timeout "${LOCAL_TIMEOUT}" codex mcp get solidstats_memory >/dev/null
  timeout "${LOCAL_TIMEOUT}" python3 "${PROBE_SCRIPT}" client-policy \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" >/dev/null
}

remove_new_client() {
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'client ' >>"${EVENT_LOG}"
    return 0
  fi
  required SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH
  if [[ ! -f "${CLIENT_CONFIG_PRESTATE}" || -L "${CLIENT_CONFIG_PRESTATE}" ]]; then
    if ! timeout "${LOCAL_TIMEOUT}" codex mcp get solidstats_memory \
      >/dev/null 2>&1; then
      return 0
    fi
    echo "FATAL: exact client config prestate is unavailable" >&2
    return 1
  fi
  if timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" rollback \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --prestate "${CLIENT_CONFIG_PRESTATE}" \
    --name solidstats_memory >/dev/null; then
    return 0
  fi
  return 1
}

rollback() {
  local stage="${CURRENT_STAGE}"
  local pending="${PENDING_MUTATION}"
  local index
  index=$(stage_index "${stage}")
  local failed=0

  if [[ "${pending}" == "client" || "${index}" -ge 4 ]]; then
    remove_new_client || failed=1
  fi
  if [[ "${pending}" == "nginx" || "${pending}" == "client" || "${index}" -ge 3 ]]; then
    run_remote_batch rollback-nginx || failed=1
  fi
  if [[ "${pending}" =~ ^(alias|nginx|client)$ || "${index}" -ge 2 ]]; then
    run_alias rollback || failed=1
  fi
  if [[ "${pending}" =~ ^(workload|alias|nginx|client)$ || "${index}" -ge 1 ]]; then
    run_remote_batch stop-new || failed=1
  fi
  if [[ "${pending}" =~ ^(legacy|workload|alias|nginx|client)$ || "${index}" -ge 1 ]]; then
    run_remote_batch start-legacy || failed=1
  fi
  if [[ "${failed}" -ne 0 ]]; then
    echo "FATAL: rollback did not restore every recorded boundary" >&2
    return 1
  fi
  record_stage PREPARED
}

handle_cutover_failure() {
  local status=$?
  trap - ERR
  if ! rollback; then
    echo "FATAL: cutover failed and rollback is incomplete" >&2
  fi
  exit "${status}"
}

run_probe() {
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'probe ' >>"${EVENT_LOG}"
    return 0
  fi
  required SOLIDSTATS_MEMORY_PUBLIC_URL
  required SOLIDSTATS_MEMORY_TOKEN_ENV
  required SOLIDSTATS_MEMORY_RUN_ID
  timeout "${PROBE_TIMEOUT}" python3 "${PROBE_SCRIPT}" full \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" \
    --run-id "${SOLIDSTATS_MEMORY_RUN_ID}" >/dev/null
}

preflight() {
  if [[ "${CURRENT_STAGE}" != "PREPARED" ]]; then
    return 0
  fi
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "DRY_RUN: preflight contract validated"
    return 0
  fi
  run_remote_batch capture-prestate
  if [[ "${CUTOVER_SELF_TEST:-}" != "1" ]]; then
    required SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME
    timeout "${LOCAL_TIMEOUT}" codex mcp get \
      "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" >/dev/null
    if timeout "${LOCAL_TIMEOUT}" codex mcp get solidstats_memory \
      >/dev/null 2>&1; then
      echo "FATAL: new client exists before cutover" >&2
      return 1
    fi
    timeout "${LOCAL_TIMEOUT}" python3 "${RESTORE_SCRIPT}" \
      alias-prestate --check-only >/dev/null
    timeout "${LOCAL_TIMEOUT}" python3 "${RESTORE_SCRIPT}" \
      rollback --check-only >/dev/null
    timeout "${LOCAL_TIMEOUT}" python3 "${PROBE_SCRIPT}" --help >/dev/null
    run_runtime_bootstrap
    timeout "${LOCAL_TIMEOUT}" python3 "${RESTORE_SCRIPT}" \
      alias-prestate >/dev/null
  fi
}

perform_cutover() {
  local index
  index=$(stage_index "${CURRENT_STAGE}")
  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "DRY_RUN: legacy/workload, alias, nginx, probe, and client mutations skipped"
    return 0
  fi
  if [[ "${PENDING_MUTATION}" != "none" ]]; then
    echo "WARN: unacknowledged mutation found; rolling back before resume" >&2
    rollback
    index=0
  fi
  if [[ "${index}" -lt 1 ]]; then
    record_pending workload
    run_remote_batch stop-legacy-start-new
    record_stage PRIVATE_LIVE
  fi
  index=$(stage_index "${CURRENT_STAGE}")
  if [[ "${index}" -lt 2 ]]; then
    record_pending alias
    run_alias alias-cutover
    record_stage DATA_SWITCHED
  fi
  index=$(stage_index "${CURRENT_STAGE}")
  if [[ "${index}" -lt 3 ]]; then
    record_pending nginx
    run_remote_batch install-nginx "${NGINX_TEMPLATE}"
    run_probe
    record_stage PUBLIC_LIVE
  fi
  index=$(stage_index "${CURRENT_STAGE}")
  if [[ "${index}" -lt 4 ]]; then
    record_pending client
    register_client
    record_stage CLIENT_ADDED
  fi
}

self_test_failure_case() {
  local stage="$1"
  local pending="$2"
  local expected="$3"
  : >"${EVENT_LOG}"
  CURRENT_STAGE="${stage}"
  PENDING_MUTATION="${pending}"
  journal_write "${stage}" "${pending}"
  set +e
  (
    trap handle_cutover_failure ERR
    false
  ) >/dev/null 2>&1
  local status=$?
  set -e
  [[ "${status}" -ne 0 ]] || {
    echo "SELF_TEST FAILED: injected mutation failure was accepted" >&2
    return 1
  }
  local observed
  observed=$(sed -e 's/[[:space:]]*$//' "${EVENT_LOG}")
  [[ "${observed}" == "${expected}" ]] || {
    echo "SELF_TEST FAILED: rollback order mismatch" >&2
    return 1
  }
}

self_test() {
  local temporary
  temporary=$(mktemp -d)
  chmod 700 "${temporary}"
  CUTOVER_SELF_TEST=1
  STATE_DIR="${temporary}/state"
  mkdir -m 700 "${STATE_DIR}"
  JOURNAL_PATH="${STATE_DIR}/journal"
  EVENT_LOG="${temporary}/events"
  RUN_ID_SHA256=$(printf 'phase21-self-test' | sha256sum | cut -d' ' -f1)
  CURRENT_STAGE="PREPARED"
  PENDING_MUTATION="none"

  self_test_failure_case PREPARED workload "workload legacy"
  self_test_failure_case PRIVATE_LIVE alias "alias workload legacy"
  self_test_failure_case DATA_SWITCHED nginx "nginx alias workload legacy"
  self_test_failure_case PUBLIC_LIVE client "client nginx alias workload legacy"
  : >"${EVENT_LOG}"
  CURRENT_STAGE="PUBLIC_LIVE"
  PENDING_MUTATION="none"
  journal_write "${CURRENT_STAGE}" "${PENDING_MUTATION}"
  CUTOVER_SELF_TEST_POLICY_FAIL=1
  set +e
  (
    trap handle_cutover_failure ERR
    perform_cutover
  ) >/dev/null 2>&1
  local policy_status=$?
  set -e
  unset CUTOVER_SELF_TEST_POLICY_FAIL
  [[ "${policy_status}" -ne 0 ]] || {
    echo "SELF_TEST FAILED: client policy failure was accepted" >&2
    return 1
  }
  [[ "$(sed -e 's/[[:space:]]*$//' "${EVENT_LOG}")" == \
    "client-add client nginx alias workload legacy" ]] || {
    echo "SELF_TEST FAILED: client policy rollback order mismatch" >&2
    return 1
  }
  echo "SELF_TEST PASSED: ${ROLLBACK_ORDER}"
  rm -f "${EVENT_LOG}" "${JOURNAL_PATH}"
  rmdir "${STATE_DIR}" "${temporary}"
}

usage() {
  echo "usage: cutover-solidstats-memory.sh [preflight|cutover|rollback] [--dry-run] [--resume-run]"
  echo "       cutover-solidstats-memory.sh --self-test"
}

main() {
  local command=""
  DRY_RUN=0
  RESUME_RUN=0
  if [[ "${1:-}" == "--self-test" ]]; then
    self_test
    return 0
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      preflight|cutover|rollback) command="$1" ;;
      --dry-run) DRY_RUN=1 ;;
      --resume-run) RESUME_RUN=1 ;;
      --help|-h) usage; return 0 ;;
      *) echo "FATAL: unknown argument" >&2; usage >&2; return 64 ;;
    esac
    shift
  done
  [[ -n "${command}" ]] || { usage >&2; return 64; }

  required SOLIDSTATS_MEMORY_RUN_ID
  required SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT
  RUN_ID_SHA256=$(printf '%s' "${SOLIDSTATS_MEMORY_RUN_ID}" | sha256sum | cut -d' ' -f1)
  STATE_DIR="${SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT}/${RUN_ID_SHA256}"
  mkdir -p -m 700 "${STATE_DIR}"
  chmod 700 "${STATE_DIR}"
  JOURNAL_PATH="${STATE_DIR}/cutover.journal"
  : "${SOLIDSTATS_MEMORY_ALIAS_PRESTATE:=${STATE_DIR}/alias-prestate.json}"
  export SOLIDSTATS_MEMORY_ALIAS_PRESTATE
  CURRENT_STAGE="PREPARED"
  PENDING_MUTATION="none"
  REMOTE_TIMEOUT="${SOLIDSTATS_MEMORY_REMOTE_TIMEOUT:-600s}"
  LOCAL_TIMEOUT="${SOLIDSTATS_MEMORY_LOCAL_TIMEOUT:-60s}"
  PROBE_TIMEOUT="${SOLIDSTATS_MEMORY_PROBE_TIMEOUT:-1800s}"
  SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  RESTORE_SCRIPT="${SCRIPT_DIR}/restore-solidstats-memory.py"
  PRIVATE_OPERATOR_SCRIPT="${SCRIPT_DIR}/operate-solidstats-memory.py"
  PROBE_SCRIPT="${SCRIPT_DIR}/probe-solidstats-memory.py"
  CLIENT_POLICY_SCRIPT="${SCRIPT_DIR}/configure-solidstats-memory-client.py"
  CLIENT_CONFIG_PRESTATE="${STATE_DIR}/codex-config.prestate.toml"
  NGINX_TEMPLATE="${SCRIPT_DIR}/../config/nginx/sites-available/solidstats-memory-shared-cutover.patch.template"

  if [[ -e "${JOURNAL_PATH}" ]]; then
    [[ "${RESUME_RUN}" == "1" ]] || {
      echo "FATAL: existing journal requires --resume-run" >&2
      return 1
    }
    load_journal
  else
    journal_write PREPARED none
  fi

  case "${command}" in
    preflight) preflight ;;
    cutover)
      trap handle_cutover_failure ERR
      preflight
      perform_cutover
      trap - ERR
      echo "PASS: CLIENT_ADDED; legacy is transitional until Plan 21-04 seal"
      ;;
    rollback) rollback ;;
  esac
}

main "$@"
