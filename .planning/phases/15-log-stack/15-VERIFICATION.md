---
phase: 15-log-stack
verified: 2026-06-14T07:10:00Z
status: gaps_found
score: 11/12 must-haves verified
overrides_applied: 0
gaps:
  - truth: "deploy-observability.yml rollout verification extended with loki statefulset + alloy daemonset (15-04 must-have artifact)"
    status: failed
    reason: >-
      The 15-04 plan declared artifact .github/workflows/deploy-observability.yml with
      provides "rollout verification extended with loki statefulset + alloy daemonset"
      (contains "loki"). The 15-04 SUMMARY frontmatter also lists this file under
      key_files.modified. Git proves NO Phase 15 commit ever touched this file (last
      changed in Phase 13: 04c5624, 93a8711); `git log -S` for the loki/alloy rollout
      lines returns empty. The "Verify rollouts" step (lines 92-99) still only checks
      prometheus-server, grafana, kube-state-metrics, node-exporter, postgres-exporter.
      Loki StatefulSet and Alloy DaemonSet ARE applied by the existing
      `find k8s/observability -maxdepth 1` glob, but their rollout is never asserted in
      CI — a future master-push deploy could silently fail to roll out Loki/Alloy.
      Goal-impact: LOW. This is a CI-hardening gap, not a goal blocker — the live log
      stack is fully functional and was independently re-validated by the verifier.
    artifacts:
      - path: ".github/workflows/deploy-observability.yml"
        issue: >-
          "Verify rollouts" step omits `kubectl rollout status statefulset/loki` and
          `kubectl rollout status daemonset/alloy`; file was not modified in Phase 15
          despite the 15-04 must-have and SUMMARY claim.
    missing:
      - "Add `kubectl -n monitoring rollout status statefulset/loki --timeout=300s` to the Verify rollouts step"
      - "Add `kubectl -n monitoring rollout status daemonset/alloy --timeout=120s` to the Verify rollouts step"
deferred:
  - truth: >-
      Re-runnable whole-stack validation (incl. a Loki query) failing loudly on any
      broken capability — the broader concern behind the missing CI rollout check
    addressed_in: "Phase 17"
    evidence: >-
      Phase 17 (Network Isolation & Stack Validation, depends on Phase 15) Success
      Criterion 3: "A re-runnable validation script verifies the full stack on a fresh
      staging deploy: Prometheus target health, Grafana datasource health, a Loki query,
      and a forced GlitchTip test event — failing loudly on any broken capability."
      Note: Phase 17 owns a validation SCRIPT; the gap above is specifically the CI
      deploy-workflow `rollout status` step, which is narrower. Kept as a real gap
      (conservative) rather than fully deferred.
---

# Phase 15: Log Stack (Loki + Grafana Alloy) Verification Report

**Phase Goal:** Cluster logs collected conservatively into Loki (bounded retention), queryable in Grafana as a 2nd datasource, without leaking request bodies or secrets.
**Verified:** 2026-06-14T07:10:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

The phase **goal itself is fully achieved and was independently re-verified live** by the
verifier (not trusting SUMMARY claims): `validate-phase-15.sh` PASSED against the live
cluster in the verifier's own process, and the LOG-02 no-leakage discipline was confirmed
by querying the LIVE Loki stream labels directly. All 3 ROADMAP success criteria are met.

A single plan-level must-have (15-04 CI `deploy-observability.yml` rollout verification for
loki/alloy) is **FAILED** — claimed in the plan + SUMMARY but git-proven never implemented.
This is a CI-hardening gap that does **not** block the phase goal (Loki/Alloy are applied by
the existing apply glob; only the post-apply rollout assertion is missing). Per the
verification decision tree, one failed must-have ⇒ `status: gaps_found`.

### Observable Truths

