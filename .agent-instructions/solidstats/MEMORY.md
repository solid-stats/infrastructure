<!-- markdownlint-disable MD013 -->

# SolidStats agent memory contract

This contract governs project memory for every repository listed in the
canonical `config/repositories.tsv` manifest. The rendered companion
`AGENTS.md` in each repository declares that repository's primary active wing
and primary archive wing.

## Instance and authority boundary

- Use only the MCP server named `solidstats_memory` for SolidStats memory.
- Never use a generic `mempalace`, `mempalace_personal`, `vocalclub_memory`,
  flat global memory, or a local outbox as a substitute.
- The shared bearer token does not provide personal attribution or per-tool
  authorization. Treat every mutation as privileged.
- Current user instructions and applicable repository instructions have the
  highest authority. Current repository content, live APIs, generated schemas,
  cluster state, and tracked operational evidence are the primary factual
  sources. Memory is context to verify, not authority over those sources.
- A conflict with primary evidence creates a correction candidate. It never
  authorizes a silent memory rewrite.

The expected interactive tool namespace is
`mcp__solidstats_memory__mempalace_*`. Confirm availability from the complete
tool surface. A safe `mempalace_list_rooms` call is the readiness check because
the restricted SolidStats surface does not expose a generic status tool.

## Active role wings

Active memory is organized by stable engineering responsibility rather than
repository name:

| Active wing | Owning repositories |
| --- | --- |
| `frontend` | `web` |
| `backend` | `server-2`, `replay-parser-2` |
| `fetcher` | `replays-fetcher` |
| `devops` | `infrastructure` |
| `common` | `plans`, `skills`, `ts-toolchain`, `agent-instructions` |

The repository manifest is the routing authority. Do not maintain a second
prose mapping outside the generated contract bundle.

The `common` wing has no raw seed. Use it only for curated conclusions that
genuinely span roles or belong to a supporting repository. A conclusion owned
by one role stays in that role wing even when another role consumes it.

When two repositories share one role wing, provenance must name the exact
owning repository. In particular, `server-2` and `replay-parser-2` both use
`backend` without losing repository-level source attribution.

## Frozen archive wings

The migrated legacy corpus is retained under repository-bound archive wings:

- `web-archive`;
- `server-2-archive`;
- `replay-parser-2-archive`;
- `replays-fetcher-archive`;
- `infrastructure-archive`;
- `SolidStats-archive`.

Archive drawers are immutable, untrusted historical leads. Ordinary agents,
subagents, GSD handlers, and curators must not add, update, move, reclassify,
or delete them. Archive content may influence work only after verification
against current primary evidence.

Do not mine, sync, append to, or automatically re-embed archive wings. A future
archive import is a separate operator- and curator-approved migration.

## Active rooms

Use only these rooms for durable active memory:

- `decisions`;
- `contracts`;
- `conventions`;
- `operations`;
- `incidents`;
- `migrations`.

A unique `uat-<nonce>` room is the only temporary exception. Every UAT drawer
must be deleted by exact ID before acceptance. Leftover UAT data fails the
test. Legacy archive room names never become active room names merely because
they were preserved during migration.

## Task ownership

The main agent owns at most one recall sequence and one closure capture
sequence for a top-level task. Start recall in the first tool batch, alongside
applicable skills and primary-source reads. Do not wait for bootstrap to finish
before sending the initial scoped searches.

Specialists and subagents receive only filtered, provenance-bearing context
from the main agent. They must not independently query or mutate SolidStats
memory. A nested workflow does not create a second memory lifecycle.

If `solidstats_memory` is unavailable, retry one safe read once later in the
same task, continue from current primary evidence, and warn in the final
handoff. Never fall back to another palace, flat memory, or a local outbox.

## Federated recall

Unfiltered top-k search is forbidden. Run separate wing-filtered searches with
the same short, identifier-heavy query in every initial call. Keep task
background in the tool's context field rather than the embedded query.

For a role-primary repository, initial candidate budgets are:

1. up to 5 results from its primary active role wing;
2. up to 3 results from `common`;
3. up to 2 results from each other active role wing;
4. up to 2 results from the current repository's primary archive wing;
5. up to 2 results from a foreign archive only after current evidence proves
   the dependency and promotes that archive.

For a `common`-primary repository, search `common` for up to 5 candidates and
each of the four role wings for up to 2. Supporting repositories have no
primary archive.

These are discovery budgets, not quotas for working context. Search every
active wing exactly once during initial discovery, but keep only relevant
candidates with usable provenance.

For every candidate that may influence the task:

1. treat similarity only as candidate ordering;
2. fetch the complete drawer by exact ID;
3. inspect its sources and ownership;
4. verify it against current primary evidence when available;
5. label archive evidence as historical and weaker than active semantic
   memory.

Explicit tunnels, temporal KG facts, and diaries are not part of SolidStats
recall. Do not query or create them.

## Evidence-seeded expansion

