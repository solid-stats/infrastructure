---
phase: 13-deploy-pipeline-metrics-stack
verified: 2026-06-14T05:20:00Z
status: human_needed
score: 14/14 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Set the three GitHub `staging` environment secrets so the CI obs-deploy path is runnable: K8S_OBS_TOKEN (obs-ci-deployer token), GRAFANA_ADMIN_PASSWORD, PG_MONITOR_PASSWORD"
    expected: "All three secrets present in the staging environment; `deploy-observability.yml` can render obs Secrets and deploy without operator SSH. (gh secret set ... --env staging — see docs/observability.md §4)"
    why_human: "Auto-mode classifier gates agent-driven GitHub-secret writes (persistent config beyond live-staging ops); the plan marked them operator-provided. The stack already runs live from directly-applied k8s Secrets, so this only unblocks the repeatable CI deploy. Accepted follow-up, not a phase gap."
  - test: "Confirm Grafana dashboards render non-zero live data (visual): kubectl -n monitoring port-forward svc/grafana 3000:80, open http://localhost:3000 (admin / GRAFANA_ADMIN_PASSWORD), open the Node Exporter, PostgreSQL, RabbitMQ, and kube-state dashboards"
    expected: "Each dashboard shows populated panels with non-zero metric values (not empty / no-data)"
    why_human: "Panel rendering is a visual confirmation that cannot be asserted programmatically. validate-phase-13.sh confirms datasource health OK + 4 dashboards provisioned, but not pixel-level panel population. Documented manual operator action (MET-06)."
---

# Phase 13: Deploy Pipeline & Metrics Stack Verification Report

**Phase Goal:** A complete metrics stack (Prometheus, Grafana, kube-state-metrics, node-exporter, postgres/rabbitmq metrics) runs on staging via a deploy path independent of runtime CD, dashboards rendering live data, validated internally, no public edge yet.
**Verified:** 2026-06-14T05:20:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is **achieved in the codebase and on the live cluster.** All four ROADMAP success criteria and all ten requirements (DEP-01..04, MET-01..06) are substantively satisfied. The metrics stack is live in the `monitoring` namespace (all 5 obs pods Running, all 5 Prometheus targets UP), deployed via an independent `deploy-observability.yml` workflow with no coupling to runtime CD, with no public ingress/TLS.

Status is `human_needed` (not `passed`) solely because two **documented, accepted operator/visual follow-ups** remain — neither blocks the live stack: (1) the three GitHub environment secrets for the *repeatable CI* deploy path, and (2) the MET-06 visual non-zero-panel confirmation. Both are explicitly listed in the verification-context accepted-followups and in `docs/observability.md`.

### Observable Truths

