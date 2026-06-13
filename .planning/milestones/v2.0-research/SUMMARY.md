# Project Research Summary

**Project:** Solid Stats Infrastructure
**Domain:** Single-staging k3s production-readiness + kubectl-native CD (solo operator, closed VPS)
**Researched:** 2026-06-11
**Confidence:** HIGH

## Executive Summary

v2.0 adds six features onto an already-working v1 staging system: kubectl-native CD,
edge automation, S3 lifecycle, an automated PostgreSQL restore drill, `web` runtime
wiring, and a controlled production cutover. The headline and settled foundation is
**kubectl-native CD** — replacing the SSH/scp deploy transport with a WireGuard tunnel
brought up *inside* the GitHub job, authenticating as a namespace-scoped ServiceAccount
(long-lived `kubernetes.io/service-account-token` Secret), and running `kubectl apply`
directly against the closed k3s API at `https://10.8.0.1:6443`. Everything else deploys
*through* that foundation, so it goes first; the production cutover consumes all the
others and goes last.

The expert approach here is deliberately lean and host-centric, not cloud-native-maximal.
Research across all four files converges on the same anti-features: **no GitOps controller
(ArgoCD/Flux), no service mesh / progressive canary, no cert-manager/ingress, no `mc`,
no full-tunnel WireGuard.** The public edge stays host-nginx with host `certbot` on a
systemd timer (k3s has no ingress in scope), S3 lifecycle is **expiration-only** because
Timeweb does not support storage-class transitions, and the cutover is a single reversible
nginx-upstream switch with legacy kept warm one edit away. This matches the solo-operator,
scope-creep-averse reality of one tiny single-namespace cluster.

The dominant risks are concentrated in the CD foundation and the data-path features.
The k3s API hop crosses the public internet over UDP, so the WireGuard handshake must be
*gated before any kubectl* (split-tunnel `AllowedIPs=10.8.0.1/32`, `PersistentKeepalive=25`,
possibly `MTU=1380`); the SA token model changed at k8s 1.24 so the token Secret must be
created explicitly; the serving cert must carry `10.8.0.1` in its SANs (never
`--insecure-skip-tls-verify`); RBAC must be scoped tightly but still cover `rollout status`;
and the namespace must be operator-bootstrapped once because a namespaced Role cannot create
the cluster-scoped Namespace. On the data side, the restore drill must run in an **ephemeral
scratch PostgreSQL**, never live `postgres-0`, and S3 lifecycle support must be proven on
Timeweb with a put-then-get round-trip plus an observed expiry, not assumed.

## Key Findings

### Recommended Stack

The stack is almost entirely *reuse* of the existing validated v1 stack (GitHub Actions,
k3s, PostgreSQL 17 / RabbitMQ 4 StatefulSets, GHCR, Timeweb S3, vendored `aws-cli`,
`render-staging-secrets.py`, `validate-staging.py`). v2.0 adds only the glue for the five
integration points. See `STACK.md` for full rationale.

**Core technologies:**
- **WireGuard-in-CI** (`niklaskeerl/easy-wireguard-action@v2`, pin SHA — or ~6 lines of
  inline `wg-quick` for zero third-party trust): brings up the tunnel from a client config
  in secrets, matching `wireguard-access.md` topology 1:1.
- **`azure/setup-kubectl@v4`** (pin to k3s server minor, e.g. `v1.31.x`): kubectl now runs
  on the runner, not the VPS, so it must be installed and version-skew-safe.
- **Scoped ServiceAccount + manual long-lived token Secret + namespaced Role/RoleBinding**
  (`kubernetes.io/service-account-token`, k8s ≥1.24 model): the CI identity, replacing
  `CD_SSH_*`. `kubectl create token` is short-lived and unusable for unattended CD.
- **`aws s3api put-bucket-lifecycle-configuration`** against `s3.twcstorage.ru` (path-style):
  Timeweb-documented; reuses existing `S3_*` secrets. Expiration-only.
