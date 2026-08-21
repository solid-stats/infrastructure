---
phase: 21-restore-cutover-recovery
plan: 03
subsystem: memory-cutover
tags:
  - qdrant
  - mempalace
  - nginx
  - mcp
  - rollback
requires:
  - phase: 21-restore-cutover-recovery
    plan: 02
    provides: Provenance-bound backup and exact isolated restore
provides:
  - Authenticated SolidStats MCP cutover accepted at CLIENT_ADDED
  - Atomic logical binding with exact rollback pre-state
  - Value-free public, protocol, client, and private-boundary evidence
  - Exact seven-tool Codex client policy with legacy fallback retained
affects:
  - 21-04 recovery and final seal
  - 22 archive distillation
actuals:
  tokens: 77583
  tasks: 2
  commits: 16
tech-stack:
  added: []
  patterns:
    - Compare-and-switch logical binding with immediate read-back
    - Acknowledged-stage journal with reverse-order rollback
    - Value-free evidence bound to private operator aggregates by digest
key-files:
  created:
    - scripts/probe-solidstats-memory.py
    - scripts/cutover-solidstats-memory.sh
    - scripts/configure-solidstats-memory-client.py
    - scripts/bootstrap-solidstats-memory-palace.py
    - scripts/operate-solidstats-memory-cutover-remote.sh
    - scripts/render-solidstats-memory-shared-nginx.py
    - .planning/phases/21-restore-cutover-recovery/21-CUTOVER-EVIDENCE.json
  modified:
    - scripts/restore-solidstats-memory.py
    - scripts/operate-solidstats-memory.py
    - scripts/validate-memory-manifests.py
    - scripts/validate-memory-nginx.py
    - k8s/memory/20-mempalace.yaml
    - tests/test-memory-cutover-contract.py
    - tests/test-memory-operator-contract.py
    - tests/test-memory-qdrant-jwt-contract.py
    - tests/test-memory-runtime-contract.py
key-decisions:
  - Keep the legacy client and rollback pre-state through Plan 21-04 rather than removing them at CLIENT_ADDED.
  - Expose the exact seven normal recall, capture, and cleanup tools in Codex while accepting the wider raw server catalog.
  - Bind the runtime Qdrant credential to the logical name and retain physical-target access only in the operator identity.
  - Leave the recurring backup CronJob suspended until Plan 21-04 proves recovery, quiescence, and write resumption.
patterns-established:
  - Every external mutation is preceded by a durable pending marker and followed by an acknowledged stage.
  - Public evidence stores only booleans, counts, safe codes, timestamps, and SHA-256 bindings.
  - Synthetic MCP verification must prove exact read-back and exact deletion before acceptance.
requirements-completed:
  - ISO-03
  - OPS-03
coverage:
  - id: D1
    description: The restored physical target is live through the exact logical binding with 19,534 records and an actionable rollback.
    requirement: OPS-03
    verification:
      - kind: e2e
        ref: 21-CUTOVER-EVIDENCE.json live_audit and predecessor checks
        status: pass
    human_judgment: false
  - id: D2
    description: Public Qdrant ports remain blocked while authenticated MCP behavior passes through the shared nginx route.
    requirement: ISO-03
    verification:
      - kind: e2e
        ref: 21-CUTOVER-EVIDENCE.json final_probe and live_audit checks
        status: pass
      - kind: integration
        ref: python3 scripts/validate-phase-21.py --evidence 21-CUTOVER-EVIDENCE.json
        status: pass
    human_judgment: false
  - id: D3
    description: The exact new client and exact legacy fallback registration coexist until recovery sealing.
    verification:
      - kind: e2e
        ref: 21-CUTOVER-EVIDENCE.json live_audit client checks
        status: pass
    human_judgment: false
  - id: D4
    description: The authenticated MCP matrix covers session negotiation, schemas, recall, miss fallback, archive labeling, capture, read-back, and exact cleanup.
    verification:
      - kind: e2e
        ref: 21-CUTOVER-EVIDENCE.json final_probe checks
        status: pass
      - kind: unit
        ref: tests/test-memory-cutover-contract.py
        status: pass
    human_judgment: false
duration: 3h 51m
completed: 2026-08-21
status: complete
---

# Phase 21 Plan 03: Reversible MCP Cutover Summary

**Run r8 reached `CLIENT_ADDED`: the restored 19,534-record target now serves
the authenticated SolidStats MCP route through the exact new client, with
Qdrant private and rollback retained.**

## Performance

