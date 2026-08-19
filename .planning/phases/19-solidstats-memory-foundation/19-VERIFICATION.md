---
phase: 19-solidstats-memory-foundation
verified: 2026-08-19T20:22:45Z
status: gaps_found
score: 4/7 must-haves verified
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/5
  gaps_closed:
    - "A dedicated authenticated memory deployment workflow exists."
  gaps_remaining:
    - "OPS-04 monitoring is not operationally complete."
  regressions:
    - "The observer cannot reach MemPalace through default-deny ingress."
    - "The snapshot-freshness alert selects a nonexistent CronJob."
gaps:
  - truth: >-
      Prometheus actively scrapes a namespace-local observer for MCP and Qdrant
      signals under default-deny NetworkPolicies.
    status: failed
    reason: >-
      The observer has egress to MemPalace TCP 8765, but no NetworkPolicy allows
      observer ingress to the MemPalace pod. Default-deny blocks every MCP probe.
    artifacts:
      - path: "k8s/memory/30-network-policy.yaml"
        issue: "No ingress rule selects MemPalace and permits solidstats-memory-observer on TCP 8765."
      - path: "scripts/validate-memory-manifests.py"
        issue: "Checks observer egress but not reciprocal MemPalace ingress."
    missing:
      - "A least-privilege MemPalace ingress rule for the observer on TCP 8765 and a regression assertion."
  - truth: >-
      Snapshot freshness is alerted whenever the enabled backup fails to produce a
      recent Qdrant snapshot.
    status: failed
    reason: >-
      Prometheus selects cronjob=qdrant-snapshot, while the only CronJob is named
      solidstats-memory-backup. The alert condition has no matching CronJob series.
    artifacts:
      - path: "k8s/observability/values/prometheus-values.yaml"
        issue: "Uses qdrant-snapshot instead of solidstats-memory-backup."
      - path: "k8s/observability/10-prometheus.yaml"
        issue: "Committed rendered configuration repeats the wrong CronJob label."
      - path: "tests/test-memory-runtime-contract.py"
        issue: "Asserts the incorrect label instead of relating the rule to the backup manifest."
    missing:
      - "Correct backup CronJob selector in values/rendered config and a cross-manifest regression test."
behavior_unverified_items:
  - truth: >-
      Default-deny policies allow only the documented DNS, observer, Qdrant,
      host-nginx, and Prometheus paths under kube-router.
    test: >-
      Render measured CIDRs in an isolated cluster and exercise every permitted
      path plus representative denied traffic.
    expected: "Allowed paths work; non-allowed ingress and egress traffic is denied."
    why_human: >-
      Static sources cannot establish kube-router source-address rewriting or
      runtime enforcement.
human_verification:
  - test: >-
      Run a fresh Helm render from the pinned Prometheus chart and compare its
      generated configuration with committed 10-prometheus.yaml.
    expected: "Observer jobs, node-volume job, recording rules, and alert rules are preserved exactly."
    why_human: >-
      Source/rendered text parity is tested locally, but the pinned chart was not
      fetched or rendered during Phase 19 offline execution.
---

# Phase 19: SolidStats Memory Foundation Verification Report

**Phase Goal:** Add repository-local policy, validation, and plans for a dedicated
namespace/runtime/storage/network/backup/monitoring/CD boundary.
**Verified:** 2026-08-19T20:22:45Z
**Status:** gaps_found
**Re-verification:** Yes — after gap closure plan 19-03

## Goal Achievement

### Observable Truths

<!-- markdownlint-disable MD013 -->
| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Policy and offline bundle integrity are enforced. | ✓ VERIFIED | Policy validator and its 7 tests passed. ROADMAP and REQUIREMENTS now consistently assign MIG-03..07 to Phase 19 and MIG-01..02 to Phase 20. |
| 2 | A source-only isolated runtime/storage boundary rejects unmeasured values. | ✓ VERIFIED | `k8s/memory/` validates 26 resources with private Qdrant, separate PVCs, hardening, and strict placeholder rejection. |
| 3 | A dedicated workflow proves exact memory identity and namespace-only mutation. | ✓ VERIFIED | Uses `K8S_MEMORY_TOKEN`, exact `auth whoami`, negative `can-i` checks, server-side dry-run/apply, allowlisted manifests, and managed cleanup. |
| 4 | The managed SSH tunnel fails safely without signaling unrelated processes. | ✓ VERIFIED | 11 runtime-contract tests passed, including fake-SSH start/stop, stale PID, wrong-forward, and startup-failure cleanup. |
| 5 | Observer actively collects MCP and Qdrant signals under default deny. | ✗ FAILED | Observer egress allows MemPalace TCP 8765, but MemPalace has no matching observer ingress allow. |
| 6 | Rules alert on every OPS-04 signal, including enabled-backup freshness. | ✗ FAILED | Snapshot freshness selects nonexistent `qdrant-snapshot`, not `solidstats-memory-backup`. |
| 7 | kube-router enforces the declared default-deny paths. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Explicitly retained as operator UAT; no live-cluster claim was made. |
<!-- markdownlint-enable MD013 -->

