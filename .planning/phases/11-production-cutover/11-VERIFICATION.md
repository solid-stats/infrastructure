---
phase: 11-production-cutover
verified: 2026-06-13T00:00:00Z
status: human_needed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 11: Production Cutover Verification Report

**Phase Goal:** "Operator can switch production traffic to the new runtime in a single reversible nginx-upstream edit, gated on a fresh backup and a green diff, with a tested rollback and a post-cutover smoke check."

**Verified:** 2026-06-13
**Status:** human_needed

## Goal Achievement

### Observable Truths

Phase 11 delivers a **complete, offline-proven production cutover mechanism** that enables the operator to perform a single reversible traffic switch from legacy to new runtime, with all four requirements (CUT-01 through CUT-04) fully implemented, tested, and wired. The actual LIVE production traffic flip is intentionally **operator-gated** (not performed autonomously in this environment) because it is a consequential action affecting real production traffic, and the target production infrastructure is outside this staging environment's scope (per AGENTS.md).

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `scripts/cutover.sh` exists, is executable, and passes bash syntax validation | ✓ VERIFIED | `bash -n scripts/cutover.sh` → PASS; file mode: `755`; defined at lines 1-341 |
| 2 | Gate A (backup verification) is enforced: script refuses to proceed unless `docs/backup-gate.md` contains "Status: verified" | ✓ VERIFIED | Lines 177-183 in cutover.sh; grep -Eq anchor at line 180; tested: unverified gate → exit 1; `docs/backup-gate.md` contains "Status: verified" at line 17 |
| 3 | Gate B (coverage-only diff) is enforced: script refuses unless `docs/diff-readiness.md` contains "strict_failures: 0" | ✓ VERIFIED | Lines 185-198 in cutover.sh; grep -Eq anchor at line 194; tested: missing marker → exit 1; coverage-only note explicit in script comments (lines 10-11, 186-189) and runbook (docs/cutover.md lines 19-27) |
| 4 | Both gates are enforced even in DRY_RUN mode (gates are pre-flight checks, not bypassed by dry-run) | ✓ VERIFIED | DRY_RUN early-exit placed at line 206, AFTER gate checks (lines 177-200); tested: `DRY_RUN=1` with unverified gate → FATAL exit 1 before DRY_RUN branch is reached |
| 5 | Script backs up the live vhost before switching upstream (reversibility anchor) | ✓ VERIFIED | Lines 220-227: vhost backup with `cp -p` to `.cutover.bak`; always overwritten pre-run to reflect current state |
| 6 | nginx -t validation is fail-closed: script refuses to reload on invalid config, and calls rollback() on failure | ✓ VERIFIED | Lines 275-280: `${NGINX_T_CMD}` invoked before reload; failure path calls `rollback()` + `exit 1`; no reload on invalid config |
| 7 | rollback() function exists and is the single, tested reversibility path: restores vhost backup, runs nginx -t, reloads nginx | ✓ VERIFIED | Lines 84-111: rollback() defined once (single source of truth); calls cp/nginx-t/reload with fail-closed checks; SELF_TEST=1 exercises this REAL function (not a stub) with nginx commands injectable (lines 154-155) |
| 8 | Smoke check runs post-reload and auto-rolls back on failure; uses 2xx/3xx acceptance, not 200-only | ✓ VERIFIED | Lines 305-321: curl capture http_code, loop with 2xx/3xx regex `^[23]` (line 308), auto-rollback on exhausted retries (lines 317-321), exit 0 on success (implicit from line 340) |

**Score:** 8/8 must-haves verified

### Requirement Coverage (REQUIREMENTS.md)

All four Phase 11 requirements achieved and traceable:

| Requirement | SUMMARY Status | Evidence | Verification Status |
|-------------|---|---|---|
| CUT-01: Single reversible nginx-upstream switch | Complete (11-01-SUMMARY, line 72) | scripts/cutover.sh implements sed-based upstream switch with backup-before-overwrite pattern; WR-01 fix anchors to # CUTOVER: marker; WR-02 fix escapes NEW_UPSTREAM; WR-03 fix verifies exact match | ✓ SATISFIED |
| CUT-02: Tested rollback reverts upstream in one edit | Complete (11-01-SUMMARY, line 73) | rollback() function at lines 84-111; SELF_TEST=1 exercises the REAL rollback() (not a stub, per CR-01 fix) by setting NGINX_T_CMD/NGINX_RELOAD_CMD=true and asserting byte-restore (lines 157-167) | ✓ SATISFIED |
| CUT-03: Cutover gated on fresh backup + green diff | Complete (11-01-SUMMARY, lines 74-76) | Gate A (lines 177-183) checks "Status: verified" in backup-gate.md; Gate B (lines 185-198) checks "strict_failures: 0" in diff-readiness.md; both gates enforce coverage-only contract (not equality); gates run before any mutation, even in DRY_RUN | ✓ SATISFIED |
| CUT-04: Post-cutover smoke check confirms new runtime responds; auto-rollback on failure | Complete (11-01-SUMMARY, line 76) | Smoke check at lines 305-321: curl -fsS captures http_code; 2xx/3xx success; up to SMOKE_RETRIES=3 (default); auto-rollback (line 319) if exhausted; smoke_ok sentinel controls fall-through to success banner | ✓ SATISFIED |

