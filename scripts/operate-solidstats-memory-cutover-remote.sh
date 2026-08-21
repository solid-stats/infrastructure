#!/usr/bin/env bash
set -Eeuo pipefail

# Host-side half of the Phase 21 memory cutover. The local orchestrator invokes
# one allowlisted operation per SSH batch. All private paths and command paths come
# from a root-owned, mode-0600 config; the file is parsed as data, never sourced.

readonly CONFIG_SCHEMA="solidstats-memory-remote-cutover-config/v1"
readonly MAX_NGINX_BYTES=1048576
readonly MEMORY_NAMESPACE="solidstats-memory"
readonly MEMORY_DEPLOYMENT="mempalace"
readonly QDRANT_STATEFULSET="qdrant"
readonly BACKUP_CRONJOB="solidstats-memory-backup"
readonly BACKUP_SERVICE_ACCOUNT="solidstats-memory-backup"
readonly DENIED_SERVICE_ACCOUNT="solidstats-memory-backup-probe-denied"
readonly BOOT_ID_PATH="/proc/sys/kernel/random/boot_id"

fatal() {
  echo "FATAL: remote cutover operation failed closed" >&2
  exit 1
}

usage() {
  echo "usage: operate-solidstats-memory-cutover-remote.sh OPERATION RUN_ID_SHA256 [RECONNECT_TIMEOUT]" >&2
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
  [[ "${NEW_NAMESPACE}" == "${MEMORY_NAMESPACE}" ]] || fatal
  [[ "${NEW_DEPLOYMENT}" == "${MEMORY_DEPLOYMENT}" ]] || fatal
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

kube_quiet() {
  run_quiet "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" \
    -n "${MEMORY_NAMESPACE}" "$@"
}

kube_value() {
  capture_command "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" \
    -n "${MEMORY_NAMESPACE}" "$@"
}

result_field() {
  local path="$1" key="$2" value count
  require_regular_private_file "${path}"
  count=$(grep -c "^${key}=" "${path}" || true)
  [[ "${count}" -eq 1 ]] || fatal
  value=$(sed -n "s/^${key}=//p" "${path}")
  [[ -n "${value}" ]] || fatal
  printf '%s\n' "${value}"
}

write_result() {
  local operation="$1"
  shift
  local item
  {
    printf 'schema=solidstats-memory-remote-operation-result/v1\n'
    printf 'operation=%s\n' "${operation}"
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    for item in "$@"; do
      [[ "${item}" =~ ^[a-z][a-z0-9_]{0,63}=(true|false|[0-9]+|[0-9a-f]{64}|service|endpoint)$ ]] || fatal
      printf '%s\n' "${item}"
    done
  } | private_write "${RUN_ROOT}/${operation}.result"
}

require_operation_complete() {
  [[ "$(operation_status "$1")" == complete ]] || fatal
  require_regular_private_file "${RUN_ROOT}/$1.result"
  [[ "$(result_field "${RUN_ROOT}/$1.result" config_sha256)" == "${CONFIG_SHA256}" ]] || fatal
}

resource_identity() {
  local selector="$1" value
  [[ "${selector}" == "mempalace" || "${selector}" == "qdrant" ]] || fatal
  value=$(kube_value get pods -l "app.kubernetes.io/name=${selector}" \
    -o 'jsonpath={range .items[*]}{.metadata.uid}{"\n"}{end}')
  [[ -n "${value}" ]] || fatal
  printf '%s' "${value}" | sha256sum | cut -d' ' -f1
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

restart_workload() {
  local operation="$1" kind="$2" name="$3" selector="$4" before after
  local status=""
  status=$(operation_status "${operation}" 2>/dev/null || true)
  if [[ "${status}" == complete ]]; then
    require_operation_complete "${operation}"
    return 0
  fi
  [[ -z "${status}" ]] || fatal
  before=$(resource_identity "${selector}")
  record_operation "${operation}" pending
  kube_quiet rollout restart "${kind}/${name}"
  kube_quiet rollout status "${kind}/${name}" \
    "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
  after=$(resource_identity "${selector}")
  [[ "${before}" != "${after}" ]] || fatal
  write_result "${operation}" \
    "identity_changed=true" "before_sha256=${before}" "after_sha256=${after}"
  record_operation "${operation}" complete
}

backup_schedule_state() {
  local value
  value=$(kube_value get cronjob "${BACKUP_CRONJOB}" \
    -o 'jsonpath={.spec.suspend}:{.spec.concurrencyPolicy}')
  [[ "${value}" == "true:Forbid" || "${value}" == "false:Forbid" ]] || fatal
  printf '%s\n' "${value}"
}

set_backup_schedule() {
  local operation="$1" desired="$2"
  [[ "${desired}" == true || "${desired}" == false ]] || fatal
  if [[ "$(operation_status "${operation}" 2>/dev/null || true)" == complete ]]; then
    [[ "$(backup_schedule_state)" == "${desired}:Forbid" ]] || fatal
    require_operation_complete "${operation}"
    return 0
  fi
  record_operation "${operation}" pending
  kube_quiet patch cronjob "${BACKUP_CRONJOB}" --type=merge \
    -p "{\"spec\":{\"suspend\":${desired}}}"
  [[ "$(backup_schedule_state)" == "${desired}:Forbid" ]] || fatal
  write_result "${operation}" "schedule_suspended=${desired}" \
    "concurrency_forbid=true"
  record_operation "${operation}" complete
}

capture_boot_identity() {
  if [[ "$(operation_status capture-boot-identity 2>/dev/null || true)" == complete ]]; then
    require_regular_private_file "${RUN_ROOT}/boot-before.sha256"
    require_operation_complete capture-boot-identity
    return 0
  fi
  [[ -r "${BOOT_ID_PATH}" && -f "${BOOT_ID_PATH}" && ! -L "${BOOT_ID_PATH}" ]] || fatal
  local digest
  digest=$(sha256sum -- "${BOOT_ID_PATH}" | cut -d' ' -f1)
  [[ "${digest}" =~ ^[0-9a-f]{64}$ ]] || fatal
  printf '%s\n' "${digest}" | private_write "${RUN_ROOT}/boot-before.sha256"
  write_result capture-boot-identity "boot_identity_recorded=true" \
    "boot_sha256=${digest}"
  record_operation capture-boot-identity complete
}

request_reboot() {
  require_operation_complete capture-boot-identity
  local before current status
  before=$(<"${RUN_ROOT}/boot-before.sha256")
  current=$(sha256sum -- "${BOOT_ID_PATH}" | cut -d' ' -f1)
  status=$(operation_status reboot-host 2>/dev/null || true)
  if [[ "${status}" == complete ]]; then
    [[ "${current}" != "${before}" ]] || fatal
    return 0
  fi
  if [[ "${status}" == pending ]]; then
    if [[ "${current}" != "${before}" ]]; then
      write_result reboot-host "reboot_requested=true" \
        "boot_identity_changed=true"
      record_operation reboot-host complete
      return 0
    fi
    fatal
  fi
  [[ -z "${status}" && "${current}" == "${before}" ]] || fatal
  record_operation reboot-host pending
  run_quiet "${SYSTEMCTL_PATH}" --no-block reboot
}

verify_reboot_recovery() {
  local reconnect_timeout="$1" before current pvc_states
  [[ "${reconnect_timeout}" =~ ^[1-9][0-9]{0,3}$ ]] || fatal
  (( reconnect_timeout <= 9999 )) || fatal
  require_operation_complete capture-boot-identity
  before=$(<"${RUN_ROOT}/boot-before.sha256")
  current=$(sha256sum -- "${BOOT_ID_PATH}" | cut -d' ' -f1)
  [[ "${current}" != "${before}" ]] || fatal
  if [[ "$(operation_status reboot-host 2>/dev/null || true)" == pending ]]; then
    write_result reboot-host "reboot_requested=true" \
      "boot_identity_changed=true"
    record_operation reboot-host complete
  else
    require_operation_complete reboot-host
  fi
  kube_quiet wait --for=condition=Ready nodes --all \
    "--timeout=${reconnect_timeout}s"
  pvc_states=$(kube_value get pvc \
    -o 'jsonpath={range .items[*]}{.status.phase}{" "}{end}')
  [[ "${pvc_states}" =~ ^(Bound[[:space:]]+)+$ ]] || fatal
  kube_quiet rollout status "statefulset/${QDRANT_STATEFULSET}" \
    "--timeout=${reconnect_timeout}s"
  wait_new_replicas "${NEW_EXPECTED_REPLICAS}"
  run_quiet "${SYSTEMCTL_PATH}" is-active --quiet "${NGINX_UNIT}"
  write_result verify-reboot-recovery \
    "boot_identity_changed=true" "node_ready=true" "pvc_bound=true" \
    "qdrant_ready=true" "mempalace_available=true" "nginx_active=true" \
    "reconnect_timeout_seconds=${reconnect_timeout}"
  record_operation verify-reboot-recovery complete
}

verify_legacy_behavior() {
  [[ "$(legacy_state)" == running ]] || fatal
  [[ "$(new_replicas)" == "$(field new_replicas)" ]] || fatal
  current_available_matches_prestate || fatal
  current_enabled_matches_prestate || fatal
  write_result verify-legacy-behavior \
    "legacy_running=true" "new_prestate_restored=true" \
    "nginx_prestate_restored=true"
  record_operation verify-legacy-behavior complete
}

verify_retained_collections() {
  kube_quiet rollout status "statefulset/${QDRANT_STATEFULSET}" \
    "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
  [[ "$(new_replicas)" == "${NEW_EXPECTED_REPLICAS}" ]] || fatal
  write_result verify-retained-collections \
    "qdrant_ready=true" "mempalace_available=true" \
    "destructive_collection_calls=0"
  record_operation verify-retained-collections complete
}

capture_kube_json() {
  local destination="$1"
  shift
  local temporary="${destination}.tmp.$$"
  umask 077
  if ! timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" "$@" \
    >"${temporary}" 2>/dev/null; then
    rm -f -- "${temporary}"
    fatal
  fi
  [[ -s "${temporary}" && "$(stat -c '%s' -- "${temporary}")" -le 1048576 ]] || {
    rm -f -- "${temporary}"
    fatal
  }
  chmod 600 "${temporary}"
  mv -f -- "${temporary}" "${destination}"
}

discover_api_candidates() {
  local service_json="${RUN_ROOT}/api-service.json"
  local endpoints_json="${RUN_ROOT}/api-endpoints.json"
  local candidates="${RUN_ROOT}/api-candidates"
  capture_kube_json "${service_json}" -n default get service kubernetes -o json
  capture_kube_json "${endpoints_json}" -n default get endpointslices \
    -l kubernetes.io/service-name=kubernetes -o json
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${PYTHON_PATH}" -c '
import ipaddress, json, pathlib, sys
service = json.loads(pathlib.Path(sys.argv[1]).read_text())
slices = json.loads(pathlib.Path(sys.argv[2]).read_text())
rows = []
address = ipaddress.ip_address(service["spec"]["clusterIP"])
ports = [item["port"] for item in service["spec"]["ports"] if item.get("name") == "https"]
if len(ports) != 1:
    raise SystemExit(1)
rows.append(("service", f"{address}/{address.max_prefixlen}", int(ports[0])))
for item in slices.get("items", []):
    item_ports = [entry["port"] for entry in item.get("ports", []) if entry.get("name") == "https"]
    if len(item_ports) != 1:
        continue
    for endpoint in item.get("endpoints", []):
        if endpoint.get("conditions", {}).get("ready") is not True:
            continue
        for raw in endpoint.get("addresses", []):
            address = ipaddress.ip_address(raw)
            rows.append(("endpoint", f"{address}/{address.max_prefixlen}", int(item_ports[0])))
rows = sorted(set(rows))
if len([row for row in rows if row[0] == "service"]) != 1 or not any(row[0] == "endpoint" for row in rows):
    raise SystemExit(1)
path = pathlib.Path(sys.argv[3])
path.write_text("".join(f"{mode} {cidr} {port}\n" for mode, cidr, port in rows))
path.chmod(0o600)
' "${service_json}" "${endpoints_json}" "${candidates}" \
    </dev/null >/dev/null 2>&1 || fatal
  require_regular_private_file "${candidates}"
  rm -f -- "${service_json}" "${endpoints_json}"
}

validate_api_binding_values() {
  local mode="$1" cidr="$2" port="$3"
  [[ "${mode}" == service || "${mode}" == endpoint ]] || fatal
  [[ "${port}" =~ ^[1-9][0-9]{0,4}$ ]] || fatal
  (( port <= 65535 )) || fatal
  printf '%s\n' "${cidr}" | timeout --signal=TERM --kill-after=5s \
    "${COMMAND_TIMEOUT_SECONDS}s" "${PYTHON_PATH}" -c '
import ipaddress, sys
network = ipaddress.ip_network(sys.stdin.read().strip(), strict=True)
if network.prefixlen != network.max_prefixlen:
    raise SystemExit(1)
' >/dev/null 2>&1 || fatal
}

render_api_bootstrap() {
  local mode="$1" cidr="$2" port="$3"
  validate_api_binding_values "${mode}" "${cidr}" "${port}"
  {
    printf '%s\n' \
      'apiVersion: rbac.authorization.k8s.io/v1' \
      'kind: Role' \
      'metadata:' \
      '  name: solidstats-memory-backup' \
      '  namespace: solidstats-memory' \
      'rules:' \
      '  - apiGroups: ["apps"]' \
      '    resources: ["deployments"]' \
      '    resourceNames: ["mempalace"]' \
      '    verbs: ["get"]' \
      '  - apiGroups: ["apps"]' \
      '    resources: ["deployments/scale"]' \
      '    resourceNames: ["mempalace"]' \
      '    verbs: ["get", "patch"]' \
      '  - apiGroups: [""]' \
      '    resources: ["pods"]' \
      '    verbs: ["list"]' \
      '---' \
      'apiVersion: rbac.authorization.k8s.io/v1' \
      'kind: RoleBinding' \
      'metadata:' \
      '  name: solidstats-memory-backup' \
      '  namespace: solidstats-memory' \
      'subjects:' \
      '  - kind: ServiceAccount' \
      '    name: solidstats-memory-backup' \
      '    namespace: solidstats-memory' \
      'roleRef:' \
      '  apiGroup: rbac.authorization.k8s.io' \
      '  kind: Role' \
      '  name: solidstats-memory-backup' \
      '---' \
      'apiVersion: networking.k8s.io/v1' \
      'kind: NetworkPolicy' \
      'metadata:' \
      '  name: allow-backup-to-kubernetes-api' \
      '  namespace: solidstats-memory' \
      'spec:' \
      '  podSelector:' \
      '    matchLabels:' \
      '      app.kubernetes.io/name: solidstats-memory-backup' \
      '  policyTypes: [Egress]' \
      '  egress:' \
      '    - to:' \
      '        - ipBlock:' \
    printf '            cidr: %s\n' "${cidr}"
    printf '%s\n' \
      '      ports:' \
      '        - protocol: TCP'
    printf '          port: %s\n' "${port}"
  } | private_write "${RUN_ROOT}/api-bootstrap.yaml"
}

apply_api_binding() {
  local mode="$1" cidr="$2" port="$3"
  render_api_bootstrap "${mode}" "${cidr}" "${port}"
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" apply \
    -f "${RUN_ROOT}/api-bootstrap.yaml" </dev/null >/dev/null 2>&1 || fatal
}

backup_probe_image() {
  local value
  value=$(timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    get cronjob "${BACKUP_CRONJOB}" \
    -o 'jsonpath={.spec.jobTemplate.spec.template.spec.containers[0].image}' \
    </dev/null 2>/dev/null) || fatal
  [[ "${#value}" -le 512 && "${value}" != *$'\n'* && \
    "${value}" =~ ^[A-Za-z0-9._/:+-]+@sha256:[0-9a-f]{64}$ ]] || fatal
  printf '%s\n' "${value}"
}

render_api_probe_pod() {
  local mode="$1" pod_name="$2" service_account="$3" label="$4" image="$5"
  [[ "${mode}" =~ ^(positive|network-negative|rbac-negative)$ ]] || fatal
  [[ "${pod_name}" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] || fatal
  [[ "${service_account}" == "${BACKUP_SERVICE_ACCOUNT}" || \
    "${service_account}" == "${DENIED_SERVICE_ACCOUNT}" ]] || fatal
  [[ "${label}" == "${BACKUP_CRONJOB}" || "${label}" == "${DENIED_SERVICE_ACCOUNT}" ]] || fatal
  local check
  case "${mode}" in
    positive) check='test "${status}" = 200' ;;
    rbac-negative) check='test "${status}" = 403' ;;
    network-negative) check='test "${status}" = 000' ;;
  esac
  {
    printf '%s\n' \
      'apiVersion: v1' \
      'kind: Pod' \
      'metadata:'
    printf '  name: %s\n' "${pod_name}"
    printf '  namespace: %s\n' "${MEMORY_NAMESPACE}"
    printf '%s\n' '  labels:'
    printf '    app.kubernetes.io/name: %s\n' "${label}"
    printf '%s\n' \
      'spec:' \
      '  restartPolicy: Never'
    printf '  serviceAccountName: %s\n' "${service_account}"
    printf '%s\n' \
      '  automountServiceAccountToken: false' \
      '  containers:' \
      '    - name: probe'
    printf '      image: %s\n' "${image}"
    printf '%s\n' \
      '      command: ["/bin/sh", "-ec"]' \
      '      args:' \
      '        - |' \
      '          api="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT_HTTPS}/apis/apps/v1/namespaces/solidstats-memory/deployments/mempalace/scale"' \
      '          status="$({ printf '\''header = "Authorization: Bearer '\''; cat /var/run/secrets/solidstats-memory/token; printf '\''"\n'\''; } | curl --config - --silent --show-error --output /dev/null --write-out "%{http_code}" --connect-timeout 3 --max-time 8 --cacert /var/run/secrets/solidstats-memory/ca.crt "${api}" || true)"'
    printf '          %s\n' "${check}"
    printf '%s\n' \
      '      securityContext:' \
      '        allowPrivilegeEscalation: false' \
      '        readOnlyRootFilesystem: true' \
      '        capabilities:' \
      '          drop: ["ALL"]' \
      '      resources:' \
      '        requests:' \
      '          cpu: 10m' \
      '          memory: 32Mi' \
      '        limits:' \
      '          cpu: 100m' \
      '          memory: 128Mi' \
      '      volumeMounts:' \
      '        - name: kubernetes-api-access' \
      '          mountPath: /var/run/secrets/solidstats-memory' \
      '          readOnly: true' \
      '  volumes:' \
      '    - name: kubernetes-api-access' \
      '      projected:' \
      '        defaultMode: 0400' \
      '        sources:' \
      '          - serviceAccountToken:' \
      '              path: token' \
      '              expirationSeconds: 600' \
      '          - configMap:' \
      '              name: kube-root-ca.crt' \
      '              items:' \
      '                - key: ca.crt' \
      '                  path: ca.crt'
  } | private_write "${RUN_ROOT}/api-probe-pod.yaml"
}

