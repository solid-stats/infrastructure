---
phase: 08-automated-restore-drill
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - k8s/staging/restore-drill/70-restore-drill.yaml
  - scripts/restore-drill.sh
  - scripts/validate-staging.py
  - docs/backup-restore.md
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the automated restore-drill Job, its trigger script, the staging
validator, and the runbook. The **DRILL-01 safety design is sound** — no
`postgres-data` PVC mount, scratch postgres on `emptyDir`, a refuse-if-not-localhost
barrier that runs before any DB op, and `PGHOST/PGPORT/PGUSER` forced to localhost.
The S3 latest-backup discovery, manifest.json gate, lexicographic sort, aws-cli
endpoint/region/path-style/metadata-disabled, and `secretKeyRef`-only (no secret
values in YAML) are all correct. The captured-rc teardown design is correct *in the
happy path* — `dropdb`/`pg_ctl stop` use `|| true` while the real exit comes from
`exit $drill_result`.

**However, the Job will crash at runtime before it ever restores anything, and a
true assertion failure can be silently skipped.** Three BLOCKERs make this drill
unrunnable / unsafe-to-trust as written:

1. The container runs as **root (uid 0)** — `initdb`/`pg_ctl initdb` hard-refuse to
   run as root, so the scratch postgres never initializes. The Job dies at Step 3.
2. **`$PGPASSWORD` is never set** — the env block injects `POSTGRES_PASSWORD`, but
   the script reads `$PGPASSWORD`. initdb writes an *empty* superuser password and
   no client has a password, so md5 auth blocks every later `createdb`/`psql`/
   `pg_restore`.
3. An empty `table_count` (psql error / connection failure) makes the `[ "" -lt 5 ]`
   test evaluate **false**, so the table-count assertion is silently skipped — a
   path to a **false PASS** when psql misbehaves rather than returns a real count.

None of these are caught by CI: `validate-staging.py` only bash-syntax-checks the
trigger script and asserts the drill manifest is not at depth-1; it never validates
the drill manifest's content. Running this live now wastes the run.

## Critical Issues

### CR-01: Scratch postgres never initializes — container runs as root, initdb refuses

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:34-39, 52-77`
**Issue:** The pod `securityContext` sets only `fsGroup: 999`; there is **no
`runAsUser`/`runAsNonRoot`**. The `postgres:17-alpine` image only drops to uid 999
(postgres) inside its `docker-entrypoint.sh`, which is **bypassed here** because
`command:` is overridden to `/bin/sh`. The shell therefore runs as **root (uid 0)**.
`pg_ctl initdb` (line 77) invokes `initdb`, which hard-refuses to run as root:
`initdb: error: cannot be run as root`. The Job crashes at Step 3 before any restore.
This was not caught because CI does not exercise the drill manifest.
**Fix:** Run the container as uid 999 so the bypassed entrypoint's normal user is
restored. Add to the pod (or container) securityContext:
```yaml
      securityContext:
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
        runAsNonRoot: true
```
`emptyDir` is writable by the pod user, and `fsGroup: 999` already grants group
ownership of `/scratch` to gid 999, so uid 999 can write `pgdata`. Verify initdb and
`pg_ctl start` succeed under uid 999 in a dry run before the live drill.

### CR-02: `$PGPASSWORD` is empty — superuser gets a blank password, all later libpq calls fail

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:76, 107, 116, 121, 145-150`
**Issue:** Line 76 does `printf '%s' "$PGPASSWORD" > /scratch/pgpwfile` and passes it
to `initdb -A md5 --pwfile=`, but the env block only defines **`POSTGRES_PASSWORD`**
(lines 146-150) — `PGPASSWORD` is never exported. `$PGPASSWORD` expands to empty, so:
(a) the scratch superuser is created with an **empty** password, and
(b) `createdb`/`psql`/`pg_restore` (lines 107, 108, 116, 121, 139) run with no
`PGPASSWORD` either, so under `md5` auth over TCP (`-h localhost`) they are prompted
for a password on a non-interactive Job and fail. Note: the password value is
irrelevant for safety since this is a throwaway scratch DB, but it must be consistent
between initdb and clients, or use a no-password local auth method.
**Fix:** Simplest — drop the password requirement entirely and use trust auth for the
ephemeral localhost-only scratch instance (it is isolated on emptyDir, never exposed):
```sh
              pg_ctl initdb -D "$initdb_dir" -A trust
              # remove pwfile lines 76, 78 entirely
```
Or, if keeping md5, set a self-generated password and export it for clients:
```sh
              export PGPASSWORD="$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
              printf '%s' "$PGPASSWORD" > /scratch/pgpwfile
              pg_ctl initdb -D "$initdb_dir" -A md5 --pwfile=/scratch/pgpwfile
              rm /scratch/pgpwfile
```
The injected `POSTGRES_PASSWORD` secret is unnecessary for a scratch DB; consider
removing it from `env` to avoid mounting the live postgres secret into the drill.

