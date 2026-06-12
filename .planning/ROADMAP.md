# Roadmap: Solid Stats Infrastructure

## Milestones

- ✅ **v1.0 Staging Foundation** - Phases 1-5 (shipped 2026-05-10)
- 🚧 **v2.0 Production-Ready Infra & kubectl-native CD** - Phases 6-11 (in progress)

## Overview

v1 proved the staging infrastructure path: a reproducible infra-owned deploy, a manual backup and restore-list gate, a gradual app CD ownership boundary, a controlled full-run, and old-vs-new diff readiness. v2.0 hardens that into production-readiness. The keystone is kubectl-native CD — replacing SSH/scp with a WireGuard tunnel brought up inside the CI job and a namespace-scoped ServiceAccount applying directly against the closed k3s API. Every other feature deploys through that path, so it lands first. Edge automation, an automated restore drill, the `web` runtime slot, and S3 lifecycle land in parallel between the CD foundation and the finale, building the reversibility and recovery confidence required for the last step: a single-lever, reversible production cutover.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Staging Deploy Baseline** - Operator can deploy and verify the staging runtime from this infrastructure repository.
- [x] **Phase 2: Backup Gate** - Operator has a current PostgreSQL backup point in Timeweb S3 with restore-list validation and restore drill instructions.
- [x] **Phase 3: App CD Boundary** - App repositories can keep building images while infrastructure owns staging runtime wiring and pinned image tags.
- [x] **Phase 4: Controlled Full Run** - Operator can explicitly start and monitor a manual ingest run without enabling recurring fetching first.
- [x] **Phase 5: Diff and Cutover Readiness** - Operator can produce reviewable old-vs-new diff output while production cutover remains blocked.
- [ ] **Phase 6: kubectl-native CD** - CI deploys staging via `kubectl` over a WireGuard tunnel as a namespace-scoped ServiceAccount, with SSH removed.
- [x] **Phase 7: Edge Automation** - Host nginx, TLS renewal, and firewall for staging are repo-managed, idempotent, and proven reversible. (completed 2026-06-12)
- [x] **Phase 8: Automated Restore Drill** - Operator can prove the latest S3 backup restores cleanly into an ephemeral scratch PostgreSQL, never touching live data. (completed 2026-06-12)
- [ ] **Phase 9: web Runtime Wiring** - The future `web` application has a conventions-compliant, validated Kubernetes slot deployed as a stub.
- [ ] **Phase 10: S3 Lifecycle & Retention** - Backup-prefix retention is enforced via a repo-stored expiration policy, with Timeweb support proven empirically.
- [ ] **Phase 11: Production Cutover** - Operator can flip production traffic to the new runtime in one reversible nginx-upstream edit, gated and smoke-checked.

## Phase Details

<details>
<summary>✅ v1.0 Staging Foundation (Phases 1-5) - SHIPPED 2026-05-10</summary>

### Phase 1: Staging Deploy Baseline

