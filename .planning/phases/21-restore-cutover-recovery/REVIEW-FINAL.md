---
phase: 21-restore-cutover-recovery
reviewed: 2026-08-21T18:06:43Z
head: 9b1b52c0d48cf701b0f3f74eb07fdfc875bbdfec
commits_reviewed:
  - fa76991
  - 0703200
  - 29dbd1e
depth: deep-targeted
files_reviewed: 11
files_reviewed_list:
  - k8s/memory/40-backup.yaml
  - scripts/configure-solidstats-memory-client.py
  - scripts/cutover-solidstats-memory.sh
  - scripts/operate-solidstats-memory.py
  - scripts/probe-solidstats-memory.py
  - scripts/restore-solidstats-memory.py
  - scripts/solidstats_memory_backup_oracle.py
  - scripts/validate-memory-manifests.py
  - tests/test-memory-cutover-contract.py
  - tests/test-memory-operator-contract.py
  - tests/test-memory-runtime-contract.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
verdict: remaining_findings
---

# Phase 21: Final Code Review

**Reviewed:** 2026-08-21T18:06:43Z
**HEAD:** `9b1b52c0d48cf701b0f3f74eb07fdfc875bbdfec`
**Fix commits:** `fa76991`, `0703200`, `29dbd1e`
**Verdict:** remaining findings

## Summary

RR-CR-01, RR-CR-02, and RR-CR-03 are closed. Alias writers now share and
validate one canonical lease, ambiguous cleanup is observation-driven, and the
backup oracle accepts only the pinned not-found mapping. Complete MCP table
subtrees are removed and restored without orphaned nested tables.

RR-CR-04 remains open because the client update is still a check-then-rename,
not an atomic compare-and-swap. The token-isolation change also validates only
the replacement registration; it never rejects a legacy personal registration
bound to the ambiguous or SolidStats token. RR-WR-01 uses deterministic listing
now, but its fixed 10,000-drawer bound is not tied to accepted corpus/wing
evidence.

## Closure Matrix

| Scope | Result | Evidence |
| --- | --- | --- |
| RR-CR-01 | CLOSED | Canonical lease and inherited FD are validated. |
| RR-CR-02 | CLOSED | Both timeout orders are reconciled. |
| RR-CR-03 | CLOSED | Exact delete and not-found results are validated. |
| RR-CR-04 | OPEN | FINAL-CR-01 |
| RR-WR-01 | PARTIAL | FINAL-WR-01 |
| MCP subtree | CLOSED | Parent and nested tables move together. |
| Distinct token bindings | OPEN | FINAL-CR-02 |

## Remaining Critical Issues

### FINAL-CR-01: Client config replacement is still not an atomic CAS

**Classification:** BLOCKER

**File:** `scripts/configure-solidstats-memory-client.py:180-210`

**Issue:** `_atomic_replace()` checks the current inode and bytes at lines
201-209, then calls `os.replace()` at line 210. A nonparticipating writer can
replace or edit the config after the final check and before the rename; its
change is then silently overwritten. The advisory lock does not protect an
editor or `codex mcp`, which was the original CR-05/RR-CR-04 threat. The new
failure injection changes the file before `_atomic_replace()` performs its
checks, so it cannot exercise this final TOCTOU window. The double check narrows
the race but does not close the data-loss defect.

**Fix:** Use a real atomic ownership transition. On Linux, one option is
`renameat2(RENAME_EXCHANGE)`: exchange the candidate with the live path, verify
the displaced inode and bytes equal the expected prestate, and retain/merge or
restore safely when they do not. Alternatively route the mutation through the
single config-owning client process/API. Add an injected change between the
last comparison and publication and prove those bytes cannot be lost.

### FINAL-CR-02: Legacy token collision is asserted in fixtures but never rejected

**Classification:** BLOCKER

**Files:** `scripts/configure-solidstats-memory-client.py:21-24`,
`scripts/configure-solidstats-memory-client.py:658-674`

**Issue:** Production code defines and enforces only
`MEMPALACE_SOLIDSTATS_MCP_TOKEN`. `retire_transaction()` records the legacy
mapping but never requires its `bearer_token_env_var` to equal
`MEMPALACE_PERSONAL_MCP_TOKEN`, differ from the replacement token, or reject
`MEMPALACE_MCP_TOKEN`. Rollback performs only mapping equality checks at lines
493-528. The positive tests construct a correct personal binding, while the
negative tests reject ambiguous/personal names only when supplied as the
replacement `token_env`. A live legacy registration using the ambiguous or
SolidStats binding therefore passes pre-retirement and can coexist with the new
client under a colliding identity. The requested distinct-token invariant is
not enforced at the trust boundary.

**Fix:** Define `PERSONAL_TOKEN_ENV_NAME = "MEMPALACE_PERSONAL_MCP_TOKEN"` and
validate the complete legacy subtree before capture, rollback, retirement, and
restore. Require the legacy bearer binding to equal that value and the
replacement binding to equal `MEMPALACE_SOLIDSTATS_MCP_TOKEN`; explicitly reject
`MEMPALACE_MCP_TOKEN` and cross-bound values. Add negative transaction tests
for legacy ambiguous, legacy SolidStats, replacement personal, and replacement
ambiguous bindings.

## Remaining Warning

### FINAL-WR-01: Deterministic cleanup inventory has an unbound 10,000 limit

**Classification:** WARNING

**File:** `scripts/probe-solidstats-memory.py:495-541`

**Issue:** ANN recovery was correctly replaced with complete pagination, but
the function hard-codes at most 100 pages and rejects `total > 10_000`. Phase 20
accepted 19,555 source drawers and Phase 21 accepted 19,534 restored records;
the review artifacts do not establish that the `infrastructure` wing will
remain below 10,000. The new test covers only 101 drawers. Once that wing crosses
the arbitrary limit, every authenticated behavior probe fails before capture,
blocking recovery despite valid state.

**Fix:** Bind the maximum to a reviewed live per-wing count plus explicit
headroom, or use the accepted Phase 20 maximum-record bound with a bounded
deadline/response budget. Add boundary tests at the accepted maximum and one
over it.

## Verification

- Thirteen targeted test selections passed across the cutover, operator, and
  runtime contract files.
- Bash syntax and Python compilation passed.
- Memory manifest validation passed for 34 resources.
- Phase 21 evidence-chain validation passed.
- The ConfigMap/source synchronization and exact oracle tests passed.
- Production source contains only the SolidStats token name; the ambiguous name
  appears only in negative tests, but the legacy input mapping is not validated.
- No live, network, Docker, or full-suite operation was run.
- No source file, lock, git state, or Phase 22 artifact was changed.

---

_Reviewed: 2026-08-21T18:06:43Z_
_Reviewer: the agent (gsd-code-reviewer)_
