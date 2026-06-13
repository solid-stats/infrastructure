---
phase: 09-web-runtime-wiring
reviewed: 2026-06-13T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - k8s/staging/36-web.yaml
  - k8s/staging/37-web-deployment.yaml
  - scripts/validate-staging.py
  - .github/workflows/deploy-staging.yml
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-06-13
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 9 adds a conventions-compliant Kubernetes slot for the future `web` app as a
0-replica / placeholder-image (`registry.k8s.io/pause:3.9`) stub, and wires it into
`validate-staging.py` and the CD rollout/service gates. The implementation is solid
and proportionate to a low-risk stub. Convention fidelity against the
`35-server-2-deployment.yaml` reference is essentially exact: dedicated
ServiceAccount, `automountServiceAccountToken: false`, `imagePullPolicy: IfNotPresent`,
both probes, resource requests+limits, `securityContext` (allowPrivilegeEscalation:false
+ drop ALL), explicit namespace, `app.kubernetes.io` labels, and numeric-prefix
ordering are all present and match the codebase baseline (web omits
`readOnlyRootFilesystem`/`runAsNonRoot`/`seccompProfile`, but so does server-2, so this
is consistent with the established convention, not a regression).

`validate-staging.py` correctly adds `web` to `EXPECTED_MANIFESTS` and
`EXPECTED_WORKLOADS`, and correctly EXCLUDES it from `APP_IMAGES` (pause is not a GHCR
image — including it would have failed the `image: ghcr.io/solid-stats/` pin check).
The workload-safety check passes for `web` as a `long_running: True` Deployment because
probes + resources + securityContext + SA token disable are all present. The
`validate-staging.py` run is green locally (all six checks `ok`).

The CD changes are correct: `rollout status deployment/web` on a 0-replica Deployment
returns success immediately (the controller reports the rollout complete once observed
replicas reconcile to 0), so it does not block CD; `web` is correctly appended to the
`get service ... web` line.

The one substantive finding (WR-01) is a future-swap footgun: the probes target a port
the `pause` image does not serve, so the documented activation step ("set replicas > 0")
in isolation would produce a CrashLoop/NotReady deployment and a stuck `rollout status`
gate — the image swap is mandatory and must happen in the same change, which the inline
comments imply but the deployment-spec comment (lines 19-22) does not state as forcefully
as the container-line comment (lines 39-40).

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Activating the stub by replicas alone (without the image swap) would CrashLoop and block CD

**File:** `k8s/staging/37-web-deployment.yaml:19-23,49-60`
**Issue:** The deployment carries HTTP `readinessProbe` and `livenessProbe` against
`port: http` (containerPort 3001), but the placeholder `registry.k8s.io/pause:3.9`
image serves nothing on 3001. While `replicas: 0` this is inert and harmless. The risk
is the documented activation path: the deployment-spec comment (lines 19-22) says
"To activate: set replicas: N and replace the image line", but the two steps are
described as a list and an operator skimming could raise replicas first (or only) — at
which point pods never pass readiness, the liveness probe kills them, the deployment
CrashLoops, and the CD `rollout status deployment/web --timeout=300s` gate
(`deploy-staging.yml:134`) blocks for 300s and then fails the deploy job. This turns a
"harmless stub" into a CD outage if the swap is done partially.
**Fix:** Make the image-and-replicas swap atomic and unmissable in the comment that sits
directly above `replicas:` (not only the one above `image:`). For example:

```yaml
spec:
  # WEB-02: stub at 0 replicas pending real image.
  # ACTIVATION IS ATOMIC — do BOTH in the same commit, never replicas alone:
  #   1. replace the image line with: image: ghcr.io/solid-stats/web@sha256:<digest>
  #   2. set replicas: N
  # Raising replicas without swapping the image will CrashLoop (pause serves
  # nothing on 3001) and block the CD `rollout status deployment/web` gate.
  replicas: 0
```

No code change is strictly required for the stub to be correct today; this is a
guardrail for the future swap.

## Info

### IN-01: `port: http` probe/Service targetPort depends on the future image binding 3001 — document the contract

**File:** `k8s/staging/36-web.yaml:24-27`, `k8s/staging/37-web-deployment.yaml:43-58`
**Issue:** The Service `targetPort: http` and both probes (`port: http`) resolve through
the container port named `http` (containerPort 3001) and the ConfigMap `PORT: "3001"`.
These three must stay in agreement when the real image lands; if the real web image
listens on a different port or names it differently, the Service and probes silently
break. This is an implicit contract, not a defect today.
**Fix:** Add a one-line comment near the `ports:` block noting that `PORT` (ConfigMap),
`containerPort` (3001), the port name `http`, and the Service `targetPort: http` must
match whatever the real `web` image serves.

### IN-02: `name: {name}` substring workload-detection in `validate_workload_safety` is loose (pre-existing)

**File:** `scripts/validate-staging.py:261`
**Issue:** `require(f"name: {name}" in text, ...)` asserts the workload name appears
anywhere in the file as a substring. For `web`, `name: web` matches the ServiceAccount,
Deployment, and container — fine. But the check is positional-agnostic: it does not
confirm the safety fields (`serviceAccountName`, `automountServiceAccountToken: false`,
`securityContext`, probes) belong to the *workload's* pod template rather than merely
co-existing somewhere in the file. This is a pre-existing weakness in the shared helper,
not introduced by Phase 9, and it happens to pass correctly for `web` because the file
contains exactly one workload. Flagging so it is not mistaken for per-workload rigor.
**Fix:** No action required for this phase. If hardened later, scope the field checks to
the document containing `kind: Deployment` for `{name}` (the file already has
`split_documents`).

### IN-03: Local `validate-staging.py` run cannot exercise the `web` probe/port wiring

**File:** `scripts/validate-staging.py:252-272`
**Issue:** `validate_workload_safety` only asserts the *presence* of `readinessProbe:`/
`livenessProbe:`/`resources:` substrings for `long_running` workloads. It does not (and
for a stdlib-only line parser, cannot easily) validate that the probe `port` resolves to
a declared `containerPort`, nor that a 0-replica long-running workload is intentional.
So the WR-01 future-swap hazard is invisible to CI by design. Acceptable for a stub.
**Fix:** None required. The authoritative `kubectl apply --dry-run=server` step in
`deploy-staging.yml` will validate schema, and `rollout status` will catch a bad
activation at deploy time (which is the WR-01 failure mode).

### IN-04: ConfigMap `web-config` is clean — minimal, no secrets

**File:** `k8s/staging/36-web.yaml:1-13`
**Issue:** Not a defect — recorded as a positive verification. `web-config` contains only
`NODE_ENV`, `PORT`, and `API_BASE_URL: http://server-2:3000` (in-cluster Service DNS, no
credentials), matching the "no secrets in ConfigMaps" convention and the AGENTS.md secret
policy. `API_BASE_URL` correctly targets `server-2`'s Service port 3000.
**Fix:** None.

---

_Reviewed: 2026-06-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
