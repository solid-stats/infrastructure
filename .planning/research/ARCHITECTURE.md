# Architecture Research

**Domain:** k3s-on-VPS infrastructure CD — v2.0 production-readiness features
**Researched:** 2026-06-11
**Confidence:** HIGH (grounded in the actual repo; external facts on k3s SA tokens / RBAC are standard Kubernetes behavior)

## Standard Architecture

This research answers how the six v2.0 features integrate with the existing
repo, what is **new** vs **modified**, the data-flow changes, and a
dependency-aware build order. The settled, highest-priority slice is
**kubectl-native CD**; everything else sequences after or beside it.

### Current vs Target System Overview

```
CURRENT (v1)
┌──────────────────────────────────────────────────────────────────────┐
│ GitHub Actions: validate → deploy                                      │
│   deploy: Install-SSH-key → Trust-host → deploy-staging.sh             │
└───────────────┬──────────────────────────────────────────────────────┘
                │ ssh/scp (CD_SSH_* secrets)
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ VPS (Timeweb)                                                          │
│  host nginx (manual) ──► server-2 Service (k8s)                        │
│  k3s API 127.0.0.1:6443 (local kubectl invoked over SSH)              │
│  ns solid-stats-staging: postgres, rabbitmq, server-2,                 │
│    replay-parser-2, replays-fetcher(suspended), postgres-backup        │
│  WireGuard wg0 10.8.0.1 (operator workstation access only)            │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼  backups/postgres/  ──►  Timeweb S3
```

```
TARGET (v2)
┌──────────────────────────────────────────────────────────────────────┐
│ GitHub Actions: validate → deploy                                      │
│   deploy: wg-up(WG_* secrets) → assemble kubeconfig(SA token+CA+      │
│           https://10.8.0.1:6443) → render secrets → kubectl apply      │
│           (no ssh, no scp, no CD_SSH_*)                                │
└───────────────┬──────────────────────────────────────────────────────┘
                │ WireGuard UDP 51820  → tunnel 10.8.0.1
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ VPS (Timeweb)                                                         │
│  edge: host nginx (now repo-managed config + cert renewal + ufw)      │
│        ──► server-2 Service  (+ later: web Service)                   │
│  k3s API 10.8.0.1:6443  ← scoped SA `infra-deployer` (RBAC)           │
│  ns solid-stats-staging: …existing… + web Deployment/Service/CM       │
│  scratch ns solid-stats-restore-drill: restore Job (reads S3)         │
└───────────────┬──────────────────────────────────────────────────────┘
                ▼  S3 lifecycle rules on backups/replay/artifact prefixes
```

### Component Responsibilities (new + changed only)

| Component | Responsibility | New / Modified |
|-----------|----------------|----------------|
| CI `deploy` job | Bring up WG, build kubeconfig from SA token, run `kubectl apply` directly | **Modified** (replaces SSH steps) |
| `wg0` client config in CI | Ephemeral tunnel from the runner to `10.8.0.1` | **New** (CI-side; server already has wg0) |
| `infra-deployer` SA + RBAC | Identity CI authenticates as; least-privilege to deploy ns resources | **New** (`05-ci-rbac.yaml`) |
| `deploy-staging.sh` (or replacement) | Render secrets locally → pipe `kubectl apply -f -`, no ssh/scp wrappers | **Modified / largely rewritten** |
| host nginx config + cert + firewall | Edge config becomes repo-managed and automated (renewal, ufw) | **New** (out-of-cluster automation) |
| S3 lifecycle policy | Retention rules per prefix on the Timeweb bucket | **New** (one-time/idempotent apply) |
| restore-drill Job + scratch ns | Automated `pg_restore` validation reading a dump from S3 | **New** (`k8s/restore-drill/` or scratch manifest) |
| `web` Deployment/Service/ConfigMap | Future `web` app runtime wiring | **New** (`45-web-*.yaml`) |

## Recommended Project Structure

