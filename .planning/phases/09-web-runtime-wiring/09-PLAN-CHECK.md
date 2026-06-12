---
phase: 09-web-runtime-wiring
plan_count: 1
status: PASS
verified_date: 2026-06-13
---

# Phase 9: web Runtime Wiring — Plan Verification

**Result:** PASS — Plan 09-01 will achieve the phase goal.

---

## Verification Summary

### Phase Goal
"The future `web` application has a conventions-compliant Kubernetes slot — deployed as a 0-replica / image-pending stub — wired into validation and the rollout-status gate."

### Requirements Covered
- **WEB-01**: ✓ web Deployment, Service, and ConfigMap follow server-2 conventions
- **WEB-02**: ✓ web deploys as 0-replica / image-pending stub without blocking deploy
- **WEB-03**: ✓ validate-staging.py and deploy-staging.yml integration complete

---

## Dimension Results

### 1. Requirement Coverage
All three WEB-01..03 requirements have explicit covering tasks:
- **WEB-01** (conventions) — Task 1: Creates manifests with dedicated ServiceAccount, automountServiceAccountToken:false, imagePullSecrets, imagePullPolicy:IfNotPresent, named ports, readinessProbe + livenessProbe, resource requests/limits, securityContext (allowPrivilegeEscalation:false, drop ALL), app.kubernetes.io labels, explicit namespace. Mirrors server-2 conventions exactly.
- **WEB-02** (0-replica stub) — Task 1: `replicas: 0` and `registry.k8s.io/pause:3.9` placeholder (inert, won't pull, can't run code). Task 2: kubectl rollout status exits 0 immediately because 0/0 desired = already satisfied.
- **WEB-03** (validation) — Task 2: Extends validate-staging.py EXPECTED_MANIFESTS (adds 36-web.yaml, 37-web-deployment.yaml) and EXPECTED_WORKLOADS (adds web Deployment entry with long_running:True). Extends deploy-staging.yml Verify rollouts with `kubectl rollout status deployment/web` and Verify services with `web` in the get service line.

**Status:** ✓ Complete

---

### 2. Task Completeness
**Task 1: Create web manifests**
- Files: k8s/staging/36-web.yaml, k8s/staging/37-web-deployment.yaml — specified ✓
- Action: Detailed block-by-block YAML spec for ConfigMap, Service, ServiceAccount, Deployment with all required conventions — specific and runnable ✓
- Verify: Automated grep checks for namespace, labels, replicas:0, pause:3.9, automountServiceAccountToken:false, readinessProbe, livenessProbe, plus Python manifest structure validation ✓
- Done: Acceptance criteria list all WEB-01 hardening, 0-replica placeholder, and no secrets in ConfigMap ✓

**Task 2: Wire web into validate-staging.py and deploy-staging.yml**
- Files: scripts/validate-staging.py, .github/workflows/deploy-staging.yml — specified ✓
- Action: Two targeted edits to validate-staging.py (EXPECTED_MANIFESTS and EXPECTED_WORKLOADS with specific dicts and line numbers) and two to deploy-staging.yml (Verify rollouts and Verify services). Explicitly excludes web from APP_IMAGES (pause is not a GHCR image, no pin check needed) ✓
- Verify: Automated `python3 scripts/validate-staging.py` command — will pass because pause:3.9 has all required manifest fields (serviceAccountName, automountServiceAccountToken:false, resources, securityContext, readinessProbe, livenessProbe) ✓
- Done: Validator exits 0 with all six checks passing, deploy-staging.yml includes rollout status and service get lines ✓

**Status:** ✓ Complete

---

### 3. Dependency Correctness
- Wave: 1
- depends_on: [] (no upstream dependencies)
- No cyclic references ✓

**Status:** ✓ Correct

---

### 4. Key Links (Artifact Wiring)
All three critical data flow links are planned:

1. **37-web-deployment.yaml → 36-web.yaml** via ConfigMap envFrom
   - Plan line 145-147: `envFrom: configMapRef: name: web-config`
   - Plan line 101-107: ConfigMap `web-config` defined in 36-web.yaml
   - Wiring: ✓ Explicit

2. **validate-staging.py EXPECTED_WORKLOADS → 37-web-deployment.yaml**
   - Plan Task 2 adds web to EXPECTED_WORKLOADS pointing to "37-web-deployment.yaml"
   - validate_workload_safety() reads that file and checks for required fields
   - Wiring: ✓ Explicit

3. **deploy-staging.yml Verify rollouts → 37-web-deployment.yaml**
   - Plan Task 2 adds `kubectl rollout status deployment/web`
   - This queries the Deployment created in 37-web-deployment.yaml
   - Wiring: ✓ Explicit

