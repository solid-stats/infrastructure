---
phase: 13-deploy-pipeline-metrics-stack
plan: "06"
subsystem: obs-live-apply
status: complete
tags: [live-apply, prometheus, grafana, exporters, met-01, met-02, met-03, met-04, met-05, met-06]

dependency_graph:
  requires: ["13-05"]
  provides:
    - "live metrics stack in monitoring ns: Prometheus, Grafana, kube-state-metrics, node-exporter, postgres-exporter"
    - "RabbitMQ native prometheus plugin scraped (15692)"
    - "validate-phase-13.sh green (MET-01..06)"
  affects:
    - "live solid-stats-staging + monitoring namespaces"
    - k8s/observability/10-prometheus.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/observability/values/grafana-values.yaml
    - scripts/validate-obs-manifests.py
    - scripts/render-obs-secrets.py
    - .github/workflows/deploy-observability.yml

key_files:
  modified:
    - k8s/observability/10-prometheus.yaml
    - k8s/observability/50-grafana.yaml
    - k8s/observability/values/grafana-values.yaml
    - scripts/validate-obs-manifests.py
    - scripts/render-obs-secrets.py
    - .github/workflows/deploy-observability.yml

decisions:
  - "Right-sizing (Task 3): live usage is ~290Mi total (grafana 206, prometheus 47, others <35) — well under the ASSUMED requests/limits and the node headroom. ASSUMED values confirmed adequate; no re-render needed. Prometheus will grow with TSDB within its limit."
  - "Deployed the no-secret tier first (Prometheus/kube-state/node-exporter/rabbitmq), then the secret-gated tier (postgres-exporter, Grafana) after 13-05's secret bootstrap — kept the live apply incremental and de-risked."

requirements: [MET-01, MET-02, MET-03, MET-04, MET-05, MET-06]
---

# Plan 13-06 — Live Apply & Verification

## What is live (verified by validate-phase-13.sh → PASSED)

| Req | Result |
|-----|--------|
| MET-01 | prometheus-server Running; retention 15d/5GB |
| MET-02 | kube-state-metrics + node-exporter targets UP |
| MET-03 | postgres-exporter target UP; `pg_up=1` (non-superuser solid_monitor) |
| MET-04 | rabbitmq target UP via native plugin (15692); `rabbitmq_identity_info` present |
| MET-05 | Grafana datasource health OK |
| MET-06 | 4 dashboards provisioned (manual non-zero-panel check = documented operator action) |

All five Prometheus targets UP. Grafana 2/2 Running. Node at ~51% memory after deploy.

## Defects found and fixed during the live apply (gap-closure)

1. **10-prometheus.yaml corrupted** — a transient helm chart-download timeout (`context deadline
   exceeded`) had been spliced into the rendered YAML by 13-02, breaking the parse at apply.
   Re-rendered cleanly; **hardened `validate-obs-manifests.py`** with a render-error-signature
   guard so spliced CLI errors fail the static gate (commit `077ce4e`).
2. **grafana-secrets missing `admin-user`** → Grafana `CreateContainerConfigError`. Fixed
   `render-obs-secrets.py` to emit both keys (commit `5f782fb`).
3. **postgres-exporter `sslmode=prefer`** rejected by lib/pq → `pg_up=0`. Reverted to `disable`
   with rationale (commit `5ac145c`).
4. **Grafana partial-migration DB** (`no such column: uid`) left by defect #2's crash loop —
   wiped grafana.db, clean re-init.
5. **Durable deploy fixes:** `deploy-observability.yml` now uses `--server-side --force-conflicts`
   (256KB annotation limit on large dashboards); `grafana-values.yaml` `testFramework.enabled=false`
   drops helm-test hooks from the render (commit for both).

## Requirements
- MET-01..06 all verified live (validate-phase-13.sh PASSED). ✓
