# Phase 3: App CD Boundary - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 3 documents and enforces the staging deployment ownership boundary:
application repositories keep building and publishing images, while this
infrastructure repository owns staging Kubernetes runtime wiring and pinned
image tags.

</domain>

<decisions>
## Implementation Decisions

### App CD Boundary
- Keep image builds in application repositories.
- Keep staging runtime wiring and pinned image tags in this repository.
- Do not remove legacy app deploy workflows automatically in this phase.
- Document which resources app repositories should stop applying in v1 and how
  to update pinned image tags safely here.

### the agent's Discretion
Implementation details are at the agent's discretion as long as they preserve
the gradual handoff and avoid breaking active staging.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `docs/staging.md` already has a deploy model section.
- App image tags are pinned in `35-server-2-deployment.yaml`,
  `40-replay-parser-2.yaml`, and `50-replays-fetcher.yaml`.
- `README.md` already states app repositories own source and image builds.

### Established Patterns
- Documentation is concise and operator-facing.
- Manifests use explicit image SHA tags and `imagePullPolicy: IfNotPresent`.

### Integration Points
- Phase 4 should use this repo's pinned runtime wiring after the backup gate.

</code_context>

<specifics>
## Specific Ideas

Add a handoff matrix and image tag update procedure. Add validation that app
images do not use `latest`.

</specifics>

<deferred>
## Deferred Ideas

Actual removal of legacy app repository workflows remains a coordinated
repository-by-repository handoff outside this phase.

</deferred>
