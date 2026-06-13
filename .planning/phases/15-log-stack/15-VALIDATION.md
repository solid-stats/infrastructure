---
phase: 15
slug: log-stack
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-14
---

# Phase 15 — Validation Strategy

> Internal log stack (no public edge / no DNS gate). Validation is kubectl + Prometheus/Loki/
> Grafana HTTP API checks. Reuses the Phase 13 obs pipeline (helm-render → k8s/observability/).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Static** | `python3 scripts/validate-obs-manifests.py` (namespace=monitoring, obs-background, no secrets, no render-error splice) |
| **Live suite** | `scripts/validate-phase-15.sh` (created Wave 0; mirrors validate-phase-13.sh) |

> **Metric-name correction (from 15-RESEARCH):** the ROADMAP wrote `loki_compactor_runs_total`
> and `alloy_logs_entries_total`, which do NOT exist. The real proofs are
> `loki_boltdb_shipper_compactor_running` (gauge, 1=compactor active) and
> `loki_write_sent_entries_total` (Alloy `loki.write` counter). Validation uses the real names.

---

## Per-Requirement Verification Map

| Req | Behavior | Type | Check |
|-----|----------|------|-------|
| LOG-01 | Loki SingleBinary/filesystem Running, replication_factor 1, retention ~168h | live | loki pod Running; `loki_boltdb_shipper_compactor_running == 1`; config shows retention_period 168h + compactor retention_enabled |
| LOG-01 | Loki PVC right-sized + bound | live | `kubectl -n monitoring get pvc` loki bound, ~8–10Gi |
| LOG-02 | Alloy DaemonSet running, conservative labels, shipping | live | alloy DaemonSet desired==ready; `loki_write_sent_entries_total > 0`; stream labels ⊆ {namespace,pod,container,app,job} |
| LOG-02 | no request bodies / secrets in labels | static+live | Alloy config relabels to the allowed label set only; spot-check a Loki stream's labels |
| LOG-03 | Loki healthy Grafana datasource | live | `/api/datasources/.../health` (Loki) status OK |
| LOG-03 | LogQL returns recent server-2 lines | live | Loki query_range `{namespace="solid-stats-staging",app=~"server-2.*"}` returns ≥1 entry |

---

## Wave 0 Requirements

- [ ] `scripts/validate-phase-15.sh` — live LOG-01..03 assertions (Loki/Prometheus/Grafana/Loki-query APIs), corrected metric names
- [ ] Loki + Alloy scrape targets added to `k8s/observability/10-prometheus.yaml` (loki:3100/metrics, alloy:12345/metrics)
- [ ] `k8s/staging/03-alloy-rbac.yaml` — operator-bootstrap Alloy ClusterRole (rbac.create:false in chart; obs-ci-deployer can't create cluster RBAC) — read-only pods/pods log/namespaces

---

## Manual-Only Verifications

| Behavior | Req | Why | Instructions |
|----------|-----|-----|--------------|
| LogQL non-empty in Grafana Explore | LOG-03 | visual | port-forward Grafana, Explore → Loki → `{namespace="solid-stats-staging"}` shows server-2 lines |

---

## Security (LOG-02)

- Alloy pipeline relabels to namespace/pod/container/app/job ONLY; everything else dropped before `loki.write`. No structured-body parsing that could capture request bodies or secret values.
- Loki `auth_enabled: false` is acceptable (internal ClusterIP only; NetworkPolicy isolation in Phase 17).
- Alloy ClusterRole is read-only (get/list/watch pods, pods/log, namespaces).

---

## Validation Sign-Off

- [ ] Loki compactor active (gauge==1), Alloy shipping (counter>0), Loki datasource healthy, LogQL returns server-2 lines
- [ ] static gate green on the new rendered manifests
- [ ] `nyquist_compliant: true` once plans wire all checks

**Approval:** pending
