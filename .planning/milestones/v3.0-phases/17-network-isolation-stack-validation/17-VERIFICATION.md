---
phase: 17-network-isolation-stack-validation
status: passed
verified: "2026-06-14"
method: live (staging k3s, operator-agent over SSH)
requirements: [NET-01, NET-02, VAL-01]
---

# Phase 17 Verification — PASSED

Goal-backward check against the three success criteria, verified live.

| # | Success criterion | Evidence | Verdict |
|---|-------------------|----------|---------|
| 1 | NetworkPolicy enforcement confirmed with a test policy before any default-deny | netpol-probe deny-all: pod→pod BLOCKED (http=000), KUBE-NWPLCY chains active; probe ns torn down | ✓ PASS (NET-01) |
| 2 | Default-deny + minimal-allow isolate monitoring + error-tracking (incl scrape into solid-stats-staging); all Prometheus targets UP + Grafana datasources healthy after | 11 + 6 policies live; all 7 targets UP; Grafana Prometheus+Loki datasources healthy; app namespace not locked down; both public URLs non-502 | ✓ PASS (NET-02) |
| 3 | Re-runnable validate-stack.sh: Prometheus targets, Grafana datasources, Loki query, forced GlitchTip event — fails loudly | `validate-stack.sh` green BEFORE (--quick) and AFTER (full) the apply; forced GlitchTip event ingested + issue appeared; fail-loud preflight + unknown-flag guards | ✓ PASS (VAL-01) |

## Notes
- Two egress gaps (k8s-API for kube-state-metrics/grafana sidecars; node-exporter host-IP) were
  found by reasoning and fixed before apply, so post-apply passed first try (no rollback).
- A1/A2 finding (host source = cni0 gateway 10.42.0.1, not node public IP) prevented a likely
  edge-breaking ipBlock. Recorded in docs/network-policies.md.

Full evidence: `.planning/phases/17-network-isolation-stack-validation/17-03-SUMMARY.md`,
`docs/network-policies.md`.
