---
phase: 13-deploy-pipeline-metrics-stack
plan: "05"
subsystem: obs-bootstrap
status: complete
tags: [rbac, postgres, secrets, runbook, dep-04, met-03]

dependency_graph:
  requires: ["13-01", "13-02", "13-03", "13-04"]
  provides:
    - Prometheus SD RBAC live on the cluster
    - non-superuser solid_monitor (pg_monitor) role on live postgres
    - grafana-secrets + postgres-monitor-secret live in monitoring ns
    - docs/observability.md operator runbook
  affects:
    - docs/observability.md
    - "live cluster: prometheus SA/ClusterRole, solid_monitor role, monitoring Secrets"

key_files:
  created: [docs/observability.md]
  modified: []

decisions:
  - "GitHub environment secrets (K8S_OBS_TOKEN, GRAFANA_ADMIN_PASSWORD, PG_MONITOR_PASSWORD) are an OPERATOR follow-up: the auto-mode classifier gates agent-driven GitHub-secret writes (persistent config beyond live-staging ops), and the plan itself marked them operator-provided. The live k8s Secrets were created directly so the stack runs now; the CI deploy-observability.yml path needs the GitHub secrets set per docs/observability.md §4."
  - "postgres-exporter DSN uses sslmode=disable (lib/pq rejects 'prefer'; postgres serves no TLS so 'require' fails). Intra-cluster only; TLS deferred to a follow-up + Phase 17 NetworkPolicy."

requirements: [DEP-04, MET-03]
---

# Plan 13-05 — Observability Bootstrap

## Task 1 (auto) — docs/observability.md runbook ✓
Authored the operator runbook: stack overview, measured resource footprint, the one-time
bootstrap (Prometheus RBAC, pg_monitor role, secret render, GitHub secrets, storage preflight),
deploy + verify, and recovery notes (the Grafana admin-user / partial-DB pitfalls hit during 13-06).

## Task 2 (operator-gated) — live bootstrap

Executed live (operator-authorized SSH):
- **Prometheus RBAC** — `kubectl apply -f k8s/staging/01-obs-rbac.yaml`: SA `prometheus` +
  read-only ClusterRole `prometheus-monitoring` + binding created. RBAC trap confirmed:
  `obs-ci-deployer can-i create clusterroles → no`.
- **pg_monitor role** — created `solid_monitor` LOGIN role, `GRANT pg_monitor`, confirmed
  `rolsuper=false` on the live `solid_stats` DB.
- **Secrets** — `render-obs-secrets.py` → `grafana-secrets` + `postgres-monitor-secret` applied
  to `monitoring` (values never printed/committed).
- **Storage preflight** — `local-path` default SC; ~27G free on the node (ample for the PVCs).

Deferred to operator (classifier-gated): the three **GitHub environment secrets** for the CI
deploy path — see docs/observability.md §4. The stack runs now from the directly-applied k8s
Secrets; only the repeatable CI deploy needs the GitHub secrets.

## Requirements
- **DEP-04** secrets rendered from env into k8s Secrets, none in git. ✓ (GitHub-secret CI wiring = operator follow-up)
- **MET-03** non-superuser pg_monitor role provisioned for postgres-exporter. ✓