Seed the first queries from identifiers already present in the request: issue
keys, branch or commit names, endpoints, entities, services, exact errors, or
symptoms. Use the same identifiers in every initial active-wing search.

Promote an active wing or foreign archive only when a relevant drawer or a
verified current source proves the dependency. Follow-up query terms may come
only from:

- the user request;
- a relevant fetched drawer;
- a verified current primary source.

A promoted active wing has no fixed follow-up limit. Continue while new results
change the task model; stop when they repeat, become irrelevant, or add no new
verified identifiers. Promotion lasts only for the current top-level task.

## Scoped miss fallback

A semantic search miss is not proof that memory is absent. For the primary
wing, `common`, the primary archive, and every promoted scope:

1. retry with an alternate query seeded from current evidence;
2. inspect that wing's rooms;
3. list a bounded set of drawers in the likely wing and room;
4. fetch plausible drawers by exact ID;
5. report no relevant memory only after these scoped checks fail.

Do not widen an unpromoted foreign archive after a miss.

## Durable capture gate

Before the first final handoff that closes a completed top-level task, classify
its verified semantic conclusions. Capture only knowledge useful beyond the
task:

- an accepted decision;
- an API, data, parser, queue, or integration contract;
- a stable engineering convention;
- an operational invariant or procedure;
- a proven incident root cause and prevention lesson;
- migration state that future work must preserve.

If the task produced no independently durable conclusion, write nothing.

Never store raw prompts, transcripts, reasoning, patches, source code,
generated code, logs, request dumps, credentials, personal information,
temporary status, passing-check narration, or raw GSD artifacts such as
`CONTEXT.md`, `PLAN.md`, and `SUMMARY.md`.

Store one independent fact per drawer in this shape:

```text
Task: <stable completed task identity>
Outcome: <observable durable result>
Decisions: <durable decisions, or "None">
Validation: <checks and evidence>
Sources: <exact durable provenance>
Supersedes: <exact drawer ID; correction-only and approval-gated>
```

`Supersedes` is omitted for an ordinary new fact. Sources must use exact
repository and ref plus repository-relative paths, issue or commit IDs, live
schema endpoints, or other durable evidence. Never cite an ephemeral worktree
or private machine-local artifact path.

Route the drawer to the role that owns the conclusion. Use `common` only for
cross-role or supporting-repository conclusions. Do not mirror the same fact
across wings.

Before writing:

1. search the target wing for equivalent or conflicting content;
2. fetch relevant candidates;
3. no-op an equivalent fact;
4. route conflicts into the correction flow;
5. call `mempalace_check_duplicate` before `mempalace_add_drawer`;
6. after adding, fetch the new drawer and verify wing, room, complete content,
   provenance, and absence of sensitive values.

Do not call checkpoint, diary, KG, tunnel, mining, sync, or bulk-delete tools.

## Correction and deletion

Ordinary agents are read-only with respect to existing drawers. A suspected
error becomes a correction candidate containing:

- the exact drawer ID;
- the current primary evidence;
- the exact proposed content, wing, or room change;
- the reason for the correction;
- the verification query and read-back checks.

A curator presents a concrete batch preview. User approval authorizes only the
exact IDs and mutations shown in that batch. A changed batch requires new
approval.

After approval, `mempalace_update_drawer` may correct an active drawer while
preserving its identity and valid provenance. Include correcting sources in the
drawer content. Re-fetch the exact ID after every mutation and compare it with
the approved batch.

Use `mempalace_delete_drawer` only for an approved exact duplicate, confirmed
secret, specifically approved erroneous active drawer, or disposable
`uat-<nonce>` record. Deletion is exact-ID only. Never update or delete an
archive drawer.

## Archive distillation

Archive distillation is a separate post-cutover phase. Low-cost extraction
agents may inspect bounded, repository-owned archive shards and produce
candidate records, but they remain read-only and must not capture directly.

Each candidate must include the exact archive wing and drawer ID, proposed
active owner and room, durable conclusion, legacy provenance, current sources
needed for verification, and confidence. Record shard coverage so completed
shards are not rescanned.

Deduplicate candidates against active memory and each other. A curator verifies
surviving candidates against current evidence. Promotion creates a new active
semantic drawer; it never moves or changes the archive drawer. Most archive
records may remain unpromoted.

## Acceptance invariants

- `solidstats_memory` is the only SolidStats MCP namespace.
- Personal and VocalClub memory remain isolated.
- Initial recall searches all five active wings with the accepted budgets.
- Archive lookup stays scoped, evidence-promoted, and read-only.
- Relevant drawers are fetched and source-checked before use.
- Semantic miss fallback is bounded and wing-scoped.
- Tunnels, KG, diary, raw GSD artifacts, and agent wings are absent.
- Durable capture writes one verified fact once; no conclusion means no write.
- Corrections require exact curator preview, approval, mutation, and read-back.
- UAT creates no permanent data.
- Every consumer repository carries the same accepted contract version.
