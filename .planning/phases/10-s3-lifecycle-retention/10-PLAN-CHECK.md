---
phase: 10-s3-lifecycle-retention
status: NEEDS_REVISION
revision_cycle: 1
total_issues: 8
blockers: 4
warnings: 4
---

# Phase 10 Plan Verification

**Phase Goal:** Backup-prefix retention is enforced through a repo-stored, script-applied expiration policy, with Timeweb S3 lifecycle support proven empirically before retention is relied upon.

**Requirements:** S3-01 (per-prefix expiration policy, repo-stored, script-applied), S3-02 (abort incomplete multipart uploads), S3-03 (empirical S3 lifecycle API support proof).

**Plans Verified:** 10-01, 10-02, 10-03

**Status:** NEEDS_REVISION — 4 blockers and 4 warnings prevent execution.

---

## Critical Findings

### BLOCKER: Plan 01, Task 1 — Lifecycle JSON Content Not Specified

**Dimension:** Task Completeness / Requirement Coverage

**Plan:** 10-01

**Task:** Task 1

**Severity:** BLOCKER

**Description:** Task 1 action requires creating `config/s3/backups-lifecycle.json` with "two rules" (Expiration + AbortIncompleteMultipartUpload) but does not specify the actual JSON structure or provide the complete file content. The action says:

```
Rule 1 — ID "expire-postgres-backups", Status "Enabled", Filter { Prefix: "backups/postgres/" },
Expiration { Days: 30 }.
Rule 2 — ID "abort-incomplete-multipart", Status "Enabled", Filter { Prefix: "" } (bucket-wide),
AbortIncompleteMultipartUpload { DaysAfterInitiation: 7 }.
```

This is pseudocode, not the actual JSON structure required by AWS S3 `PutBucketLifecycleConfiguration` API.

**Why This Fails S3-01:** S3-01 requires "stored in the repo" — a real JSON file. Without the actual JSON structure in the plan, there is no specification of what file will be created. The plan cannot be executed because the executor does not know the exact format to generate.

**Why This Fails S3-02:** S3-02 requires "AbortIncompleteMultipartUpload rule" — the validator in Task 1 is supposed to assert this rule exists in the JSON. But if the JSON structure is not defined, the validator cannot be written to correctly parse it.

**Example Issue:** The PutBucketLifecycleConfiguration API requires this exact structure:
```json
{
  "Rules": [
    {
      "ID": "expire-postgres-backups",
      "Status": "Enabled",
      "Filter": { "Prefix": "backups/postgres/" },
      "Expiration": { "Days": 30 }
    },
    {
      "ID": "abort-incomplete-multipart",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 }
    }
  ]
}
```

**Fix Required:** Plan 01, Task 1 must include the complete JSON file content in the action, either:
1. Embedded directly in the action as the exact JSON to write, or
2. Point to a generated template file and explain exactly how it will be produced.

---

### BLOCKER: Plan 01, Task 2 — apply-s3-lifecycle.sh Design Creates Dangerous Shell Escaping Risk

**Dimension:** Task Completeness / Key Links Planned

**Plan:** 10-01

**Task:** Task 2

**Severity:** BLOCKER

**Description:** Task 2 action describes embedding the JSON file content into a Kubernetes Job YAML via shell variable substitution and heredoc, but the design creates a critical shell-escaping vulnerability:

