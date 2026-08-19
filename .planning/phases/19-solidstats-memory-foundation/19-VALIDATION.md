# Phase 19: Validation Strategy

## Offline Gates

| Gate | Evidence | Status |
| --- | --- | --- |
| Accepted policy invariants | `validate-solidstats-memory-policy.py` | Ready after patch application |
| Validator negative paths | Python unit tests | Ready after patch application |
| YAML parse and namespace ownership | memory manifest validator | Blocked on manifest authorization |
| No committed secret values | renderer fixtures plus secret scan | Blocked on renderer implementation |
| Workload hardening | static pod-spec assertions | Blocked on manifest authorization |
| Workflow separation | CI identity/context/glob assertions | Blocked on workflow authorization |
| Nginx path/auth/streaming | isolated-prefix `nginx -t` | Blocked on edge template authorization |

## Local Migration Gates

1. Record frozen-write timestamp and source snapshot checksum.
2. Inventory corpus bytes, record counts, room/wing counts, embedding dimensions,
   and duplicate identifiers without reading secrets.
3. Source-review the Chroma-to-Qdrant record mapping.
4. Record whether vectors are reused or re-embedded, exact model/version,
   dimension, corpus checksum, and parity evaluation; do not choose a strategy
   without evidence.
5. Produce a bundle and validate every checksum and evidence attestation.
6. Import into an isolated local Qdrant collection.
7. Compare counts, IDs, metadata, vector evidence, and deterministic recall
   fixtures before any VPS upload.

## Live Operator Gates

1. Probe kube-router host-source semantics and storage capacity.
2. Bootstrap namespace/RBAC and render secrets from approved external stores.
3. Deploy Qdrant, then MemPalace; old and new long-running VPS stacks must not
   overlap.
4. Restore a snapshot into an isolated collection before cutover.
5. Verify token rejection/acceptance, MCP schema, scoped recall, semantic-miss
   drawer fallback, archive labeling, capture shape, read-after-write, restart,
   and reboot recovery.
6. Register only `solidstats_memory`; remove the legacy alias after validation.

## Completion Rule

Repository-local validation cannot mark the milestone complete. Completion
requires signed live evidence for backup/restore, auth, migration parity,
NetworkPolicy, public TLS, restart, and reboot checks.
