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

ensure_private_directory() {
  local path="$1" current=/ component
  local -a components
  valid_path_value "${path}" || fatal
  IFS='/' read -r -a components <<<"${path#/}"
  for component in "${components[@]}"; do
    [[ -n "${component}" ]] || continue
    current="${current%/}/${component}"
    if [[ -e "${current}" || -L "${current}" ]]; then
      [[ -d "${current}" && ! -L "${current}" ]] || fatal
    else
      mkdir -m 700 "${current}"
    fi
  done
  [[ "$(stat -c '%a:%u' "${path}")" == "700:$(id -u)" ]] || fatal
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
      backup_timeout_seconds) BACKUP_TIMEOUT_SECONDS="${value}" ;;
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
  [[ "${#seen[@]}" -eq 26 ]] || fatal
  [[ "${CONFIG_SCHEMA_VALUE:-}" == "${CONFIG_SCHEMA}" ]] || fatal
  for value in "${STATE_ROOT:-}" "${NGINX_ROOT:-}" "${NGINX_AVAILABLE:-}" "${NGINX_ENABLED:-}"; do
    valid_path_value "${value}" || fatal
  done
  [[ "${COMMAND_TIMEOUT_SECONDS:-}" =~ ^[1-9][0-9]?$|^120$ ]] || fatal
  [[ "${BACKUP_TIMEOUT_SECONDS:-}" =~ ^[1-9][0-9]{0,3}$ ]] || fatal
  (( BACKUP_TIMEOUT_SECONDS <= 3600 )) || fatal
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

operation_sequence() {
  case "$1" in
    capture-prestate) echo 10 ;; stop-legacy-start-new) echo 20 ;; install-nginx) echo 30 ;;
    restart-mempalace) echo 100 ;; restart-qdrant) echo 110 ;;
    measure-backup-api-egress) echo 200 ;; prove-backup-api-positive) echo 210 ;;
    prove-backup-api-network-negative) echo 220 ;; prove-backup-api-rbac-negative) echo 230 ;;
    recheck-backup-api-access) echo 240 ;; capture-backup-template-digest) echo 250 ;;
    prepare-guard-package) echo 260 ;; verify-guard-package) echo 270 ;;
    install-backup-guard) echo 280 ;; verify-backup-guard) echo 290 ;;
    guard-self-test-active) echo 294 ;; test-backup-guard-suspension) echo 295 ;;
    record-backup-writer-prestate) echo 297 ;; prove-backup-consistency) echo 300 ;;
    restore-backup-writer) echo 310 ;; suspend-backup-schedule) echo 320 ;;
    capture-boot-identity) echo 400 ;; reboot-host) echo 410 ;; verify-reboot-recovery) echo 420 ;;
    rollback-nginx) echo 500 ;; stop-new) echo 510 ;; start-legacy) echo 520 ;;
    verify-legacy-behavior) echo 530 ;; rearm-forward-cycle) echo 540 ;;
    verify-retained-collections) echo 570 ;; activate-backup-schedule) echo 600 ;;
    rollback-backup-guard) echo 610 ;; *) fatal ;;
  esac
}

write_result() {
  local operation="$1"
  shift
  local item
  {
    printf 'schema=solidstats-memory-remote-operation-result/v1\n'
    printf 'operation=%s\n' "${operation}"
    printf 'sequence=%s\n' "$(operation_sequence "${operation}")"
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    printf 'run_id_sha256=%s\n' "${RUN_ID_SHA256}"
    for item in "$@"; do
      [[ "${item}" =~ ^[a-z][a-z0-9_]{0,63}=(true|false|[0-9]+|[0-9a-f]{64}|service|endpoint)$ ]] || fatal
      printf '%s\n' "${item}"
    done
  } | private_write "$(operation_path "${operation}" result)"
}

require_operation_complete() {
  local path
  [[ "$(operation_status "$1")" == complete ]] || fatal
  path=$(operation_path "$1" result)
  require_regular_private_file "${path}"
  [[ "$(result_field "${path}" config_sha256)" == "${CONFIG_SHA256}" ]] || fatal
}

resource_identity() {
  local selector="$1" value
  [[ "${selector}" == "mempalace" || "${selector}" == "qdrant" ]] || fatal
  value=$(kube_value get pods -l "app.kubernetes.io/name=${selector}" \
    -o 'jsonpath={range .items[*]}{.metadata.uid}{"\n"}{end}')
  [[ -n "${value}" ]] || fatal
  printf '%s' "${value}" | sha256sum | cut -d' ' -f1
}

