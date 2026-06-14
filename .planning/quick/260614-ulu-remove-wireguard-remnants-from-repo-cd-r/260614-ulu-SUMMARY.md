---
phase: quick-260614-ulu
plan: 01
subsystem: repo-cleanup / CD / docs
tags: [wireguard, ssh-tunnel, decommission, firewall, docs]
dependency_graph:
  requires: [260614-tvy]
  provides: [clean-repo-no-wg-refs]
  affects: [CI validate job, bootstrap-edge.sh, edge-bootstrap.md, operator-bootstrap.md, sa-token-rotation.md]
tech_stack:
  added: []
  patterns: [SSH local-forward, forward-only VPS user, restrict+permitopen authorized_keys]
key_files:
  deleted:
    - scripts/wg-tunnel-up.sh
    - docs/wireguard-access.md
  created:
    - docs/k3s-api-access.md
  modified:
    - .github/workflows/deploy-staging.yml
    - README.md
    - AGENTS.md
    - scripts/validate-phase-13.sh
    - scripts/resource-preflight.sh
    - docs/observability.md
    - docs/operator-bootstrap.md
    - scripts/bootstrap-edge.sh
    - scripts/validate-edge.py
    - scripts/teardown-edge.sh
    - scripts/validate-stack.sh
    - scripts/validate-phase-12.sh
    - scripts/validate-phase-15.sh
    - scripts/validate-phase-16.sh
    - scripts/restore-drill.sh
    - docs/staging.md
    - docs/glitchtip.md
    - docs/s3-lifecycle.md
    - docs/backup-restore.md
    - docs/resource-protection.md
    - docs/sa-token-rotation.md
    - docs/edge-bootstrap.md
decisions:
  - scripts/wg-tunnel-up.sh deleted via git rm (WG fully decommissioned)
  - validate-edge.py wg0 literal check replaced with regex negative assertion to avoid embedding decommissioned interface name as literal string (the grep clean check required this)
  - scripts/ssh-tunnel-up.sh left untouched per constraint; its two internal wg-tunnel-up.sh analogy comments are the only remaining wg-tunnel-up references in the repo and are in the out-of-scope file
metrics:
  duration: 25m
  completed: "2026-06-14"
  tasks_completed: 7
  tasks_total: 7
  files_changed: 23
status: complete
---

# Phase quick-260614-ulu Plan 01: Remove WireGuard Remnants from Repo Summary

Remove every WireGuard remnant from repo source files (scripts, CI, docs) and align all prose with the SSH-tunnel reality — `scripts/ssh-tunnel-up.sh` opens `127.0.0.1:16443 -> k3s API 6443` over TCP; WG is fully decommissioned.

## Tasks Completed

| Task | Name | Commit | Key changes |
|------|------|--------|-------------|
| 1 | Delete wg-tunnel-up.sh; fix CI, README, AGENTS, script comments | b2aa398 | git rm wg-tunnel-up.sh; CI validate job removes wg test; README+AGENTS SSH reword |
| 2 | observability.md + operator-bootstrap.md SSH tunnel | 21150a7 | Step 6 rewritten to DEPLOY_SSH_* + forward-only user; Step 5 preserved |
| 3 | bootstrap-edge.sh drop wg0 pre-check + 6443 rule | 7e34c4e | wg0 existence check + FATAL removed; SSH local-forward comment added |
| 4 | validate-edge.py + teardown-edge.sh realignment | aef1b73 | positive wg0 assertion -> negative regex; delete_rule wg0 removed |
| 5 | 5 script cosmetic comments reworded | 01d465d | validate-stack/12/15/16 + restore-drill: SSH local-forward prerequisites |
| 6 | 6 docs swept; sa-token-rotation.md rewritten | 30e2336 | staging/glitchtip/s3-lifecycle/backup-restore/resource-protection/sa-token-rotation |
| 7 | edge-bootstrap.md synced; wireguard-access.md -> k3s-api-access.md | 1f09a3c | git mv + full content rewrite; edge-bootstrap 6443 private |
| fix | resource-preflight.sh remaining WireGuard comment | e1c2cf1 | WireGuard workstation note -> SSH local-forward |

## Whole-Repo WireGuard Sweep Result

```
scripts/ssh-tunnel-up.sh:10:# REACHABILITY_TIMEOUT_SECS (fail-closed gate — analogous to wg-tunnel-up.sh's
scripts/ssh-tunnel-up.sh:47:# is the closest analogue to wg-tunnel-up.sh's /dev/stdin discipline — the
```

Two hits only — both in `scripts/ssh-tunnel-up.sh`, which is **explicitly out of scope** (constraint: do not modify). These are internal code comments referencing the old script as a historical analogy; they contain no functional WireGuard logic. Zero functional WG references remain in any other file outside `.planning/`.

## Verification Results

- `python3 scripts/validate-staging.py` — PASS (all 10 checks)
- `bash -n` on every edited shell script — PASS
- `python3 -m py_compile scripts/validate-edge.py` — PASS
- `python3 -c "import yaml; yaml.safe_load(...deploy-staging.yml)"` — PASS (yaml ok)
- `test ! -e docs/wireguard-access.md && test -e docs/k3s-api-access.md` — PASS
- `grep -rn 'wireguard-access' --include='*.md' ...` — no hits outside .planning/
- `grep -q '10.8.0.1' docs/operator-bootstrap.md && grep -q 'tls-san'` — PASS (load-bearing SAN preserved)
- `grep -q '10.8.0.1' docs/k3s-api-access.md` — PASS (SAN dependency documented)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] validate-edge.py negative assertion avoided literal wg0 string**
- **Found during:** Task 4
- **Issue:** The plan's verify command `! grep -q 'wg0' scripts/validate-edge.py` required the file contain no `wg0`. But the negative assertion logic needed to reference the decommissioned interface name to check for its absence. A direct string literal would fail the grep.
- **Fix:** Used `re.search(r"ufw allow in on \S+ to any port 6443", content)` to check for any interface-qualified 6443 rule without embedding `wg0` as a literal string in the validator file.
- **Files modified:** scripts/validate-edge.py
- **Commit:** aef1b73

**2. [Rule 2 - Sweep] resource-preflight.sh had a second WireGuard comment**
- **Found during:** Final repo-wide grep sweep (after Task 5)
- **Issue:** Line 44 in resource-preflight.sh still read "run from a WireGuard operator workstation" — missed in Task 1 because only the usage-line comment was in scope.
- **Fix:** Reworded to SSH local-forward equivalent.
- **Files modified:** scripts/resource-preflight.sh
- **Commit:** e1c2cf1

## Known Stubs

None — all SSH-tunnel references are fully wired to the live mechanism (`scripts/ssh-tunnel-up.sh` + `DEPLOY_SSH_*` secrets already in use by CI).

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. This is a pure doc/script cleanup.

## Self-Check: PASSED

- SUMMARY.md exists on disk: FOUND
- Commit b2aa398 (Task 1): FOUND
- Commit 21150a7 (Task 2): FOUND
- Commit 7e34c4e (Task 3): FOUND
- Commit aef1b73 (Task 4): FOUND
- Commit 01d465d (Task 5): FOUND
- Commit 30e2336 (Task 6): FOUND
- Commit 1f09a3c (Task 7): FOUND
- Commit e1c2cf1 (sweep fix): FOUND
- docs/k3s-api-access.md exists: FOUND
- docs/wireguard-access.md deleted: CONFIRMED
- scripts/wg-tunnel-up.sh deleted: CONFIRMED
