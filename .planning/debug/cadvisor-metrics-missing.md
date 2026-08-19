---
status: resolved
trigger: >-
  Prometheus exposes node-exporter metrics but stores no Kubernetes
  container/cAdvisor resource metrics, so pod P95 usage and CPU throttling
  cannot be assessed.
created: 2026-08-20
updated: 2026-08-20
---

# Debug Session: cAdvisor Metrics Missing

## Symptoms

- Expected behavior: Prometheus scrapes the k3s kubelet cAdvisor endpoint and
  stores current container resource series with namespace, pod, and container
  labels.
- Actual behavior: node-exporter metrics are available, but no `container_*`
  cAdvisor resource series are stored.
- Error messages: no cAdvisor target existed to report a scrape error; direct
  kubelet access at `89.223.124.200:10250` returned connection refused.
- Timeline: observed on 2026-08-20; prior observability plans intentionally
  disabled the default cAdvisor scrape job.
- Reproduction: query Prometheus for the required `container_*` metrics and
  inspect `/api/v1/targets`, scrape errors, kubelet `/metrics/cadvisor`, and
  Prometheus service-account authorization.

## Current Focus

- hypothesis: confirmed — the Helm values disabled the only cAdvisor job.
  No cAdvisor target could exist in the rendered configuration.
- test: live Prometheus config had no cAdvisor job; the mounted Prometheus token
  fetched a current labeled cAdvisor series through the Kubernetes API proxy.
  Enabled a proxy-based node-discovery job, rendered v29.11.0, deployed it, and
  queried the resulting series through Grafana's Prometheus datasource.
- expecting: met — one `kubernetes-nodes-cadvisor` target is `up`, all five
  required metrics are non-empty, and workload series have `namespace`, `pod`,
  and `container` labels.
- next_action: accumulate 7–14 representative days before reassessing
  `server-2` and PostgreSQL CPU limits.

## Evidence

- timestamp: 2026-08-20;
  `k8s/observability/values/prometheus-values.yaml:90-92` set
  `kubernetes-nodes-cadvisor.enabled: false` before this fix.
- timestamp: 2026-08-20; rendered `k8s/observability/10-prometheus.yaml:21-59`
  had seven jobs and no `kubernetes-nodes-cadvisor` entry before this fix.
- timestamp: 2026-08-20; live Prometheus `prometheus.yml` also has no cAdvisor
  job, and Grafana has no required `container_*` series.
- timestamp: 2026-08-20; pinned chart v29.11.0 renders an enabled job with node
  discovery, a service-account bearer token, and an API-server proxy path of
  `/api/v1/nodes/$1/proxy/metrics/cadvisor`.
- timestamp: 2026-08-20; `k8s/staging/01-obs-rbac.yaml:197-230` binds
  Prometheus to a ClusterRole containing `nodes/metrics`. Kubernetes maps
  kubelet `/metrics/*` requests to that subresource.
  <https://kubernetes.io/docs/reference/access-authn-authz/kubelet-authn-authz/>
- timestamp: 2026-08-20; direct kubelet access at
  `89.223.124.200:10250` was refused, while the authenticated Kubernetes API
  proxy path succeeded from the Prometheus pod. The final job uses the proxy;
  no NetworkPolicy change is required.
- timestamp: 2026-08-20; `.github/workflows/deploy-observability.yml:112-129`
  applies both the rendered Prometheus manifest and monitoring NetworkPolicy.
  No deploy-path change is needed.
- timestamp: 2026-08-20; local checks passed: exact Helm render comparison for
  chart v29.11.0, `python3 scripts/validate-obs-manifests.py`,
  `bash -n scripts/validate-phase-13.sh`, and `git diff --check`.
- timestamp: 2026-08-20; the new static gate rejected a simulated disabled
  Helm value and missing rendered cAdvisor job.
- timestamp: 2026-08-20; a request from the Prometheus pod using its mounted
  ServiceAccount token returned `container_cpu_cfs_periods_total` with non-empty
  `namespace`, `pod`, and `container` labels through the kubelet cAdvisor path.
- timestamp: 2026-08-20T01:28:58+07:00; the first successful Prometheus scrape
  for `kubernetes-nodes-cadvisor` was recorded. The target is `up` and reports
  4,295 scraped samples.
- timestamp: 2026-08-20; Grafana queries returned current labeled series for
  `container_cpu_usage_seconds_total` (25),
  `container_cpu_cfs_throttled_periods_total` (16),
  `container_cpu_cfs_periods_total` (16),
  `container_memory_working_set_bytes` (25), and
  `container_oom_events_total` (24).
- timestamp: 2026-08-20; direct PromQL returned pod-level CPU P95, memory P95,
  and CPU throttling percentages grouped by namespace and pod. No recording
  rule or dashboard change is required to compute them.

## Eliminated

- RBAC absence as the repository root cause: the ServiceAccount, ClusterRole,
  and ClusterRoleBinding already exist. `nodes/metrics` is the least-privilege
  permission for kubelet metric endpoints; CAD-01 still verifies live access.
- NetworkPolicy as a blocking cause: authenticated Kubernetes API proxy
  connectivity worked from Prometheus before the change.
- A CI deployment omission: the workflow applies `10-prometheus.yaml` and
  `95-netpol-monitoring.yaml` in its monitoring step.
- Missing namespace/pod/container labels as a configuration concern: cAdvisor
  emits the container series; CAD-01 rejects any result without all three labels.

## Resolution

- root_cause: The sole cAdvisor scrape job was disabled in the Helm input and
  omitted from the deployed Prometheus configuration.
- fix: Enable a `kubernetes-nodes-cadvisor` node-discovery job that scrapes the
  kubelet endpoint through the authenticated Kubernetes API proxy, commit its
  exact render, and add static plus live regression gates.
- verification: The live target is `up`; all five required metrics are non-empty
  with namespace, pod, and container labels. Usable accumulation began at
  2026-08-20T01:28:58+07:00. Repository validation and exact Helm-render
  comparison pass.
- files_changed: `k8s/observability/values/prometheus-values.yaml`,
  `k8s/observability/10-prometheus.yaml`,
  `scripts/validate-obs-manifests.py`, `scripts/validate-phase-13.sh`, and
  `.planning/debug/cadvisor-metrics-missing.md`.
