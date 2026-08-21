---
phase: 21-restore-cutover-recovery
verified: 2026-08-21T18:43:11Z
status: passed
score: 13/13 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 21: Restore, Cutover & Recovery Verification Report

**Phase Goal:** Prove snapshot restore in isolation, then perform a reversible
operator-gated cutover to `/solidstats/mcp` and `solidstats_memory` with restart
and reboot recovery evidence.

**Verified:** 2026-08-21T18:43:11Z
**Status:** passed
**Re-verification:** No — initial verification

## Verification Basis

- No previous `21-VERIFICATION.md` existed, so this is an initial,
  goal-backward verification.
- The checked tree is `efbb052eabfd9569c494225c7ad08265394fa7c9`; the only
  tracked change after the final implementation/review tree is
  `21-SECURITY.md`. The restore, cutover, probe, backup, client, manifests,
  tests, and evidence are unchanged from the audited implementation.
- The worktree has no upstream. Remote freshness was not asserted because this
  verification was explicitly prohibited from making network calls. The current
  source tree and committed value-free evidence are the evidence boundary.
- The pre-existing untracked
  `.planning/phases/21-restore-cutover-recovery/.21-02-restore.lock` remained
  untouched and mode `0600`.

## Goal Achievement

### Observable Truths

The 37 plan-frontmatter truths were deduplicated into the following 13
goal-level observables. All four plans, the Phase 21 context, research, and
validation strategy were used; roadmap requirements remain the contract.

<!-- markdownlint-disable MD013 -->

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Evidence transitions are provenance-bound, idempotent where allowed, ordered, lock-protected, and value-free. | VERIFIED | `scripts/validate-phase-21.py` enforces exact schemas, digest predecessors, lock/replay rules, and recursive privacy rejection; the chain validator passed. |
| 2 | Qdrant remains private while only authenticated MemPalace MCP is reachable publicly. | VERIFIED | `10-qdrant.yaml` is ClusterIP-only; reciprocal default-deny policy is validated; recovery evidence contains all-address 6333/6334 negatives and authenticated MCP proof. |
| 3 | The backup is deterministic, checksum-verified, resumable without overwrite, and has a four-member S3 package. | VERIFIED | Backup/restore evidence validates and records one Job, four members/objects, local and downloaded checksum checks; source manifest and 34-resource validator pass. |
| 4 | Restore is only to an absent isolated target and preserves exact parity. | VERIFIED | Source rejects occupied collection/alias targets; live evidence requires three-way target absence and records matching restore/parity count of **19,534** with exact fields, IDs, metadata, timestamps, vectors, exclusions, and ANN behavior. |
| 5 | Isolated restore leaves active routing, nginx, registrations, legacy runtime, and schedule unchanged. | VERIFIED | Backup/restore evidence validator requires exact rollback/prestate checks; named stage-machine and alias rollback tests passed. |
| 6 | Cutover is preflighted, reversible, journaled, and stops the legacy stack before accepting the new stack. | VERIFIED | `cutover-solidstats-memory.sh` records only acknowledged stages, offers reverse-order rollback from every mutation, and its cutover/recovery self-test passed. |
| 7 | Missing/invalid bearer credentials fail; valid credentials, real MCP initialization/schema, recall/miss/archive/capture/read-after-write, and cleanup pass. | VERIFIED | `probe-solidstats-memory.py` owns the full matrix; cutover/recovery evidence is digest-bound and valid. The named loopback auth fixture passed. |
| 8 | The exact `solidstats_memory` registration is token-isolated, and legacy retirement occurs only after recovery/rollback gates. | VERIFIED | `configure-solidstats-memory-client.py` enforces exact personal and SolidStats token bindings plus Linux atomic exchange; named retirement and token/collision tests passed; final seal requires one live new client and no legacy client. |
| 9 | MemPalace and Qdrant recover one at a time, then the same behavior matrix passes after each restart and the VPS reboot. | VERIFIED | Recovery validator requires ordered restart checks, changed boot identity, Ready/Bound/available/nginx/freeze-lock checks, and behavior proof; recovery evidence and self-test pass. |
| 10 | The scheduled backup has a measured least-privilege Kubernetes API path and a consistency-proven writer quiesce/resume cycle. | VERIFIED | `05-rbac.yaml` scopes Deployment/scale access; `40-backup.yaml` projects a 600-second token; recovery evidence requires positive, network-negative, RBAC-negative, zero-writer, equal metadata digest, replica restoration, and write resumption. |
| 11 | Rollback is actually exercised, its forward replay succeeds, and schedule activation retains `concurrencyPolicy: Forbid`. | VERIFIED | Recovery evidence requires reverse order and exact forward replay; `40-backup.yaml` is active with `suspend: false` and `Forbid`; the final seal requires `backup_schedule_live`. |
| 12 | The review/fix/rereview/final-fix/pass chain closed the discovered alias, cleanup, backup-oracle, client-CAS, token-isolation, and inventory-bound defects. | VERIFIED | All closure commits are ancestors of HEAD; current source contains the reviewed `renameat2(RENAME_EXCHANGE)` and complete token-subtree checks; `REVIEW-PASS.md` is PASS. |
| 13 | The ASVS Level 2 threat gate is closed without relying only on prose. | VERIFIED | Current source/manifests were independently revalidated, targeted behavior tests passed, and `21-SECURITY.md` records 18/18 closed threats with no source change after its audited tree. |

