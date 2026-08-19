---
phase: 19-solidstats-memory-foundation
verified: 2026-08-19T20:44:55Z
status: human_needed
score: 6/7 must-haves verified
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/7
  gaps_closed:
    - "Observer-to-MemPalace traffic is reciprocal under default deny."
    - "Snapshot freshness selects the manifest-owned backup CronJob."
  gaps_remaining: []
  regressions: []
behavior_unverified_items:
  - truth: >-
      Default-deny policies allow only the documented DNS, observer, Qdrant,
      host-nginx, and Prometheus paths under kube-router.
    test: >-
      Render measured values in an isolated cluster and exercise all permitted
      paths plus representative denied traffic.
    expected: "Allowed paths work; non-allowed ingress and egress traffic is denied."
    why_human: >-
      Static sources cannot establish kube-router source-address rewriting or
      runtime enforcement.
human_verification:
  - test: >-
      Render the pinned Prometheus Helm chart in the approved CI/operator
      environment and compare it with committed 10-prometheus.yaml.
    expected: >-
      The generated configuration retains the observer jobs, node-volume job,
      recording rules, and alert rules.
    why_human: >-
      Phase 19 did not fetch or render the pinned chart during offline work.
  - test: >-
      Apply the rendered manifests to an isolated cluster and test observer MCP,
      Qdrant, Prometheus, and denied paths under kube-router.
    expected: >-
      Observer reaches MemPalace and Qdrant, Prometheus reaches only observer TCP
      9108, and non-allowed flows are denied.
    why_human: >-
      NetworkPolicy source structure is proven offline; live CNI enforcement is
      not observable from this repository.
---

# Phase 19: SolidStats Memory Foundation Verification Report

**Phase Goal:** Add repository-local policy, validation, and plans for a dedicated
namespace/runtime/storage/network/backup/monitoring/CD boundary.
**Verified:** 2026-08-19T20:44:55Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure plan 19-04

## Goal Achievement

### Observable Truths

<!-- markdownlint-disable MD013 -->
| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The repository enforces accepted migration policy and offline bundle integrity. | ✓ VERIFIED | Policy validator and seven tests passed. ROADMAP/REQUIREMENTS consistently map MIG-03..07 to Phase 19 and MIG-01..02 to Phase 20. |
| 2 | A source-only isolated namespace/runtime/storage boundary rejects unmeasured values. | ✓ VERIFIED | Memory validator accepted 27 resources only with explicit placeholder allowance; strict mode rejected all 8 unresolved operator inputs. |
| 3 | A dedicated deploy workflow proves exact memory identity and limits mutation to `solidstats-memory`. | ✓ VERIFIED | Exact `auth whoami`, negative `can-i` boundary checks, allowlisted dry-run/apply, rollout checks, and managed cleanup are all wired. |
| 4 | Managed SSH lifecycle cannot signal unrelated processes. | ✓ VERIFIED | Runtime contracts execute fake-SSH start/stop, stale PID, wrong-forward, and startup-failure cleanup against the real helper. |
| 5 | The observer-to-MemPalace path is exact and reciprocal under default deny. | ✓ VERIFIED | New ingress policy admits only `solidstats-memory-observer` to MemPalace TCP 8765; validator and parsed-YAML tests reject broadened/drifted shapes. |
| 6 | OPS-04 source configuration covers observer, Qdrant, snapshot, and PVC signals. | ✓ VERIFIED | Values/rendered Prometheus configurations use the sole `solidstats-memory-backup` CronJob; validator and tests reject missing, duplicate, or divergent names. |
| 7 | kube-router enforces the declared paths at runtime. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Correctly preserved as operator UAT; no live-cluster result was inferred from static files. |
<!-- markdownlint-enable MD013 -->

**Score:** 6/7 truths verified (1 present, behavior-unverified)

### Required Artifacts