- **Duration:** 3h 51m across eight fail-closed operator runs
- **Started:** 2026-08-21T06:41:44Z
- **Completed:** 2026-08-21T10:32:35Z
- **Tasks:** 2
- **Files modified:** 21

## Accomplishments

- Implemented compare-and-switch data routing, byte-preserving shared-nginx
  patching, exact client registration, acknowledged mutation journaling, and
  one reverse-order rollback path.
- Accepted run r8 at `CLIENT_ADDED`. The logical binding points to the verified
  restored target, the new workload is ready, the legacy runtime is stopped,
  and the freeze lock remains active.
- Proved missing and invalid token rejection, valid authentication, Origin
  rejection, MCP protocol negotiation, the required schema digest, scoped
  recall, semantic-miss fallback, archive labeling, deduplication, capture
  shape, read-after-write, and exact synthetic cleanup.
- Kept public Qdrant ports blocked and preserved the sibling personal route
  byte-for-byte in the shared nginx server.
- Registered the exact new `solidstats_memory` client with a seven-tool
  allowlist while preserving the exact legacy `mempalace` registration and the
  pre-cutover token/config state for Plan 21-04 rollback.

## Task Commits

Task 1 used TDD and live hardening; Task 2 is sealed by the evidence and
summary commit:

1. **Task 1: Implement compare-and-switch cutover, MCP probes, and exact
   rollback**
   - RED: `7382653`
   - Initial implementation: `35f35f2`
   - Runtime, nginx, auth, client-policy, JWT, bootstrap, resource, and cleanup
     hardening: `b2e8b7e` through `4acfc7e`
2. **Task 2: Authorize and execute the reversible live cutover**
   - Aggregate evidence and plan summary: committed atomically with this file

## Files Created/Modified

- `scripts/probe-solidstats-memory.py` — Runs bounded negative-auth, MCP
  protocol, behavior, client-policy, and public-boundary probes.
- `scripts/cutover-solidstats-memory.sh` — Journals acknowledged stages and
  rolls back client, nginx, logical binding, new workload, and legacy runtime
  in reverse order.
- `scripts/restore-solidstats-memory.py` — Owns compare-and-switch mutation,
  binding verification, and exact pre-state restoration.
- `scripts/operate-solidstats-memory-cutover-remote.sh` — Performs coarse,
  restartable VPS batches without depending on a worktree path.
- `scripts/configure-solidstats-memory-client.py` — Applies the exact seven-tool
  policy and preserves byte-exact Codex configuration pre-state.
- `scripts/bootstrap-solidstats-memory-palace.py` — Initializes the runtime
  backend marker and verified embedding model state without changing the
  restored record set.
- `k8s/memory/20-mempalace.yaml` — Carries logical-binding authorization,
  runtime bootstrap, and measured embedding memory resources.
- `.planning/phases/21-restore-cutover-recovery/21-CUTOVER-EVIDENCE.json` —
  Binds accepted r8 live and protocol aggregates to Plan 20 and Plan 21-02
  evidence by digest.

## Decisions Made

- Kept the legacy client registration and rollback material after the successful
  cutover. Plan 21-04 must exercise recovery and rollback/forward recovery
  before removing or disabling the legacy entry.
- Limited the normal Codex surface to seven tools required for recall, capture,
  read-back, and exact cleanup. The probe records the wider server catalog count
  but does not expose those extra tools to the client.
- Scoped the MemPalace Qdrant JWT to the logical binding. Physical-target
  mutation remains an operator-only responsibility.
- Left the recurring CronJob suspended and unchanged. Its quiescence,
  metadata-consistency, write-resumption, restart, and reboot gates belong to
  Plan 21-04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Matched the real shared nginx topology**

- **Found during:** Task 2 preflight runs r1-r3
- **Issue:** The first renderer assumptions did not preserve the production
  prefix rewrite, dual listener pair, or the single server that owns both
  memory routes.
- **Fix:** Switched to stdin transport, required the trailing-slash upstream
  contract, and patched only the SolidStats upstream inside the measured shared
  server.
- **Files modified:** Cutover script, remote operator, nginx renderer,
  template, validators, and contract tests.
- **Verification:** Exact candidate and sibling-route preservation passed in
  accepted run r8.
- **Committed in:** `b2e8b7e` through `00215c3`

**2. [Rule 1 - Bug] Hardened public auth and client capability enforcement**

- **Found during:** Task 2 public and client gates
- **Issue:** Real auth rejection bodies were not always JSON, and registering
  the client alone did not constrain the wider raw MCP tool catalog.
