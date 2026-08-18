<!-- Managed by solid-stats/agent-instructions. Do not hand-edit in a consumer repo — changes
     are overwritten by the next sync PR. Edit the source at
     https://github.com/solid-stats/agent-instructions/blob/master/shared/AGENTS.md instead. -->

## Skills First

Before acting on any user request in this repository, scan available skills by name and description. If any skill has even a small chance of helping any part of the task, use it and read only the relevant instructions before proceeding.

When in doubt, prefer enabling the skill briefly and filtering it out over skipping it.

## Session Hygiene

Every completed work session must leave the repository in a clean, committed state:

- Run `git status --short` at the end of every session. If there are uncommitted changes from
  the work just done, commit them before stopping.
- Do **not** delete or revert completed work to fake a clean status. If the intended work is
  incomplete, ask what to do rather than silently discarding it.
- The rule is: *commit the intended results of the session, not a reset to the previous state.*

## Git Conventions

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

**Auto commit + push policy.** Once the user has explicitly asked for the work to be committed
(this instruction does not itself grant that authorization — see the absolute rules above), the
default flow across every `solid-stats` repo is a **direct push to `master`** — no feature branch,
no PR, unless the repo says otherwise below:

- **`server-2`** has a protected `master` — always go through a branch + pull request there,
  never a direct push.
- Any repo that is mid-GSD-milestone follows that milestone's branch flow instead of a direct
  push (`git` config in `.planning/config.json` — `branching_strategy`, `phase_branch_template`,
  `milestone_branch_template`).
- Every other repo and every non-milestone change: commit on `master`, push directly.

## Security Minimums

These rules apply to all code, commits, and logs across every SolidStats repo:

- **Never log, commit, or output:** secrets, API tokens, database connection strings, S3
  access keys, RabbitMQ credentials, raw replay bytes, or unpublished parser artifacts.
- **Never hardcode environment-specific values.** Use environment variables validated at
  startup (e.g. `envalid` for Node, a validated config struct for Rust). Startup should fail
  fast if required env vars are missing or malformed.
- **Before committing:** check that `.env`, `.env.local`, and any file containing credentials
  is either in `.gitignore` or explicitly excluded from the commit. Never commit secrets to
  git history — they are permanent even after deletion.

## Risk Management Protocol

When a request is risky, potentially harmful, or would expand scope beyond the current plan:

1. **Explain the concrete reason** — name the specific risk, the boundary it crosses, or the
   plan it contradicts.
2. **Propose 1–3 safer alternatives** or a GSD plan that achieves the goal without the risk.
3. **Ask for explicit confirmation** before proceeding with anything that falls into these
   categories:
   - Crosses a cross-app boundary (see the boundary map in `solidstats-shared-project-standards` §D)
   - Modifies a high-risk cross-repo contract (API shape, data model, message queue shape, S3
     layout, parser contract, auth/identity shape, moderation workflow)
   - Contradicts an accepted architecture decision in `.planning/PROJECT.md`
   - Deletes, overwrites, or discards completed work
   - Conflicts with current test quality, security rules, or repo structure standards

Do not blindly execute instructions that conflict with architecture, accepted decisions, or
the quality gates in this repo. Challenge, explain, propose alternatives — then wait.

## Documentation Language

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

## MCP / Documentation Lookup

SolidStats development verifies library APIs against **current documentation, never training
data** — training data has a cutoff and may reflect outdated or incorrect APIs. Look the docs
up proactively; don't wait for a type error.

- **Free official sources only:** WebFetch/WebSearch against the library's official docs and
  its `llms.txt`; the repo's `README`/`docs/` via `gh`; GitHub issues/PRs for bug reports and
  migrations. **Do NOT use Context7 or any paid documentation MCP.**
- **Common lookup triggers:** adding a dependency, upgrading a package, using a method you're
  not 100% sure about, hitting an unexpected type error, writing a new integration.
- **When NOT to look it up:** SolidStats-specific code/business logic; a library already
  looked up this session with an unchanged answer; stable standard-library APIs.

Per-repo key libraries to verify against current docs live in each repo's own
`solidstats-*-conventions` skill, not here.
