# Phase 19: SolidStats Memory Foundation - Research

**Researched:** 2026-08-20
**Confidence:** High for documented runtime surfaces; blocked where live evidence
or an upstream migration tool is absent

## Primary Contracts

- MemPalace release v3.5.0 is the verified application contract. Its CLI accepts
  `--transport http`, `--host`, and `--port`; the HTTP surface is `POST /mcp`
  with `GET /healthz` readiness.
- Qdrant v1.19.0 has an official unprivileged GHCR artifact. The verified digest
  is `sha256:18a245d16eb663d4f6ad054123371243248d8256a8067f352cd6e88d512fee0b`.
- Qdrant REST and gRPC ports are 6333 and 6334. Collection snapshots use
  `POST /collections/{collection_name}/snapshots` and local snapshots are stored
  under `/qdrant/snapshots` in the official container layout.
- Qdrant API authentication uses `QDRANT__SERVICE__API_KEY`; an empty read-only
  key must never be configured.

## Architecture

Use one Qdrant StatefulSet and one MemPalace Deployment. Qdrant has no public
Service. MemPalace receives only Qdrant URL/key/namespace and its own MCP token.
The public path terminates at host nginx and proxies to the MemPalace ClusterIP.
A dedicated memory deployment workflow mirrors the repository's proven
render-then-apply and operator-bootstrap split without widening staging or
observability credentials.

## Migration Gap

Upstream documentation verifies pluggable Chroma and Qdrant backends but does
not document a native Chroma-to-Qdrant export/import command. Chroma's documented
migration tooling concerns Chroma schema/version migrations, not cross-backend
MemPalace transfer. Therefore this repository may validate an offline bundle and
its checksums, but must not fabricate a transform or claim semantic equivalence.
Before Phase 20 execution, source-review the exact transform and embedding
strategy. Record whether vectors are reused or re-embedded, the exact
model/version, dimension, corpus checksum, and parity evaluation. Obtain one of:

1. an upstream-supported export/import command with versioned schema; or
2. a source-reviewed record mapping that preserves identifiers, text, metadata,
   room/wing ownership, and timestamps, with an evidence-backed vector strategy.

## Live-Evidence Blockers

- Immutable MemPalace image reference from the local build pipeline.
- Host source address observed by kube-router for nginx-to-MCP traffic.
- Existing StorageClass semantics and available node/PVC capacity.
- Local corpus bytes, record count, vector dimensions, and expected Qdrant
  collection count.
- MemPalace metrics endpoint and exact metric names; do not invent them.
- Snapshot upload tool image and credentials already approved for the repository.
- Qdrant namespace-to-collection naming produced by MemPalace v3.5.0.

## Sources

- MemPalace repository and v3.5.0 release documentation.
- MemPalace server, configuration, backend, and Docker source at tag v3.5.0.
- Qdrant official documentation for interfaces, health, authentication,
  snapshots, and container deployment.
- Qdrant official GHCR package metadata for v1.19.0-unprivileged.
