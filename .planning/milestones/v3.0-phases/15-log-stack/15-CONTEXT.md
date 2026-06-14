# Phase 15: Log Stack - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Cluster logs are collected conservatively into Loki with bounded retention and queryable in
Grafana as a second datasource, without leaking request bodies or secrets.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Reuse the Phase 13 obs pipeline
Loki + Alloy are helm-rendered (no operator/CRDs) into `k8s/observability/`, committed, and
applied via the same `deploy-observability.yml` path + `obs-ci-deployer`. Both run in the
`monitoring` namespace with `priorityClassName: obs-background` and TIGHT requests/limits.
Grafana gets Loki added as a second provisioned datasource (extend the Phase 13 grafana values/
rendered manifest). Extend `validate-phase-13.sh` style with a `validate-phase-15.sh`.

### Node headroom (live, 2026-06-14)
4 CPU / 7.75Gi; ~2.8Gi available, swap ~0.6Gi used, disk 25G free. Loki (monolithic/filesystem)
+ Alloy DaemonSet must be tight — target Loki ~128–256Mi, Alloy ~64–128Mi. Loki PVC sized for
~7-day retention against the 25G free disk (e.g. 8–10Gi), compactor-driven retention.

### Conservative collection (LOG-02 security)
Alloy collects only namespace/pod/container/app/job labels — NO request bodies, NO secrets.
Drop/scrub high-cardinality or sensitive content at the Alloy pipeline. Loki monolithic mode,
filesystem storage, single replica (single-node staging).

</decisions>

<code_context>
## Existing Code Insights

Mirror Phase 13: k8s/observability/ rendered manifests, values/, validate-obs-manifests.py static
gate, render-then-apply. Grafana datasource provisioning already exists (Prometheus) — add Loki.

</code_context>

<specifics>
## Specific Ideas

LogQL acceptance: a query in Grafana Explore returns recent `server-2` log lines (LOG-03).
Compactor proof: `loki_compactor_runs_total > 0`. Alloy proof: `alloy_logs_entries_total > 0`.

</specifics>

<deferred>
## Deferred Ideas

None — GlitchTip log ingestion is explicitly out of scope (errors only; logs live in Loki).

</deferred>
