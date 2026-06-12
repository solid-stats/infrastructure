---
phase: 11-production-cutover
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - scripts/cutover.sh
  - docs/cutover.md
  - scripts/validate-staging.py
findings:
  critical: 1
  warning: 5
  info: 3
  total: 9
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-06-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Reviewed the production-cutover artifacts: the operator-run `scripts/cutover.sh`
(nginx upstream switch), the operator runbook `docs/cutover.md`, and the offline
CI validator `scripts/validate-staging.py` (specifically `validate_cutover_artifacts`).

**What holds up (verified by tracing + execution):**

- **Both gates genuinely block, including under DRY_RUN.** Control flow places the
  two `grep -q` gate checks (lines 128, 138) *before* the `DRY_RUN` early exit
  (line 150). A failing gate `exit 1`s under `set -e` before any mutation. Confirmed
  the current `docs/diff-readiness.md` has no literal `strict_failures: 0`, so the
  gate correctly blocks today.
- **Green-diff gate is coverage-only, never equality.** Script comments (lines 10,
  133-137), the runbook (lines 19-27, 61-71), and the validator's not-equality
  assertion (lines 458-460) are all consistent. No equality framing found anywhere.
- **Smoke check control flow is correct.** `http_code` capture with `|| true` +
  `[[ =~ ^[23] ]]` works; HTTP 000/curl-failure yields NOMATCH → retry → rollback
  → `exit 1`. No false-success path (verified by execution against a dead host).
- **nginx -t is fail-closed before reload** (lines 229-233) and on rollback
  (lines 192-195); both restore/refuse on failure.
- **SELF_TEST byte-restore proof runs and passes** (verified by execution).

The findings below are the defects that survived that scrutiny. The headline issue
(CR-01) is that SELF_TEST does not actually exercise the real `rollback()` — it
proves a stripped-down stub, so the script's central safety claim ("SELF_TEST
exercises rollback() in isolation") is materially overstated.

## Critical Issues

### CR-01: SELF_TEST exercises a stub `rollback()`, not the real one — the central safety proof is hollow

**File:** `scripts/cutover.sh:97-105` (stub) vs `scripts/cutover.sh:178-205` (real)
**Issue:**
The script header (line 24) and the SELF_TEST banner (line 65) claim SELF_TEST
"exercises rollback() in isolation." It does not. The SELF_TEST block defines its
**own local** `rollback()` (lines 97-105) that performs only `cp "${BAK_VHOST}"
"${VHOST_CONF}"`. The real `rollback()` used during a live flip (lines 178-205)
additionally runs `nginx -t` (fail-closed, lines 192-195) and `systemctl reload
nginx` (lines 198-201) and emits to stderr.

Consequences:

- SELF_TEST proves only that `cp` restores a file — it never tests the real
  rollback's nginx revalidation or reload branches, nor their fail-closed `exit 1`
  paths. The two functions can drift independently; a bug introduced into the real
  `rollback()` (e.g. wrong restore order, missing reload, a broken `nginx -t`
  guard) would pass SELF_TEST unchanged.
- The validator (`validate-staging.py:430-431`) only greps for the string
  `rollback` in the file, so it cannot detect this either.

This matters because rollback is the entire reversibility guarantee (CUT-02) for a
*production* traffic flip. A self-test that green-lights a rollback path it never
ran is worse than no self-test — it manufactures false confidence.

**Fix:** Make SELF_TEST drive the *real* `rollback()` with nginx commands stubbed
out via injectable indirection, rather than redefining the function. For example,
parameterize the nginx invocations:

```bash
# near the top
: "${NGINX_T_CMD:=nginx -t}"
: "${NGINX_RELOAD_CMD:=systemctl reload nginx}"
# in the single, real rollback():
if ! ${NGINX_T_CMD} 2>&1; then ... ; fi
if ! ${NGINX_RELOAD_CMD}; then ... ; fi
```

Then in SELF_TEST set `NGINX_T_CMD=true NGINX_RELOAD_CMD=true`, point
`VHOST_CONF`/`BAK_VHOST` at the temp files, and call the *defined* `rollback`
(do not redefine it). Now the self-test exercises the actual restore + the actual
nginx-t/reload control flow, including their failure branches if you stub `false`.

## Warnings

