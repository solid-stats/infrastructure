---
phase: 06-kubectl-native-cd
verified: 2026-06-12T00:00:00Z
live_verified: 2026-06-13T04:08:00Z
status: verified
score: 6/6 must-have groups verified
overrides_applied: 0
human_verification:
  - test: "Trigger the deploy workflow from a real GitHub Actions runner (PR for validate+dry-run, or a master push / workflow_dispatch for full deploy)."
    expected: "wg-tunnel-up.sh completes the WireGuard handshake within the timeout, kubeconfig-setup.sh reports a non-anonymous ci-deployer identity (not system:anonymous), dry-run apply succeeds, and on master the four workloads reach rolled-out status."
    why_human: "The WireGuard handshake against the live VPS, 6443 reachability through the tunnel, SA-token authentication, and the real kubectl apply / rollout can only be exercised by an actual CI run against the unreachable staging cluster. This environment is VPN-isolated from the cluster and must not contact it."
    resolved: "2026-06-13 — RESOLVED. Cluster became reachable from the operator workstation; operator bootstrapped ci-deployer RBAC + a dedicated CI WireGuard peer (10.8.0.3) and set the staging-env secrets. PR #1 dry-run job went green (WG handshake from a real runner + ci-deployer SA-token auth + server-side apply of every manifest); the master-push deploy job went green (render+apply secrets, apply manifests, rollout of postgres/rabbitmq/server-2/replay-parser-2/web, services + CronJobs verified). Six latent script/workflow bugs — never caught because the path had only been offline-verified — were found and fixed during the run (see Live CI Verification section)."
warnings:
  - file: "docs/staging.md"
    issue: "Operator-facing doc still lists CD_SSH_PRIVATE_KEY/HOST/PORT/USER as required GitHub secrets (lines 66-69) and instructs deploy via the deleted ./scripts/deploy-staging.sh (lines 132, 145). It does not list the new WG_PRIVATE_KEY / WG_PEER_PUBLIC_KEY / WG_ENDPOINT / K8S_TOKEN / K8S_CA_CERT secrets. Documentation drift only — CI does not read this file, so it does not break the CD path. Outside the declared must-haves of all four plans (none scope docs/staging.md). README.md and AGENTS.md also still mention scripts/deploy-staging.sh."
    severity: warning
    recommendation: "Follow-up doc cleanup: replace CD_SSH_* secrets with WG_*/K8S_* and remove ./scripts/deploy-staging.sh references in docs/staging.md, README.md, AGENTS.md."
---

# Phase 06: kubectl-native CD Verification Report

