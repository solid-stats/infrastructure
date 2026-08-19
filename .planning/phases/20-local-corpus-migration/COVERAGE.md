# API Coverage — MemPalace v3.5.0 and Local Qdrant

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

<!-- markdownlint-disable MD013 -->

| capability | decision | reason |
| --- | --- | --- |
| MemPalace v3.5.0 source version and provenance inspection | INTEGRATE | |
| MemPalace v3.5.0 palace identity and namespace lookup | INTEGRATE | |
| MemPalace v3.5.0 collection-name derivation | INTEGRATE | |
| MemPalace v3.5.0 deterministic UUIDv5 point-ID mapping | INTEGRATE | |
| MemPalace v3.5.0 payload and timestamp mapping | INTEGRATE | |
| MemPalace v3.5.0 embedder identity and configuration inspection | INTEGRATE | |
| MemPalace v3.5.0 local embedding invocation | INTEGRATE | |
| MemPalace v3.5.0 source vector-query and metadata-filter behavior | INTEGRATE | |
| Qdrant REST readiness and server provenance | INTEGRATE | |
| Qdrant REST collection existence and configuration inspection | INTEGRATE | |
| Qdrant REST collection creation with derived name, dimension, and Cosine metric | INTEGRATE | |
| Qdrant REST bounded point upsert with acknowledgement | INTEGRATE | |
| Qdrant REST exact point count | INTEGRATE | |
| Qdrant REST bounded point scroll and retrieval with payload and vectors | INTEGRATE | |
| Qdrant REST vector query with representative metadata filters | INTEGRATE | |
| Qdrant REST disposable local collection cleanup | INTEGRATE | Cleanup is pass-gated and run-bound; failure preserves diagnostic state. The immutable source, digest-locked bundle, and sanitized reports are retained. |
| Qdrant collection snapshot creation and restore | OPT-OUT | Explicitly owned by Phase 21 live restore and recovery. |
| Qdrant collection aliases or live-name switching | OPT-OUT | Explicitly owned by Phase 21 client cutover. |
| Qdrant cluster peers, replication, and distributed consistency | OPT-OUT | Phase 20 uses one disposable isolated local node; runtime topology belongs to Phase 21. |
| Qdrant public authentication and TLS exposure | OPT-OUT | Phase 20 binds a disposable target to loopback only; Phase 21 owns runtime network and secret wiring. |
| Qdrant in-place point mutation or deletion | OPT-OUT | The migration contract is immutable one-pass import into a proven-empty target. |
| MemPalace MCP registration and client configuration | OPT-OUT | Explicitly owned by Phase 21 registration and client cutover. |
| MemPalace live restore and legacy backend retirement | OPT-OUT | Explicitly owned by Phase 21 live cutover and recovery. |
| MemPalace archive distillation | OPT-OUT | Explicitly owned by Phase 22. |

<!-- markdownlint-enable MD013 -->