All requirements appear in REQUIREMENTS.md traceability table (lines 123-126) as "Complete".

### Artifacts Verified

#### Level 1: Existence

| Artifact | Path | Status | Evidence |
|----------|------|--------|----------|
| Cutover script | `scripts/cutover.sh` | ✓ EXISTS | 341 lines; mode 755; readable |
| Operator runbook | `docs/cutover.md` | ✓ EXISTS | 230 lines; readable; sections: overview, policy, pre-flight gates, procedure, rollback, offline checks |
| Validator extension | `scripts/validate-staging.py` | ✓ EXISTS | `validate_cutover_artifacts()` present at lines 409-460; wired into main() checks list |

#### Level 2: Substantive (Content + Behavior)

**scripts/cutover.sh (341 lines):**
- Required env var enforcement: `required NEW_UPSTREAM` at line 49; exits 64 if unset ✓
- Gate A (backup): lines 177-183, grep -Eq anchored to "Status: verified" on its own line ✓
- Gate B (coverage): lines 185-198, grep -Eq anchored to "strict_failures: 0" on its own line ✓
- DRY_RUN early-exit: line 206, AFTER gates (proves gates always run) ✓
- Backup before switch: lines 220-227, cp -p to .cutover.bak ✓
- CUTOVER marker check: lines 240-243, asserts marker exists before sed ✓
- NEW_UPSTREAM escaping: line 248, sed -e 's/[&|\\]/\\&/g' escapes for sed replacement ✓
- Anchored sed: line 256, `/# CUTOVER:/,/^[[:space:]]*server [^;]*;/{...}` scopes to marker + next server line ✓
- Exact match verification: line 263, grep -cF (fixed-string) counts exactly 1 match ✓
- nginx -t fail-closed: lines 276-280, ${NGINX_T_CMD} before reload; rollback on failure ✓
- Smoke check logic: lines 305-321, curl http_code capture, 2xx/3xx regex, auto-rollback ✓
- SELF_TEST isolation: lines 118-171, exercises REAL rollback() with nginx stubbed via injectable commands ✓
- No secrets: no PASSWORD, SECRET_KEY, TOKEN, PRIVATE_KEY references ✓

**docs/cutover.md (230 lines):**
- Overview: lines 1-12, describes lever and reversibility ✓
- Policy section: lines 14-33, coverage-only green-diff note (lines 19-27), deferred CUT-05, do-not-execute warning ✓
- Pre-flight Gates section: lines 35-103, all 4 gates documented with procedures ✓
- Coverage-only note: lines 19-27 explicitly state "NOT value-equality", value divergence expected by design ✓
- Timing guidance: lines 105-119, recommends 24h parallel, review before flip ✓
- Procedure section: lines 121-169, DRY_RUN preview, what cutover.sh does, post-cutover checks ✓
- Rollback section: lines 185-216, two methods (backup restore + systemctl, bootstrap-edge.sh), verification ✓
- Cutover evidence placeholder: lines 171-183, clearly marked "not yet performed" ✓

**scripts/validate-staging.py validate_cutover_artifacts():**
- Script existence + bash -n: lines 412-416 ✓
- Script markers: set -euo pipefail, exit 64, Status: verified, strict_failures, rollback, nginx -t, curl+smoke ✓
- No secrets check: lines 438-442 ✓
- Runbook existence + markers: backup-gate, diff-readiness references, rollback, coverage-only note ✓
- coverage-only assertion: lines 459-460, checks for "NOT" AND ("equality" OR "value-equality") ✓

#### Level 3: Wiring (Integration + Data Flow)

**Gate A (backup gate):**
- Script reads: `grep -Eq '^[[:space:]]*Status:[[:space:]]+verified[[:space:]]*$' "${BACKUP_GATE_FILE}"` (line 180) ✓
- File exists: docs/backup-gate.md contains "Status: verified" at line 17 ✓
- Tested integration: gate-A refusal test with unverified file → exit 1 ✓

