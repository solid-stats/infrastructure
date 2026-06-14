# Operator Bootstrap: Namespace, CI RBAC, and k3s Certificate SAN

This is a **one-time operator action**. CI (GitHub Actions) never creates the namespace and
never applies `k8s/staging/01-ci-rbac.yaml`. After this bootstrap is complete, all subsequent
deploys are fully automated via the workflow in `.github/workflows/deploy-staging.yml`.

For token and SSH key rotation after the initial setup, see
[`docs/sa-token-rotation.md`](sa-token-rotation.md).

## Prerequisites

- `kubectl` access to the k3s cluster with admin privileges (admin kubeconfig)
- Git clone of this repository (`k8s/staging/01-ci-rbac.yaml` present)
- Access to GitHub repository environment secrets (**Settings → Environments → staging**)
- `openssl` available on the operator machine (for SAN verification in Step 5)

## Step 1: Create the namespace

```bash
kubectl create namespace solid-stats-staging
```

If the namespace already exists the command returns an error — that is safe to ignore.

> **Important:** CI never creates the namespace. If a deploy job fails with
> "namespace not found", the operator must re-run this step.

Verify:

```bash
kubectl get namespace solid-stats-staging
```

## Step 2: Apply the RBAC bootstrap manifest

```bash
kubectl apply -f k8s/staging/01-ci-rbac.yaml
```

This creates four resources in `solid-stats-staging`:

- `ServiceAccount` **ci-deployer** — identity used by CI
- `Secret` **ci-deployer-token** — long-lived token (k8s ≥1.24 requires explicit creation)
- `Role` **ci-deployer** — namespace-scoped permissions for `kubectl apply` and `kubectl rollout status`
- `RoleBinding` **ci-deployer** — binds the Role to the ServiceAccount

The Kubernetes control plane auto-populates `Secret.data.token` within a few seconds of
the Secret being created. Wait 5 seconds before proceeding to Step 3.

## Step 3: Verify RBAC

Check what the ServiceAccount is allowed to do:

```bash
kubectl auth can-i --list \
  --as=system:serviceaccount:solid-stats-staging:ci-deployer \
  -n solid-stats-staging
```

Expected output includes `get`, `list`, `watch`, `create`, `update`, `patch` verbs on
`deployments`, `statefulsets`, `cronjobs`, `configmaps`, `secrets`, `services`,
`persistentvolumeclaims`, and `serviceaccounts`; and `get`, `list`, `watch` on `pods`.
The output must **not** show cluster-scoped resources (namespaces, nodes, clusterroles).

Confirm the token has been populated (prints first 20 characters):

```bash
kubectl get secret ci-deployer-token \
  -n solid-stats-staging \
  -o jsonpath='{.data.token}' | base64 -d | cut -c1-20
```

If the output is empty, wait 5 more seconds and retry — the control plane may still be
populating the token.

## Step 4: Extract token and CA for GitHub secrets

Extract the ServiceAccount token:

```bash
kubectl get secret ci-deployer-token \
  -n solid-stats-staging \
  -o jsonpath='{.data.token}' | base64 -d
```

Extract the cluster CA certificate:

```bash
kubectl get secret ci-deployer-token \
  -n solid-stats-staging \
  -o jsonpath='{.data.ca\.crt}' | base64 -d
```

Store the values as GitHub environment secrets (Settings → Environments → staging):

| GitHub Secret | Value source |
|---------------|--------------|
| `K8S_TOKEN` | SA token from command above |
| `K8S_CA_CERT` | CA cert from command above |

**NEVER commit these values to git.**

## Step 5: Patch k3s API server certificate SAN (if 10.8.0.1 is not already in SANs)

Verify the current certificate SANs:

```bash
openssl s_client -connect 10.8.0.1:6443 </dev/null 2>/dev/null \
  | openssl x509 -noout -text \
  | grep -A1 'Subject Alternative Name'
```

