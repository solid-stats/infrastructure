---
phase: 16-error-tracking-glitchtip
plan: "03"
subsystem: error-tracking
status: complete
tags: [glitchtip, kubernetes, secrets, ci, deploy, validate, observability]
completed: "2026-06-14T01:00:00Z"
duration: "~10 minutes"

dependency_graph:
  requires:
    - "16-01 — glitchtip-postgres-auth + glitchtip-secrets Secret names; 90-91 manifests"
    - "16-02 — 92-93 migrate/seed Jobs; validate-obs-manifests.py already accepts error-tracking"
    - "Phase 13 — render-obs-secrets.py pattern; deploy-observability.yml base workflow"
  provides:
    - "scripts/render-obs-secrets.py — extended to emit glitchtip-postgres-auth + glitchtip-secrets in error-tracking ns"
    - "scripts/split-obs-secrets.py — splits multi-ns rendered YAML by namespace for scoped CI tokens"
    - ".github/workflows/deploy-observability.yml — error-tracking deploy path (K8S_OBS_ET_TOKEN, GlitchTip steps)"
    - "scripts/validate-phase-16.sh — ERR-01/02/03 live harness (pods/valkey/migrate/reg-closed/forced-error)"
    - "scripts/test-glitchtip-ingest.sh — Sentry envelope POST ingest test via port-forward"
    - "docs/glitchtip.md — operator runbook (5 secrets, first-run order, cutover, troubleshooting)"
    - "k8s/staging/01-obs-rbac.yaml — error-tracking obs-ci-deployer Role gains batch/jobs verbs"
  affects:
    - "16-04 — live apply uses these scripts/workflow; seed-org step sets GLITCHTIP_DSN for ERR-03"
    - "16-05 — operator cutover uses docs/glitchtip.md + bootstrap-obs-edge.sh"

tech_stack:
  added:
    - "scripts/split-obs-secrets.py — stdlib Python helper for per-namespace secret routing"
    - "scripts/validate-phase-16.sh — bash live harness (kubectl + curl + python3 stdlib)"
    - "scripts/test-glitchtip-ingest.sh — bash Sentry envelope ingest test"
    - "docs/glitchtip.md — operator runbook"
  patterns:
    - "Multi-namespace secret renderer: secret() now takes explicit namespace arg; monitoring secrets byte-identical"
    - "Per-namespace CI token split: split-obs-secrets.py routes docs by namespace: field"
    - "Separate kubeconfig contexts (obs-k3s-staging / obs-et-k3s-staging) per token (T-16-11)"
    - "Port-forward ERR-02/03 validation pattern: wait-loop on /api/0/config/ + trap kill on EXIT"
    - "Sentry envelope format: 3-line newline-separated JSON (header + item-header + event payload)"

key_files:
  created:
    - scripts/split-obs-secrets.py
    - scripts/validate-phase-16.sh
    - scripts/test-glitchtip-ingest.sh
    - docs/glitchtip.md
  modified:
    - scripts/render-obs-secrets.py
    - .github/workflows/deploy-observability.yml
    - k8s/staging/01-obs-rbac.yaml

decisions:
  - "secret() takes explicit namespace arg instead of module-level NAMESPACE — minimal diff, monitoring callers pass 'monitoring' explicitly, all output byte-identical"
  - "split-obs-secrets.py as a standalone script instead of heredoc in workflow YAML — heredoc inside YAML run: blocks conflicts with the YAML parser; external script is also testable"
  - "validate-phase-16.sh uses pf_port=18000 (not 8000) to avoid conflict if operator has another port-forward running"
  - "ERR-03 VALKEY_URL check uses jsonpath filter on the web Deployment env array — direct assertion on the deployed spec, not pod logs"
  - "batch/jobs added to error-tracking obs-ci-deployer Role alongside cronjobs (16-02 flagged gap)"

metrics:
  tasks_total: 3
  tasks_completed: 3
  files_created: 4
  files_modified: 3
---

# Phase 16 Plan 03: Secret Renderer + Deploy Pipeline + Validation Scripts Summary

**One-liner:** Extended render-obs-secrets.py to emit GlitchTip error-tracking secrets (4 vars, url-encoded DATABASE_URL, sslmode=disable), wired a separate error-tracking CI deploy path (K8S_OBS_ET_TOKEN + split-by-namespace), and authored validate-phase-16.sh + test-glitchtip-ingest.sh + docs/glitchtip.md.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend render-obs-secrets.py for GlitchTip | 0f67421 | scripts/render-obs-secrets.py |
| 2 | Add GlitchTip deploy path to deploy-observability.yml | 8293f01 | .github/workflows/deploy-observability.yml, scripts/split-obs-secrets.py |
| 3 | validate-phase-16.sh + test-glitchtip-ingest.sh + docs + RBAC fix | 69d7afe | scripts/validate-phase-16.sh, scripts/test-glitchtip-ingest.sh, docs/glitchtip.md, k8s/staging/01-obs-rbac.yaml |