```
k8s/
├── staging/                 # existing apply-ordered runtime (numeric prefixes)
│   ├── 00-namespace.yaml
│   ├── 05-ci-rbac.yaml      # NEW: infra-deployer SA + Role + RoleBinding
│   ├── 10-postgres.yaml
│   ├── 20-rabbitmq.yaml
│   ├── 30-server-2.yaml
│   ├── 35-server-2-deployment.yaml
│   ├── 40-replay-parser-2.yaml
│   ├── 45-web-config.yaml   # NEW: web ConfigMap + Service
│   ├── 46-web-deployment.yaml  # NEW: web Deployment (split like server-2 30/35)
│   ├── 50-replays-fetcher.yaml
│   └── 60-postgres-backup.yaml
├── restore-drill/           # NEW: scratch-namespace restore Job (NOT in staging/)
│   ├── 00-namespace.yaml    #   ns solid-stats-restore-drill
│   └── 10-restore-job.yaml  #   Job: pulls dump from S3 → ephemeral pg → pg_restore
edge/                        # NEW: out-of-cluster host edge automation
│   ├── nginx/               #   server-2 / web vhost templates
│   ├── renew-certs.sh       #   cert renewal (certbot or acme.sh) + reload
│   └── firewall.sh          #   ufw rules (keep 6443 tunnel-only, 80/443 public)
s3/                          # NEW: bucket lifecycle policy JSON + apply script
scripts/
├── deploy-staging.sh        # MODIFIED: drop ssh/scp, kubectl direct
├── ci-kubeconfig.sh         # NEW: assemble kubeconfig from SA token + CA
├── restore-drill.sh         # NEW: drive the restore Job + assert success
├── render-staging-secrets.py
└── validate-staging.py      # MODIFIED: add new files to EXPECTED_MANIFESTS
```

### Structure Rationale

- **`05-ci-rbac.yaml` sits right after `00-namespace.yaml`:** the SA must exist
  inside the namespace before anything else, and `05` matches the existing
  numeric-prefix convention with room left below `10`. (Confidence: HIGH)
- **`restore-drill/` is a separate directory, not in `staging/`:** the drill
  uses its own scratch namespace and must never be in the set that
  `deploy-staging.sh` globs and applies. Keeping it out of `k8s/staging/*.yaml`
  prevents accidental scheduling on every deploy. (Confidence: HIGH)
- **`edge/` and `s3/` are out-of-cluster:** they configure the host and the
  Timeweb bucket, not k3s objects, so they live outside `k8s/`. (Confidence: HIGH)
- **`web` split into config+service / deployment** mirrors the existing
  `30-server-2.yaml` (ConfigMap+Service) and `35-server-2-deployment.yaml`
  split, so image bumps touch one file. (Confidence: HIGH)

## Architectural Patterns

### Pattern 1: WireGuard-in-CI + kubeconfig-from-SA-token (the CD replacement)

**What:** Replace the three SSH-era steps (`Install SSH key`, `Trust deploy
host`, `Apply staging manifests` via `deploy-staging.sh` over ssh) with: bring
up a WireGuard interface on the runner, then build a kubeconfig that targets
`https://10.8.0.1:6443` and authenticates as the scoped SA bearer token.

**When to use:** This is the settled foundation — do it first.

**Trade-offs:** Runner needs `wireguard-tools` + `NET_ADMIN` (available on
`ubuntu-latest` via `sudo wg-quick`/`ip`). The handshake is UDP to
`<VPS_PUBLIC_IP>:51820`, already open at the Timeweb perimeter. The SA token is
long-lived unless you mint a short-lived one; a bound token via
`kubectl create token` is better but requires bootstrap access, so a stored
token Secret is the pragmatic v2 default.

