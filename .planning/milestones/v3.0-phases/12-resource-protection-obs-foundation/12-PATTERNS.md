# Phase 12: Resource Protection & Obs Foundation - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 9 (2 new manifests, 6 patched manifests, 1 new script, 1 CI workflow edit)
**Analogs found:** 9 / 9

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `k8s/staging/01-obs-rbac.yaml` | manifest / bootstrap RBAC | request-response (operator-once) | `k8s/staging/01-ci-rbac.yaml` | exact |
| `k8s/staging/02-priority-classes.yaml` | manifest / cluster-scoped config | config (operator-once) | `k8s/staging/00-namespace.yaml` (header/label pattern) + RESEARCH.md design | role-match |
| `k8s/staging/10-postgres.yaml` (patch) | manifest / StatefulSet | CRUD | self (existing file being patched) | self |
| `k8s/staging/20-rabbitmq.yaml` (patch) | manifest / StatefulSet | CRUD | `k8s/staging/10-postgres.yaml` | exact |
| `k8s/staging/35-server-2-deployment.yaml` (patch) | manifest / Deployment | CRUD | self (existing file being patched) | self |
| `k8s/staging/40-replay-parser-2.yaml` (patch) | manifest / Deployment | CRUD | `k8s/staging/35-server-2-deployment.yaml` | exact |
| `k8s/staging/50-replays-fetcher.yaml` (patch) | manifest / CronJob | batch | `k8s/staging/35-server-2-deployment.yaml` (pod template location) | role-match |
| `k8s/staging/60-postgres-backup.yaml` (patch) | manifest / CronJob | batch | `k8s/staging/35-server-2-deployment.yaml` (pod template location) | role-match |
| `scripts/resource-preflight.sh` | script / operational | request-response (re-runnable) | `scripts/backup-postgres-now.sh` | role-match |
| `scripts/validate-phase-12.sh` | script / validation | request-response (CI gate) | `scripts/backup-postgres-now.sh` + `scripts/validate-staging.py` style | role-match |
| `.github/workflows/deploy-staging.yml` (patch) | CI workflow | config | self (glob exclusion lines 72 and 130) | self |

---

## Pattern Assignments

### `k8s/staging/01-obs-rbac.yaml` (bootstrap RBAC manifest, operator-once)

**Analog:** `k8s/staging/01-ci-rbac.yaml` (lines 1-78) — exact structural mirror.

**File header pattern** (lines 1-4 of analog):
```yaml
# Operator-applied bootstrap manifest — DO NOT apply from CI.
# This file is applied ONCE by the operator: kubectl apply -f k8s/staging/01-obs-rbac.yaml
# CI (GitHub Actions) never applies this file. The deploy glob must exclude
# 01-obs-rbac.yaml so that each master-push deploy does not overwrite operator-managed RBAC.
```

**Namespace declarations** — copy from `k8s/staging/00-namespace.yaml` label style (lines 1-7):
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    app.kubernetes.io/part-of: solid-stats
    solid-stats.io/environment: staging
---
apiVersion: v1
kind: Namespace
metadata:
  name: error-tracking
  labels:
    app.kubernetes.io/part-of: solid-stats
    solid-stats.io/environment: staging
```

**ServiceAccount pattern** (analog lines 6-13):
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: obs-ci-deployer
  namespace: monitoring          # repeat block for error-tracking
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
```

**Long-lived token Secret pattern** (analog lines 15-28):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: obs-ci-deployer-token
  namespace: monitoring          # repeat for error-tracking
  annotations:
    kubernetes.io/service-account.name: obs-ci-deployer
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
type: kubernetes.io/service-account-token
```

**Role pattern** (analog lines 30-61) — same verb set as `ci-deployer` plus `daemonsets`:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: obs-ci-deployer
  namespace: monitoring
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services", "configmaps", "secrets", "persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch"]
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch"]
```

**RoleBinding pattern** (analog lines 62-78):
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: obs-ci-deployer
  namespace: monitoring
  labels:
    app.kubernetes.io/name: obs-ci-deployer
    app.kubernetes.io/part-of: solid-stats