qdrant_inventory() {
  local value image manifest
  local pod="phase21-qdrant-inventory-${RUN_ID_SHA256:0:12}"
  local policy="${pod}"
  image=$(kube_value get deployment "${MEMORY_DEPLOYMENT}" \
    -o 'jsonpath={.spec.template.spec.containers[?(@.name=="mempalace")].image}')
  [[ "${image}" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}@sha256:[0-9a-f]{64}$ ]] || fatal
  manifest="${RUN_ROOT}/qdrant-inventory.yaml"
  {
    printf '%s\n' \
      'apiVersion: networking.k8s.io/v1' \
      'kind: NetworkPolicy' \
      'metadata:' \
      "  name: ${policy}-egress" \
      "  namespace: ${MEMORY_NAMESPACE}" \
      'spec:' \
      '  podSelector:' \
      '    matchLabels:' \
      '      solidstats.memory/role: qdrant-admin-inventory' \
      '  policyTypes: [Egress]' \
      '  egress:' \
      '    - to:' \
      '        - podSelector:' \
      '            matchLabels:' \
      '              app.kubernetes.io/name: qdrant' \
      '      ports:' \
      '        - protocol: TCP' \
      '          port: 6333' \
      '---' \
      'apiVersion: networking.k8s.io/v1' \
      'kind: NetworkPolicy' \
      'metadata:' \
      "  name: ${policy}-ingress" \
      "  namespace: ${MEMORY_NAMESPACE}" \
      'spec:' \
      '  podSelector:' \
      '    matchLabels:' \
      '      app.kubernetes.io/name: qdrant' \
      '  policyTypes: [Ingress]' \
      '  ingress:' \
      '    - from:' \
      '        - podSelector:' \
      '            matchLabels:' \
      '              solidstats.memory/role: qdrant-admin-inventory' \
      '      ports:' \
      '        - protocol: TCP' \
      '          port: 6333' \
      '---' \
      'apiVersion: v1' \
      'kind: Pod' \
      'metadata:' \
      "  name: ${pod}" \
      "  namespace: ${MEMORY_NAMESPACE}" \
      '  labels:' \
      '    solidstats.memory/role: qdrant-admin-inventory' \
      'spec:' \
      '  serviceAccountName: mempalace' \
      '  automountServiceAccountToken: false' \
      '  restartPolicy: Never' \
      '  securityContext:' \
      '    runAsNonRoot: true' \
      '    runAsUser: 1000' \
      '    runAsGroup: 1000' \
      '    seccompProfile:' \
      '      type: RuntimeDefault' \
      '  containers:' \
      '    - name: inventory' \
      "      image: ${image}" \
      '      imagePullPolicy: IfNotPresent' \
      '      command: ["python"]' \
      '      args:' \
      '        - -c' \
      '        - |' \
      '          import hashlib,json,os,urllib.request' \
      '          headers={"api-key":os.environ["QDRANT_API_KEY"]}' \
      '          def get(path):' \
      '           request=urllib.request.Request("http://qdrant:6333"+path,headers=headers)' \
      '           with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)' \
      '          collections=sorted(x["name"] for x in get("/collections")["result"]["collections"])' \
      '          aliases=sorted((x["alias_name"],x["collection_name"]) for x in get("/aliases")["result"]["aliases"])' \
      '          raw=json.dumps({"collections":collections,"aliases":aliases},separators=(",",":"),sort_keys=True).encode()' \
      '          print(hashlib.sha256(raw).hexdigest(),len(collections),len(aliases))' \
      '      env:' \
      '        - name: QDRANT_API_KEY' \
      '          valueFrom:' \
      '            secretKeyRef:' \
      '              name: qdrant-runtime' \
      '              key: QDRANT_API_KEY' \
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
      '          memory: 128Mi'
  } | private_write "${manifest}"
  cleanup_qdrant_inventory() {
    local failed=0
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
      delete pod "${pod}" --ignore-not-found=true --wait=true \
      "--timeout=${COMMAND_TIMEOUT_SECONDS}s" </dev/null >/dev/null 2>&1 || failed=1
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
      delete networkpolicy "${policy}-egress" "${policy}-ingress" \
      --ignore-not-found=true --wait=true \
      "--timeout=${COMMAND_TIMEOUT_SECONDS}s" </dev/null >/dev/null 2>&1 || failed=1
    return "${failed}"
  }
  cleanup_qdrant_inventory || fatal
  trap 'cleanup_qdrant_inventory || exit 1' EXIT INT TERM
  kube_quiet apply -f "${manifest}"
  kube_quiet wait --for=jsonpath='{.status.phase}'=Succeeded "pod/${pod}" \
    "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
  value=$(timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    logs "pod/${pod}" </dev/null 2>/dev/null) || fatal
  [[ "${#value}" -le 96 && "${value}" != *$'\n'* ]] || fatal
  [[ "${value}" =~ ^[0-9a-f]{64}[[:space:]][0-9]+[[:space:]][0-9]+$ ]] || fatal
  cleanup_qdrant_inventory || fatal
  trap - EXIT INT TERM
  printf '%s\n' "${value}"
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
  printf '%s\n' "${status}" | private_write "$(operation_path "${operation}" state)"
}

operation_status() {
  local path
  path=$(operation_path "$1" state)
  [[ -f "${path}" && ! -L "${path}" ]] || return 1
  [[ "$(stat -c '%a' -- "${path}")" == "600" ]] || fatal
  local value
  value=$(<"${path}")
  [[ "${value}" == "pending" || "${value}" == "complete" ]] || fatal
  printf '%s\n' "${value}"
}

cycle_scoped_operation() {
  [[ "$1" =~ ^(stop-legacy-start-new|install-nginx|rollback-nginx|stop-new|start-legacy)$ ]]
}

