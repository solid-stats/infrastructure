# Phase 4: Controlled Full Run - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 creates the explicit, monitored manual full-run path for
`replays-fetcher` after the backup gate is verified. It must not enable the
recurring CronJob schedule.

</domain>

<decisions>
## Implementation Decisions

### Controlled Full Run
- Keep `replays-fetcher` deployed with `suspend: true`.
- Provide a manual Job command/script from the CronJob for controlled ingest.
- Require `docs/backup-gate.md` to show `Status: verified` before starting.
- Provide monitoring commands for queue depth, parser pods, server readiness,
  and S3 object writes.

### the agent's Discretion
Implementation details are at the agent's discretion, but the recurring fetcher
schedule must remain suspended.

</decisions>

<code_context>
## Existing Code Insights

- `k8s/staging/50-replays-fetcher.yaml` defines the suspended CronJob.
- `docs/backup-gate.md` records the latest verified backup.
- `docs/staging.md` documents rollout verification and suspended fetcher
  behavior.

</code_context>

<specifics>
## Specific Ideas

Add a script to start one controlled Job from the suspended CronJob, plus a
monitoring runbook.

</specifics>

<deferred>
## Deferred Ideas

Recurring schedule enablement stays out of Phase 4 unless explicitly approved
after a clean manual run.

</deferred>
