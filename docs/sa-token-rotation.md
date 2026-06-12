# ServiceAccount Token and WireGuard Key Rotation

This runbook covers periodic rotation of the CI deployer ServiceAccount token and the
WireGuard key pair used by GitHub Actions to reach the k3s API. Long-lived SA tokens are
a security risk without rotation discipline — CD-09 requires documented cadence and
procedure. For the one-time initial setup that creates these credentials, see
[`docs/operator-bootstrap.md`](operator-bootstrap.md).

**Important ordering rule:** Update GitHub environment secrets **before** rotating the VPS
side. This ensures no deploy fails mid-rotation because the runner still holds the old
credentials when it connects. Both rotations must happen in the same maintenance window.

## Overview

| | |
|---|---|
| **Owner** | Operator — the person who performed the initial bootstrap |
| **Cadence** | At minimum quarterly; rotate immediately if a token or key is suspected compromised |
| **Scope** | SA token (`K8S_TOKEN`) and WireGuard key pair (`WG_PRIVATE_KEY` + `WG_PEER_PUBLIC_KEY`) — both in the same window |
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

## Step 2: Rotate the WireGuard Key Pair

**2a. Generate a new WireGuard private key** for the CI runner peer:

```bash
wg genkey
```

Store the output securely (e.g. a password manager). Do **not** commit it to git.

**2b. Derive the corresponding public key:**

```bash
echo "<private-key>" | wg pubkey
```

Replace `<private-key>` with the value from Step 2a.

**2c. Update GitHub environment secrets** (Settings → Environments → staging):

| GitHub Secret | New value |
|---------------|-----------|
| `WG_PRIVATE_KEY` | New private key from Step 2a |
| `WG_PEER_PUBLIC_KEY` | New public key from Step 2b |

**Never commit key values to git.**

**2d. Update the VPS WireGuard configuration:**

On the VPS, replace the CI peer's `PublicKey` entry in the WireGuard interface config
(typically `/etc/wireguard/wg0.conf`) with the new public key from Step 2b, then reload
without dropping existing peers:

```bash
sudo wg syncconf wg0 <(sudo wg-quick strip wg0)
```

If `wg syncconf` is unavailable on the VPS distribution, restart the interface instead:

```bash
sudo systemctl restart wg-quick@wg0
```

**2e. Verify the handshake** from the VPS after triggering a CI deploy (or after the
runner brings up the tunnel manually):

```bash
sudo wg show wg0 latest-handshakes
```

The CI peer entry must show a recent timestamp (within the last few minutes). A timestamp
of `0` means no handshake has occurred yet.

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
| `WireGuard handshake did not complete` | VPS peer config not yet updated, or new public key does not match new private key | Verify the VPS config has the correct public key from Step 2b; if keys were regenerated again, redo Step 2 end-to-end |
| `WG_PEER_PUBLIC_KEY` rejected | Public key derived from wrong private key | Regenerate the key pair (Steps 2a–2b) and update both secrets |
| Rotation fails mid-window | Partial update — old GitHub secret still valid | Revert `K8S_TOKEN` or `WG_PRIVATE_KEY` to the previous value while diagnosing; the old credentials remain valid until the VPS side is also rotated |

## Related Documents

- [`docs/operator-bootstrap.md`](operator-bootstrap.md) — initial namespace, RBAC, and
  WireGuard setup (first rotation follows the same Secret deletion pattern in Step 2)