run_api_control() {
  local mode="$1" suffix image pod_name service_account label status=0
  suffix=$(printf '%s' "${mode}" | tr -cd 'a-z-' | cut -c1-18)
  pod_name="memory-api-${suffix}-${RUN_ID_SHA256:0:8}"
  service_account="${BACKUP_SERVICE_ACCOUNT}"
  label="${BACKUP_CRONJOB}"
  if [[ "${mode}" == network-negative ]]; then
    label="${DENIED_SERVICE_ACCOUNT}"
  elif [[ "${mode}" == rbac-negative ]]; then
    service_account="${DENIED_SERVICE_ACCOUNT}"
  fi
  image=$(backup_probe_image)
  render_api_probe_pod "${mode}" "${pod_name}" "${service_account}" "${label}" "${image}"
  cleanup_api_control() {
    trap - EXIT INT TERM
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
      delete pod "${pod_name}" --ignore-not-found=true --wait=true \
      </dev/null >/dev/null 2>&1 || status=1
    if [[ "${mode}" == rbac-negative ]]; then
      timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
        "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
        delete serviceaccount "${DENIED_SERVICE_ACCOUNT}" \
        --ignore-not-found=true --wait=true </dev/null >/dev/null 2>&1 || status=1
    fi
  }
  trap cleanup_api_control EXIT INT TERM
  if [[ "${mode}" == rbac-negative ]]; then
    {
      printf '%s\n' \
        'apiVersion: v1' \
        'kind: ServiceAccount' \
        'metadata:' \
        '  name: solidstats-memory-backup-probe-denied' \
        '  namespace: solidstats-memory' \
        'automountServiceAccountToken: false'
    } | private_write "${RUN_ROOT}/api-denied-sa.yaml"
    if ! timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" apply \
      -f "${RUN_ROOT}/api-denied-sa.yaml" </dev/null >/dev/null 2>&1; then
      timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
        "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
        delete serviceaccount "${DENIED_SERVICE_ACCOUNT}" \
        --ignore-not-found=true --wait=true </dev/null >/dev/null 2>&1 || true
      fatal
    fi
  fi
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    delete pod "${pod_name}" --ignore-not-found=true --wait=true \
    </dev/null >/dev/null 2>&1 || status=1
  if [[ "${status}" == 0 ]]; then
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" create \
      -f "${RUN_ROOT}/api-probe-pod.yaml" </dev/null >/dev/null 2>&1 || status=1
  fi
  if [[ "${status}" == 0 ]]; then
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
      wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod_name}" \
      "--timeout=${COMMAND_TIMEOUT_SECONDS}s" </dev/null >/dev/null 2>&1 || status=1
  fi
  cleanup_api_control
  return "${status}"
}

