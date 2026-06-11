---
phase: "04"
status: human_needed
verified_at: 2026-05-10
---

# Phase 04 Verification - Controlled Full Run

## Status

status: human_needed

The controlled full-run command and monitoring runbook are implemented and
locally verified. The actual ingest Job was not started automatically because
it intentionally writes replay data and should be an explicit operator action.

## Evidence

- `python3 scripts/validate-staging.py` passed.
- `bash -n scripts/start-controlled-full-run.sh` passed.
- `scripts/start-controlled-full-run.sh` refuses to run unless
  `docs/backup-gate.md` contains `Status: verified`.
- `scripts/start-controlled-full-run.sh` creates one Job from
  `cronjob/replays-fetcher` and does not patch `spec.suspend`.
- `docs/full-run.md` documents start, checkpoints, RabbitMQ queue monitoring,
  parser monitoring, server readiness, fetcher logs, and S3 object checks.

## Human Verification Required

Run the controlled ingest only when ready:

```bash
K8S_NAMESPACE=solid-stats-staging ./scripts/start-controlled-full-run.sh
```

Then record the Job name, queue trend, parser health, server readiness, and S3
object writes.
