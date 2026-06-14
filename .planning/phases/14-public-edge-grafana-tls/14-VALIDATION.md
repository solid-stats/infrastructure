---
phase: 14
slug: public-edge-grafana-tls
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-14
---

# Phase 14 — Validation Strategy

> Edge phase: validation is shell/curl/openssl checks against the host nginx + certbot.
> The live checks are DNS-gated (operator must create the two A records first).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Bash + dig + curl + openssl (host-edge checks); mirror `scripts/validate-edge.py` |
| **Static** | `bash -n bootstrap-obs-edge.sh`; nginx `-t` config test |
| **Live suite** | `scripts/validate-obs-edge.py` (created Wave 0; DNS-gated) |

---

## Sampling Rate

- **After every task commit:** `bash -n` script syntax + nginx config-template lint
- **After operator bootstrap (DNS live):** `python3 scripts/validate-obs-edge.py`
- **Phase gate:** Grafana reachable over HTTPS behind login (operator confirms once DNS+cert exist)

---

## Per-Requirement Verification Map

| Req | Behavior | Type | Check | Gate |
|-----|----------|------|-------|------|
| EDGE-01 | both A records resolve to 89.223.124.200 | live | `dig +short grafana.solid-stats.ru` / `errors.…` == host IP | OPERATOR (DNS) |
| EDGE-02 | obs-edge bootstrap serves HTTP vhost then TLS, proxies Grafana ClusterIP | static+live | `bootstrap-obs-edge.sh` exists, idempotent adopt-reconcile; `nginx -t` passes; vhost proxies grafana ClusterIP:80 | author=auto, run=OPERATOR |
| EDGE-03 | certbot per-domain cert issued + served | live | `openssl s_client -connect grafana.…:443` shows valid LE cert; `certbot certonly -d` (never full-renew) | OPERATOR (needs DNS) |
| MET-07 | Grafana reachable at public HTTPS URL behind local-user auth | live | `curl -sI https://grafana.solid-stats.ru` → 200/302 to Grafana login | OPERATOR |

---

## Wave 0 Requirements

- [ ] `scripts/bootstrap-obs-edge.sh` — env-parameterized (DOMAIN, UPSTREAM) mirror of bootstrap-edge.sh: HTTP-first vhost → `certbot certonly -d <domain>` → TLS vhost; idempotent; resolves Grafana ClusterIP at runtime
- [ ] `scripts/validate-obs-edge.py` — DNS resolve + HTTP→HTTPS + cert validity + Grafana login over TLS (mirror validate-edge.py)
- [ ] `docs/obs-edge.md` (or extend docs/edge-bootstrap.md) — operator runbook incl. the DNS prerequisite + per-domain certbot caveat
- [ ] errors. placeholder TLS vhost (503 until Phase 16 wires the upstream)

---

## Manual / Operator-Gated Verifications

| Behavior | Req | Why operator | Instructions |
|----------|-----|--------------|--------------|
| Create the two DNS A records | EDGE-01 | registrar/DNS-provider controlled; agent has no DNS API | add A `grafana.stats-staging` + `errors.stats-staging` → 89.223.124.200 |
| Run bootstrap-obs-edge.sh live + certbot | EDGE-02/03 | issues real Let's Encrypt certs; needs DNS resolving | `DOMAIN=grafana.solid-stats.ru UPSTREAM=<grafana-clusterip>:80 bash scripts/bootstrap-obs-edge.sh` (then errors.) |
| Confirm Grafana over HTTPS behind login | MET-07 | visual / post-DNS | open https://grafana.solid-stats.ru |

---

## Validation Sign-Off

- [ ] bootstrap-obs-edge.sh + validator + docs authored, syntax-clean (autonomous)
- [ ] Live cert + public-URL checks pass once operator creates DNS (deferred, documented)
- [ ] `nyquist_compliant: true` once authoring lands (live checks are operator-gated by design)

**Approval:** pending