read_api_binding() {
  local path="${RUN_ROOT}/api-binding" mode cidr port
  require_regular_private_file "${path}"
  [[ "$(result_field "${path}" schema)" == solidstats-memory-api-binding/v1 ]] || fatal
  [[ "$(result_field "${path}" config_sha256)" == "${CONFIG_SHA256}" ]] || fatal
  mode=$(result_field "${path}" mode)
  cidr=$(result_field "${path}" cidr)
  port=$(result_field "${path}" port)
  validate_api_binding_values "${mode}" "${cidr}" "${port}"
  printf '%s %s %s\n' "${mode}" "${cidr}" "${port}"
}

measure_backup_api_egress() {
  local candidates selected_mode="" selected_cidr="" selected_port=""
  local mode cidr port passing_endpoints=0 candidate_count=0
  if [[ "$(operation_status measure-backup-api-egress 2>/dev/null || true)" == complete ]]; then
    local binding
    binding=$(read_api_binding)
    read -r selected_mode selected_cidr selected_port <<<"${binding}"
    apply_api_binding "${selected_mode}" "${selected_cidr}" "${selected_port}"
    require_operation_complete measure-backup-api-egress
    return 0
  fi
  discover_api_candidates
  candidates="${RUN_ROOT}/api-candidates"
  while read -r mode cidr port; do
    validate_api_binding_values "${mode}" "${cidr}" "${port}"
    candidate_count=$((candidate_count + 1))
    apply_api_binding "${mode}" "${cidr}" "${port}"
    if run_api_control positive; then
      if [[ "${mode}" == service ]]; then
        selected_mode="${mode}"
        selected_cidr="${cidr}"
        selected_port="${port}"
        break
      fi
      passing_endpoints=$((passing_endpoints + 1))
      selected_mode="${mode}"
      selected_cidr="${cidr}"
      selected_port="${port}"
    fi
  done <"${candidates}"
  if [[ -z "${selected_mode}" || \
    ("${selected_mode}" == endpoint && "${passing_endpoints}" -ne 1) ]]; then
    fatal
  fi
  {
    printf 'schema=solidstats-memory-api-binding/v1\n'
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    printf 'mode=%s\n' "${selected_mode}"
    printf 'cidr=%s\n' "${selected_cidr}"
    printf 'port=%s\n' "${selected_port}"
  } | private_write "${RUN_ROOT}/api-binding"
  apply_api_binding "${selected_mode}" "${selected_cidr}" "${selected_port}"
  local policy_sha
  policy_sha=$(sha256sum -- "${RUN_ROOT}/api-bootstrap.yaml" | cut -d' ' -f1)
  write_result measure-backup-api-egress \
    "measured=true" "single_candidate=true" "mode=${selected_mode}" \
    "candidate_count=${candidate_count}" "policy_sha256=${policy_sha}"
  record_operation measure-backup-api-egress complete
}

