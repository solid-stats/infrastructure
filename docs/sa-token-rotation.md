# ServiceAccount Token and CI SSH Key Rotation

This runbook covers periodic rotation of the CI deployer ServiceAccount token and the
forward-only CI SSH key used by GitHub Actions to reach the k3s API over the SSH
local-forward. Long-lived SA tokens are a security risk without rotation discipline —
CD-09 requires documented cadence and procedure. For the one-time initial setup that
creates these credentials, see
[`docs/operator-bootstrap.md`](operator-bootstrap.md).

**Important ordering rule:** Update GitHub environment secrets **before** rotating the VPS
side. This ensures no deploy fails mid-rotation because the runner still holds the old
credentials when it connects. Both rotations must happen in the same maintenance window.

## Overview

| | |
|---|---|
| **Owner** | Operator — the person who performed the initial bootstrap |
| **Cadence** | At minimum quarterly; rotate immediately if a token or key is suspected compromised |
| **Scope** | SA token (`K8S_TOKEN`) and CI SSH key (`DEPLOY_SSH_PRIVATE_KEY`, plus the matching public key on the VPS forward-only user) — both in the same window |
| **Window rule** | Update GitHub secrets first, then rotate on the VPS |

## Step 1: Rotate the ServiceAccount Token

**1a. Delete the old token Secret:**

```bash
kubectl delete secret ci-deployer-token -n solid-stats-staging
```

**1b. Re-apply the RBAC manifest** to recreate the Secret (the Secret definition lives in
`k8s/staging/01-ci-rbac.yaml`; deleting and re-applying forces the control plane to
generate a new token):

```bash
kubectl apply -f k8s/staging/01-ci-rbac.yaml
```

**1c. Wait for the new token to be populated** (a few seconds) and confirm it is non-empty:

```bash
kubectl get secret ci-deployer-token \
  -n solid-stats-staging \
  -o jsonpath='{.data.token}' | base64 -d | wc -c
```

The command must print a non-zero length. If it prints `0`, wait 5 seconds and retry —
the control plane may still be populating the token.

**1d. Extract the new token:**

```bash
kubectl get secret ci-deployer-token \
  -n solid-stats-staging \
  -o jsonpath='{.data.token}' | base64 -d
```

**1e. Update the GitHub environment secret:**

In **Settings → Environments → staging**, update `K8S_TOKEN` with the value from the
command above. **Never commit the token value to git.**

## Step 2: Rotate the CI SSH Key

**2a. Generate a new SSH keypair** for the forward-only CI user:

```bash
ssh-keygen -t ed25519 -N '' -f /tmp/ci-forward-key
```

This creates `/tmp/ci-forward-key` (private) and `/tmp/ci-forward-key.pub` (public).
Store the private key securely (e.g. a password manager). Do **not** commit it to git.

**2b. Update GitHub environment secrets** (Settings → Environments → staging):

| GitHub Secret | New value |
|---------------|-----------|
| `DEPLOY_SSH_PRIVATE_KEY` | Contents of `/tmp/ci-forward-key` (include the trailing newline) |

Refresh `DEPLOY_SSH_KNOWN_HOSTS` only if the VPS host key changed (rare — host key
changes on OS reinstall or SSH server reconfiguration). If needed:

```bash
ssh-keyscan -p 22 <VPS_HOST>
```

**Never commit key values to git.**

**2c. Update the VPS forward-only user's authorized_keys:**

On the VPS, replace the existing public key line in the forward-only user's
`~/.ssh/authorized_keys` with the new public key from Step 2a, keeping the options prefix:

```
restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false" <NEW_PUBLIC_KEY>
```

Replace `<NEW_PUBLIC_KEY>` with the contents of `/tmp/ci-forward-key.pub`. The options
prefix (`restrict,port-forwarding,permitopen=...`) must remain exactly as-is — it limits
the key to opening only the local-forward to the k3s API.

**2d. Verify the rotation** by triggering a CI deploy (branch push or `workflow_dispatch`).
Confirm the SSH local-forward opens successfully and `kubectl auth whoami` shows the
`ci-deployer` identity (not `system:anonymous`).

**2e. Delete the temporary key files** from the operator workstation:

```bash
rm -f /tmp/ci-forward-key /tmp/ci-forward-key.pub
```

## Step 3: Verify Both Rotations

**3a.** Trigger the deploy workflow on a branch or via `workflow_dispatch`. Both the
**Validate manifests** and **Dry-run deploy (server-side)** jobs must complete without
authentication errors.

**3b.** In the dry-run job log, confirm `kubectl auth whoami` output shows the
`ci-deployer` ServiceAccount identity, **not** `system:anonymous`.

**3c.** In the deploy job log (if triggered on `master`), confirm no `Unauthorized`
errors appear during `kubectl apply` or `kubectl rollout status`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Unauthorized` after token rotation | `K8S_TOKEN` in GitHub still holds the old token | Re-extract the token (Step 1d) and update the secret again |
| `secret has no token field` / empty token | Control plane still populating the token | Wait 5 seconds and retry Step 1c–1d |
| SSH local-forward fails to open / `Permission denied (publickey)` | New key not yet in the VPS forward-only user's authorized_keys, or `DEPLOY_SSH_PRIVATE_KEY` secret missing its trailing newline | Verify the VPS authorized_keys has the new public key with the correct options prefix; re-set `DEPLOY_SSH_PRIVATE_KEY` ensuring a trailing newline |
| `ExitOnForwardFailure` / port 6443 refused | `permitopen` does not match `127.0.0.1:6443` on the forward-only user | Check the authorized_keys options prefix on the VPS |
| Rotation fails mid-window | Partial update — old GitHub secret still valid | Revert `DEPLOY_SSH_PRIVATE_KEY` to the previous value while diagnosing; the old credentials remain valid until the VPS side is also rotated |

## Related Documents

- [`docs/operator-bootstrap.md`](operator-bootstrap.md) — initial namespace, RBAC, and
  SSH-tunnel setup (first rotation follows the same pattern as Step 2)
