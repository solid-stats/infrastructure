<!-- markdownlint-disable MD013 -->

# Phase 20: Local Corpus Migration - Research

**Researched:** 2026-08-20
**Domain:** Offline, evidence-gated Chroma-to-Qdrant corpus migration
**Confidence:** MEDIUM — the v3.5.0 storage contract is source-verified, but the frozen source corpus, its sidecars, and an executable v3.5.0 local environment remain unavailable.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Legacy writes stop before the source snapshot is taken. Read-only recall may continue until cutover, but the migration source is one immutable post-freeze snapshot with a recorded freeze time and checksum.
- **D-02:** The snapshot includes the complete Chroma palace and all identity sidecars needed to prove the deployed MemPalace, Chroma, collection, and embedding configuration. A checksum without that provenance is insufficient.
- **D-03:** The transform follows the reviewed MemPalace v3.5.0 backend contract. It preserves every source ID, document byte sequence, metadata dictionary, source timestamp, and vector selected for reuse without inventing missing defaults.
- **D-04:** The original MemPalace ID remains the canonical migration identity. Qdrant stores it as `mempalace_id`; the Qdrant point ID is the deterministic UUIDv5 derived by MemPalace v3.5.0. Parity must prove this mapping is bijective.
- **D-05:** Wing, room, archive label, and content timestamps remain metadata. Qdrant's ingestion-time `updated_at` does not replace source timestamps.
- **D-06:** The target collection name is derived from the actual palace ID, namespace, and collection configuration using the pinned v3.5.0 source logic. No hand-written collection name is accepted as evidence.
- **D-07:** Vector reuse is allowed only when the frozen snapshot proves the same embedding identity and configuration, vector dimension, compatible source metric, target Cosine semantics, and compatible serialization. Equal dimensions alone do not permit reuse.
- **D-08:** If any embedding identity or metric evidence is absent or incompatible, re-embed locally with the chosen pinned model and record that decision in the migration manifest.
- **D-09:** Acceptance requires deterministic field and vector comparison plus recall and ranking fixtures against the frozen source and isolated target. Record counts and package checksums alone cannot close MIG-02.

### the agent's Discretion

The planner may choose the offline bundle format, script boundaries, fixture format, and local isolated Qdrant orchestration, provided they preserve the locked evidence and fail-closed parity contract above.

### Deferred Ideas (OUT OF SCOPE)

- Live Qdrant restore, MCP deployment, client registration, reversible cutover, and rollback rehearsal belong to Phase 21.
- Archive distillation and promotion into active semantic drawers belong to Phase 22.
</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
| --- | --- | --- |
| MIG-01 | Legacy SolidStats writes are frozen before export; old reads may continue until cutover. | Record an operator-confirmed freeze time before snapshot creation; bind all later artifacts to the snapshot checksum. |
| MIG-02 | Export, build, transform, and verification run locally; the VPS never runs old and new long-running stacks together. The exact transform stays blocked until its source mapping is reviewed. | Use an isolated local Qdrant, a v3.5.0-reviewed mapping, and field/vector/recall parity gates. Do not deploy or restore on the VPS. |

</phase_requirements>

## Summary

Phase 20 should be planned as a controlled offline data migration with two gates before any transformation: an operator-confirmed write freeze and a complete immutable source snapshot that includes backend and embedder sidecars. The current repository validator already rejects a bundle that omits the Chroma source, Qdrant target, freeze attestation, embedding evidence, corpus checksum, parity evidence, or safe SHA-256-indexed files. [VERIFIED: scripts/validate-solidstats-memory-policy.py:91-138]

Use MemPalace v3.5.0 as the transform oracle, not a hand-written approximation. Its common backend contract represents records as IDs, documents, metadata, and optional embeddings; the Qdrant implementation persists the original ID in `mempalace_id`, generates the point ID with UUIDv5, and writes document/metadata in the payload. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/base.py] [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]

The repository must fail closed on missing source evidence. This workstation has MemPalace 3.4.1, while the phase is pinned to v3.5.0; Docker is installed but the current account cannot access the daemon. Neither condition permits silently using an older backend or claiming an isolated-Qdrant import. [VERIFIED: local command probes on 2026-08-20]

