# Stack Research

**Domain:** Infrastructure / kubectl-native CD for a closed k3s cluster (Timeweb VPS), edge automation, S3 lifecycle, PostgreSQL restore drill
**Researched:** 2026-06-11
**Confidence:** HIGH

## Scope

Stack **additions/changes for the v2.0 NEW features only**. The existing validated
stack (GitHub Actions runner, k3s on the VPS, PostgreSQL 17 + RabbitMQ 4
StatefulSets, GHCR images, Timeweb S3 at `https://s3.twcstorage.ru`, `aws-cli`
in the backup CronJob, `render-staging-secrets.py`, `validate-staging.py`) is
**not re-researched**. Everything below plugs into those.

The five integration points that matter:
1. CI runner reaches the closed k3s API (`https://10.8.0.1:6443`) only through a
   WireGuard tunnel brought up **inside the job**.
2. `kubectl` authenticates with a **scoped ServiceAccount + namespace RBAC + a
   long-lived SA token Secret**, replacing `CD_SSH_*`.
3. Edge TLS renewal stays on the **host** (host-nginx is the public edge; k3s has
   no ingress in scope).
4. S3 lifecycle uses **`aws s3api put-bucket-lifecycle-configuration`** against
   `https://s3.twcstorage.ru` (Timeweb supports it — confirmed).
5. Restore drill is a **scripted `pg_restore` Job into a throwaway namespace**.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `niklaskeerl/easy-wireguard-action` | `@v2` (pin commit SHA) | Bring up `wg-quick` tunnel inside the GitHub job from a config in secrets | Smallest action that does exactly the documented manual flow (`apt install wireguard` + `wg-quick up` from a `WG_CONFIG_FILE`). One input, no extra surface. Matches the existing `docs/wireguard-access.md` topology 1:1 (client `[Interface]`/`[Peer]`, `AllowedIPs = 10.8.0.1/32`, split tunnel). Pin to a commit SHA — it is not GitHub-certified. |
| `azure/setup-kubectl` | `@v4` | Install a pinned `kubectl` on the runner | Official, cached, PATH-managed. Pin `version:` to match the k3s server minor (e.g. `v1.31.x`) to stay inside the ±1 skew window. Replaces the implicit "kubectl already on the VPS" assumption now that kubectl runs on the runner. |
| Kubernetes ServiceAccount + long-lived token Secret | k3s/k8s ≥1.24 token model | CI identity against the API | Since 1.24, SAs no longer auto-create token Secrets and `kubectl create token` issues **short-lived bound** tokens (expire, unusable for unattended CD). For CI you must **manually create** a `type: kubernetes.io/service-account-token` Secret with the SA annotation; the controller fills a **non-expiring** token. This is the supported long-lived path. Scope it with a namespace `Role` + `RoleBinding`. |
| `aws-cli` (S3 lifecycle) | v2 (already vendored in backup Job) | `put-bucket-lifecycle-configuration` against Timeweb S3 | Already proven against `https://s3.twcstorage.ru` in `60-postgres-backup.yaml`. Timeweb explicitly documents `aws s3api put-bucket-lifecycle-configuration ... --endpoint-url https://s3.twcstorage.ru` with prefix `Expiration` rules. No new tool needed. |
| `pg_restore` / `pg_dump` (`postgres:17-alpine`) | 17 (match server) | Restore-drill Job | Same image already used for backup. `pg_restore --list` is already the backup gate; the drill extends it to an actual `pg_restore` into a scratch DB. Keep client major == server major. |

### Supporting Libraries / Primitives