### WR-01: `sed` upstream switch is NOT anchored to the `# CUTOVER:` marker — it rewrites every matching `server …;` line

**File:** `scripts/cutover.sh:214`
**Issue:**
The comment (lines 208-211) and runbook (docs/cutover.md:4-9, 144) state the lever
is "the `server` line at the `# CUTOVER:` marker." The sed is a *global*,
unaddressed substitution: `sed -i "s|^\( *\)server [^;]*;|\1server ${NEW_UPSTREAM};|"`.
It happens to hit exactly one line in today's vhost only because that file contains
a single `server <addr>;` directive (verified). It is in no way tied to the
`# CUTOVER:` marker. If a second upstream/`server` directive is ever added (a second
backend, a health-check upstream, a commented example uncommented), this silently
rewrites **all** of them. The post-sed `grep -q` (line 217) would still pass.
The script also never asserts the marker exists or that exactly one line matched.

**Fix:** Scope the substitution to the marker and assert exactly one replacement.
Address the line *following* the `# CUTOVER:` marker:

```bash
# replace only the server line on the line after the # CUTOVER: marker
sed -i "/# CUTOVER:/{n; s|^\( *\)server [^;]*;|\1server ${NEW_UPSTREAM};|;}" "${VHOST_CONF}"
# then assert exactly one upstream server line now equals NEW_UPSTREAM
match_count=$(grep -cE "^[[:space:]]*server ${NEW_UPSTREAM};" "${VHOST_CONF}")
[[ "${match_count}" -eq 1 ]] || { echo "FATAL: expected 1 upstream rewrite, got ${match_count}" >&2; rollback; exit 1; }
```

### WR-02: `NEW_UPSTREAM` is interpolated unescaped into the sed *replacement* — `&` corrupts the config, `|` aborts mid-run

**File:** `scripts/cutover.sh:214`
**Issue:**
`${NEW_UPSTREAM}` is spliced raw into the sed replacement string. In a sed
replacement, `&` expands to the whole match and `\` is special; `|` is the chosen
delimiter. Verified by execution: `NEW_UPSTREAM='a&b:3000'` produces a mangled
`server a    server 10.43.94.103:3000;b:3000;` line, and `NEW_UPSTREAM='a|b'` makes
sed error out (`unknown option to 's'`) *after* the backup has been taken but
*before* any reload. For an operator-only tool with controlled IP:port input this
is unlikely, but a fat-fingered value can corrupt the live vhost; `nginx -t` would
then catch the `&` case and rollback, which is a noisy way to discover an avoidable
defect.

**Fix:** Escape the replacement, or avoid sed entirely (see WR-01 marker-anchored
approach). Minimal escape of `&`, `\`, and the delimiter:

```bash
esc_upstream=$(printf '%s' "${NEW_UPSTREAM}" | sed -e 's/[&\\|]/\\&/g')
sed -i "s|^\( *\)server [^;]*;|\1server ${esc_upstream};|" "${VHOST_CONF}"
```

### WR-03: post-switch verification uses `NEW_UPSTREAM` as a *grep regex* — `.` is a wildcard, so the check can false-pass

**File:** `scripts/cutover.sh:217`
**Issue:**
`grep -q "${NEW_UPSTREAM}" "${VHOST_CONF}"` treats the IP:port as a regex. The dots
in an IPv4 address are `any-char` wildcards. Verified: `grep -q "10.43.94.103:3000"`
matches `server 10X43X94X103:3000;`. So if the sed wrote a subtly wrong address, the
verification can still pass. This is the safety net for the switch having landed —
it should be exact.

**Fix:** Use a fixed-string, anchored check on the upstream line:

```bash
if ! grep -qF "server ${NEW_UPSTREAM};" "${VHOST_CONF}"; then
  echo "FATAL: sed did not write NEW_UPSTREAM to vhost — aborting" >&2
  exit 1