**Primary recommendation:** Implement three stdlib-only Python commands—inventory/export, transform/import, and parity verification—whose only accepted inputs are a frozen snapshot, a locally pinned v3.5.0 execution environment, and an isolated Qdrant endpoint; every uncertain mapping or vector compatibility condition must stop the run.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
| --- | --- | --- | --- |
| Freeze and source snapshot | Operations | Storage | The source service owner must stop writes; the local workflow only records and verifies the resulting immutable evidence. |
| Inventory and bundle construction | Local migration tool | Storage | A local process reads the frozen Chroma corpus and sidecars, emits checksummed non-secret artifacts, and never contacts the VPS. |
| ID/payload/vector transformation | Local migration tool | API / Backend | The v3.5.0 backend contract defines target record semantics; the local tool applies and verifies them. |
| Isolated target import | Local Qdrant | Local migration tool | Qdrant receives points only in a disposable local collection; the migration tool creates and probes it. |
| Parity and recall fixtures | Local migration tool | Local Qdrant | Field, vector, and ranking comparisons need both the frozen source and the isolated target. |
| Restore, edge cutover, and recovery | Operations | Kubernetes | These are explicitly Phase 21 responsibilities and must not enter this phase. |

## Project Constraints (from AGENTS.md)

- Do not read secret files, log credentials, or place secret values in git, logs, bundles, or planning artifacts. [VERIFIED: AGENTS.md]
- Infrastructure owns runtime manifests, deployment wiring, scripts, and runbooks; it does not own application image builds or production management. [VERIFIED: AGENTS.md]
- Kubernetes work uses explicit resources, probes, least-privilege ServiceAccounts, non-root security contexts, and network isolation; Phase 20 must not bypass the existing hardened boundary. [VERIFIED: AGENTS.md]
- Internal repository and planning documents are English. [VERIFIED: AGENTS.md]
- Markdown edits must be formatted with `markdownlint-cli2 --fix`. [VERIFIED: AGENTS.md]

## Standard Stack

### Core

| Library / tool | Version | Purpose | Why standard |
| --- | --- | --- | --- |
| MemPalace source contract | v3.5.0 | Defines Chroma read shape, Qdrant payload layout, UUIDv5 point identity, collection naming, and explicit-embedding writes. | The phase decisions pin this exact upstream tag; its release documents the Qdrant bulk-scroll reliability work. [CITED: https://github.com/MemPalace/mempalace/releases/tag/v3.5.0] |
| Python standard library | Python 3.14.4 available | Deterministic JSON, SHA-256, filesystem containment, subprocess invocation, and test fixtures. | Existing policy tooling already uses only standard-library Python. [VERIFIED: scripts/validate-solidstats-memory-policy.py:1-164] |
| Qdrant | existing pinned `v1.19.0-unprivileged` image | Disposable local target for import and parity only. | The existing target manifest pins Qdrant and exposes no public Service. [VERIFIED: k8s/memory/10-qdrant.yaml:1-119] |

### Supporting

| Tool | Version / state | Purpose | When to use |
| --- | --- | --- | --- |
| Docker Compose | v5.4.0 installed; daemon inaccessible to this session | Start an isolated local Qdrant with a new empty data directory and no host exposure beyond loopback. | Only after an authorized local runner can access the Docker daemon. [VERIFIED: local command probes on 2026-08-20] |
| `unittest` | standard library | Regression tests for manifests, malformed input, mapping fixtures, and parity reports. | Extend the repository's existing test style. [VERIFIED: tests/test-solidstats-memory-policy.py:1-154] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
| --- | --- | --- |
| Source-derived conversion | A generic Chroma-to-Qdrant copier | Rejected: it cannot prove MemPalace collection naming, payload keys, UUID namespace, metadata handling, or embedder sidecars. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py] |
| Vector reuse only with complete evidence | Always reuse equal-dimension vectors | Rejected by locked D-07: equal dimensions do not establish model, metric, or serialization compatibility. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:36-39] |
| Local isolated import | VPS rehearsal | Rejected by MIG-02 and the phase boundary; VPS restore/cutover/recovery are Phase 21. [VERIFIED: .planning/REQUIREMENTS.md:28-30] |

