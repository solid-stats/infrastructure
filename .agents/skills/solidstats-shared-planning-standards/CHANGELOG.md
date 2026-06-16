# Changelog — solidstats-shared-planning-standards

## 2026-06-16 — Initial
- New shared foundation skill. Implements **Improvement 1 (plan provenance)** from
  `plans/product/BMAD-EVALUATION-AND-GSD-IMPROVEMENTS.md` (decision D2) plus the **planning half of
  C6 (graphify wired into the workflow)** from `plans/product/GSD-IMPROVEMENTS.md`.
- §A source anchors `[src: file#anchor]` / `[src: graph:…]` / `[src: SUMMARY.md#deviations]` on every
  load-bearing premise, in the same citation idiom as the reviewers' `[conv: …]` / `[std: …]`.
- §B premises ledger — `claim` + `src` + a one-line `verify` command the plan-checker runs, distinct
  from `must_haves.truths` (premises are inputs; truths are post-conditions).
- §C carried-forward learnings — cite the prior phase's `*-SUMMARY.md#deviations` as a stated premise.
- §D consult the knowledge graph at discuss/plan (gated on `graphify.enabled`): query for the phase
  topic, fold the community + blast radius into `<context>`/premises, refresh after execution. The
  skill-injection route is the bridge; the gsd-core capability-descriptor patch (ADR-857) is the
  heavier alternative. The review half of C6 lives in `solidstats-shared-review-standards`.
- §E wiring — `agent_skills` injection for `gsd-planner`/`gsd-plan-checker`/`gsd-executor` in each
  repo's `.planning/config.json`, plus the plan-checker spot-verify checklist item (consumer-repo
  config, tracked outside this repo). Additive: a plan with no anchors still plans.
- Meta-only triggers (RU + EN): read by the planning agents via injection, never triggered directly.
- Provenance: ADR `decisions/0007-bmad-borrowed-improvements.md`.