<!-- markdownlint-disable MD013 -->
| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `config/solidstats-memory/migration-policy.json` and validator | Policy and fail-closed bundle gate | ✓ VERIFIED | Committed values and all negative bundle tests pass. |
| `k8s/memory/` | Isolated runtime, storage, backup, and NetworkPolicy boundary | ✓ VERIFIED (source) | Separate PVCs/identities, private Qdrant, hardened workloads, default deny, and exact observer path pass validation. |
| `.github/workflows/deploy-memory.yml` | Authenticated namespace-scoped deploy path | ✓ VERIFIED (offline contract) | Exact identity and authorization proof occur before every mutation; bootstrap manifests are excluded. |
| `scripts/ssh-tunnel-up.sh` | Managed SSH PID lifecycle | ✓ VERIFIED | 0600 atomic PID handoff and process identity checks are behaviorally tested. |
| `k8s/memory/50-monitoring.yaml` | Executable memory observer | ✓ VERIFIED (source) | Observer behavior is exercised with deterministic HTTP fixtures and has private Qdrant key input. |
| Prometheus values/render plus validators/tests | OPS-04 scrape/rule/alert boundary | ✓ VERIFIED (source) | Static observer and authenticated volume targets, rules, and alerts are present; backup selector is dynamically tied to the only CronJob. |
<!-- markdownlint-enable MD013 -->

### Key Link Verification

<!-- markdownlint-disable MD013 -->
| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Memory workflow | `memory-ci-deployer` | token, context, exact identity proof | ✓ WIRED | No staging/observability identity appears; forbidden mutation checks fail closed. |
| Workflow | rendered resources | one allowlist excluding namespace/RBAC bootstrap | ✓ WIRED | Same workload list is server-side dry-run then applied; rendered Secret is separately gated. |
| Workflow | managed tunnel | workflow-owned PID file and always cleanup | ✓ WIRED | Tests prove only a matching SSH command/forward/user/host is signaled. |
| Prometheus | observer | static target and reciprocal policies on TCP 9108 | ✓ WIRED (source) | Monitoring egress and memory observer ingress select only intended labels. |
| Observer | Qdrant | TCP 6333 egress and Qdrant ingress | ✓ WIRED (source) | Both selectors match the observer identity. |
| Observer | MemPalace | TCP 8765 egress and dedicated ingress | ✓ WIRED (source) | New ingress selects MemPalace and only observer peer; host-nginx IP policy remains separate. |
| Backup CronJob | snapshot freshness alert | sole parsed CronJob name | ✓ WIRED (source) | Values and committed render select `solidstats-memory-backup`; drift/missing/duplicate cases fail tests and validator. |
| Prometheus values | committed render | source/render contract | ✓ WIRED (static) | Both contain the same verified selector and all OPS-04 markers. Fresh chart regeneration remains an operator check. |
<!-- markdownlint-enable MD013 -->

### Data-Flow Trace (Level 4)

<!-- markdownlint-disable MD013 -->
| Artifact | Data | Source | Status |
| --- | --- | --- | --- |
| Observer MCP metrics | readiness, latency, errors | MemPalace `/healthz` through exact TCP 8765 policies | ✓ FLOWING (source design) |
| Observer Qdrant metrics | readiness, collection state, snapshot timestamp | Qdrant HTTP endpoints with Secret-derived API key | ✓ FLOWING (source design) |
| Prometheus observer scrape | observer metrics | static Service target | ✓ FLOWING (source design) |
| PVC capacity | `kubelet_volume_stats_*` | authenticated Kubernetes API node proxy | ✓ FLOWING (source design) |
| Snapshot freshness | timestamp and enabled CronJob state | recording/alerting rules keyed to manifest CronJob | ✓ FLOWING (source design) |
<!-- markdownlint-enable MD013 -->

### Behavioral Spot-Checks