<!-- markdownlint-enable MD013 -->

**Score:** 13/13 truths verified (0 present-but-behavior-unverified)

## Required Artifacts

<!-- markdownlint-disable MD013 -->

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `scripts/validate-phase-21.py` | Evidence, privacy, provenance, and final-seal validator | VERIFIED | Compiles; validates the complete current chain and fails closed when the seal lacks paired recovery evidence. |
| `scripts/restore-solidstats-memory.py` | Backup/restore, absent-target, parity, and alias control | VERIFIED | Substantive controller; named stage-machine and alias rollback tests pass. |
| `scripts/cutover-solidstats-memory.sh` | Reversible cutover, recovery, rollback/forward, and activation orchestration | VERIFIED | Bash syntax and both built-in self-tests pass. |
| `scripts/probe-solidstats-memory.py` | Authenticated MCP and behavior matrix | VERIFIED | Substantive protocol client; auth loopback fixture and synthetic contract coverage pass. |
| `scripts/configure-solidstats-memory-client.py` | Exact client policy, transaction, retirement, and token isolation | VERIFIED | Atomic exchange and complete registration-subtree validation are present and covered by named tests. |
| `k8s/memory/05-rbac.yaml`, `30-network-policy.yaml`, `40-backup.yaml` | Least-privilege scale path, private networking, and recurring backup | VERIFIED | 34-resource manifest validation passes; source has exact scale RBAC, projected token, default deny, and `Forbid` concurrency. |
| `21-BACKUP-RESTORE-EVIDENCE.json`, `21-CUTOVER-EVIDENCE.json`, `21-RECOVERY-EVIDENCE.json`, `21-CUTOVER-SEAL.json` | Value-free live restore, cutover, recovery, and acceptance evidence | VERIFIED | All four exist, schemas/aggregate gates validate, and their predecessor SHA-256 chain matches current files. |
| `tests/test-memory-cutover-contract.py`, `tests/test-memory-runtime-contract.py`, `tests/test-memory-operator-contract.py`, `tests/test-memory-qdrant-jwt-contract.py` | Failure-injection and contract coverage | VERIFIED | Full Phase 21 test set is 224/224 passing when the two loopback fixtures are run outside the restricted socket sandbox. |

<!-- markdownlint-enable MD013 -->

## Key Link Verification

<!-- markdownlint-disable MD013 -->

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Restore controller | Phase 20 handoff and parity report | Recomputed digest bindings before private restore work | WIRED | Current handoff/parity SHA-256 values equal the backup evidence bindings; chain validator passes. |
| Backup evidence | Cutover evidence | `prior_evidence_sha256` and `input_digests.backup_restore_evidence_sha256` | WIRED | Both equal the current backup evidence SHA-256. |
| Cutover evidence | Recovery evidence | `cutover_evidence_sha256` | WIRED | Recovery references the current cutover evidence SHA-256. |
| Recovery evidence | Final seal | `recovery_evidence_sha256` | WIRED | Paired validation succeeds; standalone seal validation fails closed without recovery evidence. |
| Cutover controller | MCP/client configuration | Exact `codex mcp add/get/remove` plus policy transaction | WIRED | Exact `solidstats_memory` calls and token binding are present; retirement test passes. |
| Cutover controller | nginx public route | Private shared-site patch, byte backup, test/reload, and exact rollback | WIRED | The direct plan filename was superseded during Plan 21-03 by the stricter shared-site patch template; current `NGINX_TEMPLATE` points to `solidstats-memory-shared-cutover.patch.template`, whose renderer preserves the sibling route and is validated with all nginx templates. |

<!-- markdownlint-enable MD013 -->

## Data-Flow Trace (Level 4)

<!-- markdownlint-disable MD013 -->

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| Backup/restore evidence | package, target-absence, restore, parity aggregates | Live operator backup/restore run | Four-member package and 19,534-record parity are validator-bound | FLOWING |
| Cutover evidence | predecessor, live audit, final probe digests | Operator journal plus authenticated MCP/public probes | Digest-bound `CLIENT_ADDED` evidence | FLOWING |
| Recovery evidence | API-control, backup-consistency, reboot, rollback/forward aggregates | Remote operator results plus five behavior probes | Collector derives requirement booleans from actual result files, not literals | FLOWING |
| Cutover seal | ISO/OPS requirements and prohibitions | Recovery/cutover predecessor evidence | Validator requires exact booleans and predecessor SHA-256 | FLOWING |

<!-- markdownlint-enable MD013 -->

## Requirements Coverage

