# Operator Bootstrap: Namespace, CI RBAC, and k3s Certificate SAN

This is a **one-time operator action**. CI (GitHub Actions) never creates the namespace and
never applies `k8s/staging/01-ci-rbac.yaml`. After this bootstrap is complete, all subsequent
deploys are fully automated via the workflow in `.github/workflows/deploy-staging.yml`.

For token and WireGuard key rotation after the initial setup, see
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

## Step 6: Configure WireGuard secrets in GitHub

The CI runner connects to the k3s API server over a WireGuard tunnel (peer IP `10.8.0.2`,
VPS WireGuard IP `10.8.0.1`). Add the following secrets to the GitHub **staging** environment:

| GitHub Secret | Description |
|---------------|-------------|
| `WG_PRIVATE_KEY` | WireGuard private key for the CI runner peer |
| `WG_PEER_PUBLIC_KEY` | WireGuard public key of the VPS endpoint |
| `WG_ENDPOINT` | VPS WireGuard endpoint in `HOST:51820` format |

On the VPS, add the CI runner peer to the WireGuard interface configuration:

```ini
[Peer]
PublicKey = <CI runner WireGuard public key>
AllowedIPs = 10.8.0.2/32
```

Then reload WireGuard on the VPS:

```bash
sudo wg syncconf wg0 <(sudo wg showconf wg0)
```

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
| `WireGuard handshake did not complete` | 51820/udp egress blocked | Check VPS firewall; ensure UDP 51820 is open; check GitHub runner network |
| `Unauthorized` after token extraction | Token extracted before control plane populated it | Re-extract token (Step 4) and update `K8S_TOKEN` |
