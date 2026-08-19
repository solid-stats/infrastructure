<!-- markdownlint-disable MD013 -->

# Phase 20: Local Corpus Migration - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution
> agents. Decisions are captured in `20-CONTEXT.md`; this log preserves the
> analysis.

**Date:** 2026-08-20
**Phase:** 20-local-corpus-migration
**Mode:** assumptions
**Areas analyzed:** frozen source boundary, mapping and corpus integrity,
embedding and parity gate

## Assumptions Presented

### Frozen Source Boundary

| Assumption | Confidence | Evidence |
| --- | --- | --- |
| Freeze legacy writes before one immutable local snapshot; read-only recall may continue until cutover. | Confident | `.planning/REQUIREMENTS.md`, `config/solidstats-memory/migration-policy.json`, `docs/solidstats-memory.md` |

### Mapping and Corpus Integrity

| Assumption | Confidence | Evidence |
| --- | --- | --- |
| Review the exact legacy and target source schemas before choosing the mapping; preserve IDs, documents, metadata, wing/room ownership, and timestamps. | Confident | `19-RESEARCH.md`, MemPalace v3.5.0 `base.py`, `chroma.py`, and `qdrant.py` |

### Embedding and Parity Gate

| Assumption | Confidence | Evidence |
| --- | --- | --- |
| Keep vector reuse versus re-embedding conditional on exact identity, dimension, metric, and serialization evidence; require deterministic field, vector, recall, and ranking parity. | Confident | `.planning/REQUIREMENTS.md`, MemPalace v3.5.0 `base.py`, `chroma.py`, and `qdrant.py` |

## Corrections Made

No corrections — all assumptions were confident and auto-accepted by the
autonomous workflow.

## External Research

- MemPalace v3.5.0 persists the backend-neutral record contract as IDs,
  documents, metadata, and optional embeddings. Metadata is opaque and must be
  preserved losslessly. Source: [backend contract](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/base.py).
- The Qdrant backend derives a UUIDv5 point ID while retaining the original ID
  as `mempalace_id`; it stores the document, metadata dictionary, and target
  `updated_at` in the payload. Source: [Qdrant backend](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/qdrant.py).
- Qdrant collections use Cosine distance. Chroma exposes its actual
  `hnsw:space`, while absent configuration means its default cannot be treated
  as proven compatible. Source: [Chroma backend](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/backends/chroma.py).
- MemPalace v3.5.0 has no supported cross-backend Chroma-to-Qdrant migration
  command. Its migration and repair commands are Chroma-specific. Source:
  [MemPalace CLI](https://github.com/MemPalace/mempalace/blob/v3.5.0/mempalace/cli.py).
