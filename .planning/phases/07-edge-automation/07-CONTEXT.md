# Phase 7: Edge Automation - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — smart discuss skipped per autonomous infrastructure detection)

<domain>
## Phase Boundary

The public staging edge — host nginx vhost, TLS renewal, and firewall — is
repo-managed, idempotently re-runnable, and proven reversible in isolation before
it becomes the cutover lever (Phase 11).

In scope (EDGE-01..05):
- Host nginx vhost config for staging, stored in the repo.
- An idempotent, re-runnable bootstrap script that applies the edge config the
  same way on every run.
- Automatic TLS renewal via host `certbot` on a systemd timer, with an
  `nginx -t`-gated reload hook; `certbot renew --dry-run` passes.
- Certificate-renewal failure surfacing (alert or log entry, not silent).
- Host firewall: allow 80/443 inbound; keep `6443` (k3s API) reachable only
  through the WireGuard tunnel.

Out of scope: the actual production-traffic cutover (Phase 11 — the single
reversible nginx-upstream switch). This phase only proves the edge is
repo-managed and reversible in isolation.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — this is a pure
infrastructure phase (host edge config + bootstrap scripting), with no
user-facing behavior. Implementation is guided by the ROADMAP goal, the EDGE-01
through EDGE-05 success criteria, the project anti-features (no cert-manager / no
k8s ingress — the edge is host-nginx; no `--insecure-skip-tls-verify`), and the
existing repo conventions (`#!/usr/bin/env bash`, `set -euo pipefail`, explicit
required-env checks, idempotency, reversibility proven in isolation). Research
during plan-phase will fix the concrete choices (certbot auth mode, firewall
tool, renewal-failure surfacing mechanism, systemd timer cadence).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/wg-tunnel-up.sh`, `scripts/kubeconfig-setup.sh` — Phase 6 bash
  conventions to mirror: handshake/precondition gating, `set -euo pipefail`,
  explicit required-env validation, no secret echoing.
- `docs/wireguard-access.md`, `docs/operator-bootstrap.md` — existing
  operator-runbook style and the WireGuard interface (`10.8.0.1`, tunnel) the
  `6443`-only-via-WG firewall rule must align with.
- `scripts/validate-staging.py` — repo validation harness; edge artifacts should
  be validatable in the same spirit (syntax / shape checks runnable in CI without
  touching the live host).

### Established Patterns
- No host-level nginx / certbot / firewall tooling exists yet — this is the
  repo's first edge layer (greenfield host automation).
- Idempotent re-runnable bootstrap scripts; manifests/configs pinned in-repo;
  one environment per directory; explicit namespace/host boundaries.

### Integration Points
- The k3s API (`6443`) is reached only over the WireGuard tunnel from Phase 6 —
  the firewall rule must preserve that and not expose `6443` publicly.
- The edge nginx upstream is the future Phase 11 cutover lever — config must be
  structured so the upstream switch is a single reversible edit.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase. Refer to EDGE-01..05 and the
ROADMAP success criteria. Live application to the VPS host is out of band for
this environment (VPN-isolated); the phase delivers repo-managed, validatable
artifacts plus an operator runbook, with live apply deferred like the Phase 6
live deploy.

</specifics>

<deferred>
## Deferred Ideas

- Weighted / blue-green nginx cutover with gradual traffic shift (CUT-05) — out
  of scope, deferred to v2.x.
- The actual production cutover (Phase 11).

</deferred>
