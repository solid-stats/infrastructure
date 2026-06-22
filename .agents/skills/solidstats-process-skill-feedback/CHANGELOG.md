# Changelog — solidstats-process-skill-feedback

## v1.0 — 2026-06-22 — initial skill

- New direct-invoke (`disable-model-invocation`) process skill: the SolidStats self-improvement loop
  for the artefactual `solidstats-*` skills (conventions / code-review / tests / shared-*-standards).
- Sibling of `estesis-process-review-feedback`, diverging on three deliberate decisions:
  - **Signal** — learns from *agent-discovered-during-work* divergence (skill wrong / incomplete /
    caused a bug), not only human edits to AI reviews. Five signals: divergence, gap, caused-bug,
    friction, preference.
  - **Threshold** — hybrid fact/preference: a **fact** promotes at one occurrence; a **preference**
    promotes at three (rule of three). The `class` field is load-bearing.
  - **Journal location** — in the canonical `solid-stats/skills` repo (`<skill>/corrections-log.md` +
    `regression-evals.jsonl`), committed next to the skill, no separate corrections repo and no ENV
    var (this repo is the source of truth the promotion edits). CAPTURE resolves that canonical
    checkout explicitly (§H) — the witness usually works in a *consuming* repo where the running copy
    is the vendored `.agents/skills/**` (wiped on sync), so the journal must never be written there.
- Two modes: CAPTURE (per discovery; entry point via `capture-session-lessons` routing or the
  active-suggestion offer) and PROMOTE (batch, manual; applies the edit in-repo on user approval,
  leaves the commit to the user).
- Boundary with MemPalace/memory: the one-question test — *would fixing this edit a `solidstats-*`
  SKILL.md?* — keeps skill-rule corrections here and product/code facts in MemPalace.
- Active-suggestion protocol documented (§E); the proactive offer is wired into
  `solidstats-shared-project-standards` (auto-fires on every task), since this skill never
  auto-triggers.
- Files: SKILL.md, workflows/{capture,promote}.md, references/{signal-taxonomy,journal-schema}.md,
  templates/correction-entry.md.
