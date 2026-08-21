---
phase: 21-restore-cutover-recovery
reviewed: 2026-08-21T17:03:26Z
depth: deep
files_reviewed: 34
files_reviewed_list:
  - .github/workflows/deploy-memory.yml
  - config/nginx/sites-available/solidstats-memory-shared-cutover.patch.template
  - config/solidstats-memory/backup-guard.config.template
  - config/solidstats-memory/remote-cutover-operator.config.template
  - docs/solidstats-memory.md
  - k8s/memory/05-rbac.yaml
  - k8s/memory/10-qdrant.yaml
  - k8s/memory/20-mempalace.yaml
  - k8s/memory/30-network-policy.yaml
  - k8s/memory/40-backup.yaml
  - k8s/memory/50-monitoring.yaml
  - scripts/bootstrap-solidstats-memory-palace.py
  - scripts/collect-phase-21-recovery-evidence.py
  - scripts/configure-solidstats-memory-client.py
  - scripts/cutover-solidstats-memory.sh
  - scripts/guard-solidstats-memory-backup.sh
  - scripts/operate-solidstats-memory-cutover-remote.sh
  - scripts/operate-solidstats-memory.py
  - scripts/probe-solidstats-memory.py
  - scripts/render-memory-manifests.py
  - scripts/render-memory-secrets.py
  - scripts/render-solidstats-memory-backup-activation.py
  - scripts/render-solidstats-memory-shared-nginx.py
  - scripts/restore-solidstats-memory.py
  - scripts/solidstats-memory-backup-guard.service
  - scripts/solidstats-memory-backup-guard.timer
  - scripts/suspend-solidstats-memory-backup.sh
  - scripts/validate-memory-manifests.py
  - scripts/validate-memory-nginx.py
  - scripts/validate-phase-21.py
  - tests/test-memory-cutover-contract.py
  - tests/test-memory-operator-contract.py
  - tests/test-memory-qdrant-jwt-contract.py
  - tests/test-memory-runtime-contract.py
findings:
  critical: 5
  warning: 3
  info: 0
  total: 8
status: issues_found
---

# Phase 21: Code Review Report

**Reviewed:** 2026-08-21T17:03:26Z
**Depth:** deep
**Files Reviewed:** 34
**Status:** issues_found

## Summary

The Phase 21 restore, cutover, recovery, recurring-backup, and evidence
chain was reviewed against the four phase plans, context, research, and
requirements ISO-01, ISO-03, OPS-02, OPS-03, and OPS-05. The submitted
evidence chain is internally valid and the lightweight offline validators
pass, but five correctness defects can overwrite concurrent state, leave live
synthetic mutations behind, or accept an unsuccessful recurring-backup cleanup
as a passing recovery gate. Phase 21 must not ship until the blockers are fixed
and covered by failure-injection tests.

## Narrative Findings (AI reviewer)

### Critical Issues

#### CR-01: Alias compare-and-switch is not conditional

**Classification:** BLOCKER

**File:** `scripts/restore-solidstats-memory.py:1319-1350`

**Issue:** `compare_and_switch_alias()` reads `/aliases`, compares it with the
recorded map, and later submits an unconditional delete/create batch. Qdrant
receives no predicate tying the mutation to the map read at line 1319. A second
authorized writer can change the active alias after the comparison and before
line 1350; this operation will then delete or overwrite that newer binding.
`restore_alias_prestate()` repeats the same check-then-write pattern at lines
1381-1403. The cutover journal does not serialize processes either:
`cutover-solidstats-memory.sh:1094-1102` checks for a journal and then replaces
it without an exclusive process lock. The existing race test changes the alias
before the GET and cannot exercise this interleaving. A concurrent cutover can
route live clients to the wrong collection, violating OPS-03 and OPS-05.

**Fix:** Put capture, mutation, read-back, and rollback under one exclusive
lease honored by every authorized alias writer. If Qdrant has no conditional
alias-update primitive, use a host or distributed lock with ownership and
expiry, reject a second cutover before any stage or journal write, and stop
describing the operation as CAS. Add an injected interleaving test that changes
the alias after the comparison and before the POST.

#### CR-02: Lost create acknowledgement leaves temporary alias live

**Classification:** BLOCKER

**File:** `scripts/restore-solidstats-memory.py:1424-1459`

**Issue:** The compatibility probe sets `created = True` only after
`_alias_action()` returns. If Qdrant applies the create but the response is lost
or times out, `created` remains false. The `finally` branch then only observes
that the final map differs; it reports a failed restoration without attempting
to delete the alias. This contradicts the function's "always restore exact
absence" contract and leaves a persistent alias that blocks retry and expands
the live mutation surface.

**Fix:** In `finally`, always reconcile the observed alias map to the recorded
prestate, regardless of whether the create call returned. Preserve the
unrelated-alias comparison and fail only after a best-effort exact restoration
and read-back. Add an apply-then-raise transport test.

#### CR-03: Runtime bootstrap compensation also depends on post-response flags

**Classification:** BLOCKER

**File:** `scripts/operate-solidstats-memory.py:1850-1919`