**Installation:** No new package installation is recommended in this phase. Build or obtain an independently reviewed local environment that resolves the official MemPalace `v3.5.0` source revision, then record its artifact checksum in the bundle. [CITED: https://github.com/MemPalace/mempalace/releases/tag/v3.5.0]

## Package Legitimacy Audit

No external package is proposed for installation. The plan consumes the existing pinned Qdrant image and must obtain a reviewed MemPalace v3.5.0 execution environment; its provenance is the upstream signed release tag, not a newly suggested registry package. [CITED: https://github.com/MemPalace/mempalace/releases/tag/v3.5.0]

## Architecture Patterns

### System Architecture Diagram

```text
Operator write freeze
        |
        v
Immutable Chroma palace + sidecars -----> inventory / integrity checks
        |                                      |
        |                                      +--> reject missing model, metric, ID, or metadata evidence
        v
Checksummed source snapshot
        |
        v
v3.5.0 mapping oracle --> canonical JSONL + manifest + recall fixtures
        |                                   |
        |                                   +--> bundle validator / SHA-256 verification
        v
isolated local Qdrant <----- import (new empty collection)
        |
        v
field + ID + vector + ranking parity ------> pass bundle for Phase 21
                                         \--> fail: preserve evidence, do not cut over
```

### Recommended Project Structure

```text
scripts/
├── inventory-solidstats-memory.py       # snapshot inventory and source evidence extraction
├── build-solidstats-memory-bundle.py    # canonical export, transform, and isolated import
└── verify-solidstats-memory-parity.py   # field/vector/recall comparisons and report
tests/
├── test-solidstats-memory-policy.py     # existing bundle-policy barrier
└── test-solidstats-memory-migration.py  # fixture-driven transform and failure cases
config/solidstats-memory/
└── migration-policy.json                # existing non-secret policy contract
```

### Pattern 1: Evidence-first immutable snapshot

**What:** Treat the snapshot plus sidecars as the only migration source; calculate an inventory before a transform and bind every output artifact to the source checksum.

**When to use:** Always. The legacy service may remain readable, but no object read after the freeze may be treated as the migration source unless it is inside the recorded snapshot. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:12-24]

**Implementation:** Inventory each collection with paginated `get(..., include=[documents, metadatas, embeddings])`, record count, duplicate IDs, document byte hashes, canonical metadata hashes, vector dimensions, source timestamp-key presence, sidecar hashes, and collection configuration. The v3.5.0 Chroma adapter exposes exactly those fields and accepts `limit`/`offset`; cross-check the paged total against the collection count to catch partial extraction. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/chroma.py]

### Pattern 2: Source-derived Qdrant mapping with preflight assertions

**What:** Import only records that pass type and serialization preflight, then construct the target through the v3.5.0 mapping rules.

**When to use:** After the inventory passes and vector strategy is selected from evidence.

**Verified v3.5.0 mapping:** The Qdrant backend uses these payload names verbatim: `"mempalace_id"`, `"document"`, and `"metadata"`; its point ID is `uuid.uuid5(UUID("c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1"), str(doc_id))`; it writes a separate ingestion `"updated_at"` field. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]

**Critical guard:** Do not call the backend's metadata helper as a permissive converter. It replaces non-JSON-serializable metadata with `{}`, which conflicts with D-03's no-default/no-loss rule. Preflight must instead prove every metadata dictionary round-trips losslessly through the chosen canonical JSON encoding, otherwise stop before upsert. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py] [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:27-29]

### Pattern 3: Derived target collection, never a copied literal

**What:** Derive the remote collection name by invoking or exactly testing the pinned v3.5.0 backend rule against the snapshot's palace ID, namespace, and collection name.

**When to use:** Before creating the isolated local target and again when handing the bundle to Phase 21.

The v3.5.0 prefix is built from `"mempalace"`, an optional slugged namespace, and the first 16 hexadecimal characters of SHA-256 over `PalaceRef.id`; the final name appends the slugged collection name. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]

