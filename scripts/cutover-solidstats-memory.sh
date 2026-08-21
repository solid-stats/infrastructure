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

require_private_root() {
  local path="$1" current component
  local -a components
  [[ "${path}" == /* && "${path}" != *..* ]] || return 1
  current=/
  IFS='/' read -r -a components <<<"${path#/}"
  for component in "${components[@]}"; do
    [[ -n "${component}" ]] || continue
    current="${current%/}/${component}"
    if [[ -e "${current}" || -L "${current}" ]]; then
      [[ -d "${current}" && ! -L "${current}" ]] || return 1
    else
      mkdir -m 700 "${current}" || return 1
    fi
  done
  [[ "$(stat -c '%a:%u' "${path}")" == "700:$(id -u)" ]] || return 1
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
  local attempt max_attempts=3 retry_delay=0 call_timeout="${REMOTE_TIMEOUT}"
  local output_path="${STATE_DIR}/remote-${operation}.result"
  case "${operation}" in
    prove-backup-consistency)
      max_attempts=1
      call_timeout="${BACKUP_REMOTE_TIMEOUT_SECONDS}s"
      ;;
    verify-reboot-recovery)
      [[ "${1:-}" =~ ^[1-9][0-9]{0,3}$ ]] || {
        echo "FATAL: reboot reconnect payload is invalid" >&2
        return 1
      }
      max_attempts=$((($1 + 24) / 25))
      retry_delay=5
      call_timeout=20s
      ;;
  esac
  for ((attempt = 1; attempt <= max_attempts; attempt += 1)); do
    if timeout "${call_timeout}" ssh \
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
      <"${input_path}" >"${output_path}.tmp" 2>/dev/null; then
      chmod 600 "${output_path}.tmp"
      if [[ "$(grep -c '^PASS: remote cutover boundary acknowledged$' "${output_path}.tmp" || true)" -ne 1 ]] ||
        grep -Ev '^(PASS: remote cutover boundary acknowledged|schema=solidstats-memory-remote-operation-result/v1|operation=[a-z0-9-]+|config_sha256=[0-9a-f]{64}|run_id_sha256=[0-9a-f]{64}|[a-z][a-z0-9_]{0,63}=(true|false|[0-9]+|[0-9a-f]{64}|service|endpoint))$' "${output_path}.tmp" | grep -q .; then
        rm -f "${output_path}.tmp"
        return 1
      fi
      local result_count
      result_count=$(grep -c '^schema=solidstats-memory-remote-operation-result/v1$' "${output_path}.tmp" || true)
      [[ "${result_count}" -eq 1 ]] || return 1
      if [[ "${result_count}" -eq 1 ]]; then
        [[ "$(grep -c '^operation=' "${output_path}.tmp")" -eq 1 &&
          "$(sed -n 's/^operation=//p' "${output_path}.tmp")" == "${operation}" &&
          "$(grep -c '^config_sha256=' "${output_path}.tmp")" -eq 1 &&
          "$(grep -c '^sequence=' "${output_path}.tmp")" -eq 1 &&
          "$(grep -c '^run_id_sha256=' "${output_path}.tmp")" -eq 1 &&
          "$(sed -n 's/^run_id_sha256=//p' "${output_path}.tmp")" == "${RUN_ID_SHA256}" ]] || return 1
        local observed_config config_binding="${STATE_DIR}/remote-config.sha256"
        observed_config=$(sed -n 's/^config_sha256=//p' "${output_path}.tmp")
        if [[ -f "${config_binding}" ]]; then
          [[ "$(<"${config_binding}")" == "${observed_config}" ]] || return 1
        else
          printf '%s\n' "${observed_config}" >"${config_binding}"
          chmod 600 "${config_binding}"
        fi
      fi
      mv -f "${output_path}.tmp" "${output_path}"
      return 0
    fi
    if [[ "${attempt}" -lt "${max_attempts}" && "${retry_delay}" -gt 0 ]]; then
      sleep "${retry_delay}"
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
  if ! timeout "${LOCAL_TIMEOUT}" codex mcp get solidstats_memory \
    >/dev/null 2>&1; then
    return 0
  fi
  if [[ ! -f "${CLIENT_CONFIG_PRESTATE}" || -L "${CLIENT_CONFIG_PRESTATE}" ]]; then
    echo "FATAL: exact client config prestate is unavailable" >&2
    return 1
  fi
  if timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" rollback-current \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --prestate "${CLIENT_CONFIG_PRESTATE}" \
    --result "${STATE_DIR}/client-rollback.result" \
    --name solidstats_memory \
    --legacy-name "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" \
    --timeout-seconds "${LOCAL_TIMEOUT%s}" >/dev/null; then
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
  local label="${1:-behavior}"
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'probe ' >>"${EVENT_LOG}"
    return 0
  fi
  required SOLIDSTATS_MEMORY_PUBLIC_URL
  required SOLIDSTATS_MEMORY_TOKEN_ENV
  required SOLIDSTATS_MEMORY_RUN_ID
  local evidence="${STATE_DIR}/probe-${label}.json"
  [[ "${label}" =~ ^[a-z0-9-]{1,48}$ ]] || return 1
  rm -f "${evidence}"
  timeout "${PROBE_TIMEOUT}" python3 "${PROBE_SCRIPT}" full \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" \
    --run-id "${SOLIDSTATS_MEMORY_RUN_ID}" --evidence "${evidence}" >/dev/null
}

write_recovery_gate() {
  local name="$1"
  local path="${STATE_DIR}/recovery-${name}.gate"
  umask 077
  printf 'pass\n' >"${path}.tmp"
  chmod 600 "${path}.tmp"
  mv "${path}.tmp" "${path}"
}

require_recovery_gate() {
  local name="$1"
  local path="${STATE_DIR}/recovery-${name}.gate"
  [[ -f "${path}" && ! -L "${path}" &&
    "$(stat -c '%a' "${path}")" == "600" &&
    "$(cat "${path}")" == "pass" ]] || {
    echo "FATAL: recovery predecessor is unavailable" >&2
    return 1
  }
}

restart_recovery() {
  [[ "${CURRENT_STAGE}" == "CLIENT_ADDED" ]] || {
    echo "FATAL: restart recovery requires CLIENT_ADDED" >&2
    return 1
  }
  run_remote_batch restart-mempalace
  run_probe restart-mempalace
  run_remote_batch restart-qdrant
  run_probe restart-qdrant
  write_recovery_gate restart
}

measure_backup_api_egress() {
  # The remote operator discovers Service and ready EndpointSlice candidates,
  # trials one exact /32 and port per fresh pod, prefers the Service result,
  # and retains only the selected mode/digest/booleans.
  run_remote_batch measure-backup-api-egress
}

prove_backup_api_access() {
  require_recovery_gate restart
  measure_backup_api_egress
  run_remote_batch prove-backup-api-positive
  run_remote_batch prove-backup-api-network-negative
  run_remote_batch prove-backup-api-rbac-negative
  run_remote_batch recheck-backup-api-access
  write_recovery_gate backup-api
}

prove_backup_consistency() {
  require_recovery_gate backup-api
  prepare_backup_activation
  stage_guard_package
  run_remote_batch capture-backup-template-digest
  run_remote_batch install-backup-guard
  run_remote_batch verify-backup-guard
  run_remote_batch test-backup-guard-suspension
  run_remote_batch record-backup-writer-prestate
  if ! run_remote_batch prove-backup-consistency; then
    recover_backup_failure
    echo "FATAL: backup consistency failed; recovery was verified" >&2
    return 1
  fi
  if ! run_probe backup-resumption; then
    recover_backup_failure
    echo "FATAL: write resumption failed; recovery was verified" >&2
    return 1
  fi
  write_recovery_gate backup-consistency
}

recover_backup_failure() {
  local failed=0
  if ! run_remote_batch restore-backup-writer; then failed=1; fi
  if ! run_remote_batch suspend-backup-schedule; then failed=1; fi
  if ! run_probe backup-failure-recovery; then failed=1; fi
  [[ "${failed}" -eq 0 ]] || {
    echo "FATAL: mandatory backup recovery is incomplete" >&2
    return 1
  }
}

activation_compensate() {
  local original_status="${1:-$?}" failed=0
  trap - ERR INT TERM
  if ! run_remote_batch suspend-backup-schedule; then failed=1; fi
  if [[ "${ACTIVATION_SOURCE_PROMOTED:-0}" == 1 ]] &&
    ! restore_suspended_backup_source; then failed=1; fi
  if [[ "${ACTIVATION_CLIENT_CHANGED:-0}" == 1 ]] &&
    ! restore_retired_client; then failed=1; fi
  if ! run_remote_batch restore-backup-writer; then failed=1; fi
  if [[ "${failed}" -ne 0 ]]; then
    echo "FATAL: activation compensation is incomplete" >&2
    return 1
  fi
  return "${original_status}"
}

reboot_recovery() {
  require_recovery_gate backup-consistency
  run_remote_batch capture-boot-identity
  run_remote_batch reboot-host
  run_remote_batch verify-reboot-recovery "${RECONNECT_TIMEOUT}"
  run_remote_batch verify-backup-guard
  run_probe reboot
  write_recovery_gate reboot
}

exercise_live_rollback() {
  require_recovery_gate reboot
  rollback
  run_remote_batch verify-legacy-behavior
  run_remote_batch rearm-forward-cycle
  perform_cutover
  run_remote_batch verify-retained-collections
  run_probe forward
  if [[ "${CUTOVER_SELF_TEST:-}" != 1 ]]; then
    {
      printf 'schema=solidstats-memory-rollback-forward-evidence/v1\n'
      printf 'rollback_client_sequence=1\nrollback_nginx_sequence=2\n'
      printf 'rollback_alias_sequence=3\nrollback_workload_sequence=4\n'
      printf 'rollback_legacy_sequence=5\nforward_rearm_sequence=6\n'
      printf 'forward_cutover_sequence=7\nretained_verification_sequence=8\n'
      printf 'reverse_order=true\nforward_exact=true\n'
    } >"${STATE_DIR}/rollback-forward.result.tmp"
    chmod 600 "${STATE_DIR}/rollback-forward.result.tmp"
    mv -f "${STATE_DIR}/rollback-forward.result.tmp" "${STATE_DIR}/rollback-forward.result"
  fi
  write_recovery_gate rollback-forward
}

activate_backup_schedule() {
  require_recovery_gate restart
  require_recovery_gate backup-api
  require_recovery_gate backup-consistency
  require_recovery_gate reboot
  require_recovery_gate rollback-forward
  if [[ "${CUTOVER_SELF_TEST:-}" == 1 ]]; then
    run_remote_batch install-backup-guard
    run_remote_batch verify-backup-guard
    run_remote_batch activate-backup-schedule
    write_recovery_gate activated
    return 0
  fi
  ACTIVATION_SOURCE_PROMOTED=0
  ACTIVATION_CLIENT_CHANGED=0
  on_activation_error() { local status=$?; trap - ERR INT TERM; activation_compensate "${status}" || exit 1; exit "${status}"; }
  on_activation_int() { trap - ERR INT TERM; activation_compensate 130 || exit 1; exit 130; }
  on_activation_term() { trap - ERR INT TERM; activation_compensate 143 || exit 1; exit 143; }
  trap on_activation_error ERR
  trap on_activation_int INT
  trap on_activation_term TERM
  prepare_backup_activation
  stage_guard_package
  run_remote_batch install-backup-guard
  run_remote_batch verify-backup-guard
  record_pre_retirement_client_evidence
  collect_recovery_evidence
  ACTIVATION_SOURCE_PROMOTED=1
  commit_backup_activation
  run_remote_batch activate-backup-schedule
  record_public_boundary_evidence
  if [[ "${CUTOVER_SELF_TEST:-}" != "1" ]]; then
    retire_legacy_client
    ACTIVATION_CLIENT_CHANGED=1
  fi
  collect_cutover_seal
  write_recovery_gate activated
  trap - ERR INT TERM
}

stage_guard_package() {
  if [[ "${CUTOVER_SELF_TEST:-}" == 1 ]]; then
    run_remote_batch prepare-guard-package
    run_remote_batch verify-guard-package
    return 0
  fi
  local gate="${STATE_DIR}/guard-package.gate" descriptor="${STATE_DIR}/guard-package.SHA256SUMS"
  required SOLIDSTATS_MEMORY_REMOTE_STATE_ROOT
  required SOLIDSTATS_MEMORY_BACKUP_GUARD_CONFIG
  [[ "${SOLIDSTATS_MEMORY_REMOTE_STATE_ROOT}" =~ ^/[A-Za-z0-9._/-]+$ &&
    "${SOLIDSTATS_MEMORY_REMOTE_STATE_ROOT}" != *..* &&
    "${SOLIDSTATS_MEMORY_REMOTE_STATE_ROOT}" != *//* ]] || return 1
  local package_root="${STATE_DIR}/guard-package-local"
  if [[ -e "${package_root}" ]]; then
    [[ -d "${package_root}" && ! -L "${package_root}" &&
      "$(stat -c '%a:%u' "${package_root}")" == "700:$(id -u)" ]] || return 1
  else
    mkdir -m 700 "${package_root}"
  fi
  install -m 755 "${SCRIPT_DIR}/guard-solidstats-memory-backup.sh" \
    "${package_root}/guard-solidstats-memory-backup.sh"
  install -m 755 "${SCRIPT_DIR}/suspend-solidstats-memory-backup.sh" \
    "${package_root}/suspend-solidstats-memory-backup.sh"
  install -m 644 "${SCRIPT_DIR}/solidstats-memory-backup-guard.service" \
    "${package_root}/solidstats-memory-backup-guard.service"
  install -m 644 "${SCRIPT_DIR}/solidstats-memory-backup-guard.timer" \
    "${package_root}/solidstats-memory-backup-guard.timer"
  install -m 600 "${SOLIDSTATS_MEMORY_BACKUP_GUARD_CONFIG}" \
    "${package_root}/guard-solidstats-memory-backup.sh.config"
  install -m 600 "${BACKUP_RENDERED_CANDIDATE}" \
    "${package_root}/40-backup.active.yaml"
  install -m 600 "${STATE_DIR}/backup-activation.provenance.json" \
    "${package_root}/backup-activation.provenance.json"
  local -a sources=(
    "${package_root}/guard-solidstats-memory-backup.sh"
    "${package_root}/suspend-solidstats-memory-backup.sh"
    "${package_root}/solidstats-memory-backup-guard.service"
    "${package_root}/solidstats-memory-backup-guard.timer"
    "${package_root}/guard-solidstats-memory-backup.sh.config"
    "${package_root}/40-backup.active.yaml"
    "${package_root}/backup-activation.provenance.json"
  )
  local source remote_dir="${SOLIDSTATS_MEMORY_REMOTE_STATE_ROOT}/${RUN_ID_SHA256}/guard-package"
  for source in "${sources[@]}"; do
    [[ -f "${source}" && ! -L "${source}" ]] || return 1
  done
  [[ "$(find "${package_root}" -mindepth 1 -maxdepth 1 | wc -l)" -eq 7 ]] || return 1
  [[ "$(stat -c '%a' "${SOLIDSTATS_MEMORY_BACKUP_GUARD_CONFIG}")" == 600 ]] || return 1
  {
    sha256sum "${sources[0]}" | sed 's#  .*#  guard-solidstats-memory-backup.sh#'
    sha256sum "${sources[1]}" | sed 's#  .*#  suspend-solidstats-memory-backup.sh#'
    sha256sum "${sources[2]}" | sed 's#  .*#  solidstats-memory-backup-guard.service#'
    sha256sum "${sources[3]}" | sed 's#  .*#  solidstats-memory-backup-guard.timer#'
    sha256sum "${sources[4]}" | sed 's#  .*#  guard-solidstats-memory-backup.sh.config#'
    sha256sum "${sources[5]}" | sed 's#  .*#  40-backup.active.yaml#'
    sha256sum "${sources[6]}" | sed 's#  .*#  backup-activation.provenance.json#'
  } >"${descriptor}"
  chmod 600 "${descriptor}"
  run_remote_batch prepare-guard-package
  local -a scp_options=(-p -F /dev/null -i "${SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=${SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE}" -o BatchMode=yes)
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[0]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/guard-solidstats-memory-backup.sh" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[1]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/suspend-solidstats-memory-backup.sh" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[2]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/solidstats-memory-backup-guard.service" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[3]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/solidstats-memory-backup-guard.timer" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[4]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/guard-solidstats-memory-backup.sh.config" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[5]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/40-backup.active.yaml" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${sources[6]}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/backup-activation.provenance.json" >/dev/null 2>&1
  timeout "${REMOTE_TIMEOUT}" scp "${scp_options[@]}" \
    "${descriptor}" "${SOLIDSTATS_MEMORY_SSH_TARGET}:${remote_dir}/SHA256SUMS" >/dev/null 2>&1
  run_remote_batch verify-guard-package
  printf 'pass\n' >"${gate}"
  chmod 600 "${gate}"
}

collect_recovery_evidence() {
  required SOLIDSTATS_MEMORY_CUTOVER_EVIDENCE
  required SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE
  timeout "${LOCAL_TIMEOUT}" python3 "${EVIDENCE_COLLECTOR}" \
    --schema recovery --state-root "${STATE_DIR}" \
    --run-id "${SOLIDSTATS_MEMORY_RUN_ID}" \
    --predecessor "${SOLIDSTATS_MEMORY_CUTOVER_EVIDENCE}" \
    --output "${SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE}"
  timeout "${LOCAL_TIMEOUT}" python3 "${PHASE21_VALIDATOR}" \
    --evidence "${SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE}" >/dev/null
}

record_pre_retirement_client_evidence() {
  required SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH
  timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" pre-retirement \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --result "${STATE_DIR}/client-pre-retirement.result" \
    --legacy-name "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" >/dev/null
}

record_public_boundary_evidence() {
  required SOLIDSTATS_MEMORY_PUBLIC_URL
  local host forward_probe api_result policy_sha boundary_result address_sha address_count port_6333_sha port_6334_sha
  forward_probe="${STATE_DIR}/probe-forward.json"
  api_result="${STATE_DIR}/remote-recheck-backup-api-access.result"
  [[ -f "${forward_probe}" && ! -L "${forward_probe}" &&
    -f "${api_result}" && ! -L "${api_result}" ]] || return 1
  host=$(python3 -c 'from urllib.parse import urlsplit; import sys; value=urlsplit(sys.argv[1]).hostname; print(value or "")' "${SOLIDSTATS_MEMORY_PUBLIC_URL}")
  [[ "${host}" =~ ^[A-Za-z0-9.-]+$ ]] || return 1
  boundary_result=$(timeout "${PROBE_TIMEOUT}" python3 "${PROBE_SCRIPT}" private-boundary \
    --host "${host}") || return 1
  [[ "$(printf '%s\n' "${boundary_result}" | wc -l)" -eq 6 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^address_set_sha256=')" -eq 1 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^address_count=')" -eq 1 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^port_6333_all_addresses_blocked=true$')" -eq 1 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^port_6333_result_sha256=')" -eq 1 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^port_6334_all_addresses_blocked=true$')" -eq 1 &&
    "$(printf '%s\n' "${boundary_result}" | grep -c '^port_6334_result_sha256=')" -eq 1 ]] || return 1
  address_sha=$(printf '%s\n' "${boundary_result}" | sed -n 's/^address_set_sha256=//p')
  address_count=$(printf '%s\n' "${boundary_result}" | sed -n 's/^address_count=//p')
  port_6333_sha=$(printf '%s\n' "${boundary_result}" | sed -n 's/^port_6333_result_sha256=//p')
  port_6334_sha=$(printf '%s\n' "${boundary_result}" | sed -n 's/^port_6334_result_sha256=//p')
  [[ "${address_sha}" =~ ^[0-9a-f]{64}$ && "${address_count}" =~ ^[1-9][0-9]?$ &&
    "${port_6333_sha}" =~ ^[0-9a-f]{64}$ && "${port_6334_sha}" =~ ^[0-9a-f]{64}$ ]] || return 1
  policy_sha=$(sed -n 's/^policy_sha256=//p' "${api_result}")
  [[ "${policy_sha}" =~ ^[0-9a-f]{64}$ ]] || return 1
  {
    printf 'schema=solidstats-memory-public-boundary-evidence/v1\n'
    printf 'sequence=620\naddress_set_sha256=%s\naddress_count=%s\n' "${address_sha}" "${address_count}"
    printf 'port_6333_all_addresses_blocked=true\nport_6333_result_sha256=%s\n' "${port_6333_sha}"
    printf 'port_6334_all_addresses_blocked=true\nport_6334_result_sha256=%s\n' "${port_6334_sha}"
    printf 'authenticated_mcp_boundary=true\n'
    printf 'authenticated_mcp_probe_sha256=%s\n' "$(sha256sum "${forward_probe}" | cut -d' ' -f1)"
    printf 'api_policy_sha256=%s\n' "${policy_sha}"
  } >"${STATE_DIR}/public-boundary.result.tmp"
  chmod 600 "${STATE_DIR}/public-boundary.result.tmp"
  mv -f "${STATE_DIR}/public-boundary.result.tmp" "${STATE_DIR}/public-boundary.result"
}

prepare_backup_activation() {
  [[ "${CUTOVER_SELF_TEST:-}" != 1 ]] || return 0
  local source="${SCRIPT_DIR}/../k8s/memory/40-backup.yaml"
  required SOLIDSTATS_MEMORY_RENDERED_MANIFEST_DIR
  required SOLIDSTATS_MEMORY_OPERATOR_CONFIG
  timeout "${LOCAL_TIMEOUT}" python3 "${SCRIPT_DIR}/validate-memory-manifests.py" \
    --allow-operator-placeholders >/dev/null
  BACKUP_SOURCE_PRESTATE="${STATE_DIR}/40-backup.suspended.yaml"
  BACKUP_SOURCE_CANDIDATE="${STATE_DIR}/40-backup.active.yaml"
  BACKUP_RENDERED_PRESTATE="${STATE_DIR}/40-backup.rendered-suspended.yaml"
  BACKUP_RENDERED_CANDIDATE="${STATE_DIR}/40-backup.rendered-active.yaml"
  [[ "$(grep -c '^  suspend: true$' "${source}")" -eq 1 ]] || return 1
  install -m 600 "${source}" "${BACKUP_SOURCE_PRESTATE}"
  local rendered="${SOLIDSTATS_MEMORY_RENDERED_MANIFEST_DIR}/40-backup.yaml"
  [[ -f "${rendered}" && ! -L "${rendered}" &&
    "$(grep -c '^  suspend: true$' "${rendered}")" -eq 1 ]] || return 1
  install -m 600 "${rendered}" "${BACKUP_RENDERED_PRESTATE}"
  local derived
  for derived in "${BACKUP_SOURCE_CANDIDATE}" "${BACKUP_RENDERED_CANDIDATE}" \
    "${STATE_DIR}/backup-activation.provenance.json"; do
    if [[ -e "${derived}" ]]; then
      [[ -f "${derived}" && ! -L "${derived}" &&
        "$(stat -c '%a:%u' "${derived}")" == "600:$(id -u)" ]] || return 1
      rm -f -- "${derived}"
    fi
  done
  timeout "${LOCAL_TIMEOUT}" python3 "${ACTIVATION_RENDERER}" \
    "${source}" "${rendered}" "${BACKUP_SOURCE_CANDIDATE}" \
    "${BACKUP_RENDERED_CANDIDATE}" \
    "${STATE_DIR}/backup-activation.provenance.json" \
    --operator-config "${SOLIDSTATS_MEMORY_OPERATOR_CONFIG}" >/dev/null
  sha256sum "${source}" "${BACKUP_SOURCE_CANDIDATE}" \
    "${rendered}" "${BACKUP_RENDERED_CANDIDATE}" >"${STATE_DIR}/backup-activation.digests"
  chmod 600 "${STATE_DIR}/backup-activation.digests"
}

commit_backup_activation() {
  local source="${SCRIPT_DIR}/../k8s/memory/40-backup.yaml"
  [[ -f "${BACKUP_SOURCE_CANDIDATE}" && ! -L "${BACKUP_SOURCE_CANDIDATE}" ]] || return 1
  install -m "$(stat -c '%a' "${source}")" "${BACKUP_SOURCE_CANDIDATE}" "${source}.tmp"
  mv -f "${source}.tmp" "${source}"
  local rendered="${SOLIDSTATS_MEMORY_RENDERED_MANIFEST_DIR}/40-backup.yaml"
  install -m "$(stat -c '%a' "${rendered}")" "${BACKUP_RENDERED_CANDIDATE}" "${rendered}.tmp"
  mv -f "${rendered}.tmp" "${rendered}"
  cmp -s -- "${source}" "${BACKUP_SOURCE_CANDIDATE}" || return 1
  cmp -s -- "${rendered}" "${BACKUP_RENDERED_CANDIDATE}" || return 1
  timeout "${LOCAL_TIMEOUT}" python3 "${SCRIPT_DIR}/validate-memory-manifests.py" \
    --allow-operator-placeholders >/dev/null
}

restore_suspended_backup_source() {
  if [[ "${CUTOVER_SELF_TEST:-}" == 1 ]]; then
    printf 'source ' >>"${EVENT_LOG}"
    return 0
  fi
  local source="${SCRIPT_DIR}/../k8s/memory/40-backup.yaml"
  [[ -f "${BACKUP_SOURCE_PRESTATE}" && ! -L "${BACKUP_SOURCE_PRESTATE}" ]] || return 1
  install -m "$(stat -c '%a' "${source}")" "${BACKUP_SOURCE_PRESTATE}" "${source}.tmp"
  mv -f "${source}.tmp" "${source}"
  local rendered="${SOLIDSTATS_MEMORY_RENDERED_MANIFEST_DIR}/40-backup.yaml"
  install -m "$(stat -c '%a' "${rendered}")" "${BACKUP_RENDERED_PRESTATE}" "${rendered}.tmp"
  mv -f "${rendered}.tmp" "${rendered}"
}

collect_cutover_seal() {
  required SOLIDSTATS_MEMORY_CUTOVER_SEAL
  timeout "${LOCAL_TIMEOUT}" python3 "${EVIDENCE_COLLECTOR}" \
    --schema seal --state-root "${STATE_DIR}" \
    --run-id "${SOLIDSTATS_MEMORY_RUN_ID}" \
    --cutover-evidence "${SOLIDSTATS_MEMORY_CUTOVER_EVIDENCE}" \
    --predecessor "${SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE}" \
    --output "${SOLIDSTATS_MEMORY_CUTOVER_SEAL}"
  timeout "${LOCAL_TIMEOUT}" python3 "${PHASE21_VALIDATOR}" \
    --evidence "${SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE}" \
    --evidence "${SOLIDSTATS_MEMORY_CUTOVER_SEAL}" >/dev/null
}

retire_legacy_client() {
  required SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME
  required SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH
  [[ "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" == "mempalace" ]] || {
    echo "FATAL: legacy client name is not the accepted exact name" >&2
    return 1
  }
  timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" retire \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --prestate "${CLIENT_CONFIG_PRESTATE}" \
    --result "${STATE_DIR}/client-retired.result" \
    --legacy-name "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" \
    --url "${SOLIDSTATS_MEMORY_PUBLIC_URL}" \
    --token-env "${SOLIDSTATS_MEMORY_TOKEN_ENV}" \
    --timeout-seconds "${LOCAL_TIMEOUT%s}" >/dev/null
}

restore_retired_client() {
  if [[ "${CUTOVER_SELF_TEST:-}" == "1" ]]; then
    printf 'client ' >>"${EVENT_LOG}"
    return 0
  fi
  required SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH
  timeout "${LOCAL_TIMEOUT}" python3 "${CLIENT_POLICY_SCRIPT}" \
    restore-retirement \
    --config "${SOLIDSTATS_MEMORY_CODEX_CONFIG_PATH}" \
    --result "${STATE_DIR}/client-retired.result" \
    --legacy-name "${SOLIDSTATS_MEMORY_LEGACY_CLIENT_NAME}" >/dev/null
}

seal_cutover() {
  require_recovery_gate activated
  required SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE
  required SOLIDSTATS_MEMORY_CUTOVER_SEAL
  timeout "${LOCAL_TIMEOUT}" python3 "${PHASE21_VALIDATOR}" \
    --evidence "${SOLIDSTATS_MEMORY_RECOVERY_EVIDENCE}" \
    --evidence "${SOLIDSTATS_MEMORY_CUTOVER_SEAL}" >/dev/null
  write_recovery_gate sealed
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
  NGINX_TEMPLATE="/dev/null"

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
  local boundary expected compensation_status
  for boundary in prepared source-promoted live-activated legacy-retired seal; do
    : >"${EVENT_LOG}"
    ACTIVATION_SOURCE_PROMOTED=0
    ACTIVATION_CLIENT_CHANGED=0
    expected="suspend-backup-schedule restore-backup-writer"
    if [[ "${boundary}" != prepared ]]; then
      ACTIVATION_SOURCE_PROMOTED=1
      expected="suspend-backup-schedule source restore-backup-writer"
    fi
    if [[ "${boundary}" == legacy-retired || "${boundary}" == seal ]]; then
      ACTIVATION_CLIENT_CHANGED=1
      expected="suspend-backup-schedule source client restore-backup-writer"
    fi
    set +e
    (activation_compensate 1) >/dev/null 2>&1
    compensation_status=$?
    set -e
    [[ "${compensation_status}" -ne 0 &&
      "$(sed -e 's/[[:space:]]*$//' "${EVENT_LOG}")" == "${expected}" ]] || {
      echo "SELF_TEST FAILED: activation compensation order mismatch" >&2
      return 1
    }
  done
  CURRENT_STAGE="CLIENT_ADDED"
  PENDING_MUTATION="none"
  RECONNECT_TIMEOUT=30
  : >"${EVENT_LOG}"
  restart_recovery
  prove_backup_api_access
  prove_backup_consistency
  reboot_recovery
  exercise_live_rollback
  activate_backup_schedule
  local recovery_events
  recovery_events=$(sed -e 's/[[:space:]]*$//' "${EVENT_LOG}")
  [[ "${recovery_events}" == restart-mempalace\ probe\ restart-qdrant\ probe\ * ]] || {
    echo "SELF_TEST FAILED: restart behavior order mismatch" >&2
    return 1
  }
  for gate in restart backup-api backup-consistency reboot rollback-forward activated; do
    require_recovery_gate "${gate}"
  done
  echo "SELF_TEST PASSED: ${ROLLBACK_ORDER}"
  echo "RECOVERY_SELF_TEST PASSED"
  rm -f "${STATE_DIR}"/recovery-*.gate
  rm -f "${EVENT_LOG}" "${JOURNAL_PATH}"
  rmdir "${STATE_DIR}" "${temporary}"
}

usage() {
  echo "usage: cutover-solidstats-memory.sh [preflight|cutover|rollback|restart-recovery|reboot-recovery|prove-backup-api-access|prove-backup-consistency|exercise-rollback|activate-backup-schedule|seal] [--dry-run] [--resume-run] [--reconnect-timeout SECONDS]"
  echo "       cutover-solidstats-memory.sh --self-test"
}

main() {
  local command=""
  DRY_RUN=0
  RESUME_RUN=0
  RECONNECT_TIMEOUT=900
  if [[ "${1:-}" == "--self-test" ]]; then
    self_test
    return 0
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      preflight|cutover|rollback|restart-recovery|reboot-recovery|prove-backup-api-access|prove-backup-consistency|exercise-rollback|activate-backup-schedule|seal) command="$1" ;;
      --dry-run) DRY_RUN=1 ;;
      --resume-run) RESUME_RUN=1 ;;
      --reconnect-timeout)
        shift
        [[ "${1:-}" =~ ^[1-9][0-9]{0,3}$ ]] || {
          echo "FATAL: reconnect timeout is invalid" >&2
          return 64
        }
        RECONNECT_TIMEOUT="$1"
        ;;
      --help|-h) usage; return 0 ;;
      *) echo "FATAL: unknown argument" >&2; usage >&2; return 64 ;;
    esac
    shift
  done
  [[ -n "${command}" ]] || { usage >&2; return 64; }

  required SOLIDSTATS_MEMORY_RUN_ID
  required SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT
  require_private_root "${SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT}" || {
    echo "FATAL: private run root is unsafe" >&2
    return 1
  }
  RUN_ID_SHA256=$(printf '%s' "${SOLIDSTATS_MEMORY_RUN_ID}" | sha256sum | cut -d' ' -f1)
  STATE_DIR="${SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT}/${RUN_ID_SHA256}"
  require_private_root "${STATE_DIR}" || return 1
  JOURNAL_PATH="${STATE_DIR}/cutover.journal"
  ALIAS_LOCK_PATH="${SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT}/.solidstats-memory-alias.lock"
  exec 9<>"${ALIAS_LOCK_PATH}"
  chmod 600 "${ALIAS_LOCK_PATH}"
  flock -n 9 || {
    echo "FATAL: alias writer lease is held" >&2
    return 1
  }
  printf '{"schema":"solidstats-memory-alias-lock/v1","pid":%d,"run_id_sha256":"%s"}\n' "$$" "${RUN_ID_SHA256}" >"${ALIAS_LOCK_PATH}"
  sync "${ALIAS_LOCK_PATH}"
  export SOLIDSTATS_MEMORY_ALIAS_LOCK_FD=9
  : "${SOLIDSTATS_MEMORY_ALIAS_PRESTATE:=${STATE_DIR}/alias-prestate.json}"
  export SOLIDSTATS_MEMORY_ALIAS_PRESTATE
  CURRENT_STAGE="PREPARED"
  PENDING_MUTATION="none"
  REMOTE_TIMEOUT="${SOLIDSTATS_MEMORY_REMOTE_TIMEOUT:-600s}"
  BACKUP_REMOTE_TIMEOUT_SECONDS="${SOLIDSTATS_MEMORY_BACKUP_REMOTE_TIMEOUT_SECONDS:-3600}"
  [[ "${BACKUP_REMOTE_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]{0,3}$ &&
    "${BACKUP_REMOTE_TIMEOUT_SECONDS}" -le 3600 ]] || {
    echo "FATAL: backup remote timeout is invalid" >&2
    return 64
  }
  LOCAL_TIMEOUT="${SOLIDSTATS_MEMORY_LOCAL_TIMEOUT:-60s}"
  PROBE_TIMEOUT="${SOLIDSTATS_MEMORY_PROBE_TIMEOUT:-1800s}"
  SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  RESTORE_SCRIPT="${SCRIPT_DIR}/restore-solidstats-memory.py"
  PRIVATE_OPERATOR_SCRIPT="${SCRIPT_DIR}/operate-solidstats-memory.py"
  PROBE_SCRIPT="${SCRIPT_DIR}/probe-solidstats-memory.py"
  CLIENT_POLICY_SCRIPT="${SCRIPT_DIR}/configure-solidstats-memory-client.py"
  PHASE21_VALIDATOR="${SCRIPT_DIR}/validate-phase-21.py"
  EVIDENCE_COLLECTOR="${SCRIPT_DIR}/collect-phase-21-recovery-evidence.py"
  ACTIVATION_RENDERER="${SCRIPT_DIR}/render-solidstats-memory-backup-activation.py"
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
    restart-recovery) restart_recovery ;;
    reboot-recovery) reboot_recovery ;;
    prove-backup-api-access) prove_backup_api_access ;;
    prove-backup-consistency) prove_backup_consistency ;;
    exercise-rollback) exercise_live_rollback ;;
    activate-backup-schedule) activate_backup_schedule ;;
    seal) seal_cutover ;;
  esac
}

main "$@"
