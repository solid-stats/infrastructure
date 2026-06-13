---
phase: "07-edge-automation"
plan: 2
subsystem: edge
tags: [certbot, systemd, drop-in, deploy-hook, tls-renewal, failure-surfacing, nginx]
dependency_graph:
  requires:
    - scripts/validate-edge.py (07-01)
  provides:
    - config/systemd/certbot.service.d/onfailure.conf
    - config/systemd/certbot-renew-failure.service
    - config/systemd/certbot-deploy-hook.sh
  affects:
    - scripts/bootstrap-edge.sh (07-03, installs these artifacts)
tech_stack:
  added:
    - systemd drop-in unit (certbot.service.d/onfailure.conf)
    - systemd oneshot service (certbot-renew-failure.service)
    - bash deploy-hook script (certbot-deploy-hook.sh)
  patterns:
    - systemd OnFailure= drop-in extending stock unit without replacing it
    - fail-closed nginx -t gate before systemctl reload
    - logger -p user.crit for journald failure surfacing
key_files:
  created:
    - config/systemd/certbot.service.d/onfailure.conf
    - config/systemd/certbot-renew-failure.service
    - config/systemd/certbot-deploy-hook.sh
  modified: []
decisions:
  - "D-4: no custom certbot-renew.timer/service created — drop-in extends stock certbot.service only"
  - "D-5: OnFailure= wired via drop-in to oneshot logger -p user.crit failure handler"
  - "EDGE-02: deploy-hook exits 1 on nginx -t failure, blocking reload; certbot marks hook failed"
  - "EDGE-03: OnFailure= in onfailure.conf drop-in routes failures to certbot-renew-failure.service"
metrics:
  duration: "120s"
  completed: "2026-06-13"
  tasks: 2
  files: 3
status: complete
---

# Phase 07 Plan 02: Certbot Systemd Drop-in, Failure Handler, and Deploy Hook Summary

**One-liner:** systemd OnFailure= drop-in extending stock certbot.service + journald failure handler (logger -p user.crit) + nginx -t-gated deploy hook for post-renewal reload (EDGE-02, EDGE-03, D-4, D-5).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | OnFailure drop-in + failure handler (EDGE-03, D-5) | af2048a | config/systemd/certbot.service.d/onfailure.conf, config/systemd/certbot-renew-failure.service |
| 2 | certbot deploy-hook with nginx -t gate (EDGE-02, D-4) | d74c90e | config/systemd/certbot-deploy-hook.sh |

## What Was Built

### config/systemd/certbot.service.d/onfailure.conf
Systemd drop-in for the stock `certbot.service` (Ubuntu 24.04 apt-managed). The drop-in directory `certbot.service.d` is the systemd convention for extending the unit named `certbot.service` without replacing it. Contains only a `[Unit]` section with `OnFailure=certbot-renew-failure.service`. No `ExecStart`, no timer override — the stock certbot.timer runs twice daily unchanged (D-4).

Installed to `/etc/systemd/system/certbot.service.d/onfailure.conf` by bootstrap-edge.sh (Plan 03).

### config/systemd/certbot-renew-failure.service
Oneshot failure handler activated by `OnFailure=` in the drop-in above. Calls `logger -t certbot-alert -p user.crit` to write a crit-priority syslog entry to journald. Operator reads alerts via `journalctl -t certbot-alert --since today` or `journalctl -p crit --since today`. No external monitoring, no webhook, no email — journald is sufficient for a solo operator (D-5). The message text directs to `journalctl -u certbot.service -n 20` for the actual renewal logs.

Installed to `/etc/systemd/system/certbot-renew-failure.service` by bootstrap-edge.sh.

### config/systemd/certbot-deploy-hook.sh
Bash deploy hook installed by bootstrap-edge.sh to `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`. The stock certbot.timer calls all scripts in that directory after each successful renewal. The hook:
1. Logs a timestamped entry with `$RENEWED_DOMAINS`
2. Runs `nginx -t` — if it fails, exits 1 immediately (fail-closed: new cert installed but nginx NOT reloaded; operator must fix config manually)
3. Runs `systemctl reload nginx` only after nginx -t passes
4. Logs success

If the hook exits non-zero, certbot marks the deploy hook as failed, which propagates through the `OnFailure=` drop-in from Task 1 and fires the journald alert. The repo file does not need execute permission — bootstrap-edge.sh runs `chmod +x` on the host copy.

## Verification Results

- `bash -n config/systemd/certbot-deploy-hook.sh` → exit 0 (syntax OK)
- `grep "nginx -t"` → present at line 16
- `grep "systemctl reload nginx"` → present at line 25; line 16 < line 25 (ORDER OK)
- `grep "set -euo pipefail"` → present
- `grep "OnFailure=certbot-renew-failure.service" onfailure.conf` → present
- `grep "[Unit]" onfailure.conf` → present
- `grep "logger" certbot-renew-failure.service` → present
- `grep "user.crit" certbot-renew-failure.service` → present
- `grep "[Service]" certbot-renew-failure.service` → present
- validate_systemd_units() inline run → `ok: systemd units shape`
- Full `python3 scripts/validate-edge.py` fails at `scripts/bootstrap-edge.sh missing` (expected — Plan 03 artifact, not in scope of this plan)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all three files are complete and self-contained. They reference host paths (`/etc/letsencrypt/`, `systemctl`, `nginx`) that are host-runtime dependencies, not stubs.

## Threat Surface Scan

No new threat surface beyond the plan's `<threat_model>`:

- T-7-02-01 (silent renewal failure): mitigated — OnFailure= drop-in + logger -p user.crit
- T-7-02-02 (nginx reload on broken config): mitigated — certbot-deploy-hook.sh exits 1 on nginx -t failure
- T-7-02-03 (custom timer conflicts): mitigated — no custom timer/service created; drop-in only
- T-7-02-04 (deploy-hook runs as root): accepted — certbot requirement; hook only calls nginx -t and systemctl reload nginx
- T-7-02-05 (drop-in dir name mismatch): mitigated — dir is `certbot.service.d`, matching stock unit `certbot.service`

## Self-Check: PASSED

- FOUND: config/systemd/certbot.service.d/onfailure.conf
- FOUND: config/systemd/certbot-renew-failure.service
- FOUND: config/systemd/certbot-deploy-hook.sh
- FOUND: commit af2048a (Task 1)
- FOUND: commit d74c90e (Task 2)
