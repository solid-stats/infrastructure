---
phase: 21
slug: restore-cutover-recovery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-20
---

# Phase 21 — Validation Strategy

<!-- markdownlint-disable MD013 -->

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
| --- | --- |
| **Framework** | Python `unittest` with PyYAML |
| **Config file** | none |
| **Quick run command** | `timeout 30s python3 -m unittest tests/test-memory-cutover-contract.py` |
| **Full suite command** | `timeout 90s python3 -m unittest tests/test-memory-runtime-contract.py tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py tests/test-memory-cutover-contract.py` |
| **Estimated runtime** | Less than 90 seconds offline; live recovery gates are operator-bounded |

## Sampling Rate

- **After every task commit:** Run the quick Phase 21 contract suite and the
  validator affected by the task.
- **After every plan wave:** Run the full offline suite with a supported Python
  runtime.
- **Before `$gsd-verify-work`:** The offline suite and one complete live
  restore, cutover, rollback, restart, and reboot evidence chain must be green.
- **Max feedback latency:** 30 seconds for task-level offline checks.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 21-01-01 | 01 | 0 | OPS-03 | T-21-01 | Evidence state chain rejects existing-target and transition collisions | unit | `timeout 30s python3 -m unittest tests/test-memory-cutover-contract.py` | ❌ W0 | ⬜ pending |
| 21-01-02 | 01 | 0 | ISO-03 | T-21-04 | Reciprocal private MemPalace-to-Qdrant path and isolated Python fixture | contract | `timeout 30s python3 -m unittest tests/test-memory-runtime-contract.py` | ✅ extend | ⬜ pending |
| 21-02-01 | 02 | 1 | OPS-02 | T-21-02 | Digests and backup checksums fail closed | unit + live | Quick suite plus backup stage | ❌ W0 | ⬜ pending |
| 21-02-02 | 02 | 1 | OPS-03 | T-21-01 | Restore remains isolated until parity passes | unit + live | Quick suite plus restore stage | ❌ W0 | ⬜ pending |
| 21-03-01 | 03 | 2 | ISO-01, ISO-03 | T-21-03, T-21-04 | Public MCP is authenticated; Qdrant remains private | contract + live | Quick suite plus cutover probe | ❌ W0 | ⬜ pending |
| 21-03-02 | 03 | 2 | OPS-05 | T-21-03 | MCP schema, recall, archive, and capture behavior pass | live acceptance | Operator probe stage | ❌ W0 | ⬜ pending |
| 21-04-01 | 04 | 3 | OPS-05 | T-21-06, T-21-07 | Restart, reboot, rollback, and forward paths require the full behavior matrix | unit + live recovery | Quick suite plus operator recovery stages | ❌ W0 | ⬜ pending |
| 21-04-02 | 04 | 3 | OPS-02 | T-21-15, T-21-16, T-21-17, T-21-18 | Exact-template backup has projected identity, named scale RBAC, measured exact kube-router API egress, positive/network-negative/RBAC-negative controls, coherent metadata, replica/write restoration, and blocked early activation | contract + live recovery | Runtime suite plus `prove-backup-api-access` and `prove-backup-consistency` | ✅ extend | ⬜ pending |
| 21-04-03 | 04 | 3 | ISO-01, OPS-05 | T-21-14, T-21-15 | Schedule activation and exact legacy removal occur only after consistency, recovery, rollback, and forward evidence pass | live recovery | Operator activation, seal, and client stages | ❌ W0 | ⬜ pending |

Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky

## Wave 0 Requirements

- [ ] `tests/test-memory-cutover-contract.py` — transition, idempotency,
  privacy, absent-target, alias rollback, and probe-schema tests.
- [ ] `tests/test-memory-runtime-contract.py` — reciprocal MemPalace egress
  contract.
- [ ] `scripts/validate-memory-manifests.py` — reciprocal NetworkPolicy
  validation plus exact backup scale RBAC, projected-token, API-egress, and
  operator-bootstrap contracts.
- [ ] `tests/test-memory-runtime-contract.py` — exact `05-rbac.yaml` manifest
  inventory, RBAC/NetworkPolicy/token mutation coverage, and three-file CI
  bootstrap exclusion.
- [ ] Synthetic Qdrant HTTP fixtures for snapshot, recovery, alias, and failure
  paths.
- [ ] A supported Python runtime gate or repair for the Phase 20 inventory tests
  that fail under Python 3.14.4.
- [ ] Recursive rejection of secrets, corpus values, identifiers, vectors, and
  private paths in Phase 21 evidence.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
| --- | --- | --- | --- |
| Isolated Qdrant snapshot restore | OPS-02, OPS-03 | Requires private snapshot, cluster, S3, and live capacity state | Run the operator restore stage only after digest, absence, and capacity gates pass; retain aggregate evidence. |
| Public cutover and client registration | ISO-01, ISO-03, OPS-05 | Mutates host nginx and machine-local MCP configuration | Run the reversible cutover stage, then the full auth and MCP behavior matrix. |
| Backup Kubernetes API control proof | OPS-02 | Requires the live kube-router translation path, operator-bootstrap RBAC/policy apply, and disruptive-identity test pods | Discover Service and ready-endpoint candidates; trial one exact `/32`/port at a time with fresh pods; require the backup-identity positive, wrong-label network-negative, and unprivileged-identity RBAC-negative controls before any scale or schedule activation. |
| Steady-state metadata consistency proof | OPS-02 | Temporarily scales the live MemPalace writer and reads its private PVC | Only after the API-control proof, run the exact still-suspended CronJob template as a one-shot; require zero writers, equal source-before/source-after/extracted-archive digests, package revalidation, exact replica restoration, and capture/read-after-write before schedule eligibility. |
| Process restart and VPS reboot | OPS-05 | Mutates live staging availability and host state | Capture pre-state, run one bounded restart/reboot, reconnect, and rerun the full private/public matrix. |
| Rollback and forward recovery | OPS-03, OPS-05 | Exercises live alias, nginx, client, and workload state | Restore recorded pre-state, prove service, then reapply the verified state before sealing. |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies.
- [ ] Sampling continuity: no three consecutive tasks lack automated checks.
- [ ] Wave 0 covers all missing references.
- [ ] No watch-mode flags.
- [ ] Offline feedback latency is less than 30 seconds.
- [ ] Live evidence is aggregate and contains no secrets or private values.
- [ ] `nyquist_compliant: true` is set in frontmatter.

Approval: pending

<!-- markdownlint-enable MD013 -->