**Example (new CI deploy steps, replacing lines 50–82 of the workflow):**
```yaml
- name: Bring up WireGuard
  env:
    WG_PRIVATE_KEY:  ${{ secrets.CD_WG_PRIVATE_KEY }}   # runner's own /32
    WG_SERVER_PUBKEY: ${{ secrets.CD_WG_SERVER_PUBLIC_KEY }}
    WG_ENDPOINT:     ${{ secrets.CD_WG_ENDPOINT }}      # <VPS_PUBLIC_IP>:51820
    WG_ADDRESS:      ${{ secrets.CD_WG_ADDRESS }}       # 10.8.0.<N>/32
  run: |
    sudo apt-get update && sudo apt-get install -y wireguard-tools
    umask 077
    cat >wg0.conf <<EOF
    [Interface]
    Address = ${WG_ADDRESS}
    PrivateKey = ${WG_PRIVATE_KEY}
    [Peer]
    PublicKey = ${WG_SERVER_PUBKEY}
    Endpoint = ${WG_ENDPOINT}
    AllowedIPs = 10.8.0.1/32
    PersistentKeepalive = 25
    EOF
    sudo wg-quick up ./wg0.conf
    ping -c1 -W5 10.8.0.1

- name: Assemble kubeconfig
  env:
    K8S_SA_TOKEN: ${{ secrets.CD_K8S_SA_TOKEN }}
    K8S_CA_CERT:  ${{ secrets.CD_K8S_CA_CERT }}   # base64 of the API CA
  run: ./scripts/ci-kubeconfig.sh   # writes $KUBECONFIG → server https://10.8.0.1:6443

- name: Deploy
  env: { ...same app/secret env as today... }
  run: ./scripts/deploy-staging.sh   # now kubectl-direct, no ssh

- name: Tear down WireGuard
  if: always()
  run: sudo wg-quick down ./wg0.conf || true
```
The server already advertises `10.8.0.1` in the k3s cert SANs
(`tls-san: 10.8.0.1`), so TLS verification against the tunnel IP works.
(Confidence: HIGH — repo doc confirms the SAN; the CI mechanics are standard.)

### Pattern 2: Scoped SA + namespace RBAC, with the namespace-create boundary

**What:** `05-ci-rbac.yaml` defines a `ServiceAccount infra-deployer` plus a
namespaced `Role` granting only the verbs/resources the deploy needs
(`get/list/create/update/patch` on `secrets, configmaps, services,
serviceaccounts, deployments, statefulsets, cronjobs, jobs, persistentvolume
claims, pods` within the namespace) and a `RoleBinding`.

**The namespace-create boundary (the key design decision):**
`Namespace` is **cluster-scoped** — a namespaced `Role` *cannot* grant
`create namespace`. Today `deploy-staging.sh` runs
`kubectl create namespace ... || true` as cluster-admin over SSH. Once CI
authenticates as a least-privilege SA, that line will fail with a forbidden
error. Three options:

| Option | What it means | Verdict |
|--------|---------------|---------|
| **A. Bootstrap the namespace once** (manual/admin) and remove the create line from CI | CI never creates namespaces; the SA + Role + namespace are seeded once out-of-band, CI only applies into an existing ns | **Recommended.** Smallest blast radius; matches "git is source of truth for what *ships*", and the ns rarely changes. (Confidence: HIGH) |
| **B. Narrow ClusterRole** granting `get;create` on `namespaces` (optionally name-restricted via admission, not RBAC) | CI can self-heal the namespace | More privilege than needed; RBAC can't restrict to one namespace name, so it's `create any namespace`. Avoid unless self-bootstrap is required. |
| **C. Keep a tiny admin bootstrap path** for ns + RBAC, separate from the CD SA | A one-time `kubectl apply` of `00-namespace.yaml` + `05-ci-rbac.yaml` by an operator (over the workstation WG kubeconfig), CD SA owns everything `>=10` | **Recommended companion to A.** This is the chicken-and-egg resolution: the SA that CI uses can't create the namespace it lives in, so an operator seeds `00`+`05` once. (Confidence: HIGH) |

