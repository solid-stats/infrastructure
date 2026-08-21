---
phase: 21-restore-cutover-recovery
audited: 2026-08-22
status: secured
asvs_level: 2
block_on: high
threats_total: 18
threats_closed: 18
threats_open: 0
head: dbce5640d743a9cf9a8d209d3b21b56f4fbbda93
---

# Phase 21 Security Audit

## SECURED

**Phase:** 21 — Restore, Cutover, and Recovery  
**Threats Closed:** 18/18  
**ASVS Level:** 2  
**Blocking threshold:** high  
**Audited tree:** `dbce5640d743a9cf9a8d209d3b21b56f4fbbda93`

Every declared mitigation is implemented at the boundary that receives the
threatened input or controls the privileged transition. No critical, high,
medium, or low threat remains open. Under the configured ASVS Level 2 policy,
the Phase 21 release gate is therefore secured.

## Audit Scope and Method

This audit verifies the four Phase 21 threat models and their combined
implementation at the requested exact local tree. It does not infer closure
from plans, summaries, or review prose. Each threat was traced to the relevant
restore, cutover, client, Kubernetes, backup, host-guard, and evidence boundary,
then exercised with bounded value-free checks where a targeted test existed.

Repository freshness was established before substantive inspection:

- The worktree branch is `worktree-agent-p21-02-wave1` with no upstream.
- `origin` was refreshed with `git fetch --prune origin`.
- The requested local tree is exactly
  `dbce5640d743a9cf9a8d209d3b21b56f4fbbda93`.
- The remote milestone ref is older than the requested local tree, so the exact
  requested tree, rather than the remote ref, is the audit source of truth.
- The pre-existing untracked `.21-02-restore.lock` was preserved and remained
  mode `0600`.

The first repository action was `ast-index rebuild`. Structural navigation then
used `outline`, `explore`, `symbol`, `usages`, `refs`, and `callers` across the
restore, cutover, operator, client, backup guard/oracle, and evidence paths.

## Threat Verification

<!-- markdownlint-disable MD013 -->

