# Requirements

## v1 Requirements

### Infrastructure Ownership

- [ ] **OWN-01**: Operator can see all staging shared runtime resources in the
  infrastructure repository.
- [ ] **OWN-02**: Operator can deploy staging shared resources and app runtime
  wiring from the infrastructure repository.
- [ ] **OWN-03**: Application repositories can gradually stop applying shared
  Kubernetes resources and keep ownership of image builds.
- [ ] **OWN-04**: Staging app image tags are pinned explicitly and can be
  updated without relying on mutable `latest`.

### Staging Runtime

- [ ] **RUN-01**: Operator can apply namespace, PostgreSQL, RabbitMQ,
  `server-2`, `replay-parser-2`, and `replays-fetcher` manifests to k3s.
- [ ] **RUN-02**: Operator can verify PostgreSQL, RabbitMQ, `server-2`, and
  `replay-parser-2` rollouts after deploy.
- [ ] **RUN-03**: `replays-fetcher` remains deployed but suspended until a
  controlled manual ingest run is explicitly started.
- [ ] **RUN-04**: Runtime secrets are rendered from GitHub environment secrets
  without storing secret values in git.

### Backup and Restore

- [ ] **BKP-01**: PostgreSQL nightly backup CronJob writes custom-format dumps
  to Timeweb S3 under `backups/postgres/`.
- [ ] **BKP-02**: Manual backup command creates a one-off backup Job from the
  CronJob and waits for completion.
- [ ] **BKP-03**: Every backup upload includes a dump, `pg_restore --list`
  output, and manifest metadata.
- [ ] **BKP-04**: Backup verification gate passes before any full ingest run:
  backup Job completes, S3 upload succeeds, and `pg_restore --list` succeeds.
- [ ] **BKP-05**: Restore drill runbook explains how to restore into an isolated
  database and run smoke checks.

### Full Run Readiness

- [ ] **FULL-01**: Operator has a manual full-run path for `replays-fetcher`
  that does not require enabling the recurring schedule first.
- [ ] **FULL-02**: Full-run procedure records checkpoints and logs sufficient to
  resume or diagnose ingest failures.
- [ ] **FULL-03**: Queue depth, parser consumers, server readiness, and S3
  object writes can be monitored during the run.

### Diff Readiness

- [ ] **DIFF-01**: Project defines how to compare old statistics against new
  statistics after a full run.
- [ ] **DIFF-02**: Diff output separates strict failures from allowlisted known
  differences.
- [ ] **DIFF-03**: Production traffic cutover remains blocked until diff output
  is clean enough to review.

### Validation and Safety

- [ ] **VAL-01**: CI validates manifest and script syntax before deploy.
- [ ] **VAL-02**: Live deploy verification checks current Kubernetes resource
  state after apply.
- [ ] **VAL-03**: Secret rendering is validated so GHCR pull credentials and
  runtime secrets are accepted by Kubernetes.
- [ ] **VAL-04**: Documentation states which resources are intentionally outside
  infra ownership in v1.

### Kubernetes Safety

- [ ] **K8S-01**: Workloads use explicit ServiceAccounts and avoid the default
  ServiceAccount unless an exception is documented.
- [ ] **K8S-02**: Workloads define resource requests, resource limits, health
  probes, and security contexts where container images allow it.
- [ ] **K8S-03**: Namespace network isolation is defined through NetworkPolicies
  or a documented k3s/CNI exception with a follow-up path.
- [ ] **K8S-04**: Persistent storage and PVC changes are documented and verified
  so infra deploys do not accidentally destroy PostgreSQL or RabbitMQ state.

## v2 Requirements

- [ ] **PROD-01**: Add production environment manifests and cutover procedure.
- [ ] **EDGE-01**: Bring host nginx/certificate/firewall state under explicit
  infrastructure management or documented automation.
- [ ] **LIFE-01**: Configure S3 lifecycle or retention policy for backups,
  reports, raw replays, and artifacts.
- [ ] **REST-01**: Automate restore drill validation beyond the documented
  manual runbook.
- [ ] **WEB-01**: Add `web` runtime wiring after the web application is ready.

## Out of Scope

- Production cutover in v1 — staging must complete backup, full-run, and diff
  verification first.
- Application source changes — source code and image publishing stay in app
  repositories.
- Immediate removal of all app deploy workflows — ownership transfer is gradual
  to avoid breaking current staging.
- Scheduled replay fetching before backup verification — the first ingest run is
  manual and monitored.
- Replacing k3s or rebuilding the VPS from scratch — v1 uses the existing
  staging server.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| OWN-01 | Phase 1 | Pending |
| OWN-02 | Phase 1 | Pending |
| OWN-03 | Phase 3 | Pending |
| OWN-04 | Phase 3 | Pending |
| RUN-01 | Phase 1 | Pending |
| RUN-02 | Phase 1 | Pending |
| RUN-03 | Phase 4 | Pending |
| RUN-04 | Phase 1 | Pending |
| BKP-01 | Phase 2 | Pending |
| BKP-02 | Phase 2 | Pending |
| BKP-03 | Phase 2 | Pending |
| BKP-04 | Phase 2 | Pending |
| BKP-05 | Phase 2 | Pending |
| FULL-01 | Phase 4 | Pending |
| FULL-02 | Phase 4 | Pending |
| FULL-03 | Phase 4 | Pending |
| DIFF-01 | Phase 5 | Pending |
| DIFF-02 | Phase 5 | Pending |
| DIFF-03 | Phase 5 | Pending |
| VAL-01 | Phase 1 | Pending |
| VAL-02 | Phase 1 | Pending |
| VAL-03 | Phase 1 | Pending |
| VAL-04 | Phase 1 | Pending |
| K8S-01 | Phase 1 | Pending |
| K8S-02 | Phase 1 | Pending |
| K8S-03 | Phase 1 | Pending |
| K8S-04 | Phase 2 | Pending |
