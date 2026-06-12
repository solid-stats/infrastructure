---
phase: 8
slug: automated-restore-drill
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-13
---

# Phase 8 — Validation Strategy

> Per-phase validation contract. This is an infrastructure phase (bash + k8s manifests +
> an operator-run restore drill) — there is no unit-test framework. Validation = offline
> structural checks (CI-runnable) + an on-demand live drill that produces PASS/FAIL evidence.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | none — Python stdlib offline validator + `bash -n` + the drill Job itself |
| **Config file** | `scripts/validate-staging.py` (extended with a DRILL-04 depth-1 guard) |
| **Quick run command** | `python3 scripts/validate-staging.py && bash -n scripts/restore-drill.sh` |
| **Full suite command** | `python3 scripts/validate-staging.py` + operator: `scripts/restore-drill.sh` (live drill on cluster) |
| **Estimated runtime** | offline ~2s; live drill ~1–3 min |

---

## Sampling Rate

- **After every task commit:** `python3 scripts/validate-staging.py` (manifest shape, workload safety, DRILL-04 depth-1 guard) + `bash -n` on any changed shell script.
- **After the phase:** operator runs `scripts/restore-drill.sh` against the live cluster — the drill Job restores the latest S3 backup into scratch postgres and emits a PASS/FAIL evidence line.
- **Before `/gsd-verify-work`:** offline validator exit 0 AND one successful live drill run captured as evidence.

---

## Per-Task Verification Map

| Task | Requirement | Secure Behavior | Verify | Status |
|------|-------------|-----------------|--------|--------|
| restore-drill Job manifest | DRILL-01 | scratch postgres on emptyDir; never connects to live `postgres` Service/PVC; guarded DB name `solid_stats_drill` | `validate-staging.py` workload-safety + manifest grep asserts no live-Service host; live drill restores cleanly | ⬜ pending |
| sanity assertions | DRILL-02 | row-count / table-existence checks; non-zero exit on failure, not masked by teardown | live drill: forced bad assertion → Job fails loudly | ⬜ pending |
| teardown + evidence | DRILL-03 | `restartPolicy: Never` + `ttlSecondsAfterFinished`; structured PASS/FAIL log line | live drill log shows evidence line; Job self-cleans | ⬜ pending |
| out-of-CD-path placement | DRILL-04 | drill manifest under `k8s/staging/restore-drill/` (NOT matched by `find -maxdepth 1`) | `validate-staging.py` DRILL-04 guard asserts no drill yaml at `k8s/staging/*.yaml` depth-1 | ⬜ pending |

---

## Wave 0 Requirements

- Existing infrastructure covers validation: `scripts/validate-staging.py` is extended in-phase with the DRILL-04 depth-1 guard; no test framework install needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Latest S3 backup restores into scratch postgres with passing sanity checks | DRILL-01, DRILL-02 | Requires live cluster + S3 creds (k8s Secrets) | Operator: `scripts/restore-drill.sh`; confirm Job PASS, scratch DB row counts > 0, live `postgres-data` untouched |
| Drill self-cleans and never schedules under CD | DRILL-03, DRILL-04 | Requires live cluster + CD dry-run | Confirm Job gone after `ttlSecondsAfterFinished`; `kubectl get cronjob,job` shows no drill scheduled by CD |

---

## Validation Sign-Off

- [ ] All tasks have an offline check or a documented live-drill verification
- [ ] DRILL-04 depth-1 guard added to `validate-staging.py`
- [ ] One successful live drill run captured as evidence before verify-work
- [x] `nyquist_compliant: true` (infra-appropriate validation contract)

**Approval:** pending