- **`pg_restore`/`pg_dump` (`postgres:17-alpine`)** in a throwaway Job for the restore drill;
  **host `certbot --nginx` + systemd timer** for edge TLS (NOT cert-manager).

### Expected Features

Six features, all P1 except S3 lifecycle and web wiring (P2). See `FEATURES.md`.

**Must have (table stakes):**
- kubectl-native CD: push-to-deploy on master, WG tunnel in-job, scoped SA + namespace RBAC,
  ordered `kubectl apply`, rollout-status gating, pre-apply validation, **SSH/`CD_SSH_*` removed**.
- Edge automation: host nginx config in repo, certbot auto-renew via systemd timer with
  reload hook + renewal-failure visibility, host firewall (allow 80/443, keep 6443 tunnel-only).
- Restore drill: full restore into an **ephemeral scratch target**, on-demand command,
  post-restore sanity assertions, isolation from live PostgreSQL, drill result logged as evidence.
- Production cutover: both runtimes live in parallel, single-lever reversible nginx-upstream
  switch, tested rollback, pre-cutover diff gate green + fresh backup point.
- S3 lifecycle: per-prefix expiration, backup retention window, abort incomplete multipart,
  config stored in repo + applied via script.
- web wiring: Deployment+Service+ConfigMap following existing conventions, dedicated SA,
  resource limits/probes, pinned image (0-replicas/image-pending stub until real image exists).

**Should have (competitive):**
- Concurrency lock on the deploy job (one line, high value).
- Post-cutover scripted smoke check; idempotent edge bootstrap script.
- Distinct short retention for replay/artifact scratch prefixes.

**Defer (v2.x / future):**
- PR dry-run diff comment; scheduled drill CronJob + alert; weighted/blue-green nginx cutover.
- GitOps controller, service mesh, cert-manager, PITR/WAL — explicit anti-features at this scale.

### Architecture Approach

New/changed surface is small and additive (see `ARCHITECTURE.md`). CI `deploy` is rewritten
to bring up WG → assemble kubeconfig from SA token+CA → render secrets → `kubectl apply -f -`
(no ssh/scp). New manifests: `05-ci-rbac.yaml` (SA+Role+RoleBinding, right after `00-namespace`),
`45/46-web-*.yaml` (mirroring the server-2 30/35 split), a **separate** `restore-drill/`
directory (kept out of the `k8s/staging/*.yaml` deploy glob), and out-of-cluster `edge/` and
`s3/` directories. The namespace-create chicken-and-egg is resolved by an operator seeding
`00`+`05` once via their workstation WG kubeconfig; CI's SA owns everything `>=10`.

**Major components:**
1. **CI deploy job (modified)** — WG-up, kubeconfig-from-SA-token, kubectl-direct, SSH removed.
2. **`infra-deployer` SA + namespaced RBAC (new)** — least-privilege CI identity, no ClusterRole.
3. **Restore-drill Job + scratch namespace (new)** — reads dump from S3, ephemeral pg, never `postgres-0`.
4. **Host edge automation (new, out-of-cluster)** — repo-managed nginx vhosts + certbot timer + ufw.
5. **`web` Deployment/Service/ConfigMap (new)** — slot wired to conventions, routed by host nginx.
6. **S3 lifecycle policy (new)** — per-prefix expiration applied idempotently to the bucket.

### Critical Pitfalls

Top items from `PITFALLS.md` (10 total, mapped to phases there):

1. **WireGuard handshake never completes from the ephemeral runner** — gate on
   `wg show wg0 latest-handshakes` non-zero (or `ping 10.8.0.1`) before any kubectl;
   split-tunnel `AllowedIPs=10.8.0.1/32`, `PersistentKeepalive=25`, `MTU=1380` if large flights stall.
2. **k3s ≥1.24 SA has no auto-token Secret** — create the `kubernetes.io/service-account-token`
   Secret explicitly; assert `kubectl auth whoami != system:anonymous`.
3. **TLS SAN/CA mismatch on `10.8.0.1`** — verify `10.8.0.1 ∈ tls-san` via `openssl s_client`;
   supply the real CA; never `--insecure-skip-tls-verify`.