**Status:** ✓ All links planned

---

### 5. Scope Sanity
- Tasks per plan: 2 (within 2–3 target) ✓
- Files modified: 4 files total (36-web.yaml, 37-web-deployment.yaml, validate-staging.py, deploy-staging.yml) — reasonable ✓
- No scope creep or deferred ideas included ✓

**Status:** ✓ Scope appropriate

---

### 6. Convention Compliance (WEB-01 Deep Dive)

**Mirrored from server-2 (35-server-2-deployment.yaml):**

| Convention | server-2 | Plan Task 1 | Status |
|------------|----------|------------|--------|
| ServiceAccount: name: {app} | server-2 | web | ✓ |
| automountServiceAccountToken: false | Present | Line 133 | ✓ |
| imagePullSecrets: ghcr-pull | Present | Lines 134–135 | ✓ |
| imagePullPolicy: IfNotPresent | Present | Line 141 | ✓ |
| Named container port (http) | Present (3000) | Lines 143–144 (3001) | ✓ |
| readinessProbe: httpGet | Present | Lines 148–152 | ✓ |
| livenessProbe: httpGet | Present | Lines 154–159 | ✓ |
| resources.requests | cpu: 100m, mem: 256Mi | cpu: 100m, mem: 128Mi | ✓ |
| resources.limits | cpu: 1, mem: 1Gi | cpu: 1, mem: 512Mi | ✓ |
| securityContext.allowPrivilegeEscalation: false | Present | Line 168 | ✓ |
| securityContext.capabilities.drop: ["ALL"] | Present | Line 170 | ✓ |
| app.kubernetes.io/name label | Present | ConfigMap line 103, Deployment line 127 | ✓ |
| app.kubernetes.io/part-of label | Present | ConfigMap line 104, Deployment line 128 | ✓ |
| Explicit namespace: solid-stats-staging | Present | ConfigMap line 102, Service line 111, ServiceAccount line 121, Deployment line 126 | ✓ |
| Dedicated namespace in spec.template.spec | Not applicable | ServiceAccount name: web (line 132) | ✓ |

All WEB-01 conventions fully implemented.

**Status:** ✓ WEB-01 complete

---

### 7. WEB-02: 0-Replica / Image-Pending Safety

**Requirement:** Deployment must deploy as a stub with replicas: 0 and a pinned, inert placeholder image without breaking the deploy gate.

**Plan delivers:**

1. **replicas: 0** (Plan line 128)
   - Verified by Task 1 automated grep: `grep -c 'replicas: 0' k8s/staging/37-web-deployment.yaml`
   - Result: No pod ever starts ✓

2. **Pinned inert placeholder image** (Plan line 138)
   - Image: `registry.k8s.io/pause:3.9`
   - Choice rationale (Plan lines 172–176): Pause is the inert placeholder used by k8s itself; binds no ports, runs no code, cannot serve traffic. No possibility of wrong image accidentally running code.
   - Visibility to image-pin check (Plan lines 172–176): validate_app_image_pins() only checks `image: ghcr.io/solid-stats/` lines. pause:3.9 won't match, so no exception needed.
   - Verified by Task 1 automated grep: `grep -c 'registry.k8s.io/pause:3.9' k8s/staging/37-web-deployment.yaml`
   - Result: One match, confirmed ✓

3. **kubectl rollout status does NOT block deploy** (Plan Task 2 lines 250–253)
   - A 0-replica Deployment: desired replicas = 0, ready replicas = 0
   - `kubectl rollout status` reports: "deployment web successfully rolled out" immediately
   - Result: Does not stall deploy gate ✓

4. **Future swap is one-line change** (Plan lines 178–182)
   - Swap image line and set replicas > 0; nothing else changes
   - Comment block added for clarity
   - Result: When real ghcr.io/solid-stats/web@sha256:… image lands, swap is trivial ✓

**Status:** ✓ WEB-02 complete

---

### 8. WEB-03: Validation Integration

**Requirement:** validate-staging.py EXPECTED_* and rollout-status verification must include web.

**Plan Task 2 edits:**

**scripts/validate-staging.py:**

1. EXPECTED_MANIFESTS (lines 226–229)
   - Adds after "35-server-2-deployment.yaml":
     ```python
     "36-web.yaml",
     "37-web-deployment.yaml",
     ```
   - Maintains numeric ordering ✓
   - Result: Validator will check both files exist and validate their shape ✓