### Pattern 4: Parity is a multi-oracle gate

**What:** Compare one canonical source record stream, the bundle stream, and a target retrieval stream, then compare deterministic search fixtures.

**When to use:** Before producing the Phase 21 handoff.

Pass only if all of the following hold:

1. Source IDs, `mempalace_id` payload values, and UUIDv5 point IDs form a one-to-one mapping.
2. Document bytes and canonical metadata representations match per source ID; source timestamp fields remain in metadata and target ingestion `updated_at` is excluded from source-field equality.
3. Vector strategy, model identity, dimension, source metric evidence, target Cosine configuration, serialization evidence, and vector comparator are recorded before the vector check executes.
4. Frozen query vectors and filters return the same ordered IDs and equivalent distances/ranking under a documented comparison rule. A count-only comparison is insufficient. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:36-42]

### Anti-Patterns to Avoid

- **Live-source export:** Reading the running palace without a write freeze can mix pre- and post-change records. Record the freeze time before snapshotting. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:12-18]
- **Hand-written collection name:** This may select a different Qdrant collection when the palace ID or namespace differs. Use the pinned source logic. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]
- **Permissive metadata sanitization:** Converting invalid metadata to an empty object hides semantic loss. Reject it. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]
- **Shared or pre-existing local target:** A reusable target can hide stale points and defeat count parity. Require an empty isolated collection and an explicit cleanup policy outside the source snapshot. [ASSUMED]
- **Beginning Phase 21 work early:** Do not deploy, restore, alter MCP registration, or retire the legacy service in this phase. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:64-66]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
| --- | --- | --- | --- |
| MemPalace point identity | Ad-hoc integer or random UUID mapping | The pinned v3.5.0 UUIDv5 derivation | Stable deterministic identity is required for bijection evidence. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py] |
| Qdrant payload contract | A new payload schema | The v3.5.0 `mempalace_id` / document / metadata payload mapping | The runtime backend reads this exact layout. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py] |
| Bundle integrity | Custom unchecked archive layout | Existing manifest + SHA-256 policy validator | It rejects unsafe paths, invalid lowercase digests, missing files, and missing attestations. [VERIFIED: scripts/validate-solidstats-memory-policy.py:91-138] |
| Search parity | A count-only smoke check | Frozen deterministic vector/filtered ranking fixtures | Query results contain ordered IDs, documents, metadata, distances, and optional embeddings. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/base.py] |

**Key insight:** The safe custom work is the thin orchestration and verifier around the upstream v3.5.0 contract; the mapping itself must remain source-derived and testable.

## Runtime State Inventory

| Category | Items Found | Action Required |
| --- | --- | --- |
| Stored data | The actual legacy Chroma palace, SQLite/Chroma contents, and identity sidecars were not available to this research session. The policy requires a Chroma source, Qdrant target, write freeze, embedding, checksum, and parity attestations. [VERIFIED: scripts/validate-solidstats-memory-policy.py:97-113] | Operator supplies one post-freeze snapshot. Inventory its records and sidecars before transformation; this is a data export, not a code-only edit. |
| Live service config | No VPS or live service access was assumed or used; the legacy write freeze has not been evidenced. [VERIFIED: phase task scope] | Operator must freeze writes, record the time, and snapshot the deployed backend/embedding configuration. |
| OS-registered state | No process-manager or host registrations were inspected; this phase cannot infer their absence from repository files. [VERIFIED: phase task scope] | No change in Phase 20. Phase 21 must inspect live service registration before restore/cutover. |
| Secrets / environment variables | Secret files and values were deliberately not read. The runtime uses secret-backed Qdrant and MCP tokens, but this phase must not copy them into the bundle. [VERIFIED: k8s/memory/20-mempalace.yaml:68-84] | Require non-secret configuration provenance only; exclude credentials from snapshot, logs, reports, and fixtures. |
| Build artifacts / installed packages | Local MemPalace is `3.4.1`, while the phase requires `v3.5.0`; Docker is installed but its daemon is inaccessible to this session. [VERIFIED: local command probes on 2026-08-20] | Supply a reviewed v3.5.0 local environment and authorized local container execution before the import/parity wave. |