**Goal**: Operator can safely deploy and verify the complete staging runtime from the infrastructure repository.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: OWN-01, OWN-02, RUN-01, RUN-02, RUN-04, VAL-01, VAL-02, VAL-03, VAL-04, K8S-01, K8S-02, K8S-03
**Success Criteria** (what must be TRUE):

  1. Operator can see namespace, PostgreSQL, RabbitMQ, `server-2`, `replay-parser-2`, `replays-fetcher`, and backup resources represented in this repository.
  2. Operator can apply the staging manifests to k3s from this repository without relying on app repository deploy steps.
  3. Operator can verify PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2` rollout state after deploy.
  4. CI catches broken manifest/script syntax, unsafe secret rendering, missing resource limits, default ServiceAccount usage, and missing security-context or NetworkPolicy decisions before deploy reaches staging.
  5. Documentation states which v1 resources remain intentionally outside infrastructure ownership and which Kubernetes hardening exceptions are deliberate.

**Plans**: 4/4 complete

### Phase 2: Backup Gate

**Goal**: Operator has a verified PostgreSQL backup point before any full ingest run begins.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: BKP-01, BKP-02, BKP-03, BKP-04, BKP-05, K8S-04
**Success Criteria** (what must be TRUE):

  1. Nightly PostgreSQL backups write custom-format dumps to Timeweb S3 under `backups/postgres/`.
  2. Operator can launch a one-off backup Job from the CronJob and wait for it to complete.
  3. Each backup upload includes a dump, `pg_restore --list` output, and manifest metadata in S3.
  4. The backup gate blocks full ingest until the backup Job completed, S3 upload succeeded, and `pg_restore --list` succeeded.
  5. Operator can verify backup-related storage and PVC changes without risking PostgreSQL or RabbitMQ persistent state.

**Plans**: 1/1 complete

### Phase 3: App CD Boundary

**Goal**: Application repositories can keep publishing images while infrastructure becomes the source of truth for staging deployment wiring.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: OWN-03, OWN-04
**Success Criteria** (what must be TRUE):

  1. Operator can identify which shared Kubernetes resources app repositories should stop applying in v1.
  2. Staging app image tags are pinned explicitly in infrastructure manifests rather than relying on mutable `latest`.
  3. Operator can update a pinned app image tag in this repository while app repositories retain ownership of image builds.
  4. Legacy app CD overlap is documented with a gradual handoff path that avoids breaking active staging.

**Plans**: 1/1 complete

### Phase 4: Controlled Full Run

**Goal**: Operator can run and monitor a manual replay ingest after backup confidence exists.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: RUN-03, FULL-01, FULL-02, FULL-03
**Success Criteria** (what must be TRUE):

  1. `replays-fetcher` remains deployed but suspended until the operator explicitly starts a controlled manual ingest run.
  2. Operator can start a manual full-run path without enabling the recurring fetch schedule first.
  3. The full-run procedure records checkpoints and logs sufficient to resume or diagnose ingest failures.
  4. Operator can monitor queue depth, parser consumers, server readiness, and S3 object writes during the run.

**Plans**: 1/1 complete

### Phase 5: Diff and Cutover Readiness

**Goal**: Operator can compare old and new statistics and keep production cutover blocked until review is clean enough.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: DIFF-01, DIFF-02, DIFF-03
**Success Criteria** (what must be TRUE):

  1. Project defines the old-vs-new statistics comparison inputs, execution path, and expected output shape.
  2. Diff output separates strict failures from allowlisted known differences.
  3. Operator can review diff results after a full run without treating the output as automatic production approval.
  4. Production traffic cutover remains explicitly blocked until diff output is clean enough for review.

**Plans**: 1/1 complete

</details>

### 🚧 v2.0 Production-Ready Infra & kubectl-native CD (In Progress)

**Milestone Goal:** Deploy staging with direct `kubectl` from CI over WireGuard (no SSH), make git the source of truth for what ships, and close the production-readiness gaps deferred from v1 — edge automation, S3 lifecycle, automated restore drill, the `web` runtime, and a controlled production cutover.

**Execution Order:** CD first / cutover last is the only hard ordering. Phases 7-10 are independent and sequenced by capacity. Edge (7) and the restore drill (8) must both land before cutover (11): the cutover lever *is* the nginx upstream and must be proven reversible, and production is never flipped without proven recoverability.

#### Phase 6: kubectl-native CD

**Goal**: CI deploys staging by running `kubectl` on the runner over a WireGuard tunnel as a namespace-scoped ServiceAccount, with all SSH transport removed and the operator-bootstrap boundary documented.
**Depends on**: Phase 5
**Requirements**: CD-01, CD-02, CD-03, CD-04, CD-05, CD-06, CD-07, CD-08, CD-09
**Success Criteria** (what must be TRUE):

  1. A push to `master` deploys staging automatically by running `kubectl apply` from the runner over a verified WireGuard tunnel, with no SSH/scp to the VPS; a PR runs validate plus a server-side dry-run without deploying.
  2. CI authenticates as the `solid-stats-staging`-scoped ServiceAccount using a long-lived token Secret (not admin kubeconfig, not an SSH key), and `kubectl auth whoami` confirms it is not `system:anonymous`.
  3. The deploy job aborts before any `kubectl` if the WireGuard handshake has not completed, and `6443` is reachable only through the tunnel.
  4. The ServiceAccount can apply and `rollout status` every staging workload kind within the namespace and nothing cluster-scoped; the namespace and CI RBAC are bootstrapped once by the operator via a documented runbook, and CI never creates the namespace.
  5. All `CD_SSH_*` secrets and SSH code paths are removed, only one deploy runs at a time, and an SA-token rotation runbook (owner, cadence, paired with WG key rotation) is documented.

**Plans**: 4 plans
Plans:
**Wave 1**

- [x] 06-01-PLAN.md — Operator bootstrap manifest (01-ci-rbac.yaml) + operator runbook (docs/operator-bootstrap.md)
- [x] 06-02-PLAN.md — SA-token and WireGuard key rotation runbook (docs/sa-token-rotation.md)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-03-PLAN.md — WireGuard handshake gate script + kubeconfig construction script

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 06-04-PLAN.md — Workflow refactor (WireGuard + kubectl native, PR/master split, concurrency lock) + SSH script deletion

#### Phase 7: Edge Automation

**Goal**: The public staging edge — host nginx vhost, TLS renewal, and firewall — is repo-managed, idempotently re-runnable, and proven reversible in isolation before it becomes the cutover lever.
**Depends on**: Phase 6
**Requirements**: EDGE-01, EDGE-02, EDGE-03, EDGE-04, EDGE-05
**Success Criteria** (what must be TRUE):

  1. The host nginx vhost config for staging lives in the repo and an idempotent bootstrap script applies it the same way on every re-run.
  2. TLS certificates renew automatically via host `certbot` on a systemd timer with an `nginx -t`-gated reload hook, and `certbot renew --dry-run` passes.
  3. A certificate-renewal failure surfaces as an alert or log entry rather than failing silently.
  4. The host firewall allows 80/443 inbound and keeps `6443` reachable only through the WireGuard tunnel.

**Plans**: 4 plans
Plans:
**Wave 1** *(parallel — no shared files)*

- [x] 07-01-PLAN.md — Offline validator (scripts/validate-edge.py) + nginx vhost verbatim mirror (config/nginx/sites-available/stats-staging-solid-stats.conf)
- [x] 07-02-PLAN.md — OnFailure= drop-in (config/systemd/certbot.service.d/onfailure.conf) + failure handler unit + deploy-hook script (stock certbot.timer preserved)

**Wave 2** *(depends on Wave 1)*

- [x] 07-03-PLAN.md — Adopt-reconcile bootstrap (scripts/bootstrap-edge.sh: backup live vhost, install repo copy, ufw split-tunnel) + teardown (scripts/teardown-edge.sh: .bak restore)

**Wave 3** *(depends on Wave 2)*

- [x] 07-04-PLAN.md — Operator runbook (docs/edge-bootstrap.md: adopt flow, OPERATOR-ONLY labels, Phase 11 lever, reversibility proof)

#### Phase 8: Automated Restore Drill

**Goal**: Operator can prove on demand that the latest S3 backup restores into an ephemeral scratch PostgreSQL with passing sanity checks, never touching live data, with the drill kept out of the CD deploy path.
**Depends on**: Phase 6
**Requirements**: DRILL-01, DRILL-02, DRILL-03, DRILL-04
**Success Criteria** (what must be TRUE):

  1. Operator can run an on-demand restore drill that restores the latest S3 backup into an ephemeral scratch PostgreSQL, never touching live `postgres-0` / `postgres-data`.
  2. The drill runs post-restore sanity assertions (row-count / object checks) and fails loudly when they do not pass.
  3. The drill tears down its scratch resources and logs the result as evidence.
  4. Drill manifests live outside the staging deploy glob, so CD never schedules them.

**Plans**: 3 plans
Plans:
**Wave 1** *(parallel — no shared files)*

- [x] 08-01-PLAN.md — Job manifest (k8s/staging/restore-drill/70-restore-drill.yaml) + operator script (scripts/restore-drill.sh)
- [x] 08-02-PLAN.md — DRILL-04 depth-1 guard + restore-drill.sh syntax check in scripts/validate-staging.py

**Wave 2** *(depends on Wave 1)*

- [x] 08-03-PLAN.md — docs/backup-restore.md automated runbook (doc task complete; live-drill checkpoint awaiting operator)

#### Phase 9: web Runtime Wiring

**Goal**: The future `web` application has a conventions-compliant Kubernetes slot — deployed as a 0-replica / image-pending stub — wired into validation and the rollout-status gate.
**Depends on**: Phase 6
**Requirements**: WEB-01, WEB-02, WEB-03
**Success Criteria** (what must be TRUE):

  1. `web` Deployment, Service, and ConfigMap exist following existing `server-2` conventions: dedicated ServiceAccount, resource requests/limits, probes, and a pinned image.
  2. `web` deploys as a 0-replica / image-pending stub until a real image exists, without breaking the deploy.
  3. `validate-staging.py` `EXPECTED_*` and the rollout-status verification include `web`.

**Plans**: TBD
**UI hint**: yes

#### Phase 10: S3 Lifecycle & Retention

**Goal**: Backup-prefix retention is enforced through a repo-stored, script-applied expiration policy, with Timeweb S3 lifecycle support proven empirically before retention is relied upon.
**Depends on**: Phase 8
**Requirements**: S3-01, S3-02, S3-03
**Success Criteria** (what must be TRUE):

  1. A per-prefix expiration lifecycle policy for `backups/postgres/` is stored in the repo and applied via script.
  2. The lifecycle config aborts incomplete multipart uploads.
  3. Timeweb S3 lifecycle support is proven empirically — a put-then-get round-trip plus an observed test-object expiry — recorded as evidence before retention is trusted.

**Plans**: TBD

#### Phase 11: Production Cutover

**Goal**: Operator can switch production traffic to the new runtime in a single reversible nginx-upstream edit, gated on a fresh backup and a green diff, with a tested rollback and a post-cutover smoke check.
**Depends on**: Phase 7, Phase 8, Phase 9, Phase 10
**Requirements**: CUT-01, CUT-02, CUT-03, CUT-04
**Success Criteria** (what must be TRUE):

  1. Legacy and new runtimes run in parallel and the cutover is a single reversible nginx-upstream switch.
  2. A tested rollback path reverts the upstream in one edit, with legacy kept warm.
  3. The cutover is gated on a fresh backup point and a green diff gate before it is allowed to proceed.
  4. A post-cutover smoke check curls the public host to confirm the new runtime responds before legacy is retired.

**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Staging Deploy Baseline | v1.0 | 4/4 | Complete | 2026-05-10 |
| 2. Backup Gate | v1.0 | 1/1 | Complete | 2026-05-10 |
| 3. App CD Boundary | v1.0 | 1/1 | Complete | 2026-05-10 |
| 4. Controlled Full Run | v1.0 | 1/1 | Complete | 2026-05-10 |
| 5. Diff and Cutover Readiness | v1.0 | 1/1 | Complete | 2026-05-10 |
| 6. kubectl-native CD | v2.0 | 4/4 | Complete   | 2026-06-12 |
| 7. Edge Automation | v2.0 | 4/4 | Complete    | 2026-06-12 |
| 8. Automated Restore Drill | v2.0 | 3/3 | Complete    | 2026-06-12 |
| 9. web Runtime Wiring | v2.0 | 0/TBD | Not started | - |
| 10. S3 Lifecycle & Retention | v2.0 | 0/TBD | Not started | - |
| 11. Production Cutover | v2.0 | 0/TBD | Not started | - |
