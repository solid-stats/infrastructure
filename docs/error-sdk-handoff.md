# App-side Error SDK — DSN Handoff (GlitchTip)

How each GlitchTip project DSN reaches its app workload so an errors-only Sentry SDK can report
to GlitchTip. Infra owns the wiring; the per-app SDK code is owned in the app repos (wire briefs:
`../plans/<app>/SENTRY-WIRE-BRIEF.md`).

## Model: one project per app, one org per environment

Each app reports to its **own** GlitchTip project, so issue lists / DSNs / quotas are separated per
service. Environments are separated at the **organization** level (`staging`, `production`).

| App | Env | GlitchTip org / project (id) | DSN the app uses |
|-----|-----|------------------------------|------------------|
| `server-2` | staging | `staging` / `server-2` (2) | `https://32d59bfbb7ea43e0bba7d91d79405c77@errors.solid-stats.ru/2` |
| `replays-fetcher` | staging | `staging` / `replays-fetcher` (3) | `https://b8337da501bf411c8e8cb454e66e9f28@errors.solid-stats.ru/3` |
| `replay-parser-2` | staging | `staging` / `replay-parser-2` (4) | `https://1c0d52572d6d4813b25329e46f5ea83b@errors.solid-stats.ru/4` |
| `server-2` | production | `production` / `server-2` (5) | `https://5b4b2f26b87c4fafbbeb1d199df077b2@errors.solid-stats.ru/5` |
| `replays-fetcher` | production | `production` / `replays-fetcher` (6) | `https://8d1bd54c772e45f2b0deb916e6d9a9fc@errors.solid-stats.ru/6` |
| `replay-parser-2` | production | `production` / `replay-parser-2` (7) | `https://a78e1215080149bb9e3b216318ae98ee@errors.solid-stats.ru/7` |

The DSN public key is a non-secret client ingest key. The **public-URL** form is used on purpose:
app pods egress freely to the public edge, and the edge → glitchtip-web ingress source is the cni0
gateway `10.42.0.1`, which the Phase 17 NetworkPolicy already allows. No new NetworkPolicy is required.

## Handoff chain (per app)

```
GlitchTip project DSN (per app, per env)
  → GitHub <env> environment secret  SENTRY_DSN_SERVER_2 | SENTRY_DSN_REPLAYS_FETCHER | SENTRY_DSN_REPLAY_PARSER_2
  → scripts/render-<env>-secrets.py  (injects each into the matching <app>-runtime Secret as SENTRY_DSN)
  → k8s Secret  server-2-runtime / replays-fetcher-runtime / replay-parser-2-runtime
  → Deployment/CronJob  envFrom: secretRef  →  env var  SENTRY_DSN
  → app SDK init  (Sentry.init / sentry::init reads SENTRY_DSN)
```

The in-pod env var name stays `SENTRY_DSN` for every app — only the value differs per app. Each DSN
is **optional** in the renderer: an empty value makes the SDK a no-op, so an app can ship the SDK
code before its secret is set (and vice versa) without breaking deploys. No manifest change is
needed — every app workload already pulls its env via `envFrom: secretRef: <app>-runtime`.

## Operator steps

**Staging — done:**

```bash
# Three per-app DSN secrets in the GitHub `staging` environment:
gh secret set SENTRY_DSN_SERVER_2        --env staging -R solid-stats/infrastructure --body '…/2'
gh secret set SENTRY_DSN_REPLAYS_FETCHER --env staging -R solid-stats/infrastructure --body '…/3'
gh secret set SENTRY_DSN_REPLAY_PARSER_2 --env staging -R solid-stats/infrastructure --body '…/4'
# render-staging-secrets.py reads them; CI renders + applies the runtime Secrets on deploy.
```

**Production — pending prod infra.** The three production projects exist (ids 5/6/7) but there is no
`render-production-secrets.py` / production namespace yet. When prod is stood up, set the **same three
secret names** in the GitHub `production` environment (values = the production DSNs above); the prod
renderer reuses the names, so no further change here.

The env var reaches the pods on their next rollout — it becomes live when an app wires the SDK and
redeploys.

## Errors-only policy (all apps)

No tracing/APM, no profiling, no session replay. `tracesSampleRate: 0`, `profilesSampleRate: 0`;
only error + unhandled-rejection/panic capture. Keep `environment: "staging"`. Short-lived
workloads (the replays-fetcher CronJob) MUST `await Sentry.flush()` before exit or events are lost.

## Per-app wire briefs

- `../plans/server-2/SENTRY-WIRE-BRIEF.md` — Node `@sentry/node`, init-first in `src/server.ts`.
- `../plans/replays-fetcher/SENTRY-WIRE-BRIEF.md` — Node `@sentry/node` CronJob, init in `src/cli.ts` + flush on exit.
- `../plans/replay-parser-2/SENTRY-WIRE-BRIEF.md` — Rust `sentry` crate, guard at the top of `main()`.