| Primitive | Version / API | Purpose | When to Use |
|-----------|---------------|---------|-------------|
| `Role` + `RoleBinding` (namespaced) | `rbac.authorization.k8s.io/v1` | Least-privilege CD permissions in `solid-stats-staging` | Always. Grant only verbs the deploy script uses: `get,list,create,patch,apply(update),delete` on `deployments,statefulsets,services,configmaps,secrets,cronjobs,jobs,pods,namespaces`-scoped. No ClusterRole. Honors the kubernetes-specialist least-privilege rule. |
| Manual SA-token `Secret` | `v1`, `type: kubernetes.io/service-account-token` | Holds the non-expiring CI token + cluster CA | One Secret per CI SA. Read `.data.token` (base64) → GitHub secret `CD_SA_TOKEN`; `.data["ca.crt"]` → `CD_K8S_CA`. |
| `Job` (restore drill) | `batch/v1` | Throwaway `pg_restore` validation | Run on demand (scripted), not a CronJob. `ttlSecondsAfterFinished` + `restartPolicy: Never` + `backoffLimit: 0`. Pulls the latest dump from S3, restores into a scratch DB/namespace, asserts row counts, tears down. |
| `certbot` (host, `--nginx` or `--webroot`) | distro/snap current | Host TLS renewal on the nginx edge | The public edge is **host-nginx, not k8s ingress** → cert-manager does not apply. `certbot renew` via systemd timer is the right tool. See "What NOT to Use". |
| `kubectl --raw='/livez?verbose'` / `kubectl version` | n/a | Post-tunnel API reachability check | First CD step after WG up + token auth, before any apply — fails fast if the tunnel/handshake didn't establish (the known UDP-swallow risk in `wireguard-access.md`). |

### Development / CI Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| GitHub Actions `environment: staging` | Holds the new CD secrets | Add `CD_K8S_API` (`https://10.8.0.1:6443`), `CD_K8S_CA`, `CD_SA_TOKEN`, `WG_CONFIG_FILE`. Remove `CD_SSH_PRIVATE_KEY/HOST/PORT/USER` after cutover. |
| `kubectl apply --server-side` / `--dry-run=server` | Safer applies now that apply runs from CI | Server-side apply + a `--dry-run=server` gate in the `validate` job catches conflicts the current `--validate=false` client apply hides. Optional hardening, not required for MVP. |
| existing `validate-staging.py` | Keep as the manifest gate | Unchanged; runs before deploy as today. |

## How It Wires Together (integration with existing repo)

**Replace the SSH transport in `scripts/deploy-staging.sh` + `deploy-staging.yml`:**

Today: install SSH key → `ssh kubectl apply`. New:
1. `easy-wireguard-action@v2` with `WG_CONFIG_FILE: ${{ secrets.WG_CONFIG_FILE }}` (a full client `wg0.conf` with `Endpoint = <VPS_PUBLIC_IP>:51820`, `AllowedIPs = 10.8.0.1/32`).
2. `azure/setup-kubectl@v4`.
3. Build kubeconfig in-job from `CD_K8S_API` + `CD_K8S_CA` + `CD_SA_TOKEN` (no kubeconfig file copied from the VPS — the SA token replaces the admin `k3s.yaml`).
4. `render-staging-secrets.py | kubectl apply -f -` and `kubectl apply -f k8s/staging/*.yaml` run **locally on the runner against the tunnel** — the `ssh`/`scp` wrapper in `deploy-staging.sh` is deleted; the `kubectl rollout status ...` lines stay verbatim, just without the `ssh` prefix.

**Server-side one-time additions** (committed as manifests, applied once via the current SSH path or by an operator over the existing WG workstation access): the CD `ServiceAccount`, `Role`, `RoleBinding`, and the token `Secret`. The SA does **not** need permission to read its own token Secret; an operator extracts it once and stores it as a GitHub secret.

**S3 lifecycle:** a committed `lifecycle.json` per prefix policy + a small script/Job calling
`aws s3api put-bucket-lifecycle-configuration --bucket "$S3_BUCKET" --lifecycle-configuration file://lifecycle.json --endpoint-url https://s3.twcstorage.ru` (path-style, as the backup Job already sets `addressing_style path`). Reuses the existing `S3_*` secrets and `AWS_EC2_METADATA_DISABLED=true`.

**Restore drill:** a new `Job` manifest + `scripts/restore-drill.sh` that creates a scratch namespace/DB, `aws s3 cp` the newest dump, `pg_restore` it, runs assertion queries, deletes the namespace.

