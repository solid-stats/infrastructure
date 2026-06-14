# k3s API Access via SSH Local-Forward

The k3s API server (`6443`) is **not exposed publicly** — it is closed at both the
host firewall (ufw `default deny incoming`) and the Timeweb perimeter firewall. To run
`kubectl` against the staging cluster from a workstation **without SSHing into the VPS
and running kubectl there**, open an SSH local-forward; the API is then reachable at
`127.0.0.1:16443` on the operator machine.

## Topology

```
Operator machine (127.0.0.1:16443)
        |
        | SSH local-forward  (-L 16443:127.0.0.1:6443)
        |
VPS (127.0.0.1:6443 — k3s API, private, never on public interface)
```

6443 is never reachable on the VPS public IP — only through the SSH forward to
`127.0.0.1:6443` inside the VPS.

## CI path (automated — scripts/ssh-tunnel-up.sh)

`scripts/ssh-tunnel-up.sh` is called by the GitHub Actions deploy workflow:

1. Opens `ssh -fN -L 16443:127.0.0.1:6443 ${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}`.
2. Fail-closed: probes `127.0.0.1:16443` until reachable (or timeout → exit 1).
3. `scripts/kubeconfig-setup.sh` then builds a kubeconfig pointing kubectl at
   `https://127.0.0.1:16443` with `--tls-server-name=10.8.0.1`.

**TLS note:** The k3s CA certificate was issued with `10.8.0.1` in its Subject Alternative
Names (see `docs/operator-bootstrap.md` Step 5). Because kubectl connects over
`127.0.0.1:16443`, TLS verification would fail without `--tls-server-name=10.8.0.1` to
tell kubectl which SAN to match. This SAN handling is **load-bearing** — never remove it.

Secrets consumed by the CI scripts (GitHub `staging` environment):

| Secret | Purpose |
|--------|---------|
| `DEPLOY_SSH_PRIVATE_KEY` | Private key for the forward-only VPS user |
| `DEPLOY_SSH_KNOWN_HOSTS` | Pinned VPS host key (`ssh-keyscan -p 22 <host>` output) |
| `DEPLOY_SSH_HOST` | VPS SSH hostname or IP |
| `DEPLOY_SSH_USER` | Forward-only VPS username |

## Operator path (manual)

Open the forward in a background SSH session:

```bash
ssh -fN -L 16443:127.0.0.1:6443 <forward-only-user>@<VPS_HOST>
```

Or as a foreground session (Ctrl-C to close):

```bash
ssh -N -L 16443:127.0.0.1:6443 <forward-only-user>@<VPS_HOST>
```

Then use kubectl with the `tls-server-name` flag:

```bash
kubectl --server=https://127.0.0.1:16443 \
        --tls-server-name=10.8.0.1 \
        --certificate-authority=<path-to-k3s-ca.crt> \
        get nodes
```

Or build a kubeconfig entry:

```yaml
clusters:
- cluster:
    server: https://127.0.0.1:16443
    tls-server-name: 10.8.0.1
    certificate-authority-data: <base64-k3s-ca>
  name: solid-stats-staging
```

## Forward-only VPS user

A dedicated non-login user is created on the VPS. Its `~/.ssh/authorized_keys` entry is
locked with the following options prefix, restricting the key to opening only the
local-forward to the k3s API and running no commands:

```
restrict,port-forwarding,permitopen="127.0.0.1:6443",command="/bin/false" <PUBLIC_KEY>
```

Replace `<PUBLIC_KEY>` with the operator or CI public key. Options breakdown:

- `restrict` — disables all SSH capabilities except those explicitly re-enabled below
- `port-forwarding` — re-enables TCP port-forwarding (required for `-L`)
- `permitopen="127.0.0.1:6443"` — limits forwarding to exactly `127.0.0.1:6443`
- `command="/bin/false"` — forces immediate exit if a session is attempted; no shell access

## Notes

- **TLS is always verified** — never use `--insecure-skip-tls-verify`. If cert validation
  fails, the SAN patch in `docs/operator-bootstrap.md` Step 5 must be applied.
- **Happ VPN / always-on VPN bypass:** if the operator machine runs an always-on VPN,
  route traffic to `<VPS_HOST>` outside the VPN tunnel. Otherwise the SSH connection is
  swallowed by the VPN and the local-forward never establishes. Add a host-specific
  policy route to the VPS IP that bypasses the VPN interface.
- The `10.8.0.1` SAN in the k3s serving certificate is a historical artifact of the
  previous access setup. The SAN remains in the cert and is reused by
  `--tls-server-name=10.8.0.1` for TLS verification over the SSH local-forward.
  Removing it would require regenerating the k3s serving certificate and updating all
  kubeconfigs.
