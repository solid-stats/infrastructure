# Codebase Concerns

**Analysis Date:** 2026-06-13

## Tech Debt

### StorageClass Not Expandable

**Issue:** `local-path` StorageClass has `allowVolumeExpansion: false` — PVC sizes are one-shot.

**Files:** k3s cluster configuration (not in this repo, but manifests depend on it)

**Impact:** Once PostgreSQL `postgres-data` (20Gi) or RabbitMQ `rabbitmq-data` (5Gi) PVCs fill, they cannot be expanded without manual intervention (delete/recreate), risking data loss or operational outage.

**Fix approach:** 
- Enable `allowVolumeExpansion: true` on `local-path` StorageClass (requires k3s cluster config change — operator-level).
- Add monitoring/alerting for PVC utilization to catch fills before they occur.
- Document manual PVC resize procedure for emergency use if cluster-level expansion is not enabled.

---

## Known Bugs

### Web Deployment Rollout Blocker

**Bug description:** CD workflow at `.github/workflows/deploy-staging.yml:140` attempts `kubectl rollout status deployment/web` but web is deployed at 0 replicas (stub with `registry.k8s.io/pause:3.9` placeholder image).

**Symptoms:** Deploy workflow hangs or fails waiting for web rollout to complete; the pause container never transitions to ready because probes target port 3001 which the pause image does not serve.

**Files:** 
- `.github/workflows/deploy-staging.yml:140` (rollout gate)
- `k8s/staging/37-web-deployment.yaml:19-27` (0 replicas + pause image)

**Trigger:** Running deploy workflow on master branch or via `workflow_dispatch` after manifest push.

**Workaround:** Web deployment currently has `replicas: 0`, so the rollout gate has a timeout. The manifest explicitly warns (line 23): "WARNING: raising replicas while the image is still registry.k8s.io/pause will CrashLoop ... and the CD `rollout status deployment/web --timeout=300s` gate will block then FAIL the deploy." This will become a real deploy blocker once a real web image is pushed and replicas > 0.

**Fix approach:** Replace the stub logic in the workflow. Option A: skip web in rollout gate until web is activated (add `! -name "37-web-deployment.yaml"` filter). Option B: add a conditional gate that only checks web if `replicas > 0`. Document the activation process clearly: both image AND replicas must be updated atomically in a single commit/PR.

---

## Security Considerations

### No NetworkPolicy Isolation

**Area:** Kubernetes network segmentation

**Risk:** All pods in `solid-stats-staging` namespace can communicate with each other without restriction. Workloads can reach PostgreSQL and RabbitMQ directly; a compromised parser pod or fetcher job could exfiltrate credentials or directly manipulate the database.

**Files:** 
- `k8s/staging/` (no NetworkPolicy manifests present)
- `docs/staging.md:36-43` (documents as explicit exception pending CNI verification)

**Current mitigation:** 
- Single-node private k3s cluster behind WireGuard tunnel (network isolation at VPS level).
- No external ingress controller (public edge is host nginx, out-of-cluster).
- Secrets stored in Kubernetes Secrets and GitHub environment (not in git).

**Recommendations:** 
- v2.x and beyond: add tested NetworkPolicy manifests (e.g., deny-all default, allow only required paths: server-2 ↔ postgres, replays-fetcher ↔ postgres+s3, replay-parser-2 ↔ rabbitmq+s3, etc.).
- Verify k3s Flannel CNI enforces NetworkPolicy (default k3s may have relaxed CNI).
- Document the chosen CNI configuration if NetworkPolicy is deferred further.

### Postgres Credentials in PostgreSQL Secret

**Area:** Secret visibility in manifests

**Risk:** `postgres-auth` Secret is created during deploy and referenced in plaintext in manifests and backup Job. The actual password value is stored only in GitHub secrets, so secrets do not escape to git — but live Kubernetes Secrets are readable by any pod in the namespace (unless RBAC/NetworkPolicy blocks it).

**Files:**
- `scripts/render-staging-secrets.py:38-40` (renders postgres-auth)
- `k8s/staging/60-postgres-backup.yaml:104-108` (references postgres-auth)

**Current mitigation:** 
- Secrets come from GitHub environment, not committed to git.
- `secretKeyRef` in manifests only (not hardcoded values).
- RBAC: `server-account`, `postgres-backup`, etc. have explicit ServiceAccounts; no default SA usage.

