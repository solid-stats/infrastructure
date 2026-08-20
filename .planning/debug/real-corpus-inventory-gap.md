---
status: resolved
trigger: >-
  The Phase 20 source inventory passes its synthetic and exact-version
  check-only gates but rejects the first real frozen legacy record.
created: 2026-08-20
updated: 2026-08-20
---

# Debug Session: Real Corpus Inventory Gap

## Symptoms

- Expected behavior: the exact MemPalace 3.5.0 inventory accepts the frozen
  legacy Chroma corpus without inventing, dropping, or normalizing source
  metadata.
- Actual behavior: both check-only runs pass, but the full inventory rejects
  record 1 with a value-free `invalid` diagnostic.
- Error messages: `FAIL: record-1-<digest>`; the digest is intentionally not
  reproduced here.
- Timeline: first observed on 2026-08-20 during the operator-approved real
  Phase 20 snapshot run. Synthetic tests had passed before real data existed.
- Reproduction: run the full inventory against a byte-identical ephemeral
  writable clone of the verified immutable snapshot in the exact MemPalace
  3.5.0 image with networking disabled.

## Current Focus

- hypothesis: confirmed — the synthetic contract invented a mandatory
  `source_timestamp` key and applies target routing labels to legacy source
  metadata before preserving it.
- test: compared implementation, policy, accepted decisions, fixture provenance,
  pinned source semantics, and aggregate real metadata shape without emitting
  corpus values.
- expecting: confirmed local validation defect plus an unresolved data-contract
  decision for timestamp and legacy-label mapping.
- next_action: obtain explicit mapping and timestamp-semantics approval before
  changing inventory, policy, bundle validation, fixtures, or parity behavior.

## Evidence

- timestamp: 2026-08-20; investigation started from the persisted aggregate
  evidence only; private snapshot contents, identifiers, documents, metadata
  values, and vectors remain out of scope for this session.
- timestamp: 2026-08-20; the repository is on the intentional concurrent
  planning branch with an untracked session file; no fetch or worktree
  mutation will be performed while establishing source provenance.
- timestamp: 2026-08-20; two exact-image check-only runs passed and left the
  private output directory unchanged.
- timestamp: 2026-08-20; full inventory rejected record 1 at
  `_validated_record` before scope classification.
- timestamp: 2026-08-20; aggregate shape inspection found all 19,555 records
  have `filed_at`; 19,364 also have numeric `source_mtime` and string
  `content_date`; none have `source_timestamp`.
- timestamp: 2026-08-20; aggregate scope inspection found 19,469 records in
  five canonical unsuffixed repository wings, 65 in the shared source wing,
  none in target `*-archive` wings, and only 3 records satisfying the current
  combined wing-and-room allowlist. The scope gate would therefore reject
  essentially the whole intended archive corpus after timestamp validation.
- timestamp: 2026-08-20; pinned upstream v3.5.0 source states that miners
  emit `filed_at`, optionally emit numeric `source_mtime` and content-derived
  `content_date`, and resolve dates by preferring `content_date` before
  `filed_at`. No producer for `source_timestamp` exists in that package.
- timestamp: 2026-08-20; the first record otherwise had a bounded string
  document, lossless JSON metadata, a 384-dimensional finite vector, and no
  structural failure.
- timestamp: 2026-08-20; the accepted decision pack says preserve legacy
  repository content under per-repository `*-archive` wings, while Phase 20
  D-03 and D-05 require exact metadata preservation.
- timestamp: 2026-08-20; source inspection finds the inventory hard-codes a
  `source_timestamp` field with UTC-seconds syntax before writing output and
  subsequently requires source `room` and `wing` values to equal target policy
  labels.
- timestamp: 2026-08-20; the policy and public validator duplicate the same
  timestamp field name, while every happy-path fixture supplies that key and
  target-shaped labels. The local test suite therefore verifies only the
  synthetic schema, not legacy metadata compatibility.
- timestamp: 2026-08-20; local policy validation and the 20 inventory/migration
  tests pass, confirming the synthetic contract is self-consistent rather than
  confirming it represents the frozen corpus.

## Eliminated

- A moving source: the writer lease is held, mutating MCP tools are read-only,
  and the snapshot tree and raw fingerprints match their attestations.
- An oracle-version mismatch: the generated reader runs under the exact
  MemPalace 3.5.0 image and approved extracted source.
- A malformed document, metadata object, or vector in the first record:
  aggregate shape checks passed those boundaries.
- The proposition that the v3.5.0 source contract requires a metadata key named
  `source_timestamp`: the pinned-source aggregate and source semantics provide
  `filed_at`, optional `source_mtime`, and optional `content_date` instead.

## Contradiction Map

<!-- markdownlint-disable MD013 -->

| Accepted source/target intent | Implemented inventory behavior | Consequence |
| --- | --- | --- |
| D-03 preserves the source metadata dictionary without invented defaults. | `_validated_record` requires a missing metadata key with an invented format. | Every real record fails before export. |
| D-05 retains source wing, room, archive label, and timestamps as metadata. | `_build_source_inventory` admits only target archive wings and active rooms. | Almost the entire source corpus would be rejected after the timestamp gate. |
| The decision pack routes legacy content to target archives after preserving the raw corpus. | The policy treats destination labels as a prerequisite for source acceptance. | The required mapping is assumed rather than reviewed or proven. |

<!-- markdownlint-enable MD013 -->

## Smallest Safe Correction Boundary

Keep source inventory limited to source-safe checks: identifier uniqueness,
document and metadata losslessness, bounds, vectors, and aggregate observation
of metadata-key and label presence. Do not require a target metadata key,
timestamp syntax, room, or wing before inventory/export. Preserve all source
metadata verbatim in the private source artifact. Apply timestamp resolution
and target routing only in a later mapping stage once their contract is
explicitly accepted and parity-tested.

## Unresolved High-Risk Contract Decision

The migration must not choose a legacy-to-target wing, room, or archive-label
mapping, nor select timestamp precedence or normalization. The observed source
fields support possible source-time semantics but do not select one. Those
choices change the archived data contract and must be approved before transform
or parity code is changed.

## Resolution

- root_cause: the source inventory and bundle policy were built around a
  synthetic target schema, then applied as a source precondition. This invents
  a mandatory timestamp key and treats destination taxonomy as existing legacy
  metadata, contradicting exact-preservation decisions.
- fix: not applied. Separate source inventory integrity from target mapping;
  retain the unresolved timestamp and legacy-label decisions for explicit
  approval.
- verification: aggregate real-corpus evidence, pinned v3.5.0 source semantics,
  implementation/fixture provenance, and the passing synthetic test suite all
  agree on the mismatch without exposing corpus values.
- files_changed: .planning/debug/real-corpus-inventory-gap.md
