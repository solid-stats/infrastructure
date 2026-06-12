---
phase: 08-automated-restore-drill
status: revised_pass
issue_count: 2
blockers: 1
warnings: 1
check_date: 2026-06-13
---

# Phase 8 Plan Verification Report

**Phase Goal:** Operator can prove on demand that the latest S3 backup restores into an ephemeral scratch PostgreSQL with passing sanity checks, never touching live data, with the drill kept out of the CD deploy path.

**Plans Verified:** 3 (08-01, 08-02, 08-03)

**Overall Status:** NEEDS_REVISION

---

## Summary

Phase 8 plans are well-structured and cover all four requirements (DRILL-01..04) with good Kubernetes hardening and secret handling. However, **one critical implementation gap** must be fixed before execution: the refuse-if-live-host safety check (Step 2 in 08-01 Task 1) is described in the plan but not implemented in the actual shell script. This guard is essential for DRILL-01's core guarantee that the drill cannot accidentally touch the live `postgres-0` pod or `postgres-data` PVC.

Additionally, there is a minor XML encoding issue in Task 2's verify block that should be corrected.

---

## Dimension Checks

### 1. Requirement Coverage

**Status:** ✅ PASS (all requirements assigned to tasks)

| Requirement | Plan | Task | Coverage |
|-------------|------|------|----------|
| DRILL-01 | 08-01 | 1, 2 | ✓ Scratch restore via Job; guarded DB name; emptyDir isolation |
| DRILL-02 | 08-01 | 1 | ✓ Sanity assertions (table count, row count, dump list); captured-result pattern |
| DRILL-03 | 08-01, 08-03 | 1; 1 | ✓ Teardown + DRILL_RESULT=PASS/FAIL evidence line; ttlSecondsAfterFinished cleanup |
| DRILL-04 | 08-01, 08-02, 08-03 | 1; 1; 1 | ✓ Subdirectory placement; validate-staging.py guard; docs updated |

All requirements are mapped to explicit tasks. ✓

---

### 2. Task Completeness

**Status:** ⚠️ PARTIAL (one task missing critical implementation; one has XML encoding issue)

#### Plan 08-01, Task 1: Restore-drill Job manifest

**Fields Present:** ✓ Files, ✓ Action, ✓ Verify, ✓ Done

**Content Assessment:**

- **BLOCKER - Step 2 Missing Implementation:** The action text describes a refuse-if-live-host check:
  ```
  Step 2 — refuse-if-live-host safety check (per DRILL-01 defense-in-depth):
  if the environment variable POSTGRES_HOST exists and equals "postgres" (the live Service name),
  emit "ERROR: PGHOST resolves to live Service — refusing drill" and exit 1.
  ```
  However, this check does **not appear in the actual shell script code** that follows. The script jumps directly from Step 1 (env setup) to Step 3 (initdb), skipping Step 2's guard entirely.
  
  **Why this is critical:** DRILL-01 requires "never touching live postgres-0/postgres-data". The three defenses are:
  1. Guarded DB name `solid_stats_drill` (present ✓)
  2. PGHOST=localhost hard-coded (present ✓)
  3. Refuse-if-live-host check (described ✓ but **NOT implemented** ❌)
  
  Without Step 2's guard, the only protection against operator misconfiguration is the hard-coded PGHOST. If someone later patches the PGHOST env or the manifest env-block gets altered, the guard should refuse the operation. Its absence is a **BLOCKER**.

  **Fix required:** Add the refuse-if-live-host check immediately after Step 1 env setup and before Step 3 initdb. Code should resemble:
  ```sh
  if [ "${POSTGRES_HOST:-}" = "postgres" ]; then
    echo "ERROR: POSTGRES_HOST resolves to live Service — refusing drill"
    exit 1
  fi
  ```

#### Plan 08-01, Task 2: Operator script

**Fields Present:** ✓ Files, ✓ Action, ✓ Verify, ✓ Done

**Content Assessment:**

