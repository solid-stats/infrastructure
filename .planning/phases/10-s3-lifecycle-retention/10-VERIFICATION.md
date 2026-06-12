---
phase: 10-s3-lifecycle-retention
verified: 2026-06-13T12:00:00Z
status: human_needed
score: 7/7 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Operator runs empirical S3 lifecycle API probe"
    expected: "Job executes, logs contain API support result (implemented or NOT implemented) and x-amz-expiration header check result, cleanup completes successfully"
    why_human: "Live S3 API call required; empirical evidence cannot be captured programmatically; must record results in docs/s3-lifecycle.md Evidence table before applying retention policy"
  - test: "Verify Evidence table in docs/s3-lifecycle.md is populated with real probe results"
    expected: "Evidence table contains: date of probe run, API support result, x-amz-expiration result, operator name — all non-blank"
    why_human: "Operator-gated: must explicitly fill table with live evidence; blank table = policy NOT proven. Requirement S3-03 states lifecycle support must be proven empirically 'before retention is relied upon'"
---

# Phase 10: S3 Lifecycle Retention Verification Report

**Phase Goal:** "Backup-prefix retention is enforced through a repo-stored, script-applied expiration policy, with Timeweb S3 lifecycle support proven empirically before retention is relied upon."

**Verified:** 2026-06-13
**Status:** human_needed
**Score:** 7/7 must-haves verified (S3-01 and S3-02 delivered and offline-verifiable; S3-03 empirical proof operator-gated)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Expiration rule for backups/postgres/ with Days=30 is stored in config/s3/backups-lifecycle.json | ✓ VERIFIED | File exists and contains `"Prefix": "backups/postgres/"` and `"Days": 30`; validated by validate-s3-lifecycle.py |
| 2 | AbortIncompleteMultipartUpload rule with DaysAfterInitiation=7 is present in lifecycle config | ✓ VERIFIED | File contains rule with empty Filter.Prefix and `"DaysAfterInitiation": 7`; validated by validate-s3-lifecycle.py |
| 3 | Offline validator enforces 30-day floor and AbortIncompleteMultipartUpload requirement | ✓ VERIFIED | scripts/validate-s3-lifecycle.py exits 0 and enforces `days >= 30` + abort rule presence; validates on offline JSON structure |
| 4 | Apply script creates in-cluster Job with GET-before-PUT and FORCE_OVERWRITE gate (S3-01) | ✓ VERIFIED | scripts/apply-s3-lifecycle.sh contains: `get-bucket-lifecycle-configuration` call, FORCE_OVERWRITE env var with gate at line 133–135, `put-bucket-lifecycle-configuration`, ConfigMap mounting; exits 1 if NotImplemented |
| 5 | Probe Job manifest is complete and isolated in subdirectory (S3-03 empirical proof artifact) | ✓ VERIFIED | k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml exists; contains ServiceAccount, API probe, x-amz-expiration check via --query, self-cleanup, server-2-runtime secret refs; NOT at depth-1 |
| 6 | validate-staging.py enforces S3 lifecycle config structure and docs existence (regression guard) | ✓ VERIFIED | validate-staging.py exits 0 with "ok: s3 lifecycle config" and "ok: s3 lifecycle runbook"; delegates to validate-s3-lifecycle.py via importlib.util; checks docs/s3-lifecycle.md exists |
| 7 | docs/s3-lifecycle.md documents apply procedure, empirical probe steps, and Evidence placeholder (S3-03 operator gate) | ✓ VERIFIED | File exists; contains 6 sections (Overview, Policy File, Apply Procedure, Empirical Proof, Evidence, Async Caveat); Evidence table has blank operator fields; explicit note: "blank evidence table means policy NOT proven" |

**Score:** 7/7 must-haves verified

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| S3-01: Per-prefix expiration policy stored and script-applied | ✓ SATISFIED | config/s3/backups-lifecycle.json created with Expiration rule on backups/postgres/; scripts/apply-s3-lifecycle.sh applies via in-cluster Job; scripts/validate-s3-lifecycle.py validates offline |
| S3-02: Abort incomplete multipart uploads | ✓ SATISFIED | config/s3/backups-lifecycle.json contains AbortIncompleteMultipartUpload rule with DaysAfterInitiation=7; validated by validate-s3-lifecycle.py |
| S3-03: Timeweb S3 lifecycle support proven empirically before retention relied upon | ⚠️ PENDING OPERATOR | k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml created (artifact complete); probe execution and evidence recording deferred to operator; docs/s3-lifecycle.md Evidence table ready for operator to populate |