operation_path() {
  local operation="$1" suffix="$2"
  if cycle_scoped_operation "${operation}"; then
    printf '%s/cycle-%s-%s.%s\n' "${RUN_ROOT}" "${CURRENT_CYCLE}" "${operation}" "${suffix}"
  else
    printf '%s/%s.%s\n' "${RUN_ROOT}" "${operation}" "${suffix}"
  fi
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

rearm_forward_cycle() {
  [[ "$(operation_status rollback-nginx)" == complete ]] || fatal
  [[ "$(operation_status stop-new)" == complete ]] || fatal
  [[ "$(operation_status start-legacy)" == complete ]] || fatal
  [[ "$(legacy_state)" == "$(field legacy_state)" ]] || fatal
  [[ "$(new_replicas)" == "$(field new_replicas)" ]] || fatal
  current_available_matches_prestate || fatal
  current_enabled_matches_prestate || fatal
  CURRENT_CYCLE=$((CURRENT_CYCLE + 1))
  printf '%s\n' "${CURRENT_CYCLE}" | private_write "${RUN_ROOT}/cycle"
  write_result rearm-forward-cycle "cycle=${CURRENT_CYCLE}"
  record_operation rearm-forward-cycle complete
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
  local inventory_before="" inventory_after="" inventory_digest collections aliases
  if [[ "${selector}" == qdrant ]]; then
    inventory_before=$(qdrant_inventory)
  fi
  record_operation "${operation}" pending
  kube_quiet rollout restart "${kind}/${name}"
  kube_quiet rollout status "${kind}/${name}" \
    "--timeout=${COMMAND_TIMEOUT_SECONDS}s"
  after=$(resource_identity "${selector}")
  [[ "${before}" != "${after}" ]] || fatal
  if [[ "${selector}" == qdrant ]]; then
    inventory_after=$(qdrant_inventory)
    [[ "${inventory_before}" == "${inventory_after}" ]] || fatal
    read -r inventory_digest collections aliases <<<"${inventory_after}"
    (( collections >= 2 && aliases >= 1 )) || fatal
    printf '%s\n' "${inventory_digest}" | private_write "${RUN_ROOT}/qdrant-inventory.sha256"
  fi
  if [[ "${selector}" == qdrant ]]; then
    write_result "${operation}" \
      "identity_changed=true" "before_sha256=${before}" "after_sha256=${after}" \
      "inventory_before_sha256=${inventory_digest}" \
      "inventory_after_sha256=${inventory_digest}" \
      "collection_count=${collections}" "alias_count=${aliases}"
  else
    write_result "${operation}" \
      "identity_changed=true" "before_sha256=${before}" "after_sha256=${after}"
  fi
  record_operation "${operation}" complete
}

backup_schedule_state() {
  local value
  value=$(kube_value get cronjob "${BACKUP_CRONJOB}" \
    -o 'jsonpath={.spec.suspend}:{.spec.concurrencyPolicy}')
  [[ "${value}" == "true:Forbid" || "${value}" == "false:Forbid" ]] || fatal
  printf '%s\n' "${value}"
}

backup_template_digest() {
  local path="${RUN_ROOT}/backup-cronjob.json"
  capture_kube_json "${path}" -n "${MEMORY_NAMESPACE}" get cronjob \
    "${BACKUP_CRONJOB}" -o json
  "${PYTHON_PATH}" -c '
import hashlib,json,sys
value=json.load(open(sys.argv[1]))["spec"]["jobTemplate"]
raw=json.dumps(value,separators=(",",":"),sort_keys=True).encode()
print(hashlib.sha256(raw).hexdigest())
' "${path}"
  rm -f "${path}"
}

capture_backup_template_digest() {
  local digest candidate
  digest=$(backup_template_digest)
  candidate=$(<"${RUN_ROOT}/guard-package/candidate-template.sha256")
  [[ "${digest}" =~ ^[0-9a-f]{64}$ ]] || fatal
  [[ "${digest}" == "${candidate}" ]] || fatal
  printf '%s\n' "${digest}" | private_write "${RUN_ROOT}/backup-template.sha256"
  write_result capture-backup-template-digest "template_sha256=${digest}" \
    "schedule_suspended=true"
  record_operation capture-backup-template-digest complete
}

set_backup_schedule() {
  local operation="$1" desired="$2"
  [[ "${desired}" == true || "${desired}" == false ]] || fatal
  if [[ "$(operation_status "${operation}" 2>/dev/null || true)" == complete ]]; then
    if [[ "$(backup_schedule_state)" != "${desired}:Forbid" ]]; then
      kube_quiet patch cronjob "${BACKUP_CRONJOB}" --type=merge \
        -p "{\"spec\":{\"suspend\":${desired}}}"
    fi
    [[ "$(backup_schedule_state)" == "${desired}:Forbid" ]] || fatal
    if [[ "${operation}" == activate-backup-schedule ]]; then
      local active_digest
      active_digest=$(backup_template_digest)
      [[ "${active_digest}" == "$(<"${RUN_ROOT}/guard-package/candidate-template.sha256")" ]] || fatal
      write_result "${operation}" "schedule_suspended=${desired}" \
        "concurrency_forbid=true" "active_template_sha256=${active_digest}"
    else
      write_result "${operation}" "schedule_suspended=${desired}" "concurrency_forbid=true"
    fi
    require_operation_complete "${operation}"
    return 0
  fi
  record_operation "${operation}" pending
  kube_quiet patch cronjob "${BACKUP_CRONJOB}" --type=merge \
    -p "{\"spec\":{\"suspend\":${desired}}}"
  [[ "$(backup_schedule_state)" == "${desired}:Forbid" ]] || fatal
  if [[ "${operation}" == activate-backup-schedule ]]; then
    local active_digest
    active_digest=$(backup_template_digest)
    [[ "${active_digest}" == "$(<"${RUN_ROOT}/guard-package/candidate-template.sha256")" ]] || fatal
    write_result "${operation}" "schedule_suspended=${desired}" \
      "concurrency_forbid=true" "active_template_sha256=${active_digest}"
  else
    write_result "${operation}" "schedule_suspended=${desired}" "concurrency_forbid=true"
  fi
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
  local expected current digest collections aliases
  require_regular_private_file "${RUN_ROOT}/qdrant-inventory.sha256"
  expected=$(<"${RUN_ROOT}/qdrant-inventory.sha256")
  current=$(qdrant_inventory)
  read -r digest collections aliases <<<"${current}"
  [[ "${digest}" == "${expected}" ]] || fatal
  (( collections >= 2 && aliases >= 1 )) || fatal
  write_result verify-retained-collections \
    "qdrant_ready=true" "mempalace_available=true" \
    "inventory_before_sha256=${expected}" "inventory_after_sha256=${digest}" \
    "collection_count=${collections}" "alias_count=${aliases}" \
    "destructive_collection_calls=0"
  record_operation verify-retained-collections complete
}

install_backup_guard() {
  if [[ "$(operation_status install-backup-guard 2>/dev/null || true)" == complete ]]; then
    verify_backup_guard
    require_operation_complete install-backup-guard
    return 0
  fi
  local guard_source suspend_source service_source timer_source config_source
  require_operation_complete verify-guard-package
  guard_source="${RUN_ROOT}/guard-package/guard-solidstats-memory-backup.sh"
  suspend_source="${RUN_ROOT}/guard-package/suspend-solidstats-memory-backup.sh"
  service_source="${RUN_ROOT}/guard-package/solidstats-memory-backup-guard.service"
  timer_source="${RUN_ROOT}/guard-package/solidstats-memory-backup-guard.timer"
  config_source="${RUN_ROOT}/guard-package/guard-solidstats-memory-backup.sh.config"
  require_binary "${guard_source}"
  require_binary "${suspend_source}"
  require_regular_private_file "${config_source}"
  [[ -f "${service_source}" && ! -L "${service_source}" &&
    -f "${timer_source}" && ! -L "${timer_source}" ]] || fatal
  local destination backup name
  mkdir -p -m 700 "${RUN_ROOT}/guard-prestate"
  if "${SYSTEMCTL_PATH}" is-enabled --quiet solidstats-memory-backup-guard.timer 2>/dev/null; then
    printf 'true\n' | private_write "${RUN_ROOT}/guard-prestate/enabled"
  else
    printf 'false\n' | private_write "${RUN_ROOT}/guard-prestate/enabled"
  fi
  if "${SYSTEMCTL_PATH}" is-active --quiet solidstats-memory-backup-guard.timer 2>/dev/null; then
    printf 'true\n' | private_write "${RUN_ROOT}/guard-prestate/active"
  else
    printf 'false\n' | private_write "${RUN_ROOT}/guard-prestate/active"
  fi
  for name in script suspend service timer config; do
    case "${name}" in
      script) destination=/usr/local/libexec/solidstats-memory-backup-guard ;;
      suspend) destination=/usr/local/libexec/solidstats-memory-backup-suspend ;;
      service) destination=/etc/systemd/system/solidstats-memory-backup-guard.service ;;
      timer) destination=/etc/systemd/system/solidstats-memory-backup-guard.timer ;;
      config) destination=/etc/solidstats-memory-backup-guard.conf ;;
    esac
    backup="${RUN_ROOT}/guard-prestate/${name}"
    if [[ -e "${destination}" ]]; then
      [[ -f "${destination}" && ! -L "${destination}" ]] || fatal
      stat -c '%a' "${destination}" | private_write "${backup}.mode"
      stat -c '%u:%g' "${destination}" | private_write "${backup}.owner"
      cp --preserve=all "${destination}" "${backup}"
      chmod 600 "${backup}"
      printf 'file\n' | private_write "${backup}.state"
    else
      printf 'absent\n' | private_write "${backup}.state"
    fi
  done
  install -m 0755 "${guard_source}" /usr/local/libexec/solidstats-memory-backup-guard
  install -m 0755 "${suspend_source}" /usr/local/libexec/solidstats-memory-backup-suspend
  install -m 0644 "${service_source}" /etc/systemd/system/solidstats-memory-backup-guard.service
  install -m 0644 "${timer_source}" /etc/systemd/system/solidstats-memory-backup-guard.timer
  install -m 0600 "${config_source}" /etc/solidstats-memory-backup-guard.conf
  run_quiet "${SYSTEMCTL_PATH}" daemon-reload
  run_quiet "${SYSTEMCTL_PATH}" enable --now solidstats-memory-backup-guard.timer
  verify_backup_guard
  write_result install-backup-guard "installed=true" "prestate_retained=true"
  record_operation install-backup-guard complete
}