**Issue:** `alias_created` becomes true only after the Qdrant alias request
returns, so an applied create followed by a lost response is detected at final
read-back but never removed. The nested runtime probe has the same defect in
`scripts/bootstrap-solidstats-memory-palace.py:405-427`: `wrote_probe` becomes
true only after `collection.upsert()` returns. An applied upsert with a lost
acknowledgement skips cleanup and leaves the fixed probe ID in the restored
collection. Either residue makes the next bootstrap refuse its prestate and can
contaminate the collection accepted for cutover.

**Fix:** Make compensation observation-based, not acknowledgement-flag-based.
Always inspect and reconcile the temporary alias to its captured prestate, and
always query and delete the fixed probe ID in the exception path after proving
it was absent initially. Add lost-acknowledgement tests for both mutations.

#### CR-04: The recurring backup oracle reports PASS without proving synthetic cleanup

**Classification:** BLOCKER

**File:** `k8s/memory/40-backup.yaml:641-655`

**Issue:** The recurring backup controller creates and reads a synthetic drawer,
then ignores the result of `mempalace_delete_drawer` and immediately prints both
PASS markers. Its MCP helper rejects JSON-RPC errors but does not reject a tool
result with `isError: true`; the delete response is not structurally validated
and absence is not read back.
`scripts/guard-solidstats-memory-backup.sh:90-96` trusts only these log markers,
so an ineffective cleanup is accepted as a healthy recurring backup and the
schedule remains live while one synthetic drawer may be retained per run. This
invalidates the OPS-02/OPS-05 behavior gate.

**Fix:** Reject tool-level errors, parse the exact MemPalace delete contract used
by `probe-solidstats-memory.py`, and verify the drawer is absent, or that the
exact pre-count is restored, before printing either PASS marker. Add mutation
tests for `isError: true`, malformed success, and an ineffective delete.

#### CR-05: Client retirement can overwrite unrelated concurrent config changes

**Classification:** BLOCKER

**File:** `scripts/configure-solidstats-memory-client.py:489-541`

**Issue:** `retire_transaction()` reads the complete client config at line 489,
performs several filesystem operations, and unconditionally replaces the config
with bytes derived from that stale snapshot at line 513. Any user or Codex
process editing another config section in that interval loses its change. The
exception compensation is worse: if the observed file differs from the original
snapshot, lines 539-541 overwrite it with the old complete file, including
changes made after retirement. `rollback_registration_transaction()` has the
same read/replace shape at lines 374-394 and 415-418. The post-write "unrelated
unchanged" digest only proves the stale bytes were written; it cannot detect the
overwritten concurrent edit. This is direct local data-loss risk and contradicts
ISO-01's exact client-retirement boundary.

**Fix:** Serialize all participating client-config mutations with an exclusive
lock, then re-read and rebase the one registration removal immediately before
the atomic replace. Compensation must restore only the target registration after
verifying an exact expected current state; it must refuse rather than replace
the whole file when unrelated bytes changed. Add tests for unrelated edits
before replacement and before compensation.

### Warnings

#### WR-01: Authenticated behavior probe lacks failure cleanup

**Classification:** WARNING

**File:** `scripts/probe-solidstats-memory.py:702-727`

**Issue:** Once `mempalace_add_drawer` succeeds, any failure while extracting the
ID, reading back, parsing the delete response, or validating cleanup exits
without a `finally` reconciliation. The probe correctly fails, but it can leave
synthetic operational data in the live palace and make repeated recovery
attempts accumulate residue.

**Fix:** Capture the prestate and put exact-ID cleanup in `finally`. After an
ambiguous create response, locate only the run-bound synthetic record through a
bounded exact lookup before deletion. Preserve the original probe error while
surfacing incomplete cleanup separately.

#### WR-02: Final seal does not bind one operator config revision

**Classification:** WARNING

**File:** `scripts/collect-phase-21-recovery-evidence.py:212-255`

**Issue:** Recovery aggregation explicitly requires every remote result to carry
one identical `config_sha256` at lines 182-187. Seal aggregation parses another
set of remote results but omits the same equality check. The normal shell runner
binds results to a local config digest, which reduces likelihood, but the
collector itself can synthesize a passing seal from same-run files produced by
different operator-config revisions.

**Fix:** Build and validate the seal result's `config_sha256` set exactly as the
recovery branch does, and bind it to the predecessor generation. Add a collector
test where one seal input has a different config digest.

#### WR-03: Failed snapshot upload leaves a replay-blocking multipart artifact

**Classification:** WARNING

**File:** `scripts/operate-solidstats-memory.py:2166-2191`

**Issue:** `snapshot-upload.multipart` is unlinked only after the complete HTTP
exchange. Any connection, send, response, or port-forward exception leaves the
file in the private state directory. The next resume uses `open("xb")` on the
same path and fails before retrying the upload. The retained file also duplicates
the private snapshot bytes unnecessarily.

**Fix:** Create the multipart file under a unique private temporary name and
unlink it in `finally`, closing the HTTP connection there as well. Add a
transport-failure test that proves both cleanup and immediate retry.

---

_Reviewed: 2026-08-21T17:03:26Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
