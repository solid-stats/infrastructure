---
phase: 19-solidstats-memory-foundation
plan: "02"
subsystem: isolated-memory-runtime
tags: [kubernetes, qdrant, mempalace, nginx, github-actions, fail-closed]
requires: [19-01]
provides:
  - Isolated SolidStats memory Kubernetes boundary
  - Fail-closed deploy-time rendering and validation
  - Suspended backup and static health-target handoff
affects: [20-memory-migration, solidstats-memory-cutover]
tech-stack:
  added: [Qdrant v1.19.0-unprivileged, Kubernetes NetworkPolicy]
  patterns:
    - Operator placeholders rejected before deployment
    - Namespace-scoped CI identity and disposable manifest rendering
    - Default-deny workload network isolation
key-files:
  created:
    - k8s/memory/00-namespace.yaml
    - k8s/memory/10-qdrant.yaml
    - k8s/memory/20-mempalace.yaml
    - scripts/validate-memory-manifests.py
    - config/nginx/sites-available/solidstats-memory-mcp.conf.template
  modified:
    - docs/solidstats-memory.md
    - .github/workflows/deploy-memory.yml
decisions:
  - Qdrant is private ClusterIP-only and MemPalace is exposed only through a future host nginx route.
  - All unverified runtime values remain explicit placeholders and fail strict validation.
  - Backup begins suspended and cannot upload until its collection, uploader, credentials, and egress are approved.
metrics:
  duration: 35m
  completed: 2026-08-19
status: complete
---

# Phase 19 Plan 02: Author the Isolated Runtime Boundary Summary

**A validation-ready, default-deny Qdrant and MemPalace runtime boundary with
operator-gated deployment, backup, monitoring, and HTTPS MCP edge artifacts.**

## Accomplishments

- Created `solidstats-memory` namespace bootstrap, scoped CI RBAC, dedicated
  ServiceAccounts, separate RWO storage, private Qdrant, and internal MemPalace.
- Pinned Qdrant to the verified unprivileged v1.19.0 digest; kept MemPalace and
  backup images as strict operator gates.
- Added default-deny policies with explicit DNS, Qdrant, backup upload,
  Prometheus, and host-nginx paths; the two unmeasured CIDRs remain rejected.
- Added a suspended snapshot-packaging CronJob and verified-health target
  handoff without inventing a metrics endpoint or alert metric name.
- Added disposable manifest and secret renderers, strict offline validators,
  an independent deployment workflow, and an uninstalled nginx MCP template.

## Task Commits

1. **Task 1: Namespace, identity, workload, and storage** — `08ce70d`
2. **Task 2: Network isolation** — `485729f`
3. **Task 3: Backup and monitoring** — `7c9d118`
4. **Task 4: Independent deploy path** — `6313d01`
5. **Task 5: Public edge preparation** — `5899766`

## Verification

- `python3 -m py_compile` passed for all new Python scripts.
- `python3 scripts/validate-memory-manifests.py --allow-operator-placeholders`
  validated 22 source resources.
- Strict manifest validation failed as intended, listing all seven unresolved
  `MEMORY_OPERATOR_*` manifest gates.
- Rendering into a temporary directory with synthetic values passed strict
  manifest validation for all 22 resources.
- `python3 scripts/validate-memory-nginx.py --allow-operator-placeholders`
  passed; strict mode rejected the four unresolved edge placeholders.
- `markdownlint-cli2 --fix docs/solidstats-memory.md` completed with no errors.
- `git diff --check` and the scoped high-confidence secret-pattern scan passed.
- `actionlint` and a YAML parser were unavailable; the workflow is covered by
  the local workflow-contract validator and static review instead.

## Operator Gates

- Supply immutable MemPalace and backup-uploader image digests.
- Measure the kube-router source CIDR for host nginx and approve the S3 egress
  CIDR, persistent-volume sizing, and collection name.
- Provide protected deployment secrets, confirm metrics and probe integration,
  then complete an isolated restore drill.
- Resolve the host-routable MemPalace ClusterIP, public server name, and TLS
  paths before nginx validation, installation, or reload.
- Obtain separate authorization before applying namespace/RBAC/workload files,
  changing nginx/DNS, or inspecting a live cluster.

## Deviations from Plan

### Auto-fixed Issues

1. **[Rule 1 - Bug] Restored backup-to-Qdrant ingress alignment**
   - **Found during:** Task 3
   - **Issue:** The backup job had Qdrant egress but Qdrant ingress initially
     allowed only MemPalace, so snapshots would be blocked when enabled.
   - **Fix:** Allowed the dedicated backup pod selector on Qdrant port 6333.
   - **Files modified:** `k8s/memory/30-network-policy.yaml`
   - **Commit:** `7c9d118`

2. **[Rule 1 - Bug] Made the validator distinguish source and rendered gates**
   - **Found during:** Task 4 verification
   - **Issue:** The strict validator required source placeholder strings even
     after a valid temporary render.
   - **Fix:** It now checks placeholders in source and validates resolved CIDRs
     in rendered manifests.
   - **Files modified:** `scripts/validate-memory-manifests.py`
   - **Commit:** `5899766`

3. **[Rule 2 - Critical functionality] Denied backup uploads until S3 egress
   is approved**
   - **Found during:** Task 3
   - **Issue:** Default deny would leave a future backup job unable to reach
     its object store.
   - **Fix:** Added a dedicated backup-only HTTPS egress policy with an
     explicit validator-rejected CIDR gate.
   - **Files modified:** `k8s/memory/30-network-policy.yaml`
   - **Commit:** `7c9d118`

4. **[Rule 1 - Bug] Made the Qdrant governing Service headless**
   - **Found during:** Kubernetes compliance pass
   - **Issue:** The Qdrant StatefulSet pointed at a normal ClusterIP Service,
     which does not provide StatefulSet pod identities.
   - **Fix:** Set `clusterIP: None` and added a matching validator assertion.
   - **Files modified:** `k8s/memory/10-qdrant.yaml`,
     `scripts/validate-memory-manifests.py`
   - **Commit:** `8a78515`

## Known Stubs

The following placeholders are intentional fail-closed operator gates and do
not claim a deployable runtime:

- MemPalace and backup-uploader image digests.
- Qdrant and MemPalace PVC sizes.
- Host-nginx and S3 egress CIDRs.
- Qdrant collection name.
- nginx ClusterIP, public server name, and TLS certificate paths.

## Self-Check: PASSED

- All expected `k8s/memory/`, renderer, validator, workflow, edge-template, and
  documentation files exist.
- Task commits `08ce70d`, `485729f`, `7c9d118`, `6313d01`, and `5899766` exist.
- Only pre-existing concurrent paths remain outside this plan's committed scope.
