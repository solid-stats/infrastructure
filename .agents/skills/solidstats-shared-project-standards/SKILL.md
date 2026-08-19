---
name: solidstats-shared-project-standards
description: >
  SolidStats-specific project standards: GSD workflow obligations and skill authority, the
  cross-app boundary map (what each repo owns and must not cross), the cross-app compatibility
  protocol, and the org's repo taxonomy and documentation standard. Cross-repo rules that apply
  to any team's agents regardless of stack — session hygiene, git conventions, security minimums,
  risk management, documentation language, MemPalace, MCP/doc lookup — live in
  `solid-stats/agent-instructions` instead; read both.
  Use this proactively — read it at the start of any task in any SolidStats repo, even when the
  task doesn't name any of these topics. It is the shared baseline every other SolidStats skill
  assumes. Over-triggering is acceptable.
  Triggers: any SolidStats task; cross-repo changes; architecture; Kubernetes; deploy.
  Триггеры: любая задача SolidStats; межрепозиторные изменения; архитектура; Kubernetes; деплой.
---

<!-- markdownlint-disable MD013 -->

# SolidStats Project Standards — Universal Baseline

These standards apply to **every repo in the `solid-stats` org** and every session. They define
*how work happens* across the platform, not how any single stack is written — the per-stack
skills own the code details.

