---
name: solidstats-shared-project-standards
description: >
  Universal project standards for every SolidStats repository (server-2, replays-fetcher,
  replay-parser-2, web, infrastructure). Covers GSD workflow obligations, session hygiene, git
  conventions, the cross-app boundary map (what each repo owns and must not cross), the cross-app
  compatibility protocol, security minimums, risk management, and documentation language.
  Use this proactively — read it at the start of any task in any SolidStats repo, even when the
  task doesn't name any of these topics. It is the shared baseline every other SolidStats skill
  assumes. Over-triggering is acceptable.
  Triggers: any task in a SolidStats repo, start of a work session, git commits, cross-repo
  changes, architecture decisions, session planning, before any implementation, Kubernetes,
  deploy, staging, infrastructure.
  Триггеры: любая задача в репо SolidStats, начало рабочей сессии, git коммиты, изменения с
  влиянием на другие репо, архитектурные решения, планирование, перед любой реализацией,
  Kubernetes, деплой, стейджинг, инфраструктура.
---

# SolidStats Project Standards — Universal Baseline

These standards apply to **every repo in the `solid-stats` org** and every session. They define
*how work happens* across the platform, not how any single stack is written — the per-stack
skills own the code details.

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

---

## B. Session Hygiene

Every completed work session must leave the repository in a clean, committed state:

- Run `git status --short` at the end of every session. If there are uncommitted changes from
  the work just done, commit them before stopping.
- Do **not** delete or revert completed work to fake a clean status. If the intended work is
  incomplete, ask what to do rather than silently discarding it.
- The rule is: *commit the intended results of the session, not a reset to the previous state.*

---

## C. Git Conventions

All commits in every SolidStats repo follow **Conventional Commits**:

```
<type>(<scope>): <short description>
```

Common types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
Scope: the phase number, feature area, or affected layer (e.g. `feat(17-03): …`,
`fix(ingest): …`, `docs(planning): …`).

**Absolute rules:**

- Never run `git commit`, `git push`, or any destructive git operation (reset --hard, force
  push, branch -D, rebase) without an explicit instruction from the user in the current message.
  Authorization from a previous message does not carry forward.
- Never skip hooks with `--no-verify` or `--no-gpg-sign` unless explicitly asked to. If a
  pre-commit hook fails, fix the underlying issue — the hook is the signal, not the obstacle.
- When a pre-commit hook fails, the commit did not happen. Create a new commit after fixing;
  do not amend the previous one (amending could silently modify work that already shipped).

---

## D. Cross-App Boundary Map

The platform tier is five services (§J); each has a strict ownership boundary. Crossing it
introduces hidden coupling that is hard to untangle later.

| Repo | Owns | Must NOT |
|------|------|----------|
| **server-2** | Canonical business state: replays, parse_jobs, parse_results, stats, identity, moderation. HTTP API. RabbitMQ orchestration. Auth (Steam OpenID). | Parse OCAP replay content. Crawl/fetch external replay sources. |
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

## F. Security Minimums

These rules apply to all code, commits, and logs across every SolidStats repo:

- **Never log, commit, or output:** secrets, API tokens, database connection strings, S3
  access keys, RabbitMQ credentials, raw replay bytes, or unpublished parser artifacts.
- **Never hardcode environment-specific values.** Use environment variables validated at
  startup (e.g. `envalid` for Node, a validated config struct for Rust). Startup should fail
  fast if required env vars are missing or malformed.
- **Before committing:** check that `.env`, `.env.local`, and any file containing credentials
  is either in `.gitignore` or explicitly excluded from the commit. Never commit secrets to
  git history — they are permanent even after deletion.

---

## G. Risk Management Protocol

When a request is risky, potentially harmful, or would expand scope beyond the current plan:

1. **Explain the concrete reason** — name the specific risk, the boundary it crosses, or the
   plan it contradicts.
2. **Propose 1–3 safer alternatives** or a GSD plan that achieves the goal without the risk.
3. **Ask for explicit confirmation** before proceeding with anything that falls into these
   categories:
   - Crosses a cross-app boundary (§D)
   - Modifies a high-risk cross-repo contract (§E)
   - Contradicts an accepted architecture decision in `.planning/PROJECT.md`
   - Deletes, overwrites, or discards completed work
   - Conflicts with current test quality, security rules, or repo structure standards

Do not blindly execute instructions that conflict with architecture, accepted decisions, or
the quality gates in this repo. Challenge, explain, propose alternatives — then wait.

---

## H. Documentation Language

Language follows the reader. The test for any doc is: who reads it — a user, or an engineer?

- **Every repo README is bilingual.** A README is the repo's front door, read by users (the
  RU-speaking Solid Games community), not an internal engineering doc. So each repo carries a
  Russian `README.md` (primary) plus an English `README.en.md` mirror, edited together in one
  change so they never drift. This is the same pattern the `.github` org profile already uses
  (`profile/README.md` + `profile/README.en.md`) — the profile is just the org-level README.
- **Everything internal is English only** — code, comments, planning docs, skill bodies and
  references, `AGENTS.md`, and all technical `docs/`. These are read by the people and agents
  building the platform, not by users.
- **GSD workflow responses** (conversations within a GSD session) and replies to the user:
  Russian.
- **Skill trigger phrases** (`description` field in `SKILL.md`): RU + EN mandatory. Every skill
  triggers on both languages — the team works in a RU context.

---

## I. MCP Usage

