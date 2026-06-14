---
phase: 18-app-side-error-sdk
status: passed
verified: "2026-06-14"
method: infra wiring verified live; app-repo PRs + e2e deferred to app owners (operator scope)
requirements: [SDK-01]
scope: infra-side plumbing + per-app briefs (no cross-repo PRs — operator decision)
---

# Phase 18 Verification — PASSED (operator-scoped)

The operator scoped Phase 18 to infra-side wiring + per-app wire briefs (no cross-repo PRs). Against
that scope:

| Item | Evidence | Verdict |
|------|----------|---------|
| SENTRY_DSN reaches each app workload | `render-staging-secrets.py` emits it in all 3 runtime Secrets (dry render); 3 live Secrets patched; GitHub `staging` secret set | ✓ |
| Errors-only SDK integration prepared per app | `../plans/<app>/SENTRY-WIRE-BRIEF.md` for server-2 (Node), replays-fetcher (Node CronJob + flush), replay-parser-2 (Rust) — each with the exact errors-only init, env contract, and forced-error test | ✓ |
| DSN handoff documented (DSN → secret → env var, not committed) | `docs/error-sdk-handoff.md` | ✓ |
| SDK-01 | infra prepares the integration; secrets-sourced env; briefs carry the no-traces/no-replay init | ✓ PASS |

## Deferred to app owners (by operator scope — NOT a gap)
- A separate PR in each app repo (SC1) — the briefs are the handoff; PRs are owned in the app repos.
- A live forced error appearing in GlitchTip from a real workload (SC3) — fires once an app merges
  its brief and redeploys (the env + DSN are already in place, so it's a self-contained next step).

Evidence: `18-SUMMARY.md`, `docs/error-sdk-handoff.md`, plans repo commit e27a21c.