| #   | Truth (source) | Status | Evidence |
| --- | -------------- | ------ | -------- |
| 1 | SC1 / DEP-01: obs manifests rendered with `helm template`, committed under `k8s/observability/` | VERIFIED | 14 files under `k8s/observability/` (5 values, 5 workload YAMLs, 4 dashboard JSONs); each YAML carries `helm.sh/chart` provenance + reproducible render command in header comment; `validate-obs-manifests.py` passed (11 manifest files) |
| 2 | SC1 / DEP-02: applied by a separate `deploy-observability.yml` (own concurrency group, obs-ci-deployer + WireGuard) | VERIFIED | `.github/workflows/deploy-observability.yml` L11-13 `concurrency.group: infrastructure-obs-deploy`; L61 `K8S_OBS_TOKEN`; L64 `obs-ci-deployer`; L48-57 WireGuard; L89 applies `k8s/observability/*.yaml` maxdepth 1 |
| 3 | SC1 / DEP-03: runtime deploy does not depend on obs deploy | VERIFIED | `deploy-staging.yml` has separate group `infrastructure-staging-deploy`, no `needs`/reference to obs, and explicitly excludes `01-obs-rbac.yaml` (`! -name '01-obs-rbac.yaml'`) in both dry-run + deploy globs; `validate-staging.py` exit 0 after rabbitmq edits |
| 4 | SC1 / DEP-04: all obs secrets rendered from GitHub env into k8s Secrets, no secret values in git | VERIFIED (live) + follow-up | `render-obs-secrets.py` emits grafana-secrets + postgres-monitor-secret from env (exit 64 if missing); `validate-obs-manifests.py` secret-pattern gate passes; live Secrets applied (13-05). CI-path GitHub secrets = accepted operator follow-up (human item 1) |
| 5 | SC2 / MET-01: Prometheus standalone (no operator/CRDs), tuned scrape interval, bounded retention sized to PVC, Running | VERIFIED (live) | `10-prometheus.yaml` L173-174 `--storage.tsdb.retention.time=15d` + `.size=5GB`, 8Gi PVC (L75), scrape_interval 30s; no CRDs/operator; **live**: prometheus-server 2/2 Running, `/api/v1/status/config` contains `15d` |
| 6 | SC2 / MET-02: kube-state-metrics + node-exporter targets UP | VERIFIED (live) | `20-kube-state-metrics.yaml` (ClusterIP:8080), `30-node-exporter.yaml` (DaemonSet:9100); scrape jobs in prometheus.yml; **live `/api/v1/targets`**: both `up` |
| 7 | SC2 / MET-03: postgres-exporter UP, app ≥ v0.15.0, non-superuser pg_monitor, pg_up==1 | VERIFIED (live) | `40-postgres-exporter.yaml` app v0.19.1, DSN from `postgres-monitor-secret` secretKeyRef (no inline DSN); **live**: target `up`, `pg_up == 1`, `SELECT rolsuper WHERE rolname='solid_monitor'` → `f` (non-superuser) |
| 8 | SC2 / MET-04: RabbitMQ scraped via native plugin (port 15692, no separate exporter) | VERIFIED (live) | `20-rabbitmq.yaml` enabled_plugins `[rabbitmq_management,rabbitmq_prometheus].`, Service+containerPort 15692; prometheus scrape job `rabbitmq.solid-stats-staging.svc:15692`; **live**: target `up`, `rabbitmq_identity_info` present; no separate exporter workload |
| 9 | SC3 / MET-05: Grafana with Prometheus provisioned as healthy datasource | VERIFIED (live) | `50-grafana.yaml` datasource `http://prometheus-server.monitoring.svc:80` isDefault, admin creds from grafana-secrets (no inline); **live**: `/api/datasources/1/health` → OK; grafana 2/2 Running |
| 10 | SC3 / MET-06: 4 standard dashboards provisioned as code, rendering live data | VERIFIED (provisioned) + visual follow-up | `60-grafana-dashboards.yaml` 4 ConfigMaps labelled `grafana_dashboard=1` (node-exporter/kube-state/postgresql/rabbitmq); sidecar LABEL=grafana_dashboard; **live**: `/api/search` → 4 dashboards. Non-zero-panel visual = accepted manual op (human item 2) |
| 11 | SC4: operator reaches Grafana internally (port-forward/ClusterIP), no public ingress/TLS | VERIFIED | Grafana Service type ClusterIP (port 80); validate-phase-13.sh uses `port-forward svc/grafana 13000:80`; no Ingress/TLS resource in any obs manifest; docs §"Verify" documents port-forward 3000:80 |
| 12 | 13-04: Prometheus runtime SA + read-only ClusterRole/Binding in operator-bootstrap 01-obs-rbac.yaml (not CI manifests) | VERIFIED | `01-obs-rbac.yaml` L177-220: SA prometheus/monitoring + ClusterRole `prometheus-monitoring` (get/list/watch only, no write verbs) + ClusterRoleBinding; file header marks operator-applied; excluded from CI glob |
| 13 | 13-01: validation harness asserts all MET-01..06 live checks, exits 1 on first failure | VERIFIED | `validate-phase-13.sh` asserts target health==up, pg_up==1, rabbitmq_identity_info present, datasource OK, dashboards≥4; `bash -n` clean; ran live → "Phase 13 validation PASSED" exit 0 |
| 14 | 13-06: observed working set recorded; ASSUMED sizing confirmed adequate | VERIFIED | `docs/observability.md` L20-30 measured footprint table (~290Mi total); 13-06 decision: no re-render needed, values adequate; live node ~51% memory after deploy |