- **WARNING - XML Encoding:** The `<verify>` block contains:
  ```xml
  <automated>bash -n scripts/restore-drill.sh &amp;&amp; grep -q 'DRILL_RESULT=' ...
  ```
  The `&amp;` is XML-encoded ampersand, which may cause parsing issues if the verification system interprets the raw XML. Should be `&&` (plain ampersand in XML attribute content is not standard; CDATA section or unescaped && after closing quote may be safer, or the entity stays and the parser handles it).
  
  **Note:** This is a warning, not a blocker, because XML parsers will handle `&amp;` correctly. However, when this is rendered or interpreted as a shell command, the double-ampersand must be unescape or interpreted correctly.

- **All other fields correct:**
  - Mirrors `backup-postgres-now.sh` style ✓
  - `set -euo pipefail` ✓
  - `required()` helper for env checks ✓
  - Exit code 64 for config errors ✓
  - `DRILL_RESULT=` extraction ✓
  - Cleanup with `|| true` ✓

#### Plan 08-02, Task 1: Validate-staging.py extension

**Fields Present:** ✓ Files, ✓ Action, ✓ Verify, ✓ Done

**Content Assessment:**

- **PASS:** DRILL-04 guard implementation is explicit and placed correctly after the existing manifest checks and before the manifest loop.
- **PASS:** Bash -n check for `restore-drill.sh` added to `validate_scripts()`.
- **Scope is tight:** Two additions, no rewrite of existing code.

#### Plan 08-03, Task 1: Update docs

**Fields Present:** ✓ Files, ✓ Action, ✓ Verify, ✓ Done

**Content Assessment:**

- **PASS:** Runbook is clear and complete.
- **PASS:** Explains what drill does (restore, assert) and what it does NOT do (touch live data, write S3, auto-schedule).
- **PASS:** DRILL_RESULT=PASS example shown.
- **PASS:** DRILL-04 subdirectory placement explained.
- **PASS:** Cadence guidance provided.

#### Plan 08-03, Checkpoint (human-verify)

**Gate Type:** Blocking checkpoint

**Content Assessment:**

- **PASS:** Verification steps are concrete (run drill, confirm PASS, check live postgres untouched).
- **PASS:** Requires operator to paste evidence line before approval.
- **Note:** This is correct pattern for infrastructure gate; live drill is the final proof of DRILL-01..03.

---

### 3. Dependency Correctness

**Status:** ✅ PASS

- **Wave 1:** 08-01, 08-02 both have `depends_on: []` (independent, can run parallel) ✓
- **Wave 2:** 08-03 has `depends_on: ["08-01", "08-02"]` (waits for both Wave 1 tasks) ✓
- **No cycles:** Dependency graph is a DAG ✓
- **No forward references:** No plan references a future plan ✓
- **Wave assignment:** Wave = max(depends_on) + 1 = 1 + 1 = 2 for 08-03 ✓

---

### 4. Key Links Planned

**Status:** ✅ PASS

| From | To | Via | Plan | Task | Verified |
|------|----|----|------|------|----------|
| scripts/restore-drill.sh | k8s/staging/restore-drill/70-restore-drill.yaml | `kubectl apply -f` | 08-01 | 2 | ✓ Action mentions manifest path |
| Job manifest | postgres-auth Secret | secretKeyRef | 08-01 | 1 | ✓ Env block references secret |
| Job manifest | server-2-runtime Secret | secretKeyRef | 08-01 | 1 | ✓ S3 creds via secret |
| docs/backup-restore.md | scripts/restore-drill.sh | Usage command | 08-03 | 1 | ✓ Runbook references script |

All critical wiring is documented. ✓

---

### 5. Scope Sanity

**Status:** ✅ PASS

| Plan | Tasks | Files Modified | Complexity | Assessment |
|------|-------|-----------------|------------|-------------|
| 08-01 | 2 | 2 files | Medium (K8s Job + bash script) | Within budget; Job spec is complex but well-structured |
| 08-02 | 1 | 1 file | Low (Python script additions only) | Minimal scope; edits only |
| 08-03 | 2 (1 task + 1 checkpoint) | 1 file (docs) | Low (documentation + gate) | Appropriate for docs + verification |

Total: 4 logical tasks (3 implementation + 1 human gate) across 3 plans. Scope is reasonable. ✓

---

### 6. Must-Haves Derivation

**Status:** ✅ PASS

All `must_haves` are user-observable and traceable to phase goal:

**Plan 08-01 truths:**
- "Operator can apply the drill Job and it runs in namespace solid-stats-staging" → observable: Job exists and runs
- "Job pod initializes its own scratch postgres on emptyDir, never connecting to Service postgres" → observable: pod exits cleanly, live postgres untouched
- "Script detects PGHOST != localhost at startup and exits 1" → observable: **DESCRIBED but IMPLEMENTATION MISSING** ❌
- "Latest S3 backup is discovered via lexicographic max..." → observable: logs show backup_id
- "Sanity assertions emit PASS/FAIL line" → observable: DRILL_RESULT= in logs
- "Scratch DB and postgres are torn down..." → observable: no leftover DB in live postgres, logs show exit code

**Plan 08-02 truths:**
- "python3 scripts/validate-staging.py exits 0 when no drill yaml at k8s/staging depth-1" → observable: validator output
- "validate-staging.py exits 1 if drill yaml at depth-1" → observable: CI failure message

**Plan 08-03 truths:**
- "docs/backup-restore.md contains automated drill section with restore-drill.sh usage" → observable: grep for "restore-drill.sh"
- "Runbook explains: drill never touches postgres-0 / postgres-data" → observable: docs contain safety notes
- "Live drill produces DRILL_RESULT=PASS evidence before phase sign-off" → observable: evidence captured in checkpoint

Assessment: Truths are concrete and measurable. However, truth #3 in 08-01 cannot be verified because the implementation is missing. ⚠️

---

### 7. Context Compliance

**Status:** ✅ PASS (no contradictions; all locked decisions implemented)

Checking against 08-CONTEXT.md `<decisions>` section:

**Locked Decision:** "Scratch PostgreSQL topology: self-contained drill Job that runs OWN throwaway postgres process inside the drill pod (sidecar container or pg_ctl on emptyDir), so there is zero chance of touching postgres-data or the live Service."

- Plan 08-01 implements: pg_ctl initialization on emptyDir in Step 3 ✓
- Guarded DB name: solid_stats_drill (not solid_stats) ✓
- Refuse-if-live-host: **DESCRIBED but NOT IMPLEMENTED** ❌

**Locked Decision:** "Latest-backup discovery: aws s3 ls → lexicographic max → download solid_stats.dump"

- Plan 08-01 Step 4 implements: `aws s3 ls ... | sort -r | head -1` ✓

**Locked Decision:** "Sanity assertions: row-count / object checks, fail loudly = non-zero exit + clear log, NO teardown-masks-failure"

- Plan 08-01 Step 7 implements: captured-result pattern ✓

**Locked Decision:** "Teardown + evidence: drop scratch DB / remove emptyDir, emit structured result line (PASS/FAIL, backup_id, row counts, duration) to stdout/logs"

- Plan 08-01 Step 8 implements: dropdb + pg_ctl stop ✓
- Evidence line: DRILL_RESULT=PASS/FAIL with metrics ✓

**Locked Decision:** "Out-of-CD-path placement: SUBDIRECTORY (e.g., k8s/staging/restore-drill/) so -maxdepth 1 never matches. Operator script for on-demand apply. Offline validator check."

- Plan 08-01 Task 1: k8s/staging/restore-drill/70-restore-drill.yaml ✓
- Plan 08-01 Task 2: scripts/restore-drill.sh ✓
- Plan 08-02 Task 1: validate-staging.py guard ✓

**No contradictions detected.** However, the refuse-if-live-host guard (locked decision) is not fully implemented. ⚠️

---

### 8. Kubernetes Hardening

**Status:** ⚠️ MOSTLY PASS (hardening is correct but one critical guard is missing in logic, not structure)

**Manifest-level hardening (08-01 Task 1):**

| Control | Required | Present | Notes |
|---------|----------|---------|-------|
| ServiceAccount exists | ✓ | ✓ | `restore-drill` SA defined |
| No default SA | ✓ | ✓ | Explicit `serviceAccountName: restore-drill` |
| automountServiceAccountToken: false | ✓ | ✓ | Set in pod spec |
| allowPrivilegeEscalation: false | ✓ | ✓ | Set in container securityContext |
| fsGroup for file writes | ✓ | ✓ | fsGroup: 999 (postgres user) |
| Resource requests + limits | ✓ | ✓ | requests: cpu=100m, mem=512Mi; limits: cpu=1, mem=2Gi |
| Explicit namespace | ✓ | ✓ | solid-stats-staging |
| Image pinning | ✓ | ✓ | postgres:17-alpine (same as backup job) |
| imagePullPolicy: IfNotPresent | ✓ | ✓ | Set |
| ttlSecondsAfterFinished | ✓ | ✓ | 3600s (self-cleanup) |
| restartPolicy: Never | ✓ | ✓ | Set (no retries on failure) |
| backoffLimit: 0 | ✓ | ✓ | Set (fail loudly on first run) |