## What Was Built

### render-obs-secrets.py (extended)

`secret()` helper now takes an explicit `namespace` parameter (no module-level `NAMESPACE` constant).
Monitoring secrets (`grafana-secrets`, `postgres-monitor-secret`) pass `"monitoring"` — output is
byte-identical to the previous version. Added four `required()` reads for GlitchTip vars, all
exiting 64 on missing. Emits two new error-tracking Secrets:

- `glitchtip-postgres-auth` (error-tracking): `POSTGRES_PASSWORD`
- `glitchtip-secrets` (error-tracking): `SECRET_KEY`, `DATABASE_URL` (url-encoded password +
  `sslmode=disable` — same rationale as postgres-exporter DSN), `GLITCHTIP_SUPERUSER_EMAIL`,
  `GLITCHTIP_SUPERUSER_PASSWORD`

Total output: 4 Secret documents in a single multi-doc YAML.

### split-obs-secrets.py (new)

Takes the full rendered YAML and splits by `namespace:` field into two per-namespace files.
Replaces the heredoc approach (which breaks YAML parsing in GitHub Actions `run:` blocks).
Fully testable locally; verified that no cross-namespace leak occurs.

### deploy-observability.yml (extended)

Added without altering monitoring path behavior:

1. **Setup kubeconfig (obs-ci-deployer, error-tracking)** — builds `obs-et-k3s-staging` context using `K8S_OBS_ET_TOKEN`
2. **Render+apply obs secrets** — now splits by namespace; monitoring docs applied with monitoring context, error-tracking docs with et context
3. **Apply GlitchTip manifests (error-tracking)** — `find 9*-glitchtip*.yaml | xargs kubectl --context obs-et-k3s-staging apply --server-side`
4. **Verify GlitchTip rollouts** — statefulset/glitchtip-postgres + deployment/glitchtip-web + deployment/glitchtip-worker rollout status + `kubectl wait --for=condition=complete job/glitchtip-migrate`

Monitoring rollout steps retargeted to `--context obs-k3s-staging` (previously relied on default context — behavior unchanged).

### validate-phase-16.sh (new)

Live ERR-01/02/03 harness:

- **ERR-01**: `kubectl get pod` by label for postgres/web/worker; grep for valkey/redis workloads (must be absent); `job/glitchtip-migrate .status.succeeded == 1`; jsonpath on web Deployment env for `VALKEY_URL == ""`
- **ERR-02**: port-forward to `svc/glitchtip-web:18000`; wait-loop on `/api/0/config/`; Python parse for `user_registration_enabled: false` (Method A — reliable); best-effort POST to `/api/0/auth/registration/` (Method B)
- **ERR-03**: optional project count via `/api/0/projects/` with `SUPERUSER_TOKEN`; delegates to `test-glitchtip-ingest.sh` when `GLITCHTIP_DSN` is set

Flags: `--internal` (default, port-forward), `--public` (post-cutover URL), `--quick` (skip ingest).

### test-glitchtip-ingest.sh (new)

Forced-error ingest test:
1. Parses `PUBLIC_KEY` and `PROJECT_ID` from `GLITCHTIP_DSN` (format `http://KEY@host/ID`)
2. Port-forward to `svc/glitchtip-web:18000`; wait-loop until ready
3. Builds 3-line Sentry envelope per spec (header + item-header + event payload with unique timestamp marker)
4. POSTs to `/api/PROJECT_ID/envelope/` with `Content-Type: application/x-sentry-envelope`
5. Asserts HTTP 200 or 202; explicitly fails on 403 (Pitfall 8 — wrong DSN key)
6. If `SUPERUSER_TOKEN` set: polls issues API for the marker (up to 60s)
7. `exit 64` on missing `GLITCHTIP_DSN`

### docs/glitchtip.md (new)

Operator runbook covering:
- 5 secrets: `GLITCHTIP_SECRET_KEY/POSTGRES_PASSWORD/SUPERUSER_EMAIL/SUPERUSER_PASSWORD` with generation commands; `K8S_OBS_ET_TOKEN` with mint command
- First-run order (Wave 1 CI + Wave 2 operator 16-04 seed)
- Verification commands (`validate-phase-16.sh` + `test-glitchtip-ingest.sh`)
- Public URL cutover via `bootstrap-obs-edge.sh` with exact command
- Troubleshooting: worker CrashLoop (VALKEY_URL), migrate ordering, 403 DSN mismatch, OOMKill