1. The script reads `config/s3/backups-lifecycle.json` into a shell variable at run-time.
2. This variable is then embedded inside a Job spec YAML, which is itself written as a heredoc to `kubectl apply -f -`.
3. If the JSON contains special shell characters (`"`, `$`, backticks, `\`), they will be interpreted by the shell and break the YAML or the JSON.

**Current Plan Language:**
> "embed the JSON as a heredoc inside the container command string, written to /tmp/backups-lifecycle.json inside the container. This avoids a ConfigMap. Use this approach — write the JSON content via printf or cat to /tmp/backups-lifecycle.json in the container, then reference file:///tmp/backups-lifecycle.json. To avoid drift between the repo file and the embedded copy, the script reads config/s3/backups-lifecycle.json at Job-creation time and embeds the content via a shell variable substitution inside the Job's command string."

This approach is **unsafe and will fail** if the JSON contains:
- Double quotes (JSON always has them in keys and strings)
- Dollar signs (e.g., in comments or edge-case strings)
- Backticks or `$()` subshell markers

**Example Failure Scenario:**
```bash
# Script tries to embed JSON with quotes:
json_content=$(cat config/s3/backups-lifecycle.json)
kubectl apply -f - <<EOF
...
args: ["sh", "-ec", "cat > /tmp/config.json << 'JSON'\n${json_content}\nJSON\naws ..."]
EOF
```

If JSON contains `"Rules"` or `"Prefix": "backups/postgres/"`, the shell will interpret the quotes and break the YAML.

**Fix Required:** Plan 01, Task 2 must specify ONE of the following approaches:

**Option A (ConfigMap + cleanup — more robust):**
- Script creates a temporary ConfigMap from the file: `kubectl create configmap temp-lifecycle --from-file=...`
- Job mounts this ConfigMap as a volume at `/etc/config/backups-lifecycle.json`
- Job reads from the volume: `aws s3api put-bucket-lifecycle-configuration ... file:///etc/config/backups-lifecycle.json`
- Script deletes ConfigMap after Job completes: `kubectl delete configmap temp-lifecycle`

**Option B (Base64 encode — simpler for small files):**
- Script reads JSON and base64-encodes it: `base64 -w0 config/s3/backups-lifecycle.json`
- Embed the base64 string (no special chars) in the Job spec
- Job decodes: `echo "${LIFECYCLE_CONFIG_B64}" | base64 -d > /tmp/config.json`
- No escaping risks; base64 has no shell special characters

**Option A is preferred** because it avoids encoding overhead and is closer to the in-cluster-creds pattern used in backup-postgres-now.sh.

---

### BLOCKER: Plan 02 — No Dependency on Plan 01, Allows Out-of-Order Execution

**Dimension:** Dependency Correctness

**Plan:** 10-02

**Severity:** BLOCKER

**Description:** Plan 02 (S3 lifecycle empirical probe Job) is in Wave 1 with `depends_on: []`, same as Plan 01. This means the two plans can run in parallel or the operator can run Plan 02 before Plan 01.

**Why This is Dangerous:**
- Plan 02 creates the probe Job manifest (`k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml`) — a **one-shot runtime artifact**
- Plan 01 creates the actual lifecycle JSON policy (`config/s3/backups-lifecycle.json`) and apply script
- The CONTEXT.md explicitly states: "run the empirical probe first" and "confirm S3-03 evidence before running apply"
- **But there is no enforced ordering** — nothing prevents the operator from applying the real policy without running the probe first

**Per CONTEXT.md:**
> "Empirical proof (S3-03) — design SAFE, default to operator-gated: Timeweb S3 lifecycle parity is MEDIUM confidence. The proof has two parts... Provide a runbook + record evidence."

The runbook (Plan 03, docs/s3-lifecycle.md) states "Pre-requisite: run the empirical probe first and record S3-03 evidence before proceeding." But there is no **plan-level enforcement** of this prerequisite.

**Fix Required:** Plan 02 must add `depends_on: ["10-01"]` so it only runs after Plan 01 completes. The Phase ordering should be:
- Plan 01 (Wave 1): Create JSON policy, apply script, offline validator
- Plan 02 (Wave 2, depends on 01): Create probe Job, operator runs empirical test
- Plan 03 (Wave 3, depends on 02): Create runbook, document evidence

**Alternative (Less Preferred):** If the intent is to run the probe independently, then Plan 03's Task 3 checkpoint must **explicitly verify that the operator filled in the Evidence section before allowing Phase 10 to be marked complete.**

---

### BLOCKER: Plan 03, Task 3 — Checkpoint Allows Completion Without Recorded Evidence

**Dimension:** Context Compliance / Verification Derivation

**Plan:** 10-03

**Task:** Task 3

**Severity:** BLOCKER

**Description:** Plan 03, Task 3 is a `checkpoint:human-verify` that asks the operator to confirm Phase 10 artifacts are complete. However, the instructions and resume-signal do NOT require the operator to fill in the Evidence section in `docs/s3-lifecycle.md` before marking the phase complete.

**Current resume-signal:**
```
Type "approved" to confirm Phase 10 artifacts are complete and consistent. Note any issues found.
```

**Per CONTEXT.md and S3-03 requirement:**
> "Empirical proof (S3-03) — design SAFE, default to operator-gated: ... Provide a runbook + record evidence. ... (the script makes it one command), not done blind. Provide a runbook + record evidence."

The runbook (docs/s3-lifecycle.md, Section 5) states:
> "This section must be filled before the apply procedure (Section 3) is run for the first time. A blank evidence table means the policy has NOT been proven."

**The Problem:** An operator can:
1. Run Plan 01 (policy + apply script created)
2. Run Plan 02 (probe Job created, but may not have run it)
3. Run Plan 03 (runbook created, Evidence section blank)
4. Type "approved" at Task 3 checkpoint
5. Phase 10 is marked COMPLETE
6. Nothing prevents them from running `scripts/apply-s3-lifecycle.sh` to apply the real policy **without evidence**

**Why This Violates the Phase Goal:** The phase goal states "with Timeweb S3 lifecycle support proven empirically **before** retention is relied upon." A blank Evidence section means the proof was never run. The goal is not achieved.

**Fix Required:** Plan 03, Task 3 checkpoint must add an explicit check:

```
<how-to-verify>
... existing steps ...

Step 6 — Check that the Evidence section is filled:
  grep -A 5 "^| Date of probe run" docs/s3-lifecycle.md | grep -v "^|.*|$"
  If the Evidence table is blank (only header rows), do NOT type "approved".
  
The Evidence section MUST be filled with:
  - Date of probe run
  - API support result (API implemented / NOT implemented)
  - x-amz-expiration present (yes / no)
  - Cleanup confirmed (yes)
  - Operator name and date
</how-to-verify>

<resume-signal>
Type "approved" ONLY if:
1. docs/s3-lifecycle.md Evidence section is filled with operator name, date, API result, and x-amz-expiration status.
2. If Evidence is blank, type "awaiting-probe" to defer Phase 10 completion until the probe is run.
Type "not-implemented" if the API is not supported (blocks retention policy).
</resume-signal>
```

---

## Secondary Issues

### WARNING: Plan 01, Task 2 — GET-before-PUT Error Handling Lacks "NotImplemented" Clarity

**Dimension:** Task Completeness

**Plan:** 10-01

**Task:** Task 2

**Severity:** WARNING

**Description:** The action describes GET-before-PUT as:
```
If exit code == 0, print "WARN: bucket already has a lifecycle configuration..."
If exit code != 0 AND output contains "NoSuchLifecycleConfiguration", treat as expected (first apply).
If exit code != 0 AND output does NOT contain "NoSuchLifecycleConfiguration" AND does not contain "NotImplemented", abort with "FATAL: unexpected error..."
```

This logic is incomplete. If the response contains "NotImplemented", it should be an **error**, not just another branch. The script should:
```
If output contains "NotImplemented":
  print "FATAL: Timeweb S3 does not support lifecycle API — S3-03 proof must be completed first" exit 1
```

**Fix Required:** Task 2 action must clarify:
> "If the output contains "NotImplemented", exit 1 with message: 'FATAL: Timeweb S3 endpoint does not support lifecycle API at this endpoint. S3-03 empirical proof did not complete successfully. Do not apply retention policy.'"

---

### WARNING: Plan 02, Task 1 — kubectl Dry-Run Validation Insufficient

**Dimension:** Verification Derivation

**Plan:** 10-02

**Task:** Task 1

**Severity:** WARNING

**Description:** The `<verify>` step uses `kubectl apply --dry-run=client` to validate the Job manifest. However, this only validates the **YAML structure**, not the **shell script** embedded in the `args` field.

The Job's command is an 8-line shell script with complex logic (apk add, aws configure, API probe, PUT/HEAD, cleanup). A syntax error in this shell script would not be caught by kubectl dry-run.

**Example:** If the script contains a stray backtick or unquoted variable, kubectl dry-run will still pass (it parses the YAML), but the Job will fail at runtime.

**Current Verify:**
```bash
kubectl apply --dry-run=client --validate=false -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml
# Plus grep checks for presence of certain strings
```

**Fix Required:** Add explicit shell syntax check to the task's `<verify>`:
```bash
# Extract the args from the Job and run bash -n on the embedded script
# (This requires parsing YAML to extract args, which is complex)
# OR: Add a comment in the Job manifest with a stand-alone version of the script
# that can be validated with bash -n
```

Alternatively, document that the embedded script cannot be validated offline and must be tested at runtime.

---

### WARNING: Plan 01, Task 3 — validate-s3-lifecycle.py Validation Does Not Check JSON Structure

**Dimension:** Requirement Coverage

**Plan:** 10-01

**Task:** Task 3

**Severity:** WARNING

**Description:** The task adds `validate_s3_lifecycle_config()` to validate-staging.py that checks:
```python
- asserts "Rules" key is present and non-empty
- asserts one Rule with Filter.Prefix == "backups/postgres/" and Expiration.Days >= 1
- asserts one Rule with AbortIncompleteMultipartUpload
```

However, this validation is **string-based**, not **structural**. It checks:
```python
any(r.get('Filter',{}).get('Prefix')=='backups/postgres/' for r in d['Rules'])
```

This assumes the JSON will have the exact keys and nesting. If the JSON is malformed (e.g., `Filter` is a string instead of an object, or `Rules` is missing), the assertion will fail ungracefully or pass when it shouldn't.

**Better Approach:** Parse the JSON structure explicitly:
```python
def validate_lifecycle_json():
    with open(config_file) as f:
        config = json.load(f)
    
    assert 'Rules' in config and isinstance(config['Rules'], list), "Rules must be a non-empty list"
    assert len(config['Rules']) > 0, "Rules list is empty"
    
    # Check for Expiration rule
    has_expiration = False
    for rule in config['Rules']:
        if rule.get('Filter', {}).get('Prefix') == 'backups/postgres/':
            assert rule.get('Status') == 'Enabled', "Expiration rule must be Enabled"
            assert 'Expiration' in rule, "Expiration rule missing Expiration key"
            assert rule['Expiration'].get('Days', 0) >= 30, "Days must be >= 30"
            has_expiration = True
    assert has_expiration, "Missing Expiration rule for backups/postgres/"
    
    # Check for AbortIncompleteMultipartUpload rule
    has_abort = any('AbortIncompleteMultipartUpload' in rule for rule in config['Rules'])
    assert has_abort, "Missing AbortIncompleteMultipartUpload rule"
```

**Fix Required:** Plan 01, Task 1 must include strict structural validation of the JSON, not just string matching.

---

### INFO: Plan 01, 02, 03 — No Explicit CONTEXT.md Decision References

**Dimension:** Context Compliance

**Plans:** 10-01, 10-02, 10-03

**Severity:** INFO

**Description:** CONTEXT.md defines several locked decisions (S3 endpoint, path-style addressing, in-cluster-creds pattern, lifecycle policy file location, 30-day retention window, etc.). The plans reference these decisions conceptually (e.g., "30 days" is mentioned) but do not include explicit `D-XX` markers or citations to the CONTEXT.md section.

This is not a blocker, but it weakens traceability. Future readers cannot quickly link plan artifacts back to the decisions that shaped them.

**Recommendation (non-blocking):** Plan frontmatter could include:
```yaml
decisions_implemented:
  - "30-day retention window (CONTEXT.md, Claude's discretion)"
  - "in-cluster-creds pattern via Job (CONTEXT.md, locked by codebase facts)"
  - "config/s3/backups-lifecycle.json location (CONTEXT.md, Claude's discretion)"
```

---

## Dimension Verification Results

| Dimension | Status | Notes |
|-----------|--------|-------|
| Requirement Coverage | BLOCKED | S3-01 JSON structure undefined; S3-02 structure assumed but not specified; S3-03 ordering not enforced |
| Task Completeness | BLOCKED | Plan 01 Task 1 and Task 2 actions are incomplete; no executable specification |
| Dependency Correctness | BLOCKED | Plan 02 should depend on Plan 01 to enforce probe-before-apply ordering |
| Key Links Planned | BLOCKED | apply-s3-lifecycle.sh → config/s3/backups-lifecycle.json wiring not yet defined (design flaw in embed approach) |
| Scope Sanity | PASS | 3 tasks per plan; file counts reasonable; context budget within limits |
| Verification Derivation | PASS | must_haves are user-observable (offline validator, apply script, runbook, evidence recorded) |
| Context Compliance | NEEDS_DETAIL | Locked decisions present in action text but not explicitly cited; no scope reduction detected |
| Architectural Tier Compliance | PASS | All work assigned to correct tier (API/Job tier for S3 operations, no unauthorized tier migrations) |
| Cross-Plan Data Contracts | PASS | No shared data pipelines or transform conflicts |
| CLAUDE.md Compliance | PASS | Project conventions followed (bash/python style, stdlib-only, security context, RBAC patterns) |

---

## Recommendation

**DO NOT EXECUTE these plans.** Return to the planner with the following requirements:

1. **Plan 01, Task 1:** Provide the complete, executable JSON structure for `config/s3/backups-lifecycle.json`. Include all keys, values, and nesting exactly as the file will appear in git.

2. **Plan 01, Task 2:** Redesign the apply-s3-lifecycle.sh Job-creation mechanism to avoid shell-escaping risks. Use **ConfigMap approach (Option A)** — this mirrors existing patterns and is safer.

3. **Plan 02:** Add `depends_on: ["10-01"]` to enforce Wave 2. This ensures the policy is created before the probe is available.

4. **Plan 03, Task 3:** Add explicit Evidence-filled validation to the checkpoint. Resume-signal must require Evidence table to be populated before "approved" is accepted.

5. **Plan 01, Task 2:** Clarify that "NotImplemented" in GET output is a fatal error, not a fallthrough case.

6. **Plan 01, Task 1:** Add strict structural validation to validate-s3-lifecycle.py, not just string matching.

---

## Summary

**Phase Goal Achievement:** ❌ BLOCKED

The three plans claim to deliver S3-01, S3-02, S3-03, but:
- **S3-01 (policy stored, script-applied):** Blocked by undefined JSON structure and unsafe shell-escaping in apply script
- **S3-02 (AbortIncompleteMultipartUpload):** Blocked by inability to validate JSON structure
- **S3-03 (empirical proof before reliance):** Blocked by lack of ordering enforcement and insufficient evidence gate

**Issue Count:** 8 issues (4 blockers, 4 warnings, 0 info)

**Path Forward:** Planner must address all 4 blockers. Warnings are improvements but not execution-blocking. Return plans with revised Task 1, Task 2, Task 3, and corrected dependencies for re-verification.

