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
| 21-01-01 | 01 | 0 | ISO-03 | T-21-04 | Reciprocal private MemPalace-to-Qdrant path | contract | `timeout 30s python3 -m unittest tests/test-memory-runtime-contract.py` | ✅ extend | ⬜ pending |
| 21-01-02 | 01 | 0 | OPS-03 | T-21-01 | Existing restore targets are rejected | unit | `timeout 30s python3 -m unittest tests/test-memory-cutover-contract.py` | ❌ W0 | ⬜ pending |
| 21-02-01 | 02 | 1 | OPS-02 | T-21-02 | Digests and backup checksums fail closed | unit + live | Quick suite plus backup stage | ❌ W0 | ⬜ pending |
| 21-02-02 | 02 | 1 | OPS-03 | T-21-01 | Restore remains isolated until parity passes | unit + live | Quick suite plus restore stage | ❌ W0 | ⬜ pending |
| 21-03-01 | 03 | 2 | ISO-01, ISO-03 | T-21-03, T-21-04 | Public MCP is authenticated; Qdrant remains private | contract + live | Quick suite plus cutover probe | ❌ W0 | ⬜ pending |
| 21-03-02 | 03 | 2 | OPS-05 | T-21-03 | MCP schema, recall, archive, and capture behavior pass | live acceptance | Operator probe stage | ❌ W0 | ⬜ pending |
| 21-04-01 | 04 | 3 | OPS-05 | T-21-06 | Restart and reboot preserve the full data path | live recovery | Operator recovery stage | ❌ W0 | ⬜ pending |
| 21-04-02 | 04 | 3 | ISO-01, OPS-05 | T-21-05 | Rollback is exercised before legacy removal | live recovery | Operator rollback and forward stages | ❌ W0 | ⬜ pending |

Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky

## Wave 0 Requirements

- [ ] `tests/test-memory-cutover-contract.py` — transition, idempotency,
  privacy, absent-target, alias rollback, and probe-schema tests.
- [ ] `tests/test-memory-runtime-contract.py` — reciprocal MemPalace egress
  contract.
- [ ] `scripts/validate-memory-manifests.py` — reciprocal NetworkPolicy
  validation.
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
