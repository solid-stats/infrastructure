<!-- markdownlint-disable MD003 MD013 MD041 -->

---

phase: 20-local-corpus-migration
plan: 06
subsystem: local-memory-parity
tags: [mempalace-v3.5.0, qdrant, ann, parity, provenance]
requires: [20-05]
provides: [sanitized passing parity report, digest-bound Phase 21 handoff]
affects: [21-live-cutover-and-recovery, MIG-01, MIG-02]
actuals: {tokens: 0, tasks: 2, commits: 16}
status: complete
---

# Phase 20 Plan 06: Exact Parity and Phase 21 Handoff Summary

The frozen source and isolated target passed exact field, ID, vector, and strict cross-engine ANN recall parity before the disposable target was removed.

## Accomplishments

- Verified 19,534 imported records for field, UUIDv5 identity, and vector parity with zero failures.
- Passed recall parity with three stable v3.5.0 source runs; five approved excluded fixtures and 21 excluded records were reconciled without exposing corpus values.
- Wrote digest-bound, privacy-validated parity and Phase 21 handoff artifacts, then removed only the run-bound isolated collection, container, and Qdrant data after pass-only checks.

## Deviation from Plan

Exact ordered-ID recall was not valid across distinct Chroma and Qdrant HNSW graphs. The accepted strict ANN equivalence retains equal result lengths, exact top-1, at least 80% per-fixture overlap, exact relative order for common IDs, and common distances bounded by the greater of source repeatability and eight float32 ULPs. Exact field, ID, and vector gates remain unchanged.

## Validation

- Full real parity, privacy validation, and digest binding for both public artifacts passed.
- 61 offline tests passed: 7 policy and 54 migration tests; Python compilation and diff checks passed.
- Retained snapshot, source, and bundle provenance revalidated after cleanup; the disposable container and data directory were absent.

## Phase 21 Boundary

Phase 21 must recompute handoff and provenance digests, revalidate retained bundle evidence, and perform any live restore only in that phase.

## Known Stubs

None.

## Self-Check: PASSED

- Public report and handoff exist and bind current provenance digests.
- Cleanup affected only the disposable run-bound target after the passing handoff was sealed.

<!-- markdownlint-enable MD003 MD013 MD041 -->