**Gate B (coverage gate):**
- Script reads: `grep -Eq '^[[:space:]]*strict_failures:[[:space:]]*0[[:space:]]*$' "${DIFF_GATE_FILE}"` (line 194) ✓
- File exists: docs/diff-readiness.md current state does not yet contain "strict_failures: 0" marker (normal — awaits human diff review) ✓
- Tested integration: gate-B refusal test with missing marker → exit 1 ✓

**CUTOVER marker in nginx config:**
- nginx vhost config: config/nginx/sites-available/stats-staging-solid-stats.conf, line 9: `# CUTOVER: change this server address...` ✓
- Script anchors to marker: line 256, `/# CUTOVER:/,/^[[:space:]]*server [^;]*;/` ✓
- Tested integration: sed scopes only to the marked server line (no global rewrite) ✓

**rollback() invocation paths:**
- From live nginx -t failure: line 278, `rollback` called if ${NGINX_T_CMD} fails ✓
- From live reload failure: line 289, `rollback` called if ${NGINX_RELOAD_CMD} fails ✓
- From smoke-check exhaustion: line 319, `rollback` called after SMOKE_RETRIES exhausted ✓
- From SELF_TEST: line 157, REAL rollback() driven with injectable nginx commands ✓

**Data flow: Gate files → Script → Decisions:**
- Backup gate reads from BACKUP_GATE_FILE (default: ${REPO_ROOT}/docs/backup-gate.md) ✓
- Diff gate reads from DIFF_GATE_FILE (default: ${REPO_ROOT}/docs/diff-readiness.md) ✓
- Script resolves gate files relative to repo root (lines 56-62), so gates work from any CWD (WR-05 fix) ✓
- Both gates block mutation before DRY_RUN early-exit ✓

**Validator wiring:**
- validate_cutover_artifacts() called in main() checks list ✓
- `python3 scripts/validate-staging.py` exits 0, includes "ok: cutover artifacts" ✓

### Spot Checks (Behavioral Verification)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Syntax check | `bash -n scripts/cutover.sh` | PASS (no stderr) | ✓ PASS |
| Validator all checks | `python3 scripts/validate-staging.py 2>&1 \| tail -1` | "ok: cutover artifacts" | ✓ PASS |
| Gate-A refusal | `BACKUP_GATE_FILE=/tmp/unverified NEW_UPSTREAM=1.2.3.4:8080 bash scripts/cutover.sh 2>&1 \| grep -q "backup gate not verified"` | MATCH (exit 1) | ✓ PASS |
| Gate-B refusal | `DIFF_GATE_FILE=/tmp/no-marker NEW_UPSTREAM=1.2.3.4:8080 bash scripts/cutover.sh 2>&1 \| grep -q "diff coverage gate"` | MATCH (exit 1) | ✓ PASS |
| Gate-A in DRY_RUN | `DRY_RUN=1 BACKUP_GATE_FILE=/tmp/unverified NEW_UPSTREAM=1.2.3.4:8080 bash scripts/cutover.sh 2>&1 \| grep -q "backup gate not verified"` | MATCH (exit 1 before DRY_RUN branch) | ✓ PASS |
| SELF_TEST rollback | `SELF_TEST=1 NEW_UPSTREAM=10.43.94.103:3000 bash scripts/cutover.sh 2>&1 \| grep -q "SELF_TEST PASSED"` | MATCH; byte-restore asserted | ✓ PASS |

### Code Review Issues (All Resolved)

The code review (11-REVIEW.md) identified **1 critical + 5 warning issues**. All have been **FIXED** in the delivered code:

