---
name: solidstats-process-skill-feedback
description: >
  Closes the self-improvement loop for the artefactual SolidStats skills — the per-stack
  `solidstats-*-conventions`, `*-code-review`, `*-tests`, and the `solidstats-shared-*-standards`
  they delegate to. While an agent does real work in server-2, replays-fetcher, replay-parser-2, or
  web, it discovers that a skill's rule is WRONG (diverges from the code reality), INCOMPLETE (a real
  pattern the rule doesn't cover), or CAUSED A BUG (following the rule produced a defect); a human may
  also edit a skill-produced artefact. Today that signal evaporates. This skill captures it into a
  per-skill journal that lives in THIS skills repo (`<skill>/corrections-log.md`), and — once a
  pattern earns it (a fact at one occurrence, a preference at three) — proposes a routed patch to the
  target skill's SKILL.md / references plus its CHANGELOG entry for you to apply. It is the SolidStats
  sibling of `estesis-process-review-feedback` (which is a different client) but learns from
  agent-discovered-during-work divergence, not just human edits to AI reviews. Two modes: CAPTURE
  (per discovery; often routed here by capture-session-lessons or offered proactively by the active
  skill) and PROMOTE (batch, manual). NOT for product/code facts (those go to MemPalace via the GSD
  curator) and NOT for process/knowledge skills (no capturable signal). Use it whenever a
  `solidstats-*` rule has been shown wrong by real work, you want to feed that back, or you want to
  promote accumulated corrections into rules.
  Triggers: "skill feedback", "the convention is wrong", "this skill is out of date", "capture skill
  correction", "feed this back into the skill", "promote skill corrections", "improve the solidstats
  skill from work", "обратная связь по скиллу", "конвенция врёт", "скилл устарел", "зафиксируй
  правку скилла", "учти это в скилле", "промоут правок скиллов", "обнови скилл по итогам работы".
disable-model-invocation: true
---

# SolidStats Skill Feedback — self-improvement loop for the artefactual skills

The SolidStats `solidstats-*` rule skills are **prescriptive** (AGENTS.md): they define the desired
standard, and the codebase is brought into line over time. But a prescriptive skill can still be
**wrong** about a fact (it names a path/import/API that does not exist), **incomplete** (a real
pattern emerged that no rule covers), or **harmful** (following it produced a bug). The agent that
discovers this while working in server-2 / replays-fetcher / replay-parser-2 / web is the best —
and often the only — witness. This skill turns that discovery into a durable improvement to the
**target** skill.

It does **not** review code and it does **not** decide conventions on its own. It records that a
skill diverged from reality and, on enough evidence, proposes the rule edit for you to apply.

This is the SolidStats sibling of `estesis-process-review-feedback`. That one is a different client
(VocalClub/Estesis) and learns from a human editing an AI review in a separate corrections repo.
This one learns from **agent-discovered-during-work** divergence and keeps the journal **inside this
skills repo**.

---

## A. The mental model — why it works this way

Four ideas drive the design. Understand these and the workflows follow.

**1. The witness is the working agent, not a human reviewing a review.** Estesis' dominant signal is
a reviewer trimming/adding findings on an AI review. Here the dominant signal is an agent mid-task
finding that `solidstats-server-ts-conventions` says one thing and `server-2` does another, or that
obeying a rule produced a bug. That signal is perishable — the agent moves on and the insight dies
unless captured now. So capture is cheap, append-only, and offered the moment divergence is seen.

**2. The journal is a cheap interlingua.** Corrections arrive in different shapes (an agent's
mid-work observation, a human edit, free-form prose). They all normalize into **one journal entry
schema** so the rest of the machine is source-agnostic. The journal is plain Markdown committed next
to the skill — it costs nothing to hold many entries. See `references/journal-schema.md`.

**3. Fact vs preference decides the threshold — not a flat rule of three.** A correction is one of
two classes, and that class is the single most important field:
- **fact** — objectively right/wrong: the skill names a wrong path/method/command, contradicts
  itself, or caused a bug. One credible occurrence is enough; waiting for three repeats of a known
  falsehood just leaves the skill lying twice more. → eligible to promote at **one** occurrence.