fi
```

### WR-04: Gate greps are unanchored substring matches — negated/qualified phrasings false-pass

**File:** `scripts/cutover.sh:128` and `scripts/cutover.sh:138`
**Issue:**
`grep -q "Status: verified"` and `grep -q "strict_failures: 0"` match the substring
anywhere on any line. A line like `Status: verified backup is STALE — do not use`
or `strict_failures: 0 (PLACEHOLDER, not yet run)` would satisfy the gate. These are
the two gates guarding a production traffic flip; they should be anchored and exact.
(The current docs happen to be well-formed, so this is latent, not currently
exploited.)

**Fix:** Anchor and constrain:

```bash
grep -qE '^[[:space:]]*Status:[[:space:]]+verified[[:space:]]*$' "${BACKUP_GATE_FILE}"
grep -qE '^[[:space:]]*strict_failures:[[:space:]]*0[[:space:]]*$' "${DIFF_GATE_FILE}"
```

### WR-05: Gate file paths are relative (`docs/…`) but the runbook tells the operator to run the script from the VPS without specifying CWD

**File:** `scripts/cutover.sh:51-52` and `docs/cutover.md:123-127`
**Issue:**
`BACKUP_GATE_FILE`/`DIFF_GATE_FILE` default to relative paths `docs/backup-gate.md`
and `docs/diff-readiness.md`. The runbook (line 126) instructs `NEW_UPSTREAM=... 
scripts/cutover.sh` "on the VPS" but never pins the working directory to the repo
root. If the operator runs the script from anywhere other than the repo root, both
`grep -q` calls fail on a missing file → the script `exit 1`s. That is fail-*safe*
(it blocks rather than flips), so it is not a security hole — but it is a real
operational footgun that will surface only at flip time and can be misread as a gate
failure. Worse, if a stray `docs/backup-gate.md` with a stale `Status: verified`
exists under the operator's CWD, the wrong file would gate the flip.

**Fix:** Resolve gate files relative to the script/repo, or require the runbook to
`cd` to the repo root. E.g. at the top of the script:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
: "${BACKUP_GATE_FILE:=${REPO_ROOT}/docs/backup-gate.md}"
: "${DIFF_GATE_FILE:=${REPO_ROOT}/docs/diff-readiness.md}"
```

## Info

### IN-01: `validate_cutover_artifacts()` only asserts marker *presence*, not behavior or determinism

**File:** `scripts/validate-staging.py:409-460`
**Issue:**
The validator greps the script/runbook text for literal substrings
(`set -euo pipefail`, `exit 64`, `Status: verified`, `strict_failures: 0`,
`rollback`, `nginx -t`, `curl`+`smoke`). It cannot detect any of the behavioral
defects above (CR-01 stub rollback, WR-01 unanchored sed, WR-04 substring gates) —
e.g. `"rollback" in content` is satisfied by the stub. The check is deterministic
and reads repo files (good — no live-doc dependency), but it validates *spelling*,
not *correctness*, so "ok: cutover artifacts" overstates what was verified.
**Fix:** Add a behavioral check that actually runs `SELF_TEST=1` against the repo
vhost fallback and asserts exit 0 + the byte-restore message — and once CR-01 is
fixed, that this exercised the real rollback path.

### IN-02: `cp -p` on backup but plain `cp` on restore loses mode/owner/timestamps on rollback

**File:** `scripts/cutover.sh:170` vs `scripts/cutover.sh:189`
**Issue:**
Backup uses `cp -p "${VHOST_CONF}" "${BAK_VHOST}"` (preserves perms/timestamps) but
`rollback()` restores with plain `cp "${BAK_VHOST}" "${VHOST_CONF}"`, so a rolled-back
vhost may end up with different mode/owner than the original. For a root-owned nginx
config this is usually fine, but it is an inconsistency in a reversibility path.
**Fix:** Use `cp -p "${BAK_VHOST}" "${VHOST_CONF}"` in `rollback()` for symmetry.

### IN-03: No temp-file cleanup trap in SELF_TEST on early `mktemp`/`cp` failure

**File:** `scripts/cutover.sh:67-121`
**Issue:**
SELF_TEST cleans up `${TMP_VHOST}` and `${TMP_VHOST}.cutover.bak` on the pass path
(line 118) and the diff-fail path (line 112), but if `set -e` aborts between
`mktemp` (line 67) and those points (e.g. the source `cp` at line 82 fails), the
temp files leak in `/tmp`. Minor hygiene only.
**Fix:** Add `trap 'rm -f "${TMP_VHOST}" "${TMP_VHOST}.cutover.bak"' EXIT` right
after the `mktemp`.

---

_Reviewed: 2026-06-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