Practical resolution: **A + C.** Operator applies `00-namespace.yaml` and
`05-ci-rbac.yaml` once via their personal WG kubeconfig (cluster-admin).
Thereafter CI's SA applies `10..60` and future `45/46`. Remove the
`kubectl create namespace` line from the deploy script (or guard it so it's a
no-op the SA never reaches).

**Example RBAC skeleton (`05-ci-rbac.yaml`):**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata: { name: infra-deployer, namespace: solid-stats-staging }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: infra-deployer, namespace: solid-stats-staging }
rules:
  - apiGroups: [""]
    resources: [secrets, configmaps, services, serviceaccounts, persistentvolumeclaims, pods]
    verbs: [get, list, watch, create, update, patch]
  - apiGroups: ["apps"]
    resources: [deployments, statefulsets]
    verbs: [get, list, watch, create, update, patch]
  - apiGroups: ["batch"]
    resources: [cronjobs, jobs]
    verbs: [get, list, watch, create, update, patch]
  # rollout status needs get on deployments/statefulsets (covered above)
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: infra-deployer, namespace: solid-stats-staging }
subjects: [{ kind: ServiceAccount, name: infra-deployer, namespace: solid-stats-staging }]
roleRef: { kind: Role, name: infra-deployer, apiGroup: rbac.authorization.k8s.io }
```
Note: no `delete`, no `namespaces`, no cluster scope. The CI token comes from a
manually-created `kubernetes.io/service-account-token` Secret bound to this SA
(k3s/k8s ≥1.24 no longer auto-creates SA token Secrets), stored as
`CD_K8S_SA_TOKEN`. (Confidence: HIGH)

### Pattern 3: Restore drill as an isolated scratch-namespace Job (data flow change)

**What:** Today the restore drill is a **manual runbook** (`docs/backup-restore.md`):
operator `createdb` in the live `postgres-0` pod, `kubectl cp` a dump, `pg_restore`
into `solid_stats_restore_drill`, then `dropdb`. v2 automates it as a **Job in a
scratch namespace** that reads the dump **directly from S3** rather than touching
the production pod.

**When to use:** Independent of CD — can be built in parallel with everything
once the CD foundation exists to apply it.

**Trade-offs:** Running pg inside the Job (ephemeral `postgres:17-alpine`
sidecar or initdb) keeps the live database untouched (the runbook's "do not
restore over the active staging database" rule, now enforced structurally).
Reuses the backup Job's exact S3 access pattern (path-style, `AWS_*` from the
`server-2-runtime` Secret, `S3_ENDPOINT=https://s3.twcstorage.ru`,
`AWS_EC2_METADATA_DISABLED=true`). Needs read of the latest `manifest.json` to
resolve the newest `backups/postgres/<id>/solid_stats.dump`.

**Data flow (new):**
```
S3 backups/postgres/<latest>/solid_stats.dump
      │ aws s3 cp (path-style, creds from secret)
      ▼
restore-drill ns ── Job: ephemeral postgres ── pg_restore --list (gate)
                                              └─ pg_restore into scratch db
                                              └─ smoke: select current_database()
      ▼ assert exit 0, then namespace torn down (ttlSecondsAfterFinished)
```
(Confidence: HIGH — mirrors existing backup Job and runbook.)

### Pattern 4: `web` runtime wiring + edge routing (cutover question)

**What:** `web` slots into `k8s/staging/` between `replay-parser-2` (40) and
`replays-fetcher` (50) as `45-web-config.yaml` (ConfigMap+Service) and
`46-web-deployment.yaml`, mirroring the server-2 30/35 split. Its Service is
then routed by the **host nginx edge**, exactly as `server-2` is today.

