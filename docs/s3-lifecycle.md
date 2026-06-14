# S3 Lifecycle Retention

This runbook covers the S3 retention lifecycle policy for `backups/postgres/` objects in the
Solid Stats staging S3-compatible bucket. It documents the apply procedure, the empirical proof
procedure required before first apply, the async expiry caveat, and the operator gate.

Requirements satisfied by this plan set: S3-01 (policy stored and script-applied), S3-02
(AbortIncompleteMultipartUpload), S3-03 (empirical lifecycle API support proven before relying on retention).

**Operator gate.** Applying the real lifecycle policy to the production backup bucket is a
consequential, retention-affecting action — it will permanently delete `backups/postgres/` objects
older than 30 days once active. Run the empirical probe (Section 4) and record S3-03 evidence
(Section 5) before running the apply procedure (Section 3). Do not apply without evidence on record.

---

## 1. Overview

The lifecycle policy expires PostgreSQL backup objects after 30 days and aborts any stuck
incomplete multipart uploads after 7 days.

### Why 30 days

Thirty days retains approximately 30 daily backup points — a conservative window that covers
multi-week outage scenarios and provides time for manual intervention before the oldest backup is
lost. The operator may raise `Expiration.Days` in `config/s3/backups-lifecycle.json` before the
first apply without any code change.

### Scope

The expiration rule is scoped strictly to the `backups/postgres/` prefix. Replay files, parser
artifacts, and any other prefixes are not affected by this policy. S3-04 (distinct windows for
other prefixes) is deferred to v2.x.

---

## 2. Lifecycle Policy File

**Location:** `config/s3/backups-lifecycle.json`

The file is a `PutBucketLifecycleConfiguration` JSON object with two rules:

### Rule 1: expire-postgres-backups

```json
{
  "ID": "expire-postgres-backups",
  "Status": "Enabled",
  "Filter": { "Prefix": "backups/postgres/" },
  "Expiration": { "Days": 30 }
}
```

Scoped to `backups/postgres/` only. Objects under this prefix are eligible for expiration 30 days
after creation. The operator may increase `Days` before first apply; decreasing it narrows the
retention window and is a consequential change requiring deliberate review.

### Rule 2: abort-incomplete-multipart

```json
{
  "ID": "abort-incomplete-multipart",
  "Status": "Enabled",
  "Filter": { "Prefix": "" },
  "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 }
}
```

Bucket-wide (empty prefix). Aborts any incomplete multipart upload after 7 days — the standard
AWS-recommended window. Only affects uploads that were initiated but never completed; it does not
touch successfully uploaded objects. Satisfies S3-02.

This file contains no secrets. All values are prefix strings and day counts. Safe to commit.

---

## 3. Apply Procedure (S3-01)

**Pre-requisites:**

1. SSH local-forward to the staging cluster is up (`kubectl cluster-info` confirms the API is reachable).
2. `KUBECONFIG` is configured for `solid-stats-staging` (`kubectl get ns solid-stats-staging`
   should succeed).
3. The empirical probe (Section 4) has been run and the Evidence table (Section 5) is filled with
   real results. A blank Evidence table means the policy has NOT been proven — do not proceed.

**Steps:**

1. Review `config/s3/backups-lifecycle.json`. Confirm the `Expiration.Days` value is acceptable
   for the current backup retention requirement.

