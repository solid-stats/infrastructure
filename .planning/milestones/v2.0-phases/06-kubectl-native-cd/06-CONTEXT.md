# Phase 6: kubectl-native CD - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

CI deploys staging by running `kubectl` on the runner over a WireGuard tunnel as a
namespace-scoped ServiceAccount, with all SSH transport removed and the
operator-bootstrap boundary documented.

**Success criteria (what must be TRUE):**
1. A push to `master` deploys staging automatically by running `kubectl apply` from
   the runner over a verified WireGuard tunnel, with no SSH/scp to the VPS; a PR runs
   validate plus a server-side dry-run without deploying.
2. CI authenticates as the `solid-stats-staging`-scoped ServiceAccount using a
   long-lived token Secret (not admin kubeconfig, not an SSH key), and
   `kubectl auth whoami` confirms it is not `system:anonymous`.
3. The deploy job aborts before any `kubectl` if the WireGuard handshake has not
   completed, and `6443` is reachable only through the tunnel.
4. The ServiceAccount can apply and `rollout status` every staging workload kind
   within the namespace and nothing cluster-scoped; the namespace and CI RBAC are
   bootstrapped once by the operator via a documented runbook, and CI never creates
   the namespace.
5. All `CD_SSH_*` secrets and SSH code paths are removed, only one deploy runs at a
   time, and an SA-token rotation runbook (owner, cadence, paired with WG key
   rotation) is documented.

**Requirements:** CD-01, CD-02, CD-03, CD-04, CD-05, CD-06, CD-07, CD-08, CD-09

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per
user setting. Use ROADMAP phase goal, success criteria, and codebase conventions to
guide decisions.

### Carried design risks (from STATE.md Blockers/Concerns)
- WireGuard handshake from the ephemeral runner must be gated before any `kubectl`;
  51820/udp outbound from GitHub-hosted runners is assumed and must be validated early.
- k8s ≥1.24 SA has no auto-token Secret — the `kubernetes.io/service-account-token`
  Secret must be created explicitly; serving cert must carry `10.8.0.1` in its SANs.
- RBAC must be namespace-scoped yet still cover `rollout status`; verify with
  `auth can-i --list` and an SA-impersonated dry-run.
- Namespace + CI RBAC are operator-bootstrapped once (a namespaced Role cannot create
  the cluster-scoped Namespace); CI never creates the namespace.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — discuss phase skipped. Refer to ROADMAP phase description
and success criteria.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. (Note: CD-10 PR dry-run diff comment is deferred to v2.x
per STATE.md.)

</deferred>