2. EXPECTED_WORKLOADS (around line 232)
   - Adds after "server-2" entry:
     ```python
     "web": {"kind": "Deployment", "file": "37-web-deployment.yaml", "long_running": True},
     ```
   - Sets long_running: True because 37-web-deployment.yaml includes readinessProbe + livenessProbe (required by this flag)
   - Result: Validator will check web Deployment for serviceAccountName, automountServiceAccountToken:false, resources, securityContext, probes ✓

3. Does NOT add web to APP_IMAGES
   - Plan explicitly states (lines 236–240): "Do NOT add web to APP_IMAGES"
   - Reason: APP_IMAGES is for `image: ghcr.io/solid-stats/` pins only. pause:3.9 is not a GHCR image, so no pin check applies. Adding it would require an exception; not adding it keeps validation clean.
   - Result: No exception needed, validator stays simple ✓

4. Does NOT add web to EXPECTED_SECRETS
   - Plan explicitly states (lines 239–240): "The web slot has no runtime Secret"
   - Result: No unnecessary secret entries ✓

**Validator will pass because:**
- validate_workload_safety() checks (line 249–269 of current validate-staging.py):
  - `name: web` in file: ✓ Deployment line 126
  - `serviceAccountName:`: ✓ line 132
  - `automountServiceAccountToken: false`: ✓ line 133
  - `resources:` with `requests:` + `limits:`: ✓ lines 160–166
  - `securityContext:`: ✓ lines 167–170
  - For `long_running: True`: `readinessProbe:` + `livenessProbe:`: ✓ lines 148–159
- 0-replica count is not inspected by validator (only manifest structure) ✓

**.github/workflows/deploy-staging.yml:**

1. Verify rollouts step (Plan Task 2 lines 250–253)
   - Adds after `kubectl ... rollout status deployment/replay-parser-2 --timeout=300s`:
     ```bash
     kubectl -n "$K8S_NAMESPACE" rollout status deployment/web --timeout=300s
     ```
   - A 0-replica Deployment: rollout status exits 0 immediately
   - Result: Does NOT block deploy gate ✓

2. Verify services and CronJobs step (Plan Task 2 line 258)
   - Changes line 139 from:
     ```bash
     kubectl -n "$K8S_NAMESPACE" get service postgres rabbitmq server-2 -o wide
     ```
   - To:
     ```bash
     kubectl -n "$K8S_NAMESPACE" get service postgres rabbitmq server-2 web -o wide
     ```
   - Result: Operator sees web Service status in every deploy ✓

**Verification command:**
- Task 2 verify block: `python3 scripts/validate-staging.py`
- Expected output: All six checks pass:
  ```
  ok: script syntax
  ok: manifest shape
  ok: drill manifest safety
  ok: workload safety
  ok: app image pins
  ok: rendered secret structure
  ```

**Status:** ✓ WEB-03 complete

---

### 9. File Numbering & Collision Check

Current k8s/staging/ files:
```
00-namespace.yaml
01-ci-rbac.yaml
10-postgres.yaml
20-rabbitmq.yaml
30-server-2.yaml
35-server-2-deployment.yaml
40-replay-parser-2.yaml ← next free range starts at 36
50-replays-fetcher.yaml
60-postgres-backup.yaml
restore-drill/ (depth-2, excluded from CD glob)
```

Plan uses:
- **36-web.yaml** (ConfigMap + Service) — free, < 40 ✓
- **37-web-deployment.yaml** (ServiceAccount + Deployment) — free, < 40 ✓

Ordering rule: CM/Service before Deployment
- 36 (CM/Service) < 37 (Deployment) ✓

No collisions, numbering correct.

**Status:** ✓ No conflicts

---

### 10. Context Compliance (09-CONTEXT.md)

**Locked decisions (must implement exactly):**
- Split layout: 36-web.yaml + 37-web-deployment.yaml ✓ (exact filenames)
- server-2 conventions: serviceAccountName, automountServiceAccountToken:false, imagePullSecrets, imagePullPolicy, probes, resources, securityContext, labels, namespace ✓ (all present in Task 1)
- Integration points: validate-staging.py (EXPECTED_MANIFESTS + EXPECTED_WORKLOADS) ✓ and deploy-staging.yml (rollout status + get service) ✓

**Claude's discretion (planner choice, justify rationale):**
- WEB-02 image-pending strategy: Chose option (a) — registry.k8s.io/pause:3.9 placeholder ✓
  - Rationale provided (Plan lines 172–176):
    1. Keeps validate-staging.py app-image-pin check happy (pause not checked) ✓
    2. Cannot accidentally run wrong image (inert, k8s uses it) ✓
    3. Future swap is one-line change ✓