**Score:** 4/7 truths verified (1 present, behavior-unverified)

### Required Artifacts

<!-- markdownlint-disable MD013 -->
| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `.github/workflows/deploy-memory.yml` | Authenticated namespace-only deploy | ✓ VERIFIED | Pre-mutation identity/RBAC gate, dry-run/apply, rollouts, and always cleanup are wired. |
| `scripts/ssh-tunnel-up.sh` | Managed SSH PID lifecycle | ✓ VERIFIED | Atomic 0600 pidfile and command/forward/user/host validation before TERM/KILL; actual helper is exercised by tests. |
| `k8s/memory/50-monitoring.yaml` | Executable observer | ⚠️ PARTIAL | Exporter fake-HTTP behavior is tested, but its MCP transport is blocked by missing reciprocal ingress. |
| `k8s/memory/30-network-policy.yaml` | Exact observer/Prometheus paths | ✗ FAILED | Prometheus-to-observer and observer-to-Qdrant are reciprocal; observer-to-MemPalace is not. |
| Prometheus values and rendered manifest | OPS-04 jobs, rules, and alerts | ✗ FAILED | Source/rendered configurations use the wrong snapshot CronJob selector. |
| `tests/test-memory-runtime-contract.py` | Regression coverage | ⚠️ PARTIAL | All 11 tests run, but neither NetPol reciprocity nor actual backup CronJob identity is asserted. |
<!-- markdownlint-enable MD013 -->

### Key Link Verification

<!-- markdownlint-disable MD013 -->
| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Workflow | memory CI identity | `K8S_MEMORY_TOKEN` → context → exact `auth whoami` | ✓ WIRED | Precedes every dry-run/apply and rejects foreign authority. |
| Workflow | rendered manifests | Shared allowlist excluding bootstrap and secrets | ✓ WIRED | Same list is dry-run then applied; rendered Secret is handled separately. |
| Workflow | SSH helper | One PID file and `if: always()` stop | ✓ WIRED | Runtime tests prove only validated SSH processes are signaled. |
| Prometheus | observer | TCP 9108 and reciprocal policies | ✓ WIRED | Both sides select their intended identities. |
| Observer | Qdrant | TCP 6333 and Qdrant ingress | ✓ WIRED | Egress and ingress selector agree. |
| Observer | MemPalace | TCP 8765 | ✗ NOT WIRED | Egress exists; MemPalace ingress does not permit the observer. |
| Snapshot alert | backup CronJob | `kube_cronjob_spec_suspend` | ✗ NOT WIRED | Rule selects `qdrant-snapshot`; manifest creates `solidstats-memory-backup`. |
| Prometheus values | committed render | repository rendered-config contract | ⚠️ PRESENT | Marker parity passes, but a fresh pinned-chart render was not run offline. |
<!-- markdownlint-enable MD013 -->

### Data-Flow Trace (Level 4)

<!-- markdownlint-disable MD013 -->
| Artifact | Data | Source | Status |
| --- | --- | --- | --- |
| Observer MCP metrics | readiness, duration, errors | MemPalace `/healthz` | ✗ DISCONNECTED by missing MemPalace ingress policy |
| Observer Qdrant metrics | readiness, collection health, snapshot timestamp | Qdrant HTTP API | ✓ FLOWING (source design) |
| Prometheus scrape | observer metrics | static observer Service target | ✓ FLOWING (source design) |
| PVC capacity | `kubelet_volume_stats_*` | authenticated Kubernetes API node proxy | ✓ FLOWING (source design) |
| Snapshot freshness | timestamp plus CronJob suspension | recording/alerting rules | ✗ DISCONNECTED by wrong CronJob label |
<!-- markdownlint-enable MD013 -->

### Behavioral Spot-Checks