prove_api_control() {
  local operation="$1" mode="$2" binding binding_mode cidr port policy_sha
  require_operation_complete measure-backup-api-egress
  binding=$(read_api_binding)
  read -r binding_mode cidr port <<<"${binding}"
  apply_api_binding "${binding_mode}" "${cidr}" "${port}"
  run_api_control "${mode}" || fatal
  policy_sha=$(sha256sum -- "${RUN_ROOT}/api-bootstrap.yaml" | cut -d' ' -f1)
  write_result "${operation}" "passed=true" "policy_sha256=${policy_sha}"
  record_operation "${operation}" complete
}

recheck_backup_api_access() {
  local binding binding_mode cidr port policy_sha
  require_operation_complete prove-backup-api-positive
  require_operation_complete prove-backup-api-network-negative
  require_operation_complete prove-backup-api-rbac-negative
  binding=$(read_api_binding)
  read -r binding_mode cidr port <<<"${binding}"
  apply_api_binding "${binding_mode}" "${cidr}" "${port}"
  run_api_control positive || fatal
  run_api_control network-negative || fatal
  run_api_control rbac-negative || fatal
  policy_sha=$(sha256sum -- "${RUN_ROOT}/api-bootstrap.yaml" | cut -d' ' -f1)
  write_result recheck-backup-api-access \
    "binding_current=true" "positive_get=true" \
    "network_negative=true" "rbac_negative=true" \
    "policy_sha256=${policy_sha}"
  record_operation recheck-backup-api-access complete
}