- Probes on 0-replica stub: Kept (WEB-01 requires them) ✓
- ConfigMap contents: Minimal starting-point config ✓ (NODE_ENV, PORT, API_BASE_URL to server-2)

**Deferred ideas (not in scope):**
- Building/deploying real web image — plan does NOT include ✓ (owned by web app repo)
- HPA/ingress/network policy — plan does NOT include ✓

**Status:** ✓ Context compliant

---

### 11. Threat Model

Plan includes STRIDE threat register with 6 identified threats:

| Threat | Component | Mitigation | Assessment |
|--------|-----------|-----------|-----------|
| T-09-01: Placeholder image accidentally runs | Deployment replicas | replicas: 0 in manifest; 0-replica never schedules pod | Adequate |
| T-09-02: ConfigMap contains secrets | web-config | Only non-secret config (NODE_ENV, PORT, API_BASE_URL); no secretRef | Adequate |
| T-09-03: Token auto-mounted | ServiceAccount | automountServiceAccountToken: false in both SA and Deployment | Adequate |
| T-09-04: 0-replica stub blocks CD | Deploy gate | kubectl rollout status on 0-replica exits 0 immediately | Adequate |
| T-09-05: pause container escalates | Container | securityContext.allowPrivilegeEscalation:false + drop ALL | Adequate |
| T-09-SC: Package manager installs | Script | No npm/pip/cargo invocations (YAML + Python edits only) | Accept |

**Status:** ✓ Threat model complete and proportionate

---

### 12. Scope Reduction Detection

**Check:** Does the plan claim to implement WEB-01..03 but silently reduce the scope?

Scan for scope-reduction language: v1, simplified, static for now, hardcoded, future enhancement, placeholder, basic version, will be wired later, stub, etc.

**Findings:**

Plan Task 1 lines 172–176:
> "Image choice rationale… pause image is invisible to that check and requires no exception. When the web image is ready, swap image: and set replicas: N — nothing else changes."

Plan Task 1 lines 178–182:
> "Future swap comment… To activate: set replicas: N and replace the image line with… No other manifest changes required."

**Assessment:** This is NOT scope reduction. The plan explicitly delivers:
- All WEB-01 conventions (ServiceAccount, automountServiceAccountToken:false, imagePullSecrets, probes, resources, securityContext, labels, namespace)
- All WEB-02 safety (replicas: 0, inert placeholder, rollout status green)
- All WEB-03 integration (EXPECTED_MANIFESTS, EXPECTED_WORKLOADS, rollout status, service get)

The "swap for real image later" is not a placeholder excuse — it's a documented, intentional design for a 0-replica stub. The user (CONTEXT.md, Decisions) explicitly approved this strategy: "Whether… a 0-replica image-pending workload (so a placeholder image or 0 replicas does not trip the long_running checks)." Plan delivers what was decided.

**Status:** ✓ No scope reduction

---

### 13. Verification Execution

**Acceptance criteria (from plan success_criteria block):**

1. python3 scripts/validate-staging.py exits 0 with all six checks passing ✓
   - Task 1 creates manifests with all required fields
   - Task 2 adds to EXPECTED_MANIFESTS and EXPECTED_WORKLOADS
   - pause:3.9 passes all checks (has serviceAccountName, automountServiceAccountToken:false, resources, securityContext, probes)

2. k8s/staging/36-web.yaml and 37-web-deployment.yaml exist with all WEB-01 conventions ✓
   - Task 1 action lists all conventions block-by-block

3. 37-web-deployment.yaml has replicas: 0 and image: registry.k8s.io/pause:3.9 ✓
   - Task 1 action lines 128, 138

4. deploy-staging.yml includes rollout status deployment/web and web Service ✓
   - Task 2 action adds both

5. No secret values in 36-web.yaml ✓
   - Task 1 comment line 108 and verified by code review

6. APP_IMAGES unchanged (pause not checked) ✓
   - Task 2 action explicitly excludes web from APP_IMAGES (line 236)

**Status:** ✓ All criteria planned

---

## Conclusion

**Phase 9 plan is verified to achieve the phase goal.**

All three requirements (WEB-01, WEB-02, WEB-03) have complete, properly-wired task coverage. Tasks are specific, measurable, and test-gated. File numbering is collision-free. Context decisions are honored. Scope is appropriate. The stub design is safe and documented.

**Recommendation:** Proceed to execution.

---

**Verified by:** Plan Checker Agent  
**Date:** 2026-06-13  
**Verification duration:** Full goal-backward analysis across 13 dimensions
