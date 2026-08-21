#!/usr/bin/env bash
set -Eeuo pipefail

fatal() { echo "FATAL: backup guard failed closed" >&2; return 1; }
[[ "$#" -eq 1 ]] || fatal
config="$1"
fallback_suspend() {
  local status=$? fallback_kubectl
  trap - ERR
  if [[ -x /usr/local/bin/kubectl && ! -L /usr/local/bin/kubectl ]]; then
    fallback_kubectl=/usr/local/bin/kubectl
  else
    fallback_kubectl=/usr/bin/kubectl
  fi
  timeout 30s "${fallback_kubectl}" --kubeconfig /etc/rancher/k3s/k3s.yaml \
    -n solidstats-memory patch cronjob solidstats-memory-backup --type=merge \
    -p '{"spec":{"suspend":true}}' >/dev/null 2>&1 || status=1
  exit "${status}"
}
trap fallback_suspend ERR
[[ "${config}" == /etc/solidstats-memory-backup-guard.conf &&
  -f "${config}" && ! -L "${config}" &&
  "$(stat -c '%a' "${config}")" == 600 &&
  "$(stat -c '%u' "${config}")" == 0 ]] || fatal
declare -A values=()
while IFS='=' read -r key value; do
  [[ "${key}" =~ ^[a-z_]+$ && -n "${value}" && -z "${values[$key]:-}" ]] || fatal
  values[$key]="${value}"
done <"${config}"
[[ "${#values[@]}" -eq 8 && "${values[schema]:-}" == solidstats-memory-backup-guard/v1 &&
  "${values[namespace]:-}" == solidstats-memory &&
  "${values[cronjob]:-}" == solidstats-memory-backup &&
  "${values[job_timeout_seconds]:-}" =~ ^[1-9][0-9]{0,3}$ ]] || fatal
(( values[job_timeout_seconds] <= 3600 )) || fatal
state_root="${values[state_root]:-}"
[[ "${state_root}" == /var/lib/solidstats-memory-backup-guard ]] || fatal
install -d -m 700 -o 0 -g 0 "${state_root}"
[[ -d "${state_root}" && ! -L "${state_root}" &&
  "$(stat -c '%a:%u' "${state_root}")" == 700:0 ]] || fatal
kubectl="${values[kubectl_path]:-}"
[[ "${kubectl}" =~ ^/usr(/local)?/bin/kubectl$ && -x "${kubectl}" && ! -L "${kubectl}" &&
  "$(stat -c '%u:%a' "${kubectl}")" =~ ^0:(755|750)$ ]] || fatal
kubeconfig="${values[kubeconfig_path]:-}"
[[ "${kubeconfig}" == /etc/rancher/k3s/k3s.yaml && -f "${kubeconfig}" &&
  ! -L "${kubeconfig}" && "$(stat -c '%u:%a' "${kubeconfig}")" =~ ^0:(600|640)$ ]] || fatal
