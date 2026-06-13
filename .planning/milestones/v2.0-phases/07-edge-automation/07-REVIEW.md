---
phase: 07-edge-automation
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - scripts/validate-edge.py
  - scripts/validate-staging.py
  - scripts/bootstrap-edge.sh
  - scripts/teardown-edge.sh
  - config/nginx/sites-available/stats-staging-solid-stats.conf
  - config/systemd/certbot-deploy-hook.sh
  - config/systemd/certbot-renew-failure.service
  - config/systemd/certbot.service.d/onfailure.conf
  - docs/edge-bootstrap.md
findings:
  critical: 2
  warning: 7
  info: 4
  total: 13
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the Phase 7 edge-automation artifacts: the offline structural validator, the
operator-run bootstrap/teardown scripts, the nginx vhost, the certbot deploy hook + systemd
failure-surfacing units, and the operator runbook. The artifacts are generally careful —
`set -euo pipefail` everywhere, fail-closed `nginx -t` gates, backup-before-overwrite, and a
genuinely good wg0 pre-check that refuses to expose the k3s API publicly.

Two issues rise to BLOCKER: (1) the bootstrap nginx restore-on-failure path leaves nginx serving
a stale in-memory config and never reloads the restored backup, and (2) `reload nginx || start
nginx` masks reload failures by falling back to a no-op `start`. Both undermine the fail-closed
guarantee the script advertises. Seven warnings concern over-broad recursive chmod, fragile
hand-rolled YAML parsing in the staging validator, a teardown branch that can delete an
un-backed-up live vhost, and several error-masking `2>/dev/null` / `|| true` patterns that hide
real failures from the operator.

## Critical Issues

### CR-01: nginx restore-on-failure path never reloads the restored config

**File:** `scripts/bootstrap-edge.sh:71-83`
**Issue:** When the repo vhost fails `nginx -t`, the script restores `$BAK_VHOST`, re-runs
`nginx -t` to confirm the restored file is valid — then `exit 1` **without reloading nginx**.
The bad repo vhost is on disk-then-restored, but the live nginx process keeps running its
previous good in-memory config, so this specific case is benign. However, the inverse is the
real defect: the success path at line 83 (`systemctl reload nginx || systemctl start nginx`)
only runs when `nginx -t` passes. If `nginx -t` passes but `reload` then fails, the `|| start`
fallback (see CR-02) hides it. Additionally, when there is **no** backup (`! -f "$BAK_VHOST"`),
the failure branch skips the restore entirely (the `if [[ -f "$BAK_VHOST" ]]` guard at line 73
is false) and `exit 1` leaves the broken repo vhost installed and symlinked into
`sites-enabled` — a subsequent manual `systemctl reload nginx` or host reboot will then load the
invalid config and break the edge. The "fail-closed / reversible" guarantee does not hold on a
host that had no prior vhost.
**Fix:** On the no-backup failure branch, remove the just-installed broken vhost and its symlink
before exiting:
```bash
if ! nginx -t 2>&1; then
  echo "FATAL: nginx config invalid after vhost install" >&2
  if [[ -f "$BAK_VHOST" ]]; then
    cp "$BAK_VHOST" "$VHOST_CONF"
  else
    # No prior config to restore — remove the broken artifact so it can't be loaded later
    rm -f "$VHOST_CONF" "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf"
  fi
  if ! nginx -t 2>&1; then
    echo "FATAL: config still invalid — refusing reload" >&2
    exit 1
  fi
  exit 1
fi
```

### CR-02: `reload nginx || start nginx` masks reload failures

**File:** `scripts/bootstrap-edge.sh:83`
**Issue:** `systemctl reload nginx || systemctl start nginx`. If nginx is already running and
`reload` fails (e.g. the master process rejects the new config despite `nginx -t` passing, or a
transient systemd error), the fallback `systemctl start nginx` is a **no-op that returns 0** for
an already-running unit. The script then prints "nginx vhost installed and reloaded" and exits
successfully even though the reload never took effect — the operator believes the new vhost is
live when it is not. This defeats the fail-closed intent on the one operation that actually
applies the config. The `|| start` idiom only makes sense if nginx might be stopped, but in the
adopt-not-rebuild scenario nginx is always already serving.
**Fix:** Fail loudly on reload failure instead of masking it:
```bash
if ! systemctl reload nginx; then
  echo "FATAL: nginx reload failed despite passing nginx -t — investigate manually" >&2
  systemctl status nginx --no-pager >&2 || true
  exit 1
fi
```
If a cold-start case is genuinely needed, gate it explicitly on `systemctl is-active --quiet
nginx` rather than blindly OR-ing into `start`.

## Warnings

### WR-01: `chmod -R 755` recurses over the entire webroot

