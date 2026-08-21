---
phase: 21-restore-cutover-recovery
plan: 04
subsystem: memory-recovery
tags:
  - mempalace
  - qdrant
  - backup
  - recovery
  - kubernetes
  - s3
requires:
  - phase: 21-restore-cutover-recovery
    plan: 03
    provides: Reversible MCP cutover accepted at CLIENT_ADDED
provides:
  - Behavior-proven process restart and single VPS reboot recovery
  - Least-privilege recurring backup with exact writer quiescence and restoration
  - Timeweb S3 upload, download, checksum, and behavior-oracle proof
  - Exercised rollback and exact forward replay
  - Active guarded backup schedule and predecessor-bound cutover seal
affects:
  - Phase 22 archival planning
actuals:
  tasks: 3
  commits: 52
  tests: 205
tech-stack:
  added: []
  patterns:
    - Native-sidecar writer restoration across multi-container backup stages
    - Host systemd guard that suspends the schedule on incomplete Job evidence
    - Exact remote result schemas with monotonic recovery ordinals
    - Transactional source, live schedule, and client activation compensation
key-files:
  created:
    - k8s/memory/05-rbac.yaml
    - scripts/collect-phase-21-recovery-evidence.py
    - scripts/guard-solidstats-memory-backup.sh
    - scripts/suspend-solidstats-memory-backup.sh
    - scripts/solidstats-memory-backup-guard.service
    - scripts/solidstats-memory-backup-guard.timer
    - scripts/render-solidstats-memory-backup-activation.py
    - .planning/phases/21-restore-cutover-recovery/21-RECOVERY-EVIDENCE.json
    - .planning/phases/21-restore-cutover-recovery/21-CUTOVER-SEAL.json
  modified:
    - k8s/memory/30-network-policy.yaml
    - k8s/memory/40-backup.yaml
    - scripts/configure-solidstats-memory-client.py
    - scripts/cutover-solidstats-memory.sh
    - scripts/operate-solidstats-memory-cutover-remote.sh
    - scripts/validate-memory-manifests.py
    - scripts/validate-phase-21.py
    - tests/test-memory-cutover-contract.py
    - tests/test-memory-runtime-contract.py
key-decisions:
  - Keep AWS CLI containers limited to supported S3 transfer commands and perform package work in the approved MemPalace image.
  - Treat the retained legacy runtime as intentionally read-only under its peer-writer freeze lock and verify that exact behavior in-container.
  - Preserve unrelated Codex configuration bytes during rollback and retirement instead of accepting CLI-wide TOML reserialization.
  - Promote the checked-in and rendered CronJob to active only inside the final compensatable activation transaction.
patterns-established:
  - Stateful remote operations retain pending and complete records with exact run, config, sequence, and result bindings.
  - Live negative controls use fresh pods so stale connection state cannot create an authorization or NetworkPolicy false pass.
  - Private credentials remain in Kubernetes Secrets, container environments, or mode-0600 local files and never enter repository evidence.
requirements-completed:
  - ISO-01
  - ISO-03
  - OPS-02
  - OPS-03
  - OPS-05
coverage:
  - id: D1
    description: MemPalace and Qdrant recover after ordered process restarts and one changed-boot VPS reboot.
    requirement: OPS-05
    verification:
      - kind: e2e
        ref: 21-RECOVERY-EVIDENCE.json restart_checks and reboot_checks
        status: pass
    human_judgment: false
  - id: D2
    description: The exact recurring template quiesces the sole writer, preserves metadata, restores writes, and verifies an S3 round trip.
    requirement: OPS-02
    verification:
      - kind: e2e
        ref: 21-RECOVERY-EVIDENCE.json steady_state_backup_consistency, fresh_backup_checks, and writer_resumption_checks
        status: pass
    human_judgment: false
  - id: D3
    description: Actual rollback and forward replay preserve retained Qdrant data and pass their correct behavior contracts.
    requirement: OPS-03
    verification:
      - kind: e2e
        ref: 21-RECOVERY-EVIDENCE.json rollback_checks and forward_checks
        status: pass
    human_judgment: false
  - id: D4
    description: The final client and public boundary expose only authenticated SolidStats MCP while Qdrant remains private.
    requirement: ISO-01, ISO-03
    verification:
      - kind: e2e
        ref: 21-CUTOVER-SEAL.json requirements and prohibitions
        status: pass
    human_judgment: false
duration: 6h
completed: 2026-08-21
status: complete
---

# Phase 21 Plan 04: Recovery and Cutover Seal Summary

**Run r8 completed the full recovery contract: the guarded recurring backup is
active, only `solidstats_memory` remains as the SolidStats client, and the
predecessor-bound Phase 21 seal passes.**

## Performance

- **Duration:** approximately 6 hours for Plan 21-04 live execution and hardening
- **Tasks:** 3
- **Pre-summary commits:** 51
- **Final contract suite:** 205 tests

## Accomplishments

- Restarted MemPalace and Qdrant one at a time and passed the authenticated MCP
  behavior matrix after each restart.
- Measured the live Kubernetes API destination and proved the exact positive,
  NetworkPolicy-negative, and RBAC-negative access controls with fresh pods.
- Ran a steady-state backup from the exact suspended CronJob template. The Job
  recorded and quiesced the sole writer, created a Qdrant snapshot and metadata
  archive, uploaded four package members to private Timeweb S3, downloaded them,
  rechecked every checksum, restored the writer, and passed capture/read/delete
  behavior after resumption.