- **Fix:** Kept successful responses strict, treated bounded non-success bodies
  as opaque, and applied an exact seven-tool Codex allowlist with byte-exact
  rollback.
- **Files modified:** MCP probe, client-policy writer, cutover script, and tests.
- **Verification:** Auth, protocol, client, and complete behavior matrices
  passed in r8.
- **Committed in:** `bc8741a`, `4bf24e4`

**3. [Rule 2 - Missing Critical] Added logical-binding authorization and safe
runtime bootstrap**

- **Found during:** Task 2 private runtime gates
- **Issue:** The initial runtime credential was physical-target scoped, while
  MemPalace addresses the logical binding; the restored package also lacked a
  usable backend marker and verified embedding cache for writes.
- **Fix:** Separated operator and runtime claims, initialized the marker through
  the official backend, preserved the restored collection, seeded the verified
  embedding model cache, and restored all temporary bootstrap state.
- **Files modified:** Secret renderer, operator, bootstrap controller,
  MemPalace manifest, validators, and tests.
- **Verification:** Private bootstrap and the full public
  capture/read-back/cleanup matrix passed without changing the 19,534-record
  baseline.
- **Committed in:** `579a361` through `67eecf3`

**4. [Rule 1 - Bug] Aligned measured memory and exact cleanup contracts**

- **Found during:** Task 2 bootstrap and r7 cleanup gate
- **Issue:** The embedding workload exceeded the original 1 GiB limit, and the
  cleanup probe expected a response shape that MemPalace 3.5.0 does not return.
- **Fix:** Applied the measured 1 GiB request and 3 GiB limit consistently, then
  validated the exact versioned delete response and internal count consistency.
- **Files modified:** MemPalace manifest, validators, probe, and contract tests.
- **Verification:** The accepted r8 probe deleted the synthetic record exactly
  and the target returned to 19,534 records.
- **Committed in:** `6d90a63`, `4acfc7e`

---

**Total deviations:** 4 grouped correctness and critical-runtime classes.
**Impact on plan:** Each change closed a fail-closed live gate. The public path,
restored corpus, client scope, and Plan 21 boundary did not expand.

## Issues Encountered

- Runs r1-r7 stopped at their first failing gate and restored logical binding,
  nginx, workload, legacy runtime, client, and token/config pre-state. No
  synthetic record or other data residue remained.
- Run r8 is the accepted run. Its value-free live audit, final MCP probe,
  journal, and locator are retained under logical artifact IDs
  `phase21-cutover-operator-20260821-r8` and
  `phase21-cutover-run-20260821-r8`; repository evidence contains only their
  digests and aggregates.

## User Setup Required

None. The new and legacy machine-local registrations are already present. A
fresh Codex session is needed before relying on the newly registered server
because MCP client environment bindings are resolved at session start.

## Validation

- Full memory contract suite: 180 tests passed.
- Python compilation, Bash syntax, and cutover self-test: passed.
- Manifest, nginx, migration-policy, and evidence validators: passed.
- Accepted r8 stage: `CLIENT_ADDED`, pending mutation: none.
- Restored target count: 19,534 before and after synthetic MCP verification.
- Full authenticated MCP behavior matrix: passed.
- Public Qdrant TCP 6333/6334 boundary: blocked.
- Shared nginx candidate and sibling personal route preservation: exact.
- New workload ready; legacy runtime stopped; freeze lock running.
- Exact new and legacy client registrations: present.
- Rollback: actionable and bound to retained exact pre-state.
- Phase 21 evidence envelope: passed the recursive value-free validator.

## Next Phase Readiness

Plan 21-04 can start from the accepted `CLIENT_ADDED` state. It still owns
ordered process restart, one VPS reboot, rollback and forward recovery,
steady-state backup quiescence and consistency, recurring CronJob activation,
final `SEALED` evidence, and exact legacy-client retirement.

## Known Stubs

None.

## Self-Check: PASSED

- `21-CUTOVER-EVIDENCE.json` exists, parses, is recursively value-free, and
  validates with verdict `pass`.
- The accepted evidence is bound to the exact Plan 20 handoff/parity, Plan
  21-02 predecessor, r8 live audit, final MCP probe, cutover journal, and
  retained locator digests.
- All Plan 21-03 commits from `7382653` through `4acfc7e` exist.
- No private paths, names, credentials, corpus values, raw responses, or
  authorization material appear in the committed evidence.
- The only unrelated/uncommitted artifact remains the pre-existing mode-0600
  restore lock.

---

*Phase: 21-restore-cutover-recovery*
*Completed: 2026-08-21*