<!-- markdownlint-disable MD013 -->
| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Migration policy | `timeout 10s python3 scripts/validate-solidstats-memory-policy.py` | PASS | ✓ PASS |
| Migration policy tests | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` | 7 passed | ✓ PASS |
| Deploy, tunnel, observer, and Prometheus contracts | `timeout 30s python3 tests/test-memory-runtime-contract.py` | 15 passed | ✓ PASS |
| Memory manifests | validator with operator placeholders | 27 resources validated | ✓ PASS |
| Observability source/render contract | `timeout 10s python3 scripts/validate-obs-manifests.py` | 22 manifest files validated | ✓ PASS |
| Strict memory/nginx gates | strict validators | Both rejected unresolved placeholders | ✓ PASS (expected rejection) |
| Live policy/Helm behavior | cluster and pinned chart | outside offline scope | ? SKIP |
<!-- markdownlint-enable MD013 -->

### Requirements Coverage

<!-- markdownlint-disable MD013 -->
| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| ISO-01 | 19-01 | ⚠️ DEFERRED | Policy uses `solidstats_memory`; registration/legacy alias removal is Phase 21 cutover work. |
| ISO-02 | 19-01..03 | ✓ SATISFIED (source) | Dedicated namespace, separate storage/runtime identities, and memory-only CI identity exist. |
| ISO-03 | 19-02 | ⚠️ DEFERRED | Qdrant is private and nginx is fail-closed; public TLS is Phase 21. |
| ISO-04 | 19-02..04 | ? NEEDS HUMAN | Exact static policies now pass; kube-router enforcement remains operator UAT. |
| RUN-01 | 19-02 | ⚠️ GATED | Correct HTTP contract exists; immutable MemPalace image remains intentionally operator-supplied. |
| RUN-02 | 19-02 | ✓ SATISFIED (source) | Private unprivileged StatefulSet has REST/gRPC, probes, RWO PVC, and Retain policy. |
| RUN-03 | 19-02, 19-03 | ✓ SATISFIED (source) | Separate identities, token-disabled hardening, read-only roots, explicit writable volumes, and resources are present. |
| RUN-04 | 19-02 | ✓ SATISFIED (source) | MemPalace and Qdrant use separate claims. |
| RUN-05 | 19-02 | ✓ SATISFIED | No ResourceQuota/LimitRange precedes sizing evidence. |
| MIG-03..07 | 19-01 | ✓ SATISFIED (policy gate) | Policy fixes rooms/wings and disables unapproved automation, KG, tunnels, and unverified bundle content. |
| OPS-01 | 19-02, 19-03 | ✓ SATISFIED (offline contract) | Dedicated workflow proves exact least-privilege identity before mutation. |
| OPS-04 | 19-02..04 | ✓ SATISFIED (source) | Complete static scrape/rule/alert source and reciprocal policy structure validate; live values remain UAT. |
<!-- markdownlint-enable MD013 -->

### Anti-Patterns Found

<!-- markdownlint-disable MD013 -->
| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `MEMORY_OPERATOR_*` inputs | Strictly rejected operator values | ℹ️ Intended gate | Validators reject unresolved images, sizes, CIDRs, and collection name. |
| Pinned-chart Helm render | Not run in offline Phase 19 | ⚠️ Warning | Requires approved operator/CI execution before future regeneration. |
<!-- markdownlint-enable MD013 -->

### Human Verification Required

### 1. kube-router policy enforcement

**Test:** Render real values in an isolated cluster; test observer→MemPalace,
observer→Qdrant, Prometheus→observer, host-nginx→MCP, DNS, and denied flows.

**Expected:** Every listed permitted path works and non-allowed ingress/egress is
denied.

**Why human:** Runtime source addressing and policy enforcement cannot be seen
from static manifests.

### 2. Pinned-chart render parity

**Test:** In the approved networked CI/operator environment, render Prometheus
chart v29.11.0 and compare it with `k8s/observability/10-prometheus.yaml`.

**Expected:** Observer jobs, node-volume job, rules, and alerts match the committed
configuration.

**Why human:** The phase intentionally did not fetch the pinned chart offline.

## Next Action

Perform the two operator checks above. No repository gap remains; after they
pass, record the UAT evidence rather than changing Phase 19 source artifacts.

---

_Verified: 2026-08-19T20:44:55Z_
_Verifier: the agent (gsd-verifier)_
