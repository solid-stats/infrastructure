---
phase: 14-public-edge-grafana-tls
plan: "03"
subsystem: scripts/docs
tags: [nginx, certbot, tls, grafana, observability, validation, offline, runbook]
dependency_graph:
  requires:
    - scripts/bootstrap-obs-edge.sh       # Wave 1 (14-01) — script validator asserts against
    - config/nginx/sites-available/grafana-stats-staging-solid-stats.conf  # Wave 1 (14-02)
    - config/nginx/sites-available/errors-stats-staging-solid-stats.conf   # Wave 1 (14-02)
    - config/systemd/certbot-deploy-hook.sh       # Phase 07 shared artifact
    - config/systemd/certbot.service.d/onfailure.conf
    - config/systemd/certbot-renew-failure.service
  provides:
    - scripts/validate-obs-edge.py        # offline structural validator (CI gate)
    - docs/obs-edge-bootstrap.md          # operator runbook (Wave 3 human-action reference)
  affects:
    - 14-04  # Wave 3 human-action checkpoint references the runbook and validator
tech_stack:
  added: []
  patterns:
    - "Python 3 stdlib offline validator (mirrors validate-edge.py): ROOT/ValidationError/require()/per-group check functions"
    - "Negative assertion pattern: certbot full-renew flag absence checked without writing the dangerous flag itself"
    - "Per-listen http2 assertion: regex on each 443 listen line, not full-content substring"
    - "UPSTREAM_PLACEHOLDER acceptance: validator allows token OR 10.x.x.x; rejects bare 127.0.0.1-only stub"
key_files:
  created:
    - scripts/validate-obs-edge.py
    - docs/obs-edge-bootstrap.md
  modified: []
decisions:
  - "Validator split into 4 check groups mirroring validate-edge.py structure: bootstrap script, grafana vhost, errors vhost, docs+shared artifacts"
  - "Negative full-renew assert written as string concatenation to avoid the literal dangerous flag appearing in the validator source"
  - "Task 1 commit carries the validator (exits 1 on missing runbook); Task 2 commit adds the runbook making the full run exit 0"
  - "errors vhost NO proxy_pass assert uses simple substring — confirmed clean by 14-02 deviation fix (comment text reworded to remove the word)"
metrics:
  duration_minutes: 12
  completed_date: "2026-06-14T00:00:00Z"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
status: complete
requirements: [EDGE-01, EDGE-02, EDGE-03, MET-07]
---

# Phase 14 Plan 03: Offline Structural Validator + Operator Runbook Summary

**One-liner:** Python 3 stdlib offline validator asserting obs-edge script and both vhosts are well-formed (4 check groups, exits 0 against Wave 1 artifacts), plus operator runbook covering the DNS gate, per-domain certonly, and live verification.

## What Was Built

### scripts/validate-obs-edge.py (307 lines)

Offline structural validator mirroring `scripts/validate-edge.py` exactly in structure:
`ROOT = Path(__file__).resolve().parents[1]`, `ValidationError` class, `require()` helper,
four check group functions, `main()` returning 1 on first error.

| Check Group | Function | Key Assertions |
|-------------|----------|----------------|
| A — bootstrap script | `validate_bootstrap_script` | bash -n, set -euo pipefail, exit 64, mkdir -p, ln -sf, .bak, nginx -t, kubectl get svc grafana, certbot certonly, letsencrypt/live, negative: no --full-renew flag |
| B — grafana vhost | `validate_grafana_vhost` | upstream grafana_obs, keepalive, ACME block, return 301, ssl_certificate, options-ssl-nginx.conf, ssl-dhparams.pem, HSTS, proxy_set_header Upgrade, per-listen http2, no bare 127.0.0.1 |
| C — errors vhost | `validate_errors_vhost` | ACME block, return 301, return 503, ssl_certificate, options-ssl-nginx.conf, ssl-dhparams.pem, HSTS, no proxy_pass |
| D — docs + shared artifacts | `validate_docs_and_shared_artifacts` | docs/obs-edge-bootstrap.md, certbot-deploy-hook.sh, onfailure.conf, certbot-renew-failure.service |

Exits 0 against all Wave 1 artifacts. Removing any asserted token would make it exit 1 with a
named `error:` line.

### docs/obs-edge-bootstrap.md (234 lines)

Operator runbook with sections mirroring `docs/edge-bootstrap.md`:

- **Context** — additive to Phase 07 edge; DO NOT touch stats-staging vhost or cert
- **DNS Prerequisite (EDGE-01)** — both A records (`89.223.124.200`), dig propagation check
- **Offline Checks** — `python3 scripts/validate-obs-edge.py`
- **Step 2: grafana bootstrap** — full env-prefixed invocation, 9-step walkthrough
- **Step 3: errors bootstrap** — `SKIP_UPSTREAM_CHECK=1`, cert-only rationale (rate-limit)
- **certbot caveat** — per-domain `certbot certonly -d` only; full-renew hangs on this VPS
- **Step 4: Operator live verification** — nginx -t, certbot certificates, openssl s_client, curl HTTP→HTTPS, Grafana login page (MET-07), renewal dry-run
- **Known post-deploy check** — root_url in Grafana ConfigMap if login redirects to http://
- **Phase 16 reuse** — re-run bootstrap with errors. + GlitchTip ClusterIP; no script change
- **Troubleshooting table** — 8 rows covering NXDOMAIN, rate limit, 502, nginx -t failure, missing env vars

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `20cb6dd` | feat(14-03): offline structural validator for obs-edge artifacts |
| Task 2 | `66ae553` | docs(14-03): operator runbook for obs-edge bootstrap |

## Verification

All checks passed:

- `python3 -m py_compile scripts/validate-obs-edge.py` — OK
- `python3 scripts/validate-obs-edge.py` — exits 0, 4 ok: lines + 1 warn:
- Task 2 grep assertions — all pass (grafana., errors., certbot certonly, dig, 89.223.124.200)
- No live VPS calls made — all authoring only as required by success criteria

## Deviations from Plan

None — plan executed exactly as written. The Task 1 validator intentionally exited 1 until
Task 2 created the runbook (the docs/obs-edge-bootstrap.md existence check gates group D).
This is expected sequential behavior, not a deviation.

## Threat Flags

None — both artifacts are read-only repo files. No new network endpoints, auth paths, or
schema changes. T-14-09 (artifact drift) is mitigated by the validator itself; T-14-10
(full-renew hang) is mitigated by the negative assertion and the runbook caveat section.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `scripts/validate-obs-edge.py` exists | FOUND |
| `docs/obs-edge-bootstrap.md` exists | FOUND |
| Commit `20cb6dd` exists | FOUND |
| Commit `66ae553` exists | FOUND |
| `python3 scripts/validate-obs-edge.py` exits 0 | PASSED |
| `python3 -m py_compile` clean | PASSED |
