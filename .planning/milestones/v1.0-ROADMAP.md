# Roadmap: Solid Stats Infrastructure

## Overview

v1 proves the staging infrastructure path before any production traffic decision. The work moves from a reproducible infra-owned staging deploy, through a manual backup and restore-list gate, into a gradual app CD ownership boundary, then a controlled full-run and old-vs-new diff readiness.

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

## Phase Details

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

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Staging Deploy Baseline | 4/4 | Complete | 2026-05-10 |
| 2. Backup Gate | 1/1 | Complete | 2026-05-10 |
| 3. App CD Boundary | 1/1 | Complete | 2026-05-10 |
| 4. Controlled Full Run | 1/1 | Complete | 2026-05-10 |
| 5. Diff and Cutover Readiness | 1/1 | Complete | 2026-05-10 |