**This skill and `solid-stats/agent-instructions` are companions, not alternatives.** This skill
owns what is genuinely *SolidStats*-specific: GSD/skill workflow, the cross-app boundary map, the
cross-app compatibility protocol, and the repo taxonomy. Session hygiene, git conventions
(including the auto commit + push policy), security minimums, risk management, documentation
language, MemPalace conventions, and MCP/doc-lookup rules moved to
[`solid-stats/agent-instructions`](https://github.com/solid-stats/agent-instructions) — they
were generic to any team's agents, not to SolidStats, and were previously hand-duplicated across
every repo's `AGENTS.md` instead of living once. A release-managed block embeds that shared source
at the start of every root `AGENTS.md`; read it alongside this skill. (Sections §B, §C, §F, §G,
§H, §I moved there — the remaining letters are not renumbered, so every existing
"§D"/"§E"/"§J" reference elsewhere in the org stays valid.)

The org is not one flat set of repos: there are five **platform services** that run the product,
a few **supporting** repos, and one **legacy** repo. §J defines the three tiers and what
documentation each owes; most of the rules below target the platform services. Read this skill at
the start of any session and keep it in mind throughout.

---

## A. GSD Workflow

SolidStats development runs exclusively through AI agents + GSD workflow. Direct, non-GSD
development is outside the process.

- **Planning docs are first-class:** before implementing anything, check `.planning/` for
  `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, and `STATE.md`. These files define the
  accepted architecture, current milestone, and in-flight decisions. Working from stale or
  missing context causes boundary violations and wasted work.
- **Keep planning docs current.** If a decision is made, a phase advances, or scope changes
  during a session, update the relevant planning file before the session ends.
- **Skills-first.** Before acting on any task, scan available skills. Use a skill even when
  there's only a small chance it helps — the cost is low, the benefit is standardized work.
- **The skill is the source of truth.** For its stack, the installed `solidstats-*` skill
  (conventions or review) **outranks the existing code** — surrounding or legacy code is not a
  style reference, and matching it does not make a change correct. When code and skill disagree,
  never silently follow the code; exactly one of two things is true:
  1. **The code is wrong** → bring the code into line with the skill.
  2. **The skill doesn't yet account for something the code legitimately needs** → the code may
     be right and the skill incomplete → stop, work out how to capture that case, and fix the
     skill itself. Skill edits go in the `solid-stats/skills` repo, then re-sync — never the
     vendored `.agents/skills/**` copy (overwritten on the next sync) — and are recorded in that
     skill's `CHANGELOG.md`.
  Either way, surface the conflict and route the fix to one side — never quietly follow the code
  and move on. This is the working-time face of the authoring rule that conventions are
  *prescriptive*: code is brought into line with the skill, not the reverse.
- **Capturing the skill fix — don't let it evaporate.** When the skill is the thing that's wrong —
  it states a wrong fact, lacks a rule the code legitimately needs, or following it caused a bug —
  proactively **offer to capture that via `solidstats-process-skill-feedback`** (a one-line,
  non-blocking nudge; capture only on a yes). That records the divergence into the target skill's
  `corrections-log.md` so the fix survives after you move on: a **fact** can be promoted into the
  skill at one occurrence, a **preference** after it recurs. This is only for *skill* divergences —
  the test is whether fixing it means editing a `solidstats-*` SKILL.md; a fact about the product or
  codebase goes to memory / MemPalace instead.

---

## D. Cross-App Boundary Map

The platform tier is five services (§J); each has a strict ownership boundary. Crossing it
introduces hidden coupling that is hard to untangle later.

| Repo | Owns | Must NOT |
| ------ | ------ | ---------- |
| **server-2** | Canonical business state: replays, parse_jobs, parse_results, stats, identity, moderation. HTTP API. RabbitMQ orchestration. Auth (Discord OAuth for request authors, moderators, and admins). | Parse OCAP replay content. Crawl/fetch external replay sources. |
| **replays-fetcher** | Raw replay object storage (S3). Ingest staging/outbox records. Source metadata (URL, checksums, fetch timestamps). | Parse replay contents. Mutate server-2 business tables (replays, parse_jobs, parse_results, stats, identity, moderation). Publish RabbitMQ messages. Calculate stats. |
| **replay-parser-2** | OCAP parsing. Versioned parser artifacts. RabbitMQ worker. Health probes. | Write parser results directly into server-2 business tables. Own or assign canonical player identity (server-2 owns player matching). |
| **web** | Frontend. Typed API client (generated from server-2 OpenAPI schema). UI state. | Directly access the database or S3. Bypass the typed API client with raw fetch. |
| **infrastructure** | Kubernetes staging manifests (`k8s/staging/`). Runtime wiring (secrets, env, service mesh). Deployment scripts and runbooks (Bash/Python). Staging CI/CD pipeline. | Own application source code or build container images (app repos do this). Manage production environment (out of scope for v1). Store secret values in git (secrets come from GitHub environment at deploy time only). |

When a task involves code in one repo but touches a boundary, stop and verify the change
stays within that repo's ownership.

**Infrastructure ↔ app repos coordination:** when an app repo changes its container image
interface (env vars, ports, health probe paths, S3 key layout, RabbitMQ queue names), the
infrastructure repo's Kubernetes manifests and secret-rendering scripts must be updated in
sync. Image SHA pinning in `k8s/staging/` must be updated explicitly — the infrastructure
repo never auto-pulls `latest`.

---

## E. Cross-App Compatibility Protocol

Changes in one repo can break another silently. Apply this risk-based check before
implementing:

**Low risk — local only.** Changes that affect only internal business logic, no cross-repo
contracts: rely on local planning docs (`.planning/`). Proceed normally.

**High risk — cross-repo contracts.** Any change that touches the following requires reading
the adjacent app's planning docs or asking the user for confirmation before proceeding:

- **API contract** (server-2 route shape, response structure, error codes)
- **Data model** (PostgreSQL schema, enum values, column types)
- **RabbitMQ message shape** (queue name, message body, routing key)
- **S3 key layout** (bucket, prefix, object naming)
- **Parser contract** (artifact schema version, field names, retryability codes)
- **Auth/identity shape** (session structure, role names, user fields)
- **Moderation workflow** (status transitions, event types)

The check: *does this change affect what server-2 exposes, what the parser produces, or what
web consumes?* If yes, verify compatibility before writing code.

---

## J. Repo Taxonomy & Documentation Standard

The `solid-stats` org is more than the five platform services, and not every repo owes the same
documentation. A runtime service carries more than a shared config package, which carries more
than a frozen legacy repo. Classifying each repo into a tier tells you at a glance what it owes.
The boundary map (§D) covers only the platform tier; this covers the whole org.

**Three tiers:**

- **Platform services (5)** — `server-2`, `replays-fetcher`, `replay-parser-2`, `web`,
  `infrastructure`. They run the product; each owns a runtime boundary (§D) and is a GSD project
  with its own `.planning/`.
- **Supporting (4)** — `plans` (cross-project planning), `skills` (this skill set), `ts-toolchain`
  (shared TypeScript config), `agent-instructions` (shared AGENTS.md fragment + GSD config
  commons). They support the platform but own no runtime boundary.
- **Legacy (1)** — `sg-replay-parser`. Superseded by `replay-parser-2`; frozen.

**Per-tier documentation:**

| Tier | README | AGENTS.md | LICENSE | `.planning/` |
| ------ | -------- | ----------- | --------- | -------------- |
| Platform service | bilingual (`README.md` RU + `README.en.md` EN) | yes — shared header + repo body | yes | yes (GSD) |
| Supporting | bilingual (RU + EN) | yes — shared header + repo body | only if it ships reusable code (`ts-toolchain`, `agent-instructions`) | optional (`plans` is docs, not a GSD project) |
| Legacy | bilingual; deprecation banner pointing forward | leave as-is | keep existing | frozen |

- **AGENTS.md starts with the release-managed `agent-instructions` block**, followed by
  repo-specific guidance: a blockquote header, what the repo is, its boundary (link to §D for
  platform repos), and a pointer to this skill set. The header makes any repo legible to an agent
  landing in it cold; the body stays per-repo. Don't edit the managed block or rewrite a working
  body to fit a template — update shared rules in `solid-stats/agent-instructions` and keep local
  guidance outside the markers.
- **AGENTS.md is the only required agent-instruction file.** Do not create, restore, or validate
  `CLAUDE.md`; repositories may remove it. This keeps one source of agent guidance per repo.
- **Governance is centralized.** `CONTRIBUTING` / `SECURITY` / `CODE_OF_CONDUCT` / issue + PR
  templates live once in the `.github` org repo and apply to every repo through GitHub's
  org-default fallback. Don't copy them into individual repos — duplicates drift.
- **The org profile reflects reality.** The `.github` `profile/README.*` repo table groups
  Platform and Supporting and keeps the legacy line. When a repo is added, moves tier, or is
  retired, update the profile (both language files, per the documentation-language rule in
  `agent-instructions`) in the same change.

---

## References

For the standard CI/CD pipeline pattern used across SolidStats repos (GitHub Actions structure,
concurrency, job layout, Docker build), see
[`references/ci-cd-pattern.md`](references/ci-cd-pattern.md). Read it when setting up or
modifying a `.github/workflows/` file.