| Threat ID | Category | Severity | Disposition | Status | ASVS L2 implementation evidence |
| --- | --- | --- | --- | --- | --- |
| T-21-01 | Tampering | critical | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:606` rejects occupied targets before private restore reads and rechecks the transition; `scripts/validate-phase-21.py:720` binds the transition into the sealed chain. The occupied-target contract test passed. |
| T-21-02 | Tampering | high | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:330` recomputes Phase 20 artifact digests, schema, provenance, and tool identity before restore; the public evidence and seal are digest-linked by `scripts/validate-phase-21.py:776`. Drift fails before private bundle reads. |
| T-21-03 | Information disclosure | critical | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:1785` creates private state with exclusive/no-follow semantics and mode `0600`; `scripts/probe-solidstats-memory.py:270` bounds raw probe storage under `0700`/`0600`; `scripts/validate-phase-21.py:323` recursively rejects private paths, token names, secret-shaped keys, and non-allowlisted fields from public evidence. Private-surface rejection tests passed. |
| T-21-04 | Information disclosure | high | mitigate | CLOSED | `k8s/memory/10-qdrant.yaml:12` exposes Qdrant only as an internal ClusterIP service with JWT RBAC; `k8s/memory/30-network-policy.yaml:42` applies default deny and exact reciprocal TCP/6333 permits. `scripts/probe-solidstats-memory.py:622` negatively probes every resolved public address. Manifest and public-boundary checks passed. |
| T-21-05 | Tampering | critical | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:85` and `scripts/operate-solidstats-memory.py:113` use one canonical shared alias lease and validate inherited descriptor, inode, owner, and run identity. Restore/cutover performs compare-and-swap, readback, and bounded lost-ACK reconciliation. The final client transaction uses Linux `renameat2(RENAME_EXCHANGE)` at `scripts/configure-solidstats-memory-client.py:184`, with inode/byte verification and fail-closed recovery. Twenty-two alias/exchange-focused tests passed. |
| T-21-06 | Denial of service | high | mitigate | CLOSED | `scripts/cutover-solidstats-memory.sh:65` uses bounded SSH, strict host-key/identity handling, a durable mode-`0600` journal, one-at-a-time restarts, and reverse-order compensation. `scripts/operate-solidstats-memory-cutover-remote.sh:1008` verifies boot identity and bounded reconnect before behavior probes. Cutover and recovery self-tests passed. |
| T-21-07 | Spoofing | critical | mitigate | CLOSED | `scripts/collect-phase-21-recovery-evidence.py:205` derives success only from exact operation outputs; `scripts/validate-phase-21.py:615` requires every recovery boolean, run identity, transition sequence, and metadata digest to agree. The chain validator rejects a seal without its paired recovery evidence and accepts the exact paired chain. |
| T-21-08 | Denial of service | medium | mitigate | CLOSED | The offline health fixture exercises healthy, malformed, empty, and timeout paths without external time or network dependence in `tests/test-memory-runtime-contract.py:1601` and `:1628`. Both targeted fixture tests passed and stable metrics remain bounded to the declared surface. |
| T-21-09 | Denial of service | high | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:657` computes required restore space from the exact package and checks target capacity before mutation. Capacity failure is recorded without secret or host detail. Three capacity-focused tests passed. |
| T-21-10 | Repudiation | medium | mitigate | CLOSED | `scripts/restore-solidstats-memory.py:720` requires one complete deterministic package; `:923` binds archive, object prefix, checksums, inventory, and storage readback to the run. Exact-package, collision, and checksum tests passed, and the sealed backup evidence contains only value-free digests/counts. |
| T-21-11 | Spoofing | high | mitigate | CLOSED | `scripts/probe-solidstats-memory.py:165` requires the exact HTTPS `/solidstats/mcp` endpoint and `:595` proves missing-token, invalid-token, untrusted-origin, and valid-auth behavior. `scripts/configure-solidstats-memory-client.py:350` enforces the same exact URL. The synthetic auth/session/schema/behavior fixture passed. |
| T-21-12 | Elevation of privilege | medium | mitigate | CLOSED | `scripts/configure-solidstats-memory-client.py:24` separates personal and SolidStats token variables, defines the exact seven-tool allowlist, and rejects forbidden tool fragments. `:550` recursively validates the complete registration subtree and sole bearer reference, not selected TOML leaves. Collision and retirement tests passed. |
| T-21-13 | Tampering | high | mitigate | CLOSED | `scripts/cutover-solidstats-memory.sh:362` journals exact rollback/forward state and compensates in reverse order; `:516` re-arms the forward cycle only after restored behavior. The client exchange at `scripts/configure-solidstats-memory-client.py:235` verifies unrelated bytes and supports recovery from each interruption point. Recovery self-tests and atomic-exchange tests passed. |
| T-21-14 | Elevation of privilege | medium | mitigate | CLOSED | `scripts/configure-solidstats-memory-client.py:782` removes the exact legacy registration only inside one pre-authorized transaction after full old/new subtree validation. `scripts/collect-phase-21-recovery-evidence.py:254` proves activation precedes pre-retirement readback and retirement. Early removal is a sealed prohibition. |
| T-21-15 | Repudiation | high | mitigate | CLOSED | `k8s/memory/40-backup.yaml:22` owns writer quiescence/restoration and exact source-before/source-after/archive checks. `scripts/cutover-solidstats-memory.sh:491` restores the writer and suspends the schedule on failure. `scripts/guard-solidstats-memory-backup.sh` accepts only exact PASS markers and invokes the fixed suspension helper on failure; the service/timer unit trust chain is root-owned and hardened. Backup-oracle and control-plane tests passed. |
| T-21-16 | Elevation of privilege | high | mitigate | CLOSED | `k8s/memory/05-rbac.yaml:1` grants the backup ServiceAccount only exact namespaced Deployment get/scale operations and Pod list. `k8s/memory/40-backup.yaml:724` projects an audience-bound token with a 600-second lifetime and mode `0400`; default API-token automount is disabled. Identity-drift and RBAC-broadening tests passed. |
| T-21-17 | Information disclosure | high | mitigate | CLOSED | `k8s/memory/05-rbac.yaml:40` limits backup API egress to the runtime-measured single host prefix and exact port. `scripts/operate-solidstats-memory-cutover-remote.sh:1635` creates fresh positive, NetworkPolicy-negative, and RBAC-negative proof pods and requires exact status outcomes before activation. Manifest validators reject broadened controls. |
| T-21-18 | Spoofing | high | mitigate | CLOSED | `scripts/operate-solidstats-memory-cutover-remote.sh:1501` discovers API candidates only from the Kubernetes Service and ready EndpointSlices, measures each candidate through the three control probes, selects the Service or exactly one endpoint, and records only a value-free mode/digest. `:1892` rechecks all controls before recovery completion. |

<!-- markdownlint-enable MD013 -->

## ASVS Level 2 Boundary Assessment

The L2 boundary check produced these conclusions:

- Authentication and authorization are enforced at the public MCP and
  Kubernetes API boundaries, not only in orchestration callers.
- Alias authority is enforced by a shared filesystem lease plus atomic exchange,
  compare/readback, and lost-ack reconciliation at every writer path.
- Qdrant is not publicly published; workload and backup paths are explicit in
  NetworkPolicy, and public-address negatives cover the whole resolved set.
- Backup writer privilege is short-lived, audience-bound, namespaced, and
  independently constrained by both RBAC and measured NetworkPolicy.
- Secret-bearing state stays in private mode-controlled files or Kubernetes
  Secrets. Public evidence is recursively allowlisted and value-free.
- Recovery, reboot, rollback, forward re-arm, backup activation, and legacy
  retirement are ordered transitions whose exact identities and digests are
  required by the final seal.

## Requirement Coverage

<!-- markdownlint-disable MD013 -->

| Requirement | Security-relevant closure evidence |
| --- | --- |
| ISO-01 | Deterministic package, backup source, inventory, checksums, and restored state are bound to one provenance chain; target absence and capacity are checked before mutation. |
| ISO-03 | Alias ownership, public MCP behavior, internal Qdrant isolation, and exact retained-collection verification are proven before sealed cutover completion. |
| OPS-02 | Backup activation requires writer quiescence/restoration, source/archive equality, upload inventory, redownload/checksum, deletion, not-found, and behavior oracles. |
| OPS-03 | Reboot recovery requires changed boot identity, bounded reconnect, retained inventory, public behavior, backup resumption, and exact rollback/forward proof. |
| OPS-05 | The final seal requires every named recovery gate and prohibition, including no early legacy removal, no public Qdrant, and no retained-data deletion. |

<!-- markdownlint-enable MD013 -->

## Review and Fix Chain

The audit included the entire Phase 21 review/fix/pass chain through the audited
tree:

- Initial and repeated reviews: `REVIEW.md`, `REVIEW-REREVIEW.md`, and
  `REVIEW-FINAL.md`.
- Fix records: `REVIEW-FIX.md`, `REVIEW-REREVIEW-FIX.md`, and
  `REVIEW-FINAL-FIX.md`.
- Fix commits `e76f1f2`, `0274d54`, `fa76991`, `0703200`, `29dbd1e`, and
  `227e1d5` were inspected in history and against the current implementation.
- Commit `227e1d5` supplies the final atomic exchange, complete TOML subtree and
  token-isolation validation, and bounded inventory checks.
- `REVIEW-PASS.md` records zero remaining findings at `2db6199`; subsequent
  commit `dbce564` only seals that final review artifact and does not change the
  audited implementation.

Documentation did not substitute for the implementation checks above.

## Exact Bounded Checks

No live Kubernetes, VPS, S3, DNS, network, credential, Docker, or heavy parallel
operation was performed. The following local checks passed:

- `ast-index rebuild`, followed by structural `outline`, `explore`, `symbol`,
  `usages`, `refs`, and `callers` queries.
- `python3 -B scripts/validate-phase-21.py --check-chain ...` validated the
  exact backup, cutover, recovery, and seal chain.
- Standalone backup, cutover, and recovery evidence validation passed.
- Standalone seal validation rejected the seal without paired recovery evidence,
  as required by its fail-closed contract; paired chain validation passed.
- `python3 -B scripts/validate-memory-manifests.py
  --allow-operator-placeholders` validated 34 resources.
- All three nginx templates passed
  `scripts/validate-memory-nginx.py --allow-operator-placeholders`.
- `bash -n` passed for the cutover, remote operator, guard, and suspension
  scripts.
- `bash scripts/cutover-solidstats-memory.sh --self-test` reported both
  `SELF_TEST PASSED` and `RECOVERY_SELF_TEST PASSED`.
- Forty-eight focused unit cases passed across alias lease/lost-ack handling,
  client atomic exchange, complete token-subtree collision rejection, retirement,
  recovery evidence, public evidence schema, occupied targets, exact packages,
  capacity, backup control plane/oracle/identity, reciprocal isolation,
  auth/session behavior, and stable/unhealthy offline metrics.

`git diff --check` passed after formatting. Final status contains only this
new audit artifact and the pre-existing, preserved restore lock.

## Live Value-Free Evidence Reviewed

The checked evidence set is:

- `21-BACKUP-RESTORE-EVIDENCE.json`
- `21-CUTOVER-EVIDENCE.json`
- `21-RECOVERY-EVIDENCE.json`
- `21-CUTOVER-SEAL.json`

The evidence was parsed through the repository validators and inspected without
reading credentials or secret-bearing configuration. Its public content consists
of booleans, counts, modes, run identities, sequences, and cryptographic digests.
The chain binds backup/restore, cutover, reboot/recovery, retained state, public
behavior, backup resumption, rollback/forward, and final prohibitions.

The current-machine client authentication split and shared-configuration commit
`79c85d3faa542dd` were treated only as external corroborating evidence. No token
value, `.env`, `.env.*`, `.secrets`, or secret-bearing config content was read.

## Residual Risks and Operational Assumptions

These are non-blocking residual conditions, not open declared threats:

- The repository evidence is a sealed snapshot from the Phase 21 execution; this
  read-only audit did not mutate live infrastructure to reproduce it. A later
  environment change requires a new evidence chain rather than reuse of this seal.
- Source manifests intentionally retain operator-bound placeholders, and
  `05-rbac.yaml` is excluded from the CI workload apply set. The runtime operator
  must measure and bind the exact API prefix/port; validation and cutover fail
  closed if it cannot.
- `renameat2(RENAME_EXCHANGE)` is a Linux filesystem requirement. Unsupported or
  unverifiable exchange semantics fail closed instead of weakening the client
  transaction.
- Public evidence files may be repository-readable because they are recursively
  value-free. Private restore/probe/lock state remains mode `0600` under private
  directories, and the retained `.21-02-restore.lock` was not removed or replaced.
- Live client-token separation remains machine-local external state. Repository
  closure rests on the transaction's exact token/subtree validation; the external
  commit is corroboration, not a substitute for that enforcement.

## Unregistered Flags

None. The four summaries contain no `## Threat Flags` section. Their documented
implementation deviations map to registered threats: host guard/systemd to
T-21-15 through T-21-17, client editor/token split to T-21-12 and T-21-14,
alias lease/lost-ACK behavior to T-21-05, and evidence provenance/sealing fixes
to T-21-03, T-21-07, and T-21-15.