**Phase Goal:** CI deploys staging by running `kubectl` on the runner over a WireGuard tunnel as a namespace-scoped ServiceAccount, with all SSH transport removed and the operator-bootstrap boundary documented.
**Verified:** 2026-06-12 (code) · 2026-06-13 (live CI)
**Status:** verified — live CD run confirmed end-to-end on the staging cluster
**Re-verification:** 2026-06-13 — the human-verification item was executed and passed; 6 latent bugs fixed

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | Master push deploys via `kubectl apply` over a verified WG tunnel, no SSH/scp; PR runs validate + server-side dry-run only | ✓ VERIFIED | `deploy-staging.yml`: deploy job gated `if: github.event_name == 'push' && github.ref == 'refs/heads/master' || workflow_dispatch` (L77); dry-run job has no `if` so runs on PRs (L39-70); dry-run uses `--dry-run=server` (L70). No `ssh`/`scp`/`scp`/`ssh-keyscan` in workflow. |
| 2 | CI authenticates as the namespace-scoped SA via long-lived token Secret, `auth whoami` not `system:anonymous` | ✓ VERIFIED | `kubeconfig-setup.sh` builds kubeconfig from `K8S_TOKEN`+`K8S_CA_CERT` (L47-65), runs `kubectl auth whoami` and exits 1 on `system:anonymous` (L69-73); token Secret is `kubernetes.io/service-account-token` in `01-ci-rbac.yaml` (L18-28). |
| 3 | Deploy aborts before any kubectl if WG handshake incomplete; 6443 only through tunnel | ✓ VERIFIED | `wg-tunnel-up.sh` polls `wg show ... latest-handshakes`, exits 1 on timeout (L74-89), then TCP-checks `10.8.0.1:6443` and exits 1 if unreachable (L91-96). Called before kubeconfig/kubectl in both dry-run (L52-63) and deploy (L86-97) jobs. |
| 4 | SA can apply + rollout-status every workload in-namespace, nothing cluster-scoped; namespace + RBAC bootstrapped once by operator via runbook; CI never creates namespace | ✓ VERIFIED | `01-ci-rbac.yaml` Role grants namespace-scoped verbs on apps/batch/core resources + watch on pods, no cluster-scoped rules (L40-60); RoleBinding binds SA (L62-77). `docs/operator-bootstrap.md` is a 6-step runbook; states "CI never creates the namespace" (L3, L25-26). Deploy/dry-run globs exclude `01-ci-rbac.yaml` (L69, L124). |
| 5 | All `CD_SSH_*` secrets and SSH code paths removed, single concurrent deploy, SA-token rotation runbook (owner, cadence, paired WG rotation) documented | ✓ VERIFIED (code) / ⚠️ doc drift | No `CD_SSH_*`/`ssh`/`scp` in workflow (only legit app secrets `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_*`). `concurrency.group: infrastructure-staging-deploy`, `cancel-in-progress: false` (L10-12). `docs/sa-token-rotation.md` has owner, quarterly cadence, both rotation procedures, same-window rule. **Warning:** `docs/staging.md` still documents `CD_SSH_*` secrets (out of must-have scope). |

**Score:** 5/5 ROADMAP success criteria verified (criterion 5 has a non-blocking documentation-drift warning).

### Per-Must-Have Verification (all four plans)

