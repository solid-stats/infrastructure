---
phase: 20-local-corpus-migration
plan: 05
subsystem: offline-memory-migration
tags: [mempalace-v3.5.0, qdrant, transform, privacy, provenance]
requires:
  - phase: 20-08
    provides: approved inventory-bound mapping contract
  - phase: 20-04
    provides: sanitized immutable source inventory proof
provides:
  - deterministic approval-bound private transform bundle
  - isolated loopback Qdrant import evidence
  - sanitized transform manifest with target ID parity proof
affects: [20-06, MIG-01, MIG-02]
actuals:
  tokens: 14238
  tasks: 2
  commits: 11
tech-stack:
  added: []
  patterns:
    - exact-version oracle subprocesses
    - contained snapshot sidecars
    - loopback-only Qdrant import verification
    - allowlisted public migration evidence
key-files:
  created:
    - .planning/phases/20-local-corpus-migration/20-TRANSFORM-MANIFEST.json
    - .planning/phases/20-local-corpus-migration/20-05-SUMMARY.md
  modified:
    - scripts/build-solidstats-memory-bundle.py
    - tests/test-solidstats-memory-migration.py
key-decisions:
  - Approved mapping semantics are validated before private record transformation.
  - The target remains a retained loopback-only Qdrant run for Plan 20-06 parity.
  - Public evidence contains only allowlisted aggregates, digests, and pinned image provenance.
requirements-completed: [MIG-01, MIG-02]
coverage:
  - id: D1
    description: Approval-bound deterministic transform and v3.5.0 point mapping.
    requirement: MIG-02
    verification:
      - kind: unit
        ref: tests/test-solidstats-memory-migration.py
        status: pass
    human_judgment: false
  - id: D2
    description: Empty loopback Qdrant import with schema, count, and target-ID parity proof.
    requirement: MIG-02
    verification:
      - kind: integration
        ref: local exact-image aggregate verification
        status: pass
    human_judgment: false
duration: continuation-based execution
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 05: Approval-Bound Local Transform Summary

The frozen corpus was transformed through the exact MemPalace v3.5.0 mapping
and imported into a new loopback-only Qdrant target with schema, count, and
target-ID-set parity evidence, while private data remains outside the repository.

## Accomplishments

- Built deterministic target points from the current approved mapping contract,
  preserving the exact v3.5.0 UUIDv5 identity and selecting vector reuse only
  when all D-07 predicates matched.
- Imported bounded batches into a new empty local Qdrant collection using the
  exact pinned image digest and verified the post-create Cosine schema,
  acknowledgement shape, final count, and complete target ID-set digest.
- Recorded sanitized provenance in `20-TRANSFORM-MANIFEST.json`; it binds the
  exact current source-inventory and mapping-contract bytes and contains no
  private paths, records, source IDs, documents, metadata, vectors, or secrets.

## Validation

- Full offline suite passed: 46 tests.
- Python compilation, CLI help, contract/digest assertions, manifest privacy and
  shape assertions, and `git diff --check` passed.
- Aggregate live checks passed for the labeled Qdrant container: loopback-only
  binding, exact pinned image, health, private-mode evidence, collection schema,
  empty-target proof, final count, target ID digest, and run-ID consistency.

## Task Commits

1. **Task 1 RED:** `2ba4cb9` — initial failing transform contract tests.
2. **Task 1 GREEN:** `b8e123b` — approval-bound transform and importer.
3. **Rule-driven regression RED:** `d0847e7` — isolated-import safeguards.
4. **Rule-driven regression GREEN:** `dc957b0` — import hardening.
5. **Fallback correction:** `5c3a01d` — reembed artifact only for fallback.
6. **Private shard bound correction:** `6f0f97c` — bounded larger source shards.
7. **Oracle API RED:** `7164b48` — v3.5.0 `PalaceRef` import fixture.
8. **Oracle API GREEN:** `8e88555` — exact backend-base import.
9. **Public-manifest RED:** `adc080f` — fixed schema privacy regression.
10. **Public-manifest GREEN:** `7499dc8` — narrow schema allowlist.
11. **Task 2 evidence:** `09c59f1` — sanitized transform manifest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Accepted the approved fail-closed collision wording**

- **Found during:** Task 2 preflight.
- **Issue:** The validator required an obsolete shorthand instead of the
  approved contract's explicit collision sentence.
- **Fix:** Validated the fail-closed semantic and reserved-key condition.
- **Commits:** `d0847e7`, `dc957b0`.

**2. [Rule 2 - Correctness] Resolved identity sidecars from the snapshot manifest**

- **Found during:** Task 2 preflight.
- **Issue:** Identity and configuration sidecars were hardcoded rather than
  bound to contained manifest paths.
- **Fix:** Used contained regular-file resolution and rejected unsafe paths.
- **Commits:** `d0847e7`, `dc957b0`.

**3. [Rule 2 - Correctness] Verified real Qdrant acknowledgement and target state**

- **Found during:** Task 2 integration review.
- **Issue:** The importer expected a Boolean upsert result and did not prove
  live schema or complete target ID parity.
- **Fix:** Required completed operation records, exact pinned image binding,
  post-create schema equality, empty count, and bounded target-ID scrolling.
- **Commits:** `d0847e7`, `dc957b0`.

**4. [Rule 3 - Blocking] Allowed bounded private vector shards above 64 MiB**

- **Found during:** First local execution.
- **Issue:** The verified private vector shard exceeded an unrelated generic
  JSON cap.
- **Fix:** Added a separate 512 MiB bounded source-artifact cap while retaining
  line-by-line parsing and record limits.
- **Commit:** `6f0f97c`.

**5. [Rule 1 - Bug] Corrected the exact v3.5.0 oracle import**

- **Found during:** Exact-image execution.
- **Issue:** `PalaceRef` was imported from an API path absent in v3.5.0.
- **Fix:** Imported it from `mempalace.backends.base` and added a faithful API fixture.
- **Commits:** `7164b48`, `8e88555`.

**6. [Rule 1 - Bug] Allowed only the fixed public transform schema slash**

- **Found during:** Successful import closeout.
- **Issue:** Generic slash rejection blocked the script's own fixed schema value.
- **Fix:** Added a narrow exact schema allowlist while retaining rejection for
  all alternative schema values and other slash-bearing fields.
- **Commits:** `adc080f`, `7499dc8`.

**7. [Rule 3 - Blocking] Used the exact-image interpreter and corrected local
runtime setup**

- **Found during:** Main-owned integration execution.
- **Issue:** The continuation lacked the exact interpreter, and the disposable
  Qdrant run required local UID permission and storage-mount corrections.
- **Fix:** The main execution used the retained exact interpreter, a fresh empty
  private storage mount with correct local ownership, and a loopback-only
  labeled container.
- **Verification:** Exact-image transform/import and aggregate target checks passed.

**Total deviations:** 7 auto-fixed issues. All changes were required for
correctness, privacy, or execution; no live runtime, Kubernetes, MCP, or client
configuration was changed.

## Known Stubs

None.

## Next Phase Readiness

Plan 20-06 can consume the retained successful private bundle and running
loopback Qdrant target for field, vector, and recall parity. Failed private runs
remain stopped and retained for diagnosis; they are not repository artifacts.

## Self-Check: PASSED

- The transform manifest, code, tests, and all Task 1/Task 2 commits exist.
- The successful target evidence is aggregate-only and privacy-shaped.
- Plan 20-06 is the next dependency in the authoritative chain.
