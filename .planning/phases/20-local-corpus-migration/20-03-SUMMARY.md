---
phase: 20-local-corpus-migration
plan: 03
subsystem: offline-migration-prerequisites
tags: [mempalace, chroma, qdrant, freeze, snapshot]
requires:
  - 20-02
provides:
  - verified-frozen-source-boundary
  - verified-exact-v350-local-oracle
  - verified-local-docker-prerequisite
affects:
  - 20-04
  - 20-05
  - 20-06
tech_stack:
  added: []
  patterns:
    - immutable source snapshots
    - exact-version oracle isolation
    - local-only disposable target validation
key_files:
  created:
    - .planning/phases/20-local-corpus-migration/20-03-SUMMARY.md
  modified: []
decisions:
  - The frozen source boundary is a private immutable snapshot, not the live palace.
  - The exact v3.5.0 runtime is the only migration oracle.
  - Real source validation uses local Docker with no network and no shared target.
metrics:
  tasks_completed: 2
  files_modified: 1
actuals:
  tokens: 13597
  tasks: 2
  commits: 1
completed: 2026-08-20
status: complete
---

# Phase 20 Plan 03: Frozen Source and Local Oracle Summary

The legacy source is frozen and immutably captured, while the exact MemPalace
v3.5.0 oracle and local-only Docker path are proven for subsequent migration
plans.

## Accomplishments

- Proved the D-01 read-only boundary: all known legacy writers were covered,
  the sole data-volume writer was locked, and the service remained healthy for
  reads while mutating MCP tools were read-only.
- Created a private immutable snapshot of the complete legacy data volume with
  identity, configuration, embedder, and freeze-attestation sidecars.
- Verified the snapshot twice after transfer: it had 58 regular files, no
  symlinks, stable timestamps and digests, and a matching full-tree checksum.
- Verified the extracted v3.5.0 source and the deployed image have the same
  image identity. The old v3.4.1 installation was not used.
- Verified the pinned Qdrant image in a disposable, loopback-only local
  container, then removed the container and its volume.
- Ran the real inventory check twice inside the exact v3.5.0 image with no
  network. Both runs passed and left their output directory unchanged.

## Task Results

1. **Task 1: Prove the write freeze and immutable complete source snapshot**
   - Passed after explicit operator approval.
   - The freeze attestation precedes snapshot creation and the private source
     snapshot remains immutable.
2. **Task 2: Prove exact v3.5.0 oracle provenance and local Docker access**
   - Passed after explicit operator approval.
   - The exact oracle source, image, Docker daemon, and pinned local Qdrant
     prerequisite were independently checked.

## Validation

- Generic MemPalace reads and status checks remained available after the
  write lock; SQLite integrity passed with 19,555 drawers reported.
- The frozen snapshot passed two independent, check-only inventory runs in
  the exact image. A byte-identical ephemeral copy was used because ChromaDB
  opens SQLite with writable service state; the authoritative snapshot was
  never opened for writing.
- The inventory command ran with `--network none`, the approved extracted
  v3.5.0 source, and `/usr/local/bin/python` from that exact image.
- The Qdrant validation used the corrected pinned image reference from
  `k8s/memory/10-qdrant.yaml`, bound only to loopback, and did not contact a
  VPS or shared target.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Supplied the exact oracle interpreter to the real check**

- **Found during:** Task 1 validation.
- **Issue:** The planned command predates the required `--oracle-python`
  argument and could not prove raw Chroma extraction with the exact runtime.
- **Fix:** Ran both checks inside the exact v3.5.0 image using its Python
  interpreter and the approved extracted source contract.
- **Impact:** Preserved the plan's exact-version and local-only guarantees.

**2. [Rule 2 - Correctness] Kept the authoritative snapshot read-only**

- **Found during:** Task 1 validation.
- **Issue:** ChromaDB opens SQLite with writable service state even for an
  inventory operation.
- **Fix:** Each check used a byte-identical ephemeral clone while retaining
  the authoritative snapshot as immutable private evidence.
- **Impact:** Prevented validation from mutating the migration source.

## Known Stubs

None.

## Next Phase Readiness

Plans 20-04 through 20-06 may consume the private frozen source and exact
local oracle. This plan does not claim transform, import, field parity, vector
parity, recall parity, deployment, or cutover completion.

## Self-Check: PASSED

- The summary exists at the required phase path.
- The prerequisite evidence is recorded without corpus text, identifiers,
  metadata, vectors, credentials, or private snapshot paths.