prepare_guard_package() {
  local directory="${RUN_ROOT}/guard-package"
  local name
  if [[ -e "${directory}" ]]; then
    [[ -d "${directory}" && ! -L "${directory}" &&
      "$(stat -c '%a:%u' "${directory}")" == "700:$(id -u)" ]] || fatal
  else
    mkdir -m 700 "${directory}"
  fi
  for name in guard-solidstats-memory-backup.sh suspend-solidstats-memory-backup.sh \
    solidstats-memory-backup-guard.service solidstats-memory-backup-guard.timer \
    guard-solidstats-memory-backup.sh.config 40-backup.active.yaml \
    backup-activation.provenance.json SHA256SUMS 40-backup.rendered.json \
    candidate-template.sha256; do
    if [[ -e "${directory}/${name}" ]]; then
      [[ -f "${directory}/${name}" && ! -L "${directory}/${name}" ]] || fatal
      rm -f -- "${directory}/${name}"
    fi
  done
  write_result prepare-guard-package "prepared=true"
  record_operation prepare-guard-package complete
}

verify_guard_package() {
  local directory="${RUN_ROOT}/guard-package" descriptor="${RUN_ROOT}/guard-package/SHA256SUMS" name
  require_regular_private_file "${descriptor}"
  [[ "$(wc -l <"${descriptor}")" -eq 7 ]] || fatal
  for name in guard-solidstats-memory-backup.sh suspend-solidstats-memory-backup.sh solidstats-memory-backup-guard.service solidstats-memory-backup-guard.timer guard-solidstats-memory-backup.sh.config 40-backup.active.yaml backup-activation.provenance.json; do
    [[ -f "${directory}/${name}" && ! -L "${directory}/${name}" ]] || fatal
    case "${name}" in
      *.config|*.yaml|*.json) [[ "$(stat -c '%a' "${directory}/${name}")" == 600 ]] || fatal ;;
      *.sh) [[ "$(stat -c '%a' "${directory}/${name}")" == 755 ]] || fatal ;;
      *) [[ "$(stat -c '%a' "${directory}/${name}")" == 644 ]] || fatal ;;
    esac
    grep -Eq "^[0-9a-f]{64}  ${name}$" "${descriptor}" || fatal
  done
  (cd "${directory}" && sha256sum -c SHA256SUMS >/dev/null 2>&1) || fatal
  local rendered="${directory}/40-backup.rendered.json" digest
  timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" create --dry-run=client -f "${directory}/40-backup.active.yaml" \
    -o json >"${rendered}.tmp" 2>/dev/null || fatal
  chmod 600 "${rendered}.tmp"
  mv -f "${rendered}.tmp" "${rendered}"
  digest=$("${PYTHON_PATH}" -c '
import hashlib,json,pathlib,sys
raw=pathlib.Path(sys.argv[1]).read_text()
decoder=json.JSONDecoder()
values=[]
index=0
while index < len(raw):
    while index < len(raw) and raw[index].isspace():
        index += 1
    if index < len(raw):
        value,index=decoder.raw_decode(raw,index)
        values.append(value)
cronjobs=[value for value in values if value.get("kind")=="CronJob" and value.get("metadata",{}).get("name")=="solidstats-memory-backup"]
if len(cronjobs)!=1:
    raise SystemExit(1)
value=cronjobs[0]["spec"]["jobTemplate"]
raw=json.dumps(value,separators=(",",":"),sort_keys=True).encode()
print(hashlib.sha256(raw).hexdigest())
' "${rendered}")
  [[ "${digest}" =~ ^[0-9a-f]{64}$ ]] || fatal
  local candidate_sha provenance_status
  candidate_sha=$(sha256sum -- "${directory}/40-backup.active.yaml" | cut -d' ' -f1)
  provenance_status=$("${PYTHON_PATH}" -c '
import json,sys
value=json.load(open(sys.argv[1]))
expected={"schema","source_suspended_sha256","rendered_suspended_sha256","active_candidate_sha256","canonical_job_template_sha256","source_render_exact"}
ok=set(value)==expected and value["schema"]=="solidstats-memory-backup-activation-render/v1" and value["source_render_exact"] is True and value["source_suspended_sha256"]!=value["rendered_suspended_sha256"] and value["active_candidate_sha256"]==sys.argv[2] and value["canonical_job_template_sha256"]==sys.argv[3]
print("true" if ok else "false")
' "${directory}/backup-activation.provenance.json" "${candidate_sha}" "${digest}")
  [[ "${provenance_status}" == true ]] || fatal
  printf '%s\n' "${digest}" | private_write "${directory}/candidate-template.sha256"
  local package_sha
  package_sha=$(sha256sum -- "${descriptor}" | cut -d' ' -f1)
  write_result verify-guard-package "verified=true" "file_count=7" \
    "package_sha256=${package_sha}" \
    "provenance_verified=true" "active_candidate_sha256=${candidate_sha}" \
    "template_sha256=${digest}"
  record_operation verify-guard-package complete
}

rollback_backup_guard() {
  local name destination state backup
  run_quiet "${SYSTEMCTL_PATH}" disable --now solidstats-memory-backup-guard.timer
  for name in script suspend service timer config; do
    case "${name}" in
      script) destination=/usr/local/libexec/solidstats-memory-backup-guard ;;
      suspend) destination=/usr/local/libexec/solidstats-memory-backup-suspend ;;
      service) destination=/etc/systemd/system/solidstats-memory-backup-guard.service ;;
      timer) destination=/etc/systemd/system/solidstats-memory-backup-guard.timer ;;
      config) destination=/etc/solidstats-memory-backup-guard.conf ;;
    esac
    state="${RUN_ROOT}/guard-prestate/${name}.state"
    require_regular_private_file "${state}"
    if [[ "$(<"${state}")" == file ]]; then
      backup="${RUN_ROOT}/guard-prestate/${name}"
      require_regular_private_file "${backup}"
      require_regular_private_file "${backup}.mode"
      require_regular_private_file "${backup}.owner"
      [[ "$(<"${backup}.mode")" =~ ^[0-7]{3,4}$ ]] || fatal
      [[ "$(<"${backup}.owner")" =~ ^[0-9]+:[0-9]+$ ]] || fatal
      install -o "$(cut -d: -f1 "${backup}.owner")" \
        -g "$(cut -d: -f2 "${backup}.owner")" \
        -m "$(<"${backup}.mode")" "${backup}" "${destination}"
    else
      [[ "$(<"${state}")" == absent ]] || fatal
      rm -f "${destination}"
    fi
  done
  run_quiet "${SYSTEMCTL_PATH}" daemon-reload
  if [[ "$(<"${RUN_ROOT}/guard-prestate/enabled")" == true ]]; then
    run_quiet "${SYSTEMCTL_PATH}" enable solidstats-memory-backup-guard.timer
  fi
  if [[ "$(<"${RUN_ROOT}/guard-prestate/active")" == true ]]; then
    run_quiet "${SYSTEMCTL_PATH}" start solidstats-memory-backup-guard.timer
  fi
  write_result rollback-backup-guard "prestate_restored=true"
  record_operation rollback-backup-guard complete
}

