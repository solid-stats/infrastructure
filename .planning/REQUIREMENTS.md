# Requirements: Solid Stats Infrastructure — Milestone v2.0

**Defined:** 2026-06-11
**Core Value:** Staging must be reproducible, backed up, and safe to run end-to-end before it is used to produce or compare new statistics.

> v1.0 requirements are archived at `.planning/milestones/v1.0-REQUIREMENTS.md`.

## Milestone v2.0 Requirements

Committed scope for v2.0 (Production-Ready Infra & kubectl-native CD). Each maps to a roadmap phase.

### CD — kubectl-native CD

- [x] **CD-01**: Operator can deploy staging via `kubectl` run on the CI runner over a WireGuard tunnel, with no SSH/scp to the VPS.
- [x] **CD-02**: CI authenticates to the k3s API as a namespace-scoped ServiceAccount using a long-lived token Secret (not the admin kubeconfig, not an SSH key).
- [x] **CD-03**: The deploy job gates on a verified WireGuard handshake before running any `kubectl`.
- [x] **CD-04**: ServiceAccount RBAC is restricted to the `solid-stats-staging` namespace and covers apply plus `rollout status` for every staging workload kind.
- [x] **CD-05**: Namespace and CI RBAC are bootstrapped once by the operator via a documented runbook; CI never creates the namespace.
- [ ] **CD-06**: Push to `master` deploys staging automatically; PRs run validate plus a server-side dry-run without deploying.
- [ ] **CD-07**: All `CD_SSH_*` secrets and SSH code paths are removed after the migration.
- [ ] **CD-08**: Only one deploy runs at a time (workflow concurrency lock).
- [x] **CD-09**: A long-lived SA-token rotation runbook (owner plus cadence, paired with WG key rotation) is documented.

### EDGE — Edge automation

- [x] **EDGE-01**: The host nginx vhost config for staging is managed in the repo.
- [x] **EDGE-02**: TLS certificates renew automatically via host `certbot` on a systemd timer with an `nginx -t`-gated reload hook.
- [x] **EDGE-03**: Certificate-renewal failures are surfaced (alert or log), not silent.
- [x] **EDGE-04**: The host firewall allows 80/443 inbound and keeps `6443` reachable only through the WireGuard tunnel.
- [x] **EDGE-05**: Edge setup is an idempotent, re-runnable bootstrap script.

### DRILL — Automated restore drill

- [x] **DRILL-01**: Operator can run an on-demand restore drill that restores the latest S3 backup into an ephemeral scratch PostgreSQL, never touching live `postgres-0`/`postgres-data`.
- [x] **DRILL-02**: The drill runs post-restore sanity assertions (e.g. row-count / object checks) and fails loudly if they do not pass.
- [x] **DRILL-03**: The drill tears down its scratch resources and logs the result as evidence.
- [x] **DRILL-04**: Drill manifests live outside the staging deploy glob so CD never schedules them.

### WEB — `web` runtime wiring

- [x] **WEB-01**: `web` Deployment, Service, and ConfigMap exist following existing `server-2` conventions (dedicated ServiceAccount, resource requests/limits, probes, pinned image).
- [x] **WEB-02**: `web` deploys as a 0-replica / image-pending stub until a real image exists.
- [x] **WEB-03**: `validate-staging.py` `EXPECTED_*` and the rollout-status verification include `web`.

### S3 — S3 lifecycle / retention

- [x] **S3-01**: A per-prefix expiration lifecycle policy for `backups/postgres/` is stored in the repo and applied via script.
- [x] **S3-02**: The lifecycle config aborts incomplete multipart uploads.
- [x] **S3-03**: Timeweb S3 lifecycle support is proven empirically (put-then-get plus an observed test-object expiry) before retention is relied upon.

### CUT — Production cutover

- [ ] **CUT-01**: Legacy and new runtimes run in parallel; the cutover is a single reversible nginx-upstream switch.
- [ ] **CUT-02**: A tested rollback path reverts the upstream in one edit.
- [ ] **CUT-03**: Cutover is gated on a fresh backup point and a green diff gate.
- [ ] **CUT-04**: A post-cutover smoke check curls the public host to confirm the new runtime responds before legacy is retired.

## Future Requirements

Deferred to v2.x. Tracked but not in the current roadmap.

### S3

- **S3-04**: Distinct shorter expiration windows for `replay/` and `artifact/` prefixes (beyond backups).

### CD

- **CD-10**: PR dry-run diff comment posted on the pull request.

### DRILL

- **DRILL-05**: Scheduled restore-drill CronJob with failure alerting.

### CUT

- **CUT-05**: Weighted / blue-green nginx cutover with gradual traffic shift.

## Out of Scope

Explicitly excluded. Anti-features confirmed across all four research files for a single-namespace, solo-operator cluster.

| Feature | Reason |
|---------|--------|
| GitOps controller (ArgoCD/Flux) | Overkill for one namespace on one VPS; push-based `kubectl apply` from CI is sufficient. |
| Service mesh / progressive canary | Unjustified complexity at this scale. |
| cert-manager + k8s ingress | Edge is host-nginx; there is no k8s ingress to issue certificates for. |
| `mc` (MinIO client) | Timeweb does not document it; vendored `aws-cli` covers S3 lifecycle. |
| Full-tunnel WireGuard | Split-tunnel `AllowedIPs=10.8.0.1/32` only — CI must not route all traffic through the VPS. |
| PITR / WAL archiving | Backup + restore drill is the recovery model for staging. |
| `--insecure-skip-tls-verify` | Real CA + `10.8.0.1` in serving-cert SANs are required. |
| Storage-class transitions (S3 tiers) | Timeweb supports expiration only, not tiering. |

## Traceability

Finalized during roadmap creation. Phase numbers continue from v1.0 (ended at Phase 5).

| Requirement | Phase | Status |
|-------------|-------|--------|
| CD-01 | Phase 6 | Complete |
| CD-02 | Phase 6 | Complete |
| CD-03 | Phase 6 | Complete |
| CD-04 | Phase 6 | Complete |
| CD-05 | Phase 6 | Complete |
| CD-06 | Phase 6 | Pending |
| CD-07 | Phase 6 | Pending |
| CD-08 | Phase 6 | Pending |
| CD-09 | Phase 6 | Complete |
| EDGE-01 | Phase 7 | Complete |
| EDGE-02 | Phase 7 | Complete |
| EDGE-03 | Phase 7 | Complete |
| EDGE-04 | Phase 7 | Complete |
| EDGE-05 | Phase 7 | Complete |
| DRILL-01 | Phase 8 | Complete |
| DRILL-02 | Phase 8 | Complete |
| DRILL-03 | Phase 8 | Complete |
| DRILL-04 | Phase 8 | Complete |
| WEB-01 | Phase 9 | Complete |
| WEB-02 | Phase 9 | Complete |
| WEB-03 | Phase 9 | Complete |
| S3-01 | Phase 10 | Complete |
| S3-02 | Phase 10 | Complete |
| S3-03 | Phase 10 | Complete |
| CUT-01 | Phase 11 | Pending |
| CUT-02 | Phase 11 | Pending |
| CUT-03 | Phase 11 | Pending |
| CUT-04 | Phase 11 | Pending |

**Coverage:**

- v2.0 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-11*
*Last updated: 2026-06-11 after roadmap creation (Phases 6-11)*