### 01-obs-rbac.yaml (error-tracking Role fix)

Added `"jobs"` to the `batch` resources in the `error-tracking` obs-ci-deployer Role
(alongside existing `"cronjobs"`). Required for `kubectl apply` of 92/93 migrate/seed Jobs
and `kubectl wait --for=condition=complete job/glitchtip-migrate` in CI.

## Verification

```
python3 -m py_compile scripts/render-obs-secrets.py  # clean
GLITCHTIP_SECRET_KEY=x ... python3 scripts/render-obs-secrets.py | grep 'namespace: error-tracking'  # 2 hits
exit code 64 when GLITCHTIP_* missing  # confirmed
python3 scripts/validate-obs-manifests.py  # → PASSED (19 files)
python3 -c "import yaml; list(yaml.safe_load_all(open(...)))"  # workflow YAML valid
bash -n scripts/validate-phase-16.sh  # clean
bash -n scripts/test-glitchtip-ingest.sh  # clean
grep checks: user_registration_enabled, envelope, port-forward, ENABLE_USER_REGISTRATION, bootstrap-obs-edge.sh  # all pass
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced heredoc in workflow YAML with external split-obs-secrets.py**
- **Found during:** Task 2 verify step
- **Issue:** The plan suggested using a `<<'PYSPLIT'` heredoc inside a GitHub Actions `run: |` block to split the multi-doc secret YAML. A heredoc inside a YAML scalar string causes `python3 -c "import yaml; list(yaml.safe_load_all(...))"` to fail with `could not find expected ':'` at the PYSPLIT lines.
- **Fix:** Created `scripts/split-obs-secrets.py` as a standalone stdlib Python script; the workflow calls it as `python3 scripts/split-obs-secrets.py "$tmp_all" "$tmp_monitoring" "$tmp_et"`. Fully testable locally; no behavior change.
- **Files modified:** scripts/split-obs-secrets.py (new), .github/workflows/deploy-observability.yml (run step updated)
- **Commit:** 8293f01

**2. [Rule 2 - Missing] RBAC batch/jobs included in Task 3 commit**
- **Found during:** Task 3 — 16-02 SUMMARY documented the gap explicitly
- **Issue:** The error-tracking obs-ci-deployer Role had `batch/cronjobs` but not `batch/jobs`. CI cannot apply the migrate/seed Jobs (92-93) or `kubectl wait --for=condition=complete job/glitchtip-migrate` without this verb.
- **Fix:** Added `"jobs"` to the batch rule in the error-tracking Role in `k8s/staging/01-obs-rbac.yaml` (operator-bootstrap file; not CI-applied).
- **Files modified:** k8s/staging/01-obs-rbac.yaml
- **Commit:** 69d7afe

## Known Stubs

None — no hardcoded empty values or placeholder data. All secret references use `secretKeyRef`. The `GLITCHTIP_DSN` env var in validate-phase-16.sh/test-glitchtip-ingest.sh is intentionally optional pending the 16-04 seed step.

## Threat Flags

No new threat surface beyond the plan's `<threat_model>`. All T-16-1x mitigations implemented:
- T-16-10: rendered YAML written to `mktemp` temp files, trap-removed on EXIT; no values in CI logs
- T-16-11: `K8S_OBS_ET_TOKEN` scoped to error-tracking Role only; monitoring token unchanged; split-obs-secrets.py prevents cross-namespace apply
- T-16-12: test-glitchtip-ingest.sh parses real PUBLIC_KEY + PROJECT_ID from DSN; asserts non-403
- T-16-13: namespace allowlist is explicit `{"monitoring", "error-tracking"}` set in validate-obs-manifests.py; all other checks unchanged
- T-16-SC: no new packages; split-obs-secrets.py is stdlib Python

## Self-Check: PASSED

- FOUND: scripts/render-obs-secrets.py (modified)
- FOUND: scripts/split-obs-secrets.py
- FOUND: .github/workflows/deploy-observability.yml (modified)
- FOUND: scripts/validate-phase-16.sh
- FOUND: scripts/test-glitchtip-ingest.sh
- FOUND: docs/glitchtip.md
- FOUND: k8s/staging/01-obs-rbac.yaml (modified)
- FOUND commit: 0f67421 (render-obs-secrets.py)
- FOUND commit: 8293f01 (deploy-observability.yml + split-obs-secrets.py)
- FOUND commit: 69d7afe (validate scripts + docs + RBAC)
