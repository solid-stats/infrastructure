---
phase: 14-public-edge-grafana-tls
status: passed
verified: "2026-06-14"
method: live (staging edge, re-confirmed during the v3.0 audit)
requirements: [EDGE-01, EDGE-02, EDGE-03, MET-07]
note: Backfilled during the v3.0 milestone audit — the phase shipped live in Phase 14 (see 14-04-SUMMARY.md); this records the verification artifact.
---

# Phase 14 Verification — PASSED

| # | Success criterion | Evidence | Verdict |
|---|-------------------|----------|---------|
| 1 | DNS A records for grafana. + errors. resolve to the staging host | `dig +short grafana.solid-stats.ru` / `errors.solid-stats.ru` → 89.223.124.200 (apex hosts; operator created the records) | ✓ EDGE-01 |
| 2 | Independent host-nginx obs-edge bootstrap serves an HTTP-only vhost then a certbot TLS cert, proxying Grafana over a valid cert | `bootstrap-obs-edge.sh` adopt-reconcile; grafana vhost proxies the in-cluster ClusterIP; re-confirmed this session | ✓ EDGE-02 |
| 3 | Valid certbot TLS for both public hosts | LE cert lineages for grafana.solid-stats.ru (live) + errors.solid-stats.ru (issued in 14, reused in 16) | ✓ EDGE-03 |
| 4 | Operator reaches Grafana at the public TLS URL behind local-user auth, dashboards render live data | `curl -I https://grafana.solid-stats.ru/` → HTTP/2 302 (login redirect, non-502) this session; Grafana datasource + 4 dashboards healthy (validate-stack.sh) | ✓ MET-07 |

Live re-confirmation came for free during the Phase 17 post-apply validation: grafana.solid-stats.ru
returned 302 through the NetworkPolicy layer and the Grafana Prometheus/Loki datasources were healthy.

Evidence: `14-04-SUMMARY.md`, `docs/obs-edge-bootstrap.md`, `docs/network-policies.md` (before/after table).