record_backup_writer_prestate() {
  local replicas
  replicas=$(new_replicas)
  [[ "${replicas}" =~ ^[1-9][0-9]?$ ]] || fatal
  {
    printf 'schema=solidstats-memory-backup-writer-prestate/v1\n'
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    printf 'replicas=%s\n' "${replicas}"
  } | private_write "${RUN_ROOT}/backup-writer.prestate"
}

restore_backup_writer() {
  local path="${RUN_ROOT}/backup-writer.prestate" replicas
  require_regular_private_file "${path}"
  [[ "$(result_field "${path}" schema)" == \
    solidstats-memory-backup-writer-prestate/v1 ]] || fatal
  [[ "$(result_field "${path}" config_sha256)" == "${CONFIG_SHA256}" ]] || fatal
  replicas=$(result_field "${path}" replicas)
  [[ "${replicas}" =~ ^[1-9][0-9]?$ ]] || fatal
  set_new_replicas "${replicas}"
  write_result restore-backup-writer "replicas_restored=true" \
    "replica_count=${replicas}"
  record_operation restore-backup-writer complete
}

prove_backup_consistency() {
  require_operation_complete recheck-backup-api-access
  if [[ "$(operation_status prove-backup-consistency 2>/dev/null || true)" == complete ]]; then
    require_operation_complete prove-backup-consistency
    return 0
  fi
  [[ "$(backup_schedule_state)" == "true:Forbid" ]] || fatal
  local job="solidstats-memory-backup-${RUN_ID_SHA256:0:12}" cleanup_required=1
  record_backup_writer_prestate
  record_operation prove-backup-consistency pending
  cleanup_backup_writer() {
    trap - EXIT INT TERM
    if [[ "${cleanup_required}" == 1 ]]; then
      restore_backup_writer || true
    fi
  }
  trap cleanup_backup_writer EXIT INT TERM
  kube_quiet delete job "${job}" --ignore-not-found=true --wait=true
  kube_quiet create job "${job}" --from="cronjob/${BACKUP_CRONJOB}"
  kube_quiet wait --for=condition=Complete "job/${job}" \
    "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
  local log_sha
  log_sha=$(timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    logs "job/${job}" 2>/dev/null | sha256sum | cut -d' ' -f1) || fatal
  [[ "${log_sha}" =~ ^[0-9a-f]{64}$ ]] || fatal
  restore_backup_writer
  cleanup_required=0
  trap - EXIT INT TERM
  write_result prove-backup-consistency \
    "exact_template=true" "job_complete=true" \
    "writer_restored=true" "job_log_sha256=${log_sha}"
  record_operation prove-backup-consistency complete
}