- Issued exactly one VPS reboot and proved a changed boot identity, node and PVC
  recovery, Qdrant and MemPalace readiness, nginx activity, freeze-lock recovery,
  and the full forward MCP matrix.
- Exercised the real reverse-order rollback and exact forward replay. The legacy
  runtime passed read behavior while its peer-writer lock rejected mutation; the
  forward path passed the full mutable behavior matrix and retained inventory.
- Activated the checked-in, privately rendered, and live CronJob with
  `concurrencyPolicy: Forbid`; installed and verified the host guard; retired the
  exact legacy client while preserving unrelated Codex configuration; and sealed
  the final chain.

## Live Acceptance State

- MemPalace Deployment: 1 desired and 1 available.
- Qdrant StatefulSet: 1 ready.
- Restored corpus: 19,534 records with the retained logical binding.
- Backup CronJob: active with `suspend: false` and `Forbid` concurrency.
- SolidStats client registrations: `solidstats_memory` present, legacy
  `mempalace` absent.
- Public Qdrant ports: blocked; authenticated MCP boundary: passing.
- Recovery evidence and cutover seal: paired validation passing.

## Task Commits

1. **Task 1: Behavior-based recovery and measured API control**
   - RED: `fbeac17`
   - Initial implementation: `6a0a210`
   - Remote recovery and evidence hardening: `9dcce0d` through `908bcbf`
2. **Task 2: Executable least-privilege recurring backup**
   - RED: `9be0247`, `949c3c3`
   - Runtime, guard, RBAC, policy, and provenance implementation: `78b6e59`
     through `a5c122e`
3. **Task 3: Live recovery, rollback, activation, and seal**
   - Live-discovered backup, client, reboot, rollback, and activation fixes:
     `bb703cf` through `f174c55`
   - Evidence and summary: committed atomically with this file

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved safe metadata symlinks**

- **Issue:** The recurring backup rejected three legitimate contained model-cache
  symlinks before snapshot packaging.
- **Fix:** Canonicalized only relative regular-file symlinks whose resolved targets
  stay inside the frozen palace tree, and proved the digest remains identical after
  archive extraction.
- **Verification:** The accepted backup uploaded and downloaded the package with
  equal before, after, and archive metadata digests.

**2. [Rule 1 - Bug] Bound long backup execution and transport replay**

- **Issue:** A generic 600-second SSH timeout could interrupt the 3,600-second
  backup contract and repeat a pending failed Job.
- **Fix:** Added one dedicated bounded remote backup call and relied on durable
  complete-state replay after a transient lost SSH acknowledgement.
- **Verification:** Exactly one accepted Job completed; its result was replayed
  without another upload.

**3. [Rule 2 - Missing Critical] Closed freeze-lock reboot recovery**

- **Issue:** k3s recovered after reboot, but the retained rootless freeze-lock
  container did not start automatically and the original reboot verifier omitted
  it.
- **Fix:** Restored the captured freeze-lock state during reboot and rollback and
  made it an exact recovery evidence field.
- **Verification:** Post-reboot evidence records the changed boot identity and
  restored lock; rollback mutation was rejected with exact MemPalace code `-32001`.

**4. [Rule 1 - Bug] Preserved unrelated client configuration**

- **Issue:** Codex CLI removal reserialized the full TOML file, which broke exact
  read-back and risked overwriting unrelated concurrent configuration changes.
- **Fix:** Used the repository-owned atomic TOML editor for replacement rollback
  and legacy retirement, rotated exact cycle pre-state, and added downstream
  retirement compensation.
- **Verification:** The rollback and activation transactions preserved unrelated
  bytes, left one exact SolidStats client, and passed injected partial-failure tests.

**5. [Rule 1 - Bug] Made activation self-contained and target-set aware**

- **Issue:** Activation depended on shell variables from an earlier process and
  applied the full manifest-set validator to the private four-file operator set.
- **Fix:** Prepared candidates inside the activation process, compared promoted
  bytes with prevalidated candidates, and validated the complete checked-in source
  set separately.
- **Verification:** Source, private render, and live canonical Job template agree;
  activation completed without compensation.

**6. [Rule 2 - Missing Critical] Added host-side failed-Job enforcement**

- **Issue:** Kubernetes Job failure alone cannot guarantee immediate recurring
  schedule suspension after an uploader or verifier failure.
- **Fix:** Installed a root-owned systemd guard and fixed trust helper that accept
  only exact value-free Job markers and suspend the exact CronJob on failure,
  timeout, or malformed evidence.
- **Verification:** Guard self-test, deliberate failure, reboot recovery, unit
  state, and active timer evidence all pass.

---

**Total deviations:** six grouped correctness and critical-recovery classes.
**Impact on plan:** All changes tightened fail-closed execution or made the planned
live recovery contract executable. No application, corpus, storage prefix, or
public-route scope was added.

## Validation

- Full explicit memory suite: 205 tests passed.
- Source manifest inventory: 33 resources validated.
- Nginx templates, migration policy, Python compilation, Bash syntax, rollback
  self-test, and Git diff checks: passed.
- Recovery evidence: validated.
- Paired recovery and cutover seal chain: validated.
- Live one-shot Timeweb S3 backup and download verification: passed.
- One VPS reboot, actual rollback, exact forward replay, schedule activation, and
  legacy-client retirement: passed.

## User Setup Required

None. A fresh Codex session is required before using the final MCP registration
because MCP connection environment bindings are resolved when the session starts.