## Installation

No package manager in this repo. Changes are GitHub Actions refs + k8s manifests + scripts:

```yaml
# .github/workflows/deploy-staging.yml (deploy job, replacing SSH steps)
- uses: niklaskeerl/easy-wireguard-action@v2   # pin to commit SHA in practice
  with:
    WG_CONFIG_FILE: ${{ secrets.WG_CONFIG_FILE }}
- uses: azure/setup-kubectl@v4
  with:
    version: 'v1.31.5'   # match k3s server minor
```

```bash
# one-time, extract the long-lived token after applying the SA + Secret manifests
kubectl -n solid-stats-staging get secret solid-stats-cd-token \
  -o jsonpath='{.data.token}' | base64 -d        # -> GitHub secret CD_SA_TOKEN
kubectl -n solid-stats-staging get secret solid-stats-cd-token \
  -o jsonpath='{.data.ca\.crt}' | base64 -d       # -> GitHub secret CD_K8S_CA
```

```bash
# host edge (run on VPS, not in repo CI)
sudo certbot --nginx -d <staging-host>     # then systemd certbot.timer handles renew
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `easy-wireguard-action@v2` | Hand-rolled `apt-get install wireguard-tools` + `wg-quick up` shell step | If you want zero third-party action trust surface. ~6 lines of bash; reproduces the action exactly. Reasonable given the lean-MVP preference — the action is a convenience, not a necessity. |
| `easy-wireguard-action@v2` | `promaton/wg-action`, `rohittp0/wiregaurd` | `promaton/wg-action` is literally "access a remote cluster from GitHub Actions" and is a fine substitute; `rohittp0` adds domain-routing/split-tunnel logic you don't need. Pick whichever has a healthier recent commit history at implementation time. |
| Manual long-lived SA token Secret | OIDC / short-lived `kubectl create token` | Only if you add a token-refresh step or an OIDC issuer. Overkill for one staging cluster; the decision pack already chose a long-lived SA token. |
| Manual long-lived SA token Secret | mTLS client cert for the CD identity | If you'd rather not store a bearer token. More moving parts (CSR signing, rotation) than a single Secret; skip for MVP. |
| `aws s3api` for lifecycle | `mc ilm` (MinIO client) | Only if you already standardize on `mc`. Timeweb documents the `aws s3api` path explicitly and does **not** document `mc`; `aws-cli` is already vendored. No reason to add `mc`. |
| Host `certbot` | k8s `cert-manager` + Traefik/ingress | Only **after** a real cutover that moves the public edge into k3s ingress. While host-nginx is the edge, cert-manager has nothing to issue for and would be dead weight. Revisit in the production-cutover feature if the edge moves into the cluster. |
| `azure/setup-kubectl@v4` | `curl`-install kubectl | Trivial either way; the action gives caching + pinning for free. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| cert-manager + Ingress + ClusterIssuer (now) | The public edge is host-nginx; k3s has **no ingress in scope**. cert-manager would manage certs for resources that don't exist. Scope creep against a lean MVP. | Host `certbot` + systemd `certbot.timer` on the VPS for the current edge. Defer cert-manager to the cutover feature *if* the edge moves into k3s. |
| `kubectl create token` for the CI token | Issues a **short-lived, expiring** bound token (1.24+); unattended CD will start failing on expiry. | Manually-created `type: kubernetes.io/service-account-token` Secret → controller-issued **non-expiring** token. |
| Default ServiceAccount / ClusterRole / `cluster-admin` for CD | Violates least-privilege; a leaked CI token = full cluster. | Dedicated SA + namespaced `Role`/`RoleBinding` limited to `solid-stats-staging` and only the verbs/resources the deploy touches. |
| Copying admin `k3s.yaml` into CI | That kubeconfig carries cluster-admin creds; defeats the scoped-SA goal. | Build kubeconfig in-job from API URL + CA + scoped SA token secrets. |
| Reintroducing SSH/scp into the deploy path | The whole point of v2.0 CD is removing the SSH transport. | `kubectl` over the WG tunnel; pipe rendered secrets via `kubectl apply -f -` (no `scp`). |
| `MFA`/full-tunnel WG in CI (`AllowedIPs = 0.0.0.0/0`) | Routes all runner traffic through the VPS; breaks GHCR/API egress and is unnecessary. | Split tunnel `AllowedIPs = 10.8.0.1/32` (matches `wireguard-access.md`). |
| A CronJob for the restore drill | The drill is an explicit, observed validation, not a schedule. | On-demand `Job` + `scripts/restore-drill.sh`, like `backup-postgres-now.sh`. |
| `mc` (MinIO client) for lifecycle | Adds a tool Timeweb doesn't document and the repo doesn't use. | `aws s3api put-bucket-lifecycle-configuration`. |

## Stack Patterns by Variant

**If the production cutover keeps host-nginx as the edge:**
- Keep TLS on host `certbot`; do not add cert-manager.
- Because the cert lives where nginx terminates TLS — on the host.

**If the cutover moves the public edge into k3s (Traefik ingress):**
- Add `cert-manager` (current `v1.20.x`) + a `ClusterIssuer` (ACME HTTP-01 via the built-in k3s Traefik), and retire host `certbot`.
- Because then there is an in-cluster ingress object for cert-manager to issue and attach certs to.

**If you want minimal third-party trust in CI:**
- Replace the WG action with an inline `wireguard-tools` install + `wg-quick up` step.
- Because it removes a non-GitHub-certified dependency for ~6 lines of bash.

## Version Compatibility

| Component | Compatible With | Notes |
|-----------|-----------------|-------|
| `kubectl` (via `azure/setup-kubectl@v4`) | k3s server minor ±1 | Pin `version:` to the running k3s minor; check `kubectl version` against the cluster. |
| Long-lived SA token Secret | k8s/k3s ≥1.24 | Behavior is identical on k3s — k3s tracks upstream token model. Requires the `kubernetes.io/service-account.name` annotation on the Secret. |
| `aws s3api ... --endpoint-url https://s3.twcstorage.ru` | Timeweb S3 (path-style) | Lifecycle confirmed supported by Timeweb docs; reuse `addressing_style path` + `AWS_EC2_METADATA_DISABLED=true` as in the backup Job. |
| `pg_restore` 17 | PostgreSQL 17 server | Same `postgres:17-alpine` image as backup; keep majors aligned. |
| cert-manager `v1.20.x` (only if cutover moves edge into k3s) | recent k8s/k3s | LTS line is 1.17; 1.18/1.19/1.20 are current supported releases. Not needed while edge is host-nginx. |

