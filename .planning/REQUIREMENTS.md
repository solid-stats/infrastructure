# Requirements: SolidStats Memory Isolation

**Milestone:** v4.0
**Status:** Planned
**Source:** Accepted SolidStats MemPalace migration decision pack

## Isolation

- [ ] **ISO-01**: The MCP client is named `solidstats_memory`; no legacy
  `mempalace` alias remains after cutover.
- [ ] **ISO-02**: Kubernetes resources live in `solidstats-memory`, outside
  `k8s/staging/`, with credentials distinct from personal and VocalClub memory.
- [ ] **ISO-03**: Qdrant remains private; only MemPalace is exposed at public HTTPS
  `/solidstats/mcp` through host nginx.
- [ ] **ISO-04**: Default-deny policies permit only DNS, MemPalace to Qdrant,
  host-nginx to MCP, and Prometheus scrape paths proven under kube-router.

## Runtime

- [ ] **RUN-01**: MemPalace runs from an operator-supplied, immutable local build
  using HTTP transport, `POST /mcp`, and unauthenticated `GET /healthz`.
- [ ] **RUN-02**: Qdrant runs as a single unprivileged StatefulSet with REST 6333,
  gRPC 6334, `GET /healthz`, a RWO PVC, and Retain ownership policy.
- [ ] **RUN-03**: MemPalace and Qdrant use separate ServiceAccounts, disabled token
  automount, non-root security contexts, dropped capabilities, read-only root
  filesystems, explicit writable volumes, requests, and limits.
- [ ] **RUN-04**: MemPalace persists `/data/palace` on its own PVC and never shares
  a volume with Qdrant.
- [ ] **RUN-05**: ResourceQuota and LimitRange remain blocked until local corpus
  measurement and VPS P95/allocatable evidence exist.

## Migration

- [ ] **MIG-01**: Legacy SolidStats writes are frozen before export; old reads may
  continue until cutover.
- [ ] **MIG-02**: Export, build, transform, and verification run locally; the VPS
  never runs old and new long-running stacks together. The exact transform stays
  blocked until its source mapping is reviewed.
- [ ] **MIG-03**: Active rooms are exactly decisions, contracts, conventions,
  operations, incidents, and migrations; `SolidStats` is the common wing.
- [ ] **MIG-04**: Raw history for every canonical platform repository lands only
  in `server-2-archive`, `replays-fetcher-archive`,
  `replay-parser-2-archive`, `web-archive`, and `infrastructure-archive`, marked
  untrusted historical evidence. Supporting repositories are excluded unless
  the accepted source registry promotes them.
- [ ] **MIG-05**: Semantic tunnels, KG mirroring, diary journaling, plan recall,
  auto-capture hooks, blind agent wings, and automatic archive mining are disabled.
- [ ] **MIG-06**: No legacy KG or tunnel data is imported; later deletion requires
  exact-ID operator approval.
- [ ] **MIG-07**: Every offline bundle carries checksums plus evidence recording
  whether vectors were reused or re-embedded, the exact model/version,
  dimension, corpus checksum, and parity evaluation. No strategy is selected
  without evidence.

## Operations

- [ ] **OPS-01**: A dedicated deploy workflow and namespace-scoped CI identity are
  independent of runtime and observability deploys.
- [ ] **OPS-02**: Backups use Qdrant's collection snapshot API plus a MemPalace
  metadata archive, manifest, and checksums under
  `backups/solidstats-memory/`.
- [ ] **OPS-03**: Restore is proven in isolation before cutover and never targets
  the active collection.
- [ ] **OPS-04**: Static Prometheus scraping covers MCP readiness/latency/errors,
  Qdrant health/collection state, snapshot freshness, and PVC capacity.
- [ ] **OPS-05**: Cutover proves auth rejection, MCP schema, scoped recall,
  semantic-miss fallback, archive labeling, capture shape, read-after-write,
  restart recovery, and reboot recovery.

## Curation

- [ ] **CUR-01**: Archive distillation runs only after cutover and never blocks
  the runtime migration.
- [ ] **CUR-02**: Low-cost extraction agents receive bounded read-only shards and
  cannot write to active memory or mutate archive drawers.
- [ ] **CUR-03**: Every candidate records its exact archive wing/drawer ID,
  proposed active owner/room, durable conclusion, provenance, current
  verification sources, and confidence.
- [ ] **CUR-04**: Candidates are deduplicated and verified against current
  primary evidence before curator-owned promotion creates a new active drawer.
- [ ] **CUR-05**: Shard coverage, rejection reasons, and promotions are recorded
  so completed shards are not scanned again.

## Traceability

| Requirement | Phase | Status |
| --- | --- | --- |
| ISO-01..04, RUN-01..05, MIG-03..07, OPS-01, OPS-04 | 19 | Planned |
| MIG-01..02 | 20 | Planned |
| OPS-02..03, OPS-05 | 21 | Planned |
| CUR-01..05 | 22 | Planned |