verify_backup_guard() {
  run_quiet "${SYSTEMCTL_PATH}" is-enabled --quiet solidstats-memory-backup-guard.timer
  run_quiet "${SYSTEMCTL_PATH}" is-active --quiet solidstats-memory-backup-guard.timer
  run_quiet "${SYSTEMCTL_PATH}" start solidstats-memory-backup-guard.service
  write_result verify-backup-guard "enabled=true" "active=true" "self_test_passed=true"
  record_operation verify-backup-guard complete
}

test_backup_guard_suspension() {
  require_operation_complete install-backup-guard
  set_backup_schedule guard-self-test-active false
  run_quiet env SOLIDSTATS_MEMORY_GUARD_SELF_TEST=1 \
    /usr/local/libexec/solidstats-memory-backup-guard \
    /etc/solidstats-memory-backup-guard.conf
  [[ "$(backup_schedule_state)" == true:Forbid ]] || fatal
  write_result test-backup-guard-suspension "temporary_activation=true" \
    "schedule_suspended=true" "guard_passed=true"
  record_operation test-backup-guard-suspension complete
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
rows = sorted(set(rows), key=lambda row: (row[0] != "service", row))
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
      '        - ipBlock:'
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
  local expected_status
  case "${mode}" in
    positive) expected_status=200 ;;
    rbac-negative) expected_status=403 ;;
    network-negative) expected_status=0 ;;
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
      '  securityContext:' \
      '    runAsNonRoot: true' \
      '    runAsUser: 1000' \
      '    runAsGroup: 1000' \
      '    fsGroup: 1000' \
      '    fsGroupChangePolicy: OnRootMismatch' \
      '    seccompProfile:' \
      '      type: RuntimeDefault' \
      '  containers:' \
      '    - name: probe'
    printf '      image: %s\n' "${image}"
    printf '%s\n' \
      '      command: ["python3", "-c"]' \
      '      args:' \
      '        - |' \
      '          import os,pathlib,ssl,urllib.error,urllib.request' \
      '          token=pathlib.Path("/var/run/secrets/solidstats-memory/token").read_text(encoding="ascii").strip()' \
      '          if not token or any(character.isspace() for character in token):raise SystemExit(1)' \
      '          host=os.environ["KUBERNETES_SERVICE_HOST"]' \
      '          port=os.environ["KUBERNETES_SERVICE_PORT_HTTPS"]' \
      '          url=f"https://{host}:{port}/apis/apps/v1/namespaces/solidstats-memory/deployments/mempalace/scale"' \
      '          request=urllib.request.Request(url,headers={"Authorization":f"Bearer {token}"})' \
      '          context=ssl.create_default_context(cafile="/var/run/secrets/solidstats-memory/ca.crt")' \
      '          try:' \
      '           with urllib.request.urlopen(request,timeout=8,context=context) as response:status=response.status' \
      '          except urllib.error.HTTPError as error:' \
      '           status=error.code' \
      '           error.close()' \
      '          except (OSError,TimeoutError):status=0'
    printf '          if status != %s:raise SystemExit(1)\n' "${expected_status}"
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
  local attempt phase poll
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
        --ignore-not-found=true --wait=true </dev/null >/dev/null 2>&1 || fatal
      fatal
    fi
  fi
  for ((attempt = 1; attempt <= 3; attempt += 1)); do
    status=0
    timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
      "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
      delete pod "${pod_name}" --ignore-not-found=true --wait=true \
      </dev/null >/dev/null 2>&1 || status=1
    if [[ "${status}" == 0 ]]; then
      timeout --signal=TERM --kill-after=5s "${COMMAND_TIMEOUT_SECONDS}s" \
        "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" create \
        -f "${RUN_ROOT}/api-probe-pod.yaml" </dev/null >/dev/null 2>&1 || status=1
    fi
    phase=""
    if [[ "${status}" == 0 ]]; then
      for ((poll = 1; poll <= 30; poll += 1)); do
        phase=$(timeout --signal=TERM --kill-after=5s \
          "${COMMAND_TIMEOUT_SECONDS}s" "${KUBECTL_PATH}" \
          --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
          get pod "${pod_name}" -o 'jsonpath={.status.phase}' \
          </dev/null 2>/dev/null) || {
          status=1
          break
        }
        case "${phase}" in
          Succeeded) status=0; break ;;
          Failed) status=1; break ;;
          ""|Pending|Running) sleep 1 ;;
          *) status=1; break ;;
        esac
      done
      [[ "${phase}" == Succeeded ]] || status=1
    fi
    [[ "${status}" == 0 ]] && break
    [[ "${attempt}" -eq 3 ]] || sleep 2
  done
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
  local mode cidr port passing_endpoints=0 candidate_count=0 candidate_ordinal=0 selected_ordinal=0
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
  candidate_count=$(wc -l <"${candidates}")
  [[ "${candidate_count}" =~ ^[1-9][0-9]*$ ]] || fatal
  while read -r mode cidr port; do
    validate_api_binding_values "${mode}" "${cidr}" "${port}"
    candidate_ordinal=$((candidate_ordinal + 1))
    apply_api_binding "${mode}" "${cidr}" "${port}"
    if run_api_control positive; then
      if [[ "${mode}" == service ]]; then
        selected_mode="${mode}"
        selected_cidr="${cidr}"
        selected_port="${port}"
        selected_ordinal="${candidate_ordinal}"
        break
      fi
      passing_endpoints=$((passing_endpoints + 1))
      selected_mode="${mode}"
      selected_cidr="${cidr}"
      selected_port="${port}"
      selected_ordinal="${candidate_ordinal}"
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
    "candidate_count=${candidate_count}" "selected_ordinal=${selected_ordinal}" \
    "policy_sha256=${policy_sha}"
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
  local replicas generation pod_digest
  replicas=$(new_replicas)
  [[ "${replicas}" =~ ^[1-9][0-9]?$ ]] || fatal
  generation=$(kube_value get deployment "${MEMORY_DEPLOYMENT}" -o 'jsonpath={.metadata.generation}')
  [[ "${generation}" =~ ^[1-9][0-9]*$ ]] || fatal
  pod_digest=$(resource_identity mempalace)
  [[ "${pod_digest}" =~ ^[0-9a-f]{64}$ ]] || fatal
  {
    printf 'schema=solidstats-memory-backup-writer-prestate/v1\n'
    printf 'config_sha256=%s\n' "${CONFIG_SHA256}"
    printf 'replicas=%s\n' "${replicas}"
    printf 'generation=%s\n' "${generation}"
    printf 'pod_identity_sha256=%s\n' "${pod_digest}"
  } | private_write "${RUN_ROOT}/backup-writer.prestate"
  write_result record-backup-writer-prestate "recorded=true" \
    "replica_count=${replicas}" "generation=${generation}" \
    "pod_identity_sha256=${pod_digest}"
  record_operation record-backup-writer-prestate complete
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
  require_operation_complete capture-backup-template-digest
  [[ "$(backup_template_digest)" == "$(<"${RUN_ROOT}/backup-template.sha256")" ]] || fatal
  if [[ "$(operation_status prove-backup-consistency 2>/dev/null || true)" == complete ]]; then
    require_operation_complete prove-backup-consistency
    return 0
  fi
  [[ "$(backup_schedule_state)" == "true:Forbid" ]] || fatal
  local job="solidstats-memory-backup-${RUN_ID_SHA256:0:12}" cleanup_required=1
  require_operation_complete record-backup-writer-prestate
  record_operation prove-backup-consistency pending
  cleanup_backup_writer() {
    local status=$?
    trap - EXIT INT TERM
    if [[ "${cleanup_required}" == 1 ]]; then
      if ! (restore_backup_writer); then status=1; fi
      if ! (set_backup_schedule suspend-backup-schedule true); then status=1; fi
    fi
    exit "${status}"
  }
  trap cleanup_backup_writer EXIT INT TERM
  kube_quiet delete job "${job}" --ignore-not-found=true --wait=true
  kube_quiet create job "${job}" --from="cronjob/${BACKUP_CRONJOB}"
  timeout --signal=TERM --kill-after=5s "${BACKUP_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    wait --for=condition=Complete "job/${job}" \
    "--timeout=${BACKUP_TIMEOUT_SECONDS}s" </dev/null >/dev/null 2>&1 || fatal
  local log_sha metadata_sha inventory_sha file_count logs="${RUN_ROOT}/backup-job.log"
  timeout --signal=TERM --kill-after=5s "${BACKUP_TIMEOUT_SECONDS}s" \
    "${KUBECTL_PATH}" --context "${KUBE_CONTEXT}" -n "${MEMORY_NAMESPACE}" \
    logs "job/${job}" >"${logs}.tmp" 2>/dev/null || fatal
  [[ "$(stat -c '%s' "${logs}.tmp")" -le 65536 ]] || fatal
  chmod 600 "${logs}.tmp"
  mv -f "${logs}.tmp" "${logs}"
  grep -qx 'PASS: writer-restored=pass' "${logs}" || fatal
  grep -qx 'PASS: behavior-oracle=pass' "${logs}" || fatal
  metadata_sha=$(sed -n 's/^PASS: metadata-sha256=//p' "${logs}")
  [[ "${metadata_sha}" =~ ^[0-9a-f]{64}$ ]] || fatal
  inventory_sha=$(sed -n 's/^PASS: package-inventory-sha256=//p' "${logs}")
  file_count=$(sed -n 's/^PASS: package-file-count=//p' "${logs}")
  [[ "${inventory_sha}" =~ ^[0-9a-f]{64}$ && "${file_count}" == 4 ]] || fatal
  grep -qx 'PASS: downloaded=pass' "${logs}" || fatal
  grep -qx 'PASS: checksums-rechecked=pass' "${logs}" || fatal
  log_sha=$(sha256sum "${logs}" | cut -d' ' -f1)
  [[ "${log_sha}" =~ ^[0-9a-f]{64}$ ]] || fatal
  restore_backup_writer
  cleanup_required=0
  trap - EXIT INT TERM
  write_result prove-backup-consistency \
    "exact_template=true" "job_complete=true" \
    "writer_restored=true" "behavior_oracle=true" \
    "zero_writers=true" "zero_pvc_consumers=true" \
    "source_before_sha256=${metadata_sha}" \
    "source_after_sha256=${metadata_sha}" "archive_sha256=${metadata_sha}" \
    "upload_file_count=${file_count}" "upload_inventory_sha256=${inventory_sha}" \
    "downloaded=true" "checksums_rechecked=true" \
    "job_log_sha256=${log_sha}"
  record_operation prove-backup-consistency complete
}