## Sources

- Existing repo: `docs/wireguard-access.md`, `.github/workflows/deploy-staging.yml`, `scripts/deploy-staging.sh`, `k8s/staging/60-postgres-backup.yaml`, `.planning/PROJECT.md` — HIGH (authoritative for current state)
- `niklaskeerl/easy-wireguard-action` (GitHub Marketplace) — v2, single `WG_CONFIG_FILE` input, uses `wg-quick` — MEDIUM (third-party, not GitHub-certified; pin SHA)
- `Azure/setup-kubectl` — v4, `version:` input, official — HIGH
- cert-manager releases (cert-manager.io / GitHub releases) — current 1.20.x, LTS 1.17 — HIGH
- Kubernetes SA token model ≥1.24 (manual `kubernetes.io/service-account-token` Secret = long-lived; `kubectl create token` = short-lived bound) — HIGH (well-established upstream behavior)
- Timeweb S3 object-lifecycle docs (`timeweb.cloud/docs/s3-storage/supported-features/object-lifecycle`) — confirms `aws s3api put-bucket-lifecycle-configuration ... --endpoint-url https://s3.twcstorage.ru` with prefix `Expiration` rules; no `mc` documented — HIGH

---
*Stack research for: v2.0 kubectl-native CD + production-readiness infra*
*Researched: 2026-06-11*
