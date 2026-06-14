# Phase 18: App-side Error SDK - Context

**Gathered:** 2026-06-14
**Status:** Ready for execution
**Mode:** Operator-directed scope (autonomous run)

<domain>
## Phase Boundary

Errors-only Sentry SDK integration for server-2, replay-parser-2, replays-fetcher, wired to the
GlitchTip DSN. Tracked here, owned in the app repos.

**Operator-chosen scope (2026-06-14):** infra-side plumbing ONLY in this repo + a per-app wire
BRIEF in the `plans` repo. Do NOT open PRs in the app repos. The briefs let each app owner wire
the SDK on their own schedule.
</domain>

<decisions>
## Implementation Decisions (locked by operator)

- **No cross-repo PRs.** Instead, one wire brief per app in `../plans/<app>/` (the SolidGames
  `plans` repo, alongside PARITY-COORDINATION.md).
- **Infra side (this repo):** add an optional `SENTRY_DSN` to the three runtime Secrets rendered
  by `scripts/render-staging-secrets.py` (server-2-runtime, replay-parser-2-runtime,
  replays-fetcher-runtime — all already consumed via `envFrom: secretRef`, so the env var reaches
  the pods on next deploy with no manifest change). Set the GitHub `staging` secret `SENTRY_DSN`
  and render the live k8s Secrets. `SENTRY_DSN` is optional/empty by default → an empty DSN makes
  the SDK a no-op, so deploys never break before an app wires it.
- **DSN value = the public-URL form** `https://<public_key>@errors.solid-stats.ru/1`. Apps in
  `solid-stats-staging` egress freely to the public edge (no default-deny on the app ns), and the
  edge→glitchtip ingress source is the cni0 gateway 10.42.0.1 which the Phase 17 netpol already
  allows. So NO new NetworkPolicy is needed (the in-cluster direct path
  glitchtip-web.error-tracking.svc:8000 WOULD need a from-solid-stats-staging rule — documented as
  the alternative, not used).
- **Errors-only**: no tracing/APM, no profiling, no session replay. tracesSampleRate=0 /
  profilesSampleRate=0; default error + unhandled-rejection/panic capture only.
- **DSN handoff** documented in `docs/error-sdk-handoff.md`: project DSN → GitHub secret → k8s
  Secret → `SENTRY_DSN` env (via envFrom) → SDK init.
</decisions>

<code_context>
## Existing Code Insights

- GlitchTip live (Phase 16): org `solidstats`, project `staging`, PROJECT_ID `1`, public key
  `e771bce6-706f-4deb-b308-0e4ba12fb233`. Public URL https://errors.solid-stats.ru.
- App stacks: server-2 = Node/TS (`node dist/src/server.js`, entry `src/server.ts`),
  replays-fetcher = Node/TS CronJob (entry `src/cli.ts`), replay-parser-2 = Rust (edition 2024).
- Env injection: each Deployment/CronJob uses `envFrom: secretRef: <app>-runtime`, so adding
  `SENTRY_DSN` to that Secret surfaces it as an env var — no per-manifest env edit needed.
- Phase 17 NetworkPolicies: error-tracking ingress to glitchtip-web allows the edge (10.42.0.1) +
  intra-ns only; a from-solid-stats-staging rule is explicitly deferred (96-netpol comment).
</code_context>

<specifics>
## Specific Ideas

- Briefs: package to add, exact errors-only init snippet, where to init (first import / top of
  main), the `SENTRY_DSN` env contract, a forced-error test, and the "infra injects the env" note.
- server-2: `@sentry/node` v8, `src/instrument.ts` imported first in `src/server.ts`.
- replays-fetcher: `@sentry/node` v8, init at the top of `src/cli.ts`; flush before process exit
  (CronJob — short-lived, must `await Sentry.flush()` so events aren't lost on exit).
- replay-parser-2: `sentry` crate, `let _guard = sentry::init((dsn, ClientOptions{ ... }))` at the
  top of `main()`; errors-only (no `traces_sample_rate`).
</specifics>

<deferred>
## Deferred Ideas

- Opening the actual app-repo PRs + merge + live end-to-end proof (SC3) — deferred to the app
  owners per operator scope. The infra plumbing + briefs make it a self-contained next step.
- In-cluster direct DSN path + its from-solid-stats-staging NetworkPolicy rule (Phase 17 deferral).
</deferred>