**Cutover decision — host-nginx vs k8s ingress/cert-manager:**
The current edge is host-level nginx → server-2 Service, with **no ingress and
no cert-manager** (PROJECT.md and staging.md both state this explicitly). For
v2, **keep host-nginx and automate it** (feature 3: repo-managed vhosts + cert
renewal + ufw). Reasons: (1) single-node k3s with an already-working host edge —
introducing ingress-nginx + cert-manager is net-new operational surface for no
traffic-scaling benefit; (2) the milestone scopes "edge automation: host nginx,
cert renewal, firewall," not an ingress migration; (3) production cutover here
means *pointing the host nginx vhost at the new runtime Service(s) and flipping
DNS/traffic*, not adopting a new ingress stack. **Verdict: host-nginx, automated;
do not adopt ingress/cert-manager in v2.** (Confidence: HIGH — directly from
PROJECT scope.)

## Data Flow

### Deploy flow change

```
v1:  CI ──ssh──► VPS: kubectl create ns; scp secrets; kubectl apply *.yaml
v2:  CI ──WG──► API 10.8.0.1:6443 (as infra-deployer SA):
        render-staging-secrets.py | kubectl apply -f -        (secrets)
        kubectl apply -f k8s/staging/  (ns assumed pre-seeded; SA can't create it)
        kubectl rollout status …  (Role grants get on deploy/statefulset)
```

### Key Data Flows

1. **CD auth:** runner → WG tunnel → API with SA bearer token; TLS verified via
   `10.8.0.1` SAN; authorization via namespaced Role.
2. **Secrets:** unchanged render path (`render-staging-secrets.py`), but piped
   to `kubectl apply -f -` locally on the runner instead of `scp` + remote apply.
3. **Restore drill:** S3 → scratch-ns Job → ephemeral pg → assert. No path
   through `postgres-0`.
4. **S3 lifecycle:** applied once to the bucket; governs expiry of
   `backups/postgres/`, raw replay, and artifact prefixes independently.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| current (single-node staging) | Host-nginx edge + single SA CD is sufficient; no ingress needed |
| add production node/cluster | Reuse the same SA+RBAC + WG-in-CI pattern per environment dir (`k8s/prod/`); only then reconsider ingress/cert-manager |
| multi-operator / token rotation | Move from stored SA token to short-lived `kubectl create token` minted by a bootstrap step, or OIDC |

### Scaling Priorities

1. **First concern:** SA token lifetime/rotation — a stored long-lived token is
   the weakest link; plan rotation early.
2. **Second concern:** WG key management in CI (one `/32` per runner identity);
   reuse the existing peer-provisioning process from `wireguard-access.md`.

## Anti-Patterns

### Anti-Pattern 1: Granting the CD SA cluster-admin or `namespaces:create`

**What people do:** Bind the CI SA to `cluster-admin` so `kubectl create
namespace` keeps working.
**Why it's wrong:** Defeats the entire least-privilege point of moving off SSH;
a leaked CI token becomes cluster takeover.
**Do this instead:** Bootstrap `00`+`05` once as an operator; scope the SA to a
namespaced Role (Pattern 2, option A+C).

### Anti-Pattern 2: Putting the restore-drill manifest in `k8s/staging/`

**What people do:** Drop `restore-job.yaml` into `k8s/staging/` so it deploys
with everything else.
**Why it's wrong:** `deploy-staging.sh` globs `k8s/staging/*.yaml`; the drill
would run on every deploy and its scratch namespace would be created in the
deploy path the SA isn't scoped for.
**Do this instead:** Separate `k8s/restore-drill/` directory + its own script;
keep it out of the deploy glob.

### Anti-Pattern 3: Migrating to ingress/cert-manager during cutover

**What people do:** Treat "production cutover" as a reason to adopt
ingress-nginx + cert-manager.
**Why it's wrong:** Adds two new controllers and a cert-issuance dependency to a
single-node edge that already works; out of milestone scope.
**Do this instead:** Automate the existing host nginx (vhost templates, cert
renewal, ufw) and cut over by repointing the vhost/DNS.

### Anti-Pattern 4: Forgetting `validate-staging.py` is a gate