roleRef:
  kind: Role
  name: obs-ci-deployer
  apiGroup: rbac.authorization.k8s.io
subjects:
  - kind: ServiceAccount
    name: obs-ci-deployer
    namespace: monitoring
```

Repeat the SA + Secret + Role + RoleBinding block verbatim with `namespace: error-tracking`.

**Document order:** Namespace(monitoring) → Namespace(error-tracking) → SA(monitoring) → Secret(monitoring) → Role(monitoring) → RoleBinding(monitoring) → SA(error-tracking) → Secret(error-tracking) → Role(error-tracking) → RoleBinding(error-tracking).

---

### `k8s/staging/02-priority-classes.yaml` (cluster-scoped config, operator-once)

**Analog for header/labels:** `k8s/staging/00-namespace.yaml` label block; `k8s/staging/01-ci-rbac.yaml` file header.

**PriorityClass is non-namespaced** — no `namespace:` field in metadata. Standard labels still apply.

**File header** (copy from 01-ci-rbac.yaml pattern):
```yaml
# Operator-applied bootstrap manifest — DO NOT apply from CI.
# Applied once: kubectl apply -f k8s/staging/02-priority-classes.yaml
```

**Full manifest** (from RESEARCH.md § PriorityClass Design, lines 191-210 — verified against k8s docs):
```yaml
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: app-critical
  labels:
    app.kubernetes.io/part-of: solid-stats
value: 1000000
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: >-
  Runtime app workloads (postgres, server-2, replay-parser-2, etc).
  Evicted after obs-background pods under node memory pressure.
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: obs-background
  labels:
    app.kubernetes.io/part-of: solid-stats
value: 100
preemptionPolicy: PreemptLowerPriority
globalDefault: false
description: >-
  Observability workloads (Prometheus, Grafana, Loki, etc).
  Evicted before app-critical pods under node memory pressure.
```

---

### `k8s/staging/10-postgres.yaml` (patch — Guaranteed QoS + priorityClassName)

**Analog:** self. Current state (lines 45-81):

Current `spec.template.spec` (line 45-48):
```yaml
    spec:
      serviceAccountName: postgres
      automountServiceAccountToken: false
      containers:
```

**Add `priorityClassName` immediately after the pod spec opens, before `serviceAccountName`:**
```yaml
    spec:
      priorityClassName: app-critical   # ADD — eviction protection
      serviceAccountName: postgres
      automountServiceAccountToken: false
```

Current resources block (lines 75-81):
```yaml
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 2Gi
```

**Replace with Guaranteed QoS (requests == limits). Values are ASSUMED — operator must verify with `kubectl top pods` before committing:**
```yaml
          resources:
            requests:
              cpu: 500m      # raised from 250m to match limit; verify against live P95
              memory: 1Gi    # raised from 512Mi to match limit; verify against live P95
            limits:
              cpu: 500m      # lowered from 1; MUST be >= observed P95 to avoid throttle
              memory: 1Gi    # lowered from 2Gi; MUST be >= observed P95 to avoid OOM
```

**Verify after apply:** `kubectl -n solid-stats-staging get pod postgres-0 -o jsonpath='{.status.qosClass}'` must return `Guaranteed`.

---

### `k8s/staging/20-rabbitmq.yaml` (patch — priorityClassName only)

**Analog:** `k8s/staging/10-postgres.yaml` (StatefulSet pattern).

Same `priorityClassName: app-critical` injection into `spec.template.spec` before `serviceAccountName`. No QoS change required (PREP-04 scope is postgres + server-2 only). No resource value changes.

---

### `k8s/staging/35-server-2-deployment.yaml` (patch — Guaranteed QoS + priorityClassName)

**Analog:** self. Current state (lines 28-83):

Current pod spec opening (lines 28-31):
```yaml
    spec:
      serviceAccountName: server-2
      automountServiceAccountToken: false
      imagePullSecrets:
```

**Add `priorityClassName` before `serviceAccountName`:**
```yaml
    spec:
      priorityClassName: app-critical   # ADD
      serviceAccountName: server-2
      automountServiceAccountToken: false
