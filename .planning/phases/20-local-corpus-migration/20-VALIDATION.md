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
| 20-01-01 | 01 | 1 | MIG-01, MIG-02 | T-20-01-02, T-20-01-06, T-20-01-07 | Validate one synthetic freeze-to-parity artifact chain without treating synthetic evidence as a real migration pass. | unit/contract | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | Extend existing + Wave 0 | Pending |
| 20-01-02 | 01 | 1 | MIG-01, MIG-02 | T-20-01-01, T-20-01-03, T-20-01-04, T-20-01-05 | Reject path/symlink escape, lossy or oversized records, unbounded work, and secret-bearing diagnostics before transform or target writes. | unit/security | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | Extend existing + Wave 0 | Pending |
| 20-01-03 | 01 | 1 | MIG-02 | T-20-01-02, T-20-01-07 | Freeze the v3.5.0 ID, collection, vector-strategy, and ranked-recall evidence contracts without claiming that live prerequisites exist. | unit/contract | `timeout 10s python3 -m unittest tests/test-solidstats-memory-migration.py && timeout 10s python3 scripts/validate-solidstats-memory-policy.py` | Wave 0 | Pending |
| 20-02-01 | 02 | 2 | MIG-01, MIG-02 | T-20-02-01, T-20-02-02, T-20-02-04 | Extract a complete synthetic source collection losslessly through the pinned oracle while containing paths and bounding pagination. | unit/contract | `timeout 15s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | Planned in 20-02 | Pending |
| 20-02-02 | 02 | 2 | MIG-02 | T-20-02-03, T-20-02-04, T-20-02-05, T-20-02-06 | Produce deterministic bounded private recall fixtures and sanitized value-free evidence without a target-parity claim. | unit/contract | `timeout 15s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py && timeout 10s python3 scripts/inventory-solidstats-memory.py --help` | Planned in 20-02 | Pending |
| 20-03-01 | 03 | 3 | MIG-01 | T-20-03-01, T-20-03-02, T-20-03-05 | Block all corpus work until operator evidence proves every writer is frozen and the complete immutable snapshot plus sidecars is stable. | checkpoint/contract | `timeout 30s test -n "$SOLIDSTATS_MEMORY_SNAPSHOT_DIR" && timeout 30s test -n "$SOLIDSTATS_MEMORY_FREEZE_ATTESTATION" && timeout 60s python3 scripts/inventory-solidstats-memory.py --snapshot-dir "$SOLIDSTATS_MEMORY_SNAPSHOT_DIR" --freeze-attestation "$SOLIDSTATS_MEMORY_FREEZE_ATTESTATION" --oracle-source-dir "$SOLIDSTATS_MEMORY_V350_SOURCE" --output-dir "$SOLIDSTATS_MEMORY_WORK_DIR/source-check" --check-only` | Operator gate | Pending |
| 20-03-02 | 03 | 3 | MIG-02 | T-20-03-03, T-20-03-04, T-20-03-06 | Block transform/import until exact v3.5.0 provenance and local Docker-daemon access are proven; reject 3.4.1, VPS, and shared targets. | checkpoint/contract | `timeout 20s "$SOLIDSTATS_MEMORY_V350_PYTHON" -c "import importlib.metadata as m, mempalace; assert m.version('mempalace') == '3.5.0'; print(m.version('mempalace')); print(mempalace.__file__)" && timeout 20s git -C "$SOLIDSTATS_MEMORY_V350_SOURCE" status --short && timeout 20s docker version && timeout 10s python3 scripts/inventory-solidstats-memory.py --help` | Operator gate | Pending |
| 20-04-01 | 04 | 4 | MIG-01, MIG-02 | T-20-04-01, T-20-04-02, T-20-04-04, T-20-04-05 | Inventory the immutable real snapshot once into complete private evidence with stable pre/post digests and no source mutation or value logging. | integration | `timeout 1800s "$SOLIDSTATS_MEMORY_V350_PYTHON" scripts/inventory-solidstats-memory.py --snapshot-dir "$SOLIDSTATS_MEMORY_SNAPSHOT_DIR" --freeze-attestation "$SOLIDSTATS_MEMORY_FREEZE_ATTESTATION" --oracle-source-dir "$SOLIDSTATS_MEMORY_V350_SOURCE" --output-dir "$SOLIDSTATS_MEMORY_WORK_DIR/source"` | Runtime output | Pending |
| 20-04-02 | 04 | 4 | MIG-01, MIG-02 | T-20-04-03, T-20-04-06 | Publish only allowlisted aggregate inventory provenance and prove the private source digests did not drift. | contract/privacy | `timeout 30s "$SOLIDSTATS_MEMORY_V350_PYTHON" scripts/inventory-solidstats-memory.py --snapshot-dir "$SOLIDSTATS_MEMORY_SNAPSHOT_DIR" --freeze-attestation "$SOLIDSTATS_MEMORY_FREEZE_ATTESTATION" --oracle-source-dir "$SOLIDSTATS_MEMORY_V350_SOURCE" --output-dir "$SOLIDSTATS_MEMORY_WORK_DIR/source" --check-only && timeout 15s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | Runtime output | Pending |
| 20-05-01 | 05 | 5 | MIG-02 | T-20-05-01, T-20-05-02, T-20-05-04, T-20-05-05, T-20-05-06 | Apply the closed D-07/D-08 vector decision and exact v3.5.0 ID/payload mapping without defaults, downloads, or mixed strategies. | unit/contract | `timeout 20s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py && timeout 10s python3 scripts/build-solidstats-memory-bundle.py --help` | Planned in 20-05 | Pending |
| 20-05-02 | 05 | 5 | MIG-02 | T-20-05-03, T-20-05-04, T-20-05-06, T-20-05-07 | Import deterministic bounded batches only into the proven-empty, loopback-only, exact-image Qdrant run and publish sanitized aggregate evidence. | integration | `timeout 1800s "$SOLIDSTATS_MEMORY_V350_PYTHON" scripts/build-solidstats-memory-bundle.py --inventory "$SOLIDSTATS_MEMORY_WORK_DIR/source/source-inventory.json" --source-records "$SOLIDSTATS_MEMORY_WORK_DIR/source/source-records.jsonl" --source-vectors "$SOLIDSTATS_MEMORY_WORK_DIR/source/source-vectors.jsonl" --recall-fixtures "$SOLIDSTATS_MEMORY_WORK_DIR/source/recall-fixtures.json" --output-dir "$SOLIDSTATS_MEMORY_WORK_DIR/transform" --oracle-python "$SOLIDSTATS_MEMORY_V350_PYTHON" --oracle-source-dir "$SOLIDSTATS_MEMORY_V350_SOURCE" --reembed-model-artifact "$SOLIDSTATS_MEMORY_REEMBED_MODEL" --qdrant-url "$SOLIDSTATS_MEMORY_LOCAL_QDRANT_URL"` | Runtime output | Pending |
| 20-06-01 | 06 | 6 | MIG-02 | T-20-06-02, T-20-06-04, T-20-06-05, T-20-06-06 | Prove exact bounded field/vector/ranking comparators and fail-closed cleanup guards without exposing source or target values. | unit/contract | `timeout 25s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py && timeout 10s python3 scripts/verify-solidstats-memory-parity.py --help` | Planned in 20-06 | Pending |
| 20-06-02 | 06 | 6 | MIG-01, MIG-02 | T-20-06-01, T-20-06-03, T-20-06-04, T-20-06-05, T-20-06-06, T-20-06-07 | Seal a handoff only from complete real parity, preserve isolated evidence on failure, and clean only the passed run's collection/container/private runtime after retained-artifact checks. | integration | `timeout 3600s "$SOLIDSTATS_MEMORY_V350_PYTHON" scripts/verify-solidstats-memory-parity.py --inventory "$SOLIDSTATS_MEMORY_WORK_DIR/source/source-inventory.json" --transform-manifest .planning/phases/20-local-corpus-migration/20-TRANSFORM-MANIFEST.json --bundle-dir "$SOLIDSTATS_MEMORY_WORK_DIR/transform" --recall-fixtures "$SOLIDSTATS_MEMORY_WORK_DIR/source/recall-fixtures.json" --oracle-python "$SOLIDSTATS_MEMORY_V350_PYTHON" --oracle-source-dir "$SOLIDSTATS_MEMORY_V350_SOURCE" --qdrant-url "$SOLIDSTATS_MEMORY_LOCAL_QDRANT_URL" --qdrant-container "$SOLIDSTATS_MEMORY_LOCAL_QDRANT_CONTAINER" --qdrant-data-dir "$SOLIDSTATS_MEMORY_WORK_DIR/qdrant-data" --output .planning/phases/20-local-corpus-migration/20-PARITY-REPORT.json --handoff-output .planning/phases/20-local-corpus-migration/20-PHASE21-HANDOFF.json --source-repeat-runs 3 --cleanup-after-pass` | Runtime output | Pending |

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