**Script-level hardening (logic, not structure):**

| Defense | Required | Implemented |
|---------|----------|-------------|
| PGHOST=localhost hard-coded | ✓ | ✓ Step 1 |
| Guarded DB name (solid_stats_drill) | ✓ | ✓ Step 6 |
| Refuse-if-live-host check | ✓ | **❌ MISSING** (described as Step 2, not in code) |
| No echo of AWS_*/POSTGRES_PASSWORD | ✓ | ✓ (uses --only-show-errors) |
| Captured result before teardown | ✓ | ✓ Step 7 (drill_result=0, assertions, then cleanup) |
| No process escapes (allowPrivilegeEscalation: false) | ✓ | ✓ |

**Assessment:** Structural hardening is excellent and complete. However, the refuse-if-live-host check is a **logical guard** that must be in the script but is missing. ❌

---

### 9. Threat Model Completeness

**Status:** ✅ PASS (threat models are detailed and comprehensive)

**Plan 08-01 threat_model:**

Covers STRIDE threats:
- T-08-01 (Tampering: drill → live Service) — mitigated by guarded DB name, PGHOST=localhost, and refuse-if-live-host check ✓
- T-08-02 (Tampering: mutate live solid_stats) — mitigated by guarded DB name (solid_stats_drill ≠ solid_stats) ✓
- T-08-03 (Disclosure: S3 creds in logs) — mitigated by Secrets, --only-show-errors, never echo AWS_* ✓
- T-08-04 (Tampering: manifest caught by CD glob) — mitigated by subdirectory placement, DRILL-04 guard ✓
- T-08-05 (Tampering: teardown masks assertion failure) — mitigated by captured-result pattern ✓
- T-08-06 (Elevation: postgres escapes container) — mitigated by allowPrivilegeEscalation: false, fsGroup, no privileged flag ✓
- T-08-07 (DoS: unbounded memory) — mitigated by resource limits (2Gi) ✓
- T-08-08, T-08-SC (Package legitimacy) — accepted; apk install of aws-cli is within container and proven in backup job ✓

All threats are identified and addressed. ✓

---

### 10. CLAUDE.md / AGENTS.md Compliance

**Status:** ✅ PASS

**From AGENTS.md (Kubernetes Safety):**

- No default ServiceAccount ✓ (uses `restore-drill` SA)
- automountServiceAccountToken: false ✓
- securityContext with non-root or restricted elevation ✓
- Resource requests/limits ✓
- Explicit namespace ✓
- Image pinning ✓

**From AGENTS.md (Script Style):**

- scripts/restore-drill.sh: `#!/usr/bin/env bash` ✓
- `set -euo pipefail` ✓
- `required()` helper for env vars ✓
- Exit code 64 for config errors ✓
- Remote kubectl execution via WireGuard ✓ (docs mention this)

**From AGENTS.md (Manifest Style):**

- Numeric filename prefixes ✓ (70-restore-drill.yaml follows 60-postgres-backup.yaml)
- Explicit namespace ✓
- Standard Kubernetes app labels ✓
- Image tags pinned ✓
- imagePullPolicy: IfNotPresent ✓

All conventions respected. ✓

---

### 11. VALIDATION.md Compliance

**Status:** ✅ PASS

**08-VALIDATION.md requires:**

- "All tasks have an offline check or documented live-drill verification" → 08-01 Tasks 1&2 have offline verify; 08-03 has live-drill gate ✓
- "DRILL-04 depth-1 guard added to validate-staging.py" → 08-02 Task 1 implements this ✓
- "One successful live drill run captured as evidence before verify-work" → 08-03 checkpoint requires this ✓

All validation requirements are addressed. ✓

---

## Issues Summary

### BLOCKER Issues

