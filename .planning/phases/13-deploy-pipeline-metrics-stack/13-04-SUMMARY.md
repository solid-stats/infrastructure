---
phase: 13-deploy-pipeline-metrics-stack
plan: "04"
subsystem: observability
status: complete
tags: [observability, prometheus, rabbitmq, rbac, ci-workflow, metrics, kubernetes]
completed: "2026-06-14"
duration_minutes: 18
tasks_completed: 3
files_created: 1
files_modified: 2

dependency_graph:
  requires:
    - k8s/staging/01-obs-rbac.yaml (operator-bootstrap, operator-applied)
    - k8s/staging/20-rabbitmq.yaml (runtime manifest, CI-applied)
    - scripts/kubeconfig-setup.sh (13-01 or earlier)
    - scripts/render-obs-secrets.py (13-01)
    - scripts/validate-obs-manifests.py (13-01)
  provides:
    - k8s/staging/01-obs-rbac.yaml (Prometheus SA + read-only ClusterRole/ClusterRoleBinding appended)
    - k8s/staging/20-rabbitmq.yaml (port 15692 + enabled_plugins ConfigMap)
    - .github/workflows/deploy-observability.yml (independent obs CI deploy)
  affects:
    - k8s/observability/10-prometheus.yaml (references serviceAccountName: prometheus pre-created here)
    - 13-05 (operator must apply 01-obs-rbac.yaml + add GitHub secrets K8S_OBS_TOKEN/GRAFANA_ADMIN_PASSWORD/PG_MONITOR_PASSWORD)
    - 13-06 (live apply of 20-rabbitmq.yaml triggers rolling restart of rabbitmq-0)

tech_stack:
  added:
    - rabbitmq_prometheus native plugin (enabled via enabled_plugins ConfigMap mount)
    - GitHub Actions deploy-observability.yml workflow
  patterns:
    - operator-bootstrap ClusterRole pattern (Pitfall 2 mitigation: obs-ci-deployer is namespace-scoped)
    - Erlang term list format for enabled_plugins (Pitfall 5: period-terminated)
    - mktemp + trap EXIT secret render (T-13-15: no secrets in logs)
    - independent CI concurrency group (DEP-03: obs failure cannot block runtime CD)

key_files:
  created:
    - .github/workflows/deploy-observability.yml
  modified:
    - k8s/staging/01-obs-rbac.yaml
    - k8s/staging/20-rabbitmq.yaml

decisions:
  - "Prometheus ClusterRole in 01-obs-rbac.yaml (operator-applied): obs-ci-deployer is namespace-scoped, cannot create ClusterRole; bootstrap file already excluded from all CI globs"
  - "rabbitmq enabled_plugins ConfigMap (not env var): declarative, git-auditable, triggers rolling restart only on change; period-terminated Erlang term list per RabbitMQ docs"
  - "deploy-observability.yml separate workflow (not job in deploy-staging.yml): DEP-03 requires zero coupling; separate workflow = separate concurrency group, separate failure domain"
  - "render-obs-secrets.py to mktemp with trap-rm (T-13-15): secrets never touch CI log output"
  - "k8s/observability -maxdepth 1 in apply step: values/ and dashboards/ are helm inputs, not applied directly"

commits:
  - hash: 90a509f
    message: "feat(13-04): add Prometheus runtime SA + read-only ClusterRole to 01-obs-rbac.yaml"
  - hash: 23f8e1f
    message: "feat(13-04): rabbitmq port 15692 + enabled_plugins ConfigMap (MET-04)"
  - hash: 04c5624
    message: "feat(13-04): add deploy-observability.yml CI workflow (DEP-02, DEP-03)"
---

# Phase 13 Plan 04: Runtime Wiring — RBAC, RabbitMQ Plugin, Obs CI Workflow Summary

**One-liner:** Prometheus read-only ClusterRole added to operator-bootstrap file, rabbitmq port 15692 + enabled_plugins ConfigMap mounted in StatefulSet, independent deploy-observability.yml workflow authored with own concurrency group and obs-ci-deployer path — DEP-02, DEP-03, MET-04 satisfied.

## What Was Built

| File | Change | Key detail |
|------|--------|-----------|
| `k8s/staging/01-obs-rbac.yaml` | Appended SA + ClusterRole + ClusterRoleBinding | prometheus SA in monitoring; read-only verbs only (T-13-12) |
| `k8s/staging/20-rabbitmq.yaml` | ConfigMap + Service port + containerPort + volumeMount | enabled_plugins `[rabbitmq_management,rabbitmq_prometheus].`; ClusterIP only (T-13-13) |
| `.github/workflows/deploy-observability.yml` | New file | concurrency: infrastructure-obs-deploy; K8S_OBS_TOKEN; obs-ci-deployer; render-obs-secrets.py; rollout verify |