**What people do:** Add `05-ci-rbac.yaml` / `45-web-*.yaml` but not update
`EXPECTED_MANIFESTS` (and `EXPECTED_WORKLOADS`/`APP_IMAGES` for `web`).
**Why it's wrong:** The `validate` job hard-codes the expected manifest list
(scripts/validate-staging.py lines 17–60); new files either fail validation or
go unchecked.
**Do this instead:** Update the validator alongside every new manifest.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| k3s API `10.8.0.1:6443` | WG tunnel + SA bearer token kubeconfig | SAN already includes `10.8.0.1`; API closed publicly |
| Timeweb S3 `s3.twcstorage.ru` | path-style aws-cli, creds from `server-2-runtime` Secret | reused by backup Job and restore-drill Job; lifecycle rules applied at bucket level |
| GHCR | `ghcr-pull` dockerconfigjson Secret | unchanged; `web` Deployment reuses it |
| Let's Encrypt / ACME (edge) | host certbot/acme.sh renewal + nginx reload | **new**, out-of-cluster |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| CI ↔ cluster | WG + RBAC-scoped SA | replaces SSH; namespace pre-seeded by operator |
| host nginx ↔ k8s Services | proxy_pass to NodePort/ClusterIP of server-2 (+ web) | cutover = repoint vhost |
| deploy path ↔ restore drill | none (separate ns, separate script) | drill independent of CD |
| operator bootstrap ↔ CI SA | operator applies `00`+`05`, CI applies `>=10` | resolves namespace-create chicken-and-egg |

## Suggested Build Order (dependency-aware, across the 6 areas)

| Order | Area | Depends on | Why here |
|-------|------|-----------|----------|
| **1** | **kubectl-native CD** (WG-in-CI, `05-ci-rbac.yaml`, SA token, rewrite deploy script, drop SSH) | operator bootstrap of `00`+`05` | Settled foundation; everything else deploys *through* it. Resolve namespace-create boundary here (operator seeds ns+RBAC once). |
| **2** | **Restore drill** (`k8s/restore-drill/`, `restore-drill.sh`) | CD (1) to apply it; existing backups in S3 | Independent of edge/web/cutover; high recovery value; can run in parallel with 3 once CD lands. |
| **3** | **`web` runtime wiring** (`45/46-web-*.yaml`, validator update) | CD (1) | Manifests + image pin; no traffic yet. Orderable with 2 and 4. |
| **4** | **Edge automation** (`edge/` nginx + cert renewal + ufw) | none on CD; needs `web` Service to route it | Prereq for cutover; can start beside 3. |
| **5** | **S3 lifecycle** (`s3/` policy) | none (touches bucket only) | Fully independent; schedule anytime, but after restore drill confirms retention assumptions are safe. |
| **6** | **Production cutover** | 1–5 (esp. web=3, edge=4) | Last: repoint host-nginx/DNS to the new runtime once CD, web, edge, and recovery confidence exist. |

**Critical-path note:** 1 → (2,3,4,5 in parallel) → 6. The only hard ordering
is CD first and cutover last; the restore drill, web, edge, and S3 lifecycle are
otherwise independent and can be sequenced by capacity.

## Sources

- Repo files: `.planning/PROJECT.md`, `docs/staging.md`, `docs/wireguard-access.md`,
  `docs/backup-restore.md`, `.github/workflows/deploy-staging.yml`,
  `scripts/deploy-staging.sh`, `scripts/render-staging-secrets.py`,
  `scripts/validate-staging.py`, `k8s/staging/*.yaml` (HIGH confidence, primary source)
- `.agents/skills/kubernetes-specialist/SKILL.md` — RBAC least-privilege baseline
- Standard Kubernetes behavior: Namespace is cluster-scoped (a namespaced Role
  cannot grant namespace create); SA token Secrets are no longer auto-created
  since k8s 1.24 (must be created explicitly or minted via `kubectl create token`)

---
*Architecture research for: k3s-on-VPS infrastructure CD, v2.0 production-readiness*
*Researched: 2026-06-11*