**Issue 1: Missing refuse-if-live-host Guard Implementation**

- **Dimension:** Task Completeness / DRILL-01 Requirement Coverage
- **Severity:** BLOCKER
- **Plan:** 08-01
- **Task:** 1 (Restore-drill Job manifest)
- **Location:** Step 2 in action text (described but not implemented in shell script)

**Description:**

The plan describes a safety check in Step 2:
```
Step 2 — refuse-if-live-host safety check (per DRILL-01 defense-in-depth):
if the environment variable POSTGRES_HOST exists and equals "postgres",
emit "ERROR: PGHOST resolves to live Service — refusing drill" and exit 1.
```

However, this check does not appear in the actual shell script within the `command` block. The script jumps from Step 1 (env setup) directly to Step 3 (initdb), completely skipping Step 2's guard.

**Why this is critical:**

DRILL-01 requires "never touching live postgres-0/postgres-data". The plan relies on three defense-in-depth layers:
1. **Guarded DB name:** `solid_stats_drill` (present ✓)
2. **Hard-coded PGHOST:** `PGHOST=localhost` (present ✓)
3. **Refuse-if-live-host check:** Must reject if env is misconfigured (MISSING ❌)

Without the third check, the only protection against operator error (e.g., someone later adds `POSTGRES_HOST=postgres` to the pod env or modifies the manifest) is the hard-coded PGHOST. A missing implementation of an explicitly-described safety control is a blocker.

**Fix required:**

Add the following code immediately after Step 1's env setup and before Step 3's initdb:

```sh
# Step 2 — refuse-if-live-host safety check
if [ "${POSTGRES_HOST:-}" = "postgres" ]; then
  echo "ERROR: POSTGRES_HOST resolves to live Service — refusing drill" >&2
  exit 1
fi
```

This guard must be present in the final manifest's command block, not just described in the action text.

---

### WARNING Issues

**Issue 1: XML Encoding in Task 2 Verify Block**

- **Dimension:** Task Completeness / Technical Quality
- **Severity:** WARNING
- **Plan:** 08-01
- **Task:** 2 (Operator script)
- **Location:** `<verify>` XML element

**Description:**

The verify block contains:
```xml
<automated>bash -n scripts/restore-drill.sh &amp;&amp; grep -q 'DRILL_RESULT=' ...
```

The `&amp;` is an XML-encoded ampersand. While this will be correctly decoded by an XML parser to `&&`, it may cause parsing issues or confusion if the verification system expects raw shell syntax.

**Recommendation:**

Either:
1. Change `&amp;&amp;` to `&&` (if the XML parser handles unescaped ampersands in attribute content), or
2. Wrap the command in a CDATA section, or
3. Ensure the downstream tool correctly decodes XML entities.

This is a minor issue and should not block execution if the verification system handles XML entities correctly.

---

## Verdict

### Current Status: **NEEDS_REVISION**

**Blockers:** 1 (refuse-if-live-host guard missing)  
**Warnings:** 1 (XML encoding in verify)  
**Infos:** 0

### Recommendation

**Return to planner with feedback:**

The plans are comprehensive and well-structured, but **one critical implementation gap must be fixed before execution:**

1. **[BLOCKER]** Plan 08-01, Task 1: Add the refuse-if-live-host check (Step 2) to the actual shell script in the `command` block. This guard is explicitly described as a defense-in-depth control for DRILL-01 but is not implemented.

2. **[WARNING]** Plan 08-01, Task 2: Fix the XML encoding in the verify block (`&amp;&amp;` → `&&` or wrap in CDATA).

Once these fixes are applied, re-run verification before execution.

---

## Checklist for Planner

- [ ] Add refuse-if-live-host check code to 08-01 Task 1, Step 2 in the shell command block
- [ ] Fix XML encoding in 08-01 Task 2 verify block
- [ ] Re-read Step 2 to confirm the guard logic matches the description
- [ ] Ensure the guard uses `>&2` for error output (stderr)
- [ ] Confirm offline validation (bash -n, python3 validate-staging.py) passes after fixes
- [ ] Resubmit PLAN.md for re-verification

---

**Verification completed:** 2026-06-13  
**Verified by:** Claude Code (Haiku 4.5)  
**Next step:** Revision and resubmission