### CR-03: Empty `table_count` silently skips the assertion — path to a false PASS

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:116-119`
**Issue:** If the `psql` table-count query fails or returns empty (connection issue,
auth failure, transient error), `table_count` is the empty string. The guard is
`if [ "$table_count" -lt 5 ]` (line 118). With an empty value, `[` errors with
`[: Illegal number:` on stderr **and evaluates false** inside an `if` (where errexit
is suppressed), so the FAIL branch is skipped and `drill_result` stays `0`. Combined
with the `|| true` on `pg_restore` (line 110), a restore that produced no usable DB
can still emit `DRILL_RESULT=PASS`. The `total_rows` check uses `${row_count:-0}`
which correctly defaults empty→0 and would catch *that* case, but `table_count` has
no such guard, and the printed `table_count=` field in the PASS line would be blank —
easy to miss. A false PASS on a recovery drill is the worst possible outcome.
**Fix:** Default and validate `table_count` is a real number before comparing:
```sh
              table_count=$(psql ... -c "SELECT COUNT(*) ...")
              case "$table_count" in
                ''|*[!0-9]*) echo "FAIL: table_count query returned non-numeric '$table_count'"; drill_result=1; table_count=0;;
                *) [ "$table_count" -lt 5 ] && { echo "FAIL: table_count=${table_count} (expected >= 5)"; drill_result=1; };;
              esac
```
Apply the same numeric-validation pattern to `row_count`.

## Warnings

### WR-01: `set -e` aborts before Step 8/9 if any assertion query fails — teardown skipped

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:54, 116, 121, 126`
**Issue:** The shell runs `sh -ec` (errexit on). A failed **command-substitution
assignment** such as `table_count=$(psql ...)` aborts the whole script immediately
(verified: under `sh -e`, `x=$(false)` exits 1 and the next line never runs). If a
`psql`/`wc` assertion command itself exits non-zero, the script dies at that line, so
**Step 8 teardown and Step 9 `exit $drill_result` never execute**. The Job still
exits non-zero (so this is not a false PASS — good), but the scratch DB/process are
not torn down in-script. The pod self-cleans via `ttlSecondsAfterFinished: 3600`, so
this is degraded hygiene, not data loss. Note this also interacts with CR-03: the
abort only happens if psql *exits non-zero*; if psql exits 0 with empty stdout the
script continues into the false-PASS path.
**Fix:** Either wrap the assertion block so failures set `drill_result=1` and fall
through to teardown, or run teardown in an `EXIT` trap so it always runs:
```sh
              cleanup() { dropdb -h localhost -U postgres solid_stats_drill 2>/dev/null || true
                          pg_ctl -D "$initdb_dir" stop 2>/dev/null || true; }
              trap cleanup EXIT
```

### WR-02: `pg_restore ... || true` masks restore failures except the table/row counts catch them

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:108-110`
**Issue:** `pg_restore` runs with `|| true`, so a non-zero restore (partial failure,
version mismatch, corrupt dump) is swallowed. The drill relies entirely on the
downstream table/row-count assertions to detect a bad restore. That is acceptable
*if* CR-03 is fixed (otherwise a bad restore + empty `table_count` = false PASS). Even
with the counts fixed, the actual `pg_restore` exit code and its stderr (which names
the failing object) are lost from the evidence.
**Fix:** Capture the rc instead of discarding it and surface it in the FAIL line:
```sh
              if ! pg_restore --host=localhost --username=postgres \
                   --dbname=solid_stats_drill --no-owner --no-privileges \
                   /scratch/solid_stats.dump; then
                echo "WARN: pg_restore exited non-zero (continuing to assertions)"; fi
