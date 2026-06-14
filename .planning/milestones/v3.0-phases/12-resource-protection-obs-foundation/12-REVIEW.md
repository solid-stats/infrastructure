---
phase: 12-resource-protection-obs-foundation
reviewed: 2026-06-13T17:24:57Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - scripts/resource-preflight.sh
  - scripts/validate-phase-12.sh
  - scripts/validate-staging.py
  - k8s/staging/01-obs-rbac.yaml
  - k8s/staging/02-priority-classes.yaml
  - k8s/staging/10-postgres.yaml
  - k8s/staging/20-rabbitmq.yaml
  - k8s/staging/35-server-2-deployment.yaml
  - k8s/staging/40-replay-parser-2.yaml
  - k8s/staging/50-replays-fetcher.yaml
  - k8s/staging/60-postgres-backup.yaml
  - .github/workflows/deploy-staging.yml
  - docs/resource-protection.md
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-06-13T17:24:57Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the Phase 12 resource-protection / observability-foundation changes:
two bash scripts, the python validation harness, the obs RBAC + PriorityClass
bootstrap manifests, the workload patches adding `priorityClassName` + (intended)
Guaranteed QoS, the CI deploy-glob exclusions, and the swap runbook.

No secret values are present in any reviewed file (good — secrets stay in env /
live K8s Secrets). RBAC is namespace-scoped and contains no destructive verbs.
CI glob exclusions for the four operator-bootstrap manifests are correct.

The central defect is that the **resource-protection scheme it claims to deliver
is not actually delivered consistently**: the `web` deployment carries no
`priorityClassName` at all (default priority 0 < `obs-background` 100), and
RabbitMQ — explicitly listed as an `app-critical` workload — is **Burstable, not
Guaranteed**, because its container and initContainer have `requests != limits`.
The validation harness does not catch either gap, so both passed review undetected.
These invert / weaken the eviction ordering the phase exists to guarantee.

## Critical Issues

### CR-01: `web` deployment has no `priorityClassName` — sits BELOW obs-background in eviction order

**File:** `k8s/staging/37-web-deployment.yaml` (entire pod spec — no `priorityClassName` key present)
**Issue:**
`web` is a runtime app workload, but it has no `priorityClassName`, so its pods
get the cluster default priority **0**. The `obs-background` PriorityClass is
**100**. Under node memory pressure the kubelet evicts by priority ascending,
so `web` (0) would be evicted **before** observability pods (100) — the exact
inversion this phase exists to prevent. The whole stated value of Phase 12
("runtime app pods are protected under node resource pressure",
`02-priority-classes.yaml:33-34`) is broken for `web`.

This is masked because `validate-phase-12.sh` only loops over
`postgres server-2 replay-parser-2 rabbitmq` (line 57) and omits `web`, even
though `web` is a first-class long-running workload in
`validate-staging.py` `EXPECTED_WORKLOADS` (line 71) and is rollout-verified in
`deploy-staging.yml:156`.

**Fix:**
Add to `k8s/staging/37-web-deployment.yaml` pod spec (same placement as the other
deployments):
```yaml
spec:
  template:
    spec:
      priorityClassName: app-critical  # PREP-03
```
And add `web` to the `validate-phase-12.sh` loop on line 57:
```bash
for workload in postgres server-2 replay-parser-2 rabbitmq web; do
```

## Warnings

### WR-01: RabbitMQ is Burstable, not Guaranteed — `requests != limits` on both containers

**File:** `k8s/staging/20-rabbitmq.yaml:67-73` (initContainer) and `:103-109` (main container)
**Issue:**
`02-priority-classes.yaml:16` and the PREP-04 comments declare postgres, server-2,
replay-parser-2 etc. as `app-critical` Guaranteed-QoS workloads, and
`validate-phase-12.sh:57` asserts rabbitmq carries `priorityClassName: app-critical`.
But rabbitmq's main container has `requests: cpu 250m / mem 512Mi` vs
`limits: cpu "1" / mem 2Gi`, and the `repair-erlang-cookie-permissions`
initContainer has `requests: 10m/32Mi` vs `limits: 100m/128Mi`. A pod is
Guaranteed only when **every** container (init + regular) has `requests == limits`
for cpu and memory. RabbitMQ is therefore **Burstable**, receiving a worse OOM
score than the Guaranteed app pods and being evicted earlier than intended.
`validate-phase-12.sh` checks QoS for postgres-0 and server-2 (lines 75-82) but
**not** rabbitmq, so the regression is invisible.

