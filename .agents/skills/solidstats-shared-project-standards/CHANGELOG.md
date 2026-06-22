# Changelog — solidstats-shared-project-standards

## 2026-06-22 — v1.5 — §A active-suggestion hook for the skill-feedback loop

- §A "The skill is the source of truth" gains a bullet wiring the **active-suggestion protocol**: when
  a `solidstats-*` skill is shown wrong / incomplete / bug-causing during work, proactively offer to
  capture it via the new `solidstats-process-skill-feedback` (one-line nudge, capture on yes). This is
  the always-in-context hook for that loop (the feedback skill is `disable-model-invocation`, so it
  cannot prompt for itself). Reiterates the fact@1 / preference@3 threshold and the skill-vs-product
  boundary test (would the fix edit a `solidstats-*` SKILL.md?).

## 2026-06-20 — v1.4 — §I docs via free sources (drop Context7); web stack → Tailwind

- §I MCP Usage reframed from "Context7 as the primary documentation MCP" to **free official
  sources only**: WebFetch / WebSearch against official docs + a project's `llms.txt`, and the repo
  `README`/`docs` via `gh`. **Context7 and any paid documentation MCP are explicitly out** — removed
  the Context7 two-step example, the `@upstash/context7-mcp` install block, and the Context7
  ToolSearch load; deferred-tool loading now targets `WebSearch`/`WebFetch`.
- Fixed the per-repo library table: `web` now lists **tailwindcss, tailwind-variants** (was the
  superseded vanilla-extract).

## 2026-06-19 — v1.3 — Repo taxonomy & documentation standard

- Added §J Repo Taxonomy & Documentation Standard: the three org tiers (5 platform services /
  3 supporting / 1 legacy) and the per-tier documentation matrix (README, AGENTS.md + CLAUDE.md
  stub, LICENSE, `.planning/`), plus the AGENTS.md shared-header rule, the CLAUDE.md stub rule,
  centralized governance via `.github`, and the org-profile-reflects-reality rule.
- Reframed the intro and §D first line from "five-repo platform" to "every repo in the org,
  across three tiers (§J)" — the platform tier is still the five services; the boundary map is
  unchanged. Reconciles the stale "5-repo" wording against the 9 real repos (reality is canon for
  existence facts; the skill is canon for structure).
- Refined §H Documentation Language: every repo README is bilingual — a Russian `README.md`
  (primary) plus an English `README.en.md` mirror — because a README is the user-facing front door
  for the RU-speaking community, the same pattern the org profile already uses. Everything internal
  (code, comments, planning, skill bodies/refs, `AGENTS.md`, `docs/`) stays English. Replaces the
  prior blanket "README files: English only." GSD-session-Russian and RU+EN trigger rules unchanged.
- Cross-stack reasoning recorded in `decisions/0008-repo-taxonomy-and-documentation-standard.md`.

## 2026-06-18 — v1.2 — Skill is the source of truth

- Added §A bullet "The skill is the source of truth": the installed `solidstats-*` skill
  outranks existing code; on a code↔skill conflict either the code is wrong (fix the code) or
  the skill is incomplete (fix the skill in `solid-stats/skills`, re-sync, update its CHANGELOG)
  — never silently follow the code. Surfaces the authoring rule (conventions are prescriptive)
  at working time and adds the explicit conflict-resolution + skill-feedback loop.

## 2026-06-07 — v1.1 — MCP usage guidelines

- Added §I MCP Usage: Context7 as primary library docs MCP, per-repo library lookup table,
  WebSearch/WebFetch for issues and release notes.
- Covers all three agent contexts: Claude Code main session (ToolSearch deferred load),
  Claude Code subagents (same ToolSearch pattern), standalone agents (npx install).
- Explicit "when NOT to use" to avoid unnecessary lookups.

## 2026-06-07 — v1.0 — Initial release

- Created skill covering GSD workflow obligations, session hygiene, git conventions,
  cross-app boundary map, cross-app compatibility protocol, security minimums, risk
  management protocol, and documentation language.
- Added `references/ci-cd-pattern.md` with the standard GitHub Actions structure,
  Dockerfile conventions, and Docker Compose test service layout.
- Covers all five SolidStats repos: server-2, replays-fetcher, replay-parser-2, web,
  and infrastructure — single source of truth extracted from duplicated CLAUDE.md/AGENTS.md
  content across all five repos.
- §D cross-app boundary map includes the infrastructure repo (k8s manifests, staging
  orchestration, secret rendering, SHA pinning model).
- CI/CD reference includes both the app-repo pattern (verify+image) and the infrastructure
  repo pattern (validate+SSH deploy).
