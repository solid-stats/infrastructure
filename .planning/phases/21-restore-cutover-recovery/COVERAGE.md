# API Coverage — Qdrant Restore and MemPalace MCP Cutover

> Full coverage by default. Every opt-out is an explicit phase-boundary or
> safety decision.

<!-- markdownlint-disable MD013 -->

| capability | decision | reason |
| --- | --- | --- |
| Qdrant REST readiness and pinned-image provenance | INTEGRATE | |
| Qdrant REST collection and alias inventory before every restore mutation | INTEGRATE | |
| Qdrant REST target-specific absence lookup | INTEGRATE | |
| Qdrant REST collection snapshot creation | INTEGRATE | |
| Qdrant REST snapshot listing and freshness | INTEGRATE | |
| Qdrant REST snapshot download and checksum verification | INTEGRATE | |
| Qdrant REST snapshot upload or URL-bound recovery into an absent physical collection | INTEGRATE | |
| Qdrant REST recovery with snapshot-priority semantics | INTEGRATE | |
| Qdrant REST restored collection health, vector configuration, and aggregate point-count verification | INTEGRATE | |
| Qdrant REST alias pre-state capture | INTEGRATE | |
| Qdrant REST atomic alias create or switch with immediate read-back | INTEGRATE | |
| Qdrant REST compare-before-switch concurrency refusal | INTEGRATE | |
| Qdrant REST alias rollback to the exact recorded pre-state | INTEGRATE | |
| Qdrant REST persistence after ordered process restarts and one VPS reboot | INTEGRATE | |
| Qdrant REST direct public reachability on ports 6333 and 6334 | OPT-OUT | The required behavior is negative: both ports remain private and must fail public reachability probes. |
| Qdrant REST recovery over an existing collection or alias | OPT-OUT | Active-target overwrite is prohibited; equality or collision stops before recovery. |
| Qdrant REST collection deletion or in-place point deletion | OPT-OUT | Candidate and prior collections are retained for diagnosis and rollback; cleanup requires a later exact-ID decision. |
| Qdrant cluster peers, replication, and distributed consistency | OPT-OUT | The accepted runtime is a single unprivileged Qdrant StatefulSet; Phase 21 verifies that topology rather than introducing a distributed one. |
| Direct Qdrant point mutation for cutover verification | OPT-OUT | Capture and read-after-write are exercised through the public MemPalace MCP contract, not by bypassing it. |
| MemPalace unauthenticated health check inside the private boundary | INTEGRATE | |
| MemPalace public HTTPS route exactly at `/solidstats/mcp` | INTEGRATE | |
| MemPalace missing-token rejection | INTEGRATE | |
| MemPalace invalid-token rejection | INTEGRATE | |
| MemPalace valid bearer-token acceptance without token echo | INTEGRATE | |
| MCP Streamable HTTP initialize and session propagation | INTEGRATE | |
| MCP tools/list schema capture by digest | INTEGRATE | |
| MCP scoped active recall | INTEGRATE | |
| MCP semantic-miss fallback through drawer listing and bounded fetch | INTEGRATE | |
| MCP archive result labeling as untrusted historical evidence | INTEGRATE | |
| MCP deduplication, synthetic capture, shape verification, read-after-write, and exact cleanup when supported | INTEGRATE | |
| MCP disabled tunnel, KG, diary, plan-recall, and automatic-capture behavior | INTEGRATE | Verified as negative policy/runtime capabilities so the cutover cannot silently re-enable them. |
| Machine-local `solidstats_memory` client add/get/live-call/remove rollback | INTEGRATE | |
| Legacy `mempalace` client removal before rollback evidence is sealed | OPT-OUT | Early removal is forbidden; the exact legacy registration is removed or disabled only after rollback and forward recovery pass. |
| Archive shard extraction, candidate promotion, or archive mutation | OPT-OUT | These capabilities belong to Phase 22 and are excluded from the Phase 21 runtime cutover. |

<!-- markdownlint-enable MD013 -->