**Fix:**
Either (a) set `requests == limits` on both rabbitmq containers (pick values
>= observed P95, consistent with the postgres/server-2 pattern), or (b) if
RabbitMQ is intentionally Burstable, drop the implication that it is Guaranteed
and document the exception. Then add a rabbitmq QoS assertion to
`validate-phase-12.sh` mirroring the server-2 block (lines 79-82) so the choice
is enforced.

### WR-02: `validate-phase-12.sh` QoS assertion uses `.items[0]` with no ordering — flaky during rollout

**File:** `scripts/validate-phase-12.sh:79-82` (and the priorityClassName `.items[0]` reads at :58-60)
**Issue:**
`kubectl get pod -l app.kubernetes.io/name=server-2 -o jsonpath='{.items[0]...}'`
returns the first pod in the list. During a rolling update there can be two
server-2 pods (old terminating + new). The list order is not guaranteed, so the
assertion may read the **old** (pre-patch, Burstable) pod and either spuriously
FAIL a correct rollout or PASS while the new pod is wrong. The label selector
should be narrowed (e.g. to the ready pod) or the check should iterate all
matching pods and require every one to be `Guaranteed`.

**Fix:**
Iterate and require all pods match, e.g.:
```bash
for q in $(kubectl -n "$namespace" get pods -l app.kubernetes.io/name=server-2 \
  -o jsonpath='{.items[*].status.qosClass}'); do
  assert "server-2 qosClass" "$q" "Guaranteed"
done
```

### WR-03: `postgres-backup` container missing `capabilities: drop: ["ALL"]` — inconsistent hardening

**File:** `k8s/staging/60-postgres-backup.yaml:140-141`
**Issue:**
Every other app container in this phase (server-2, replay-parser-2,
replays-fetcher) sets both `allowPrivilegeEscalation: false` **and**
`capabilities: drop: ["ALL"]`. The postgres-backup container sets only
`allowPrivilegeEscalation: false`. It runs `apk add aws-cli` + `pg_dump`, none of
which need extra Linux capabilities, so dropping ALL is safe and brings it in
line with project Kubernetes-safety conventions (AGENTS.md "add pod/container
security context where images allow it").

**Fix:**
```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
```

### WR-04: backup manifest heredoc indentation is fragile under `sh -ec`

**File:** `k8s/staging/60-postgres-backup.yaml:76-85`
**Issue:**
The inline shell script is a YAML block scalar that strips the leading
indentation, but the `cat > "${manifest_path}" <<EOF ... EOF` heredoc body and
its closing `EOF` are written at the **same** indentation as the surrounding
code. A plain (non-`<<-`) heredoc requires the terminator `EOF` to be at column
0 of the produced script. After YAML block-scalar de-indentation the closing
`EOF` is preceded by the de-indented whitespace common to the block, so it
happens to land at column 0 here — but this is load-bearing on the exact block
indentation and will silently break (heredoc never terminates → script hangs or
`pg_dump`/upload never runs) if the block is re-indented during an edit. This is
not currently caught by `validate-staging.py` (it only runs `bash -n` on
external `.sh` files, not on inline CronJob scripts).

**Fix:**
Use an indented heredoc and quote the delimiter to avoid premature expansion and
indentation coupling:
```sh
cat > "${manifest_path}" <<-'EOF'
...
EOF
```
(or build the JSON with `printf`). Note `<<-` strips leading **tabs** only, so
ensure the body is tab-indented, or keep the JSON on explicit lines via `printf`.

### WR-05: `resource-preflight.sh` aborts the whole snapshot if `kubectl describe node` or the custom-columns query fails

**File:** `scripts/resource-preflight.sh:28`, `:37-38` (inside the `{ ... } | tee` group)
**Issue:**
With `set -euo pipefail`, the `kubectl describe node` (line 28) and the
`kubectl get pods -o custom-columns=...` (lines 37-38) have **no** `|| true`
guard, unlike the `kubectl top` calls (lines 31, 34) which do. A transient API
hiccup on either ungated call kills the entire snapshot before `df -h` / `free -h`
run — defeating the "re-runnable snapshot of headroom" purpose precisely when the
cluster is under the pressure you are trying to record.

**Fix:**
Append `|| echo "(describe node failed)"` and `|| echo "(pod resource query failed)"`
to lines 28 and 37-38 respectively, matching the resilience of the `kubectl top`
lines.

### WR-06: `df -h` / `free -h` in snapshot reflect the CI/operator workstation, not the k3s node

**File:** `scripts/resource-preflight.sh:41`, `:44`
**Issue:**
`kubectl` talks to the remote cluster, but `df -h` and `free -h` run on the
**local** host executing the script (CI runner or operator laptop over
WireGuard), not on the staging VPS node. The snapshot header implies these are
node figures ("--- Node disk usage ---", "--- Host memory and swap ---"), so an
operator could read CI-runner free memory and conclude the node has headroom it
does not. `resource-protection.md:31-36` even points operators at this script as
an alternative to SSHing the VPS for disk sizing — which would give a wrong
answer.

**Fix:**
Either relabel these sections as "(local host running this script — NOT the k3s
node)", or gather node-local figures via a debug pod / `kubectl debug node` /
SSH. At minimum, fix the `resource-protection.md` pre-check to not present
`resource-preflight.sh` as a substitute for `ssh ... df -h /` on the VPS.

