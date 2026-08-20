<!-- markdownlint-disable MD001 MD033 -->

# Phase 21: Restore, Cutover & Recovery - Context

**Gathered:** 2026-08-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove a provenance-bound restore into an isolated target, then perform a
reversible operator-gated cutover to the public `/solidstats/mcp` endpoint and
the `solidstats_memory` client. Capture auth rejection, MCP schema, scoped
recall and capture, snapshot backup, restart, reboot, and rollback evidence.
Archive distillation remains Phase 22 work.

</domain>

<decisions>
## Implementation Decisions

### Restore and Provenance

- Recompute every Phase 20 handoff, source, mapping, bundle, and parity digest
  before reading retained private artifacts or creating a restore target.
- Restore into an isolated collection and namespace first. No restore command
  may target a live or existing collection.
- Preserve the approved reused-vector and strict cross-engine ANN equivalence
  contracts; exact field, identifier, metadata, timestamp, and vector parity
  remain zero-tolerance gates.

### Cutover and Recovery

- Keep Qdrant private. Only token-authenticated MemPalace HTTPS is public at
  `/solidstats/mcp`.
- Treat cutover as an operator-owned, reversible state change. Preflight,
  backup, restore proof, negative-auth checks, smoke probes, and a tested
  rollback command must pass before the switch.
- Prove both process restart and VPS reboot recovery before accepting cutover.
  Recovery evidence must cover the public MCP endpoint and the private Qdrant
  collection.
- Register only the `solidstats_memory` client after the live service passes;
  remove or disable the legacy SolidStats client only after rollback evidence
  is sealed.

### Agent's Discretion

- The agent may choose the exact script boundaries, evidence schemas, probe
  ordering, and Kubernetes resource layout while preserving the requirements
  and operator gates above.
- The project knowledge graph is stale and could not be rebuilt because the
  `graphify` CLI is unavailable. Planning must treat current repository files,
  Phase 20 artifacts, and live probes as primary evidence.

</decisions>

<code_context>

## Existing Code Insights

### Reusable Assets

- `k8s/memory/` already defines the namespace, Qdrant, MemPalace, backup,
  monitoring, RBAC, and network boundaries.
- `.github/workflows/deploy-memory.yml` already renders secrets, validates the
  boundary, applies manifests, and waits for rollout health.
- `scripts/validate-memory-manifests.py` and
  `tests/test-memory-runtime-contract.py` provide the offline contract gate.
- `config/nginx/sites-available/solidstats-memory-mcp.conf.template` provides
  the public reverse-proxy shape.
- Phase 20 provides a passing parity report and a digest-bound Phase 21
  handoff; the disposable local Qdrant target was intentionally removed.

### Established Patterns

- Runtime configuration is declarative, digest-pinned, namespace-scoped, and
  fail-closed on unresolved operator evidence.
- Live operations require preflight checks, immutable backups, explicit
  rollback, and privacy-safe committed evidence.
- Secrets stay in GitHub environment secrets and Kubernetes Secrets; no secret
  or private corpus value enters repository artifacts or logs.

### Integration Points

- Phase 20 retained private snapshot, source, and bundle artifacts feed the
  isolated restore after provenance revalidation.
- The memory deploy workflow and Kubernetes manifests own workload rollout.
- Host nginx owns the public `/solidstats/mcp` route.
- The machine-local Codex MCP registration owns the final client cutover.
- Phase 22 consumes the verified live service after Phase 21 passes.

</code_context>

<specifics>
## Specific Ideas

Use the Phase 20 handoff as a fail-closed input contract, not as a pointer to a
surviving local runtime. Commit only aggregate, value-free evidence. Batch
remote operations and verify dependent recovery through one complete backup,
restart, and reboot cycle before declaring success.

</specifics>

<deferred>
## Deferred Ideas

Archive shard extraction, candidate deduplication, and curator-owned promotion
remain Phase 22 work.

</deferred>

<!-- markdownlint-enable MD001 MD033 -->