### Artifacts Verification

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| config/s3/backups-lifecycle.json | Valid JSON, Expiration rule on backups/postgres/ (30d), AbortIncompleteMultipartUpload (7d) | ✓ VERIFIED | File exists; structure validated by JSON parser and validate-s3-lifecycle.py; both rules present and correctly configured |
| scripts/apply-s3-lifecycle.sh | Bash script, GET-before-PUT, FORCE_OVERWRITE gate, exit 64 for missing config | ✓ VERIFIED | bash -n passes; contains all required markers (set -euo pipefail, exit 64, get/put calls, endpoint, JSON ref); FORCE_OVERWRITE gate at lines 133–135 |
| scripts/validate-s3-lifecycle.py | Offline validator, Days >= 30 floor enforcement, AbortIncompleteMultipartUpload check | ✓ VERIFIED | Runs standalone; exits 0 with "ok: s3 lifecycle JSON" and "ok: apply script syntax"; enforces 30-day minimum |
| k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml | Valid k8s Job + ServiceAccount, isolated prefix, x-amz-expiration check, self-cleanup, server-2-runtime refs | ✓ VERIFIED | kubectl dry-run passes (or cluster unreachable tolerated); manifest structure valid; probe prefix "s3-lifecycle-probe/" hardcoded; backups/postgres/ not referenced in executable code |
| docs/s3-lifecycle.md | Runbook with apply procedure, probe procedure, Evidence placeholder, async caveat | ✓ VERIFIED | File exists (254 lines); 6 sections present; apply-s3-lifecycle.sh referenced by name; 80-s3-lifecycle-probe-job.yaml referenced; S3-03 and AbortIncompleteMultipartUpload documented; Evidence table empty (operator gate) |
| scripts/validate-staging.py (extended) | S3 lifecycle config + docs checks | ✓ VERIFIED | validate-staging.py exits 0; includes "ok: s3 lifecycle config" and "ok: s3 lifecycle runbook"; delegates to validate-s3-lifecycle.py; checks docs file exists |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| scripts/apply-s3-lifecycle.sh | config/s3/backups-lifecycle.json | Reference: `${SCRIPT_DIR}/../config/s3/backups-lifecycle.json` at line 18; ConfigMap creation at lines 29–32 | ✓ WIRED | Script resolves path; creates ConfigMap with `--from-file`; mounts to Job at `/config` |
| scripts/validate-staging.py | scripts/validate-s3-lifecycle.py | Dynamic import via importlib.util at lines 19–31; delegates to module.validate_lifecycle_json() | ✓ WIRED | CI-enforced: importlib loads module; executes validate_lifecycle_json() → raises ValidationError if 30-day floor violated |
| docs/s3-lifecycle.md | scripts/apply-s3-lifecycle.sh | Section 3 documents: "bash scripts/apply-s3-lifecycle.sh" and "gets S3 creds from server-2-runtime Secret" | ✓ WIRED | Procedure explicitly names the script; references ConfigMap creation and Job execution |
| docs/s3-lifecycle.md | k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml | Section 4 documents: "kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml" | ✓ WIRED | Procedure explicitly names the manifest path; step 1 references it by path; step 7 cleanup references Job name |
| k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml | server-2-runtime Secret | env: secretKeyRef for S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY | ✓ WIRED | Job spec correctly references secret keys; metadata shows name: server-2-runtime at lines 97, 102, 107 |

### Code Review Findings (from 10-REVIEW.md)

**Critical Issues:** 0 (all mitigated)

**Warnings Found and Fixed:** 5

1. **WR-01 (CI validator strictness)** — FIXED: validate-staging.py now delegates to validate-s3-lifecycle.py for Days >= 30 enforcement via importlib. Single source of truth established.

2. **WR-02 (GET-before-PUT clobber without halt)** — FIXED: apply-s3-lifecycle.sh now requires explicit FORCE_OVERWRITE=1 env var; refuses to overwrite by default; dumps existing config to Job log before exiting (lines 131–136).

3. **WR-03 (Apply Job less hardened than probe)** — FIXED: apply-s3-lifecycle.sh Job spec now includes `capabilities: drop: ["ALL"]` in securityContext (lines 109–110), matching probe Job hardening.

4. **WR-04 (Unpinned apk add aws-cli)** — DEFERRED (acceptable): documented in docs/s3-lifecycle.md Section 7 as known fragility; matches 60-postgres-backup.yaml precedent; noted as operational risk to track.

5. **WR-05 (Probe x-amz-expiration false-positive risk)** — FIXED: probe Job now uses `aws s3api head-object --query 'Expiration'` (line 77–78) instead of grepping for "expir" substring; parses JSON directly; eliminates false-positive risk on unrelated error strings.

**Info Findings:** 4 (non-blocking; mostly deferred or accepted)

- **IN-01:** Probe documents "apply rule for s3-lifecycle-probe/ and re-run" step without shipped tooling — accepted; operator-directed one-time action.
- **IN-02:** Probe cleanup only runs on happy path (errexit); potential orphan object on early failure — noted but acceptable (orphan is isolated, harmless).
- **IN-03:** Both Jobs run as root for apk add — accepted pattern consistent with 60-postgres-backup.yaml.
- **IN-04:** validate-s3-lifecycle.py was dead-code relative to CI — FIXED by delegating from validate-staging.py.

### Verification Test Results

