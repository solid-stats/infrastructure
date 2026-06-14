# App-side Error SDK — DSN Handoff (GlitchTip)

How the GlitchTip project DSN reaches the app workloads so an errors-only Sentry SDK can report
to GlitchTip. Infra owns the wiring; the per-app SDK code is owned in the app repos (wire briefs:
`../plans/<app>/SENTRY-WIRE-BRIEF.md`).

## The DSN

| Field | Value |
|-------|-------|
| GlitchTip org / project | `solidstats` / `staging` (PROJECT_ID `1`) |
| Public key (non-secret client key) | `e771bce6-706f-4deb-b308-0e4ba12fb233` |
| **DSN the apps use** | `https://e771bce6-706f-4deb-b308-0e4ba12fb233@errors.solid-stats.ru/1` |

The **public-URL** form is used on purpose: app pods in `solid-stats-staging` egress freely to the
public edge, and the edge → glitchtip-web ingress source is the cni0 gateway `10.42.0.1`, which the
Phase 17 NetworkPolicy already allows. So no new NetworkPolicy is required.

> In-cluster alternative (NOT used): `http://e771bce6-…@glitchtip-web.error-tracking.svc:8000/1`.
> This direct path is blocked by the Phase 17 `error-tracking` default-deny ingress (only the edge +
> intra-ns are allowed). Using it would require adding a `from: solid-stats-staging` selector to
> `allow-glitchtip-web-ingress` in `k8s/observability/96-netpol-error-tracking.yaml` (the Phase 18
> note in that file). Prefer the public URL until there's a reason to switch.

## Handoff chain

```
GlitchTip project DSN
  → GitHub `staging` environment secret  SENTRY_DSN
  → scripts/render-staging-secrets.py  (injects SENTRY_DSN into each <app>-runtime k8s Secret)
  → k8s Secret  server-2-runtime / replay-parser-2-runtime / replays-fetcher-runtime
  → Deployment/CronJob  envFrom: secretRef  →  env var  SENTRY_DSN
  → app SDK init  (Sentry.init / sentry::init reads SENTRY_DSN)
```

`SENTRY_DSN` is **optional** in the renderer. An empty value makes the Sentry SDK a no-op, so an app
can ship the SDK code before the secret is set (and the secret can be set before the SDK ships)
without breaking deploys. No manifest change is needed — every app workload already pulls its env
via `envFrom: secretRef: <app>-runtime`.

## Operator steps (infra side — done in Phase 18)

```bash
# 1. Set the GitHub staging secret (value = the public-URL DSN above)
gh secret set SENTRY_DSN --env staging --body 'https://e771bce6-…@errors.solid-stats.ru/1'

# 2. Render + apply the runtime Secrets (CI does this on deploy; or live):
SENTRY_DSN=… <other runtime envs> python3 scripts/render-staging-secrets.py | kubectl apply -f -
```

The env var reaches the pods on their next rollout — no forced restart is needed just to carry an
unused var; it becomes live when an app actually wires the SDK and redeploys.

## Errors-only policy (all apps)

No tracing/APM, no profiling, no session replay. `tracesSampleRate: 0`, `profilesSampleRate: 0`;
only error + unhandled-rejection/panic capture. Keep `environment: "staging"`. Short-lived
workloads (the replays-fetcher CronJob) MUST `await Sentry.flush()` before exit or events are lost.

## Per-app wire briefs

- `../plans/server-2/SENTRY-WIRE-BRIEF.md` — Node `@sentry/node`, init-first in `src/server.ts`.
- `../plans/replays-fetcher/SENTRY-WIRE-BRIEF.md` — Node `@sentry/node` CronJob, init in `src/cli.ts` + flush on exit.
- `../plans/replay-parser-2/SENTRY-WIRE-BRIEF.md` — Rust `sentry` crate, guard at the top of `main()`.
