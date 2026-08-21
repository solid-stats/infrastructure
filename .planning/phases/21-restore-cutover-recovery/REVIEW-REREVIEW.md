---
phase: 21-restore-cutover-recovery
reviewed: 2026-08-21T17:30:49Z
head: 78849f8f515b3eac7380e538ba4e0cf197f75d6a
commits_reviewed:
  - e76f1f2
  - 0274d54
depth: deep-targeted
files_reviewed: 12
files_reviewed_list:
  - k8s/memory/40-backup.yaml
  - scripts/bootstrap-solidstats-memory-palace.py
  - scripts/collect-phase-21-recovery-evidence.py
  - scripts/configure-solidstats-memory-client.py
  - scripts/cutover-solidstats-memory.sh
  - scripts/operate-solidstats-memory.py
  - scripts/probe-solidstats-memory.py
  - scripts/restore-solidstats-memory.py
  - scripts/validate-memory-manifests.py
  - tests/test-memory-cutover-contract.py
  - tests/test-memory-operator-contract.py
  - tests/test-memory-runtime-contract.py
findings:
  critical: 4
  warning: 1
  info: 0
  total: 5
status: issues_found
verdict: remaining_findings
---

# Phase 21: Code Review Re-review

**Reviewed:** 2026-08-21T17:30:49Z
**HEAD:** `78849f8f515b3eac7380e538ba4e0cf197f75d6a`
**Fix commits:** `e76f1f2`, `0274d54`
**Verdict:** remaining findings

## Summary

The targeted failure-injection tests pass, and WR-02 plus WR-03 are closed.
The other fixes improve the failure paths but do not fully close their original
contracts. Four blockers remain around alias-lock authority, ambiguous alias
cleanup, recurring-backup absence proof, and concurrent client-config writes.
WR-01 also remains partially open because its “exact” recovery lookup is an
ANN search with a result limit.

## Closure Matrix

| Original | Result | Evidence |
| --- | --- | --- |
| CR-01 | OPEN | RR-CR-01 |
| CR-02 | OPEN | RR-CR-02 |
| CR-03 | OPEN | RR-CR-02 |
| CR-04 | OPEN | RR-CR-03 |
| CR-05 | OPEN | RR-CR-04 |
| WR-01 | OPEN | RR-WR-01 |
| WR-02 | CLOSED | Seal inputs now require one config revision. |
| WR-03 | CLOSED | Multipart file and connection use unconditional cleanup. |

## Remaining Critical Issues

### RR-CR-01: Alias lease authority can be bypassed or split by run

**Classification:** BLOCKER

**Files:** `scripts/restore-solidstats-memory.py:85-99`,
`scripts/operate-solidstats-memory.py:112-151`

**Issue:** Both lease helpers treat any inherited descriptor that references a
regular file as proof that the canonical alias lock is held. They do not verify
the descriptor path, lock ownership, owner record, or run binding. A stale or
misbound `SOLIDSTATS_MEMORY_ALIAS_LOCK_FD` therefore bypasses `flock` entirely.
The operator fallback also locks `self.state_root.parent`, which is the current
run directory, while the cutover/restore path locks the shared private-run root.
Two standalone operator runs can consequently acquire different files while
mutating the same Qdrant alias. The new test exercises two acquisitions of the
same canonical path without an inherited descriptor; it does not cover either
bypass. CR-01's “every authorized alias writer” requirement is not established.

**Fix:** Resolve one canonical lock path from an explicit shared-root binding in
both programs. For inherited descriptors, verify `/proc/self/fd/<n>` resolves to
that path, validate the exact owner record and run digest, and confirm/reacquire
the nonblocking exclusive lock on the inherited open-file description. Remove
the run-local fallback. Add tests for an arbitrary regular inherited FD and two
operator configs with different run directories.

### RR-CR-02: Cleanup still does not reconcile an ambiguous delete result

**Classification:** BLOCKER

**Files:** `scripts/restore-solidstats-memory.py:1410-1495`,
`scripts/operate-solidstats-memory.py:1955-1974`