**File:** `scripts/bootstrap-edge.sh:43`
**Issue:** `chmod -R 755 "$WEBROOT_PATH"` recursively rewrites permissions on **everything**
under `/var/www/html`, not just the ACME challenge dir the script created. On a shared host
`/var/www/html` may contain other site content; this silently widens (or narrows) perms on
unrelated files and makes the bootstrap non-idempotent in spirit (it mutates pre-existing state
it did not create). Only the challenge directory needs to be world-readable for the webroot
ACME flow.
**Fix:** Scope the chmod to the directory the script owns:
```bash
mkdir -p "$WEBROOT_PATH/.well-known/acme-challenge"
chmod 755 "$WEBROOT_PATH" "$WEBROOT_PATH/.well-known" "$WEBROOT_PATH/.well-known/acme-challenge"
```

### WR-02: teardown can delete an un-backed-up live vhost

**File:** `scripts/teardown-edge.sh:45-49`
**Issue:** Bootstrap only creates `$BAK_VHOST` when a live vhost existed **and** no `.bak`
already existed (`bootstrap-edge.sh:54`). If the operator runs teardown on a host where the
backup is missing (e.g. bootstrap was interrupted before backup, the `.bak` was manually
deleted, or a vhost was placed by hand after bootstrap), teardown takes the `else` branch and
`rm -f "$VHOST_CONF"` — **deleting a live, possibly hand-authored vhost with no backup to
restore.** This is irreversible data loss of host config, contradicting the phase's
reversibility goal.
**Fix:** Only remove the vhost if it is byte-identical to the repo copy this teardown is
responsible for; otherwise leave it and warn:
```bash
else
  if cmp -s "$REPO_ROOT/config/nginx/sites-available/stats-staging-solid-stats.conf" "$VHOST_CONF"; then
    rm -f "$NGINX_SITES_ENABLED/stats-staging-solid-stats.conf" "$VHOST_CONF"
  else
    echo "warn: no .bak and live vhost differs from repo copy — leaving it in place (manual review)" >&2
  fi
fi
```
(Note: teardown does not define `$REPO_ROOT`; it would need the same `REPO_ROOT` derivation
bootstrap uses.)

### WR-03: teardown ufw deletes swallow real errors and emit misleading messages

**File:** `scripts/teardown-edge.sh:68-70`
**Issue:** `ufw delete ... 2>/dev/null || echo "...not found — skipping"`. The `2>/dev/null`
discards ufw's stderr, so *any* failure (permission denied, ufw not installed, malformed rule,
ufw inactive) is reported to the operator as the benign "rule not found — skipping". An
operator running teardown to prove reversibility could be told the 6443/wg0 rule was cleanly
absent when in fact the delete failed and the k3s-API rule is **still active**. The interface-
qualified delete on line 70 must also match the exact rule string ufw stored at add time; if
ufw normalized it differently, the delete silently no-ops here.
**Fix:** Distinguish "rule absent" from "delete failed" — check existence first or inspect the
exit/output rather than blanket-suppressing stderr:
```bash
delete_rule() {
  if ufw status | grep -qF "$1"; then
    ufw delete allow "$2" || { echo "FATAL: failed to delete ufw rule: $1" >&2; exit 1; }
  else
    echo "ufw rule '$1' not present — skipping"
  fi
}
```
At minimum, drop `2>/dev/null` so genuine errors surface.

### WR-04: hand-rolled YAML parsing in validate-staging.py is fragile and can pass invalid manifests

**File:** `scripts/validate-staging.py:108-146`
**Issue:** `top_value`, `metadata_name`, and `string_data` parse YAML by string-prefix matching
on raw lines. This breaks on legitimate-but-unanticipated YAML: a `metadata:` block that uses
flow style, `name:` indented other than exactly two spaces, quoted/multi-line scalars, list-form
documents, or keys that appear as substrings. `metadata_name` returns `None` the moment any
top-level (non-indented) line follows `metadata:`, so reordering keys changes results. Because
the validator's `require()` calls trust these parsers, a structurally-broken manifest can pass
(false negative) or a valid one can fail (false positive). The script already shells out to
`kubectl` when available — but that path is skipped when the cluster is unreachable, which is
the normal CI case, leaving the brittle parser as the sole gate.
**Fix:** Use a real parser. `yaml.safe_load_all` (PyYAML) over each document gives correct,
schema-faithful access to `apiVersion`/`kind`/`metadata.name`/`stringData`. The project says
"standard library only" for scripts; if a dependency is disallowed, at minimum constrain these
helpers and document that they assume canonical 2-space block style emitted by the renderer.

### WR-05: validate-edge.py http2 regex can match the wrong listen line

**File:** `scripts/validate-edge.py:83`
**Issue:** `re.search(r"listen.*443.*http2", content)` runs without `re.DOTALL` but `.` still
spans within a line; more importantly it only requires the substrings `443` and `http2` to
co-occur after `listen` *somewhere on a single line*. It would accept `listen 443;` on one line
and is satisfied by the IPv6 `listen [::]:443 ssl http2;` even if the IPv4 `listen 443 ssl;`
lost its `http2`. The check claims to enforce "must mirror live vhost exactly" but does not
verify both listen lines. A drift on one of the two 443 listeners passes silently.
**Fix:** Match per-listen-line and require http2 on every 443 listener:
```python
listen_443 = [l for l in content.splitlines() if re.search(r"^\s*listen\b.*\b443\b", l)]
require(listen_443, "vhost has no 443 listen directive")
require(all("http2" in l for l in listen_443),
        "every 443 listen must include http2 to mirror live vhost")
```