SolidStats development relies on MCP tools to access current documentation. **Never use
training data as the primary source for library APIs** — it has a cutoff and may reflect
outdated or incorrect APIs. Prefer MCP tools for any external library lookup.

### Context7 — library documentation (primary MCP)

Use Context7 whenever you need to look up or verify a library's current API, configuration
options, migration guide, or best practices. This applies proactively — don't wait for a
type error to check the docs.

**Common lookup triggers:** adding a new dependency, upgrading a package, using a method
you're not 100% sure about, hitting an unexpected type error, writing a new integration.

**How to use (two-step pattern):**

```
# Step 1: resolve the library ID
mcp__context7__resolve-library-id({ libraryName: "fastify" })

# Step 2: query the docs
mcp__context7__query-docs({ context7CompatibleLibraryID: "/fastify/fastify", topic: "plugins" })
```

**Key libraries by repo — always look these up via Context7, not training data:**

| Repo | Libraries to look up via Context7 |
|------|-----------------------------------|
| **server-2** | fastify, zod, fastify-type-provider-zod, @fastify/swagger, kysely, pg, amqplib, pino, envalid, prom-client, @aws-sdk/client-s3 |
| **replays-fetcher** | zod, commander, @aws-sdk/client-s3, pg |
| **web** | @tanstack/start, @tanstack/router, @tanstack/react-query, @tanstack/react-table, @tanstack/react-form, @ark-ui/react, vanilla-extract, openapi-typescript, openapi-fetch, openapi-react-query |
| **replay-parser-2** | tokio, serde, serde_json, thiserror, lapin, aws-sdk-s3, axum, tracing, tracing-subscriber |
| **infrastructure** | Kubernetes API reference, kubectl |

### WebSearch / WebFetch — for what Context7 doesn't cover

Use WebSearch or WebFetch for:
- GitHub issues, bug reports, and PRs for a library
- Release notes and migration guides not yet in Context7
- Stack Overflow / forum answers for specific error messages
- Documentation for tools without a Context7 entry (e.g. k3s, MinIO, Timeweb S3)

### Loading MCP tools: Claude Code vs. standalone agents

**In Claude Code (main session):** Context7, WebSearch, and WebFetch appear as *deferred
tools* — their schemas are not loaded until requested. Load them explicitly before use:

```
ToolSearch({ query: "select:mcp__context7__resolve-library-id,mcp__context7__query-docs", max_results: 2 })
ToolSearch({ query: "select:WebSearch,WebFetch", max_results: 2 })
```

**In subagents spawned by Claude Code** (gsd-executor, gsd-planner, gsd-phase-researcher,
etc.): the same mechanism applies — the tools are available but deferred. Always call
`ToolSearch` to load Context7 before the first documentation lookup.

**In standalone agents outside a Claude Code session** (e.g. CI, remote triggers): install
the Context7 MCP server explicitly and add it to the agent's MCP config:

```bash
npx -y @upstash/context7-mcp@latest
```

Then configure the agent's MCP settings to include the Context7 server so it's available
at tool-call time.

### When NOT to use Context7

- For SolidStats-specific code or business logic (no external library is involved).
- For a library you've just looked up in the same session and the answer hasn't changed.
- For stable standard library APIs (e.g. Node.js `fs`, Rust `std::collections`) that are
  unlikely to differ from training data.

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
- **Supporting (3)** — `plans` (cross-project planning), `skills` (this skill set), `ts-toolchain`
  (shared TypeScript config). They support the platform but own no runtime boundary.
- **Legacy (1)** — `sg-replay-parser`. Superseded by `replay-parser-2`; frozen.

**Per-tier documentation:**

| Tier | README | AGENTS.md + CLAUDE.md stub | LICENSE | `.planning/` |
|------|--------|---------------------------|---------|--------------|
| Platform service | bilingual (`README.md` RU + `README.en.md` EN) | yes — shared header + repo body | yes | yes (GSD) |
| Supporting | bilingual (RU + EN) | yes — shared header + repo body | only if it ships reusable code (`ts-toolchain`) | optional (`plans` is docs, not a GSD project) |
| Legacy | bilingual; deprecation banner pointing forward | leave as-is | keep existing | frozen |

- **AGENTS.md opens with a shared header**, then continues with repo-specific guidance: what the
  repo is, its boundary (link to §D for platform repos), and a pointer to this skill set. The
  header makes any repo legible to an agent landing in it cold; the body stays per-repo. Don't
  rewrite a working body to fit a template — add the header above it.
- **CLAUDE.md is a two-line stub** that imports AGENTS.md (`See @AGENTS.md …`). One source of
  agent guidance per repo, not two kept in sync by hand.
- **Governance is centralized.** `CONTRIBUTING` / `SECURITY` / `CODE_OF_CONDUCT` / issue + PR
  templates live once in the `.github` org repo and apply to every repo through GitHub's
  org-default fallback. Don't copy them into individual repos — duplicates drift.
- **The org profile reflects reality.** The `.github` `profile/README.*` repo table groups
  Platform and Supporting and keeps the legacy line. When a repo is added, moves tier, or is
  retired, update the profile (both language files, per §H) in the same change.

---

## References

For the standard CI/CD pipeline pattern used across SolidStats repos (GitHub Actions structure,
concurrency, job layout, Docker build), see
[`references/ci-cd-pattern.md`](references/ci-cd-pattern.md). Read it when setting up or
modifying a `.github/workflows/` file.