<!-- markdownlint-disable MD013 -->
| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Migration policy | `timeout 10s python3 scripts/validate-solidstats-memory-policy.py` | PASS | ✓ PASS |
| Migration tests | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` | 7 passed | ✓ PASS |
| Deploy/observer/Prometheus contracts | `timeout 30s python3 tests/test-memory-runtime-contract.py` | 11 passed | ✓ PASS |
| Memory source manifests | memory validator with allowed placeholders | 26 resources | ✓ PASS |
| Observability source/render contract | `timeout 10s python3 scripts/validate-obs-manifests.py` | 22 files | ✓ PASS |
| Strict operator gates | strict memory and nginx validators | Both rejected placeholders | ✓ PASS (expected) |
| Runtime policy and Helm render | live cluster/fetched chart | outside offline scope | ? SKIP |
<!-- markdownlint-enable MD013 -->

### Requirements Coverage

<!-- markdownlint-disable MD013 -->
| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| ISO-01 | 19-01 | ⚠️ DEFERRED | Policy uses `solidstats_memory`; registration/legacy-alias removal is Phase 21 cutover work. |
| ISO-02 | 19-01..03 | ✓ SATISFIED (source boundary) | Dedicated namespace, separate runtime identities, and memory-only deploy identity exist. |
| ISO-03 | 19-02 | ⚠️ DEFERRED | Qdrant is private and nginx is fail-closed; public TLS is Phase 21. |
| ISO-04 | 19-02, 19-03 | ✗ BLOCKED | Observer-to-MCP is statically incomplete; kube-router UAT is also pending. |
| RUN-01 | 19-02 | ⚠️ GATED | HTTP command/probes exist; immutable MemPalace image remains intentionally unresolved. |
| RUN-02 | 19-02 | ✓ SATISFIED (source boundary) | Private single unprivileged StatefulSet has REST/gRPC, probes, RWO PVC, and Retain policy. |
| RUN-03 | 19-02, 19-03 | ✓ SATISFIED (source boundary) | Runtime/observer/backup identities are separate and hardened with explicit writable volumes. |
| RUN-04 | 19-02 | ✓ SATISFIED (source boundary) | MemPalace and Qdrant retain separate claims. |
| RUN-05 | 19-02 | ✓ SATISFIED | No ResourceQuota/LimitRange was added before required sizing evidence. |
| MIG-03..07 | 19-01 | ✓ SATISFIED (policy gate) | Policy/validator enforce rooms, archives, disabled features, deletion approval, and evidence/checksums. |
| OPS-01 | 19-02, 19-03 | ✓ SATISFIED (offline contract) | Exact namespaced identity is proved before mutation and foreign authority is rejected. |
| OPS-04 | 19-02, 19-03 | ✗ BLOCKED | MCP probe and snapshot-freshness alert wiring are broken. |
<!-- markdownlint-enable MD013 -->

### Anti-Patterns Found

<!-- markdownlint-disable MD013 -->
| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `k8s/memory/30-network-policy.yaml` | Egress-only observer-to-MemPalace policy | 🛑 Blocker | Default deny prevents MCP observation. |
| Prometheus values/render | CronJob label drift | 🛑 Blocker | Snapshot freshness alert resolves no enabled backup CronJob. |
| `MEMORY_OPERATOR_*` values | Strictly rejected operational inputs | ℹ️ Intended gate | Validated fail-closed; not a stub. |
| Fresh pinned-chart Helm render | Not run offline | ⚠️ Warning | Needs operator/CI confirmation before future chart regeneration. |
<!-- markdownlint-enable MD013 -->

### Human Verification Required

### 1. kube-router policy enforcement

**Test:** After fixing the reciprocal policy and rendering real values, exercise
all allowed and denied flows in an isolated cluster.

**Expected:** Only documented paths are reachable under default deny.

**Why human:** kube-router source-address and enforcement behavior cannot be
proven from source files.

### 2. Pinned-chart render parity

**Test:** Fetch the pinned chart in approved CI/operator context and run the
documented Helm render comparison.

**Expected:** Committed Prometheus configuration retains every memory job and rule.

**Why human:** Phase 19 did not fetch the chart during offline work.

### Gaps Summary

Plan 19-03 closed the nonfunctional deployment workflow: exact identity checks,
least-privilege preflight, and executable PID lifecycle tests are substantive.
OPS-04 remains blocked by two observable source defects: a missing reciprocal
observer-to-MemPalace ingress policy and a nonexistent CronJob selector in the
snapshot-freshness alert. Neither is an intentional placeholder or a live-only
uncertainty.

## Next Action

Run `$gsd-plan-phase 19 --gaps` to add the observer-to-MemPalace ingress rule,
correct the CronJob selector, and add cross-manifest regression coverage. Then
re-run the offline suite. Retain kube-router UAT and pinned-chart render parity
as operator verification items.

---

_Verified: 2026-08-19T20:22:45Z_
_Verifier: the agent (gsd-verifier)_
