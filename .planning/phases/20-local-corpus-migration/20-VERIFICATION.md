---
phase: 20-local-corpus-migration
verified: 2026-08-20T09:38:49Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 20: Local Corpus Migration Verification Report

**Phase Goal:** Freeze legacy writes, source-review the record mapping and embedding
strategy, transform locally, and prove identifier, metadata, vector, and recall
parity in isolated Qdrant.
**Verified:** 2026-08-20T09:38:49Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

<!-- markdownlint-disable MD013 -->
| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Legacy writes were frozen before one immutable, provenance-bound source snapshot was used; legacy reads could remain available. | ✓ VERIFIED | The supplied main-owned runtime record confirms the real local procedure passed. The committed source proof carries freeze and snapshot attestations, and inventory/transform/parity code requires their validated provenance before transformation or target access. |
| 2 | Source-to-target mapping and vector strategy were explicitly reviewed before transformation. | ✓ VERIFIED | `20-MAPPING-CONTRACT.json` is approved, complete, digest-bound to the current source proof, and `build-solidstats-memory-bundle.py` rejects absent, stale, incomplete, or unapproved contracts. The transform manifest records the closed vector-strategy decision. |
| 3 | The frozen corpus was transformed and imported only into a disposable, loopback-only local Qdrant target. | ✓ VERIFIED | The supplied runtime evidence reports a complete local import. `build-solidstats-memory-bundle.py` accepts only loopback HTTP for the target and binds the pinned image, empty-target proof, run identity, collection derivation, and point-set evidence into the transform manifest. |
| 4 | Every imported record retains identifier, document/metadata/timestamp representation, and reused-vector parity; approved exclusions are reconciled. | ✓ VERIFIED | The public parity report records 19,534 field, ID, and vector comparisons with zero failures and 21 reconciled exclusions. Streaming field/vector comparators and UUIDv5 identity checks are implemented in `verify-solidstats-memory-parity.py`; the focused 61-test suite passes. |
| 5 | Recall parity is proven against the frozen source and the isolated target, and a provenance-bound Phase 21 handoff is emitted only on success. | ✓ VERIFIED | The supplied runtime record reports a passing three-run source baseline and zero recall failures. The committed report/handoff have matching current provenance, and the verifier enforces equal result lengths, exact top-1, at least 80% overlap, exact order among common IDs, and source-derived bounded common distances. |
<!-- markdownlint-enable MD013 -->

**Score:** 5/5 truths verified (0 present, behavior-unverified)

### ANN Equivalence Decision

Plan 20-06 originally specified exact ordered IDs, but the implementation
deliberately deviates to strict cross-engine ANN equivalence. This is a
documented execution deviation, not a hidden fallback. It still meets the Phase
Goal and MIG-01/MIG-02: neither requires byte-for-byte identical HNSW rankings
across different engines, while the implemented rule proves non-vacuous
equal-length results, exact top-1, 80% minimum overlap, exact relative order for
common results, and a source-derived distance bound. Exact field, ID, metadata,
timestamp, and vector gates remain zero-tolerance checks.

### Required Artifacts

<!-- markdownlint-disable MD013 -->
| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `migration-policy.json` and policy validator | Fail-closed migration contract | ✓ VERIFIED | Artifact query found all Plan 20-01 files substantive; 61 focused policy/migration tests passed. |
| `inventory-solidstats-memory.py` | Lossless bounded source inventory | ✓ VERIFIED | Uses policy/oracle validation, private-output containment, source-shape aggregation, and no target-routing default during admission. |
| `20-SOURCE-INVENTORY.json` and `20-MAPPING-CONTRACT.json` | Sanitized source proof and approved mapping | ✓ VERIFIED | Current SHA-256 binding and approval fields were independently recomputed; only aggregate/public evidence is present. |
| `build-solidstats-memory-bundle.py` and transform manifest | Approval-bound transform and local import evidence | ✓ VERIFIED | Mapping/source-proof digests are checked before bundle creation; manifest records strategy, target identity, image, count, and ID-set evidence. |
| `verify-solidstats-memory-parity.py`, parity report, and Phase 21 handoff | Full parity, privacy-safe output, and gated cleanup | ✓ VERIFIED | Public report and handoff passed their own schema/privacy writers in a fresh temporary validation process; report is passing and handoff binds its digest. |
<!-- markdownlint-enable MD013 -->

