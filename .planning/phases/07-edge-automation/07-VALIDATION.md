---
phase: 7
slug: edge-automation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-12
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. This is a
> host-edge infrastructure phase (nginx vhost, certbot, ufw, systemd units) — the
> "test suite" is a set of offline static checks plus operator-only live checks,
> not a unit-test framework.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | none — static/offline validation (shell + `bash -n`, config linters) |
| **Config file** | `scripts/validate-staging.py` (extend), or a new `scripts/validate-edge.py` |
| **Quick run command** | `bash -n scripts/bootstrap-edge.sh scripts/teardown-edge.sh` |
| **Full suite command** | `python3 scripts/validate-edge.py` (offline checks below) |
| **Estimated runtime** | < 10 seconds (offline portion) |

---

## Sampling Rate

- **After every task commit:** Run the quick offline checks for any file touched
  (`bash -n` on shell scripts; structural lint on the nginx vhost; unit-file
  presence/shape checks).
- **End of phase:** Run the full offline validation; record which checks are
  offline-verifiable vs operator-only (live).

---

## Offline vs Operator-Only (critical distinction)

Most edge behavior can only be fully proven on the live Ubuntu 24.04 host. The
plan MUST separate what CI/repo can validate from what is operator-only, and must
NOT claim live success from offline checks.

| Check | Offline (repo/CI) | Operator-only (live host) |
|-------|-------------------|---------------------------|
| Shell syntax (`bash -n`) | ✅ | — |
| nginx vhost structural lint (no full `nginx -t` without nginx + cert files) | ✅ partial | `nginx -t` full ✅ |
| `certbot renew --dry-run` (contacts ACME staging, needs issued cert + host) | ❌ | ✅ |
| systemd unit shape (`[Unit]`/`[Service]`/`[Timer]` keys present) | ✅ | `systemd-analyze verify` ✅ |
| ufw rule presence/ordering | ✅ (lint the apply script) | `ufw status` ✅ |
| Idempotency (two-run, no diff) | ✅ dry-run of file ops | full re-run on host ✅ |
| Reversibility (teardown restores baseline) | ✅ script review | live teardown ✅ |

> The research over-stated that `certbot renew --dry-run` and full `nginx -t` are
> CI-runnable without the host — they are operator-only. Plans must reflect this.

---

## Requirement → Validation Mapping

| Req | What proves it (offline) | What proves it (operator) |
|-----|--------------------------|----------------------------|
| EDGE-01 (vhost in repo) | vhost file exists in repo; structural lint passes; ACME `/.well-known/` + HTTP→HTTPS redirect present | `nginx -t` on host |
| EDGE-02 (auto TLS renewal) | `certbot-renew.timer` + `.service` unit shape valid; deploy-hook script `bash -n` + contains `nginx -t` gate before reload | `certbot renew --dry-run` passes; timer enabled |
| EDGE-03 (failures surfaced) | `OnFailure=` wired to a handler unit that logs to journald; handler script `bash -n` | trigger a forced failure → entry in `journalctl` |
| EDGE-04 (firewall) | apply script grants 80/443 inbound and restricts 6443 to `wg0` only; lint the rule set | `ufw status` shows the split-tunnel rules |
| EDGE-05 (idempotent bootstrap) | bootstrap uses `mkdir -p`/`ln -sf`/guarded `ufw allow`; teardown script exists and reverses each step | two consecutive runs produce no host diff; teardown restores baseline |

---

## Wave 0 Gaps

- No `scripts/validate-edge.py` (or equivalent) exists yet — Wave 0 should add the
  offline validator so later waves can sample against it.
- Greenfield: no existing nginx/certbot/ufw artifacts in the repo to regress
  against; baseline is "nothing installed."