4. **RBAC too broad or too narrow** — namespace Role only (no ClusterRoleBinding), but must
   cover `rollout status` (get/list/watch on pods/replicasets/deployments/statefulsets);
   verify with `auth can-i --list` + SA-impersonated dry-run. Namespace created out-of-band.
5. **SSH path left open after cutover** — make `CD_SSH_*` removal + script de-SSH a gated step.
6. **Restore drill corrupts live DB/PVC** — automated drill runs in an ephemeral instance with
   its own volume, never live `postgres-0`/`postgres-data`; hard-guard the target DB name.
7. **Edge breaks during cutover** — land edge automation standalone first; `nginx -t`-gate every
   reload, `certbot renew --dry-run`, keep 80/443 open, cert-expiry alert; cutover only flips upstream.
8. **Timeweb S3 lifecycle silently differs from AWS** — prove with put-then-get + observed expiry;
   prefix `Expiration{Days}` only, no transitions/storage classes.

## Implications for Roadmap

Build order is dependency-forced: **CD first, cutover last, the rest parallel between.**
Suggested phases (1:1 with the six features):

### Phase 1: kubectl-native CD (WireGuard-in-CI, scoped SA, SSH removed)
**Rationale:** Settled foundation — every other feature deploys *through* the new CD path.
Resolves the namespace-create boundary (operator seeds `00`+`05` once).
**Delivers:** WG-up-in-job, kubeconfig-from-SA-token, `05-ci-rbac.yaml`, rewritten
`deploy-staging.sh` (kubectl-direct), `CD_SSH_*` deleted, handshake/auth/SAN gates.
**Addresses:** Feature #1 (push-to-deploy, scoped SA, no SSH).
**Avoids:** Pitfalls 1–6 (WG handshake, SA token model, TLS SAN, RBAC scope, SSH cleanup, token rotation).

### Phase 2: Edge automation (host nginx, cert renewal, firewall)
**Rationale:** Standalone and *before* cutover — proving renewals and firewall in isolation
prevents two unproven changes interacting at cutover. Also closes 6443 publicly, reinforcing Phase 1.
**Delivers:** repo-managed nginx vhosts, certbot systemd timer + reload hook, ufw ruleset,
idempotent edge bootstrap.
**Uses:** host `certbot --nginx` (NOT cert-manager); ufw/nftables.
**Avoids:** Pitfall 7 (`nginx -t`-gated reloads, dry-run renewal, cert-expiry alert, HTTP-01 stays open).

### Phase 3: Automated PostgreSQL restore drill
**Rationale:** Recoverability proof that should precede cutover; independent of edge/web once CD lands.
**Delivers:** `restore-drill/` scratch-namespace Job + `restore-drill.sh` reading the latest S3 dump,
ephemeral pg, row-count assertions, teardown, logged evidence.
**Implements:** isolated scratch-namespace restore (Architecture Pattern 3).
**Avoids:** Pitfall 9 (never restore over live `postgres-0`/PVC; guard target DB name).

### Phase 4: `web` runtime wiring (stub slot)
**Rationale:** First genuinely new workload under the new ownership model; low-risk, no traffic yet.
**Delivers:** `45/46-web-*.yaml` (config+service / deployment split), dedicated SA, limits/probes,
pinned image or 0-replica stub; `validate-staging.py` `EXPECTED_*` updated.
**Avoids:** Pitfall 10 (dependency-ordered apply; add web to the rollout-status gate or derive by label).

### Phase 5: S3 lifecycle / retention
**Rationale:** Fully independent; land after the restore drill confirms retention assumptions are safe.
**Delivers:** per-prefix `lifecycle.json` + apply script via `aws s3api`, expiration-only,
multipart-abort, distinct windows for backups vs replays vs artifacts.
**Avoids:** Pitfall 8 (prove support on Timeweb: put-then-get + observed test-object expiry as evidence).

### Phase 6: Production cutover
**Rationale:** Last — consumes a proven CD path, edge automation, web slot, and recovery confidence.
**Delivers:** both runtimes parallel, single reversible nginx-upstream switch, tested rollback,
fresh backup point + green diff gate, post-cutover smoke check.
**Avoids:** Pitfalls 7+10 interactions (reversible single-edit upstream; curl the public host).

