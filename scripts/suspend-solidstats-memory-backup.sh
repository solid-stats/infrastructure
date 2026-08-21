#!/usr/bin/env bash
set -Eeuo pipefail

fatal() { echo "FATAL: backup suspension helper failed closed" >&2; exit 1; }

trusted_chain() {
  local path="$1" current=/ component
  local -a components
  [[ "${path}" == /* && "${path}" != *..* ]] || return 1
  [[ -d / && ! -L / && "$(stat -c '%u' -- /)" == 0 &&
    $((8#$(stat -c '%a' -- /) & 8#022)) -eq 0 ]] || return 1
  IFS=/ read -r -a components <<<"${path#/}"
  for component in "${components[@]}"; do
    [[ -n "${component}" ]] || continue
    current="${current%/}/${component}"
    [[ -e "${current}" && ! -L "${current}" ]] || return 1
    if [[ "${current}" != "${path}" ]]; then
      [[ -d "${current}" && "$(stat -c '%u' -- "${current}")" == 0 &&
        $((8#$(stat -c '%a' -- "${current}") & 8#022)) -eq 0 ]] || return 1
    fi
  done
}

config=/etc/solidstats-memory-backup-guard.conf
trusted_chain "${config}" || fatal
[[ -f "${config}" && "$(stat -c '%u:%a' -- "${config}")" == 0:600 ]] || fatal
declare -A values=()
while IFS='=' read -r key value; do
  [[ "${key}" =~ ^[a-z_]+$ && -n "${value}" && -z "${values[$key]:-}" ]] || fatal
  values[$key]="${value}"
done <"${config}"
[[ "${#values[@]}" -eq 8 && "${values[schema]:-}" == solidstats-memory-backup-guard/v1 &&
  "${values[namespace]:-}" == solidstats-memory &&
  "${values[cronjob]:-}" == solidstats-memory-backup ]] || fatal

kubectl="${values[kubectl_path]:-}"
kubeconfig="${values[kubeconfig_path]:-}"
[[ "${kubectl}" =~ ^/usr(/local)?/bin/kubectl$ &&
  "${kubeconfig}" == /etc/rancher/k3s/k3s.yaml ]] || fatal
trusted_chain "${kubectl}" || fatal
trusted_chain "${kubeconfig}" || fatal
[[ -f "${kubectl}" && -x "${kubectl}" &&
  "$(stat -c '%u:%a' -- "${kubectl}")" =~ ^0:(755|750)$ ]] || fatal
[[ -f "${kubeconfig}" && "$(stat -c '%u:%a' -- "${kubeconfig}")" =~ ^0:(600|640)$ ]] || fatal
! grep -Eq '(^|[[:space:]])(exec:|auth-provider:)|(^|[[:space:]])(certificate-authority|client-certificate|client-key):[[:space:]]*[^/[:space:]]' "${kubeconfig}" || fatal

exec {kubectl_fd}<"${kubectl}"
exec {kubeconfig_fd}<"${kubeconfig}"
[[ "$(stat -Lc '%d:%i' -- "${kubectl}")" == "$(stat -Lc '%d:%i' -- "/proc/self/fd/${kubectl_fd}")" &&
  "$(stat -Lc '%d:%i' -- "${kubeconfig}")" == "$(stat -Lc '%d:%i' -- "/proc/self/fd/${kubeconfig_fd}")" ]] || fatal
timeout 30s "/proc/self/fd/${kubectl_fd}" \
  --kubeconfig "/proc/self/fd/${kubeconfig_fd}" \
  --context "${values[kube_context]}" -n solidstats-memory \
  patch cronjob solidstats-memory-backup --type=merge \
  -p '{"spec":{"suspend":true}}' >/dev/null 2>&1
echo "PASS: backup schedule suspended"
