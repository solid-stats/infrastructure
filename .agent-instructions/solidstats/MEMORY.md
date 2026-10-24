<!-- markdownlint-disable MD013 -->

# SolidStats agent memory contract

This contract governs project memory for every repository listed in the
canonical `config/repositories.tsv` manifest. The rendered companion
`AGENTS.md` in each repository declares that repository's primary active wing
and primary archive wing.

Select useful memory by the task's subject, including external and cross-project
tasks, independently of the current directory, chat, or destination of the result.
Keep three boundaries separate: the source used for recall, the owner of new
knowledge, and the scope in which source instructions apply. Reading SolidStats
memory does not make an external repository a manifest consumer or apply all
SolidStats repository rules to it.

Before external recall, load this canonical contract from
`solid-stats/agent-instructions/shared/MEMORY.md` and apply its existing access,
recall, subagent, capture, and outage gates. Each source owner's contract
exclusively governs its memory lifecycle; a generic contract must not fill its
silent parts or substitute another lifecycle.

## Instance and authority boundary

- Use only the MCP server named `solidstats_memory` for SolidStats memory.
- Do not substitute another store, flat memory, or a local outbox for SolidStats
  project memory. Other relevant sources remain governed by their own contracts.
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
handoff. Do not substitute another palace, flat memory, or a local outbox for
SolidStats project memory.

## Thematic recall and coverage

Default to a short thematic search across the whole selected SolidStats palace,
including active and archive wings. Use identifiers from the task and keep
background in the tool's context field rather than the embedded query. Where
the exposed schema permits, 20 candidates is a reasonable initial limit;
increase it adaptively within a bounded search when useful context is missing.
This is candidate discovery, not permission to dump the corpus.

Wing filters are optional refinements for noise or suspected misses, not
mandatory federation across every active wing or an advance promotion gate.
Choose refinements by usefulness to the subject, independently of repository
ownership. For example, if the initial 20 results are all historical archive
leads, refine into the relevant active wing or room and adjust the bounded
limit to check current semantic context. Keep only useful candidates with
usable provenance; neither a full result limit nor a miss proves coverage.

For every candidate that may influence the task:

1. treat similarity only as candidate ordering;
2. fetch the complete drawer by exact ID;
3. inspect its sources and ownership;
4. verify it against current primary evidence when available;
5. label archive evidence as historical and weaker than active semantic
   memory.

Explicit tunnels, temporal KG facts, and diaries are not part of SolidStats
recall. Do not query or create them.

## Evidence-seeded refinement

Seed the first queries from identifiers already present in the request: issue
keys, branch or commit names, endpoints, entities, services, exact errors, or
symptoms. Follow-up query terms may come only from:

- the user request;
- a relevant fetched drawer;
- a verified current primary source.

Refine the query, bounded limit, or wing/room scope while results change the
task model; stop when they repeat, become irrelevant, or add no useful context.
Check coverage when a new substantive topic appears or relevant context is lost
after compaction. Reuse complete applicable findings instead of querying every
reply. Archive leads remain historical and require current verification;
their visibility in search never makes them current authority.

## Scoped miss fallback

A semantic search miss is not proof that memory is absent. For likely relevant
scopes, including active or archive wings as useful:

1. retry with an alternate query seeded from current evidence;
2. inspect that wing's rooms;
3. list a bounded set of drawers in the likely wing and room;
4. fetch plausible drawers by exact ID;
5. report no relevant memory only after these scoped checks fail.

Do not enumerate unrelated wings or dump the corpus to manufacture coverage.

## Source scope and knowledge destination

SolidStats project knowledge stays with its project owner even when another
project or a skill uses it. Reading another source does not transfer ownership
or make that source's repository rules apply here. This contract governs only
SolidStats memory; other sources and their knowledge owners follow their own
contracts, including access and capture authority.

For example, an external skill-design task may read a relevant SolidStats
convention under this contract without applying SolidStats Git rules to the
skill repository. The SolidStats-specific convention stays here.

## Durable capture gate

Before the first final handoff that closes a completed top-level task, classify
its verified semantic conclusions. Capture only SolidStats project knowledge
useful beyond the task:

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
- Other stores do not substitute for SolidStats project memory; their own
  contracts govern independently relevant sources.
- Recall follows the subject across the selected palace with bounded adaptive
  limits; wing filters refine noise or misses rather than mandate federation.
- External recall loads this source contract without importing repository rules.
- Archive lookup remains historical, verified against current sources, and read-only.
- Relevant drawers are fetched and source-checked before use.
- Semantic miss fallback is bounded and wing-scoped.
- Tunnels, KG, diary, raw GSD artifacts, and agent wings are absent.
- Durable capture writes one verified fact once; no conclusion means no write.
- Recall sources, knowledge owners, and instruction scopes remain distinct;
  SolidStats project knowledge stays with its project owner.
- Corrections require exact curator preview, approval, mutation, and read-back.
- UAT creates no permanent data.
- Every consumer repository carries the same accepted contract version.