**Recommendations:** 
- No action needed for v1 (security posture is adequate for staging + private cluster).
- v2 production cutover: audit RBAC to prevent cross-workload Secret reads.
- Consider external secrets operator (ESO) for vault integration if production secrets proliferate.

---

## Performance Bottlenecks

### Resource Limits Heavily Overcommitted (175% CPU, 112% Memory)

**Problem:** Steady-state resource **limits** sum to 7000m CPU and 9216Mi memory, exceeding the 4 vCPU (4000m) and 8 GB (8192Mi) node capacity. Requests are reasonable (1100m CPU, 2304Mi memory = 27.5% / 28.1% utilization), but limit overcommit means any workload spike risks eviction or OOMKill.

**Files:**
- `k8s/staging/10-postgres.yaml:75-81` (postgres: 250m req / 1000m limit)
- `k8s/staging/20-rabbitmq.yaml:102-108` (rabbitmq: 250m req / 1000m limit)
- `k8s/staging/35-server-2-deployment.yaml:72-78` (server-2: 100m req / 1000m limit)
- `k8s/staging/40-replay-parser-2.yaml:80-86` (replay-parser-2: 2× 250m req / 2000m limit = 500m / 4000m)

**Current state from memory:**
- Node: 4 vCPU, 8 GB RAM, NO SWAP
- Actual usage: ~93% CPU, ~77% memory
- Limits: 7000m CPU (175% of node), 9216Mi memory (112% of node)

**Impact:** 
- Any burst (parser spike, backup job overlap) will trigger evictions.
- Incoming observability stack (prometheus, grafana, loki) in v3.0 cannot be scheduled without further squeezing.
- OOMKill of postgres/rabbitmq can cause data loss or corruption.
- No recovery from transient spikes — restarted pod must find room again.

**Improvement path:**
1. Reduce limits to match node capacity more closely: e.g., postgres 512Mi req / 1500Mi limit, parser 250m req / 800m limit.
2. Disable memory overcommit in kubelet (`--enforce-node-allocatable=pods` + `--system-reserved`).
3. Add swap to the VPS (if Timeweb allows) to cushion brief overages (not a long-term solution).
4. Plan v3.0 observability on a separate node or scale the cluster.

---

## Fragile Areas

### Web Deployment Stub State

**Files:** `k8s/staging/37-web-deployment.yaml`

**Why fragile:** The deployment uses a placeholder `registry.k8s.io/pause:3.9` image at 0 replicas. The comments (lines 19-26) mandate that BOTH `image` AND `replicas` be changed atomically: changing replicas without changing the image will cause the pause container to fail its probes (targeting port 3001, which pause does not serve) and enter CrashLoop. The CD workflow will then hang or timeout waiting for rollout. This is a footgun for future web image activation.

**Safe modification:** 
- Update BOTH lines in a single commit:
  1. Replace `image: registry.k8s.io/pause:3.9` with the actual web image SHA.
  2. Set `replicas: N` where N > 0.
- Run `python3 scripts/validate-staging.py` locally to confirm structure is correct.
- Open a PR; the dry-run will verify `kubectl apply --dry-run=server`.

**Test coverage:** The stub itself has no test; validation in `scripts/validate-staging.py` checks that the manifest exists and is valid YAML, but does not enforce the "both or neither" atomicity rule. Future work should add a CI gate to reject PRs that change replicas without updating the image (or vice versa).

### Postgres and RabbitMQ StatefulSets Skip Pod SecurityContext

**Files:**
- `k8s/staging/10-postgres.yaml` (no pod or container securityContext)
- `k8s/staging/20-rabbitmq.yaml` (no pod or container securityContext)

**Why fragile:** These stateful services store persistent data on PVCs and require specific UID/GID ownership. Forcing a strict securityContext (e.g., `runAsUser: 999`, `runAsNonRoot: true`) on pre-existing PVC data that was initialized with the default postgres:17-alpine and rabbitmq:4-management UID/GID can cause permission errors or startup failures. The restore-drill Job shows the correct pattern (`runAsUser: 70`, `fsGroup: 70` to match postgres user), but live postgres/rabbitmq do not have equivalent settings.

