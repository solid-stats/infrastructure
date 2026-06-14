---
phase: 18-app-side-error-sdk
plan: "01"
subsystem: error-tracking
status: complete
tags: [sentry, glitchtip, error-sdk, cross-repo, handoff, secrets]
completed: "2026-06-14T10:45:00Z"
duration: "~20 minutes"

dependency_graph:
  requires:
    - "Phase 16 — GlitchTip live + project DSN (org solidstats / project staging / key e771bce6…)"
    - "Phase 17 — error-tracking netpol (edge ingress allowed; public-URL DSN needs no new rule)"
  provides:
    - "SENTRY_DSN injected into the 3 app runtime Secrets (render-staging-secrets.py + live patch)"
    - "docs/error-sdk-handoff.md — DSN -> secret -> env -> SDK chain + errors-only policy"
    - "../plans/<app>/SENTRY-WIRE-BRIEF.md for server-2, replay-parser-2, replays-fetcher"
  affects:
    - "app repos — each can wire the SDK from its brief independently"

scope_note: >
  Operator-chosen scope (2026-06-14): infra-side wiring + per-app briefs in the plans repo.
  NO cross-repo PRs were opened. SC1 (a PR per app) and SC3 (live end-to-end forced error) are
  intentionally deferred to the app owners; the briefs + injected env make it a self-contained step.

key_files:
  modified:
    - scripts/render-staging-secrets.py
  created:
    - docs/error-sdk-handoff.md
    - ../plans/server-2/SENTRY-WIRE-BRIEF.md
    - ../plans/replay-parser-2/SENTRY-WIRE-BRIEF.md
    - ../plans/replays-fetcher/SENTRY-WIRE-BRIEF.md

commits:
  - "f9c2e13 feat(18): wire SENTRY_DSN into app runtime secrets + DSN handoff doc (infrastructure)"
  - "e27a21c docs: Sentry/GlitchTip wire briefs (plans repo)"

metrics:
  requirements_verified: [SDK-01]
---

# Phase 18 Plan 01: App-side Error SDK wiring (infra + briefs) Summary

**One-liner:** Injected an optional `SENTRY_DSN` into the three app runtime Secrets, documented the
DSN→secret→env→SDK handoff, and shipped a per-app errors-only wire brief to the plans repo — the
app-repo SDK PRs and the live end-to-end proof are left to the app owners (operator scope).

## What was built

- **`render-staging-secrets.py`**: optional `SENTRY_DSN` (empty = SDK no-op) added to
  `server-2-runtime`, `replay-parser-2-runtime`, `replays-fetcher-runtime`. All three are consumed
  via `envFrom: secretRef`, so the env var surfaces with no Deployment/CronJob manifest change.
- **`docs/error-sdk-handoff.md`**: the full chain (project DSN → GitHub `staging` secret →
  `render-staging-secrets.py` → k8s Secret → `envFrom` env → SDK init), the errors-only policy, and
  the choice of the **public-URL DSN** `https://e771bce6-…@errors.solid-stats.ru/1` (apps egress to
  the edge; the edge→glitchtip ingress source 10.42.0.1 is already allowed by Phase 17 — no new
  netpol). The in-cluster alternative + its required `from: solid-stats-staging` netpol rule are
  documented but not used.
- **Three wire briefs** in `../plans/<app>/SENTRY-WIRE-BRIEF.md`:
  - server-2 (Node `@sentry/node` v8, `src/instrument.ts` imported first in `src/server.ts`).
  - replays-fetcher (Node CronJob, init in `src/cli.ts`, **`await Sentry.flush()` before exit**).
  - replay-parser-2 (Rust `sentry` crate, `ClientGuard` at the top of `main()`, errors-only).

## Live state

- GitHub `staging` secret `SENTRY_DSN` set (value never printed/committed).
- The 3 live runtime Secrets in `solid-stats-staging` patched with the `SENTRY_DSN` key
  (non-destructive merge; other keys untouched; no forced rollout — picked up on next deploy).

## Requirement coverage

| Req | Status |
|-----|--------|
| SDK-01 (errors-only SDK prepared, DSN handoff documented, env sourced from secrets not committed) | ✓ infra wiring + 3 briefs deliver the prepared integration + handoff |
| SC1 (a PR per app) | deferred to app owners (briefs instead — operator scope) |
| SC3 (live forced error end-to-end) | deferred — fires once an app merges its brief + redeploys |

## Self-Check: PASSED

- render-staging-secrets.py emits SENTRY_DSN in all 3 runtime Secrets (verified via dry render).
- docs/error-sdk-handoff.md + 3 briefs present; briefs pushed to plans/master (e27a21c).
- GitHub secret set; 3 live k8s Secrets carry the key.
- Commit f9c2e13 (infra) present.