**Score:** 14/14 truths verified (2 carry an accepted human/operator follow-up that does not block the live goal)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `k8s/observability/10-prometheus.yaml` | Prometheus Deploy/CM/Svc/PVC (MET-01) | ✓ VERIFIED | 228 lines; retention 15d+5GB, 8Gi PVC, SA prometheus, obs-background, 5 scrape jobs, ns monitoring |
| `k8s/observability/20-kube-state-metrics.yaml` | KSM workload (MET-02) | ✓ VERIFIED | 315 lines; ClusterIP:8080, obs-background, ns monitoring |
| `k8s/observability/30-node-exporter.yaml` | node-exporter DaemonSet (MET-02) | ✓ VERIFIED | 179 lines; DaemonSet:9100, obs-background, ns monitoring |
| `k8s/observability/40-postgres-exporter.yaml` | postgres-exporter Deploy+Svc (MET-03) | ✓ VERIFIED | 147 lines; v0.19.1, DSN from postgres-monitor-secret, no inline DSN, obs-background |
| `k8s/observability/50-grafana.yaml` | Grafana + datasource/sidecar (MET-05) | ✓ VERIFIED | 395 lines; prometheus-server datasource, sidecar grafana_dashboard, grafana-secrets, obs-background, fsGroup 472, no helm-test Pod |
| `k8s/observability/60-grafana-dashboards.yaml` | 4 dashboard ConfigMaps (MET-06) | ✓ VERIFIED | 4 ConfigMaps, 4 grafana_dashboard labels, 4 ns monitoring |
| `k8s/observability/values/*.yaml` | helm values (5 files) | ✓ VERIFIED | prometheus/ksm/node-exporter/postgres-exporter/grafana values present, consistent with rendered output |
| `k8s/staging/01-obs-rbac.yaml` | Prometheus runtime SA + SD ClusterRole | ✓ VERIFIED | prometheus-monitoring ClusterRole read-only; operator-applied bootstrap |
| `k8s/staging/20-rabbitmq.yaml` | rabbitmq 15692 + enabled_plugins (MET-04) | ✓ VERIFIED | port 15692 + plugin ConfigMap + subPath mount |
| `.github/workflows/deploy-observability.yml` | Independent obs CI deploy (DEP-02/03) | ✓ VERIFIED | own concurrency group, obs-ci-deployer, render-obs-secrets step, rollout verify |
| `scripts/render-obs-secrets.py` | Render obs Secrets from env (DEP-04) | ✓ VERIFIED | exit 64 on missing env; emits both Secrets; no values in git |
| `scripts/validate-obs-manifests.py` | Static gate | ✓ VERIFIED | exit 0 on 11 files; secret/ns/priorityClass checks + render-error guard |
| `scripts/validate-phase-13.sh` | Live MET-01..06 harness | ✓ VERIFIED | live run PASSED exit 0 |
| `docs/observability.md` | Operator runbook | ✓ VERIFIED | 135 lines; RBAC, pg_monitor SQL, GitHub secrets §4, preflight, deploy, verify, recovery |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `10-prometheus.yaml` | `01-obs-rbac.yaml` | `serviceAccountName: prometheus` → pre-created SA + ClusterRoleBinding | ✓ WIRED | SA name matches; binding subject = prometheus/monitoring; live targets UP confirm SD-free static scrape works |
| `40-postgres-exporter.yaml` | `postgres-monitor-secret` | DATA_SOURCE_NAME secretKeyRef dsn | ✓ WIRED | L108-112 secretKeyRef; live pg_up==1 proves DSN resolves + connects |
| `50-grafana.yaml` | `10-prometheus.yaml` | datasource url prometheus-server.monitoring.svc:80 | ✓ WIRED | L78 url; live datasource health OK |
| `60-grafana-dashboards.yaml` | `50-grafana.yaml` sidecar | ConfigMap label grafana_dashboard discovered by sidecar | ✓ WIRED | sidecar LABEL/LABEL_VALUE env = grafana_dashboard/1; live /api/search → 4 dashboards |
| `50-grafana.yaml` | `grafana-secrets` | admin.existingSecret + admin-user/admin-password keys | ✓ WIRED | GF_SECURITY_ADMIN_USER/PASSWORD from grafana-secrets; live grafana Running (no CreateContainerConfigError) |
| `deploy-observability.yml` | `render-obs-secrets.py` + `kubeconfig-setup.sh` | render step + obs-ci-deployer kubeconfig | ✓ WIRED | L66 kubeconfig-setup K8S_USER_NAME=obs-ci-deployer; L76 render-obs-secrets.py |
| live cluster RBAC | `01-obs-rbac.yaml` | operator kubectl apply | ✓ WIRED | 13-05 applied; `auth can-i create clusterroles` as obs-ci-deployer → no (trap confirmed); ClusterRole live |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| Grafana datasource | Prometheus query results | prometheus-server (live, 5 targets UP) | Yes — datasource health OK, targets scraping | ✓ FLOWING |
| postgres-exporter | pg_* metrics | live solid_stats DB via solid_monitor role | Yes — pg_up==1 | ✓ FLOWING |
| rabbitmq metrics | rabbitmq_* metrics | native plugin :15692 | Yes — rabbitmq_identity_info present | ✓ FLOWING |
| Dashboard panels (visual) | node/pg/rmq/ksm panels | provisioned dashboards + datasource | Provisioned; non-zero render not auto-asserted | ⚠️ Visual op check (human item 2) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Static manifest gate | `python3 scripts/validate-obs-manifests.py` | "PASSED", 11 files, exit 0 | ✓ PASS |
| Secret renderer missing-env | `python3 scripts/render-obs-secrets.py` (no env) | exit 64 | ✓ PASS |
| Secret renderer with env | `GRAFANA_ADMIN_PASSWORD=.. PG_MONITOR_PASSWORD=.. render-obs-secrets.py` | valid Secret YAML, both keys, no git values | ✓ PASS |
| Live harness syntax | `bash -n scripts/validate-phase-13.sh` | clean | ✓ PASS |
| Runtime manifests unbroken | `python3 scripts/validate-staging.py` | exit 0 | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| Live MET-01..06 harness | `ssh root@89.223.124.200 'GRAFANA_ADMIN_PASSWORD=$(...) bash /tmp/phase13/scripts/validate-phase-13.sh'` | "Phase 13 validation PASSED", exit 0 — MET-01..06 all ok | PASS |
| Live pods | `kubectl -n monitoring get pods` | grafana 2/2, prometheus 2/2, ksm/node-exporter/postgres-exporter Running | PASS |
| Live targets | `kubectl -n monitoring exec deploy/prometheus-server -- wget .../api/v1/targets` | 5 targets, all `up` | PASS |
| Live pg_monitor role | `kubectl -n solid-stats-staging exec postgres-0 -- psql ... rolsuper` | `solid_monitor\|f` (non-superuser) | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| DEP-01 | 13-02, 13-03 | manifests rendered + committed under k8s/observability/ | ✓ SATISFIED | 14 files; helm provenance; static gate passes |
| DEP-02 | 13-04 | deploy-observability.yml with own concurrency group | ✓ SATISFIED | infrastructure-obs-deploy group |
| DEP-03 | 13-04 | runtime deploy independent of obs deploy | ✓ SATISFIED | separate workflow/group; 01-obs-rbac excluded; validate-staging.py green |
| DEP-04 | 13-01, 13-05 | no secret values in git; rendered from env | ✓ SATISFIED (live) | render-obs-secrets.py + static gate + live Secrets; GitHub-secret CI wiring = accepted operator follow-up |
| MET-01 | 13-02, 13-06 | Prometheus Running, retention bounded to PVC | ✓ SATISFIED | live Running; 15d/5GB on 8Gi |
| MET-02 | 13-02, 13-06 | KSM + node-exporter targets UP | ✓ SATISFIED | live both up |
| MET-03 | 13-02, 13-05, 13-06 | postgres-exporter UP, pg_up==1, non-superuser | ✓ SATISFIED | live up, pg_up==1, rolsuper=f |
| MET-04 | 13-04, 13-06 | RabbitMQ via native plugin 15692 | ✓ SATISFIED | live up, rabbitmq_identity_info present, no separate exporter |
| MET-05 | 13-03, 13-06 | Grafana datasource healthy (as code) | ✓ SATISFIED | live datasource health OK |
| MET-06 | 13-03, 13-06 | ≥4 dashboards provisioned + render live | ✓ SATISFIED (provisioned) | live 4 dashboards; non-zero-panel visual = accepted manual op |

