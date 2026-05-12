# infrastructure v2 Milestone Brief: Controlled Full Run, Evidence, and Observability

**Created:** 2026-05-12
**Intended command:** `$gsd-new-milestone --auto @gsd-briefs/v2-backend-parity-and-full-run.md`
**Application:** `infrastructure`
**Primary role:** third implementation milestone in the cross-app sequence

## Cross-App Briefs

Read these sibling briefs before drafting the milestone:

- `/home/afgan0r/Projects/SolidGames/server-2/gsd-briefs/v2-backend-parity-and-full-run.md`
- `/home/afgan0r/Projects/SolidGames/replays-fetcher/gsd-briefs/v2-backend-parity-and-full-run.md`
- `/home/afgan0r/Projects/SolidGames/replay-parser-2/gsd-briefs/v2-backend-parity-and-full-run.md`
- `/home/afgan0r/Projects/SolidGames/web/gsd-briefs/v2-backend-parity-and-full-run.md`

## Global Sequence

1. `server-2`: parity foundation, new-stat export, recalculation report, and diff contract.
2. `replays-fetcher`: resumable full-corpus ingest.
3. `infrastructure`: controlled run orchestration, legacy snapshot, evidence storage, and runtime observability.
4. `web`: UI implementation after backend parity and API stability.

`replay-parser-2` changes are conditional and should be driven by `server-2` contract findings.

## Goal

Provide the runtime path and evidence discipline needed to run the full corpus, snapshot legacy `sg_stats`, compare old-vs-new public statistics, and keep production cutover blocked until human review.

This milestone should not decide statistics semantics. It should make the run reproducible and inspectable.

## Source Evidence

- `.planning/STATE.md`
- `docs/full-run.md`
- `docs/diff-readiness.md`
- `docs/observability-plan.md`
- `docs/staging.md`
- `k8s/staging/`
- `scripts/start-controlled-full-run.sh`
- `/home/afgan0r/Projects/SolidGames/server-2/.planning/research/v2-full-run-findings.md`
- `/home/afgan0r/Projects/SolidGames/replays-fetcher/.planning/research/v2-full-run-findings.md`

## Required Decisions Already Made

- The final parity gate uses a full source corpus, not only the current partial staging corpus.
- Legacy trusted public stats are captured from server-side `sg_stats` through an SSH/SCP snapshot.
- App repositories build and publish images; infrastructure owns staging runtime wiring, secrets, pinned image tags, and controlled run orchestration.
- Production traffic cutover remains blocked by default.
- Full observability is valuable, but parity-critical operational visibility must come first.

## Problem To Solve

The v1 infrastructure can deploy staging and start a controlled run, but the actual full run still relied on ad hoc SQL, manual log inspection, and fragile evidence collection. The next milestone needs a reproducible runbook and artifact layout that ties together old snapshot, new backend export, full-run job metadata, and diff output.

## Suggested Milestone Phases

### Phase 1: Runtime Image and Contract Handoff

Goal: staging can run the app versions that contain the new parity/fetcher contracts.

Acceptance criteria:

- Pin image tags for `server-2`, `replays-fetcher`, and `replay-parser-2` versions selected for the full run.
- Preserve the app/infra ownership boundary: app repos publish images, infrastructure deploys runtime wiring.
- Add validation that manifests reference explicit tags and required secrets without exposing secret values.

### Phase 2: Legacy Snapshot Capture

Goal: old public stats are captured reproducibly from the trusted server-side `sg_stats`.

Acceptance criteria:

- Add or document an SSH/SCP snapshot path for required legacy result files.
- Snapshot metadata includes source host, path, timestamp, operator, checksum/manifest, and included game types/surfaces.
- Snapshot output is stored with full-run evidence.
- Snapshot capture does not mutate the legacy server state.

### Phase 3: Controlled Full-Corpus Run

Goal: run the full corpus using resumable fetcher behavior and collect durable evidence.

Acceptance criteria:

- Start full-corpus ingest without enabling recurring schedule.
- Record job names, image tags, run IDs, start/end times, source page range, completion/partial status, retry/resume events, queue depth trend, parser health, server readiness, and S3 prefixes.
- Use `server-2` readiness/recalculation reports rather than ad hoc SQL as the primary completion evidence.

### Phase 4: Old-vs-New Diff Evidence

Goal: diff output is reviewable and tied to exact inputs.

Acceptance criteria:

- Run or document the command sequence that compares the legacy snapshot with the `server-2` export.
- Store diff output with input manifests and full-run metadata.
- Diff output separates strict failures from known `deaths.byTeamkills` differences.
- Diff decision remains `review_required`; no automation approves production cutover.

### Phase 5: Parity-Critical Observability

Goal: operators can see enough runtime health to trust the run before full observability is built.

Acceptance criteria:

- Surface workload logs, queue depth, parser job outcomes, fetcher progress, server recalculation status, and backup status in a repeatable way.
- Keep full Grafana/Loki/GlitchTip rollout aligned with `docs/observability-plan.md`, but do not let it block the core parity run unless the run cannot be diagnosed without it.
- No secret values appear in rendered manifests, logs, dashboards, or committed evidence.

## Dependencies On Other Apps

- Depends on `server-2` exposing full-run reports, backfill/recalculation command, and new-stat export.
- Depends on `replays-fetcher` resumable full-run behavior.
- Depends on `replay-parser-2` worker contract remaining compatible with pinned images.
- Blocks `web` production-quality implementation because data trust and API stability depend on this gate.

## Non-Goals

- Do not change public statistics semantics here.
- Do not move app image build ownership into infrastructure.
- Do not approve production cutover.
- Do not implement the web runtime until backend parity is accepted.

## Recommended Next Command

Run this milestone after `server-2` parity foundation and `replays-fetcher` full-corpus resilience are planned or implemented enough to provide concrete runtime commands.