2. Run the apply script from the repository root:

   ```bash
   bash scripts/apply-s3-lifecycle.sh
   ```

   The script:
   - Creates a temporary ConfigMap from `config/s3/backups-lifecycle.json` (avoids shell-escaping
     hazards with double-quote-heavy JSON in heredoc YAML).
   - Launches a one-shot in-cluster Job that mounts the ConfigMap and reads S3 credentials from
     the `server-2-runtime` Kubernetes Secret (`S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
     `S3_BUCKET`). Credentials never leave the cluster.
   - Performs a GET-before-PUT check: warns (`WARN:`) if an existing lifecycle configuration is
     found on the bucket; exits 1 if `NotImplemented` is returned (Timeweb does not support the
     lifecycle API — see S3-03 gate). If `NoSuchLifecycleConfiguration` is returned, applies
     cleanly.
   - Calls `aws s3api put-bucket-lifecycle-configuration` with `file:///config/backups-lifecycle.json`.
   - Prints `lifecycle configuration applied successfully` on success.
   - Cleans up the Job and ConfigMap automatically.

3. Confirm the Job completes:

   ```bash
   # The script waits and prints logs automatically. If you need to check manually:
   kubectl logs job/<job-name> -n solid-stats-staging
   ```

   Look for: `lifecycle configuration applied successfully`

   If a `WARN:` line appears (existing config detected), review the existing policy before
   confirming you intend to overwrite it. The script still applies; the WARN is informational.

4. If the Job does not complete within the timeout (default 120 s), the script exits 1 and prints
   the Job description and logs automatically. Check the logs for the root cause before re-running.

**Idempotent:** re-running `apply-s3-lifecycle.sh` is safe. It will WARN if a config already
exists but will still apply. Confirm intent before re-running if you see the WARN.

---

## 4. Empirical Proof Procedure (S3-03)

**Why this step is required.**

Timeweb S3 lifecycle API parity with AWS S3 is rated MEDIUM confidence. The
`get-bucket-lifecycle-configuration` and `put-bucket-lifecycle-configuration` endpoints must be
implemented for the retention policy to take effect. Run this probe before relying on the policy.

**Pre-requisites:** same cluster access as Section 3 (SSH local-forward up, KUBECONFIG set).

**Steps:**

1. Apply the probe Job:

   ```bash
   kubectl apply -f k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml -n solid-stats-staging
   ```

   The manifest is in the `k8s/staging/s3-lifecycle/` subdirectory (not depth-1) so the CD apply
   glob never reaches it. It must be applied manually.

2. Wait for the Job to complete:

   ```bash
   kubectl wait --for=condition=complete job/s3-lifecycle-probe -n solid-stats-staging --timeout=120s
   ```

3. Collect logs:

   ```bash
   kubectl logs job/s3-lifecycle-probe -n solid-stats-staging
   ```

4. Review the API support result. Look for one of:

   - `RESULT: API implemented — no lifecycle config currently set` — API is supported; no policy
     applied yet (expected on first probe run).
   - `RESULT: API implemented — existing lifecycle config found` — API supported; a policy is
     already active on the bucket.
   - `RESULT: lifecycle API NOT implemented on this endpoint` — the endpoint does not support
     lifecycle management. Do NOT apply the retention policy. Escalate before proceeding.

5. Review the `x-amz-expiration` header result. Look for:

   - `RESULT: x-amz-expiration PRESENT` — the endpoint computes expiry headers; a lifecycle rule
     targeting the `s3-lifecycle-probe/` prefix (or a bucket-wide rule) is recognized.
   - `RESULT: x-amz-expiration ABSENT` — the endpoint did not return an expiry header. This is
     expected when no lifecycle rule currently targets the `s3-lifecycle-probe/` prefix. After
     running `apply-s3-lifecycle.sh`, add a temporary rule for `s3-lifecycle-probe/` and re-run
     the probe to observe the expiry header.

6. Confirm cleanup: look for `probe cleanup complete` in the logs.

7. Delete the Job object:

   ```bash
   kubectl delete job s3-lifecycle-probe -n solid-stats-staging
   ```

8. Record the results in the Evidence table (Section 5).

---

## 5. Evidence (S3-03)

This section must be filled before the apply procedure (Section 3) is run for the first time.
A blank evidence table means the policy has NOT been proven.

| Field | Value |
|-------|-------|
| Date of probe run | 2026-06-13 |
| Cluster endpoint | solid-stats-staging |
| API support result | **SUPPORTED** (confirmed 2026-06-13 via raw HTTP `--debug`). `get-bucket-lifecycle-configuration` on bucket `sg-replays` returns the AWS-standard **HTTP 404 `<Code>NoSuchLifecycleConfiguration</Code>`**. The `argument of type 'NoneType' is not iterable` seen via the high-level CLI is a **client-side aws-cli v2.32.7 bug** parsing the empty `<Message></Message>` of that 404 — NOT an unsupported API. `head-bucket` OK (creds valid). |
| Existing lifecycle config at probe time | None — clean bucket (404 `NoSuchLifecycleConfiguration`). |
| x-amz-expiration present | **Yes** — with a PUT rule on `s3-lifecycle-probe/`, a probe object's `head-object` returned `Expiration: expiry-date="Mon, 15 Jun 2026 00:00:00 GMT", rule-id="probe-roundtrip"`. Rule recognized, expiry computed. |
| Expiry date observed | Mon, 15 Jun 2026 00:00:00 GMT (probe object under a 1-day rule). |
| Cleanup confirmed | yes (probe test object created + deleted under `s3-lifecycle-probe/`; `backups/postgres/` untouched; diagnostic was read-only) |
| Operator | Pavlov Alexandr |

**S3-03 PROVEN (2026-06-13).** A reversible PUT→GET round-trip on the isolated
`s3-lifecycle-probe/` prefix confirmed the full lifecycle API:
`put-bucket-lifecycle-configuration` → 200; `get-bucket-lifecycle-configuration`
→ 200 with the rule round-tripped; a probe object's `head-object` returned a
computed `x-amz-expiration`. Timeweb implements GET + PUT correctly.

**CRITICAL caveat — `delete-bucket-lifecycle` is a NO-OP on Timeweb.** It returns
success (204) but the config persists (verified: 2 deletes + 50 s wait, rule
still present). **A lifecycle config can only be REPLACED via PUT, never
removed** — you cannot return the bucket to "no lifecycle". This is the rollback
story: to change/undo the policy, PUT a new config. See Section 7.

Consequence for the apply: the bucket currently holds a leftover harmless
`probe-roundtrip` rule (targets only the empty `s3-lifecycle-probe/` prefix) that
`delete` could not remove. The real apply's PUT will **replace** it — but because
a config is present, `apply-s3-lifecycle.sh` requires `FORCE_OVERWRITE=1`. The
destructive apply to `backups/postgres/` is still gated on a backup-inventory
review + operator confirmation (it expires objects older than 30 days).

Follow-up (non-blocking on this bucket): the apply guard + probe heuristic rely
on the high-level GET, which CRASHES (`NoneType is not iterable`) only on a CLEAN
bucket (empty-`<Message>` 404). This bucket is no longer clean, so the apply
works with `FORCE_OVERWRITE`; but a fresh bucket's FIRST apply would fail — fix
the guard to classify from the raw `<Code>` / HTTP status.

Raw diagnostic (2026-06-13): `GET /sg-replays?lifecycle` with no config → **HTTP
404** `<Error><Code>NoSuchLifecycleConfiguration</Code><Message></Message>...`
(the empty `<Message>` triggers the aws-cli `NoneType` crash); with a config →
**HTTP 200** + the `<LifecycleConfiguration>` rule. `head-bucket` OK.

---

## 6. Async Expiry Caveat

S3 lifecycle expiration is asynchronous. Objects are not deleted exactly at midnight on day 30.
AWS S3 — and Timeweb S3 where the lifecycle API is implemented — typically processes expiry within
24 hours after the expiry date, counted from the object creation date (not upload date). Do not
rely on exact-to-the-hour deletion.

The `x-amz-expiration` header in `head-object` is the best available signal that the rule is
recognized by the endpoint. It reports the computed expiry date for the specific object. Actual
deletion is confirmed by observing object count decrease over time:

```bash
aws --endpoint-url=https://s3.twcstorage.ru \
  s3 ls s3://$S3_BUCKET/backups/postgres/ --recursive \
  | wc -l
```

Run this periodically after the policy is applied to confirm old objects are being expired. Each
backup ID occupies three objects (`solid_stats.dump`, `.list`, `manifest.json`), so the count
should decrease in multiples of three as backup IDs age past 30 days.

---

## 7. Known fragilities

- **Runtime `apk add aws-cli` (WR-04).** Both the apply Job (`scripts/apply-s3-lifecycle.sh`)
  and the probe Job (`k8s/staging/s3-lifecycle/80-s3-lifecycle-probe-job.yaml`) install the AWS
  CLI at container start via `apk add --no-cache aws-cli` against the Alpine package mirror.
  This is an unpinned, network-dependent dependency fetched at execution time: if the mirror is
  unreachable, or Alpine ships a breaking aws-cli major bump, the Jobs behave non-reproducibly
  (the apply Job would fail before the PUT, which is the safe direction). This matches the
  existing `60-postgres-backup.yaml` precedent and is deliberately left as-is for consistency.
  To remove the fragility, either pin the package (`apk add --no-cache aws-cli=<ver>`) or move to
  an image with the CLI baked in — track this as a known operational risk until then.

- **Overwrite guard on apply (WR-02).** `apply-s3-lifecycle.sh` refuses to replace an existing
  bucket lifecycle configuration. If the bucket already has a config, the Job dumps it to the log
  and exits non-zero. To intentionally replace it after reviewing the dumped config, re-run with
  `FORCE_OVERWRITE=1` set in the environment.

- **`delete-bucket-lifecycle` is a NO-OP on Timeweb (proven 2026-06-13).** The endpoint accepts
  the call (returns success) but does NOT remove the configuration — verified with two deletes and
  a 50 s wait. **A lifecycle config can only be replaced (PUT), never deleted.** Implication for
  rollback: there is no "remove the policy" path — to change or undo retention you must PUT a
  different config. Plan policy changes as replacements, and treat the first apply as effectively
  permanent (modulo future PUTs).

- **High-level GET crashes on a clean bucket (aws-cli v2.32.7).** When the bucket has NO lifecycle
  config, Timeweb returns a 404 `NoSuchLifecycleConfiguration` with an empty `<Message></Message>`,
  and aws-cli's `get-bucket-lifecycle-configuration` raises `argument of type 'NoneType' is not
  iterable` (a client-side parse bug) instead of surfacing the error code. The apply guard then
  falls through to "unexpected error" and aborts (fail-safe). On a bucket that already has a config
  the GET returns 200 and works normally. The lifecycle API itself is fine — only the empty-message
  404 path is affected. Fix for a fresh-bucket first apply: classify from the raw `<Code>` / HTTP
  status (a `--debug` fallback) rather than the high-level call's exit/stdout.