```
`pg_restore` of a custom-format dump can legitimately emit non-fatal warnings, so do
not hard-fail on rc alone, but do log it.

### WR-03: 30-second startup wait may be too short for a large restore-host initdb+start

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:80-86`
**Issue:** The readiness loop waits at most 30×1s. `initdb` + first start on a
constrained pod (cpu request 100m, but limit 1) under contention can exceed 30s,
especially the first time the image's `apk add aws-cli` and initdb run cold. A
too-short wait yields a spurious `ERROR: scratch postgres did not start` and a Job
failure that looks like a backup problem.
**Fix:** Raise the bound (e.g. 60) and back off, and surface the postgres log on
timeout so the operator can distinguish startup failure from a real backup defect:
```sh
              i=0; while [ $i -lt 60 ]; do pg_isready -h localhost -p 5432 -U postgres >/dev/null 2>&1 && break; i=$((i+1)); sleep 1; done
              if ! pg_isready -h localhost -p 5432 -U postgres >/dev/null 2>&1; then
                echo "ERROR: scratch postgres did not start"; cat /scratch/postgres.log >&2 || true; exit 1; fi
```

### WR-04: Missing container-hardening fields the project's own convention/CI require elsewhere

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:47-48`
**Issue:** The container `securityContext` only sets `allowPrivilegeEscalation:
false`. The project convention (AGENTS.md: "add pod/container security context where
images allow it") and the kubernetes-specialist skill call for `capabilities: drop:
[ALL]` and, where possible, `runAsNonRoot`. Because the drill manifest lives in the
`restore-drill/` subdirectory, `validate-staging.py` never checks it, so it escaped
the workload-safety gate that every other workload passes. After fixing CR-01 to run
as uid 999, add the remaining hardening.
**Fix:**
```yaml
          securityContext:
            allowPrivilegeEscalation: false
            runAsNonRoot: true
            capabilities:
              drop: ["ALL"]
            # readOnlyRootFilesystem: true is NOT viable here — apk add and pg_ctl
            # write to the rootfs; document this exception or move writes under /scratch.
```

### WR-05: Drill manifest is entirely unvalidated by CI — content drift goes undetected

**File:** `scripts/validate-staging.py:189-205, 249-269`
**Issue:** `validate_manifest_shape` globs only `MANIFEST_DIR.glob("*.yaml")` (depth-1)
and the DRILL-04 check actively *requires* the drill yaml to be absent from depth-1.
So the drill manifest's apiVersion/kind/securityContext/SA/resources are never
shape-checked or dry-run-applied. The exact safety-critical fields (CR-01/CR-02 above)
that make the Job runnable have no automated guard. A future edit reintroducing a
`postgres-data` mount or a non-localhost host would not be caught here.
**Fix:** Add a dedicated, narrow check that the drill manifest exists in the
subdirectory and asserts its invariants (no `postgres-data` volume, no
`name: postgres` Service reference, `automountServiceAccountToken: false`,
`emptyDir` scratch, `runAsUser`/`runAsNonRoot` present). Keep it separate from the
depth-1 glob so DRILL-04 stays intact.

## Info

### IN-01: `AWS_CONFIG_FILE` set before scratch dir guaranteed writable — relies on emptyDir mount

**File:** `k8s/staging/restore-drill/70-restore-drill.yaml:62-63`
**Issue:** `AWS_CONFIG_FILE=/scratch/aws-config` and `aws configure set ...` write to
`/scratch` at Step 1, before the readiness checks. `/scratch` is the emptyDir mount so
it is writable, but after CR-01's `runAsNonRoot` fix confirm uid 999 can write there
(fsGroup 999 covers it). No change needed if CR-01 is applied; flagging the ordering
dependency.
**Fix:** None required; verify in the dry run.

### IN-02: Runbook "Live drill evidence" placeholder still empty and example values are fictional

**File:** `docs/backup-restore.md:77-79, 107-117`
**Issue:** The expected-output block uses an example `backup_id=20260613T060000Z`
which happens to equal a plausible real id, and the operator-evidence section is an
unfilled placeholder. After the live run fails on CR-01/CR-02 the operator must not
paste a PASS line that was never actually produced.
**Fix:** Leave the placeholder; ensure the operator captures the *actual* evidence
line only after CR-01–CR-03 are fixed and the drill genuinely passes.

### IN-03: Trigger script `wait --for=condition=complete` with `backoffLimit:0` — failure detection relies on timeout

**File:** `scripts/restore-drill.sh:19-25`
**Issue:** `kubectl wait --for=condition=complete` does not return early on Job
*failure*; with `backoffLimit: 0` the Job gets a `Failed` condition, but the script
only waits for `complete`, so a fast failure still blocks until the 900s timeout
before the script reports it. Functionally correct (it does exit 1 and dump logs),
just slow on failure.
**Fix (optional):** Wait on either condition, e.g. poll
`kubectl wait --for=condition=failed job/$job_name --timeout=...` in parallel, or
check `.status.failed` after a short interval to fail fast.

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