### Key Link Verification

<!-- markdownlint-disable MD013 -->
| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Source proof | Mapping contract | Current file SHA-256 and approved contract validation | ✓ WIRED | Current proof digest equals the contract binding. |
| Source proof + mapping contract | Transform manifest | Both current digests required before private bundle or target access | ✓ WIRED | Independent recomputation matches all three committed downstream artifacts. |
| Transform bundle | Local Qdrant target | Loopback-only REST, pinned run/image, empty-target and bounded import checks | ✓ WIRED | Runtime evidence passed; code rejects non-loopback target URLs and attestation mismatch. |
| Frozen source fixtures | Parity comparator | Three source runs followed by target ranking comparison | ✓ WIRED | Source instability blocks comparison; the cross-engine ANN rule is explicit and exercised by regression tests. |
| Passing parity report | Phase 21 handoff and cleanup | Digest-bound handoff; run-bound cleanup only after success | ✓ WIRED | Handoff digest equals the current report. Cleanup code requires a passing, matching handoff and checks retained evidence before removal. |
<!-- markdownlint-enable MD013 -->

### Data-Flow Trace (Level 4)

<!-- markdownlint-disable MD013 -->
| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| Source inventory | Aggregate source proof | Immutable local snapshot through the exact v3.5.0 oracle | Runtime evidence confirms the real inventory run | ✓ FLOWING |
| Mapping contract | Approved preservation/routing rules | Human decision bound to the source-proof digest | Consumed by transform with no defaults | ✓ FLOWING |
| Transform manifest | Bundle, identity, vector, and target evidence | Exact source proof plus approved contract | Consumed by parity before target access | ✓ FLOWING |
| Parity report and handoff | Aggregate parity/provenance evidence | Complete isolated-target comparison | Passing report gates handoff and cleanup | ✓ FLOWING |
<!-- markdownlint-enable MD013 -->

### Behavioral Spot-Checks

<!-- markdownlint-disable MD013 -->
| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Policy and migration regression coverage | `timeout 60s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` | 61 tests passed | ✓ PASS |
| Public parity report and handoff schema/privacy contract | Fresh temporary invocation of the report and handoff writers | Both accepted | ✓ PASS |
| Current provenance chain | Recompute proof/contract/report digests and compare every downstream binding | All bindings matched; report verdict is pass | ✓ PASS |
| Full real local parity and cleanup | Main-owned sanitized runtime evidence | Field/ID/vector/recall parity passed; disposable target removed while retained provenance revalidated | ✓ PASS |
<!-- markdownlint-enable MD013 -->

### Probe Execution

No Phase 20 probe script is declared or present; no probe execution applies.

### Requirements Coverage

<!-- markdownlint-disable MD013 -->
| Requirement | Source Plans | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| MIG-01 | 20-01 through 20-09 | Legacy writes are frozen before export while old reads may continue until cutover. | ✓ SATISFIED | Frozen immutable source evidence is required by the inventory chain; the supplied local runtime record confirms the real procedure completed. |
| MIG-02 | 20-01 through 20-09 | Export, build, transform, and verification run locally; the VPS never runs old and new long-running stacks together; exact transform waits for reviewed mapping. | ✓ SATISFIED | Approved mapping digest precedes transform; committed code enforces local loopback target and parity provenance, and the supplied runtime record confirms complete local transform/parity. |
<!-- markdownlint-enable MD013 -->

### Anti-Patterns Found

No blocker or warning anti-patterns were found in Phase 20 implementation and
public evidence files. Empty collections in the code are local accumulators, not
rendered or returned stub data. No `TBD`, `FIXME`, or `XXX` marker was found.

## Gaps Summary

No gaps found. The ANN-equivalence change is explicit and remains sufficient for
the roadmap/MIG parity outcome; it is not used to relax exact identifier, field,
metadata, timestamp, vector, provenance, or cleanup controls.

---

_Verified: 2026-08-20T09:38:49Z_
_Verifier: the agent (gsd-verifier)_
