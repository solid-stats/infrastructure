---

phase: 20
slug: local-corpus-migration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-20
---

<!-- markdownlint-disable MD013 -->

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
| --- | --- |
| **Framework** | Python `unittest` from the standard library |
| **Config file** | None — direct test modules |
| **Quick run command** | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` |
| **Full suite command** | `timeout 30s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` |
| **Estimated runtime** | Under 30 seconds without the operator-gated isolated-Qdrant run |

## Sampling Rate

- **After every task commit:** Run the quick command plus the migration unit
  tests introduced by that task.
- **After every plan wave:** Run the full suite. The isolated-Qdrant cases must
  fail closed or skip with an explicit unavailable-environment result until an
  approved local container runtime exists.
- **Before `$gsd-verify-work`:** The full suite, bundle validator, and recorded
  isolated-Qdrant parity run must be green.
- **Max feedback latency:** 30 seconds for offline tests.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20-01-01 | 01 | 0 | MIG-01 | T-20-01 | Reject absent freeze evidence, unsafe paths, symlink escape, and missing checksums. | unit | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` | Extend existing | Pending |
| 20-01-02 | 01 | 0 | MIG-02 | T-20-02 | Reject lossy metadata, duplicate IDs, invalid UUIDv5 mapping, and unsupported vector evidence. | unit | `timeout 10s python3 -m unittest tests/test-solidstats-memory-migration.py` | Wave 0 | Pending |
| 20-02-01 | 02 | 1 | MIG-01 | T-20-01 | Inventory only one post-freeze immutable snapshot and preserve complete source provenance. | contract | `timeout 30s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | Wave 0 | Pending |
| 20-03-01 | 03 | 2 | MIG-02 | T-20-02 | Import only to a new isolated local Qdrant target through the pinned v3.5.0 mapping. | integration | `timeout 30s python3 -m unittest tests/test-solidstats-memory-migration.py` | Wave 0 | Pending |
| 20-04-01 | 04 | 3 | MIG-02 | T-20-03 | Prove field, vector, and deterministic ranking parity without exposing source content or secrets. | integration | `timeout 30s python3 -m unittest tests/test-solidstats-memory-migration.py` | Wave 0 | Pending |

Status values: Pending · Green · Red · Flaky.

## Wave 0 Requirements

- [ ] `tests/test-solidstats-memory-migration.py` — deterministic source,
  mapping, malformed-metadata, duplicate-ID, and UUIDv5 fixtures.
- [ ] Synthetic source sidecars for vector-reuse and forced-re-embedding
  branches; no production content or credentials.
- [ ] An isolated-Qdrant fixture that requires an approved local container
  runtime, starts from an empty target, and records cleanup evidence.
- [ ] Machine-readable inventory, transform, and parity report schemas enforced
  by the existing policy validator.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
| --- | --- | --- | --- |
| Legacy writes are frozen before snapshot creation. | MIG-01 | The repository cannot prove a remote service mutation from local files. | Record the freeze time and operator evidence, then snapshot once and bind the inventory to its checksum. |
| The supplied execution environment is exactly MemPalace v3.5.0. | MIG-02 | The required version is not installed locally. | Record the reviewed artifact revision and checksum before any transform or import. |
| Docker can start a disposable isolated Qdrant. | MIG-02 | The daemon is currently inaccessible to this session. | Start a new loopback-only target, prove it is empty, run parity, and retain the non-secret run report. |

## Validation Sign-Off

- [ ] All tasks have automated verification or Wave 0 dependencies.
- [ ] Sampling continuity has no three consecutive tasks without automation.
- [ ] Wave 0 covers all missing references.
- [ ] No watch-mode flags are used.
- [ ] Offline feedback latency stays below 30 seconds.
- [ ] `nyquist_compliant: true` is set in frontmatter.

**Approval:** Pending