**Safe modification:** 
- Perform isolation test: spin up postgres/rabbitmq in a test namespace with tighter securityContext settings and verify startup + data write.
- Update manifests only after confirming the PVC data is compatible.
- If upgrading postgres/rabbitmq images, rebuild PVCs in an isolated environment first.

**Test coverage:** None. The restore-drill validates that restore works, but does not test postgres/rabbitmq pod hardening.

### Restore Drill Isolation (DRILL-01)

**Files:** `k8s/staging/restore-drill/70-restore-drill.yaml:158-163`

**Why fragile:** The drill explicitly checks that the PGHOST is localhost or 127.0.0.1 (lines 159-163) to prevent accidental restore into the live postgres Service. If an environment variable or inherited config injects a different host, the check catches it — but the check relies on shell string comparison, not Kubernetes validation. A malformed env var or typo could slip through if the logic is accidentally weakened.

**Safe modification:** Keep the safety barrier visible. If future work refactors the drill, preserve this check. Prefer explicit deny-by-default over implicit allow.

### RabbitMQ Init Container for Erlang Cookie

**Files:** `k8s/staging/20-rabbitmq.yaml:51-72`

**Why fragile:** RabbitMQ on the live PVC refuses to boot if `.erlang.cookie` has wrong permissions. The init container (lines 51-72) is a workaround: it repairs ownership and mode on first boot. If the PVC already has a cookie file from a previous run, this works. If the file is deleted or PVC is corrupted, the init container creates no fallback and rabbitmq-server startup may still fail with a cryptic permission error.

**Safe modification:** This is a necessary workaround given the RabbitMQ image constraints. Preserve it. If RabbitMQ image is upgraded, test the init container logic against the new image version.

---

## Scaling Limits

### Single-Node, Single-Replica Cluster (Except Parser)

**Resource/System:** High availability and fault tolerance

**Current capacity:** 
- 4 vCPU, 8 GB RAM, 31 GB disk free on 79 GB total
- Single k3s node
- All workloads at 1 replica (except replay-parser-2 at 2 replicas)

**Limit:** Node loss = full cluster outage. No HA failover. PVC data loss if node storage is lost.

**Scaling path:**
1. Add a second node to the Timeweb VPS cluster (requires new VPS or multi-node k3s setup on same infrastructure — out of scope for this project).
2. Add replication: postgres replicas using streaming replication, rabbitmq clustering, multi-replica server-2.
3. Add persistent backup recovery: already in place (`postgres-backup` CronJob + restore-drill) — enables recovery on new infrastructure, not fast failover.

**Note:** v1 explicitly targets staging only and defers production cutover to v2. Single-node is acceptable for staging.

---

## Dependencies at Risk

### Python 3 Import + stdlib Only (No Dependencies)

**Risk:** Low. Scripts in `scripts/` use only Python stdlib (json, pathlib, importlib, subprocess). `render-staging-secrets.py` and `validate-staging.py` have no external dependencies, so no supply-chain risk.

**Impact:** None.

---

## Missing Critical Features

### No Automated Scheduling for Restore Drill

**Feature gap:** The restore drill (`scripts/restore-drill.sh`) is on-demand only. It must be manually triggered after every backup or at intervals. There is no CronJob to run it automatically.

**Problem:** Backups can silently degrade (e.g., pg_dump succeeds but the dump is corrupt on disk). The drill is the only validation that a backup is actually restoreable. Without automated scheduling, a restore failure may go undetected until a real failure requires recovery.

**Blocks:** Production cutover (v2.x) cannot proceed without high confidence in backup integrity.

**Fix approach:** v2.x deferred work — add `DRILL-05` (automated scheduling + alerting): schedule the drill daily post-backup, capture PASS/FAIL evidence, alert on FAIL, integrate into observability stack.

### No Monitoring / Observability Stack

**Feature gap:** No prometheus, alerting, grafana, loki, or centralized logging. Workload health is invisible except via manual `kubectl get pods`, `kubectl logs`, and S3 object checks.

**Problem:** Slow degradation (disk fill, memory creep, leak) goes unnoticed. Full run progress is opaque. Backup success/failure requires manual log inspection.

**Blocks:** v3.0 observability initiative (currently starting). Inline with the capacity bottleneck: observability stack will add prometheus (~200m CPU, 1Gi mem), grafana (~100m CPU, 256Mi mem), loki (~200m CPU, 512Mi mem), etc. — overhead of ~500m CPU / 2Gi mem, pushing the cluster to its limits.