### Phase Ordering Rationale

- **CD first / cutover last is the only hard ordering.** Phases 2–5 are otherwise independent and
  can be sequenced by capacity (`1 → (2,3,4,5) → 6`).
- Edge (2) before cutover because the cutover lever *is* the nginx upstream and must be proven reversible.
- Restore drill (3) before cutover because you never flip production without proven recoverability.
- S3 lifecycle (5) is independent but scheduled after the drill so retention windows are validated against the drill cadence.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (CD):** highest-risk integration — WG-from-GitHub-runner mechanics, exact RBAC verb/resource
  set derived from manifests, SA-token bootstrap. Concentrate verification here.
- **Phase 5 (S3 lifecycle):** Timeweb S3 feature parity is MEDIUM confidence — must be proven empirically
  on the live bucket before trusting retention.

Phases with standard patterns (skip research-phase):
- **Phase 4 (web wiring):** mirrors existing server-2 manifests exactly; established repo convention.
- **Phase 3 (restore drill):** reuses the backup Job's S3 access pattern + existing runbook.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Mostly reuse of validated v1 stack; new pieces (WG action, setup-kubectl, SA token model) are official/well-established. WG action is third-party (pin SHA). |
| Features | HIGH | Grounded in PROJECT.md scope + Timeweb docs + kubernetes-specialist skill; anti-features explicitly bounded. |
| Architecture | HIGH | Grounded in the actual repo; namespace-create and apply-ordering boundaries are standard k8s behavior. |
| Pitfalls | HIGH (MEDIUM on S3) | k3s SA-token/WireGuard/cutover mechanics HIGH; Timeweb S3 lifecycle exact parity MEDIUM (must verify). |

**Overall confidence:** HIGH

### Gaps to Address

- **Timeweb S3 lifecycle exact feature surface** — vendor confirms lifecycle/expiration exist but not full
  AWS parity. Handle in Phase 5 with a put-then-get round-trip and an observed expiry on a test object before trusting retention.
- **Long-lived SA token rotation** — the stored token is the weakest link; a rotation runbook (owner + cadence,
  paired with WG key rotation) must be defined in Phase 1 and revisited at cutover (prod gets its own scoped token).
- **WG egress from GitHub-hosted runners** — assumes 51820/udp outbound is permitted; if a TCP-only egress path
  is hit, fallback is `wireguard-go` or a self-hosted runner on a UDP-permitting network. Validate early in Phase 1.

## Sources

### Primary (HIGH confidence)
- Repo files: `.planning/PROJECT.md`, `docs/staging.md`, `docs/wireguard-access.md`, `docs/backup-restore.md`,
  `.github/workflows/deploy-staging.yml`, `scripts/deploy-staging.sh`, `scripts/render-staging-secrets.py`,
  `scripts/validate-staging.py`, `k8s/staging/*.yaml` — authoritative for current state.
- `.agents/skills/kubernetes-specialist/SKILL.md` — least-privilege RBAC, no default SA, probes/limits, GitOps-for-fleets.
- `Azure/setup-kubectl@v4`; Kubernetes SA token model ≥1.24 (manual `service-account-token` Secret = long-lived);
  Kubernetes Namespace is cluster-scoped (namespaced Role cannot create it).
- Timeweb S3 object-lifecycle docs — confirms `aws s3api put-bucket-lifecycle-configuration` with prefix `Expiration`; no `mc`, no transitions.

### Secondary (MEDIUM confidence)
- `niklaskeerl/easy-wireguard-action@v2` (GitHub Marketplace, not GitHub-certified — pin commit SHA).
- Timeweb S3 bucket management — confirms lifecycle/versioning exist but not full AWS feature parity.
- `k3s` token docs — k3s tracks upstream SA behavior.

### Tertiary (LOW confidence)
- None.

---
*Research completed: 2026-06-11*
*Ready for roadmap: yes*