The output must include `IP Address:10.8.0.1`. If it does not, proceed with the patch:

1. Add or create `/etc/rancher/k3s/config.yaml` on the VPS:

   ```yaml
   tls-san:
     - "10.8.0.1"
   ```

2. Remove the old server certificates so k3s regenerates them on restart:

   ```bash
   sudo rm -f \
     /var/lib/rancher/k3s/server/tls/server-ca.crt \
     /var/lib/rancher/k3s/server/tls/server-ca.key \
     /var/lib/rancher/k3s/server/tls/serving-kube-apiserver.crt \
     /var/lib/rancher/k3s/server/tls/serving-kube-apiserver.key
   ```

3. Restart k3s:

   ```bash
   sudo systemctl restart k3s
   ```

4. Re-verify the SAN after restart:

   ```bash
   openssl s_client -connect 10.8.0.1:6443 </dev/null 2>/dev/null \
     | openssl x509 -noout -text \
     | grep -A1 'Subject Alternative Name'
   ```

> **Never use `--insecure-skip-tls-verify` in kubectl commands.** If certificate
> validation fails, fix the SAN — do not bypass TLS verification.

After regenerating the certificate, re-extract the CA cert (Step 4) because the old CA
may have changed, and update the `K8S_CA_CERT` GitHub secret accordingly.

## Step 6: Configure SSH tunnel secrets in GitHub

CI reaches the k3s API via an SSH local-forward (`scripts/ssh-tunnel-up.sh`) to a
forward-only SSH user on the VPS. The script opens `ssh -fN -L 16443:127.0.0.1:6443`
to `${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}` and fail-closed probes `127.0.0.1:16443`.
Port 6443 is **never exposed externally** — it is reached only through this forward to
`127.0.0.1:6443` inside the VPS.

Add the following secrets to the GitHub **staging** environment:

| GitHub Secret | Description |
|---------------|-------------|
| `DEPLOY_SSH_PRIVATE_KEY` | Forward-only SSH private key for the CI runner |
| `DEPLOY_SSH_KNOWN_HOSTS` | Pinned host key for the VPS (`ssh-keyscan -p 22 <host>` output) |
| `DEPLOY_SSH_HOST` | VPS SSH host (hostname or IP) |
| `DEPLOY_SSH_USER` | The forward-only VPS username |

**Forward-only VPS user:** create a dedicated non-login user whose `authorized_keys` entry
is locked with the options prefix:

```
restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false" <PUBLIC_KEY>
```

This ensures the key can **only** open the local-forward to the k3s API — it cannot run
any commands or open any other port. The `restrict` option disables all other SSH
capabilities (agent forwarding, X11, pty, etc.).

## Verification

Once all six steps are complete, trigger the PR validation path to confirm end-to-end
connectivity:

1. Open a draft pull request against `master`.
2. The **Validate manifests** and **Dry-run deploy (server-side)** jobs must pass.
3. In the dry-run job logs, confirm `kubectl auth whoami` output does **not** contain
   `system:anonymous`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `x509: certificate is valid for X, not 10.8.0.1` | SAN not patched | Repeat Step 5 |
| `Forbidden: namespaces is forbidden` | CI tried to create namespace | Check workflow YAML — remove any `kubectl create namespace` step |
| `secret has no token field` / empty token | Control plane has not yet populated the token | Wait 5 seconds and retry Step 3 |
| `Load key ... error in libcrypto` | `DEPLOY_SSH_PRIVATE_KEY` secret is missing its trailing newline | Re-set the secret ensuring the key value ends with a newline |
| `Permission denied (publickey)` | Key not yet authorized on the VPS forward-only user, or wrong `DEPLOY_SSH_USER` | Verify the public key is in the forward-only user's `authorized_keys` and the username matches `DEPLOY_SSH_USER` |
| `Unauthorized` after token extraction | Token extracted before control plane populated it | Re-extract token (Step 4) and update `K8S_TOKEN` |
