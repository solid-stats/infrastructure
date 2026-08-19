# SolidStats Memory Operations

## Safety Boundary

SolidStats memory is an isolated service named `solidstats_memory`. It does not
share credentials, Qdrant, storage, Kubernetes identity, or client aliases with
personal memory or VocalClub. The old SolidStats palace is read-only from the
start of migration until it is retained as an offline snapshot.

Never run the old and new long-running stacks simultaneously on the VPS. Build,
inventory, transform, and parity checks run on the local workstation. The exact
transform and choice between vector reuse and re-embedding remain blocked until
source review and embedding evidence are complete.

## Repository Boundary

Runtime artifacts belong under `k8s/memory/` in namespace
`solidstats-memory`. Qdrant is private. MemPalace is the only public service and
is exposed through host nginx at HTTPS `/solidstats/mcp`. Application images are
built outside this repository; deployment requires an immutable image digest.

## Policy Gate

```sh
python3 scripts/validate-solidstats-memory-policy.py
```

A prepared offline bundle must contain `manifest.json` with schema version 1,
`source_backend: chroma`, `target_backend: qdrant`,
`legacy_writes_frozen: true`, evidence-recorded flags for embedding strategy,
model/version, dimension, corpus checksum, and parity evaluation, plus a
non-empty `files` list.
Every file entry contains a safe relative path and lowercase SHA-256 digest.

```sh
python3 scripts/validate-solidstats-memory-policy.py --bundle /path/to/bundle
```

Passing this gate proves packaging integrity only. It does not prove that the
cross-backend record mapping is correct.

## Migration Sequence

1. Freeze legacy writes and record the timestamp.
2. Create and checksum an offline source snapshot.
3. Inventory room/wing counts, bytes, duplicate IDs, and vector dimensions.
4. Review and version the exact Chroma-to-Qdrant field mapping.
5. Record whether vectors are reused or re-embedded, exact model/version,
   dimension, corpus checksum, and parity evaluation; choose only from evidence.
6. Transform locally using the source-reviewed mapping.
7. Validate bundle checksums and import into isolated local Qdrant.
8. Compare identifiers, text, metadata, room/wing ownership, timestamps, vector
   evidence, deterministic recalls, and archive labeling.
9. Create a Qdrant snapshot and MemPalace metadata archive with manifest and
   checksums.
10. Stop the old VPS stack before starting the new long-running stack.
11. Deploy, restore in isolation, validate, cut over `/solidstats/mcp`, and then
    register only the `solidstats_memory` MCP client.

## Recall and Capture Contract

Recall is wing-scoped and budgeted. On semantic miss, list drawers and fetch the
selected drawer in full. Semantic tunnels, KG mirroring, diary journaling, plan
recall, and automatic capture hooks remain disabled. Archive wings are untrusted
historical evidence and are never automatically mined.

Capture only durable conclusions with Task, Outcome, Decisions, Validation, and
Sources. Deduplicate before capture and read back after capture. Never capture
raw logs, diffs, chat, build output, temporary diagnostics, or generated files.

## Backup and Restore

Backups combine a Qdrant collection snapshot from
`POST /collections/{collection}/snapshots` with a MemPalace metadata archive,
manifest, and checksums under `backups/solidstats-memory/`. Restore always targets
an isolated collection and is verified before any active alias or client changes.
Legacy KG and tunnel deletion requires a separate exact-ID approval.

## Post-cutover Archive Distillation

Archive distillation is a separate post-cutover phase and does not block the
runtime migration. Process each archive wing read-only in bounded shards using
low-cost extraction agents. Extractors produce candidates only; they never
write to active memory or mutate frozen archive drawers.

Each candidate records its exact archive wing and drawer ID, proposed owning
active wing and room, durable conclusion, provenance, current verification
sources, and confidence. Deduplicate candidates before curator review. The
curator verifies survivors against current repository or operational evidence
and creates new active semantic drawers only for confirmed conclusions. Track
completed shards, rejection reasons, and promotions so later runs do not rescan
finished work.

## Unresolved Operator Evidence

Do not deploy until the immutable MemPalace image, host-source NetworkPolicy CIDR,
storage sizing, collection naming, metrics surface, and backup uploader contract
are verified. Secret values never enter this repository or planning artifacts.
