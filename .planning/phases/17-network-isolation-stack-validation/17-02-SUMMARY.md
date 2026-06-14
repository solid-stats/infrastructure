---
phase: 17-network-isolation-stack-validation
plan: "02"
subsystem: validation
tags: [bash, validation, observability, orchestrator, VAL-01]
dependency_graph:
  requires:
    - scripts/validate-phase-13.sh
    - scripts/validate-phase-15.sh
    - scripts/validate-phase-16.sh
    - scripts/test-glitchtip-ingest.sh
  provides:
    - scripts/validate-stack.sh
  affects:
    - 17-03 (consumes validate-stack.sh for pre/post-policy passes)
tech_stack:
  added: []
  patterns:
    - "Thin orchestrator shell script: compose sub-scripts, no logic duplication"
    - "set -euo pipefail + sub-script non-zero exit = fail-loud-on-first-failure"
    - "kubectl cluster-info preflight for fail-closed cluster-unreachable guard"
key_files:
  created:
    - scripts/validate-stack.sh
  modified: []
decisions:
  - "Pass --quick to all three sub-scripts; pass --public only to validate-phase-16.sh (the only sub-script that accepts it)"
  - "K8S_NAMESPACE_MONITORING / K8S_NAMESPACE_ERROR overrides so both monitoring sub-scripts share one env var and phase-16 uses a separate one"
  - "Secret env (GRAFANA_ADMIN_PASSWORD, GLITCHTIP_DSN, SUPERUSER_TOKEN) intentionally never echoed in orchestrator; sub-scripts own that contract"
  - "GLITCHTIP_DSN absent => note+skip (not failure) matching validate-phase-16.sh existing contract"
  - "Full green pass (all assertions against live cluster) deferred to 17-03"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-14"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
status: complete
---

# Phase 17 Plan 02: validate-stack.sh VAL-01 Orchestrator Summary

**One-liner:** Thin bash orchestrator composing validate-phase-13/15/16.sh into a single re-runnable full-stack validation command with --quick and --public flag propagation and fail-closed cluster preflight.

## What Was Built

`scripts/validate-stack.sh` (134 lines, executable) — the VAL-01 orchestrator.

### Behavior

1. **Preflight:** `kubectl cluster-info --request-timeout=5s`. Exits 1 with FATAL message if cluster unreachable; does NOT proceed to sub-scripts. Designed to work correctly with the WireGuard tunnel up (passes) or down (fails closed).

2. **Section banners:** Prints a `====` banner before each phase invocation and a final `FULL STACK VALIDATION PASSED` banner (only reached if all three passed, since `set -euo pipefail` aborts on any sub-script non-zero exit).

3. **Flag propagation:**
   - `--quick` → passed as `--quick` to all three sub-scripts (skips Grafana port-forward and forced GlitchTip ingest)
   - `--public` → passed only to `validate-phase-16.sh` (only sub-script that accepts it)
   - Unknown flags → `exit 1` with `FATAL: unknown flag: <arg>`

4. **Namespace wiring:**
   - Phase 13 and 15: `K8S_NAMESPACE=${K8S_NAMESPACE_MONITORING:-monitoring}`
   - Phase 16: `K8S_NAMESPACE=${K8S_NAMESPACE_ERROR:-error-tracking}`

5. **Secret discipline:** `GRAFANA_ADMIN_PASSWORD`, `GLITCHTIP_DSN`, `SUPERUSER_TOKEN` are never echoed; they flow through the environment to the sub-scripts which own the no-echo contract.

### Intended usage pattern (17-03)

- **Pre-policy baseline:** `bash scripts/validate-stack.sh --quick` — confirms Prometheus targets UP and pods Running before NetworkPolicies are applied. Fast; no port-forward; no DSN required.
- **Post-policy gate:** `GRAFANA_ADMIN_PASSWORD=... GLITCHTIP_DSN=... bash scripts/validate-stack.sh` — full run through the NetworkPolicy layer. Exercises Grafana port-forward (allowed port), Loki LogQL via Prometheus exec, and GlitchTip forced-error ingest.

## Verification Results

### Task 1 — Syntax and composition
```
bash -n scripts/validate-stack.sh  → ok
grep validate-phase-13.sh          → found
grep validate-phase-15.sh          → found
grep validate-phase-16.sh          → found
grep 'set -euo pipefail'           → found
test -x scripts/validate-stack.sh  → ok
```

### Task 2 — Guard paths (dry-run, no live cluster required for unknwon-flag path)

```
bash scripts/validate-stack.sh --bogus → exit 1, FATAL: unknown flag: --bogus
```

Cluster-unreachable guard verified with a stubbed kubectl that always exits 1:
```
PATH=/tmp/kubectl-fake:$PATH bash scripts/validate-stack.sh --quick → exit 1 (FATAL: cluster unreachable)
```
Note: the staging cluster WAS reachable on the authoring machine (live WireGuard tunnel), so the raw `--quick` run proceeded into phase-13 assertions and passed. This is correct behavior — the orchestrator should pass when the cluster is up. The fail-closed guard is proven by the stub test above.

## Deviations from Plan

None. Plan executed exactly as written.

The RESEARCH §VAL-01 Script Design skeleton was used as the structural reference; minor additions:
- Separate `common_flags` and `phase16_flags` variables to handle --public being phase-16-only cleanly
- `${common_flags:+...}` / conditional string building so no empty-string args are passed to sub-scripts when no flags are set

## Known Stubs

None. The orchestrator is a pure composition with no stub data or hardcoded placeholders.

## Threat Flags

None. `validate-stack.sh` is a read-only validation script. It does not open new network endpoints, write to the cluster, or introduce new secret handling surface. T-17-05 (false-green) and T-17-06 (secret leakage) mitigations are in place as designed.

## Full Green Pass Deferred

The full green run (all three sub-scripts passing against the live cluster) is performed in plan **17-03**, which runs `validate-stack.sh --quick` before NetworkPolicies and `validate-stack.sh` (full) after applying them. This plan proves only the orchestration scaffold is sound.

## Self-Check

```
[ -f scripts/validate-stack.sh ] → FOUND
[ -x scripts/validate-stack.sh ] → FOUND
git log --oneline | head -1      → 182d50d feat(17-02): add validate-stack.sh VAL-01 full-stack validation orchestrator
```

## Self-Check: PASSED
