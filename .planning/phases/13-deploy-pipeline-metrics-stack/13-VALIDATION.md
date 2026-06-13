---
phase: 13
slug: deploy-pipeline-metrics-stack
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 13 — Validation Strategy

> Infra phase: validation is helm-render checks + static secret/namespace scans + live kubectl/Prometheus-API assertions. No unit test framework.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Bash + kubectl + Prometheus/Grafana HTTP API (live-cluster checks) |
| **Static scan** | `scripts/validate-obs-manifests.py` (no secrets in git, namespace=monitoring, priorityClassName=obs-background) |
| **Live suite** | `scripts/validate-phase-13.sh` (created Wave 0) |
| **Quick run** | `bash scripts/validate-phase-13.sh --quick` |
| **Estimated runtime** | ~30s (remote kubectl + exec into prometheus) |

---

## Sampling Rate

- **After every task commit:** `python3 scripts/validate-obs-manifests.py` (static — fast, no cluster)
- **After every wave applied to cluster:** `bash scripts/validate-phase-13.sh`
- **Phase gate:** all targets UP + Grafana datasource healthy + ≥4 dashboards provisioned before verify
- **Max feedback latency:** ~30s

---

## Per-Requirement Verification Map

| Req | Behavior | Type | Command / Check | Status |
|-----|----------|------|-----------------|--------|
| DEP-01 | manifests rendered + committed under `k8s/observability/` | static | `find k8s/observability -name '*.yaml' \| wc -l` ≥ 5 | ⬜ |
| DEP-02 | `deploy-observability.yml` with own concurrency group | static | `grep 'infrastructure-obs-deploy' .github/workflows/deploy-observability.yml` | ⬜ |
| DEP-03 | runtime deploy independent of obs deploy | static | deploy-staging.yml references no obs job/needs | ⬜ |
| DEP-04 | no secret values in committed YAML | static | `python3 scripts/validate-obs-manifests.py` (secret-pattern grep) | ⬜ |
| MET-01 | Prometheus Running + retention bounded to PVC | live | pod phase Running; `/api/v1/status/config` shows tuned retention | ⬜ |
| MET-02 | kube-state-metrics + node-exporter targets UP | live | `/api/v1/targets` health=up for both jobs | ⬜ |
| MET-03 | postgres-exporter UP + `pg_up==1`, pg_monitor role | live | target up; `pg_up` metric == 1; role is non-superuser | ⬜ |
| MET-04 | RabbitMQ scraped via native plugin (15692) | live | target up; `rabbitmq_identity_info` present; no separate exporter | ⬜ |
| MET-05 | Grafana datasource healthy (provisioned as code) | live | `/api/datasources/.../health` status=OK | ⬜ |
| MET-06 | ≥4 dashboards provisioned + render live data | live+manual | `/api/search` ≥4; operator confirms non-zero panels | ⬜ |

*Status: ⬜ pending · ✅ green · ❌ red*

---

## Wave 0 Requirements

- [ ] `scripts/validate-phase-13.sh` — live MET-01..06 assertions (Prometheus targets API, Grafana API)
- [ ] `scripts/validate-obs-manifests.py` — static: no secrets, namespace=monitoring, obs-background on every pod spec
- [ ] `scripts/render-obs-secrets.py` — render Grafana admin / pg_monitor DSN into k8s Secrets from env (no git)
- [ ] vendored dashboard JSON (node-exporter 1860, kube-state/cluster, PostgreSQL, RabbitMQ) as ConfigMaps
- [ ] helm available for rendering (NOT installed locally — Wave 0 must install/obtain helm, then `helm template` → commit)

---

## Manual-Only Verifications

| Behavior | Req | Why Manual | Instructions |
|----------|-----|------------|--------------|
| Dashboards render live, non-zero data | MET-06 | visual confirmation | `kubectl -n monitoring port-forward svc/grafana 3000:80`, open dashboards, confirm panels populated |
| GitHub env secrets present | DEP-04 | operator-managed secret store | operator adds `K8S_OBS_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD` before CI obs-deploy |

---

## Security (ASVS L2)

- Grafana admin password + pg_monitor DSN from k8s Secret only (rendered from env; never in committed YAML).
- postgres-exporter uses the built-in non-superuser `pg_monitor` role — never a superuser DSN.
- Prometheus/Grafana/RabbitMQ-metrics on ClusterIP only — no Ingress/TLS in Phase 13 (deferred to Phase 14).
- obs-ci-deployer stays namespace-scoped; the only cluster-scoped grant is Prometheus's read-only SD ClusterRole, added to the operator-bootstrap `01-obs-rbac.yaml` (excluded from CI glob).

---

## Validation Sign-Off

- [ ] Every DEP/MET req has a static or live check (no requirement unverified)
- [ ] Wave 0 creates both validation scripts + secret renderer
- [ ] No secret values reachable in committed YAML (CI static gate)
- [ ] `nyquist_compliant: true` once plans wire all checks

**Approval:** pending
