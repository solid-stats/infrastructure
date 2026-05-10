---
phase: 02
slug: backup-gate
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-10
---

# Phase 02 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | Shell and live Kubernetes Job evidence |
| Quick run command | `python3 scripts/validate-staging.py && bash -n scripts/backup-postgres-now.sh` |
| Full suite command | manual backup Job plus log/gate evidence |

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Backup Job writes to S3 | BKP-01, BKP-02, BKP-03, BKP-04 | Requires live cluster and S3 secrets | Run `scripts/backup-postgres-now.sh` or equivalent remote `kubectl` Job, then record `backup_id`, `dump_object`, and `dump_size_bytes`. |

## Validation Sign-Off

- [x] Automated syntax/static checks defined.
- [x] Live backup evidence required before Phase 2 is marked passed.
