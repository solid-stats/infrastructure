# Changelog — solidstats-process-project-standards

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
