# CAPTURE — turn one divergence into a journal entry

Run this per discovery, the moment a `solidstats-*` skill is shown wrong/incomplete/harmful — or when
`capture-session-lessons` (or a proactive offer from the active skill, SKILL.md §E) routes a lesson
here. Goal: classify it, bind the offending code, normalize, append to the journal in **this skills
repo**, emit a regression case when code is bound, and stage it for commit. It never edits a target
skill — that is PROMOTE's job.

## Required reading
- `references/signal-taxonomy.md` — the five signals and the fact/preference class rules
- `references/journal-schema.md` — the entry schema and signature
- `templates/correction-entry.md` — the block to append

## Steps

0. **Resolve the canonical skills checkout** (SKILL.md §H). The journal must land in the real
   `solid-stats/skills` repo, NOT the vendored `.agents/skills/**` copy you may be running from in a
   consuming repo (it is overwritten on the next sync). Resolve: cwd/ancestor whose remote is
   `solid-stats/skills` → else a local clone (`../skills` or under `~/Projects/**`, remote confirmed)
   → else stop and ask. All journal paths below are relative to that checkout.

1. **Confirm scope and resolve the target skill** (SKILL.md §C, §D). First apply the boundary test:
   *would fixing this mean editing a `solidstats-*` SKILL.md or its references?* If no — it is a
   product/code fact, not a skill divergence; stop and route it to memory/MemPalace instead. If yes,
   resolve which skill: infer from the cited section/skill name; if uncertain, ask the user to pick
   from the in-scope candidates. A misrouted correction pollutes the wrong skill's journal. Read that
   skill's section list so `section`/`topic` use its vocabulary.

2. **Classify.** Set `signal` (divergence / gap / caused-bug / friction / preference) and `class`
   (fact / preference) per the taxonomy decision order. The class is the load-bearing field — get it
   right, because it decides whether one occurrence can promote. Record the class reasoning in
   `rationale`.

3. **Bind the evidence** (SKILL.md §G):
   - For a **divergence**, the evidence is the *true fact* (the real path/method) — put it in
     `dev_change`; add a `file:line` in the consuming repo if one proves it.
   - For a **gap** / **caused-bug**, bind the code: prefer the exact snippet the agent was looking at
     (`code.source: agent-snippet`); else best-effort from local `HEAD` by `file:line`, honoring the
     HEAD caveat (an already-fixed snippet is a `positive-example`). For `caused-bug`, also capture the
     bug (symptom or failing test) in `dev_change`.
   - Unbindable and not a principle → `needs-code-context`; capture it but exclude from promotion
     until resolved.

4. **Author the signature** (`signal|section|canonical-description`), wording the description so a
   future near-duplicate collapses onto it (journal-schema §3).

5. **Append the entry** to `<target-skill>/corrections-log.md` using the template. Create the file on
   first use for that target. Never rewrite existing entries — append only; the log is an audit trail.

6. **Emit a regression case** (optional, recommended for conventions/code-review targets). For an
   entry with bound code, append one JSONL line to `<target-skill>/regression-evals.jsonl`
   (journal-schema §4). Skip `needs-code-context` entries.

7. **Stage for commit.** `git add` the journal files (`corrections-log.md`, and
   `regression-evals.jsonl` if written). **Do not commit or push** unless the user asks — AGENTS.md
   forbids autonomous commits, and this repo is shared truth. Tell the user the entry is staged.

8. **Print the soft nudge.** For this target, count `open` entries, `fact` entries ready to promote
   (each promotable at one), and preference clusters at/over three. Report, e.g.:
   `📊 solidstats-server-ts-conventions: 4 open · 1 fact ready · 0 preference-clusters ≥3.`
   Information, not an instruction — the user decides when to run PROMOTE.

## Output

A short summary: the target skill, the signal+class captured, whether code was bound (and as a
positive or negative example), any `needs-code-context` flag, and the nudge line. Do not propose a
skill edit here.
