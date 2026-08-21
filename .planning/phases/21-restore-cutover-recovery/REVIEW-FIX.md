---
phase: 21-restore-cutover-recovery
fixed_at: 2026-08-21T17:23:26Z
review_path: .planning/phases/21-restore-cutover-recovery/REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 21: Code Review Fix Report

**Fixed at:** 2026-08-21T17:23:26Z
**Source review:** `.planning/phases/21-restore-cutover-recovery/REVIEW.md`
**Iteration:** 1

**Summary:**

- Findings in scope: 8
- Fixed: 8
- Skipped: 0

## Fixed Issues

<!-- markdownlint-disable MD013 -->

### CR-01: Alias compare-and-switch is not conditional

**Files modified:** `scripts/restore-solidstats-memory.py`, `scripts/cutover-solidstats-memory.sh`, `scripts/operate-solidstats-memory.py`, `tests/test-memory-cutover-contract.py`, `tests/test-memory-operator-contract.py`
**Commit:** e76f1f2
**Applied fix:** Added one durable, owner-recording exclusive alias-writer lease across cutover journaling, restore alias changes, compatibility probes, and runtime bootstrap. Added an injected interleaving regression.
**Status:** fixed: requires human verification

### CR-02: Lost create acknowledgement leaves temporary alias live

**Files modified:** `scripts/restore-solidstats-memory.py`, `tests/test-memory-cutover-contract.py`
**Commit:** e76f1f2
**Applied fix:** Reconciled the observed alias map to its exact prestate in `finally`, independently of the create response. Added an apply-then-raise regression.
**Status:** fixed: requires human verification

### CR-03: Runtime bootstrap compensation depends on response flags

**Files modified:** `scripts/operate-solidstats-memory.py`, `scripts/bootstrap-solidstats-memory-palace.py`, `tests/test-memory-operator-contract.py`, `tests/test-memory-runtime-contract.py`
**Commit:** e76f1f2
**Applied fix:** Made temporary alias and fixed probe cleanup observation-based after ambiguous acknowledgements. Added lost-acknowledgement regressions for both mutations.
**Status:** fixed: requires human verification

### CR-04: Recurring backup can pass without synthetic cleanup

**Files modified:** `k8s/memory/40-backup.yaml`, `scripts/validate-memory-manifests.py`, `tests/test-memory-runtime-contract.py`
**Commit:** e76f1f2, 0274d54
**Applied fix:** Rejected MCP tool errors, required the exact delete result, and proved exact drawer absence before PASS markers. Added three manifest mutation regressions.
**Status:** fixed: requires human verification

### CR-05: Client retirement overwrites concurrent config changes

**Files modified:** `scripts/configure-solidstats-memory-client.py`, `tests/test-memory-cutover-contract.py`
**Commit:** e76f1f2
**Applied fix:** Serialized client writers with a durable owner lock, rebased the target removal on a fresh read, and limited compensation to the target registration while preserving unrelated bytes.
**Status:** fixed: requires human verification

### WR-01: Authenticated behavior probe lacks failure cleanup

**Files modified:** `scripts/probe-solidstats-memory.py`, `tests/test-memory-cutover-contract.py`
**Commit:** e76f1f2
**Applied fix:** Captured exact-content prestate and added bounded exact lookup plus exact-ID cleanup in `finally`, including ambiguous create responses.
**Status:** fixed: requires human verification

### WR-02: Final seal does not bind one operator config revision

**Files modified:** `scripts/collect-phase-21-recovery-evidence.py`, `tests/test-memory-cutover-contract.py`
**Commit:** e76f1f2
**Applied fix:** Required one identical `config_sha256` across every seal remote result and added a mixed-revision regression.
**Status:** fixed: requires human verification

### WR-03: Failed snapshot upload leaves multipart residue

**Files modified:** `scripts/operate-solidstats-memory.py`, `tests/test-memory-operator-contract.py`
**Commit:** e76f1f2
**Applied fix:** Switched to unique private multipart files and unconditional connection/file cleanup. Added a two-attempt transport-failure regression.

<!-- markdownlint-enable MD013 -->

## Verification

Verification ran in the isolated worktree
`.claude/worktrees/agent-p21-02-wave1` at commit `0274d54`.

- Targeted failure-injection regressions: passed for all eight findings.
- `tests/test-memory-operator-contract.py`: 35 passed.
- `tests/test-memory-runtime-contract.py`: 50 passed.
- `tests/test-memory-cutover-contract.py`: 67 passed.
- `tests/test-memory-qdrant-jwt-contract.py`: 1 passed.
- Python compilation, Bash syntax, YAML parsing, memory manifest validation,
  Phase 21 evidence validation, evidence-chain validation, and cutover
  self-test: passed.

---

_Fixed: 2026-08-21T17:23:26Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