```
$ python3 scripts/validate-staging.py
ok: script syntax
ok: manifest shape
ok: drill manifest safety
ok: workload safety
ok: app image pins
ok: rendered secret structure
ok: s3 lifecycle JSON
ok: s3 lifecycle config
ok: s3 lifecycle runbook

$ python3 scripts/validate-s3-lifecycle.py
ok: s3 lifecycle JSON
ok: apply script syntax and markers

$ bash -n scripts/apply-s3-lifecycle.sh
(no output — syntax valid)

$ grep -r "s3-lifecycle-probe/" k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml
(isolated prefix confirmed — backups/postgres/ not in executable code)

$ find k8s/staging -maxdepth 1 -name "*.yaml" | grep -i lifecycle
(no match — depth-1 exclusion confirmed)
```

**All offline checks PASS.**

## Human Verification Required

### S3-03: Empirical Timeweb S3 Lifecycle API Support Proof

**Status:** Artifact created; operator-gated execution required.

The phase goal explicitly requires "Timeweb S3 lifecycle support proven empirically before retention is relied upon." The probe Job and runbook are complete; the empirical evidence must be captured by the operator through a live run.

#### Procedure

1. **Prerequisites:**
   - WireGuard tunnel to staging cluster is active
   - `KUBECONFIG` configured for `solid-stats-staging`
   - kubectl reachable

2. **Run the probe Job:**
   ```bash
   kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml -n solid-stats-staging
   kubectl wait --for=condition=complete job/s3-lifecycle-probe -n solid-stats-staging --timeout=120s
   kubectl logs job/s3-lifecycle-probe -n solid-stats-staging
   kubectl delete job s3-lifecycle-probe -n solid-stats-staging
   ```

3. **Expected outcomes (review logs):**
   - Look for one of:
     - `RESULT: API implemented — no lifecycle config currently set` ✓ Safe to proceed
     - `RESULT: API implemented — existing lifecycle config found` ✓ Safe to proceed (review existing config)
     - `RESULT: lifecycle API NOT implemented on this endpoint` ✗ STOP — do not apply policy
   - Look for:
     - `RESULT: x-amz-expiration PRESENT` ✓ Lifecycle rule recognized
     - `RESULT: x-amz-expiration ABSENT` ✓ Normal if no rule targets probe prefix yet (expected on first run)
   - Confirm: `probe cleanup complete`

4. **Record evidence:**
   Edit `docs/s3-lifecycle.md` Section 5 (Evidence table) and fill:
   - Date of probe run: [timestamp]
   - API support result: [API implemented / NOT implemented]
   - x-amz-expiration present: [yes / no]
   - Operator: [your name]
   - Any relevant notes from logs

5. **Gate:** Do NOT apply the real retention policy (scripts/apply-s3-lifecycle.sh) until Evidence table is populated with real results.

#### Decision Points

- **If API implemented:** Phase 10 ready to close; evidence recorded; can proceed to apply policy.
- **If API NOT implemented:** Escalate before proceeding; S3 lifecycle API is not supported on this endpoint; retention policy cannot be relied upon.
- **If Evidence table remains blank:** S3-03 is not satisfied; phase cannot close until operator captures evidence.

---

## Summary

### What Was Delivered (Offline-Verifiable)

| Requirement | Artifact | Status |
|-------------|----------|--------|
| S3-01 (repo-stored policy) | config/s3/backups-lifecycle.json | ✓ Complete |
| S3-01 (script-applied) | scripts/apply-s3-lifecycle.sh | ✓ Complete |
| S3-02 (abort incomplete multipart) | config/s3/backups-lifecycle.json + validator | ✓ Complete |
| S3-03 (empirical probe artifact) | k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml | ✓ Complete |
| S3-03 (operator runbook) | docs/s3-lifecycle.md | ✓ Complete |
| Regression guards | scripts/validate-staging.py + validate-s3-lifecycle.py | ✓ Complete |

### What Remains (Operator-Gated)

| Item | Required For | Action |
|------|--------------|--------|
| Empirical S3 API proof | S3-03 satisfaction | Run probe Job; record API support result in Evidence table |
| Evidence table population | S3-03 gate before apply | Operator fills table with real probe results |

### Code Quality

- **All review findings addressed:** WR-01 through WR-05 either fixed or documented as acceptable deferred debt
- **No critical blockers:** Safety-critical mitigations implemented (FORCE_OVERWRITE gate, x-amz-expiration parsing fix, capability drops)
- **No stubs:** All artifacts are substantive and wired

### Status Rationale

**human_needed** (not `passed`) because:
- S3-03 requires operator execution against live S3 and evidence recording
- Evidence table in docs/s3-lifecycle.md is intentionally blank; filling it is the operator gate
- Phase goal states proof must occur "before retention is relied upon" — blank evidence = policy not proven
- Once operator records evidence, phase closes automatically (no code changes needed)

---

_Verified: 2026-06-13_
_Verifier: Claude (gsd-verifier)_
