# PROMOTE — harvest accumulated corrections into rule changes

Run this manually, in batch, when a target's journal has built up (the capture nudge tells you when).
Goal: find what has earned a rule change — a **fact at one occurrence**, a **preference at three** —
route each to the right home, draft the edit to the target skill plus its CHANGELOG, and apply on the
user's approval. PROMOTE runs in **this skills repo**, so it can apply the edit directly — but never
silently and never auto-committed.

## Required reading
- `references/journal-schema.md` — the entry schema and cluster signature
- `references/signal-taxonomy.md` — routing per signal
- The **target skill's SKILL.md** (and the relevant `references/*`) — you are editing it, so read its
  current rules and section style in full first
- The shared standard's SKILL.md — when routing a shared/ambiguity correction there

## Steps

1. **Scope.** One target skill (default) or all in-scope skills. Load
   `<target-skill>/corrections-log.md`. Consider only `status: open` entries; exclude
   `needs-code-context`.

2. **Separate facts from preferences.**
   - **fact** entries are each individually promotable — no clustering needed to reach a count. De-dup
     so the same fact logged twice is proposed once.
   - **preference** entries cluster by `signature`. Cluster **semantically** (merge matching
     `(signal, section)` whose descriptions mean the same problem), present each proposed cluster (its
     member `id`s + a one-line summary) to the user, and confirm before counting. A `generalized: true`
     principle may surface below three but still needs the user's nod.

3. **Apply the threshold.** Promote a **fact** at ≥1, a **preference cluster** at ≥3. Preferences
   below three stay open — report them as "warming" so the user sees what's near.

4. **Route each candidate** (signal-taxonomy §4) and confirm with the user in one line:
   - the wrong/missing/ambiguous rule lives in the **per-stack skill** → edit that skill;
   - it lives in a shared rule the stack delegates to → edit the `solidstats-shared-*-standards`
     skill instead (same delegation the skills already use).
   Routing is a proposal — state your reasoning and let the user redirect.

5. **Check regression evals (optional, recommended).** Before finalizing, run the relevant
   `regression-evals.jsonl` cases against the target skill as-is to confirm the gap is real, and after
   drafting the rule, re-check the change would flip them. Cheap proof the edit earns its place.

6. **Draft the edit.** Produce the concrete change to the target `SKILL.md` / `references/*`, in that
   skill's voice and section style, plus the matching `CHANGELOG.md` entry (AGENTS.md requires one on
   every skill change). Follow the additive-change preference — extend, narrow, or correct a rule;
   don't silently delete; note deprecations with a reason. Cite the source entry `id`s in the
   changelog justification.

7. **Apply on approval.** Show the diff; on the user's go, apply it to the skill and the CHANGELOG in
   this repo. **Leave the commit to the user** (AGENTS.md: never commit/push without explicit
   instruction) — even though SolidStats pushes direct-to-master, a skill is shared truth and the
   human decides when it lands.

8. **Close the loop.** After the edit lands, mark the promoted cluster's entries `status: promoted` in
   `corrections-log.md` so the pattern doesn't re-surface. Optionally graduate a proven regression case
   into the target skill's core `evals/evals.json` if the rule is now canonical — a deliberate,
   user-approved move.

## Output

A promotion report: facts ready (each with its source `id` + proposed edit), preference clusters
ready (member ids + routing + diff), preference clusters warming (count vs. three), and any
`needs-code-context` entries blocking otherwise-good patterns. End with the list of skill edits
applied or awaiting the user's hand, and a reminder that committing is the user's call.
