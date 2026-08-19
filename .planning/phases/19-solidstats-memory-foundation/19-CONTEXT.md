# Phase 19: SolidStats Memory Foundation - Context

**Gathered:** 2026-08-20
**Status:** Ready for planning
**Source:** Accepted decision pack; confirmed decisions are not reopened

## Boundary

Create an isolated, repository-owned deployment boundary for SolidStats memory:
a dedicated namespace, private Qdrant, public token-authenticated MemPalace MCP,
independent storage, backup/monitoring wiring, and a dedicated deploy workflow.
Real data migration and live cutover remain in later operator-gated phases. The
exact cross-backend transform and embedding strategy are evidence gates, not
locked implementation choices.

## Locked Decisions

- Client/service name is `solidstats_memory`; Kubernetes name is
  `solidstats-memory`.
- The implementation lives under `k8s/memory/`, never `k8s/staging/`.
- MemPalace is public only as HTTPS `/solidstats/mcp`; Qdrant is private.
- Credentials are distinct from personal and VocalClub memory.
- MemPalace uses Qdrant through `MEMPALACE_BACKEND=qdrant`,
  `MEMPALACE_QDRANT_URL`, `MEMPALACE_QDRANT_API_KEY`, and
  `MEMPALACE_QDRANT_NAMESPACE`.
- MemPalace and Qdrant never share a volume. MemPalace persists
  `/data/palace`; Qdrant owns a RWO PVC with Retain policy.
- The six locked values are active rooms. Their common wing is exactly
  `SolidStats`.
- Archive wings cover the five canonical platform repositories:
  `server-2-archive`, `replays-fetcher-archive`,
  `replay-parser-2-archive`, `web-archive`, and `infrastructure-archive`.
- ResourceQuota and LimitRange wait for measured local corpus size and live P95
  evidence.
- No live deploy, DNS, token rotation, old-palace mutation, or MCP registration
  change occurs in this phase's autonomous work.

## Security Contract

Both workloads use dedicated ServiceAccounts, `automountServiceAccountToken:
false`, non-root execution, seccomp RuntimeDefault, dropped capabilities,
read-only root filesystems, and explicit writable volumes. NetworkPolicy begins
with default deny and adds DNS, MemPalace-to-Qdrant, host-nginx-to-MCP, and
Prometheus scrape paths only. The host source CIDR must be measured under
kube-router before the edge allow rule is finalized.

## Deployment Contract

The deploy workflow has its own concurrency group and dedicated
namespace-scoped CI identity. Namespace/RBAC bootstrap is operator-applied and
excluded from CI globs. Secret values are rendered only from GitHub environment
secrets and never stored in git.

## Verified Runtime Facts

MemPalace v3.5.0 exposes Streamable HTTP MCP at `POST /mcp`, readiness at
`GET /healthz`, defaults to port 8765, and protects `/mcp` with
`MEMPALACE_MCP_HTTP_TOKEN`. Qdrant exposes REST 6333, gRPC 6334, readiness at
`GET /healthz`, API-key configuration through `QDRANT__SERVICE__API_KEY`, and
collection snapshots through `POST /collections/{collection}/snapshots`.

The infrastructure repository owns deployment wiring, not application image
builds. No verified published MemPalace image exists in the accepted evidence;
the manifest must therefore require an operator-supplied immutable local-build
image reference rather than inventing one.