No orphaned requirements — all ten DEP/MET IDs are claimed by plans and mapped to verified evidence.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in any phase-modified file | ℹ️ Info | Clean — completion is auditable |
| — | — | No inline secret literals in committed YAML (only secretKeyRef + automountServiceAccountToken booleans) | ℹ️ Info | DEP-04 secret hygiene holds |

### Human Verification Required

1. **GitHub `staging` environment secrets for the CI obs-deploy path**
   - **Test:** Add `K8S_OBS_TOKEN` (obs-ci-deployer token), `GRAFANA_ADMIN_PASSWORD`, `PG_MONITOR_PASSWORD` to the `staging` GitHub environment (`gh secret set ... --env staging`).
   - **Expected:** `deploy-observability.yml` renders the obs Secrets and deploys in CI without operator SSH.
   - **Why human / accepted follow-up:** Auto-mode classifier gates agent-driven GitHub-secret writes (persistent config beyond live-staging ops); the plan marked these operator-provided. **The live stack already runs from directly-applied k8s Secrets** (13-05) — this only unblocks the repeatable CI deploy. Documented in `docs/observability.md` §4 and 13-05-SUMMARY. This is an accepted operator follow-up, **not a phase gap**.

2. **MET-06 dashboards render non-zero live data (visual)**
   - **Test:** `kubectl -n monitoring port-forward svc/grafana 3000:80`, open `http://localhost:3000`, open the Node Exporter / PostgreSQL / RabbitMQ / kube-state dashboards.
   - **Expected:** Populated panels with non-zero values (not empty / no-data).
   - **Why human:** Visual panel rendering cannot be asserted programmatically. The harness confirms datasource health OK + 4 dashboards provisioned + all underlying targets UP (so data is flowing); only the pixel-level panel population needs a human glance. Documented manual operator action.

### Gaps Summary

**No blocking gaps.** Every ROADMAP success criterion and every DEP/MET requirement is substantively achieved, with the live metrics stack running in the `monitoring` namespace (verified by re-running the validation harness and live kubectl in this verifier's own process, not trusting SUMMARY claims). All artifacts exist, are substantive, are wired, and have real data flowing through them.

Two items remain as **accepted, documented human/operator follow-ups** that do not block the phase goal:
- DEP-04 CI-path GitHub environment secrets (the stack runs live now from directly-applied k8s Secrets; only the repeatable CI deploy needs them) — classifier-gated, plan-designated operator action.
- MET-06 non-zero-panel visual confirmation — inherently visual.

Because the status decision tree routes any non-empty human-verification section to `human_needed`, the overall status is `human_needed` rather than `passed`. There is nothing for `/gsd-plan-phase --gaps` to fix; the two items are operator/visual actions, captured in `human_verification` frontmatter.

---

_Verified: 2026-06-14T05:20:00Z_
_Verifier: Claude (gsd-verifier)_
