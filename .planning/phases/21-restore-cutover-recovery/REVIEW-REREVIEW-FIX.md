---
phase: 21-restore-cutover-recovery
fixed_at: 2026-08-21T17:50:46Z
review_path: .planning/phases/21-restore-cutover-recovery/REVIEW-REREVIEW.md
iteration: 2
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 21: Code Review Re-review Fix Report

**Fixed at:** 2026-08-21T17:50:46Z
**Source review:** `.planning/phases/21-restore-cutover-recovery/REVIEW-REREVIEW.md`
**Iteration:** 2

**Summary:**

- Findings in scope: 5
- Fixed: 5
- Skipped: 0
- Commit: `fa76991`
- Follow-up regression commit: `0703200`
- Token-isolation regression commit: `29dbd1e`

## Fixed Issues

### RR-CR-01: Alias lease authority can be bypassed or split by run

**Files modified:** `scripts/restore-solidstats-memory.py`,
`scripts/operate-solidstats-memory.py`, `scripts/cutover-solidstats-memory.sh`,
`tests/test-memory-cutover-contract.py`,
`tests/test-memory-operator-contract.py`

**Commit:** `fa76991`

**Applied fix:** Both writers now resolve one explicit shared canonical lease,
validate inherited descriptor path/inode plus the exact owner/run record, and
confirm the nonblocking exclusive lock. Run-local fallback leases were removed.

### RR-CR-02: Cleanup still does not reconcile an ambiguous delete result

**Files modified:** `scripts/restore-solidstats-memory.py`,
`scripts/operate-solidstats-memory.py`, `tests/test-memory-cutover-contract.py`,
`tests/test-memory-operator-contract.py`

**Commit:** `fa76991`

**Applied fix:** Alias restoration is now a bounded observation-driven loop that
re-observes after every submission outcome, retries only exact alias residue,
and fails closed on unrelated drift. Both cleanup timeout orderings are tested.

### RR-CR-03: Any MemPalace tool error is accepted as exact absence

**Files modified:** `scripts/solidstats_memory_backup_oracle.py`,
`k8s/memory/40-backup.yaml`, `scripts/validate-memory-manifests.py`,
`tests/test-memory-runtime-contract.py`

**Commit:** `fa76991`

**Applied fix:** The recurring backup imports an executable oracle pinned to
MemPalace v3.5.0 and accepts only the exact get-drawer not-found mapping. Tool
errors, malformed responses, availability failures, and still-present drawers
are rejected by the fake-response matrix.

### RR-CR-04: Client replacement still has an unprotected stale-write window

**Files modified:** `scripts/configure-solidstats-memory-client.py`,
`tests/test-memory-cutover-contract.py`

**Commit:** `fa76991`

**Applied fix:** Retirement and rollback re-read immediately before replacement
and use inode/digest compare-before-replace. Compensation preserves unrelated
external bytes, and late noncooperating inode replacements are refused without
temporary or result residue.

### RR-WR-01: Ambiguous capture recovery relies on incomplete semantic search

**Files modified:** `scripts/probe-solidstats-memory.py`,
`tests/test-memory-cutover-contract.py`

**Commit:** `fa76991`

**Applied fix:** Ambiguous capture cleanup now compares complete, bounded,
paginated `mempalace_list_drawers` inventories. It deletes only one
deterministically identified new drawer and proves the final inventory equals
the captured prestate; ANN search is not used for cleanup.

## Follow-up Regression Closure

### Complete MCP registration subtree retirement and rollback

**Files modified:** `scripts/configure-solidstats-memory-client.py`,
`tests/test-memory-cutover-contract.py`

**Commit:** `0703200`

**Applied fix:** Registration removal and compensation now operate on every TOML
table owned by `mcp_servers.<name>`, including nested `tools.*` tables. The
observable regression parses the retired configuration, proves the retired
server key is absent, preserves unrelated and legacy nested tables during
replacement rollback, and restores the exact pre-retirement bytes. The
compare-before-replace protections from `fa76991` remain covered.

### Distinct personal and SolidStats token bindings

**Files modified:** `scripts/configure-solidstats-memory-client.py`,
`scripts/cutover-solidstats-memory.sh`, `scripts/probe-solidstats-memory.py`,
`tests/test-memory-cutover-contract.py`

**Commit:** `29dbd1e`

**Applied fix:** The personal registration is preserved with
`MEMPALACE_PERSONAL_MCP_TOKEN`, while the replacement registration, probes, and
cutover controller require exactly `MEMPALACE_SOLIDSTATS_MCP_TOKEN`. The
ambiguous legacy `MEMPALACE_MCP_TOKEN` and the personal binding are rejected for
the replacement client. Forward, nested-subtree retirement, exact restore,
replacement rollback, and concurrent-write tests prove that each transaction
changes only its target registration and leaves the personal binding intact.

## Verification

Verification ran in the isolated Phase 21 worktree.

- Targeted failure-injection tests for all five findings passed.
- Full Phase 21 suite: 159 of 161 tests passed inside the filesystem sandbox;
  the two loopback-socket tests were blocked by sandbox `EPERM` before tested
  code and both passed in a narrow loopback-only rerun. All 161 tests passed.
- Python compilation and Bash syntax checks passed.
- Memory manifest validation passed for 34 resources.
- Phase 21 evidence-chain validation passed.
- Cutover and recovery self-tests passed.
- ConfigMap/source byte synchronization and `git diff --check` passed.
- Follow-up subtree retirement, subtree rollback, and concurrent-write CAS
  regressions passed; Python compilation and `git diff --check` passed again.
- Eight token-isolation and retained subtree/CAS regressions passed; Python
  compilation, Bash syntax, and `git diff --check` passed again.
- No live Kubernetes, VPS, S3, Docker, credential, Phase 22, or push operation
  was performed.

## Required Instructions Read

- `/home/afgan0r/.agents/skills/gsd-code-review/SKILL.md`
- `/home/afgan0r/.agents/skills/git-commit/SKILL.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-project-standards/SKILL.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-project-standards/references/ci-cd-pattern.md`
- `/home/afgan0r/Projects/SolidGames/skills/solidstats-shared-planning-standards/SKILL.md`
- `.agents/skills/kubernetes-specialist/SKILL.md`
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
- `AGENTS.md`

---

_Fixed: 2026-08-21T17:50:46Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 2_
