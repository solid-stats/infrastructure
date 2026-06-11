# Remote kubectl Access via WireGuard

The k3s API server (`6443`) is **not exposed publicly** — it is closed at both the
host firewall (ufw) and the Timeweb perimeter firewall. To run `kubectl` against the
staging cluster from a workstation **without SSHing into the VPS and running kubectl
there**, connect over a WireGuard tunnel; the API is then reachable only via the
tunnel IP.

## Topology

| Node            | WireGuard IP | Notes                                   |
|-----------------|--------------|-----------------------------------------|
| VPS (k3s)       | `10.8.0.1`   | public endpoint `<VPS_PUBLIC_IP>:51820` |
| Workstation     | `10.8.0.<N>` | one unique `/32` per operator           |

k3s API is served at `https://10.8.0.1:6443`, reachable **only through the tunnel**.

## Server-side setup (one-time, already applied on the VPS)

1. Install: `apt install wireguard`
2. `/etc/wireguard/wg0.conf`:
   ```ini
   [Interface]
   Address = 10.8.0.1/24
   ListenPort = 51820
   PrivateKey = <SERVER_PRIVATE_KEY>

   # one [Peer] block per operator, each with a unique 10.8.0.<N>/32
   [Peer]
   PublicKey = <OPERATOR_PUBLIC_KEY>
   AllowedIPs = 10.8.0.2/32
   ```
3. Enable: `systemctl enable --now wg-quick@wg0`
4. Add the WG IP to the k3s API certificate SANs — `/etc/rancher/k3s/config.yaml`:
   ```yaml
   tls-san:
     - 10.8.0.1
   ```
   then `systemctl restart k3s` (regenerates the serving cert).
5. Firewall:
   - `ufw allow in on wg0 to any port 6443 proto tcp` — API reachable only on the tunnel interface.
   - Open **`51820/udp` inbound** at the Timeweb perimeter firewall.
   - `6443` stays closed to the public on both layers.

## Client-side setup (per operator)

1. Install WireGuard (Linux: `apt install wireguard`; kernel ≥ 5.6 ships the module).
2. Generate a keypair:
   ```sh
   wg genkey | tee privatekey | wg pubkey > publickey
   ```
3. Send your **public** key to whoever administers the VPS — they add a `[Peer]` block
   with your assigned `10.8.0.<N>/32`.
4. `/etc/wireguard/wg0.conf`:
   ```ini
   [Interface]
   Address = 10.8.0.<N>/24
   PrivateKey = <YOUR_PRIVATE_KEY>

   [Peer]
   PublicKey = <SERVER_PUBLIC_KEY>
   Endpoint = <VPS_PUBLIC_IP>:51820
   AllowedIPs = 10.8.0.1/32        # only the cluster IP — split tunnel, not all traffic
   PersistentKeepalive = 25
   ```
5. Bring it up and verify the tunnel:
   ```sh
   sudo systemctl enable --now wg-quick@wg0
   ping 10.8.0.1
   ```
6. Fetch and rewrite the kubeconfig:
   ```sh
   scp <ssh-user>@<VPS_PUBLIC_IP>:/etc/rancher/k3s/k3s.yaml ~/.kube/solidstats2.yaml
   # point it at the tunnel IP and name the context
   sed -i 's#https://127.0.0.1:6443#https://10.8.0.1:6443#; s/: default/: solidstats2/g' ~/.kube/solidstats2.yaml
   ```
   Optionally merge into the main config:
   ```sh
   KUBECONFIG=~/.kube/config:~/.kube/solidstats2.yaml kubectl config view --flatten > /tmp/m && mv /tmp/m ~/.kube/config
   ```
7. Use it:
   ```sh
   kubectl config use-context solidstats2
   kubectl get nodes
   kubectl -n solid-stats-staging get pods
   ```

## Notes

- **Private keys never leave the machine that generated them, and are never committed.**
  Only public keys are exchanged.
- The API server (`6443`) is reachable **only through the tunnel** — closed at ufw and
  the Timeweb perimeter.
- If your workstation routes traffic through **another VPN/tunnel**, make sure traffic
  to `<VPS_PUBLIC_IP>` bypasses it (a host policy route to the endpoint IP) — otherwise
  the WireGuard handshake (UDP) is swallowed by the other tunnel and the connection
  never establishes.
