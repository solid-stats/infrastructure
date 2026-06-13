---
phase: "07-edge-automation"
plan: 3
subsystem: edge
tags: [bootstrap, teardown, ufw, nginx, certbot, idempotent, reversible, firewall, edge-automation]
dependency_graph:
  requires:
    - scripts/validate-edge.py (07-01)
    - config/nginx/sites-available/stats-staging-solid-stats.conf (07-01)
    - config/systemd/certbot.service.d/onfailure.conf (07-02)
    - config/systemd/certbot-renew-failure.service (07-02)
    - config/systemd/certbot-deploy-hook.sh (07-02)
  provides:
    - scripts/bootstrap-edge.sh
    - scripts/teardown-edge.sh
  affects:
    - docs/edge-bootstrap.md (07-04, referenced in bootstrap echo)
tech_stack:
  added:
    - bash adopt/reconcile bootstrap script (bootstrap-edge.sh)
    - bash teardown/reversal script (teardown-edge.sh)
  patterns:
    - Adopt-not-build: backup-before-overwrite + idempotent reconcile
    - nginx -t fail-closed gate (never reload invalid config)
    - ufw split-tunnel: interface-qualified 6443 only on wg0
    - exit 64 for missing required env vars (Phase 6 convention)
key_files:
  created:
    - scripts/bootstrap-edge.sh
    - scripts/teardown-edge.sh
  modified: []
decisions:
  - "D-6: skip cert issuance if /etc/letsencrypt/live/$DOMAIN lineage exists — checked in Section 4"
  - "D-7: ufw 6443 only on wg0 interface — wg0 pre-check exits 1 with FATAL if interface absent"
  - "D-8: backup live vhost to .bak before overwrite; teardown restores .bak exactly"
  - "D-9: SKIP_UFW=1 override available for environments without ufw (CI offline validation)"
  - "EDGE-04: firewall 80/443 public + 6443 wg0-only implemented in bootstrap Section 7"
  - "EDGE-05: idempotency (mkdir -p, ln -sf, cp overwrite, lineage guard) + reversibility (.bak restore in teardown)"
metrics:
  duration: "117s"
  completed: "2026-06-13"
  tasks: 2
  files: 2
status: complete
---

# Phase 07 Plan 03: Bootstrap and Teardown Scripts Summary

**One-liner:** Idempotent adopt-reconcile bootstrap (backup live vhost → install repo vhost → nginx -t gate → certbot hook/drop-in → ufw split-tunnel wg0-only 6443) + reversible teardown restoring .bak original (EDGE-04, EDGE-05, D-6..D-9).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Idempotent adopt-reconcile bootstrap — scripts/bootstrap-edge.sh | 09f7f28 | scripts/bootstrap-edge.sh |
| 2 | Edge teardown — scripts/teardown-edge.sh | d09d25e | scripts/teardown-edge.sh |

## What Was Built

### scripts/bootstrap-edge.sh

Eight-section idempotent adopt/reconcile script mirroring Phase 6 conventions (`set -euo pipefail`, `exit 64` for missing `ADMIN_EMAIL`, optional vars via `: "${VAR:=default}"`):

1. **Package check** — `apt-get install -y certbot nginx ufw curl openssl` (idempotent)
2. **Webroot directory** — `mkdir -p $WEBROOT_PATH/.well-known/acme-challenge`
3. **Adopt/reconcile nginx vhost (D-8)** — backs up live vhost to `.bak` (only if `.bak` absent); `cp` repo vhost (idempotent overwrite); `ln -sf` into sites-enabled; `nginx -t` gate — on failure restores `.bak` and runs a second `nginx -t` before any reload (never reloads on unvalidated config)
4. **TLS certificate (D-6)** — checks `/etc/letsencrypt/live/$DOMAIN` existence; skips `certbot certonly` if lineage present; `SKIP_CERTBOT=1` override available
5. **Deploy hook (D-4)** — `mkdir -p`; `cp` + `chmod +x` to `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`
6. **systemd OnFailure drop-in (D-5)** — `mkdir -p certbot.service.d`; `cp` onfailure.conf + certbot-renew-failure.service; `systemctl daemon-reload` error-checked with `|| { ... exit 1; }`
7. **ufw firewall rules (D-7, EDGE-04)** — guarded by `SKIP_UFW=1`; applies `allow 22/80/443` (with `|| true` for idempotency); pre-checks `ip link show wg0` before `ufw allow in on wg0 to any port 6443/tcp` — exits 1 with FATAL if wg0 absent; `ufw --force enable` error-checked
8. **Operator verification reminder** — prints 5 manual steps to run on the live host