| # | Must-have | Plan | Status | Evidence |
| - | --------- | ---- | ------ | -------- |
| 1 | `01-ci-rbac.yaml`: SA `ci-deployer`, token Secret, namespace Role, RoleBinding in `solid-stats-staging` | 06-01 | ✓ VERIFIED | `k8s/staging/01-ci-rbac.yaml` L6-77 |
| 2 | Role grants apply verbs on Deployments/StatefulSets/CronJobs/Services/ConfigMaps/Secrets/PVCs/ServiceAccounts + get/list/watch on Pods; nothing cluster-scoped | 06-01 | ✓ VERIFIED | `01-ci-rbac.yaml` L40-60 (watch on services/cm/secrets/pvc not granted — not needed for apply; pods have watch for rollout) |
| 3 | `docs/operator-bootstrap.md` step-by-step runbook (namespace, apply RBAC, SAN patch, verify can-i, extract token+CA) | 06-01 | ✓ VERIFIED | `docs/operator-bootstrap.md` L17-150 (6 steps) |
| 4 | Runbook states CI never creates namespace; operator applies `01-ci-rbac.yaml` once | 06-01 | ✓ VERIFIED | `docs/operator-bootstrap.md` L3, L25-26, L34-37 |
| 5 | `docs/sa-token-rotation.md`: owner, quarterly cadence, SA-token + WG rotation, same-window note | 06-02 | ✓ VERIFIED | `docs/sa-token-rotation.md` L9-11, L17-19, Steps 1-2 |
| 6 | Rotation doc: update GitHub secrets before VPS side to avoid mid-rotation failure | 06-02 | ✓ VERIFIED | `docs/sa-token-rotation.md` L9-11, L20, L57-60, L80-87 |
| 7 | Rotation doc: verification steps confirm new token+key accepted before revoking old | 06-02 | ✓ VERIFIED | `docs/sa-token-rotation.md` Step 3 (L115-125), Troubleshooting L135 |
| 8 | `wg-tunnel-up.sh` brings up wg0, polls handshake, exits 1 on timeout (default 10s) | 06-03 | ✓ VERIFIED | `wg-tunnel-up.sh` L22, L72-89 |
| 9 | `wg-tunnel-up.sh` verifies `10.8.0.1:6443` TCP-reachable before returning 0 | 06-03 | ✓ VERIFIED | `wg-tunnel-up.sh` L91-99 |
| 10 | `kubeconfig-setup.sh` builds kubeconfig to `https://10.8.0.1:6443` from token+CA, verifies non-anonymous, exits 1 on `system:anonymous` | 06-03 | ✓ VERIFIED | `kubeconfig-setup.sh` L28, L47-73 |
| 11 | Both scripts follow conventions (`#!/usr/bin/env bash`, `set -euo pipefail`, exit 64 missing config, mktemp+trap) | 06-03 | ✓ VERIFIED | wg L1-2, L27-38 (exit 64); kubeconfig L1-2, L18-25 (exit 64), L41-42 (mktemp+trap); both pass `bash -n` |
| 12 | `deploy-staging.yml` concurrency `infrastructure-staging-deploy`, `cancel-in-progress: false` | 06-04 | ✓ VERIFIED | `deploy-staging.yml` L10-12 |
| 13 | PR runs validate + dry-run only (`--dry-run=server`); no deploy on PR | 06-04 | ✓ VERIFIED | `deploy-staging.yml` L39-70, L77 (deploy `if` gates out PRs) |
| 14 | master push runs validate + dry-run + deploy; deploy calls wg + kubeconfig + apply (excl `01-ci-rbac.yaml`) + rollout for 4 workloads | 06-04 | ✓ VERIFIED | `deploy-staging.yml` L72-134 |
| 15 | No `CD_SSH_*` and no ssh/ssh-keyscan/scp steps in workflow | 06-04 | ✓ VERIFIED | grep: none found (only app `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_*` secrets, excluded by spec) |
| 16 | `scripts/deploy-staging.sh` deleted | 06-04 | ✓ VERIFIED | File absent; deleted in commit `5379709`; not referenced by `validate-staging.py` |
| 17 | dry-run + deploy globs both exclude `01-ci-rbac.yaml` | 06-04 | ✓ VERIFIED | `deploy-staging.yml` L69 (`! -name '01-ci-rbac.yaml'`), L124 (same) |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `.github/workflows/deploy-staging.yml` | 3-job validate/dry-run/deploy, WG+kubectl, no SSH | ✓ VERIFIED | 141 lines, all jobs and gating present |
| `scripts/wg-tunnel-up.sh` | Handshake gate, fail-closed | ✓ VERIFIED | 99 lines, substantive, `bash -n` OK |
| `scripts/kubeconfig-setup.sh` | kubeconfig from token+CA, non-anonymous check | ✓ VERIFIED | 77 lines, no `--insecure-skip-tls-verify`, `bash -n` OK |
| `k8s/staging/01-ci-rbac.yaml` | SA + token Secret + Role + RoleBinding | ✓ VERIFIED | 77 lines, namespace-scoped only |
| `docs/operator-bootstrap.md` | One-time bootstrap runbook | ✓ VERIFIED | 196 lines, 6 steps + troubleshooting |
| `docs/sa-token-rotation.md` | SA-token + WG rotation runbook | ✓ VERIFIED | 141 lines, owner/cadence/same-window |
| `scripts/deploy-staging.sh` | DELETED | ✓ VERIFIED | Absent (commit 5379709) |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| deploy-staging.yml (dry-run + deploy jobs) | scripts/wg-tunnel-up.sh | `run: bash scripts/wg-tunnel-up.sh` before kubectl | ✓ WIRED (L57, L91) |
| deploy-staging.yml (dry-run + deploy jobs) | scripts/kubeconfig-setup.sh | `run: bash scripts/kubeconfig-setup.sh` after WG up | ✓ WIRED (L63, L97) |
| 01-ci-rbac.yaml (Secret ci-deployer-token) | docs/operator-bootstrap.md (extract step) | `kubectl get secret ci-deployer-token -o jsonpath` | ✓ WIRED (bootstrap L81-83) |
| 01-ci-rbac.yaml (Role) | docs/operator-bootstrap.md (verify step) | `kubectl auth can-i --list --as=...:ci-deployer` | ✓ WIRED (bootstrap L55-57) |
| docs/sa-token-rotation.md | docs/operator-bootstrap.md | cross-reference for initial setup | ✓ WIRED (rotation L6-7, L139-140) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Validator (what CI validate job runs) exits 0 | `timeout 60 python3 scripts/validate-staging.py` | exit 0; kubectl dry-run self-skips (cluster unreachable) | ✓ PASS |
| Helper scripts are syntactically valid bash | `bash -n scripts/wg-tunnel-up.sh && bash -n scripts/kubeconfig-setup.sh` | both OK | ✓ PASS |
| No `CD_SSH_*` / ssh / scp transport in workflow | grep | only app `REPLAYS_FETCHER_REPLAY_SOURCE_SSH_*` (excluded) | ✓ PASS |
| `scripts/deploy-staging.sh` removed | `ls`, git diff-filter=D | absent, deleted in 5379709 | ✓ PASS |
| Live WG handshake + SA auth + real deploy | PR #1 dry-run job + master-push deploy job on real GitHub runners | dry-run green (handshake + SA auth + server-side apply); master deploy green (5 workloads rolled out) | ✓ PASS (2026-06-13) |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| CD-01 | Operator deploys staging via kubectl over WG tunnel, no SSH/scp | ✓ SATISFIED | workflow + helper scripts; SSH path deleted |
| CD-06 | master deploys automatically; PRs run validate + dry-run without deploying | ✓ SATISFIED | deploy job `if` gate (L77); dry-run on all events |
| CD-07 | All `CD_SSH_*` secrets and SSH code paths removed | ✓ SATISFIED (code) | none in workflow; `deploy-staging.sh` deleted. ⚠️ stale doc mention in `docs/staging.md` (non-code, warning) |
| CD-08 | Only one deploy at a time (concurrency lock) | ✓ SATISFIED | `concurrency.group` + `cancel-in-progress: false` (L10-12) |
| CD-09 | Long-lived SA-token rotation runbook (owner, cadence, paired WG rotation) | ✓ SATISFIED | `docs/sa-token-rotation.md` |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (modified phase files) | — | TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER | — | None found |
| docs/staging.md | 66-69 | Lists removed `CD_SSH_*` as required secrets; omits new WG_*/K8S_* secrets | ⚠️ Warning | Doc drift; operator following this doc would set wrong secrets. CI unaffected. Out of declared must-have scope. |
| docs/staging.md | 132, 145 | Points to deleted `./scripts/deploy-staging.sh` | ⚠️ Warning | Doc drift; broken instruction. CI unaffected. |
| README.md / AGENTS.md | 22/57, 114 | Mention deleted `scripts/deploy-staging.sh` | ℹ️ Info | Doc drift, non-load-bearing. |

