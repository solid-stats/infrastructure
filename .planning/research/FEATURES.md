# Feature Research

**Domain:** Single-staging k3s production-readiness + kubectl-native CD (solo operator)
**Researched:** 2026-06-11
**Confidence:** HIGH

Scope is the six v2.0 features only. Throughout, "table stakes" means the minimum
that makes the feature trustworthy for a solo operator running one staging cluster;
"differentiators" are real-but-optional upgrades; "anti-features" are things that
look standard in big-team / multi-cluster guides but are wrong for this context and
should be deliberately NOT built. The user is scope-creep averse — defer aggressively.

---

## 1. kubectl-native CD (WireGuard-in-CI, scoped SA + RBAC, no SSH)

**How it typically works:** the CI job brings up a WireGuard tunnel to the closed
k3s API, authenticates as a namespace-scoped ServiceAccount token (not the cluster
admin kubeconfig), runs `kubectl apply`, then gates on `kubectl rollout status`.
Replaces the current SSH→kubectl model and the `CD_SSH_*` secrets.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Push-to-deploy on master | Git is the deploy source of truth; merge = ship to staging | LOW | Replaces manual `deploy-staging.sh` over SSH |
| WireGuard tunnel brought up inside the CI job | k3s API stays closed; no public 6443 | MEDIUM | WG config + key in `staging` env secrets; teardown on job exit |
| Scoped ServiceAccount + namespace Role/RoleBinding | Least privilege; CI token can only touch `solid-stats-staging` | MEDIUM | SA token as kubeconfig; aligns with kubernetes-specialist "never use default SA / least-privilege RBAC" |
| `kubectl apply` of `k8s/staging/*.yaml` in prefix order | Declarative, ordered apply is the existing model | LOW | Reuse numeric-prefix ordering already in repo |
| Rollout-status gating (fail the job on bad rollout) | A deploy that leaves pods crash-looping must be a red build | LOW | `rollout status` already in `deploy-staging.sh`; just move into CI |
| Pre-apply validation gate (`validate-staging.py` + `kubectl apply --dry-run=server`) | Stops broken manifests / bad secret rendering reaching the cluster | LOW | Server dry-run catches schema/admission errors client-side can't |
| SSH/scp + `CD_SSH_*` secrets removed | The point of the migration; closes the SSH attack surface | LOW | Coordinate with edge/firewall feature (#3) |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| PR dry-run validation (diff/plan comment on PRs) | See what a merge would change before it ships | MEDIUM | `kubectl diff` against live cluster from the PR branch; read-only SA |
| Concurrency lock on the deploy job | Two overlapping deploys can't race on the same namespace | LOW | GitHub `concurrency:` group — one line, high value |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| GitOps controller (ArgoCD/Flux) + drift correction | "Proper" CD; auto-reconcile drift | A controller, CRDs, and its own RBAC to run forever on one tiny single-namespace staging cluster; the kubernetes-specialist GitOps reference is built for multi-cluster fleets | Push-based `kubectl apply` from CI; git is already source of truth |
| Self-hosted runner inside the cluster | Avoids the WG tunnel | New always-on workload + its own attack surface; defeats "no inbound" goal | Ephemeral GitHub-hosted runner dialing out over WG |
| Automatic drift correction / continuous reconcile | Keeps cluster matching git | Solo operator sometimes hot-patches staging on purpose; auto-revert fights the operator | `kubectl diff` on demand surfaces drift without auto-reverting |
| Cluster-admin kubeconfig in CI | Simplest to wire | Blast radius = whole cluster if the token leaks | Namespace-scoped SA + Role only |

---

## 2. Production cutover (legacy → new k3s runtime)

**How it typically works:** traffic currently reaches legacy `server-2` through
host nginx. Cutover flips the upstream (or DNS) to the new k3s runtime, with a
tested path back to legacy. For a single public API behind host nginx, an
nginx-upstream switch is the lever — not a service mesh or k8s ingress canary.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Both runtimes live in parallel before the switch | Can't cut over to something unverified | MEDIUM | Legacy stays up; new runtime gets real traffic only at flip |
| Single-lever traffic switch (nginx upstream) | One clear, reversible action | LOW | Edit upstream in host nginx (feature #3 owns the nginx automation) |
| Documented, tested rollback path | Must be able to revert in seconds if new runtime misbehaves | LOW | Rollback = point upstream back at legacy; verify it actually works pre-cutover |
| Pre-cutover diff/full-run gate already green | v1 already blocks cutover on diff readiness | LOW | Dependency on existing diff-readiness gate, not new work |
| Backup point taken immediately before cutover | A current restore point bounds the worst case | LOW | Reuse existing manual backup command |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Blue-green at the nginx layer (weighted upstream) | Shift a fraction of traffic, watch, then 100% | MEDIUM | nginx `split_clients` or weighted upstream; only worth it if you'll actually watch metrics during the window |
| Post-cutover smoke check before declaring done | Catches a broken cutover automatically | LOW | Scripted curl of key API endpoints against the new upstream |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| In-place cutover (tear down legacy, redeploy as new) | Fewer moving parts | No fast rollback — if new runtime is broken, you're rebuilding under pressure | Keep legacy warm; switch upstream; only retire legacy after a soak period |
| Service mesh / progressive canary (Istio, Flagger) | "Real" canary deploys | Massive control plane for one API endpoint on one node | Weighted nginx upstream if any gradual shift is wanted at all |
| Automated metric-driven auto-promote/auto-rollback | Hands-off cutover | Needs a metrics+SLO stack that doesn't exist here; solo operator is watching anyway | Operator watches smoke check + logs, flips manually |

---

## 3. Edge automation (host nginx, cert renewal, firewall)

**How it typically works:** the public edge is host-level nginx terminating TLS,
with certbot auto-renewing certs on a systemd timer, and a host firewall (ufw/nftables)
restricting inbound. This is host config the infra repo should own as code/runbooks,
not a Kubernetes ingress/cert-manager stack (PROJECT.md explicitly keeps ingress and
cert-manager out of scope; the public edge is host nginx).

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Host nginx config owned in repo | Edge is part of the runtime; must be reproducible | LOW | Versioned nginx site config + a documented install step |
| certbot auto-renew via systemd timer | Expired cert = outage; renewal must be unattended | LOW | `certbot renew` timer (default twice-daily) + nginx reload hook |
| Renewal failure visibility | A silently failing renewal is a time-bomb | LOW | `--deploy-hook` reloads nginx; alert/log on renew failure |
| Host firewall: allow 80/443, drop the rest | k3s API and node must not be publicly reachable | MEDIUM | ufw/nftables ruleset in repo; explicitly closes 6443 — supports #1's WG-only access |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Idempotent edge bootstrap script | Rebuild the edge from scratch reproducibly | MEDIUM | One script: install nginx, drop config, request/renew cert, apply firewall |
| Staging-only HTTP basic-auth / IP allowlist at edge | Keep staging API from public crawlers | LOW | nginx `allow`/`deny` or basic auth; cheap hardening |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| cert-manager + k8s Ingress controller | "Cloud-native" TLS | Adds an ingress controller, ACME controller, CRDs, and LoadBalancer wiring to replace one working host-nginx vhost | Keep host nginx + certbot timer (explicitly the chosen model) |
| Config-management tool (Ansible/Salt) for one host | "Proper" host automation | A whole CM toolchain for a single VPS | Idempotent shell script + documented runbook |
| Wildcard / DNS-01 certs | Future-proofing subdomains | Needs DNS API creds + plugin for a single hostname | HTTP-01 single-domain cert until a real second hostname exists |

---

## 4. S3 lifecycle / retention policies

**How it typically works (and Timeweb's actual support):** a bucket lifecycle
configuration auto-expires objects by age, scoped by prefix, and aborts incomplete
multipart uploads. **Confirmed against Timeweb docs: expiration + prefix filtering +
incomplete-multipart cleanup are supported; storage-class transitions/tiers (Glacier,
IA) are NOT supported.** So this is purely a retention/expiry feature — there is no
"transition" tier to design around. Configurable via AWS CLI
`put-bucket-lifecycle-configuration` or the panel.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-prefix expiration rules | `backups/postgres/`, replay, and artifact prefixes have different retention needs | LOW | Distinct rules keyed on the prefixes that already coexist in the bucket |
| Backup retention window (e.g. keep N days of dumps) | Bounds storage cost; old dumps aren't useful | LOW | Expiration on `backups/postgres/`; pick a window that covers the restore-drill cadence |
| Abort incomplete multipart uploads | Failed backup uploads otherwise accumulate as billable orphans | LOW | Supported by Timeweb; one rule covers the whole bucket |
| Lifecycle config stored in repo + applied via script | Retention is policy; must be reviewable and reproducible | LOW | JSON lifecycle doc in repo, applied with AWS CLI |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Distinct short retention for replay/artifact scratch prefixes | Replay scratch and report artifacts can expire faster than backups | LOW | Separate prefix rules; pure cost hygiene |
| Keep-last-N intent documented vs raw age | Makes the retention decision auditable | LOW | Note in runbook why N days was chosen relative to restore-drill cadence |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Storage-class transition tiers (Glacier/IA) | Cheaper cold storage | **Not supported by Timeweb S3** — rules would no-op or error | Expiration-only; cost-control via shorter windows |
| Object versioning + version-aware lifecycle | "Safer" retention | Doubles complexity and storage for a backup prefix that's already immutable-per-run | Immutable timestamped object keys; expire by age |
| Cross-region/replicated backup tier | DR robustness | Out of scope for single-staging; new provider + creds + cost | One bucket, prefix-scoped retention; revisit at production scale |

---

## 5. Automated PostgreSQL restore drill

**How it typically works:** today the gate is `pg_restore --list` (verifies the dump
is parseable). A real drill goes further: restore the latest dump into a throwaround
scratch target and assert it loads. Two axes: scheduled vs on-demand, and verify-only
(`--list`) vs full-restore-into-scratch.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Full restore into a scratch/ephemeral target | `--list` proves the file parses, not that it restores | MEDIUM | Restore latest dump into a temp DB / throwaround Job, then drop it |
| On-demand drill command | Operator must be able to prove recoverability before risky ops (e.g. cutover) | LOW | Wraps existing backup tooling; mirrors existing manual-command pattern |
| Post-restore sanity assertions | A restore that loads but is empty is a false pass | LOW | Row-count / key-table existence checks after restore |
| Scratch teardown + isolation from live PostgreSQL | Drill must never touch the durable staging DB | MEDIUM | Separate DB name or ephemeral Job; never restore over `postgres-data` |
| Drill result logged as evidence | Validation constraint requires fresh evidence | LOW | Capture log/output as the restore-drill proof artifact |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Scheduled drill CronJob (e.g. weekly) | Catches backup rot before you need the backup | MEDIUM | Only worth it if a failed drill actually alerts someone |
| Drill-failure alert | Turns a silent regression into a signal | LOW | Cheap if any notification channel already exists; skip if none |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Restore into the live staging PostgreSQL to "test" | Tests the real path | Can corrupt/clobber durable staging data — violates the safety constraint | Always restore into an ephemeral scratch target |
| Continuous PITR / WAL-archiving restore validation | Gold-standard RPO | WAL archiving + base-backup infra is a project of its own; not justified for staging | Periodic full-dump restore drill |
| Multi-version / cross-engine restore matrix | Future migration safety | Combinatorial effort for a single PG 17 instance | Drill the one version actually deployed |

---

## 6. `web` runtime wiring (k8s manifests for future web app)

**How it typically works:** stub the Kubernetes wiring for the future `web` app the
same way existing components are wired (Deployment + Service + ConfigMap, pinned image,
SA, probes, resource limits), so the slot exists and is deploy-ready — without
inventing app behavior the app repo owns.

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Deployment + Service manifest following existing conventions | Consistency with `server-2`/`replay-parser-2` wiring | LOW | Numeric-prefixed file in `k8s/staging/`; pinned image (no `latest`) |
| Dedicated ServiceAccount + namespace RBAC | kubernetes-specialist baseline; no default SA | LOW | Mirror existing component SAs |
| Resource requests/limits + liveness/readiness probes | MUST-DO from the skill; CD rollout gating needs probes | LOW | Same pattern as existing deployments |
| ConfigMap/Secret wiring via `render-staging-secrets.py` | Secrets stay out of git; consistent with existing rendering | LOW | Add web-specific derived keys to the renderer |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Edge route reserved for `web` | When the app ships, exposing it is a one-line nginx change | LOW | Coordinate with edge feature #3; reserve a location/upstream, leave disabled |
| Manifest-present-but-zero-replicas / image-pending stub | Slot exists and validates without running a non-existent image | LOW | Avoids a crash-looping placeholder; deploy when the real image exists |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Building/guessing the web app's runtime contract | "Make it complete" | Infra repo doesn't own app behavior; guesses will be wrong and rework | Wire the slot to conventions; let the app repo define real config |
| Placeholder image that actually runs | Looks deployed | Crash-loops / fake healthy pod pollutes rollout gating | 0 replicas or apply only when a real pinned image exists |
| Ingress/HPA/autoscaling for web now | Future-proofing | No traffic, no app, no metrics yet | Add when the app is real and has load |

---

## Feature Dependencies

```
[#3 Edge: firewall closes 6443 / WG-only]
    └──enables──> [#1 kubectl-native CD over WireGuard]
                       └──required-by──> [all manifest deploys, incl. #6 web wiring]

[#3 Edge: host nginx as code]
    └──required-by──> [#2 Production cutover (nginx upstream is the switch lever)]

[existing diff-readiness gate] ──gates──> [#2 Production cutover]
[existing backup command] ──required-by──> [#5 Restore drill] and [#2 cutover backup point]

[#5 Restore drill: proven recoverability] ──should-precede──> [#2 Production cutover]

[#4 S3 lifecycle] ── independent ──  (no hard dependency; pure retention hygiene)
```

### Dependency Notes

- **#1 CD depends on #3 firewall/WG:** kubectl-native CD only makes sense once the
  k3s API is closed (6443 dropped) and reachable solely over the WireGuard tunnel.
  Build the firewall + WG access path before removing SSH.
- **#2 Cutover depends on #3 host nginx automation:** the cutover lever *is* the
  nginx upstream; cutover can't be safe until nginx config is owned and reversible.
- **#2 Cutover depends on existing diff-readiness gate + a fresh backup point:** both
  already exist; cutover consumes them rather than rebuilding.
- **#5 Restore drill should precede #2 cutover:** never flip production traffic
  without proven recoverability, not just a parseable dump.
- **#4 S3 lifecycle is independent:** can land any time; no other feature blocks on it.
- **#6 web wiring depends on #1 CD:** the slot is only useful once deploys flow
  through the new CD path.

## MVP Definition

### Launch With (v2.0 core)

- [ ] **#1 kubectl-native CD** — the milestone's headline; git becomes deploy truth, SSH removed
- [ ] **#3 Edge automation** — firewall (closes API, unblocks #1) + certbot timer + host nginx as code; unblocks #2
- [ ] **#5 Restore drill (on-demand, full-restore-into-scratch)** — recoverability proof gating #2
- [ ] **#2 Production cutover (in-parallel + nginx-upstream switch + tested rollback)** — the deferred-from-v1 goal

### Add After Validation (v2.x)

- [ ] **#4 S3 lifecycle** — independent retention hygiene; land alongside or just after core
- [ ] **#6 web wiring (stub slot)** — low-risk; add when there's appetite, no app yet
- [ ] **#5 scheduled drill CronJob + alert** — upgrade the on-demand drill once it's trusted
- [ ] **#1 PR dry-run diff comment** — DX upgrade after push-to-deploy is solid

### Future Consideration (defer)

- [ ] **Weighted/blue-green nginx cutover** — only if a gradual shift is genuinely wanted; in-parallel + instant flip is enough first
- [ ] **GitOps controller, service mesh, cert-manager, PITR/WAL** — explicit anti-features for this scale; revisit only at multi-cluster / true-production scale

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| #1 kubectl-native CD (push-to-deploy, scoped SA, no SSH) | HIGH | MEDIUM | P1 |
| #3 Edge firewall + certbot timer + host nginx as code | HIGH | MEDIUM | P1 |
| #5 Restore drill — full-restore-into-scratch, on-demand | HIGH | MEDIUM | P1 |
| #2 Production cutover — in-parallel + nginx switch + rollback | HIGH | MEDIUM | P1 |
| #4 S3 lifecycle — prefix expiration + multipart abort | MEDIUM | LOW | P2 |
| #6 web runtime stub wiring | LOW | LOW | P2 |
| #1 PR dry-run diff comment | MEDIUM | MEDIUM | P3 |
| #5 scheduled drill CronJob + alert | MEDIUM | MEDIUM | P3 |
| #2 weighted/blue-green cutover | LOW | MEDIUM | P3 |

**Priority key:** P1 = must have for v2.0 · P2 = should have, add when possible · P3 = defer.

## Sources

- Timeweb Cloud — S3 object lifecycle (expiration + prefix + multipart abort supported; storage-class transitions NOT supported): [timeweb.cloud/docs/s3-storage/supported-features/object-lifecycle](https://timeweb.cloud/docs/s3-storage/supported-features/object-lifecycle) — HIGH
- AWS S3 lifecycle reference (expiration vs transition semantics, for contrast): [docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html) — HIGH
- Project context: `.planning/PROJECT.md`, `docs/staging.md` (existing v1 system, ownership boundaries, deferred-to-v2 items) — HIGH
- `.agents/skills/kubernetes-specialist/SKILL.md` (least-privilege RBAC, no default SA, probes/limits, GitOps-for-fleets guidance) — HIGH

---
*Feature research for: single-staging k3s production-readiness + kubectl-native CD*
*Researched: 2026-06-11*