for trusted in /etc /etc/rancher /etc/rancher/k3s /usr /usr/bin /usr/local /usr/local/bin; do
  [[ ! -e "${trusted}" || ( -d "${trusted}" && ! -L "${trusted}" &&
    "$(stat -c '%u' "${trusted}")" == 0 &&
    $((8#$(stat -c '%a' "${trusted}") & 8#022)) -eq 0 ) ]] || fatal
done
if grep -Eq '(^|[[:space:]])(exec:|auth-provider:)|(^|[[:space:]])(certificate-authority|client-certificate|client-key):[[:space:]]*[^/[:space:]]' "${kubeconfig}"; then
  fatal
fi
on_error() {
  local status=$?
  trap - ERR
  timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" \
    --context "${values[kube_context]}" -n solidstats-memory \
    patch cronjob solidstats-memory-backup --type=merge \
    -p '{"spec":{"suspend":true}}' >/dev/null 2>&1 || status=1
  exit "${status}"
}
trap on_error ERR
if [[ "${SOLIDSTATS_MEMORY_GUARD_SELF_TEST:-0}" == 1 ]]; then
  timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" \
    --context "${values[kube_context]}" -n solidstats-memory \
    patch cronjob solidstats-memory-backup --type=merge \
    -p '{"spec":{"suspend":true}}' >/dev/null 2>&1
  [[ "$(timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" \
    --context "${values[kube_context]}" -n solidstats-memory get cronjob \
    solidstats-memory-backup -o 'jsonpath={.spec.suspend}:{.spec.concurrencyPolicy}')" == true:Forbid ]]
  echo "PASS: backup guard suspension self-test"
  exit 0
fi
tmp=$(mktemp "${state_root}/jobs.XXXXXX")
log_file=""
trap 'rm -f -- "${tmp}"; [[ -z "${log_file}" ]] || rm -f -- "${log_file}"' EXIT
chmod 600 "${tmp}"
timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" --context "${values[kube_context]}" \
  -n solidstats-memory get jobs -o json \
  >"${tmp}" 2>/dev/null || fatal
while IFS=$'\t' read -r name uid state expired; do
  [[ "${name}" =~ ^solidstats-memory-backup-[a-z0-9-]+$ &&
    "${uid}" =~ ^[A-Za-z0-9-]{8,128}$ && "${state}" =~ ^(active|complete|failed)$ &&
    "${expired}" =~ ^(true|false)$ ]] || fatal
  digest=$(printf '%s' "${uid}" | sha256sum | cut -d' ' -f1)
  marker="${state_root}/${digest}.result"
  [[ ! -L "${marker}" ]] || fatal
  [[ -f "${marker}" ]] && continue
  failure=false
  if [[ "${state}" == failed || "${expired}" == true ]]; then
    failure=true
  elif [[ "${state}" == complete ]]; then
    log_file=$(mktemp "${state_root}/log.XXXXXX")
    chmod 600 "${log_file}"
    if ! timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" --context "${values[kube_context]}" \
      -n solidstats-memory logs "job/${name}" --tail=20 >"${log_file}" 2>/dev/null ||
      [[ "$(stat -c '%s' "${log_file}")" -gt 4096 ]]; then
      failure=true
    elif ! grep -qx 'PASS: writer-restored=pass' "${log_file}" ||
      ! grep -qx 'PASS: behavior-oracle=pass' "${log_file}"; then
      failure=true
    fi
    rm -f "${log_file}"
    log_file=""
  else
    continue
  fi
  if [[ "${failure}" == true ]]; then
    timeout 30s "${kubectl}" --kubeconfig "${kubeconfig}" --context "${values[kube_context]}" \
      -n solidstats-memory patch cronjob solidstats-memory-backup --type=merge \
      -p '{"spec":{"suspend":true}}' >/dev/null 2>&1 || fatal
  fi
  umask 077
  printf 'schema=solidstats-memory-backup-guard-result/v1\nuid_sha256=%s\npassed=%s\nschedule_suspended=%s\n' \
    "${digest}" "$([[ "${failure}" == false ]] && echo true || echo false)" \
    "$([[ "${failure}" == true ]] && echo true || echo false)" >"${marker}.tmp"
  chmod 600 "${marker}.tmp"
  mv -f "${marker}.tmp" "${marker}"
done < <(python3 -c '
import datetime, json, sys
now=datetime.datetime.now(datetime.timezone.utc)
for job in json.load(open(sys.argv[1]))["items"]:
 m=job["metadata"]; s=job.get("status",{}); conditions={x["type"]:x["status"] for x in s.get("conditions",[])}
 if not any(x.get("kind")=="CronJob" and x.get("name")=="solidstats-memory-backup" for x in m.get("ownerReferences",[])): continue
 state="complete" if conditions.get("Complete")=="True" else "failed" if conditions.get("Failed")=="True" else "active"
 started=s.get("startTime"); expired=False
 if started: expired=(now-datetime.datetime.fromisoformat(started.replace("Z","+00:00"))).total_seconds()>int(sys.argv[2])
 print(m["name"],m["uid"],state,str(expired).lower(),sep="\t")
' "${tmp}" "${values[job_timeout_seconds]}")
echo "PASS: backup guard checked value-free job state"
