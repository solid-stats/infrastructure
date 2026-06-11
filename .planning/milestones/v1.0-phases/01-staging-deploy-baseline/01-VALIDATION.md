---
phase: 01
slug: staging-deploy-baseline
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-10
---

# Phase 01 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Standard-library Python plus shell syntax checks |
| **Config file** | None |
| **Quick run command** | `python3 scripts/validate-staging.py` |
| **Full suite command** | `python3 scripts/validate-staging.py` |
| **Estimated runtime** | ~5 seconds |

## Sampling Rate

- **After every task commit:** Run `python3 scripts/validate-staging.py`.
- **After every plan wave:** Run `python3 scripts/validate-staging.py`.
- **Before `$gsd-verify-work`:** Full suite must be green, plus live deploy
  evidence must be captured when staging credentials are available.
- **Max feedback latency:** 10 seconds for local validation.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | VAL-01, VAL-03, RUN-04 | T-01-01 | Secret rendering checks use dummy values and do not log real secrets | static/integration | `python3 scripts/validate-staging.py` | Missing before Wave 1 | pending |
| 01-02-01 | 02 | 1 | K8S-01, K8S-02, K8S-03 | T-01-02 | Workloads avoid default ServiceAccount and document NetworkPolicy/CNI state | static | `python3 scripts/validate-staging.py` | Missing before Wave 1 | pending |
| 01-03-01 | 03 | 2 | OWN-01, OWN-02, RUN-01, RUN-02, VAL-02 | T-01-03 | Deploy script verifies rollout state without printing secret manifests | smoke/live when available | `python3 scripts/validate-staging.py` | Existing deploy script | pending |
| 01-04-01 | 04 | 2 | VAL-04 | T-01-04 | Docs disclose scope, overlap, and exceptions before operator deploy | static/docs | `python3 scripts/validate-staging.py` | Existing docs | pending |

## Wave 0 Requirements

- [ ] `scripts/validate-staging.py` - standard-library validator for manifests,
  scripts, rendered Secret structure, and safety rules.
- [ ] `.github/workflows/deploy-staging.yml` - validate job runs
  `python3 scripts/validate-staging.py`.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live staging deploy and rollout status | OWN-02, RUN-01, RUN-02, VAL-02 | Requires SSH access and staging GitHub environment secrets | Run the deploy workflow or `scripts/deploy-staging.sh`; capture rollout status for PostgreSQL, RabbitMQ, `server-2`, and `replay-parser-2`, then list `replays-fetcher` and `postgres-backup` CronJobs. |
| NetworkPolicy enforcement in current k3s CNI | K8S-03 | CNI behavior is cluster-specific | If NetworkPolicy is enabled, validate expected traffic. If unavailable or unknown, confirm docs contain the explicit exception and follow-up path. |

## Validation Sign-Off

- [x] All tasks have automated validation or explicit manual-only verification.
- [x] Sampling continuity: no 3 consecutive tasks without automated verification.
- [x] Wave 0 covers all missing validation infrastructure.
- [x] No watch-mode flags.
- [x] Feedback latency target is under 10 seconds for local checks.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-05-10
