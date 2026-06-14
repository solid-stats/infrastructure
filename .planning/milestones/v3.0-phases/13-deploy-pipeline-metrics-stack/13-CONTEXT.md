# Phase 13: Deploy Pipeline & Metrics Stack - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

A complete metrics stack — Prometheus, Grafana, kube-state-metrics, node-exporter, and the
PostgreSQL/RabbitMQ exporters — runs on staging via a deploy path independent of runtime CD,
with dashboards rendering live data, validated internally (port-forward / ClusterIP) with no
public edge yet.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

### Hard constraint from Phase 12 live preflight
The staging node is 4 CPU / 7.75Gi RAM with only ~2.5Gi memory available alongside the app
(plus a 2G host swapfile that does NOT back pods). Every observability workload MUST run in
the `monitoring` namespace with `priorityClassName: obs-background` and TIGHT resource
requests/limits, so the scheduler evicts obs before the app under pressure. Deploy via the
operator/obs-ci-deployer path, not the runtime CD glob.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — discuss phase skipped. Refer to ROADMAP phase description and success criteria.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

</deferred>
