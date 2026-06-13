---
phase: 10-s3-lifecycle-retention
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - config/s3/backups-lifecycle.json
  - scripts/apply-s3-lifecycle.sh
  - scripts/validate-s3-lifecycle.py
  - k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml
  - scripts/validate-staging.py
  - docs/s3-lifecycle.md
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 10 adds a repo-stored S3 lifecycle policy (30-day expiration on `backups/postgres/`
plus a bucket-wide abort-incomplete-multipart rule), an operator-run in-cluster apply script,
an operator-gated empirical probe Job, an offline validator, and a runbook.

I reviewed this adversarially with a focus on the production-retention blast radius. The
central safety question — **can this policy ever expire objects outside `backups/postgres/`?**
— answers **no**. The destructive rule (`Expiration`) carries a non-empty `Filter.Prefix`
of `backups/postgres/`, which exactly matches the backup writer's object layout in
`60-postgres-backup.yaml` (`backups/postgres/<id>/...`). The empty-prefix rule is bucket-wide
but only carries `AbortIncompleteMultipartUpload`, which never touches completed objects.
Both the apply Job (inline, never written to disk) and the probe Job (in a `s3-lifecycle/`
subdirectory) are provably outside the CD `-maxdepth 1` glob, so neither can run unattended.
No secret values appear in any manifest, script, or doc. No BLOCKERs.

The findings below are quality/robustness gaps: a validator-strictness mismatch between the
CI-wired and standalone validators, a clobber-without-halt behavior on existing configs, a
hardening inconsistency between the apply Job and the probe Job, and a few documentation/
robustness nits.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: CI validator accepts `Days >= 1`; only the un-wired standalone validator enforces `Days >= 30`

**File:** `scripts/validate-staging.py:382` (vs `scripts/validate-s3-lifecycle.py:57`)
**Issue:** Two validators check the same JSON with different strictness. The standalone
`validate-s3-lifecycle.py` requires `isinstance(days, int) and days >= 30`. But CI only runs
`validate-staging.py` (see `.github/workflows/deploy-staging.yml:37`), and its
`validate_s3_lifecycle_config()` requires only `days >= 1`. A future edit dropping
`Expiration.Days` to e.g. `1` (expiring backups after a single day) would pass CI. The
"30-day floor" the phase intends is therefore not actually enforced on the path that gates
merges. The stricter standalone validator is never invoked by CI (`validate-staging.py:187`
only `py_compile`s it; it never calls its `main()`).
**Fix:** Tighten the CI-wired check to match the intended floor, in
`scripts/validate-staging.py:382`:
```python
require(isinstance(days, int) and days >= 30, "Expiration.Days must be an integer >= 30")
```
(Or, if a sub-30 window must remain possible, document that explicitly and drop the `>= 30`
claim from `validate-s3-lifecycle.py` so the two validators stop disagreeing.)

### WR-02: GET-before-PUT only WARNs on an existing lifecycle config, then silently overwrites it

**File:** `scripts/apply-s3-lifecycle.sh:114-115`, `123-125`
**Issue:** When the bucket already has a lifecycle configuration, the script prints
`WARN: bucket already has a lifecycle configuration — review before applying` and then
**proceeds to PUT anyway**, fully replacing the existing config (`put-bucket-lifecycle-configuration`
is a wholesale replace, not a merge). The operator cannot review before the overwrite happens —
the WARN and the destructive PUT are in the same non-interactive run. The phase brief explicitly
asks whether the script "correctly avoids clobbering an existing lifecycle config without operator
awareness"; as written it does not. The existing rules (which could include retention windows for
other prefixes someone added out-of-band) are gone with no backup printed.
**Fix:** On the existing-config branch, dump the current config and either abort by default or
gate behind an explicit opt-in env var. Minimal version:
```sh
elif [ "$get_rc" -eq 0 ]; then
  echo "WARN: bucket already has a lifecycle configuration:" >&2
  echo "$get_output" >&2
  if [ "${FORCE_OVERWRITE:-}" != "1" ]; then
    echo "FATAL: refusing to overwrite existing lifecycle config; set FORCE_OVERWRITE=1 to proceed after review" >&2
    exit 1
  fi
```
At minimum, echo `$get_output` so the replaced config is captured in the Job logs as a record.

### WR-03: apply Job is less hardened than the probe Job (no `capabilities: drop: ALL`)

**File:** `scripts/apply-s3-lifecycle.sh:98-99`
**Issue:** The probe Job (`80-s3-lifecycle-probe-job.yaml:111-114`) sets
`allowPrivilegeEscalation: false` **and** `capabilities: drop: ["ALL"]`. The apply Job's
inline securityContext sets only `allowPrivilegeEscalation: false` — it omits the capability
drop. The apply Job is the one with **write** access to bucket lifecycle config, so it warrants
at least the same hardening as the read-mostly probe. (It does correctly use a dedicated-ish SA
`postgres-backup` and `automountServiceAccountToken: false`.) Note this matches the weaker
pattern in `60-postgres-backup.yaml:139-140`, so it is consistent with project precedent — but
the probe in this same phase sets the bar higher, making the inconsistency stand out.
**Fix:** Mirror the probe's context in the inline Job spec:
```yaml
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
```

