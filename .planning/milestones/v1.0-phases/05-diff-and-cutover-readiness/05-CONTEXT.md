# Phase 5: Diff and Cutover Readiness - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 5 defines how operators compare old and new statistics after a full run
and keeps production cutover explicitly blocked until review is clean enough.

</domain>

<decisions>
## Implementation Decisions

### Diff Readiness
- Define comparison inputs, execution path, and output shape.
- Separate strict failures from allowlisted known differences.
- Treat diff output as review evidence, not automatic production approval.
- Keep production cutover blocked in docs.

### the agent's Discretion
Implementation details are at the agent's discretion; no production traffic
changes are allowed.

</decisions>

<code_context>
## Existing Code Insights

No diff script exists yet. Documentation can define the contract for app-side
or operator-provided diff tooling while keeping cutover blocked.

</code_context>

<specifics>
## Specific Ideas

Create `docs/diff-readiness.md` with input/output contract and allowlist format.

</specifics>

<deferred>
## Deferred Ideas

Actual production cutover remains v2.

</deferred>