- **preference** — taste/style with no hard correctness ("better to name it this way", "this rule
  reads ambiguous"). One agent's opinion is noisy. → promote only after **three** (rule of three),
  the same DRY instinct the reviewers enforce.

**4. Capture and promote are two stages, not one.** *Capture* answers "what diverged?" — classify,
bind the offending code, normalize, append. Cheap, run per discovery. *Promote* answers "what do we
change?" — cluster, apply the fact/preference threshold, propose the actual rule edit. We never edit
a shared skill from an unexamined single data point.

```
  agent finds divergence mid-work ┐
  human edits a skill artefact    ┼─► normalize ─► journal entry ──► <skills-repo>/<target-skill>/corrections-log.md
  free-form prose                 ┘   (§ references/signal-taxonomy.md)   (+ regression-evals.jsonl when code is bound)
                                                                                  │  (git add; commit on the user's say-so)
                          CAPTURE (per discovery) ──────────────────────────────┘
                                                                                  │
                          PROMOTE (maintainer, batch) ─► cluster ─► fact@1 / pref@3 ─► route ─► propose SKILL.md + CHANGELOG diff ─► apply
```

---

## B. Pick the mode

| You have… | Run | Workflow |
|-----------|-----|----------|
| A fresh divergence (agent-found or human-edited), or a routed lesson from capture-session-lessons | **CAPTURE** | `workflows/capture.md` |
| A journal with accumulated entries you want to harvest into rules | **PROMOTE** | `workflows/promote.md` |

If intent is ambiguous, default to CAPTURE — corrections are perishable; nothing is lost by
capturing first and promoting later.

---

## C. Scope — which skills this loop covers

**In scope (artefactual — they have a capturable signal):**
- per-stack conventions — `solidstats-server-ts-conventions`, `solidstats-fetcher-ts-conventions`,
  `solidstats-parser-rust-conventions`, `solidstats-frontend-react-conventions`;
- per-stack code-review — `solidstats-*-code-review` (and `solidstats-frontend-react-design-review`);
- per-stack tests — `solidstats-*-tests`;
- the shared rule libraries those delegate to — `solidstats-shared-review-standards`,
  `solidstats-shared-testing-standards`, `solidstats-shared-ts-standards`,
  `solidstats-shared-backend-ts-standards`, `solidstats-shared-project-standards`.

**Out of scope (no capturable "the rule was wrong" signal):** GSD wrappers, the `process-*` skills
themselves, `estesis-*` (different client), and pure-knowledge skills. A lesson about one of those is
not a skill-divergence — route it normally (memory / MemPalace), not here.

---

## D. The boundary that keeps this DRY — what belongs here vs MemPalace/memory

This loop overlaps dangerously with `capture-session-lessons`, the global memory, and GSD's
`gsd-mempalace-curator`. Keep them separate with **one test**:

> *Would fixing this mean editing a `solidstats-*` SKILL.md or one of its `references/`?*

- **Yes** → it belongs **here**. The skill itself is wrong/incomplete/harmful. Example: "conventions
  says deps live in `deps.py`, but the repo uses `di/`."
- **No** → it is a fact about the **product or codebase**, not about a skill. Route it to MemPalace
  (`gsd-mempalace-curator`) or global memory as usual. Example: "server-2's match table is
  partitioned by month."

`capture-session-lessons` is the front door: when it identifies a lesson that passes the test above,
it routes the lesson **here** (CAPTURE) instead of into flat memory. This skill is the processor and
the journal; capture-session-lessons (or a proactive offer from the active skill — §E) is one way in.

---

## E. The active-suggestion protocol — making capture happen

The biggest risk is silent under-capture: the agent notices the skill is wrong, fixes its own work,
and moves on without recording it. Because this skill is `disable-model-invocation` (it never
auto-triggers during coding), the *prompt to capture* must come from the **active** skill — the
conventions / review / tests skill loaded while the work happens. The hook for that lives in
`solidstats-shared-project-standards` (which auto-fires on every SolidStats task): *if you find a
`solidstats-*` rule that is wrong, incomplete, or that caused a bug, proactively offer to capture it
via `solidstats-process-skill-feedback`.*

When you make that offer, keep it a one-line, non-blocking nudge — never derail the task:

> *"`solidstats-server-ts-conventions` §4 says deps live in `deps.py`, but server-2 uses `di/`.
> Want me to capture this so the skill gets fixed? (solidstats-process-skill-feedback)"*

Capture only on a yes. The user stays in control; the loop just stops the signal from evaporating.

---

## F. The five signals

Each correction carries one primary signal. The signal and the **class** (fact/preference, §A.3)
together decide capture and threshold. Full definitions and class-assignment rules:
`references/signal-taxonomy.md`.

| Signal | What happened | Class default | Code needed? | Routes to |
|--------|---------------|---------------|--------------|-----------|
| **divergence** | Skill states X; the real code / correct practice is Y | **fact** | the proof (file:line or the true fact) | fix/correct the rule in the target skill |
| **gap** | A real pattern exists in code that no rule covers | fact if canonical, else preference | yes — the pattern | a new/extended rule in the target skill |
| **caused-bug** | Following the rule produced a defect | **fact** | yes — the offending code + the bug | qualify/fix the rule; add a guardrail |
| **friction** | The rule is ambiguous/contradictory and slowed work | fact if a genuine internal contradiction, else preference | optional | clarify the rule (or shared standard) |
| **preference** | A stylistic improvement, no hard correctness | **preference** | optional (example only) | the rule, only after rule of three |

**Generalized principle.** Sometimes the witness states a *rule*, not an instance ("always reach the
DB through the repository layer"). The generalizing is already done, so code is optional (keep it as
an example) — treat it as a `gap` with `generalized: true`; it can become a candidate on its own
merits, but still route it and let the user confirm.

---

## G. Binding the offending code

A `gap` or `caused-bug` is only learnable with the code it points at. Bind code **at capture**,
because the branch is often deleted post-merge.

Source priority, most trustworthy first:
1. **The exact snippet the agent was looking at** when it found the divergence — paste it into the
   entry. This is the SolidStats norm (the witness is the working agent, §A.1).
2. **Best-effort from local `HEAD`** by `file:line` in the consuming repo. **Caveat:** because the
   agent may have already fixed its own code, `HEAD` can show the *corrected* version — that is a
   **positive example** ("don't flag this"), not the offending one. Detect and label it.
3. **None.** Pure prose with no locator → admissible only as a generalized principle (§F);
   otherwise mark `needs-code-context` and exclude from promotion until resolved.

For a pure **divergence** (skill says a wrong path/method), the "code" is the *true fact* — the real
path/method — not a snippet; record it in `dev_change`.

---

## H. Where things live — the canonical `solid-stats/skills` repo

Unlike Estesis (a separate corrections repo, because its install dir is wiped and a consumer may not
have the skills checkout), the SolidStats journal lives **inside the skills repo itself** — that repo
*is* the source of truth for the skills, and it is exactly what a promotion edits. No second repo, no
ENV var.

```
<solid-stats/skills checkout>/
└── <target-skill-name>/
    ├── SKILL.md
    ├── CHANGELOG.md
    ├── corrections-log.md        # the journal            ← committed next to the skill
    └── regression-evals.jsonl    # regression tier (opt)  ← committed; one case per code-bound entry
```

**Resolving the canonical checkout — this matters, because the witness is usually elsewhere.** The
divergence is almost always found while working in a *consuming* repo (server-2, replays-fetcher,
replay-parser-2, web), and the copy of this skill running there is the **vendored** `.agents/skills/**`
copy — which is overwritten on the next `npx skills update`. Never write the journal into the vendored
copy or into the consuming repo. Resolve the real `solid-stats/skills` checkout, in order:
1. If the cwd (or an ancestor) is a git repo whose remote is `solid-stats/skills`, use it.
2. Else look for a local clone — a sibling of the consuming repo (`../skills`) or another checkout
   under `~/Projects/**` whose remote is `solid-stats/skills`. Confirm the remote before writing.
3. Else **stop and ask** the user for the path. A journal written into the vendored copy is lost on
   the next sync and silently breaks the count — never guess.

`corrections-log.md` and `regression-evals.jsonl` are created on first capture for a target, in that
canonical checkout. There is no inbox/processed staging — the witness pastes the correction straight
into a journal entry. (This is the same resolution `solidstats-shared-project-standards` §A already
mandates for any skill edit: changes go to `solid-stats/skills`, never the vendored copy.)

---

## I. Promotion gate and edit discipline

PROMOTE may **apply** the edit in this same repo (no separate checkout to propose against), but never
silently and never auto-committed:

- Promote only a cluster that clears its threshold — **fact at one**, **preference at three** (§A.3).
  A `generalized: true` principle may surface below three but still needs the user's nod.
- Draft the concrete edit to the target `SKILL.md` / `references/*`, in that skill's voice and
  section style, plus the matching `CHANGELOG.md` entry (AGENTS.md requires a changelog entry on
  every skill change). Follow the additive-change preference — extend or narrow a rule, don't
  silently delete; note deprecations with a reason.
- **Show it, apply on the user's approval, and leave the commit to the user** (AGENTS.md: never
  commit/push without explicit instruction). For SolidStats the norm is direct-to-master; still, a
  skill is shared truth — the human decides when it lands.
- After it lands, mark the cluster's entries `status: promoted` in the journal so the same pattern
  doesn't re-surface.

Promotion is **manual**. At the end of a capture, print a soft nudge —
`📊 <skill>: N open · M facts ready · K preference-clusters ≥3` — so the user knows when it's worth
running, without forcing it.

---

## J. Workflows and references

| File | When to read |
|------|--------------|
| `workflows/capture.md` | Running CAPTURE — classify signal+class, bind code, normalize, append, emit regression case, nudge |
| `workflows/promote.md` | Running PROMOTE — cluster, apply fact@1/pref@3, route, draft SKILL.md + CHANGELOG edit, apply on approval |
| `references/signal-taxonomy.md` | The five signals, the fact/preference class rules, and how each routes |
| `references/journal-schema.md` | The normalized entry schema, the cluster signature, the regression-eval shape |
| `templates/correction-entry.md` | The exact journal block to append |