**Issue:** The new code reconciles after a lost create acknowledgement, but the
reconciliation mutation itself remains one-shot. If the delete request times
out before Qdrant applies it, `restore_alias_prestate()` exits from line 1446
without a final observation or retry, leaving the temporary alias live. Runtime
bootstrap similarly records `cleanup_failed` after an ambiguous delete and only
observes the residue; it never retries removal. The tests inject apply-then-raise
only on create. They do not inject raise-before-apply or apply-then-raise on the
cleanup action. Thus the exact-absence guarantees behind CR-02 and CR-03 remain
incomplete.

**Fix:** Make restoration an observation-driven bounded loop under the writer
lease: read the exact map, compute one alias-only action, submit it, then always
read again even if submission raises. Retry only while unrelated aliases equal
the captured prestate, and finish only on exact-map equality. Add both cleanup
failure orderings to the compatibility-probe and runtime-bootstrap tests.

### RR-CR-03: Any MemPalace tool error is accepted as exact absence

**Classification:** BLOCKER

**File:** `k8s/memory/40-backup.yaml:664-669`

**Issue:** Commit `0274d54` reads the drawer by exact ID, but accepts only the
generic condition `isError is True`. Authentication failure, backend outage,
invalid arguments, or an internal tool exception therefore proves “absence” and
allows both PASS markers. No error code or exact not-found result shape is
checked. The new runtime test mutates source strings; it never executes the
embedded controller against different tool-error payloads. CR-04's exact
absence gate is still false-positive capable.

**Fix:** Define and validate the pinned MemPalace v3.5.0 not-found response,
including its stable structured code or exact bounded content shape. Reject all
other tool errors. Extract the embedded oracle into an importable tested module,
or execute it with fake MCP responses covering not-found, unauthorized,
unavailable, malformed, and still-present cases.

### RR-CR-04: Client replacement still has an unprotected stale-write window

**Classification:** BLOCKER

**File:** `scripts/configure-solidstats-memory-client.py:591-626`

**Issue:** The new lock serializes only writers that use this script; a user,
editor, or `codex mcp` process does not honor it. The fresh read at lines 598-605
is followed by prestate/evidence/metadata operations before the whole config is
replaced at line 626. An unrelated edit in that interval is still overwritten.
The new test injects its edit through `before_replace` at line 597, before the
fresh read, so it cannot exercise the remaining window. Rollback registration
has the same cooperative-lock limitation. CR-05's external concurrent-edit data
loss remains possible.

**Fix:** Immediately before replacement, re-read the file and either rebase the
single target-table change again or perform an inode/digest compare-and-swap
that refuses on any mismatch. Repeat the comparison after preparing replacement
bytes, and preserve unrelated bytes during compensation. Add failure injection
inside `capture_pre_retirement` or `_authorize_exact_states`, after line 605 but
before the actual replace, plus an external nonparticipating-writer test.

## Remaining Warning

### RR-WR-01: Ambiguous capture recovery relies on incomplete semantic search

**Classification:** WARNING

**File:** `scripts/probe-solidstats-memory.py:509-526`

**Issue:** `_exact_content_ids()` is named as an exact lookup but obtains
candidates from `mempalace_search` with `limit: 10`. ANN search is neither a
complete enumeration nor an exact content index. After a lost add
acknowledgement it can omit the new drawer, making `created_ids` empty and
leaving the synthetic record behind. The test fake returns every exact match,
which assumes the property that production search does not guarantee.

**Fix:** Use a bounded deterministic listing/filter API or a caller-selected
synthetic ID that can be queried directly. If neither exists, record cleanup as
unrecoverable rather than calling semantic search exact, and prevent a new
capture until the run-bound residue is deterministically reconciled.

## Verification

- Ten targeted failure-injection test selections passed.
- Bash syntax and Python compilation passed.
- Memory manifest validation with reviewed placeholders passed.
- Phase 21 evidence-chain validation passed.
- No live, network, Docker, or full-suite operation was run.
- No source file, lock, git state, or Phase 22 artifact was changed.

---

_Reviewed: 2026-08-21T17:30:49Z_
_Reviewer: the agent (gsd-code-reviewer)_
