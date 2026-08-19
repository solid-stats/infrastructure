---
phase: 19-solidstats-memory-foundation
verified: 2026-08-19T19:32:38Z
status: gaps_found
score: 2/5 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "A dedicated deploy path can apply the isolated memory workload boundary using the namespace-scoped CI identity."
    status: failed
    reason: "The only deploy job has no cluster authentication or apply command and intentionally ends with `exit 1`; supplying every required GitHub value still produces a failed deployment."
    artifacts:
      - path: ".github/workflows/deploy-memory.yml"
        issue: "The final step prints an operator message and executes `exit 1` instead of invoking an authenticated, namespace-scoped apply path."
    missing:
      - >-
        An operator-authorized, authenticated apply mechanism that excludes bootstrap
        resources and uses only the memory namespace identity.
  - truth: "Static Prometheus scraping covers MCP readiness/latency/errors, Qdrant health/collection state, snapshot freshness, and PVC capacity."
    status: failed
    reason: "Only a disconnected ConfigMap handoff for two `/healthz` URLs exists. No Prometheus configuration consumes it, and no latency, error, collection-state, snapshot-freshness, or PVC-capacity signal is configured."
    artifacts:
      - path: "k8s/memory/50-monitoring.yaml"
        issue: "Contains two health targets and an explicit gate for alerts, not the OPS-04 scrape and alert coverage."
      - path: "k8s/observability/10-prometheus.yaml"
        issue: "Has no SolidStats-memory scrape configuration or reference to the handoff ConfigMap."
    missing:
      - >-
        Operator-approved Prometheus scrape/probe integration plus observed metric and
        alert definitions for every OPS-04 signal.
behavior_unverified_items:
  - truth: >-
      Default-deny policies permit only DNS, MemPalace-to-Qdrant, host-nginx-to-MCP,
      and Prometheus scrape paths under kube-router.
    test: >-
      After the measured host CIDR is rendered in an isolated cluster, exercise DNS,
      Qdrant access, nginx MCP access, and Prometheus scraping while attempting
      disallowed traffic.
    expected: "All required paths work and every other ingress/egress path is denied."
    why_human: >-
      Static manifests prove selectors and declared rules, but not kube-router
      source-address semantics or runtime policy enforcement.
---

# Phase 19: SolidStats Memory Foundation Verification Report

**Phase Goal:** Add repository-local policy, validation, and plans for a dedicated
namespace/runtime/storage/network/backup/monitoring/CD boundary.
**Verified:** 2026-08-19T19:32:38Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

<!-- markdownlint-disable MD013 -->
| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | The migration contract freezes the accepted rooms/wings and rejects incomplete or checksum-drifted offline bundles. | ✓ VERIFIED | `migration-policy.json` fixes the six rooms, five archives, `SolidStats`, frozen writes, and disabled features; `validate-solidstats-memory-policy.py` and all 7 unit tests passed. |
| 2 | A source-only isolated runtime/storage boundary exists and refuses unmeasured runtime values. | ✓ VERIFIED | `k8s/memory/` contains 22 validated resources. Separate PVCs, private Qdrant StatefulSet, internal MemPalace Deployment, hardened pod specs, and strict placeholder rejection are present. A synthetic render also passed strict validation. |
| 3 | Default-deny ingress/egress permits precisely the intended runtime paths under kube-router. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | The policy set and strict host-CIDR gate are present, but no cluster probe can establish kube-router source semantics or actual allow/deny behavior. |
| 4 | The dedicated memory deployment workflow can deploy the isolated workload boundary. | ✗ FAILED | `deploy-memory.yml` renders manifests but neither authenticates to a cluster nor applies them; its final command is `exit 1`. |
| 5 | Monitoring covers all OPS-04 signals. | ✗ FAILED | `50-monitoring.yaml` is an unconsumed health-target handoff only; no scrape configuration or coverage for latency, errors, collection state, snapshot freshness, or PVC capacity exists. |