| ID | Issue | Severity | SUMMARY Status | Verification |
|---|---|---|---|---|
| CR-01 | SELF_TEST exercised stub rollback(), not real function | CRITICAL | Auto-fixed (11-01-SUMMARY, deviation rule 1, line 90-105) | ✓ FIXED: SELF_TEST now drives REAL rollback() with nginx stubbed via NGINX_T_CMD/NGINX_RELOAD_CMD injection (lines 154-155); rollback() is defined once (lines 84-111); SELF_TEST confirms byte-restore |
| WR-01 | sed upstream switch not anchored to # CUTOVER: marker | WARNING | Auto-fixed | ✓ FIXED: sed now scoped to marker range and counts exactly 1 match (lines 240-243, 256, 263-267) |
| WR-02 | NEW_UPSTREAM unescaped in sed replacement | WARNING | Auto-fixed | ✓ FIXED: esc_upstream escapes &, \, \| for sed (line 248) |
| WR-03 | Post-switch grep uses regex (. is wildcard) | WARNING | Auto-fixed | ✓ FIXED: grep -cF (fixed-string, no regex) at line 263 |
| WR-04 | Gate greps unanchored (substring matches) | WARNING | Auto-fixed | ✓ FIXED: both gate greps now use grep -Eq with anchored patterns (lines 180, 194) |
| WR-05 | Gate file paths relative, no CWD guarantee | WARNING | Auto-fixed | ✓ FIXED: script resolves gate files relative to repo root (lines 56-62) |
| IN-01 | Validator checks spelling, not behavior | INFO | Noted (validator checks are sufficient for offline CI gate) | ✓ MITIGATED: SELF_TEST=1 provides behavioral proof; validator serves as offline CI marker check |
| IN-02 | cp -p on backup but plain cp on restore | INFO | Not fixed (acceptable for root-owned nginx config) | ✓ ACCEPTABLE: nginx config is root-owned; timestamp preservation on restore is hygiene, not a blocker |
| IN-03 | SELF_TEST temp files leak on early failure | INFO | Not fixed (minor hygiene only) | ✓ ACCEPTABLE: mktemp failure is rare; cleanup trap would be nice-to-have |

**Status:** All critical and warning issues resolved; info items are acceptable or already mitigated.

## Human Verification Required

The phase delivers a **complete, tested, reversible cutover mechanism**. All CUT-01 through CUT-04 requirements are implemented, offline-proven (gates refuse when expected, SELF_TEST passes, validator exits 0), and ready for operator use.

The actual **LIVE production traffic flip** is intentionally **operator-gated** because:
1. It is a consequential action (switches real production traffic to a new runtime).
2. The target production infrastructure is outside this staging environment's scope (AGENTS.md states "Production cutover deferred" and "v1 targets `solid-stats-staging` only").
3. The autonomous run cannot perform the flip without live production infrastructure access and without operator review of the actual diff output (which is incomplete at this point in the cycle).

### What Remains Operator-Gated

The following human verification items are required before the live production flip can proceed:

#### 1. Pre-Cutover Gate Documentation Update

**Test:** Operator confirms both pre-flight gates are satisfied:
- **Gate 1 (Fresh backup):** `docs/backup-gate.md` must contain `Status: verified` with a recent backup ID.
  - Verify: `grep -E '^Status: verified$' docs/backup-gate.md`
  - Current state: ✓ File contains "Status: verified" (line 17) with recent backup ID `20260510T073635Z`
  
- **Gate 2 (Green diff coverage):** `docs/diff-readiness.md` must contain `strict_failures: 0` under a `## Cutover Gate Evidence` section.
  - Verify: `grep -E '^strict_failures: 0$' docs/diff-readiness.md` (must appear as a standalone marker, not prose)
  - Current state: ✗ Marker not yet present (awaits human diff review and evidence recording)
  - Action: Operator runs a fresh full-run controlled ingest, reviews the diff output, and if `strict_failures: 0` passes review, adds the marker to `docs/diff-readiness.md`.

**Expected:** Both gates in their files pass.

#### 2. Operator Reviews Cutover Runbook for Clarity

**Test:** Operator reads `docs/cutover.md` and confirms:
- The four pre-flight gates are clearly described (lines 35-103).
- The coverage-only green-diff note is unambiguous (lines 19-27, policy section).
- The single-edit upstream switch procedure is straightforward (lines 121-143).
- The rollback section provides two concrete recovery methods (lines 185-216).
- Timing guidance (24h parallel observation) is reasonable (lines 105-119).

**Expected:** Operator signals readiness (e.g., "runbook is clear and I'm ready to execute").

#### 3. Dry-Run Preview Confirms Gates and Mechanism

**Test:** Operator performs a dry-run preview (assumes backup-gate.md and diff-readiness.md are populated for this test):
```bash
cd <path-to-infrastructure-repo>
DRY_RUN=1 NEW_UPSTREAM=10.43.94.103:3000 bash scripts/cutover.sh
```
**Expected:** 
- If gates are met: `[DRY-RUN] would: ...` steps, `[DRY-RUN] gates PASSED`, exit 0.
- If gates are unmet: `FATAL: [gate error]`, exit 1 (proving gates still block).

#### 4. Live Production Traffic Flip (Operator-Executed, Not Autonomous)

**Test:** Operator performs the actual production traffic cutover:
```bash
cd <path-to-infrastructure-repo>
NEW_UPSTREAM=<target-clusterip:port> bash scripts/cutover.sh
```

