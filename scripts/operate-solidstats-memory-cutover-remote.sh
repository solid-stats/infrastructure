#!/usr/bin/env bash
set -Eeuo pipefail

# Host-side half of the Phase 21 memory cutover. The local orchestrator invokes
# one allowlisted operation per SSH batch. All private paths and command paths come
# from a root-owned, mode-0600 config; the file is parsed as data, never sourced.

readonly CONFIG_SCHEMA="solidstats-memory-remote-cutover-config/v1"
readonly MAX_NGINX_BYTES=1048576

fatal() {
  echo "FATAL: remote cutover operation failed closed" >&2
  exit 1
}

usage() {
  echo "usage: operate-solidstats-memory-cutover-remote.sh OPERATION RUN_ID_SHA256" >&2
  exit 64
}

valid_path_value() {
  [[ "$1" =~ ^/[A-Za-z0-9_./:@+-]+$ && "$1" != *".."* ]]
}

require_regular_private_file() {
  local path="$1"
  [[ -f "${path}" && ! -L "${path}" ]] || fatal
  [[ "$(stat -c '%a' -- "${path}")" == "600" ]] || fatal
  [[ "$(stat -c '%u' -- "${path}")" == "$(id -u)" ]] || fatal
}

require_binary() {
  local path="$1" owner mode
  valid_path_value "${path}" || fatal
  [[ -f "${path}" && ! -L "${path}" && -x "${path}" ]] || fatal
  owner=$(stat -c '%u' -- "${path}")
  [[ "${owner}" == 0 || "${owner}" == "$(id -u)" ]] || fatal
  mode=$(stat -c '%a' -- "${path}")
  (( (8#${mode} & 8#022) == 0 )) || fatal
}

path_within() {
  local root path
  root=$(realpath -m -- "$1")
  path=$(realpath -m -- "$2")
  [[ "${path}" == "${root}" || "${path}" == "${root}/"* ]]
}

load_config() {
  local config_path="$1"
  valid_path_value "${config_path}" || fatal
  require_regular_private_file "${config_path}"
  local config_parent
  config_parent=$(dirname "${config_path}")
  [[ -d "${config_parent}" && ! -L "${config_parent}" ]] || fatal
  [[ "$(stat -c '%a' -- "${config_parent}")" == "700" ]] || fatal
  [[ "$(stat -c '%u' -- "${config_parent}")" == "$(id -u)" ]] || fatal
  local line key value
  local -A seen=()
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" == *=* && "${line}" != *$'\r'* && "${line}" != *$'\n'* ]] || fatal
    key=${line%%=*}
    value=${line#*=}
    [[ -n "${key}" && -z "${seen[${key}]:-}" ]] || fatal
    seen[${key}]=1
    case "${key}" in
      schema) CONFIG_SCHEMA_VALUE="${value}" ;;
      state_root) STATE_ROOT="${value}" ;;
      runuser_path) RUNUSER_PATH="${value}" ;;
      docker_path) DOCKER_PATH="${value}" ;;
      kubectl_path) KUBECTL_PATH="${value}" ;;
      curl_path) CURL_PATH="${value}" ;;
      nginx_path) NGINX_PATH="${value}" ;;
      systemctl_path) SYSTEMCTL_PATH="${value}" ;;
      python_path) PYTHON_PATH="${value}" ;;
      nginx_unit) NGINX_UNIT="${value}" ;;
      kube_context) KUBE_CONTEXT="${value}" ;;
      new_namespace) NEW_NAMESPACE="${value}" ;;
      new_deployment) NEW_DEPLOYMENT="${value}" ;;
      new_expected_replicas) NEW_EXPECTED_REPLICAS="${value}" ;;
      nginx_root) NGINX_ROOT="${value}" ;;
      nginx_available_path) NGINX_AVAILABLE="${value}" ;;
      nginx_enabled_path) NGINX_ENABLED="${value}" ;;
      command_timeout_seconds) COMMAND_TIMEOUT_SECONDS="${value}" ;;
      legacy_user) LEGACY_USER="${value}" ;;
      legacy_socket) LEGACY_SOCKET="${value}" ;;
      legacy_container) LEGACY_CONTAINER="${value}" ;;
      freeze_lock_container) FREEZE_LOCK_CONTAINER="${value}" ;;
      old_upstream) OLD_UPSTREAM="${value}" ;;
      new_upstream) NEW_UPSTREAM="${value}" ;;
      new_health_url) NEW_HEALTH_URL="${value}" ;;
      *) fatal ;;
    esac
  done <"${config_path}"
  [[ "${#seen[@]}" -eq 25 ]] || fatal
  [[ "${CONFIG_SCHEMA_VALUE:-}" == "${CONFIG_SCHEMA}" ]] || fatal
  for value in "${STATE_ROOT:-}" "${NGINX_ROOT:-}" "${NGINX_AVAILABLE:-}" "${NGINX_ENABLED:-}"; do
    valid_path_value "${value}" || fatal
  done
  [[ "${COMMAND_TIMEOUT_SECONDS:-}" =~ ^[1-9][0-9]?$|^120$ ]] || fatal
  [[ "${LEGACY_USER:-}" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fatal
  valid_path_value "${LEGACY_SOCKET:-}" || fatal
  [[ "${LEGACY_CONTAINER:-}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || fatal
  [[ "${FREEZE_LOCK_CONTAINER:-}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] || fatal
  [[ "${LEGACY_CONTAINER}" != "${FREEZE_LOCK_CONTAINER}" ]] || fatal
  [[ "${OLD_UPSTREAM:-}" =~ ^http://127\.0\.0\.1:[1-9][0-9]{0,4}/$ ]] || fatal
  [[ "${NEW_UPSTREAM:-}" =~ ^http://(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}):[1-9][0-9]{0,4}/$ ]] || fatal
  [[ "${NEW_HEALTH_URL:-}" == "${NEW_UPSTREAM%/}/healthz" ]] || fatal
  local old_port new_port
  old_port=${OLD_UPSTREAM%/}
  old_port=${old_port##*:}
  new_port=${NEW_UPSTREAM%/}
  new_port=${new_port##*:}
  (( old_port <= 65535 && new_port <= 65535 )) || fatal
  for value in "${RUNUSER_PATH:-}" "${DOCKER_PATH:-}" "${KUBECTL_PATH:-}" \
    "${CURL_PATH:-}" "${NGINX_PATH:-}" "${SYSTEMCTL_PATH:-}" "${PYTHON_PATH:-}"; do
    require_binary "${value}"
  done
  [[ "${NGINX_UNIT:-}" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || fatal
  [[ "${KUBE_CONTEXT:-}" =~ ^[A-Za-z0-9_.@:-]{1,128}$ ]] || fatal
  [[ "${NEW_NAMESPACE:-}" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || fatal
  [[ "${NEW_DEPLOYMENT:-}" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || fatal
  [[ "${NEW_EXPECTED_REPLICAS:-}" =~ ^[1-9][0-9]?$ ]] || fatal
  path_within "${NGINX_ROOT}" "${NGINX_AVAILABLE}" || fatal
  path_within "${NGINX_ROOT}" "${NGINX_ENABLED}" || fatal
  [[ "${NGINX_AVAILABLE}" != "${NGINX_ENABLED}" ]] || fatal
}

run_quiet() {
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" "$@" \
    </dev/null >/dev/null 2>&1 || fatal
}

capture_command() {
  local output
  output=$(timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "$@" </dev/null 2>/dev/null) || fatal
  [[ "${#output}" -le 128 && "${output}" != *$'\n'* ]] || fatal
  printf '%s\n' "${output}"
}

legacy_state() {
  local value
  value=$(capture_command "${RUNUSER_PATH}" -u "${LEGACY_USER}" -- \
    "${DOCKER_PATH}" --host "unix://${LEGACY_SOCKET}" inspect \
    --format '{{.State.Running}}' "${LEGACY_CONTAINER}")
  case "${value}" in true) echo running ;; false) echo stopped ;; *) fatal ;; esac
}

freeze_lock_state() {
  local value
  value=$(capture_command "${RUNUSER_PATH}" -u "${LEGACY_USER}" -- \
    "${DOCKER_PATH}" --host "unix://${LEGACY_SOCKET}" inspect \
    --format '{{.State.Running}}' "${FREEZE_LOCK_CONTAINER}")
  case "${value}" in true) echo running ;; false) echo stopped ;; *) fatal ;; esac
}

new_replicas() {
  local value
  value=$(capture_command "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" \
    -n "${NEW_NAMESPACE}" get deployment "${NEW_DEPLOYMENT}" \
    -o 'jsonpath={.spec.replicas}')
  [[ "${value}" =~ ^[0-9]+$ ]] || fatal
  printf '%s\n' "${value}"
}

new_available_replicas() {
  local value
  value=$(capture_command "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" \
    -n "${NEW_NAMESPACE}" get deployment "${NEW_DEPLOYMENT}" \
    -o 'jsonpath={.status.availableReplicas}')
  [[ -z "${value}" ]] && value=0
  [[ "${value}" =~ ^[0-9]+$ ]] || fatal
  printf '%s\n' "${value}"
}

probe_new_health() {
  run_quiet "${CURL_PATH}" --fail --silent --show-error --output /dev/null \
    --max-time 10 "${NEW_HEALTH_URL}"
}

wait_new_replicas() {
  local desired="$1" attempt
  if [[ "${desired}" -gt 0 ]]; then
    run_quiet "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${NEW_NAMESPACE}" \
      rollout status "deployment/${NEW_DEPLOYMENT}" \
      "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
    [[ "$(new_replicas)" == "${desired}" ]] || fatal
    [[ "$(new_available_replicas)" == "${desired}" ]] || fatal
    probe_new_health
    return 0
  fi
  for attempt in $(seq 1 "${COMMAND_TIMEOUT_SECONDS}"); do
    if [[ "$(new_replicas)" == 0 && "$(new_available_replicas)" == 0 ]]; then
      return 0
    fi
    sleep 1
  done
  fatal
}

set_new_replicas() {
  local desired="$1"
  [[ "${desired}" =~ ^[0-9]+$ ]] || fatal
  if [[ "$(new_replicas)" != "${desired}" ]]; then
    run_quiet "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${NEW_NAMESPACE}" \
      scale "deployment/${NEW_DEPLOYMENT}" "--replicas=${desired}"
  fi
  wait_new_replicas "${desired}"
}

set_legacy_state() {
  local desired="$1" current
  current=$(legacy_state)
  [[ "${current}" == "${desired}" ]] && return 0
  case "${desired}" in
    running)
      run_quiet "${RUNUSER_PATH}" -u "${LEGACY_USER}" -- "${DOCKER_PATH}" \
        --host "unix://${LEGACY_SOCKET}" start "${LEGACY_CONTAINER}"
      ;;
    stopped)
      run_quiet "${RUNUSER_PATH}" -u "${LEGACY_USER}" -- "${DOCKER_PATH}" \
        --host "unix://${LEGACY_SOCKET}" stop --time 30 "${LEGACY_CONTAINER}"
      ;;
    *) fatal ;;
  esac
  [[ "$(legacy_state)" == "${desired}" ]] || fatal
}

new_state() {
  local replicas available
  replicas=$(new_replicas)
  available=$(new_available_replicas)
  if [[ "${replicas}" == 0 && "${available}" == 0 ]]; then
    echo stopped
  elif [[ "${replicas}" == "${NEW_EXPECTED_REPLICAS}" && "${available}" == "${replicas}" ]]; then
    probe_new_health
    echo running
  else
    fatal
  fi
}

private_write() {
  local path="$1"
  local temporary="${path}.tmp.$$"
  umask 077
  cat >"${temporary}"
  chmod 600 "${temporary}"
  sync "${temporary}"
  mv -f -- "${temporary}" "${path}"
  sync "${path}"
}

field() {
  local key="$1" value count
  count=$(grep -c "^${key}=" "${PRESTATE}" || true)
  [[ "${count}" -eq 1 ]] || fatal
  value=$(sed -n "s/^${key}=//p" "${PRESTATE}")
  [[ -n "${value}" ]] || fatal
  printf '%s\n' "${value}"
}

record_operation() {
  local operation="$1" status="$2"
  printf '%s\n' "${status}" | private_write "${RUN_ROOT}/${operation}.state"
}

operation_status() {
  local path="${RUN_ROOT}/$1.state"
  [[ -f "${path}" && ! -L "${path}" ]] || return 1
  [[ "$(stat -c '%a' -- "${path}")" == "600" ]] || fatal
  local value
  value=$(<"${path}")
  [[ "${value}" == "pending" || "${value}" == "complete" ]] || fatal
  printf '%s\n' "${value}"
}

capture_nginx_state() {
  local available_state available_sha available_mode available_uid available_gid
  if [[ -e "${NGINX_AVAILABLE}" || -L "${NGINX_AVAILABLE}" ]]; then
    [[ -f "${NGINX_AVAILABLE}" && ! -L "${NGINX_AVAILABLE}" ]] || fatal
    available_state=file
    available_sha=$(sha256sum -- "${NGINX_AVAILABLE}" | cut -d' ' -f1)
    available_mode=$(stat -c '%a' -- "${NGINX_AVAILABLE}")
    available_uid=$(stat -c '%u' -- "${NGINX_AVAILABLE}")
    available_gid=$(stat -c '%g' -- "${NGINX_AVAILABLE}")
    cp --reflink=auto --preserve=all -- "${NGINX_AVAILABLE}" "${NGINX_BACKUP}"
    chmod 600 "${NGINX_BACKUP}"
  else
    available_state=absent
    available_sha=absent
    available_mode=absent
    available_uid=absent
    available_gid=absent
  fi

  local enabled_state enabled_target
  if [[ -L "${NGINX_ENABLED}" ]]; then
    enabled_state=symlink
    enabled_target=$(readlink -- "${NGINX_ENABLED}")
    [[ -n "${enabled_target}" && "${enabled_target}" != *$'\n'* ]] || fatal
  elif [[ -e "${NGINX_ENABLED}" ]]; then
    fatal
  else
    enabled_state=absent
    enabled_target=absent
  fi

  {
    printf 'schema=solidstats-memory-remote-cutover-prestate/v1\n'
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    printf 'legacy_state=%s\n' "$(legacy_state)"
    printf 'freeze_lock_state=%s\n' "$(freeze_lock_state)"
    printf 'new_state=%s\n' "$(new_state)"
    printf 'new_replicas=%s\n' "$(new_replicas)"
    printf 'new_available_replicas=%s\n' "$(new_available_replicas)"
    printf 'available_state=%s\n' "${available_state}"
    printf 'available_sha256=%s\n' "${available_sha}"
    printf 'available_mode=%s\n' "${available_mode}"
    printf 'available_uid=%s\n' "${available_uid}"
    printf 'available_gid=%s\n' "${available_gid}"
    printf 'enabled_state=%s\n' "${enabled_state}"
    printf 'enabled_target=%s\n' "${enabled_target}"
  } | private_write "${PRESTATE}"
  sha256sum -- "${PRESTATE}" | cut -d' ' -f1 | private_write "${PRESTATE_SHA}"
}

validate_prestate() {
  require_regular_private_file "${PRESTATE}"
  require_regular_private_file "${PRESTATE_SHA}"
  [[ "$(sha256sum -- "${PRESTATE}" | cut -d' ' -f1)" == "$(<"${PRESTATE_SHA}")" ]] || fatal
  [[ "$(field schema)" == "solidstats-memory-remote-cutover-prestate/v1" ]] || fatal
  [[ "$(field config_sha256)" == "${CONFIG_SHA256}" ]] || fatal
  [[ "$(field legacy_state)" =~ ^(running|stopped)$ ]] || fatal
  [[ "$(field freeze_lock_state)" =~ ^(running|stopped)$ ]] || fatal
  [[ "$(field new_state)" =~ ^(running|stopped)$ ]] || fatal
  [[ "$(field new_replicas)" =~ ^[0-9]+$ ]] || fatal
  [[ "$(field new_available_replicas)" =~ ^[0-9]+$ ]] || fatal
  [[ "$(field new_replicas)" == 0 || "$(field new_replicas)" == "${NEW_EXPECTED_REPLICAS}" ]] || fatal
  [[ "$(field available_state)" =~ ^(file|absent)$ ]] || fatal
  [[ "$(field enabled_state)" =~ ^(symlink|absent)$ ]] || fatal
  if [[ "$(field available_state)" == file ]]; then
    require_regular_private_file "${NGINX_BACKUP}"
    [[ "$(sha256sum -- "${NGINX_BACKUP}" | cut -d' ' -f1)" == "$(field available_sha256)" ]] || fatal
    [[ "$(field available_mode)" =~ ^[0-7]{3,4}$ ]] || fatal
    [[ "$(field available_uid)" =~ ^[0-9]+$ && "$(field available_gid)" =~ ^[0-9]+$ ]] || fatal
  fi
}

current_available_matches_prestate() {
  if [[ "$(field available_state)" == absent ]]; then
    [[ ! -e "${NGINX_AVAILABLE}" && ! -L "${NGINX_AVAILABLE}" ]]
  else
    [[ -f "${NGINX_AVAILABLE}" && ! -L "${NGINX_AVAILABLE}" ]] &&
      [[ "$(sha256sum -- "${NGINX_AVAILABLE}" | cut -d' ' -f1)" == "$(field available_sha256)" ]] &&
      [[ "$(stat -c '%a' -- "${NGINX_AVAILABLE}")" == "$(field available_mode)" ]] &&
      [[ "$(stat -c '%u' -- "${NGINX_AVAILABLE}")" == "$(field available_uid)" ]] &&
      [[ "$(stat -c '%g' -- "${NGINX_AVAILABLE}")" == "$(field available_gid)" ]]
  fi
}

current_enabled_matches_prestate() {
  if [[ "$(field enabled_state)" == absent ]]; then
    [[ ! -e "${NGINX_ENABLED}" && ! -L "${NGINX_ENABLED}" ]]
  else
    [[ -L "${NGINX_ENABLED}" && "$(readlink -- "${NGINX_ENABLED}")" == "$(field enabled_target)" ]]
  fi
}

capture_prestate() {
  if [[ -f "${PRESTATE}" ]]; then
    validate_prestate
    [[ "$(operation_status capture-prestate)" == complete ]] || fatal
    return 0
  fi
  [[ ! -e "${PRESTATE}" && ! -L "${PRESTATE}" ]] || fatal
  record_operation capture-prestate pending
  capture_nginx_state
  record_operation capture-prestate complete
}

transition_runtime() {
  local operation="$1" desired_legacy="$2" desired_new_replicas="$3"
  validate_prestate
  local status=""
  status=$(operation_status "${operation}" 2>/dev/null || true)
  if [[ "${status}" == complete ]]; then
    [[ "$(legacy_state)" == "${desired_legacy}" ]] || fatal
    [[ "$(new_replicas)" == "${desired_new_replicas}" ]] || fatal
    [[ "$(new_available_replicas)" == "${desired_new_replicas}" ]] || fatal
    [[ "$(freeze_lock_state)" == "$(field freeze_lock_state)" ]] || fatal
    return 0
  fi
  if [[ -z "${status}" ]]; then
    [[ "$(legacy_state)" == "$(field legacy_state)" ]] || fatal
    [[ "$(new_state)" == "$(field new_state)" ]] || fatal
    [[ "$(new_replicas)" == "$(field new_replicas)" ]] || fatal
    [[ "$(new_available_replicas)" == "$(field new_available_replicas)" ]] || fatal
    [[ "$(freeze_lock_state)" == "$(field freeze_lock_state)" ]] || fatal
    record_operation "${operation}" pending
  fi
  set_legacy_state "${desired_legacy}"
  set_new_replicas "${desired_new_replicas}"
  [[ "$(freeze_lock_state)" == "$(field freeze_lock_state)" ]] || fatal
  record_operation "${operation}" complete
}

receive_patch_descriptor() {
  local temporary="${RUN_ROOT}/nginx-template.tmp.$$"
  umask 077
  dd if=/dev/stdin of="${temporary}" bs=$((MAX_NGINX_BYTES + 1)) count=1 status=none
  [[ -s "${temporary}" && "$(stat -c '%s' -- "${temporary}")" -le "${MAX_NGINX_BYTES}" ]] || fatal
  local expected="${RUN_ROOT}/nginx-template.expected"
  {
    printf 'schema=solidstats-memory-nginx-patch/v1\n'
    printf 'public_port=8443\n'
    printf 'public_location=/solidstats/\n'
    printf 'old_upstream=MEMORY_OPERATOR_BOUND_OLD_UPSTREAM_ROOT_WITH_TRAILING_SLASH\n'
    printf 'new_upstream=MEMORY_OPERATOR_BOUND_NEW_UPSTREAM_ROOT_WITH_TRAILING_SLASH\n'
  } | private_write "${expected}"
  cmp -s -- "${temporary}" "${expected}" || fatal
  chmod 600 "${temporary}"
  mv -f -- "${temporary}" "${NGINX_TEMPLATE_COPY}"
  {
    printf 'schema=solidstats-memory-nginx-patch/v1\n'
    printf 'public_port=8443\n'
    printf 'public_location=/solidstats/\n'
    printf 'old_upstream=%s\n' "${OLD_UPSTREAM}"
    printf 'new_upstream=%s\n' "${NEW_UPSTREAM}"
  } | private_write "${NGINX_PATCH}"
  chmod 600 "${NGINX_PATCH}"
  rm -f -- "${NGINX_CANDIDATE}"
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${PYTHON_PATH}" "${NGINX_RENDERER}" "${NGINX_BACKUP}" "${NGINX_PATCH}" \
    "${NGINX_CANDIDATE}" </dev/null >/dev/null 2>&1 || fatal
  require_regular_private_file "${NGINX_CANDIDATE}"
  sha256sum -- "${NGINX_CANDIDATE}" | cut -d' ' -f1 | private_write "${NGINX_CANDIDATE_SHA}"
}

installed_nginx_matches() {
  [[ -f "${NGINX_AVAILABLE}" && ! -L "${NGINX_AVAILABLE}" ]] &&
    [[ "$(sha256sum -- "${NGINX_AVAILABLE}" | cut -d' ' -f1)" == "$(<"${NGINX_CANDIDATE_SHA}")" ]] &&
    [[ "$(stat -c '%a' -- "${NGINX_AVAILABLE}")" == "$(field available_mode)" ]] &&
    [[ "$(stat -c '%u' -- "${NGINX_AVAILABLE}")" == "$(field available_uid)" ]] &&
    [[ "$(stat -c '%g' -- "${NGINX_AVAILABLE}")" == "$(field available_gid)" ]] &&
    current_enabled_matches_prestate
}

atomic_install_candidate() {
  local available_tmp
  available_tmp=$(mktemp "${NGINX_AVAILABLE}.tmp.XXXXXX")
  install -o "$(field available_uid)" -g "$(field available_gid)" \
    -m "$(field available_mode)" -- \
    "${NGINX_CANDIDATE}" "${available_tmp}"
  mv -f -- "${available_tmp}" "${NGINX_AVAILABLE}"
}

install_nginx() {
  validate_prestate
  local status=""
  status=$(operation_status install-nginx 2>/dev/null || true)
  receive_patch_descriptor
  if [[ "${status}" == complete ]]; then
    require_regular_private_file "${NGINX_CANDIDATE}"
    require_regular_private_file "${NGINX_CANDIDATE_SHA}"
    installed_nginx_matches || fatal
    run_quiet "${NGINX_PATH}" -t
    return 0
  fi
  if [[ -z "${status}" ]]; then
    [[ "$(field available_state)" == file ]] || fatal
    current_available_matches_prestate || fatal
    current_enabled_matches_prestate || fatal
    record_operation install-nginx pending
  else
    require_regular_private_file "${NGINX_CANDIDATE}"
    require_regular_private_file "${NGINX_CANDIDATE_SHA}"
  fi
  if ! installed_nginx_matches; then
    atomic_install_candidate
  fi
  run_quiet "${NGINX_PATH}" -t
  run_quiet "${SYSTEMCTL_PATH}" reload "${NGINX_UNIT}"
  installed_nginx_matches || fatal
  record_operation install-nginx complete
}

restore_available_prestate() {
  if [[ "$(field available_state)" == absent ]]; then
    [[ ! -d "${NGINX_AVAILABLE}" ]] || fatal
    rm -f -- "${NGINX_AVAILABLE}"
  else
    local temporary
    temporary=$(mktemp "${NGINX_AVAILABLE}.rollback.XXXXXX")
    install -o "$(field available_uid)" -g "$(field available_gid)" \
      -m "$(field available_mode)" -- "${NGINX_BACKUP}" "${temporary}"
    mv -f -- "${temporary}" "${NGINX_AVAILABLE}"
  fi
}

restore_enabled_prestate() {
  if [[ "$(field enabled_state)" == absent ]]; then
    [[ ! -d "${NGINX_ENABLED}" ]] || fatal
    rm -f -- "${NGINX_ENABLED}"
  else
    local temporary
    temporary="${NGINX_ENABLED}.rollback.$$"
    [[ ! -e "${temporary}" && ! -L "${temporary}" ]] || fatal
    ln -s -- "$(field enabled_target)" "${temporary}"
    mv -Tf -- "${temporary}" "${NGINX_ENABLED}"
  fi
}

restore_runtime_component() {
  local operation="$1" component="$2" desired="$3" current
  validate_prestate
  local status=""
  status=$(operation_status "${operation}" 2>/dev/null || true)
  if [[ "${status}" == complete ]]; then
    if [[ "${component}" == legacy ]]; then
      current=$(legacy_state)
      [[ "${current}" == "${desired}" ]] || fatal
    else
      [[ "$(new_replicas)" == "${desired}" ]] || fatal
      [[ "$(new_available_replicas)" == "${desired}" ]] || fatal
    fi
    [[ "$(freeze_lock_state)" == "$(field freeze_lock_state)" ]] || fatal
    return 0
  fi
  if [[ -z "${status}" ]]; then
    record_operation "${operation}" pending
  fi
  if [[ "${component}" == legacy ]]; then
    set_legacy_state "${desired}"
  else
    set_new_replicas "${desired}"
  fi
  [[ "$(freeze_lock_state)" == "$(field freeze_lock_state)" ]] || fatal
  record_operation "${operation}" complete
}

rollback_nginx() {
  validate_prestate
  local status=""
  status=$(operation_status rollback-nginx 2>/dev/null || true)
  if [[ "${status}" == complete ]]; then
    current_available_matches_prestate || fatal
    current_enabled_matches_prestate || fatal
    run_quiet "${NGINX_PATH}" -t
    return 0
  fi
  if [[ -z "${status}" ]]; then
    local install_status=""
    install_status=$(operation_status install-nginx 2>/dev/null || true)
    if [[ "${install_status}" == pending || "${install_status}" == complete ]]; then
      if ! installed_nginx_matches; then
        current_available_matches_prestate || fatal
        current_enabled_matches_prestate || fatal
      fi
    else
      current_available_matches_prestate || fatal
      current_enabled_matches_prestate || fatal
    fi
    record_operation rollback-nginx pending
  fi
  restore_available_prestate
  restore_enabled_prestate
  run_quiet "${NGINX_PATH}" -t
  run_quiet "${SYSTEMCTL_PATH}" reload "${NGINX_UNIT}"
  current_available_matches_prestate || fatal
  current_enabled_matches_prestate || fatal
  record_operation rollback-nginx complete
}

main() {
  [[ "$#" -eq 2 ]] || usage
  local operation="$1" run_id_sha256="$2"
  case "${operation}" in
    capture-prestate|stop-legacy-start-new|install-nginx|rollback-nginx|stop-new|start-legacy) ;;
    *) usage ;;
  esac
  [[ "${run_id_sha256}" =~ ^[0-9a-f]{64}$ ]] || usage
  local script_path config_path
  script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
  [[ -f "${script_path}" && ! -L "${script_path}" ]] || fatal
  config_path="${script_path}.config"
  load_config "${config_path}"
  CONFIG_SHA256=$(sha256sum -- "${config_path}" | cut -d' ' -f1)
  umask 077
  mkdir -p -m 700 -- "${STATE_ROOT}"
  [[ -d "${STATE_ROOT}" && ! -L "${STATE_ROOT}" ]] || fatal
  chmod 700 -- "${STATE_ROOT}"
  RUN_ROOT="${STATE_ROOT}/${run_id_sha256}"
  mkdir -p -m 700 -- "${RUN_ROOT}"
  [[ -d "${RUN_ROOT}" && ! -L "${RUN_ROOT}" ]] || fatal
  chmod 700 -- "${RUN_ROOT}"
  PRESTATE="${RUN_ROOT}/prestate"
  PRESTATE_SHA="${RUN_ROOT}/prestate.sha256"
  NGINX_BACKUP="${RUN_ROOT}/nginx.available.backup"
  NGINX_CANDIDATE="${RUN_ROOT}/nginx.candidate"
  NGINX_CANDIDATE_SHA="${RUN_ROOT}/nginx.candidate.sha256"
  NGINX_PATCH="${RUN_ROOT}/nginx.patch"
  NGINX_TEMPLATE_COPY="${RUN_ROOT}/nginx.patch.template"
  SCRIPT_DIR=$(dirname "${script_path}")
  NGINX_RENDERER="${SCRIPT_DIR}/render-solidstats-memory-shared-nginx.py"
  require_binary "${NGINX_RENDERER}"

  if [[ "${operation}" != capture-prestate ]]; then
    validate_prestate
  fi
  case "${operation}" in
    capture-prestate) capture_prestate ;;
    stop-legacy-start-new) transition_runtime "${operation}" stopped "${NEW_EXPECTED_REPLICAS}" ;;
    install-nginx) install_nginx ;;
    rollback-nginx) rollback_nginx ;;
    stop-new) restore_runtime_component "${operation}" new "$(field new_replicas)" ;;
    start-legacy) restore_runtime_component "${operation}" legacy "$(field legacy_state)" ;;
  esac
  echo "PASS: remote cutover boundary acknowledged"
}

main "$@"
