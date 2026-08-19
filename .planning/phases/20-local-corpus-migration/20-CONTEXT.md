<!-- markdownlint-disable MD001 MD033 -->

# Phase 20: Local Corpus Migration - Context

**Gathered:** 2026-08-20 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Freeze writes to the legacy SolidStats Chroma palace, take one immutable and
checksummed source snapshot, review the exact persisted record and embedding
contracts, transform the corpus on the local 30 GB machine, import it into an
isolated Qdrant instance, and prove identifier, document, metadata, vector, and
recall parity. Live deployment, MCP client cutover, restore rehearsal, and old
palace retirement remain in Phase 21.
</domain>

<decisions>
## Implementation Decisions

### Frozen Source Boundary

- **D-01:** Legacy writes stop before the source snapshot is taken. Read-only
  recall may continue until cutover, but the migration source is one immutable
  post-freeze snapshot with a recorded freeze time and checksum.
- **D-02:** The snapshot includes the complete Chroma palace and all identity
  sidecars needed to prove the deployed MemPalace, Chroma, collection, and
  embedding configuration. A checksum without that provenance is insufficient.

### Mapping and Corpus Integrity

- **D-03:** The transform follows the reviewed MemPalace v3.5.0 backend
  contract. It preserves every source ID, document byte sequence, metadata
  dictionary, source timestamp, and vector selected for reuse without inventing
  missing defaults.
- **D-04:** The original MemPalace ID remains the canonical migration identity.
  Qdrant stores it as `mempalace_id`; the Qdrant point ID is the deterministic
  UUIDv5 derived by MemPalace v3.5.0. Parity must prove this mapping is
  bijective.
- **D-05:** Wing, room, archive label, and content timestamps remain metadata.
  Qdrant's ingestion-time `updated_at` does not replace source timestamps.
- **D-06:** The target collection name is derived from the actual palace ID,
  namespace, and collection configuration using the pinned v3.5.0 source logic.
  No hand-written collection name is accepted as evidence.

### Embedding and Parity Gate

- **D-07:** Vector reuse is allowed only when the frozen snapshot proves the
  same embedding identity and configuration, vector dimension, compatible
  source metric, target Cosine semantics, and compatible serialization. Equal
  dimensions alone do not permit reuse.
- **D-08:** If any embedding identity or metric evidence is absent or
  incompatible, re-embed locally with the chosen pinned model and record that
  decision in the migration manifest.
- **D-09:** Acceptance requires deterministic field and vector comparison plus
  recall and ranking fixtures against the frozen source and isolated target.
  Record counts and package checksums alone cannot close MIG-02.

### Agent's Discretion

The planner may choose the offline bundle format, script boundaries, fixture
format, and local isolated Qdrant orchestration, provided they preserve the
locked evidence and fail-closed parity contract above.
</decisions>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

- `.planning/REQUIREMENTS.md`
- `.planning/phases/19-solidstats-memory-foundation/19-CONTEXT.md`
- `.planning/phases/19-solidstats-memory-foundation/19-RESEARCH.md`
- `.planning/phases/19-solidstats-memory-foundation/19-VERIFICATION.md`
- `docs/solidstats-memory.md`
- `config/solidstats-memory/migration-policy.json`
- `scripts/validate-solidstats-memory-policy.py`
- `tests/test-solidstats-memory-policy.py`
- [SolidStats memory contract migration](https://github.com/solid-stats/agent-instructions/blob/master/docs/solidstats-memory-contract-migration.md)
- [MemPalace v3.5.0 release](https://github.com/MemPalace/mempalace/releases/tag/v3.5.0)
- [MemPalace v3.5.0 backend contract](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/base.py)
- [MemPalace v3.5.0 Chroma backend](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/chroma.py)
- [MemPalace v3.5.0 Qdrant backend](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/qdrant.py)
</canonical_refs>

<code_context>

## Existing Code Insights

### Reusable Assets

- `config/solidstats-memory/migration-policy.json` already locks the migration
  bundle contents, checksum algorithm, active rooms, archive wings, and
  fail-closed verification vocabulary.
- `scripts/validate-solidstats-memory-policy.py` and
  `tests/test-solidstats-memory-policy.py` provide the existing policy barrier
  and test style to extend with real bundle semantics.
- `k8s/memory/10-qdrant.yaml` and `k8s/memory/20-mempalace.yaml` define the
  intended target backend boundary, while remaining outside the local
  transformation path.

### Established Patterns

- Infrastructure scripts use Python standard library only, explicit required
  inputs, deterministic output, and exit code 64 for configuration errors.
- Generated or supplied evidence is rejected when required operator markers or
  provenance fields remain unresolved.
- Secret values never enter git, logs, planning artifacts, or migration bundles.

### Integration Points

- The new source inventory and transform tooling extends the Phase 19 migration
  policy rather than creating a second contract.
- The migration manifest becomes the machine-readable input to Phase 21 restore
  and cutover gates.
- The isolated target must use the same namespace and collection derivation as
  the final MemPalace runtime, without deploying that runtime in this phase.
</code_context>

<specifics>
## Specific Ideas

- Inventory metadata keys and field-presence counts before mapping them.
- Prove `source ID -> mempalace_id -> deterministic UUIDv5 point ID` for every
  record.
- Hash documents and normalized metadata independently so a structurally valid
  bundle cannot conceal semantic field loss.
- Treat re-embedding as the safe default when source identity or metric evidence
  cannot be proven from the frozen snapshot.
</specifics>

<deferred>
## Deferred Ideas

- Live Qdrant restore, MCP deployment, client registration, reversible cutover,
  and rollback rehearsal belong to Phase 21.
- Archive distillation and promotion into active semantic drawers belong to
  Phase 22.
</deferred>