**Expected:**
- Script enforces both gates (exits 1 if either is unmet).
- Backs up live vhost.
- Switches upstream to NEW_UPSTREAM.
- Validates nginx config (nginx -t passes).
- Reloads nginx.
- Runs smoke check (curl to https://stats-staging.solid-stats.ru/).
- If smoke passes: success banner with backup path and manual rollback command.
- If smoke fails: auto-rollback, exit 1.

**Why human-gated:** This step switches real production traffic. The autonomous run cannot perform it without:
- Live production infrastructure access.
- Operator review of the actual diff output (which confirms the new runtime's statistics divergence is acceptable).
- Operator judgment on timing (24h observation window, confidence threshold).

#### 5. Post-Cutover Evidence Capture (Operator Records)

**Test:** If cutover succeeds, operator records evidence in `docs/cutover.md` under the "Cutover Evidence" section (placeholder at lines 171-183):

```markdown
## Cutover Evidence

| Field | Value |
|-------|-------|
| Date | <ISO-8601 timestamp of flip> |
| Operator | <operator username> |
| Previous upstream | <legacy address:port> |
| New upstream | <new address:port> |
| Smoke check result | <HTTP code; e.g., 200 OK> |
| Post-cutover curl | <curl -I output confirming 2xx/3xx response> |
```

**Expected:** Table populated with live flip evidence (not fabricated; actual curl/nginx output from the flip moment).

#### 6. Post-Cutover Monitoring (Operator Observes)

**Test:** Operator monitors new runtime for at least 24 hours after the flip:
```bash
kubectl -n solid-stats-staging logs deployment/server-2 --since=1h | tail -50
```
**Expected:** No error spikes, normal request latency, no cascading failures. If issues arise, operator has the tested rollback path ready (documented in docs/cutover.md lines 185-216).

---

## Summary of Verification

### What Is Complete (Offline-Proven)

1. **4-gate mechanism** (`scripts/cutover.sh`): Enforces backup + diff gates, backs up vhost, switches upstream, validates nginx, reloads, smoke-checks, auto-rolls back on failure.
2. **Gate enforcement:** Both Gate A (backup) and Gate B (coverage-only diff) refuse to proceed if unmet; enforced even in DRY_RUN mode.
3. **Tested rollback:** SELF_TEST=1 exercises the REAL rollback() function (not a stub) with nginx commands injectable; asserts byte-restore.
4. **Operator runbook** (`docs/cutover.md`): Documents all 4 gates, single-edit switch, timing, rollback, coverage-only green-diff note, CUT-05 deferral.
5. **Offline validator** (`validate-staging.py`): Asserts cutover artifacts exist with all required markers; exits 0 in CI.
6. **Code review fixes:** All 1 critical + 5 warnings resolved (marker anchoring, sed escaping, gate anchoring, repo-root resolution, injectable rollback).

### What Requires Human

1. **Diff review + Gate 2 evidence:** Operator runs controlled full-run, reviews old-vs-new diff, records `strict_failures: 0` evidence in `docs/diff-readiness.md`.
2. **Runbook review:** Operator confirms procedures are clear and acceptable.
3. **Live traffic flip:** Operator executes `scripts/cutover.sh` with correct NEW_UPSTREAM, observes gates block/pass in real time, manages smoke check outcome.
4. **Evidence capture:** Operator records the flip timestamp, operator name, upstream addresses, and curl proof in the placeholder table.
5. **Post-cutover monitoring:** Operator observes new runtime for errors/anomalies over 24h.

---

## Phase Goal Achievement Assessment

**Goal:** "Operator can switch production traffic to the new runtime in a single reversible nginx-upstream edit, gated on a fresh backup and a green diff, with a tested rollback and a post-cutover smoke check."

**Verdict:**

- ✓ **Single reversible edit:** cutover.sh performs one sed-based upstream switch with backup-before-overwrite.
- ✓ **Gated on fresh backup:** Gate A enforces `docs/backup-gate.md` "Status: verified".
- ✓ **Gated on green diff:** Gate B enforces `docs/diff-readiness.md` "strict_failures: 0" (coverage-only, not equality).
- ✓ **Tested rollback:** SELF_TEST=1 proves rollback() restores byte-for-byte.
- ✓ **Post-cutover smoke check:** curl -fsS with 2xx/3xx acceptance; auto-rollback on failure.
- ✓ **Mechanism complete:** All CUT-01..04 implemented, offline-proven, validator exits 0.

**Live flip status:** Pending operator execution (human_needed) because the production target is outside staging scope and requires live operator judgment + diff review.

---

_Verified: 2026-06-13_
_Verifier: Claude (gsd-verifier)_
_Verification method: Goal-backward from requirements; artifact level 1-3 checks; behavioral spot-checks; code review fix traceability_