## Info

### IN-01: `02-priority-classes.yaml` description says "etc" but the set of app-critical workloads is undocumented and incomplete

**File:** `k8s/staging/02-priority-classes.yaml:16`
**Issue:**
"Runtime app workloads (postgres, server-2, replay-parser-2, etc)" — the open
"etc" is what let `web` (CR-01) slip through without anyone noticing it lacked
the class. An explicit, enumerated list (kept in sync with the validate loop)
would make the omission obvious.
**Fix:** Enumerate the full app-critical set (postgres, rabbitmq, server-2, web,
replay-parser-2, replays-fetcher, postgres-backup) and keep it aligned with the
`validate-phase-12.sh` loop.

### IN-02: `01-obs-rbac.yaml` Role is duplicated verbatim across two namespaces

**File:** `k8s/staging/01-obs-rbac.yaml:49-77` and `:120-151`
**Issue:**
The `obs-ci-deployer` Role rules block is copy-pasted identically for
`monitoring` and `error-tracking`. A future least-privilege tightening must be
applied in two places; drift between them is easy to introduce. Not a bug today
(both are correct and identical), purely a maintainability note given the file is
operator-applied and rarely touched.
**Fix:** Acceptable as-is for a 2-namespace bootstrap; if it grows, template it
(kustomize) or add a comment cross-linking the two blocks so edits stay paired.

### IN-03: obs-ci-deployer Role grants `secrets` create/update without `delete` but RBAC for deploy is broad

**File:** `k8s/staging/01-obs-rbac.yaml:71-73`, `:145-147`
**Issue:**
The Role grants `get/list/create/update/patch` on `secrets` in the obs
namespaces. This is consistent with "kubectl apply" needs and is namespace-scoped
(no cross-namespace, no `delete`, no cluster scope), so it satisfies the stated
least-privilege intent. Flagging only so the reviewer is aware the CI deployer
can read all Secrets in `monitoring`/`error-tracking` — fine for v1 since those
namespaces hold only obs config, but worth revisiting if app secrets ever land
there.
**Fix:** No change required for v1; revisit secret read scope if sensitive data
enters these namespaces.

### IN-04: `validate-phase-12.sh` PREP-02 swap check is documentation-only, not enforced

**File:** `scripts/validate-phase-12.sh:131-134`
**Issue:**
The PREP-02 host-swap "check" only prints a manual SSH command — it asserts
nothing and cannot fail. This is acknowledged in the header comment and is a
reasonable limitation (kubectl has no host-swap view), but it means a green
`validate-phase-12.sh` run does **not** evidence that swap is provisioned. The
validation summary printing "PASSED" (line 138) slightly overstates coverage.
**Fix:** Reword the final banner to "kubectl-checkable assertions PASSED — PREP-02
swap still requires manual SSH verification" so the PASS line is not read as full
phase sign-off.

---

_Reviewed: 2026-06-13T17:24:57Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