**Score:** 2/5 truths verified (1 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `config/solidstats-memory/migration-policy.json` | Frozen migration/room/wing policy | ✓ VERIFIED | Exact policy values are checked by the offline validator. |
| `scripts/validate-solidstats-memory-policy.py` | Fail-closed policy and bundle validator | ✓ VERIFIED | Validates required attestations, safe relative paths, lowercase SHA-256, existence, and matching digests. |
| `k8s/memory/` | Isolated namespace/runtime/storage/network/backup/monitoring manifests | ⚠️ PARTIAL | Runtime, storage, network, and backup sources are substantive; monitoring is only a handoff and cannot meet OPS-04. |
| `scripts/render-memory-manifests.py` and `scripts/validate-memory-manifests.py` | Disposable render plus strict structural validation | ✓ VERIFIED | Source passes only with explicit placeholder allowance; synthetic values render and pass strict validation. |
| `.github/workflows/deploy-memory.yml` | Independent CD path | ✗ FAILED | Has validate/render stages but is deliberately non-deploying and always fails. |
| `config/nginx/sites-available/solidstats-memory-mcp.conf.template` | Public HTTPS MCP edge preparation | ✓ VERIFIED | Restricts the public route to `/solidstats/mcp`, forwards Authorization, disables buffering, and strict mode rejects all unresolved edge values. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| MemPalace Deployment | Qdrant Service | `MEMPALACE_QDRANT_URL=http://qdrant:6333` and NetworkPolicy | ✓ WIRED | Qdrant is headless ClusterIP-only; MemPalace has Qdrant backend/key/namespace configuration. |
| MemPalace PVC | MemPalace writable data path | `/data` mount and `MEMPALACE_DATA_DIR=/data/palace` | ✓ WIRED | Writable PVC is mounted at `/data`; `/tmp` is separately writable under a read-only root filesystem. |
| Qdrant StatefulSet | Qdrant storage | `volumeClaimTemplates` mounted at `/qdrant/storage` | ✓ WIRED | Single-replica StatefulSet uses an RWO claim and Retain ownership policy. |
| Host nginx template | MemPalace HTTP MCP | `/solidstats/mcp` proxies to upstream `/mcp` | ✓ WIRED (template) | It is intentionally uninstalled and strict validation rejects unresolved address/TLS values. |
| Backup CronJob | Qdrant snapshot and S3 prefix | Snapshot API, checksums, `backups/solidstats-memory/` | ⚠️ GATED | Source is substantive and suspended; uploader image, collection, S3 CIDR, credentials, and restore drill remain operator gates. |
| Memory monitoring handoff | Prometheus | ConfigMap target consumption | ✗ NOT WIRED | No observability manifest references `solidstats-memory-health-targets`. |
| Deploy workflow | Namespace-scoped CI identity / cluster | Authenticated apply | ✗ NOT WIRED | Workflow contains no kubeconfig/SSH/kubectl/apply action and terminates non-zero. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| MemPalace runtime | Qdrant URL/key/namespace and MCP token | Deploy-time rendered Kubernetes Secrets plus manifest literals | Yes after an authorized render/apply | ✓ FLOWING (source design) |
| Backup CronJob | Snapshot, metadata archive, checksums | Qdrant API and MemPalace PVC | Not yet; job is suspended and uploader contract is unresolved | ⚠️ GATED |
| Monitoring ConfigMap | `targets.yaml` | Hard-coded service health URLs | No Prometheus consumer and no observed metrics | ✗ DISCONNECTED |
| Deploy workflow | Rendered manifests and secrets | GitHub environment variables/secrets | Stops before any cluster operation | ✗ DISCONNECTED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Policy invariants | `timeout 10s python3 scripts/validate-solidstats-memory-policy.py` | PASS | ✓ PASS |
| Policy regression suite | `timeout 10s python3 -m unittest tests/test-solidstats-memory-policy.py` | 7 tests passed | ✓ PASS |
| Source manifest boundary | `timeout 10s python3 scripts/validate-memory-manifests.py --allow-operator-placeholders` | 22 resources validated | ✓ PASS |
| Strict manifest gate | `timeout 10s python3 scripts/validate-memory-manifests.py` | Rejected 7 unresolved operator placeholders | ✓ PASS (expected rejection) |
| Rendered manifest boundary | Synthetic values → render → strict validate | 22 resources validated | ✓ PASS |
| Nginx gate | `timeout 10s python3 scripts/validate-memory-nginx.py` | Rejected 4 unresolved edge placeholders | ✓ PASS (expected rejection) |
| Cluster/edge/backup behavior | Live cluster or nginx execution | Forbidden by this verification scope | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| ISO-01 | 19-01 | ⚠️ DEFERRED | Policy names `solidstats_memory`; actual registration/removal of the legacy alias is explicitly deferred to Phase 21. |
| ISO-02 | 19-01, 19-02 | ✓ SATISFIED (source boundary) | Dedicated `solidstats-memory` manifests/PVCs and deploy-time secret renderer are outside `k8s/staging/`. |
| ISO-03 | 19-02 | ⚠️ DEFERRED | Private Qdrant and nginx template exist; public HTTPS exposure must wait for Phase 21/operator evidence. |
| ISO-04 | 19-02 | ? NEEDS HUMAN | Static default-deny rules are present; kube-router behavior is untested. |
| RUN-01 | 19-02 | ⚠️ GATED | Correct HTTP MCP command/probe exists, but immutable MemPalace image is deliberately unresolved. |
| RUN-02 | 19-02 | ✓ SATISFIED (source boundary) | One unprivileged StatefulSet, private REST/gRPC Service, health probes, RWO claim, and Retain policy are present. |
| RUN-03 | 19-02 | ⚠️ GATED | Required hardening is statically present; an actual local-build MemPalace image has not proven its writable-path/runtime compatibility. |
| RUN-04 | 19-02 | ✓ SATISFIED (source boundary) | MemPalace claim is separate from Qdrant claim and mounted at `/data` with `/data/palace` configured. |
| RUN-05 | 19-02 | ✓ SATISFIED | No ResourceQuota/LimitRange is introduced; docs retain the measurement and allocatable-evidence gate. |
| MIG-03..07 | 19-01 | ✓ SATISFIED (policy gate) | Policy and validator freeze active/archive scope, disable specified automation/KG/tunnels, require exact-ID deletion approval, and require bundle evidence/checksums. |
| OPS-01 | 19-02 | ✗ BLOCKED | CI Role is namespace scoped, but the workflow cannot deploy with it. |
| OPS-04 | 19-02 | ✗ BLOCKED | No consumed scrape configuration or required signal coverage exists. |

### Requirement Traceability Mismatch

ROADMAP.md assigns `MIG-03..07` to Phase 19, while REQUIREMENTS.md maps the
complete `MIG-01..07` range to Phase 20. Plan 19-01 nevertheless declares and
implements policy gates for `MIG-03..07`. This report credits only those policy
gates; it does not claim the Phase 20 transform/parity work has occurred. The
roadmap and requirements traceability table need one authoritative assignment
before migration work is planned or phase completion is asserted.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `.github/workflows/deploy-memory.yml` | 70 | Unconditional `exit 1` | 🛑 Blocker | The advertised deploy workflow cannot succeed. |
| `k8s/memory/50-monitoring.yaml` | 1-20 | Static, unconsumed handoff only | 🛑 Blocker | OPS-04 signals are neither scraped nor alerted on. |
| `k8s/memory/*`, validators, docs | various | `MEMORY_OPERATOR_*` placeholders | ℹ️ Intended gate | Strict validators reject unresolved values; these are not stubs. |
<!-- markdownlint-enable MD013 -->

### Human Verification Required

### 1. kube-router policy enforcement

**Test:** Render the measured host CIDR in an isolated cluster, then exercise all
permitted and denied DNS, Qdrant, nginx MCP, and Prometheus flows.

**Expected:** Required flows succeed; every other ingress and egress flow is denied.

**Why human:** The source proves only the declared selectors/CIDRs. Runtime
source-address rewriting and enforcement are cluster-dependent.

### Gaps Summary

Phase 19 establishes a substantive source-only policy/runtime boundary, and the
placeholder gates are correctly fail-closed. It does not achieve the full CD or
monitoring portions of its declared contract: the workflow cannot apply anything,
and OPS-04 has neither an actual Prometheus integration nor the required signals.
These are not future-phase deferrals: the later roadmap phases cover migration and
restore/cutover, not a replacement deploy workflow or OPS-04 implementation.

## Next Action

Run `$gsd-plan-phase 19 --gaps` to create a focused closure plan for the deploy
path and OPS-04 monitoring integration. Keep the kube-router enforcement check
as an operator-gated UAT item after the required CIDR is measured.

---

_Verified: 2026-08-19T19:32:38Z_
_Verifier: the agent (gsd-verifier)_