<!-- markdownlint-disable MD013 -->

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| ISO-01 | 21-01, 21-03, 21-04 | Exact `solidstats_memory`; no legacy `mempalace` after cutover | SATISFIED | Client policy enforces separated token subtrees; final seal has `iso_01`, `legacy_client_absent`, and `new_client_live` all true. |
| ISO-03 | 21-01, 21-02, 21-03, 21-04 | Qdrant private; authenticated MemPalace public at `/solidstats/mcp` | SATISFIED | ClusterIP/default-deny manifests validate; evidence records public 6333/6334 negatives and authenticated MCP; named auth fixture passes. |
| OPS-02 | 21-01, 21-02, 21-04 | Qdrant snapshot plus metadata archive, manifest, and checksums under the accepted backup prefix | SATISFIED | Backup evidence requires four members, inventory, download, and checksums; recovery adds template, quiescence, metadata equality, resumption, and activation proof. |
| OPS-03 | 21-01, 21-02, 21-03, 21-04 | Isolated restore before cutover; never target active collection | SATISFIED | Absent-target enforcement, exact 19,534-record parity, unchanged prestate, retained inventory, and no destructive calls are required by source and sealed evidence. |
| OPS-05 | 21-01, 21-02, 21-03, 21-04 | Auth, MCP behavior, recall/miss/archive/capture/read-after-write, restart, and reboot recovery | SATISFIED | Probe matrix, cutover/recovery evidence, ordered restarts, changed boot ID, rollback/forward, and self-test all pass. |

<!-- markdownlint-enable MD013 -->

No orphaned Phase 21 requirement was found. Phase 22 is limited to archive
distillation and does not defer any unsatisfied Phase 21 requirement.

## Behavioral Spot-Checks

<!-- markdownlint-disable MD013 -->

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full local Phase 21 suite | `timeout 150s nice -n 10 ionice -c3 python3 -B -m unittest …` | 222 passed in the restricted sandbox; its only two errors occurred before test code while binding local loopback sockets. | PARTIAL ENVIRONMENT |
| Loopback auth transport fixture | `python3 -B tests/test-memory-cutover-contract.py MemoryCutoverContractTests.test_http_transport_handles_real_auth_rejections_and_strict_successes` | 1 passed (0.514s) outside the socket-restricted sandbox. | PASS |
| Loopback Qdrant JWT fixture | `python3 -B tests/test-memory-qdrant-jwt-contract.py RealQdrantJwtContractTests.test_exact_alias_physical_and_observer_claims` | 1 passed (0.621s) outside the socket-restricted sandbox. | PASS |
| Restore/cutover/recovery/client state transitions | Four named `MemoryCutoverContractTests` | 4 passed (0.016s): stage machine, alias rollback, recovery rejects readiness-only evidence, and pre-authorized client retirement. | PASS |
| Failure compensation order | `timeout 30s … bash scripts/cutover-solidstats-memory.sh --self-test` | `SELF_TEST PASSED`; `RECOVERY_SELF_TEST PASSED`. | PASS |
| Evidence and deployment contracts | Phase validator, manifest validator, nginx validator, Python compilation, Bash syntax | All passed; manifest validator checked 34 resources. | PASS |

<!-- markdownlint-enable MD013 -->

Together, the serial suite plus the two exact local-only loopback reruns are
224/224 passing. No server, Kubernetes cluster, S3 bucket, Docker daemon,
credential, or external network was contacted during this verification.

## Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probe is declared for Phase 21.
The live MCP probe is intentionally operator-gated and was not rerun under this
read-only verification scope. Its value-free artifacts were instead checked
through the current collector and validator, including the final digest chain.

## Anti-Patterns Found

<!-- markdownlint-disable MD013 -->

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `k8s/memory/*.yaml` and manifest validator | `MEMORY_OPERATOR_*` runtime placeholders | INFO | Deliberate fail-closed operator bindings. The normal validator rejects unresolved placeholders; CI can only use the explicit placeholder mode. |

<!-- markdownlint-enable MD013 -->

No `TBD`, `FIXME`, or `XXX` debt marker was found in the Phase 21 source set.
No rendering/data-flow stub, hardcoded empty output, or unwired critical
artifact was found.

## Review and Security Closure

- The initial review found eight issues; the re-review found five; the final
  review found three. Their fixes (`e76f1f2`, `0274d54`, `fa76991`,
  `0703200`, `29dbd1e`, `227e1d5`) are all ancestors of HEAD.
- The final closure audit is `PASS`. Current source independently confirms the
  two consequential closures: `renameat2(RENAME_EXCHANGE)` protects client
  publication and personal/SolidStats bearer variables are recursively
  separated and checked.
- `21-SECURITY.md` reports ASVS L2 `SECURED`, 18/18 threats closed, zero open.
  The relevant current boundaries were rechecked through source, manifest,
  evidence-chain, and behavior-test evidence rather than accepting the audit
  prose alone.

## Residual Notes

- The roadmap progress table still says Phase 21 is `1/4` and in progress even
  though all four plans and summaries are present. This is stale workflow
  metadata, not a missing implementation or evidence artifact; it was not
  edited under this verifier's scope.
- A later infrastructure or client-configuration change must produce a fresh
  value-free evidence chain. This verification proves the committed Phase 21
  state only.

---

_Verified: 2026-08-21T18:43:11Z_
_Verifier: the agent (gsd-verifier)_
