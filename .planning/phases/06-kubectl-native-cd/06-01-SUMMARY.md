---
phase: "06-kubectl-native-cd"
plan: 1
subsystem: "ci-rbac-bootstrap"
status: complete
tags: [kubernetes, rbac, serviceaccount, operator-bootstrap, ci-cd]

dependency_graph:
  requires: []
  provides:
    - "k8s/staging/01-ci-rbac.yaml — ServiceAccount ci-deployer, token Secret ci-deployer-token, Role ci-deployer, RoleBinding ci-deployer"
    - "docs/operator-bootstrap.md — one-time operator runbook: namespace, RBAC, cert SAN, GitHub secrets"
  affects:
    - "Plan 04 — deploy glob must exclude 01-ci-rbac.yaml"
    - ".github/workflows/deploy-staging.yml — references K8S_TOKEN, K8S_CA_CERT, WG_* secrets populated by this runbook"

tech_stack:
  added: []
  patterns:
    - "kubernetes.io/service-account-token Secret (k8s >=1.24 explicit long-lived token)"
    - "namespace-scoped Role with apply+rollout verbs only (no cluster-scoped grants)"
    - "operator-bootstrap separation: operator applies RBAC once; CI never creates namespace or RBAC resources"

key_files:
  created:
    - path: "k8s/staging/01-ci-rbac.yaml"
      purpose: "Four-document RBAC manifest: ServiceAccount, token Secret, Role, RoleBinding for ci-deployer"
    - path: "docs/operator-bootstrap.md"
      purpose: "One-time operator runbook covering namespace creation, RBAC bootstrap, RBAC verification, token/CA extraction, cert SAN patching, and WireGuard secrets"
  modified: []

decisions:
  - "Long-lived kubernetes.io/service-account-token Secret used (not TokenRequest) — simpler for CI; rotation documented in sa-token-rotation.md"
  - "Role is namespace-scoped only — no cluster-scoped grants; namespace must be created by operator before first deploy"
  - "01-ci-rbac.yaml excluded from CI deploy glob (Plan 04 responsibility) — file is operator-applied once"
  - "tls-san patching documented in runbook with explicit cert deletion + k3s restart steps — NEVER --insecure-skip-tls-verify"

metrics:
  duration: "~10 minutes"
  completed_date: "2026-06-12"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 6 Plan 1: Operator Bootstrap RBAC and Runbook Summary

Namespace-scoped RBAC manifest and full operator runbook enabling CI-deployer ServiceAccount authentication to k3s over WireGuard.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Operator bootstrap manifest — ServiceAccount, token Secret, Role, RoleBinding | 4667fb1 | k8s/staging/01-ci-rbac.yaml |
| 2 | Operator bootstrap runbook — namespace, RBAC, cert SAN, GitHub secrets | 7b7c833 | docs/operator-bootstrap.md |

## What Was Built

**`k8s/staging/01-ci-rbac.yaml`** — Four-document YAML (ServiceAccount, Secret, Role, RoleBinding) for the `ci-deployer` identity in `solid-stats-staging`. The Role is namespace-scoped and covers exactly the verbs required for `kubectl apply` and `kubectl rollout status` on all staging workload kinds (Deployments, StatefulSets, CronJobs, Services, ConfigMaps, Secrets, PVCs, ServiceAccounts, Pods). No cluster-scoped resources are granted. The token Secret carries the `kubernetes.io/service-account-token` type annotation — required in k8s ≥1.24 since auto-generation was removed.

**`docs/operator-bootstrap.md`** — Six-step runbook the operator runs once before the first CI deploy: create namespace, apply RBAC manifest, verify permissions with `kubectl auth can-i --list`, extract `K8S_TOKEN` and `K8S_CA_CERT` for GitHub environment secrets, patch k3s certificate SANs for `10.8.0.1`, configure WireGuard secrets. Troubleshooting table covers all common failure modes.

## Verification Results

- `python3 yaml.safe_load_all` parses 4 documents: ServiceAccount, Secret, Role, RoleBinding
- `grep -c "^kind:" k8s/staging/01-ci-rbac.yaml` = 4
- `grep "kubernetes.io/service-account-token"` exits 0
- No cluster-scoped resources in Role rules
- `app.kubernetes.io/part-of: solid-stats` label on all 4 documents
- `grep -c "^## " docs/operator-bootstrap.md` = 9 (≥7 required)
- K8S_TOKEN, K8S_CA_CERT, tls-san, insecure-skip-tls-verify, "CI never creates", auth can-i — all present in runbook

Note: `kubectl apply --dry-run=client` was attempted but the k3s API at `10.8.0.1:6443` is not reachable from the local machine (expected per sequential_mode_notes). YAML validity was confirmed via `python3 yaml.safe_load_all`.

## Deviations from Plan

None — plan executed exactly as written. The only deviation from the verification spec is that client-side `kubectl --dry-run=client` timed out (no live cluster reachable from CI machine), and Python YAML parse was used instead, which is the documented fallback in sequential_mode_notes.

## Threat Surface Scan

No new network endpoints or auth paths beyond what is documented in the plan's threat model. The files contain no secret values — the token Secret carries only the type annotation and empty data; the control plane populates the token at apply time on the VPS.

## Requirements Satisfied

- **CD-02**: ci-deployer ServiceAccount and long-lived token Secret created
- **CD-04**: Role is namespace-scoped; no cluster-scoped grants; covers apply and rollout status verbs
- **CD-05**: Namespace and RBAC are operator-bootstrapped; operator-bootstrap.md documents that CI never creates the namespace

## Self-Check: PASSED

- [x] k8s/staging/01-ci-rbac.yaml exists and parses as 4 YAML documents
- [x] docs/operator-bootstrap.md exists with 9 `##` sections
- [x] Commit 4667fb1 exists (Task 1)
- [x] Commit 7b7c833 exists (Task 2)