### WR-06: certbot-renew-failure.service lacks the install/enable step it implies

**File:** `config/systemd/certbot-renew-failure.service:14-15` and `scripts/bootstrap-edge.sh:115-124`
**Issue:** The unit declares `[Install] WantedBy=multi-user.target`, but bootstrap only `cp`s the
unit and runs `daemon-reload` — it never runs `systemctl enable certbot-renew-failure.service`.
For an `OnFailure=`-triggered oneshot the enable is not strictly required (systemd starts it on
demand), so the `[Install]` section is misleading dead configuration: it suggests the operator
should enable it, yet nothing does, and teardown's `systemctl stop` (line 23) implies it might be
running. This inconsistency invites an operator to "fix" it by enabling, which would attempt to
start a `Type=oneshot` logger at boot for no reason.
**Fix:** Either remove the `[Install]` section (the unit is purely OnFailure-activated), or have
bootstrap explicitly `systemctl enable` it and teardown `systemctl disable` it. Removing
`[Install]` is the cleaner match to the actual activation model.

### WR-07: deploy hook reload failure is unhandled under set -e

**File:** `config/systemd/certbot-deploy-hook.sh:25`
**Issue:** `systemctl reload nginx` runs bare. Under `set -euo pipefail` a non-zero exit aborts
the script before the "Success" log on line 29, so certbot sees the hook fail — acceptable. But
the operator-facing remediation message ("Fix nginx config and run: systemctl reload nginx",
lines 17-19) is only printed on the `nginx -t` failure path, not on a reload failure. A reload
that fails *after* a passing `nginx -t` produces no actionable log line and no explicit non-zero
diagnostic — the hook just dies silently mid-way. Given a renewed cert was already written, the
operator needs to know the reload (not the validation) failed.
**Fix:** Wrap the reload with an explicit diagnostic:
```bash
if ! systemctl reload nginx; then
  echo "[$TIMESTAMP] [certbot-deploy-hook] FATAL: nginx reload failed AFTER passing nginx -t" >&2
  echo "[$TIMESTAMP] [certbot-deploy-hook] Renewed cert is installed; reload manually" >&2
  exit 1
fi
```

## Info

### IN-01: certbot certonly will fail under set -e on transient ACME errors with no cleanup

**File:** `scripts/bootstrap-edge.sh:95-102`
**Issue:** The `certbot certonly` invocation is unguarded; under `set -e` any ACME failure (rate
limit, DNS, port 80 unreachable) aborts the whole bootstrap *after* nginx was already reloaded
and *before* the deploy hook / ufw rules are installed, leaving a partially-bootstrapped host.
The docs say issuance is skipped by default (lineage exists), so this is low-probability, but a
re-run would resume cleanly only because earlier steps are idempotent. Consider a clearer error
message on certbot failure pointing at docs/edge-bootstrap.md troubleshooting.

### IN-02: `apt-get install` not pinned and runs on every invocation

**File:** `scripts/bootstrap-edge.sh:31-32`
**Issue:** `apt-get update -qq && apt-get install -y ...` runs unconditionally on every re-run.
It is idempotent (already-installed packages are no-ops) but performs network I/O and can pull
newer package versions on a re-run, subtly changing the edge between runs. Minor for staging;
worth a guard (`dpkg -s ... || apt-get install`) if reproducibility across re-runs matters.

### IN-03: hardcoded ClusterIP is a single point of drift, not a secret

**File:** `config/nginx/sites-available/stats-staging-solid-stats.conf:11`
**Issue:** `server 10.43.94.103:3000;` hardcodes the server-2 ClusterIP. This is intentional
(verbatim live mirror, marked as the Phase 11 CUTOVER lever) and is not a secret, so it is not a
security finding. Flagging only because a ClusterIP can change if the Service is recreated; the
`# CUTOVER` comment documents the lever but nothing detects drift between this value and the live
Service's actual ClusterIP. A validate-edge check that compares against the Service manifest
would catch silent breakage.

### IN-04: teardown daemon-reload is unguarded but non-fatal context

**File:** `scripts/teardown-edge.sh:28`
**Issue:** `systemctl daemon-reload` runs bare under `set -e`; a failure here would abort
teardown before the vhost-restore and ufw-cleanup sections, leaving a half-reverted host.
Bootstrap guards the same call with an explicit FATAL message (`bootstrap-edge.sh:122`);
teardown should be symmetric so a daemon-reload failure does not silently strand the operator
mid-teardown.

---

_Reviewed: 2026-06-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
