# Phase 17: Network Isolation & Stack Validation - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) + live-stack constraints from the autonomous operator

<domain>
## Phase Boundary

NetworkPolicies isolate the observability namespaces (`monitoring`, `error-tracking`) without
breaking validated scraping or datasources, and a single re-runnable script proves the whole
stack healthy on any fresh staging deploy.

Requirements: NET-01 (confirm enforcement first), NET-02 (default-deny + minimal-allow), VAL-01
(re-runnable full-stack validation script).

In scope: NetworkPolicies for `monitoring` + `error-tracking` only; one `validate-stack.sh`.
Out of scope: default-deny on the app namespace `solid-stats-staging` (would risk breaking
server-2 → postgres / rabbitmq app traffic — only an allow-scrape path is in scope there).
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion (autonomous, carte-blanche)
Implementation choices are at Claude's discretion, guided by the live stack as it actually runs
(Phases 12–16 all deployed) and the constraints below.

### Live constraints that MUST be honored (discovered across Phases 13–16)
1. **k3s enforces NetworkPolicy** via the bundled kube-router netpol controller (flannel CNI).
   NET-01 still requires an empirical enforcement check (apply a deny + prove a blocked
   connection) BEFORE any default-deny is relied on.
2. **The public edge is host nginx on the NODE**, proxying to in-cluster ClusterIPs:
   `grafana.solid-stats.ru` → grafana (monitoring, 3000) and `errors.solid-stats.ru` →
   glitchtip-web (error-tracking, 8000). A default-deny *ingress* on those namespaces MUST keep
   an allow rule for the edge/host source, or both public URLs break. Confirm how host-node
   traffic is seen by kube-router (host IP vs an ipBlock for the node/pod CIDR) during NET-01.
3. **Prometheus (monitoring) scrapes cross-namespace into `solid-stats-staging`**:
   rabbitmq `:15692` and postgres `:5432` (via postgres-exporter, which connects out to
   postgres). Default-deny *egress* on monitoring needs an allow-prometheus-scrape egress rule
   to `solid-stats-staging` for those ports. Do NOT add a default-deny ingress policy onto
   `solid-stats-staging` pods (would break app↔postgres/rabbitmq). The "allow-prometheus-scrape
   into solid-stats-staging" requirement = the monitoring-side egress allow (+ DNS), not an app
   namespace lockdown.
4. **DNS egress** (to kube-system kube-dns/coredns :53 udp/tcp) must be allowed in every
   default-deny egress policy, or every in-cluster lookup fails.
5. **Intra-namespace flows to preserve**: monitoring — prometheus↔grafana, prometheus scrapes
   kube-state-metrics / node-exporter / loki / alloy, alloy→loki, grafana→prometheus+loki.
   error-tracking — web↔glitchtip-postgres, worker↔glitchtip-postgres.
6. **node-exporter** runs with hostNetwork/hostPort — its scrape path is host-level; verify the
   netpol does not silently drop it.
7. GlitchTip does NOT expose prometheus metrics (ENABLE_OBSERVABILITY_API off) → no cross-ns
   scrape into error-tracking is needed; keep error-tracking ingress to the edge + intra-ns only.

### Validation script (VAL-01)
One re-runnable `scripts/validate-stack.sh` that fails loudly, composing the existing per-phase
harnesses rather than duplicating them: Prometheus target health (all UP), Grafana datasource
health (Prometheus + Loki), a Loki LogQL query returning recent server-2 lines, and a forced
GlitchTip test event (reuse test-glitchtip-ingest.sh). Must run green BOTH before and after the
NetworkPolicies are applied (proves isolation didn't break anything).
</decisions>

<code_context>
## Existing Code Insights

- Obs manifests live in `k8s/observability/*.yaml`; cluster RBAC/bootstrap in `k8s/staging/01-obs-rbac.yaml`,
  `03-alloy-rbac.yaml`. `validate-obs-manifests.py` is the static gate (namespace ∈ {monitoring,
  error-tracking}, obs-background priority, no secret values, no ClusterRole in the obs dir).
- Per-phase live harnesses already exist: `validate-phase-13.sh` (metrics), `validate-phase-15.sh`
  (logs), `validate-phase-16.sh` + `test-glitchtip-ingest.sh` (errors). VAL-01 should orchestrate these.
- Namespaces live: monitoring, error-tracking, solid-stats-staging, kube-system, cert-manager.
- Deploy path: `helm template` → committed manifests → `deploy-observability.yml` (obs-ci-deployer,
  namespace-scoped). NetworkPolicies are namespaced resources → fit the obs-ci-deployer RBAC if the
  Role grants networkpolicies; confirm/extend RBAC (operator-bootstrap 01-obs-rbac.yaml) as in prior phases.
- Live apply is done by the autonomous operator over SSH (root@89.223.124.200) as in Phases 13–16.
</code_context>

<specifics>
## Specific Ideas

- NET-01 enforcement proof: a throwaway deny-all + a curl from a test pod that must fail, then cleanup.
- Default-deny built as: one default-deny-ingress + default-deny-egress per obs namespace, then
  additive allow policies (dns, intra-ns, edge-ingress, scrape-egress).
- Keep NetworkPolicies in `k8s/observability/` (namespaced, CI-deployable) and out of the app namespace.
</specifics>

<deferred>
## Deferred Ideas

- Default-deny / micro-segmentation of the app namespace `solid-stats-staging` (out of v3.0 scope —
  app traffic isolation is a separate hardening effort).
- mTLS / service mesh (explicitly anti-feature per milestone scoping).
</deferred>