## Required Files Read

### Audit and project skills

- `/home/afgan0r/.agents/skills/gsd-secure-phase/SKILL.md`
- `/home/afgan0r/.codex/gsd-core/workflows/secure-phase.md`
- `/home/afgan0r/.codex/gsd-core/references/security-asvs-levels.md`
- `/home/afgan0r/.codex/gsd-core/references/agent-skills-bootstrap.md`
- `/home/afgan0r/.codex/gsd-core/references/ui-brand.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-project-standards/SKILL.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-project-standards/references/ci-cd-pattern.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-planning-standards/SKILL.md`
- `.agents/skills/solidstats-process-skill-feedback/SKILL.md`
- `.agents/skills/kubernetes-specialist/SKILL.md`

### Kubernetes specialist references

- `.agents/skills/kubernetes-specialist/references/configuration.md`
- `.agents/skills/kubernetes-specialist/references/cost-optimization.md`
- `.agents/skills/kubernetes-specialist/references/custom-operators.md`
- `.agents/skills/kubernetes-specialist/references/gitops.md`
- `.agents/skills/kubernetes-specialist/references/helm-charts.md`
- `.agents/skills/kubernetes-specialist/references/multi-cluster.md`
- `.agents/skills/kubernetes-specialist/references/networking.md`
- `.agents/skills/kubernetes-specialist/references/service-mesh.md`
- `.agents/skills/kubernetes-specialist/references/storage.md`
- `.agents/skills/kubernetes-specialist/references/troubleshooting.md`
- `.agents/skills/kubernetes-specialist/references/workloads.md`

### Repository instructions and Phase 21 planning

- `AGENTS.md`
- `.planning/config.json`
- `.planning/REQUIREMENTS.md`
- `.planning/phases/21-restore-cutover-recovery/21-CONTEXT.md`
- `.planning/phases/21-restore-cutover-recovery/21-RESEARCH.md`
- `.planning/phases/21-restore-cutover-recovery/21-VALIDATION.md`
- All four `21-01` through `21-04` plan files.
- All four `21-01` through `21-04` summary files.

### Review, evidence, and implementation

- All seven Phase 21 review/fix/pass artifacts named in the review-chain section.
- All four value-free Phase 21 JSON evidence/seal artifacts named above.
- Restore/operator/client/probe/cutover/remote-operator/evidence collector and
  Phase 21 validator scripts.
- Backup guard/suspension scripts and their systemd service/timer units.
- `k8s/memory/05-rbac.yaml`, `10-qdrant.yaml`, `20-mempalace.yaml`,
  `30-network-policy.yaml`, and `40-backup.yaml`.
- Memory manifest/nginx renderers and validators.
- `.github/workflows/deploy-memory.yml`.
- Targeted Phase 21 cutover, operator, and runtime contract tests.

**threats_open:** 0