### WR-04: `apk add aws-cli` at container start makes both Jobs fail-open on registry/network outages, with no pinning

**File:** `scripts/apply-s3-lifecycle.sh:104`, `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml:42`
**Issue:** Both Jobs install the AWS CLI at runtime via `apk add --no-cache aws-cli` against the
Alpine package mirror. This is an unpinned, network-dependent dependency fetched at execution
time. If the mirror is unreachable or ships a breaking aws-cli major bump, the apply/probe behave
unpredictably (the apply Job would fail before the PUT, which is the safe direction; but the
behavior is non-reproducible and the version is whatever Alpine serves that day). The phase's own
core value is reproducibility.
**Fix:** Acceptable to defer (matches `60-postgres-backup.yaml` precedent), but track it: pin the
package (`apk add --no-cache aws-cli=<ver>`) or move to an image with the CLI baked in. At minimum,
note the runtime-install dependency in `docs/s3-lifecycle.md` as a known fragility.

### WR-05: probe's `x-amz-expiration` detection greps a broad pattern (`expir`) that can yield a false PRESENT

**File:** `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml:70`
**Issue:** `if echo "$head_output" | grep -qi "expir"` matches any line containing "expir"
anywhere in the full `head-object` JSON — not just the `x-amz-expiration` header. If a future
Timeweb response includes an unrelated field or an error string containing "expir" (e.g.
"Expiration", "expired credentials", "ServerSideEncryption…expires"), the probe reports
`x-amz-expiration PRESENT` and the operator may record false evidence that the rule is recognized.
Since S3-03 evidence is the gate for a destructive apply, a false-positive here weakens the gate.
**Fix:** Match the actual header key returned by `head-object`, which surfaces as the
`Expiration` top-level field in the AWS CLI JSON output:
```sh
if echo "$head_output" | grep -qi '"Expiration"'; then
```
or parse explicitly with `aws s3api head-object --query 'Expiration'` and test for non-empty/non-`null`.

## Info

### IN-01: Probe documents a "PUT a rule for `s3-lifecycle-probe/` and re-run" step that has no supporting tooling

**File:** `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml:73-74`, `docs/s3-lifecycle.md:179-181`
**Issue:** Both the probe and the runbook instruct the operator, on an ABSENT expiry header, to
"add a temporary rule for `s3-lifecycle-probe/` and re-run the probe." No artifact in the phase
provides such a temporary rule, and `apply-s3-lifecycle.sh` applies the production
`backups-lifecycle.json` (which targets `backups/postgres/`, not the probe prefix). The operator
is left to hand-craft this. Not a bug, but the documented follow-up is unsupported by the shipped
tooling.
**Fix:** Either ship a `config/s3/probe-lifecycle.json` for the probe prefix, or reword the
guidance to say the operator must hand-author the temporary rule.

### IN-02: Probe is not self-cleaning if the PUT/HEAD steps fail before cleanup

**File:** `k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml:63-78`
**Issue:** The script is a linear `sh -ec` (errexit). If `s3 cp` (PUT, line 64) or `head-object`
(line 67) fails, the script exits before the cleanup `s3 rm` (line 78), leaving the test object
in `s3-lifecycle-probe/`. The phase claims the probe "self-cleans"; that holds on the happy path
only. The leaked object is harmless (isolated prefix, no retention rule deletes it automatically),
but the self-clean guarantee is weaker than stated.
**Fix:** Use a trap so cleanup always runs:
```sh
cleanup() { aws --endpoint-url="$S3_ENDPOINT" s3 rm "s3://$S3_BUCKET/$TEST_KEY" --only-show-errors || true; }
trap cleanup EXIT
```

### IN-03: Apply Job has no `securityContext.runAsNonRoot` / pod-level context; runs as root to `apk add`

**File:** `scripts/apply-s3-lifecycle.sh:98-99` and `80-s3-lifecycle-probe-job.yaml:111-114`
**Issue:** Neither Job sets `runAsNonRoot`/`runAsUser`; both run as root so `apk add` can write the
package DB (same trade-off as the drill `fetch-backup` initContainer, which is documented in
`validate-staging.py:337-339`). This is an accepted pattern in the repo, noted only so the choice
is explicit and not mistaken for an oversight. Tied to WR-04 — baking the CLI into the image would
remove the need to run as root.
**Fix:** No change required if runtime `apk add` stays; revisit alongside WR-04.

### IN-04: `validate-s3-lifecycle.py` is effectively dead relative to CI

**File:** `scripts/validate-s3-lifecycle.py` (whole file)
**Issue:** This standalone validator duplicates `validate_s3_lifecycle_config()` in
`validate-staging.py` but is never executed by CI — `validate-staging.py:187` only compiles it.
It can therefore drift from the CI-enforced checks indefinitely (it already has, per WR-01).
Maintaining two near-identical validators invites exactly the strictness mismatch flagged above.
**Fix:** Either invoke `validate-s3-lifecycle.py` from CI (so its `>= 30` floor is enforced) or
fold its stricter assertions into `validate-staging.py` and delete the standalone file to remove
the divergence.

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