main() {
  [[ "$#" -ge 2 && "$#" -le 3 ]] || usage
  local operation="$1" run_id_sha256="$2" reconnect_timeout=""
  case "${operation}" in
    capture-prestate|stop-legacy-start-new|install-nginx|rollback-nginx|stop-new|start-legacy|rearm-forward-cycle|restart-mempalace|restart-qdrant|measure-backup-api-egress|prove-backup-api-positive|prove-backup-api-network-negative|prove-backup-api-rbac-negative|recheck-backup-api-access|capture-backup-template-digest|record-backup-writer-prestate|prove-backup-consistency|restore-backup-writer|suspend-backup-schedule|capture-boot-identity|reboot-host|verify-legacy-behavior|verify-retained-collections|prepare-guard-package|verify-guard-package|install-backup-guard|verify-backup-guard|test-backup-guard-suspension|rollback-backup-guard|activate-backup-schedule)
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
  ensure_private_directory "${STATE_ROOT}"
  RUN_ROOT="${STATE_ROOT}/${run_id_sha256}"
  ensure_private_directory "${RUN_ROOT}"
  if [[ -f "${RUN_ROOT}/cycle" ]]; then
    require_regular_private_file "${RUN_ROOT}/cycle"
    CURRENT_CYCLE=$(<"${RUN_ROOT}/cycle")
    [[ "${CURRENT_CYCLE}" =~ ^[0-9]{1,3}$ ]] || fatal
  else
    CURRENT_CYCLE=0
    printf '0\n' | private_write "${RUN_ROOT}/cycle"
  fi
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
    rearm-forward-cycle) rearm_forward_cycle ;;
    restart-mempalace) restart_workload "${operation}" deployment "${MEMORY_DEPLOYMENT}" mempalace ;;
    restart-qdrant) restart_workload "${operation}" statefulset "${QDRANT_STATEFULSET}" qdrant ;;
    measure-backup-api-egress) measure_backup_api_egress ;;
    prove-backup-api-positive) prove_api_control "${operation}" positive ;;
    prove-backup-api-network-negative) prove_api_control "${operation}" network-negative ;;
    prove-backup-api-rbac-negative) prove_api_control "${operation}" rbac-negative ;;
    recheck-backup-api-access) recheck_backup_api_access ;;
    capture-backup-template-digest) capture_backup_template_digest ;;
    record-backup-writer-prestate) record_backup_writer_prestate ;;
    prove-backup-consistency) prove_backup_consistency ;;
    restore-backup-writer) restore_backup_writer ;;
    suspend-backup-schedule) set_backup_schedule "${operation}" true ;;
    capture-boot-identity) capture_boot_identity ;;
    reboot-host) request_reboot ;;
    verify-reboot-recovery) verify_reboot_recovery "${reconnect_timeout}" ;;
    verify-legacy-behavior) verify_legacy_behavior ;;
    verify-retained-collections) verify_retained_collections ;;
    prepare-guard-package) prepare_guard_package ;;
    verify-guard-package) verify_guard_package ;;
    install-backup-guard) install_backup_guard ;;
    verify-backup-guard) verify_backup_guard ;;
    test-backup-guard-suspension) test_backup_guard_suspension ;;
    rollback-backup-guard) rollback_backup_guard ;;
    activate-backup-schedule)
      require_operation_complete restart-mempalace
      require_operation_complete restart-qdrant
      require_operation_complete recheck-backup-api-access
      require_operation_complete prove-backup-consistency
      require_operation_complete verify-reboot-recovery
      require_operation_complete verify-retained-collections
      require_operation_complete verify-backup-guard
      require_operation_complete test-backup-guard-suspension
      require_operation_complete capture-backup-template-digest
      [[ "$(backup_template_digest)" == "$(<"${RUN_ROOT}/backup-template.sha256")" ]] || fatal
      set_backup_schedule "${operation}" false
      ;;
  esac
  local public_result
  public_result=$(operation_path "${operation}" result)
  if [[ ! -f "${public_result}" ]]; then
    write_result "${operation}" "completed=true"
  fi
  if [[ -f "${public_result}" ]]; then
    require_regular_private_file "${public_result}"
    cat "${public_result}"
  fi
  echo "PASS: remote cutover boundary acknowledged"
}

main "$@"