| #   | Truth (source plan)                                                                                       | Status     | Evidence                                                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Loki renders as a SingleBinary StatefulSet (not SimpleScalable read/write/backend) (15-01)                | ✓ VERIFIED | `70-loki.yaml` L205-207 `kind: StatefulSet`, L264-265 `-target=all`, L218 `replicas: 1`; values L22 `deploymentMode: SingleBinary`, all micro-replicas 0 |
| 2   | Loki uses filesystem storage on ~10Gi PVC with compactor retention ~168h (15-01)                          | ✓ VERIFIED | `70-loki.yaml` config L46-51 compactor `retention_enabled: true`, L64 `retention_period: 168h`, L86-89 `object_store: filesystem`, L338 PVC `10Gi`        |
| 3   | validate-phase-15.sh asserts LOG-01/02/03 with corrected metric names (15-01)                             | ✓ VERIFIED | Script L111 `loki_boltdb_shipper_compactor_running`, L159 `loki_write_sent_entries_total`, LOG-03 datasource health + LogQL; `bash -n` clean              |
| 4   | Alloy renders as a DaemonSet that tails via k8s API (no hostPath, no privileged) (15-02)                  | ✓ VERIFIED | `80-alloy.yaml` L135 `kind: DaemonSet`, L87 `loki.source.kubernetes`, no hostPath volume (only config configMap L219-222), no privileged securityContext  |
| 5   | Alloy relabels to exactly {namespace,pod,container,app,job} + drops monitoring ns (no bodies/secrets) (15-02) | ✓ VERIFIED | `80-alloy.yaml` L93-98 `stage.label_keep` allowlist of exactly 5 keys; L43-48 monitoring-ns drop rule FIRST. **Live stream labels confirm** (see Data-Flow). |
| 6   | Alloy ClusterRole/ClusterRoleBinding live in 03-alloy-rbac.yaml, NOT in CI-applied 80-alloy.yaml (15-02)  | ✓ VERIFIED | `03-alloy-rbac.yaml` holds ClusterRole+CRB (read-only get/list/watch); `80-alloy.yaml` has NO ClusterRole; values L118-119 `rbac.create: false`           |
| 7   | validate-obs-manifests.py fails any k8s/observability/*.yaml containing a ClusterRole (15-02)             | ✓ VERIFIED | `validate-obs-manifests.py` L47 `_FORBIDDEN_OBS_KINDS`, L170 `_check_no_clusterrole`, L238 wired into `validate()`; gate ran green (15 files)             |
| 8   | Prometheus scrapes loki:3100/metrics and alloy:12345/metrics as two static targets (15-03)                | ✓ VERIFIED | `10-prometheus.yaml` L35-38 `job_name: loki` → loki.monitoring.svc:3100, L27-30 `job_name: alloy` → alloy.monitoring.svc:12345                            |
| 9   | Grafana provisions Loki as a 2nd (non-default) datasource at loki.monitoring.svc:3100 (15-03)             | ✓ VERIFIED | `50-grafana.yaml` L79-86 `type: loki`, `url: http://loki.monitoring.svc:3100`, `isDefault: false`, `access: proxy`; Prometheus stays `isDefault: true`    |
| 10  | Live: Loki+Alloy Running, PVC Bound; compactor_running==1 and sent_entries>0 (15-04)                       | ✓ VERIFIED | **Verifier re-ran `validate-phase-15.sh` live**: loki Running, PVC Bound, compactor gauge==1, `loki_write_sent_entries_total`=16877                       |
| 11  | Live: Loki is a healthy Grafana datasource and LogQL returns recent server-2 lines (15-04)                | ✓ VERIFIED | **Live**: Loki datasource id=2 health OK; LogQL `{namespace="solid-stats-staging",app=~"server-2.*"}` returned 5 entries                                  |
| 12  | deploy-observability.yml rollout verification extended with loki statefulset + alloy daemonset (15-04)     | ✗ FAILED   | "Verify rollouts" step (L92-99) omits loki/alloy; git proves file untouched in Phase 15 (`-S` search empty). Claimed in SUMMARY but never implemented.    |

**Score:** 11/12 truths verified

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Re-runnable whole-stack validation incl. a Loki query, failing loudly on broken capability (broader concern behind truth 12) | Phase 17 | Phase 17 SC3: re-runnable script verifying Prometheus targets, Grafana datasources, a Loki query, forced GlitchTip event. NOTE: Phase 17 owns a *script*; truth 12 is the narrower CI deploy-workflow `rollout status` step — kept as a real gap, not fully deferred. |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `k8s/observability/values/loki-values.yaml` | Loki SingleBinary/filesystem/compactor values | ✓ VERIFIED | `deploymentMode: SingleBinary`, replication_factor 1, 168h retention, 10Gi PVC, caches+canary disabled |
| `k8s/observability/70-loki.yaml` | Rendered StatefulSet + Service + ConfigMap (monitoring) | ✓ VERIFIED | StatefulSet `-target=all`, Service `loki:3100`, no ClusterRole, security context hardened (runAsNonRoot, drop ALL, RO rootfs) |
| `scripts/validate-phase-15.sh` | Live LOG-01..03 harness | ✓ VERIFIED | Corrected metric names; LOG-01/02/03 assertions; ran PASS live |
| `k8s/observability/values/alloy-values.yaml` | Alloy DaemonSet values + conservative pipeline | ✓ VERIFIED | `controller.type: daemonset`, 5-label `stage.label_keep`, `rbac.create:false`, mem 192Mi |
| `k8s/observability/80-alloy.yaml` | Rendered DaemonSet + Service + ConfigMap + SA (no ClusterRole) | ✓ VERIFIED | DaemonSet, Service `alloy:12345`, River pipeline matches values, no ClusterRole |
| `k8s/staging/03-alloy-rbac.yaml` | Operator-bootstrap Alloy ClusterRole + CRB (read-only) | ✓ VERIFIED | ClusterRole get/list/watch on pods/pods log/namespaces/events/endpoints/services; CRB → SA alloy/monitoring; no secrets verb |
| `scripts/validate-obs-manifests.py` | Static gate forbids ClusterRole in obs dir | ✓ VERIFIED | `_check_no_clusterrole` wired into `validate()`; gate green on 15 files |
| `k8s/observability/values/prometheus-values.yaml` | loki + alloy scrape jobs | ✓ VERIFIED | `loki:`/`alloy:` per-job maps `enabled: true` (chart map style — renders to job_name; "Missing pattern job_name" is a false positive, see Anti-Patterns) |
| `k8s/observability/10-prometheus.yaml` | Re-rendered config with loki + alloy targets | ✓ VERIFIED | `job_name: loki`/`job_name: alloy` present; serviceAccountName prometheus; no ClusterRole |
| `k8s/observability/values/grafana-values.yaml` | Loki datasource entry | ✓ VERIFIED | Loki in `datasources.datasources.yaml.datasources` list (chart has no additionalDataSources key) |
| `k8s/observability/50-grafana.yaml` | Re-rendered with Prometheus + Loki datasources | ✓ VERIFIED | Both `type: prometheus` (default) and `type: loki` present; no ClusterRole |
| `.github/workflows/deploy-observability.yml` | Rollout verification extended w/ loki + alloy | ✗ STUB/UNCHANGED | File exists but rollout step never extended for loki/alloy; not modified in Phase 15 (git-proven) |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `70-loki.yaml` | `loki-values.yaml` | helm render input `deploymentMode: SingleBinary` | ✓ WIRED | Values + render consistent; StatefulSet `-target=all` single-binary |
| `validate-phase-15.sh` | loki/alloy/grafana live APIs | corrected metric queries | ✓ WIRED | Live run PASSED; both corrected metrics queried |
| `03-alloy-rbac.yaml` CRB | alloy SA in monitoring | `subjects` SA name alloy/monitoring | ✓ WIRED | CRB L43-46 → SA alloy/monitoring matches rendered SA |
| Alloy River pipeline | Loki push API | `loki.monitoring.svc:3100/loki/api/v1/push` | ✓ WIRED | `80-alloy.yaml` L101-105; live `sent_entries`=16877 confirms data flows |
| `10-prometheus.yaml` | loki + alloy Services | static_configs targets | ✓ WIRED | alloy.monitoring.svc:12345 + loki.monitoring.svc:3100 present |
| `50-grafana.yaml` | Loki Service | provisioned datasource url | ✓ WIRED | `http://loki.monitoring.svc:3100`; live datasource id=2 health OK |
| `deploy-observability.yml` | loki/alloy rollout | `kubectl rollout status` | ✗ NOT_WIRED | Rollout step does not reference loki StatefulSet or alloy DaemonSet |

### Data-Flow Trace (Level 4 — LOG-02 leakage verification against LIVE data)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| Loki (server-2 stream) | stream labels | Alloy River pipeline → Loki push | Yes — live | ✓ FLOWING |

**Live Loki stream labels on a server-2 entry (verifier-queried, not SUMMARY-claimed):**
`{app: server-2, container: server-2, job: solid-stats-staging/server-2, namespace: solid-stats-staging, pod: server-2-5c58b84c77-2bcjb, detected_level: unknown, service_name: server-2}`

- The 5 allowlisted labels (`app`, `container`, `job`, `namespace`, `pod`) are present and correct — exactly what `stage.label_keep` permits.
- `service_name` and `detected_level` are **Loki-side auto-derived** labels (Loki 3.x `discover_service_name` / `discover_log_levels`), NOT pushed by Alloy. Low-cardinality, derived from existing labels / log level — not request bodies, not secrets.
- **No request-body content, no secret values, no high-cardinality identifiers** (no IPs, annotations, tokens, env vars) appear as labels. The label-level `/api/v1/labels` set is `{__stream_shard__, app, container, job, namespace, pod, service_name}` — clean.
- **Conclusion: LOG-02 no-leakage discipline holds at the live data layer.**

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Static obs gate passes | `python3 scripts/validate-obs-manifests.py` | exit 0, "validated 15 manifest file(s)" | ✓ PASS |
| validate-phase-15.sh syntax | `bash -n scripts/validate-phase-15.sh` | clean | ✓ PASS |
| validator syntax | `python3 -c "ast.parse(...)"` | clean | ✓ PASS |
| Live LOG-01 compactor | live `loki_boltdb_shipper_compactor_running` query | == 1 | ✓ PASS |
| Live LOG-02 shipping | live `loki_write_sent_entries_total` query | 16877 (>0) | ✓ PASS |
| Live LOG-03 datasource + LogQL | `validate-phase-15.sh` (full, with port-forward) | datasource id=2 OK; LogQL 5 entries | ✓ PASS |
| Live LOG-02 label leakage | live Loki `/api/v1/labels` + server-2 stream | allowlist + Loki auto labels only | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| Phase 15 live validation | `bash /tmp/phase15/scripts/validate-phase-15.sh` (verifier's own process, read-only) | "=== Phase 15 validation PASSED ===" | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| LOG-01 | 15-01, 15-03, 15-04 | Loki monolithic/filesystem, ~7d compactor retention, right-sized PVC | ✓ SATISFIED | SingleBinary StatefulSet, filesystem, retention 168h, 10Gi PVC; live compactor==1, PVC Bound |
| LOG-02 | 15-02, 15-04 | Alloy DaemonSet, labels limited to 5, no bodies/secrets | ✓ SATISFIED | 5-label `stage.label_keep`, monitoring-ns drop; live stream labels confirm allowlist; read-only RBAC |
| LOG-03 | 15-01, 15-03, 15-04 | Loki healthy Grafana datasource, LogQL returns server-2 lines | ✓ SATISFIED | Live datasource id=2 health OK; LogQL returned 5 server-2 entries |

All three LOG requirements map exclusively to Phase 15 (no orphaned requirements). REQUIREMENTS.md marks all three `[x]` / Complete.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER in any of the 11 phase-15 files | ℹ️ Info | Clean |
| `prometheus-values.yaml` | — | gsd verify.artifacts flagged "Missing pattern: job_name" | ℹ️ Info (false positive) | Values uses chart per-job map style (`loki:`/`alloy:` keys); renders to `job_name: loki`/`alloy` in 10-prometheus.yaml. Truth satisfied. |
| `deploy-observability.yml` | 92-99 | gsd verify.artifacts flagged "Missing pattern: loki" | 🛑 Blocker (gap) | Real: rollout verification not extended for loki/alloy (see Gap below) |

Note: `70-loki.yaml` StatefulSet image is `grafana/loki:3.6.7` (chart appVersion) even though `loki-values.yaml` pins `singleBinary.image.tag: 3.6.11` — the values key did not take effect in the render. Minor (same minor version, functional; live pod Running). Not goal-blocking; flagged for awareness only.

### Human Verification Required

None that block status. The LOG-03 Grafana-Explore visual log check is a documented manual
operator action (validate-phase-15.sh prints the instructions at the end) and is **treated as
accepted, not a gap**, per the verification scope. The verifier already confirmed the
underlying capability programmatically (live LogQL returned 5 server-2 entries via the same
Loki datasource).

### Gaps Summary

**Goal: ACHIEVED.** The Phase 15 goal — conservative log collection into Loki with bounded
retention, queryable in Grafana as a 2nd datasource, without leaking request bodies/secrets —
is fully delivered and was independently re-validated live by the verifier (not trusting
SUMMARY): all 3 ROADMAP success criteria pass live, and the LOG-02 no-leakage label discipline
was confirmed against the LIVE Loki stream label set.

**One plan-level gap (CI hardening, non-goal-blocking):** The 15-04 must-have to extend
`deploy-observability.yml`'s rollout verification with the Loki StatefulSet and Alloy DaemonSet
was **claimed in the 15-04 SUMMARY (`key_files.modified`) but git proves the file was never
touched in Phase 15** (last changed in Phase 13; `git log -S` for the rollout lines is empty).
The workflow still applies Loki/Alloy via its `find` glob, so they DO deploy — but a future
master-push deploy will not assert their rollout succeeded, so a broken Loki/Alloy rollout
could pass CI silently. Fix is two lines added to the "Verify rollouts" step:
`kubectl -n monitoring rollout status statefulset/loki` and `... daemonset/alloy`.

The broader "fail-loudly whole-stack validation including a Loki query" concern is owned by
Phase 17 (SC3), but that is a validation *script*; this gap is the narrower CI *deploy-workflow*
rollout assertion, so it is kept as a real (not fully deferred) gap. Recommend closing the
two-line addition rather than waiting for Phase 17.

---

_Verified: 2026-06-14T07:10:00Z_
_Verifier: Claude (gsd-verifier)_