### Live CI Verification (2026-06-13) — RESOLVED

The deferred human-verification item was executed end-to-end. The staging cluster became reachable from the operator workstation, so the operator could bootstrap the one-time prerequisites and drive the pipeline from real GitHub runners.

**Operator prerequisites (out-of-band, one-time):**
- Applied `k8s/staging/01-ci-rbac.yaml` → `ci-deployer` SA + token Secret + namespace Role/RoleBinding (impersonated `auth can-i` → yes for deployments/secrets/pods).
- Added a **dedicated** CI WireGuard peer at `10.8.0.3/32` on the staging VPS (distinct from the operator laptop's `10.8.0.2`), now persisted in `/etc/wireguard/wg0.conf` so it survives reboot.
- Set the `staging` environment secrets: `WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT` (`89.223.124.200:51820`), `K8S_TOKEN`, `K8S_CA_CERT`, `GHCR_USERNAME`, `GHCR_TOKEN`.

**Result:**
- **PR #1** dry-run job → green: WireGuard handshake from a real runner, `ci-deployer` SA-token auth (non-anonymous), `kubectl apply --dry-run=server` of every `k8s/staging/*.yaml` (excl. `00-namespace.yaml` + `01-ci-rbac.yaml`). Deploy job correctly skipped on PR.
- **master push** deploy job → green: render + apply staging secrets, apply manifests, `rollout status` for **postgres, rabbitmq, server-2, replay-parser-2, web** (web is the Phase 9 0-replica slot, created), services + CronJobs verified.

**Six latent bugs found and fixed during the run** (the path had only ever been offline-verified, never run against a live cluster):

| # | Bug | Fix | Commit |
| - | --- | --- | ------ |
| 1 | `wg set ... private-key <(printf …)` → `fopen: No such file` — `sudo` closes inherited FDs (`closefrom=3`), so the process-substitution `/dev/fd/NN` path vanishes | feed the key via `/dev/stdin` (FD 0 survives sudo; key still off-disk) | `f7c44e8` |
| 2 | Handshake never initiated (WireGuard is lazy — no traffic, no init) → 10s timeout | `persistent-keepalive 25` on the peer + prime a packet to `10.8.0.1:6443` inside the wait loop | `3841680` |
| 3 | No kernel route to the tunnel IP — raw `wg set` adds no route, and the `/32` local addr adds no subnet route (handshake still succeeds endpoint-to-endpoint) | `ip route replace <allowed-ip> dev wg0` after link-up | `bf155d3` |
| 4 | `xargs kubectl apply … -f` appended all filenames after one `-f` → "Unexpected args" | prefix each path with `-f ` via `sed` so every manifest gets its own flag (both jobs) | `091bcce` |
| 5 | kubeconfig stored the CA **path**, but the temp CA file is rm'd by the script's EXIT trap → later steps `no such file` (in-script `auth whoami` passed only because the trap had not fired) | `--embed-certs=true` so the CA is inlined into the kubeconfig | `d701f6d` |
| 6 | `00-namespace.yaml` Forbidden — the namespace-scoped `ci-deployer` Role cannot get/create the cluster-scoped Namespace (by design) | exclude `00-namespace.yaml` from both apply globs, alongside `01-ci-rbac.yaml` | `c95daf4` |

Setup commit `44aed3d` pins the CI runner to the dedicated `WG_LOCAL_IP=10.8.0.3/32`. All seven commits were verified on master (PR #1 → rebase-merge); the master deploy run re-ran the full pipeline green.

**Remaining follow-up (non-blocking, unchanged):** the doc-drift warning below (`docs/staging.md` / `README.md` / `AGENTS.md` still cite removed `CD_SSH_*` secrets and the deleted `scripts/deploy-staging.sh`) is still open.

### Gaps Summary

No blocking gaps. All 17 plan must-haves and all 5 ROADMAP success criteria are verified in the codebase: the workflow is a clean 3-job validate/dry-run/deploy structure with the concurrency lock, PR-vs-master gating, WG-then-kubeconfig-then-kubectl ordering, and `01-ci-rbac.yaml` excluded from both apply globs. The two CI helper scripts are substantive, fail-closed, and convention-compliant. The RBAC manifest is namespace-scoped with nothing cluster-scoped. Both runbooks (operator-bootstrap, sa-token-rotation) are complete. The legacy SSH deploy script is deleted and de-referenced from the validator. `validate-staging.py` exits 0.

One non-blocking **warning**: `docs/staging.md` still documents the removed `CD_SSH_*` secrets and the deleted `./scripts/deploy-staging.sh`, and omits the new `WG_*` / `K8S_TOKEN` / `K8S_CA_CERT` secrets — operator-facing documentation drift that no plan's must-haves scoped. It does not affect the CD path (CI does not read it) but should be cleaned up as follow-up. `README.md` and `AGENTS.md` carry the same stale script reference.

Status is **verified**: as of 2026-06-13 the live WireGuard handshake, SA-token auth, server-side dry-run, and a real master-push deploy (with rollouts) were all confirmed by actual CI runs against the staging cluster. The previously-deferred human-verification item is resolved; six latent bugs surfaced by the first live runs were fixed (see Live CI Verification). Only the documentation-drift warning remains as non-blocking follow-up.

---

_Verified: 2026-06-12 (code) · 2026-06-13 (live CI)_
_Verifier: Claude (gsd-verifier); live run driven by operator + Claude_
