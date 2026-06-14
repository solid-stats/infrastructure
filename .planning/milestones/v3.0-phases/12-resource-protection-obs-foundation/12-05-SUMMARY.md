---
phase: 12-resource-protection-obs-foundation
plan: "05"
subsystem: kubernetes-cluster-live
status: complete
tags: [kubernetes, live-apply, qos, priorityclass, rbac, prep-01, prep-03, prep-04, prep-05]

dependency_graph:
  requires:
    - 12-01 (resource-preflight.sh + validate-phase-12.sh)
    - 12-02 (01-obs-rbac.yaml + 02-priority-classes.yaml bootstrap manifests)
    - 12-03 (patched workload manifests)
  provides:
    - Live staging cluster carries app-critical/obs-background PriorityClasses
    - monitoring + error-tracking namespaces with obs-ci-deployer least-privilege RBAC
    - postgres-0 + server-2 running at Guaranteed QoS + app-critical priority
  affects:
    - "live solid-stats-staging cluster (workload rollout)"
    - scripts/validate-phase-12.sh (bug fix)

tech_stack:
  added: []
  patterns:
    - operator-applied bootstrap manifests (excluded from CI deploy glob)
    - remote kubectl over SSH against the staging control-plane node

key_files:
  modified:
    - scripts/validate-phase-12.sh

decisions:
  - "Confirmed (not adjusted) the ASSUMED Guaranteed QoS values against live kubectl top: postgres usage ~225Mi vs 1Gi limit, server-2 ~70Mi vs 512Mi limit — both comfortably above live working set, so no manifest change. Noted tradeoff: postgres 1Gi ceiling is below its prior 2Gi limit; reversible if it OOMs under load."
  - "Node headroom finding: 4 CPU / 7.75Gi RAM, ~2.5Gi available with the app alone. The full obs stack (Phases 13-17) must run with tight limits; obs-background eviction protection is mandatory, not optional. Recorded for downstream phase sizing."
  - "Did not restart k3s for swap (see 12-04). Live application order: bootstrap (low-risk additive) → workloads (rolling restart) → validate, so a swap mishap could not block the core protection."

requirements: [PREP-01, PREP-03, PREP-04, PREP-05]
---

# Plan 12-05 — Live Application & Verification

## What was applied (live, operator-authorized over SSH)

1. **PREP-01 preflight** — ran `resource-preflight.sh` on the node; snapshot saved
   (`/tmp/phase12/resource-preflight-*.txt`). Node: 4 CPU / 7.75Gi; live use 60% CPU / 67% mem; ~2.5Gi available.
2. **QoS confirmation** — live `kubectl top` confirmed the ASSUMED values are well above working set; kept as-is.
3. **Bootstrap apply** — `02-priority-classes.yaml` + `01-obs-rbac.yaml`:
   PriorityClasses `app-critical`(1000000) / `obs-background`(100), namespaces `monitoring` + `error-tracking`,
   `obs-ci-deployer` SA + Role + RoleBinding in each.
4. **Workload apply** — the 6 patched manifests; rolling restart completed for server-2, postgres, rabbitmq, replay-parser-2.

## Live evidence

```
postgres-0          QoS=Guaranteed   priority=app-critical
server-2-...        QoS=Guaranteed   priority=app-critical
rabbitmq-0          QoS=Burstable    priority=app-critical
replay-parser-2-... QoS=Burstable    priority=app-critical
validate-phase-12.sh → "Phase 12 validation PASSED" (PREP-01/03/04/05 all ok,
  incl. positive RBAC: obs-ci-deployer CAN deploy in monitoring; negative RBAC:
  CANNOT get pods in solid-stats-staging)
```

## Bug fixed during validation (commit `3126f36`)

`validate-phase-12.sh` died under `set -e` because `kubectl auth can-i` signals its
answer via exit code (1 = "no"), tripping the command substitution before the negative
RBAC assert ran. Swallowed the exit code with `|| true` on both `auth can-i` captures;
re-ran → green.

## Cross-cutting note (F4)

Applying `50-replays-fetcher.yaml` from git reverted intentional live parity-run tuning
(image/flag/backoffLimit). Coordinated via `SolidGames/plans/product/PARITY-COORDINATION.md`;
baked the live-correct F4 state into the manifest (commit `03f557a`) so future applies are
a no-op. Did not re-apply the fetcher (live was already restored by parity-driver).

## Requirements

- **PREP-01** preflight snapshot recorded. ✓
- **PREP-03** PriorityClasses exist + all runtime pods carry app-critical. ✓
- **PREP-04** postgres + server-2 at Guaranteed QoS (confirmed on live pods). ✓
- **PREP-05** obs namespaces + obs-ci-deployer RBAC isolated from runtime ns. ✓
