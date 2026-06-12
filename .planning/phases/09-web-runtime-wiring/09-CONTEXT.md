# Phase 9: web Runtime Wiring - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); enriched with codebase facts by the orchestrator

<domain>
## Phase Boundary

The future `web` application has a conventions-compliant Kubernetes slot — deployed as a
0-replica / image-pending stub — wired into validation and the rollout-status gate.

Requirements: WEB-01, WEB-02, WEB-03. Depends on: Phase 6.
This phase does NOT build/deploy a real web image (web app repo owns that, §D). It only creates
the repo-managed k8s SLOT so the future image drops in with zero new wiring.
</domain>

<decisions>
## Implementation Decisions

### Locked by codebase facts (verified 2026-06-13)
- **Closest analog = server-2**, which uses a SPLIT layout:
  - `k8s/staging/30-server-2.yaml` — ConfigMap + Service.
  - `k8s/staging/35-server-2-deployment.yaml` — ServiceAccount + Deployment.
  Mirror this split for web. Suggested filenames (numeric-prefix ordering, after server-2 / before
  replay-parser-2's 40): `36-web.yaml` (ConfigMap + Service) and `37-web-deployment.yaml`
  (ServiceAccount + Deployment). Planner may pick other free numbers in [36..39] but keep cm/svc < deployment.
- **server-2 Deployment conventions to copy** (`35-server-2-deployment.yaml`): dedicated
  `ServiceAccount` (name web), `automountServiceAccountToken: false`, `imagePullSecrets: ghcr-pull`,
  `imagePullPolicy: IfNotPresent`, a named container port, readinessProbe + livenessProbe,
  `resources.requests/limits` (cpu 100m/1, memory 256Mi/1Gi is the server-2 baseline — web can use the
  same or smaller), `securityContext` (allowPrivilegeEscalation:false, capabilities drop ALL),
  standard `app.kubernetes.io/*` labels, explicit namespace `solid-stats-staging`.
- **Integration points that MUST be updated (WEB-03):**
  - `scripts/validate-staging.py`: add web manifest filenames to `EXPECTED_MANIFESTS` (line ~17) and a
    `web` entry to `EXPECTED_WORKLOADS` (line ~49, kind Deployment, its file).
  - `.github/workflows/deploy-staging.yml` "Verify rollouts" step (lines ~127-139): add
    `kubectl -n "$K8S_NAMESPACE" rollout status deployment/web --timeout=300s` and include `web` in the
    `kubectl get service ...` line. A 0-replica Deployment reports rollout success immediately (0/0 ready),
    so this does NOT break the deploy (WEB-02).
- **CD glob:** web manifests are normal `k8s/staging/*.yaml` depth-1 files → they ARE applied by CD
  (`find k8s/staging -maxdepth 1 -name '*.yaml' ! -name 01-ci-rbac.yaml`). That is correct and intended
  here (unlike the restore-drill, which must stay OUT).

### Claude's discretion (decide during planning, justify in PLAN)
- **WEB-02 image-pending strategy.** A Deployment needs an `image:` value, but no real web image exists yet
  AND replicas must be 0. Options to weigh: (a) pin a tiny inert placeholder (e.g. `registry.k8s.io/pause:3.9`
  pinned by tag/digest) with `replicas: 0`, clearly commented as a placeholder to be swapped for the real
  `ghcr.io/solid-stats/web@sha256:…` image; (b) a clearly-marked non-resolving `ghcr.io/solid-stats/web:PENDING`
  placeholder with `replicas: 0` (never pulled because 0 replicas). Pick the one that (i) keeps `validate-staging.py`
  app-image-pin check happy or is explicitly excepted, (ii) cannot accidentally run a wrong image, and (iii) makes
  the future swap a one-line image change. Document the swap procedure.
- **Probes on a 0-replica stub:** keep readiness/liveness probe definitions (WEB-01 requires them) even though
  no pod runs at 0 replicas — they activate automatically when replicas/image are set.
- **ConfigMap contents:** a minimal `web-config` ConfigMap mirroring how `server-2-config` is structured (env
  the future web app will need, e.g. an API base URL pointing at the in-cluster server-2 Service). Keep it minimal
  and clearly marked as a starting point; no secrets in the ConfigMap.
- Whether `validate-staging.py`'s app-image-pin / workload-safety checks need a documented exception for a
  0-replica image-pending workload (so a placeholder image or 0 replicas does not trip the long_running checks).
</decisions>

<code_context>
## Existing Code Insights
- `k8s/staging/30-server-2.yaml` + `35-server-2-deployment.yaml` — the split analog to mirror exactly.
- `scripts/validate-staging.py` — EXPECTED_MANIFESTS / EXPECTED_WORKLOADS / app-image-pin / workload-safety checks to extend.
- `.github/workflows/deploy-staging.yml` "Verify rollouts" — add web rollout-status + service get.
- AGENTS.md — manifest conventions (numeric prefixes, explicit namespace, app labels, pinned images, no default SA).
</code_context>

<specifics>
## Specific Ideas
- The slot must be a true no-op at 0 replicas: applying it to the cluster changes nothing runtime-visible,
  and the rollout-status gate stays green.
- Future image swap = change `replicas: 0 → N` and the `image:` line; nothing else.
</specifics>

<deferred>
## Deferred Ideas
- Building/deploying the real web image — owned by the web app repo (§D), out of scope here.
- HPA / ingress / web-specific network policy beyond the server-2 baseline — not in WEB-01..03.
</deferred>