### scripts/teardown-edge.sh

Four-section teardown that reverses every bootstrap step in reverse order:

1. **Remove systemd drop-in** — `systemctl stop certbot-renew-failure.service || true`; `rm -f` onfailure.conf + failure service; `rmdir` drop-in dir if empty; `systemctl daemon-reload`
2. **Remove deploy hook** — `rm -f /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`
3. **Restore original nginx vhost (D-8)** — `cp $BAK_VHOST $VHOST_CONF` then `rm -f $BAK_VHOST`; if no `.bak`, removes symlink + vhost file; re-creates symlink; `nginx -t` gate before reload (warns and skips reload if invalid)
4. **Remove ufw edge rules** — `ufw delete allow 80/tcp`, `ufw delete allow 443/tcp`, `ufw delete allow in on wg0 to any port 6443/tcp`; never removes `22/tcp`; never runs `ufw disable`

## Verification Results

All checks passed:

- `bash -n scripts/bootstrap-edge.sh` → exit 0 (syntax OK)
- `bash -n scripts/teardown-edge.sh` → exit 0 (syntax OK)
- `grep "set -euo pipefail"` both scripts → present
- `grep "exit 64"` bootstrap → present (ADMIN_EMAIL guard)
- `grep "ufw allow in on wg0 to any port 6443"` bootstrap → present (exact literal per D-7)
- `grep "ufw allow 80"` + `grep "ufw allow 443"` bootstrap → present
- `grep "ln -sf"` + `grep "mkdir -p"` bootstrap → present
- `grep "\.bak"` both scripts → present (backup and restore logic)
- `grep "letsencrypt/live"` bootstrap → present (lineage guard)
- `grep "certbot.service.d"` both scripts → present
- `grep "ufw delete"` teardown → present (3 rules)
- teardown does NOT contain `ufw disable` or `delete allow 22`
- `python3 scripts/validate-edge.py` → all 5 checks OK:
  - `ok: nginx vhost structure`
  - `ok: shell scripts syntax and markers`
  - `ok: systemd units shape`
  - `ok: bootstrap idempotency markers`
  - `ok: teardown script markers`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — both scripts are complete. They reference host-runtime paths (`/etc/nginx/`, `/etc/letsencrypt/`, `systemctl`, `ufw`, `ip`) which are host dependencies, not stubs.

## Threat Surface Scan

No new threat surface beyond the plan's `<threat_model>`:

- T-7-03-01 (k3s API publicly exposed): mitigated — `ufw allow in on wg0 to any port 6443/tcp` exact literal; `ip link show wg0` pre-check exits 1 if wg0 absent; no `|| true` masking on 6443 rule
- T-7-03-02 (operator lockout via ufw): mitigated — `ufw allow 22/tcp` applied first; teardown never removes 22/tcp; `ufw disable` never called
- T-7-03-03 (live vhost disruption): mitigated — `.bak` backup before overwrite; nginx -t fail-closed gate with `.bak` restore + second nginx -t before any reload
- T-7-03-04 (cert re-issuance on re-run): mitigated — `/etc/letsencrypt/live/$DOMAIN` lineage check in Section 4
- T-7-03-05 (relay/auth vhosts affected): mitigated — bootstrap only operates on `stats-staging-solid-stats.conf`; no glob/wildcard
- T-7-03-06 (firewall misorder → lockout): mitigated — defaults set first, `allow 22` first specific rule, `--force enable` last; `set -euo pipefail` halts on any error
- T-7-03-SC (apt installs): accepted — Ubuntu 24.04 standard packages per Package Legitimacy Audit in 07-RESEARCH.md

## Self-Check: PASSED

- FOUND: scripts/bootstrap-edge.sh
- FOUND: scripts/teardown-edge.sh
- FOUND: commit 09f7f28 (Task 1)
- FOUND: commit d09d25e (Task 2)