```

Current resources block (lines 73-78):
```yaml
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 1Gi
```

**Replace with Guaranteed QoS (ASSUMED values — verify live usage first):**
```yaml
          resources:
            requests:
              cpu: 250m      # raised from 100m; verify against live P95
              memory: 512Mi  # raised from 256Mi; verify against live P95
            limits:
              cpu: 250m      # lowered from 1; MUST be >= observed P95
              memory: 512Mi  # lowered from 1Gi; MUST be >= observed P95
```

**Note:** `initContainers` (wait-for-postgres, wait-for-rabbitmq at lines 33-47) currently have no `resources:` blocks. For true Guaranteed QoS every container including initContainers must have requests==limits. Add minimal resource blocks to both initContainers:
```yaml
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              cpu: 10m
              memory: 16Mi
```

---

### `k8s/staging/40-replay-parser-2.yaml` (patch — priorityClassName only)

**Analog:** `k8s/staging/35-server-2-deployment.yaml`. Pod spec opens at line 28-30 (same pattern).

Inject `priorityClassName: app-critical` before `serviceAccountName: replay-parser-2`. No resource or QoS changes.

---

### `k8s/staging/50-replays-fetcher.yaml` and `k8s/staging/60-postgres-backup.yaml` (patch — priorityClassName only)

**Analog:** `k8s/staging/35-server-2-deployment.yaml` pod template location pattern.

For CronJobs the priority goes in `spec.jobTemplate.spec.template.spec.priorityClassName`. Same injection point — before `serviceAccountName`. No resource changes.

---

### `scripts/resource-preflight.sh` (new operational script)

**Analog:** `scripts/backup-postgres-now.sh` (lines 1-38) for shebang + strict mode + kubectl invocation style.

**Shebang + strict mode pattern** (analog lines 1-2):
```bash
#!/usr/bin/env bash
set -euo pipefail
```

**Default env var with fallback pattern** (analog line 4 style — no `required()` because KUBECONFIG defaults to current context):
```bash
: "${NAMESPACE:=solid-stats-staging}"
: "${OUTPUT_DIR:=${PREFLIGHT_OUTPUT_DIR:-/tmp}}"
```

**kubectl invocation style** (analog line 8 — `-n "$namespace"` pattern, lowercase local vars):
```bash
kubectl -n "${NAMESPACE}" get pods ...
kubectl describe node
kubectl top nodes || echo "(metrics-server not available)"
```

**Output capture pattern** (analog line 18 — capture to var + print):
```bash
snapshot_ts="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="${OUTPUT_DIR}/resource-preflight-${snapshot_ts}.txt"
{ ... } | tee "${out_file}"
echo "Snapshot written to: ${out_file}"
```

**Full script structure** from RESEARCH.md § Resource Preflight (lines 342-384) is production-ready and should be copied directly, as it already follows all project conventions.

---

### `scripts/validate-phase-12.sh` (new validation script)

**Analog:** `scripts/backup-postgres-now.sh` for bash style; `scripts/validate-staging.py` `require()` pattern adapted to bash.

**Shebang + strict mode** (same as all scripts):
```bash
#!/usr/bin/env bash
set -euo pipefail
```

**Assertion helper pattern** (adapted from `validate-staging.py` `require()` at line 103-105):
```bash
assert() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL: ${label} — got '${actual}', want '${expected}'" >&2
    exit 1
  fi
  echo "ok: ${label}"
}
```

**kubectl namespace pattern** (from backup-postgres-now.sh line 4):
```bash
namespace="${K8S_NAMESPACE:-solid-stats-staging}"
```

**auth can-i negative assertion pattern:**
```bash
result="$(kubectl auth can-i get pods \
  --as=system:serviceaccount:monitoring:obs-ci-deployer \
  -n solid-stats-staging)"
assert "obs-ci-deployer cannot access solid-stats-staging" "$result" "no"
```

---

### `.github/workflows/deploy-staging.yml` (patch — glob exclusion)

**Analog:** self. The exclusion pattern is at lines 72 and 130 (identical in dry-run and deploy steps):

**Current pattern** (lines 72, 130):
```bash
find k8s/staging -maxdepth 1 -name '*.yaml' ! -name '00-namespace.yaml' ! -name '01-ci-rbac.yaml' | sort | sed 's/^/-f /' | \
  xargs kubectl apply -n "$K8S_NAMESPACE" --dry-run=server