## Common Pitfalls

### Pitfall 1: Using the installed 3.4.1 binary as the oracle

**What goes wrong:** Point IDs, field handling, or collection naming can drift from the phase-pinned contract.

**How to avoid:** Refuse execution until a locally inspectable v3.5.0 environment and its checksum are recorded; run mapping fixture tests through that environment. [VERIFIED: local command probes on 2026-08-20]

### Pitfall 2: Silent Chroma partial extraction

**What goes wrong:** A successful export can omit rows if an index or API path is stale or capped.

**How to avoid:** Paginate, compare extracted count to the authoritative source count, reject duplicate IDs, and retain a signed inventory report. The v3.5.0 release specifically notes a stale-Chroma HNSW fallback and a repair guard against a 10,000-row cap. [CITED: https://github.com/MemPalace/mempalace/releases/tag/v3.5.0] [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/cli.py]

### Pitfall 3: Assuming matching vector width proves reuse

**What goes wrong:** Different models or distance semantics can share a dimension but return materially different rankings.

**How to avoid:** Require D-07's complete model, metric, serialization, and target-Cosine evidence. If any element is unknown, re-embed locally and make the model decision auditable. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:36-40]

### Pitfall 4: Treating Qdrant `updated_at` as source metadata

**What goes wrong:** Import time overwrites or is compared to content time, producing false parity outcomes.

**How to avoid:** Preserve source timestamps inside metadata and explicitly exclude ingestion `updated_at` from source-field equality. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]

### Pitfall 5: Untrusted snapshot paths or hostile metadata

**What goes wrong:** A manifest path can escape the bundle root, or untrusted text can be interpreted as instructions or silently coerced.

**How to avoid:** Resolve every input below an explicit bundle root; reject absolute and parent-traversal paths; handle source text only as data; validate JSON types and sizes before invoking a subprocess. The existing validator already rejects absolute and parent paths. [VERIFIED: scripts/validate-solidstats-memory-policy.py:118-137]

## Code Examples

### Canonical mapping assertion

```python
# Source: MemPalace v3.5.0 qdrant.py
expected_point_id = str(uuid.uuid5(POINT_NAMESPACE, str(source_id)))
assert target_payload["mempalace_id"] == source_id
assert target_point_id == expected_point_id
```

The constants and payload key are from the pinned upstream implementation; production tooling must import or fixture-test the source revision instead of copying this fragment as an independent authority. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]

### Fail-closed metadata preflight

```python
canonical = json.dumps(metadata, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)
if json.loads(canonical) != metadata:
    raise ValueError("metadata is not losslessly JSON representable")
```

This guard is an implementation recommendation to protect D-03; its exact comparator must be fixture-tested against frozen source metadata. [ASSUMED]

## State of the Art