### Prometheus ClusterRole (01-obs-rbac.yaml addition)

Resources granted (read-only: get/list/watch):
- Core: `nodes`, `nodes/proxy`, `nodes/metrics`, `services`, `endpoints`, `pods`
- networking.k8s.io: `ingresses`
- nonResourceURLs: `/metrics`, `/metrics/cadvisor` (verb: get)

No write verbs. Applied by operator only — excluded from CI deploy globs in both `dry-run` and `deploy` jobs of `deploy-staging.yml`.

### RabbitMQ changes (20-rabbitmq.yaml)

```
ConfigMap rabbitmq-enabled-plugins:
  enabled_plugins: |
    [rabbitmq_management,rabbitmq_prometheus].

Service: ports amqp:5672 + management:15672 + prometheus:15692 (ClusterIP)
StatefulSet container: containerPort 15692 (name: prometheus)
volumeMount: /etc/rabbitmq/enabled_plugins subPath: enabled_plugins
volume: configMap rabbitmq-enabled-plugins
```

`validate-staging.py` passes after change. Rolling restart of `rabbitmq-0` (~30s AMQP downtime) is operator-gated in 13-06.

### deploy-observability.yml structure

| Property | Value |
|----------|-------|
| Concurrency group | `infrastructure-obs-deploy` (cancel-in-progress: false) |
| SA token | `secrets.K8S_OBS_TOKEN` → K8S_TOKEN env for kubeconfig-setup.sh |
| Kubeconfig user | `obs-ci-deployer`, context `obs-k3s-staging`, namespace `monitoring` |
| validate job | `test -d k8s/observability` + `validate-obs-manifests.py` |
| deploy job | WireGuard → kubeconfig → render secrets → apply manifests → verify rollouts |
| Manifest apply | `find k8s/observability -maxdepth 1 -name '*.yaml' | sort` |
| Rollouts verified | prometheus-server, grafana, kube-state-metrics, node-exporter (DS), postgres-exporter |
| Dependency on deploy-staging | None (DEP-03) |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All three artifacts are complete and self-consistent.

## Threat Flags

No new threat surface beyond the plan's threat model.

| Threat ID | Mitigation status |
|-----------|------------------|
| T-13-12 | ClusterRole verbs limited to get/list/watch; operator-applied only |
| T-13-13 | rabbitmq Service stays ClusterIP; no Ingress; port 15692 not externally exposed |
| T-13-14 | deploy-observability.yml has no `needs` on any deploy-staging job; separate concurrency group |
| T-13-15 | render-obs-secrets.py output to mktemp with `trap 'rm -f "$tmp"' EXIT` |
| T-13-SC | enabled_plugins term list pinned in ConfigMap; rolling restart operator-gated in 13-06 |

## Self-Check

- [x] `01-obs-rbac.yaml` contains `name: prometheus-monitoring` ClusterRole with get/list/watch only
- [x] `01-obs-rbac.yaml` contains ServiceAccount `prometheus` in namespace `monitoring`
- [x] `01-obs-rbac.yaml` contains ClusterRoleBinding `prometheus-monitoring` → SA prometheus/monitoring
- [x] No write verbs in prometheus-monitoring ClusterRole
- [x] `20-rabbitmq.yaml` contains `15692` (Service port + containerPort)
- [x] `20-rabbitmq.yaml` contains `rabbitmq_prometheus` in ConfigMap value
- [x] `20-rabbitmq.yaml` enabled_plugins value ends with `.` (Erlang term list)
- [x] `20-rabbitmq.yaml` volumeMount uses subPath `enabled_plugins`
- [x] `python3 scripts/validate-staging.py` exits 0
- [x] `deploy-observability.yml` contains `infrastructure-obs-deploy`
- [x] `deploy-observability.yml` contains `K8S_OBS_TOKEN`
- [x] `deploy-observability.yml` contains `obs-ci-deployer`
- [x] `deploy-observability.yml` contains `render-obs-secrets.py`
- [x] `git diff --quiet .github/workflows/deploy-staging.yml` passes (deploy-staging.yml unchanged)
- [x] Commits 90a509f, 23f8e1f, 04c5624 exist in git log

## Self-Check: PASSED