```

**Patched pattern** — add two more `! -name` clauses in the same style:
```bash
find k8s/staging -maxdepth 1 -name '*.yaml' \
  ! -name '00-namespace.yaml' \
  ! -name '01-ci-rbac.yaml' \
  ! -name '01-obs-rbac.yaml' \
  ! -name '02-priority-classes.yaml' \
  | sort | sed 's/^/-f /' | \
  xargs kubectl apply -n "$K8S_NAMESPACE" --dry-run=server
```

Apply the same change to both the dry-run step (line 72) and the deploy step (line 130). Preserve the comment above the find command explaining the exclusion rationale — extend it to name the two new files.

---

## Shared Patterns

### Numeric filename prefix ordering
**Source:** `k8s/staging/` directory convention.
**Apply to:** All new manifests.
- `01-` tier: operator-applied bootstrap RBAC (excluded from CI glob by name)
- `02-` tier: operator-applied cluster-scoped config (excluded from CI glob by name)
- `10+` tier: CI-managed workload manifests

### Standard Kubernetes labels
**Source:** `k8s/staging/00-namespace.yaml` lines 4-6, `k8s/staging/01-ci-rbac.yaml` lines 11-12.
**Apply to:** All new manifest `metadata.labels` blocks.
```yaml
labels:
  app.kubernetes.io/name: <resource-name>   # omit for Namespace and PriorityClass (no workload name)
  app.kubernetes.io/part-of: solid-stats
```
For Namespace resources also add: `solid-stats.io/environment: staging`

### Non-default ServiceAccount + automountServiceAccountToken: false
**Source:** `k8s/staging/10-postgres.yaml` lines 46-47, `k8s/staging/35-server-2-deployment.yaml` lines 29-30.
**Apply to:** All workload pod specs (already present; do not remove when patching).
```yaml
      serviceAccountName: <workload-name>
      automountServiceAccountToken: false
```

### Operator-bootstrap file header comment
**Source:** `k8s/staging/01-ci-rbac.yaml` lines 1-4.
**Apply to:** `01-obs-rbac.yaml` and `02-priority-classes.yaml`.
```yaml
# Operator-applied bootstrap manifest — DO NOT apply from CI.
# Applied once: kubectl apply -f k8s/staging/<filename>.yaml
```

### Bash script strict mode
**Source:** `scripts/backup-postgres-now.sh` lines 1-2.
**Apply to:** `scripts/resource-preflight.sh`, `scripts/validate-phase-12.sh`.
```bash
#!/usr/bin/env bash
set -euo pipefail
```

### kubectl namespace variable
**Source:** `scripts/backup-postgres-now.sh` line 4.
**Apply to:** Both new scripts.
```bash
namespace="${K8S_NAMESPACE:-solid-stats-staging}"
```

---

## validate-staging.py Impact

`scripts/validate-staging.py` maintains `EXPECTED_MANIFESTS` (lines 33-44) and `validate_scripts` (lines 200-211). Phase 12 additions:

- `01-obs-rbac.yaml` and `02-priority-classes.yaml` are **operator-bootstrap** files — do NOT add to `EXPECTED_MANIFESTS` (that list is CI-managed manifests only; bootstrap files are excluded from CI glob).
- `scripts/resource-preflight.sh` and `scripts/validate-phase-12.sh` are Bash scripts — add to the `validate_scripts` bash syntax check list (lines 204-211) alongside the existing `backup-postgres-now.sh`.
- `EXPECTED_WORKLOADS` entries for postgres and server-2 already exist (lines 68-70). The `validate_workload_safety` check (line 287) asserts `resources:` + `requests:` + `limits:` are present — patched manifests will continue to satisfy this.

---

## No Analog Found

None. All new files have close analogs in the codebase.

---

## Metadata

**Analog search scope:** `k8s/staging/`, `scripts/`, `.github/workflows/`
**Files scanned:** 8 source files read directly
**Pattern extraction date:** 2026-06-13