**Fix approach:** v3.0 work — add observability (may require second node or aggressive limit reduction in base workloads).

---

## Test Coverage Gaps

### Web Deployment Activation Not Tested

**Untested area:** The web deployment stub activation (swapping image + setting replicas > 0) has no test covering the atomicity rule.

**Files:** `k8s/staging/37-web-deployment.yaml`, `scripts/validate-staging.py`

**Risk:** A developer may accidentally merge a PR that raises `replicas: 1` without changing the image, causing a deploy-time CrashLoop and workflow timeout. The current validation (`validate-staging.py`) only checks YAML syntax and manifest presence.

**Priority:** Medium. This is a manual footgun, not a silent data loss, but it will block the deploy workflow.

**Fix:** Add a validation rule: if `web` deployment `replicas > 0`, then `image` must not be `registry.k8s.io/pause`. This can be added to `scripts/validate-staging.py` in a future phase.

### StatefulSet SecurityContext Hardening Not Tested

**Untested area:** PostgreSQL and RabbitMQ do not have pod/container `securityContext` applied (documented exception in `docs/staging.md:49-56`). There is no test verifying that adding `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, or other constraints will not break startup.

**Files:** `k8s/staging/10-postgres.yaml`, `k8s/staging/20-rabbitmq.yaml`

**Risk:** Blindly adding securityContext restrictions may cause mount permission errors or startup failures on the live PVC. Upgrading postgres/rabbitmq images may change UID/GID expectations.

**Priority:** Medium. This is a v2.x hardening task and should be tested in isolation before applying to the live manifests.

### Backup + Restore Validation Edge Cases Not Covered

**Untested area:** The backup Job (`postgres-backup` CronJob) validates the dump with `pg_restore --list` before uploading. The restore-drill validates restore and row counts. But edge cases are not tested:
- Backup dump with no tables (would pass `pg_restore --list` but fail assertions in the drill).
- Partial restore (some tables restored, others fail — the drill query might still return a count > 0 but miss data).
- S3 upload failure silent (aws-cli succeeds but object is truncated or corrupted).

**Files:**
- `k8s/staging/60-postgres-backup.yaml:59-94` (backup logic)
- `k8s/staging/restore-drill/70-restore-drill.yaml:222-249` (assertions)

**Risk:** Low for current steady state (backups and restores are working). Moderate risk if database schema changes (new tables added, old ones dropped) — assertions may pass but miss a structural change.

**Priority:** Low for v1 (operational runbook covers backup gate verification manually). v2.x can add structured backup validation (e.g., expected table list, row count tolerance).

---

## Deployment Risk

### Web Rollout Gate Timeout in CI Workflow

**Issue:** The deploy workflow (`.github/workflows/deploy-staging.yml:140`) runs `kubectl rollout status deployment/web --timeout=300s` unconditionally.

**Current state:** Web is at 0 replicas with pause image, so the rollout gate has no pods to wait for. The timeout is not triggered because Kubernetes considers a 0-replica deployment "rolled out" (no desired pods means no pending pods).

**Risk:** Once a real web image is deployed and replicas > 0, the rollout gate will block deployment until the pod is ready. If the image fails to pull or crashes, the deploy workflow will timeout at 300s and fail the entire deploy. This is not a data loss risk, but it will require manual intervention.

**Fix approach:** Separate web from the rollout gate (add a conditional in the workflow, or skip web in the gate until it is activated), OR add the atomicity validation described above to prevent the footgun.

---

## Deferred v2.x Items

The following items are explicitly noted in the codebase as deferred:

1. **DRILL-05:** Automated restore drill scheduling and alerting (currently on-demand only).
2. **WEB-02:** Web deployment real image activation (requires atomic image + replicas update).
3. **Production cutover:** v2.x task. Diff readiness, cutover runbook, and production NetworkPolicy/hardening.
4. **NetworkPolicy enforcement:** v2.x hardening task. Verify k3s CNI, add NetworkPolicy manifests.
5. **Observability stack (v3.0):** prometheus, grafana, loki, alerting. Requires capacity plan (second node or aggressive limit reduction).

---

*Concerns audit: 2026-06-13*