main() {
  [[ "$#" -ge 2 && "$#" -le 3 ]] || usage
  local operation="$1" run_id_sha256="$2" reconnect_timeout=""
  case "${operation}" in
    capture-prestate|stop-legacy-start-new|install-nginx|rollback-nginx|stop-new|start-legacy|restart-mempalace|restart-qdrant|measure-backup-api-egress|prove-backup-api-positive|prove-backup-api-network-negative|prove-backup-api-rbac-negative|recheck-backup-api-access|prove-backup-consistency|restore-backup-writer|suspend-backup-schedule|capture-boot-identity|reboot-host|verify-legacy-behavior|verify-retained-collections|activate-backup-schedule)
      [[ "$#" -eq 2 ]] || usage
      ;;
    verify-reboot-recovery)
      [[ "$#" -eq 3 && "$3" =~ ^[1-9][0-9]{0,3}$ ]] || usage
      (( 10#$3 <= 9999 )) || usage
      reconnect_timeout="$3"
      ;;
    *) usage ;;
  esac
  [[ "${run_id_sha256}" =~ ^[0-9a-f]{64}$ ]] || usage
  RUN_ID_SHA256="${run_id_sha256}"
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
    restart-mempalace) restart_workload "${operation}" deployment "${MEMORY_DEPLOYMENT}" mempalace ;;
    restart-qdrant) restart_workload "${operation}" statefulset "${QDRANT_STATEFULSET}" qdrant ;;
    measure-backup-api-egress) measure_backup_api_egress ;;
    prove-backup-api-positive) prove_api_control "${operation}" positive ;;
    prove-backup-api-network-negative) prove_api_control "${operation}" network-negative ;;
    prove-backup-api-rbac-negative) prove_api_control "${operation}" rbac-negative ;;
    recheck-backup-api-access) recheck_backup_api_access ;;
    prove-backup-consistency) prove_backup_consistency ;;
    restore-backup-writer) restore_backup_writer ;;
    suspend-backup-schedule) set_backup_schedule "${operation}" true ;;
    capture-boot-identity) capture_boot_identity ;;
    reboot-host) request_reboot ;;
    verify-reboot-recovery) verify_reboot_recovery "${reconnect_timeout}" ;;
    verify-legacy-behavior) verify_legacy_behavior ;;
    verify-retained-collections) verify_retained_collections ;;
    activate-backup-schedule)
      require_operation_complete restart-mempalace
      require_operation_complete restart-qdrant
      require_operation_complete recheck-backup-api-access
      require_operation_complete prove-backup-consistency
      require_operation_complete verify-reboot-recovery
      require_operation_complete verify-retained-collections
      set_backup_schedule "${operation}" false
      ;;
  esac
  echo "PASS: remote cutover boundary acknowledged"
}

main "$@"