| Old approach | Current approach | When changed | Impact |
| --- | --- | --- | --- |
| Treat Chroma dictionary returns as the backend contract | Typed `GetResult` and `QueryResult` return IDs, documents, metadata, distances, and optional embeddings | MemPalace v3.5.0 backend contract | The migration verifier can assert a backend-independent record shape. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/base.py] |
| Ad-hoc Qdrant per-page metadata loading | Single-scroll Qdrant bulk metadata fetch | MemPalace v3.5.0 | Large-corpus inventory should use paginated/scroll-aware retrieval and record its completeness evidence. [CITED: https://github.com/MemPalace/mempalace/releases/tag/v3.5.0] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
| --- | --- | --- | --- |
| A1 | A local Qdrant target must be newly empty for a reliable parity run. | Anti-Patterns | Stale points could produce a false pass. |
| A2 | The proposed JSON canonicalization is adequate for all frozen source metadata. | Code Examples | Metadata comparison could reject valid values or conceal a representation mismatch. |

## Open Questions

1. **Can the operator supply a complete post-freeze snapshot and provenance sidecars?**
   - What we know: Phase policy demands a Chroma-to-Qdrant bundle with freeze, embedding, checksum, and parity attestations. [VERIFIED: scripts/validate-solidstats-memory-policy.py:97-113]
   - What's unclear: Actual snapshot layout, corpus count, bytes, palace ID, collection name, timestamp keys, model identity, source metric, and vector serialization.
   - Recommendation: Make the first execution plan an operator checkpoint plus read-only inventory; no transform task starts until the inventory report is complete.

2. **Which vector strategy passes D-07?**
   - What we know: Qdrant's source adapter creates a collection with `"distance": "Cosine"` and requires explicit embeddings for writes. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py]
   - What's unclear: Whether the frozen Chroma vectors share model, metric, and serialization semantics with the v3.5.0 Qdrant target.
   - Recommendation: Default to local re-embedding unless the inventory proves every D-07 condition; record the chosen branch in the manifest.

3. **How will the v3.5.0 environment and isolated Qdrant run locally?**
   - What we know: MemPalace 3.4.1 is installed, Docker/Compose are installed, and the Docker daemon is not accessible to this session. [VERIFIED: local command probes on 2026-08-20]
   - What's unclear: The approved v3.5.0 artifact, its checksum, and a Docker-capable local execution context.
   - Recommendation: Add explicit `checkpoint:human-verify` tasks for the pinned execution environment and local container access; do not work around either gate with VPS access.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
| --- | --- | --- | --- | --- |
| Python | inventory, transform, validator, tests | ✓ | 3.14.4 | — |
| MemPalace oracle | reviewed mapping and optional re-embedding | ✗ required version | 3.4.1 installed; v3.5.0 required | Supply a reviewed local v3.5.0 environment. |
| Docker daemon | disposable isolated Qdrant | ✗ | Docker 29.7.2 installed; socket access denied | Authorized local runner; never use the VPS as fallback. |
| Docker Compose | local target orchestration | ✓ binary only | v5.4.0 | Direct Docker invocation after daemon access is granted. |

**Missing dependencies with no fallback:** a v3.5.0 MemPalace execution environment and Docker-daemon access block a real transform/import/parity run.

## Validation Architecture

### Test Framework

| Property | Value |
| --- | --- |
| Framework | Python `unittest` (standard library) |
| Config file | none — direct test modules |
| Quick run command | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` |
| Full phase suite command | `timeout 30s python3 -m unittest tests/test-solidstats-memory-policy.py tests/test-solidstats-memory-migration.py` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
| --- | --- | --- | --- | --- |
| MIG-01 | Bundle rejects a source without a recorded write freeze and source checksum. | unit | `python3 -m unittest tests/test-solidstats-memory-policy.py` | ◐ extend existing |
| MIG-02 | Fixture corpus preserves ID/document/metadata/vector mapping and passes deterministic recall parity in isolated Qdrant. | integration | `python3 -m unittest tests/test-solidstats-memory-migration.py` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** Run policy and pure mapping fixture tests.
- **Per wave merge:** Run the full phase suite with an isolated Qdrant only after container access is available.
- **Phase gate:** Bundle validation and a recorded parity report must pass before planning Phase 21 execution.

### Wave 0 Gaps

- [ ] `tests/test-solidstats-memory-migration.py` — deterministic source/mapping/malformed-metadata/ID-bijection fixtures.
- [ ] Isolated-Qdrant fixture that starts only with an approved local container runtime and always verifies a new empty target.
- [ ] Fixture corpus with source sidecars for both vector-reuse and forced-re-embedding branches.
- [ ] Machine-readable inventory, transform, and parity report schemas checked by the existing policy validator.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
| --- | --- | --- |
| v5.0.0 Encoding and Sanitization / Injection Prevention | Yes | Treat frozen documents and metadata as untrusted data; never evaluate them as code or shell input; validate before subprocess calls. [CITED: https://owasp.org/www-project-application-security-verification-standard/] |
| v5.0.0 Authentication | No direct Phase 20 change | Phase 20 does not expose an HTTP service or rotate tokens; Phase 21 owns live transport validation. [VERIFIED: .planning/phases/20-local-corpus-migration/20-CONTEXT.md:64-66] |
| v5.0.0 Data Protection | Yes | Store non-secret checksums and manifests only; exclude tokens, credentials, raw secret files, and external URLs containing credentials. [VERIFIED: AGENTS.md] |
| v5.0.0 File and Resource Verification | Yes | Enforce bundle-root containment, safe relative paths, SHA-256 validation, bounded record processing, and no symlink escape. Path/digest checks already exist; symlink handling is a required extension. [VERIFIED: scripts/validate-solidstats-memory-policy.py:118-137] |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
| --- | --- | --- |
| Bundle path traversal | Tampering | Reject absolute and parent paths before opening files; add a resolved-path-under-root test. [VERIFIED: scripts/validate-solidstats-memory-policy.py:118-137] |
| Crafted metadata causes field loss | Tampering | JSON-losslessness preflight and per-record metadata hash; abort rather than coerce to an empty map. [CITED: https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py] |
| Untrusted text reaches shell or logs | Elevation of privilege / Information disclosure | Pass paths and data via structured APIs; redact values in diagnostics; do not interpolate document or metadata text into commands. [VERIFIED: AGENTS.md] |
| Local Qdrant reachable outside the test boundary | Information disclosure | Bind only to a disposable local endpoint and never add a public service; no VPS deployment occurs in this phase. [VERIFIED: .planning/REQUIREMENTS.md:28-30] |

## Plan Decomposition

1. **Wave 0 — Contract tests and schemas:** Extend the policy validator/tests for required freeze evidence, source inventory, transform manifest, safe file handling, ID bijection, and parity report references. Keep fixtures non-secret and synthetic.
2. **Wave 1 — Operator-gated inventory/export:** Confirm the legacy write freeze; collect the immutable snapshot plus sidecars; produce a read-only inventory and checksummed canonical source bundle. Stop on partial extraction, duplicate IDs, unavailable source configuration, or non-lossless metadata.
3. **Wave 2 — Source-reviewed local transform:** Supply v3.5.0 locally, derive the Qdrant collection through its backend code, select reuse/re-embedding from recorded evidence, and import only into a new isolated local Qdrant collection.
4. **Wave 3 — Parity gate and handoff:** Run field, UUIDv5, document, metadata, timestamp, vector, and deterministic recall/ranking comparisons; validate the bundle; record failures or a Phase 21-ready manifest. Do not restore, deploy, register an MCP client, or retire the legacy service.

## Sources

### Primary (official sources)

- [MemPalace v3.5.0 release](https://github.com/MemPalace/mempalace/releases/tag/v3.5.0) — release scope, local HTTP transport, Chroma reliability, Qdrant bulk-scroll work.
- [MemPalace v3.5.0 backend contract](https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/base.py) — typed get/query return shapes and embedder identity semantics.
- [MemPalace v3.5.0 Chroma backend](https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/chroma.py) — paginated reads of IDs/documents/metadata/embeddings.
- [MemPalace v3.5.0 Qdrant backend](https://raw.githubusercontent.com/MemPalace/mempalace/v3.5.0/mempalace/backends/qdrant.py) — UUIDv5 point IDs, payload layout, Cosine collection creation, and collection derivation.
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/) — current secure-development verification baseline.

### Repository evidence

- `.planning/phases/20-local-corpus-migration/20-CONTEXT.md` — locked phase decisions and scope boundary.
- `config/solidstats-memory/migration-policy.json` — existing migration invariants.
- `scripts/validate-solidstats-memory-policy.py` and `tests/test-solidstats-memory-policy.py` — existing fail-closed policy and test style.
- `k8s/memory/10-qdrant.yaml` and `k8s/memory/20-mempalace.yaml` — target runtime contract without live deployment.

## Metadata

**Confidence breakdown:**

- Standard stack: MEDIUM — exact upstream v3.5.0 source was inspected, but no local v3.5.0 execution artifact is available.
- Architecture: HIGH — locked phase decisions and repository policy establish a clear local-only, fail-closed boundary.
- Pitfalls: MEDIUM — direct source identifies metadata coercion and extraction hazards; frozen-corpus-specific hazards need the inventory.

**Research date:** 2026-08-20
**Valid until:** 2026-08-27 — the source tag is pinned, but environment evidence and the migration artifact are volatile.
