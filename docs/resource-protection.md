# Host Resource Protection: Swap Provisioning (PREP-02)

## Purpose and Important Caveat

This runbook provisions persistent host swap on the staging VPS for **host-process relief
only** — benefiting systemd, kubelet, and containerd when they briefly spike beyond
available RAM.

**Pods receive zero swap.** k3s uses `swapBehavior: NoSwap` by default and this runbook
preserves that default. Even after swap is active on the host, no pod can use it. See
[k3s issue #12677](https://github.com/k3s-io/k3s/issues/12677) for confirmation that
`NodeSwap` / `LimitedSwap` allocation does not work reliably in k3s even when configured.

> **Swap is NOT a substitute for pod memory limits.** Pod OOM protection comes from
> PriorityClass (`app-critical` ≫ `obs-background`) and Guaranteed QoS
> (requests == limits), not from swap. Do not omit or relax pod resource limits on
> the assumption that host swap will absorb overruns — it will not reach pods.

---

## Pre-check: Confirm Disk Space Before Sizing Swap

Before allocating a swapfile, verify available disk space on the root filesystem.
SSH into the staging VPS and run:

```bash
ssh root@89.223.124.200
df -h /
```

Alternatively, run the preflight snapshot (requires kubectl access via WireGuard):

```bash
bash scripts/resource-preflight.sh
```

The default swapfile size is **2 G**. If the root filesystem has less than 3 G free,
reduce the size accordingly. Any size > 0 satisfies PREP-02.

---

## Step 1: Provision the Swapfile

Run the following commands **on the staging VPS** (over SSH as root). The remote shell
is **fish** — these are plain single-line commands with no heredocs.

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
```

Persist the swap entry across reboots:

```bash
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
```

Set a conservative swappiness to keep the host from swapping eagerly:

```bash
echo 'vm.swappiness=10' >> /etc/sysctl.d/99-swap.conf
sysctl -p /etc/sysctl.d/99-swap.conf
```

---

## Step 2: Create the kubelet Drop-in (NoSwap)

The k3s kubelet refuses to start if swap is present unless `failSwapOn: false` is set.
The drop-in also pins `swapBehavior: NoSwap` so pods continue to receive zero swap
even as the host has swap active.

Create the drop-in directory:

```bash
mkdir -p /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/
```

Write the drop-in file. Because the remote shell is fish and heredocs are not available,
use one of the following methods:

**Option A — `tee` with a bash subshell (must be run from a bash session or `bash -c`):**

```bash
bash -c 'cat > /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf << EOF
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
EOF'
```

**Option B — write lines individually (fish-compatible):**

```bash
printf 'apiVersion: kubelet.config.k8s.io/v1beta1\nkind: KubeletConfiguration\nfailSwapOn: false\nmemorySwap:\n  swapBehavior: NoSwap\n' > /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf
```

**Option C — use an editor on the VPS** (e.g. `nano` or `vi`) to create
`/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf` with this content:

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
```

Restart k3s to apply the kubelet configuration:

```bash
systemctl restart k3s
```

---

## Step 3: Fallback — If k3s Ignores the Drop-in

Some k3s versions do not honour the `kubelet.conf.d/` drop-in path (Pitfall 4).
Symptom: `systemctl status k3s` shows an error like:

```
failed to run Kubelet: ... swap memory is not supported
```

If this occurs, add the kubelet argument to `/etc/rancher/k3s/config.yaml` instead:

```bash
grep -q 'kubelet-arg' /etc/rancher/k3s/config.yaml \
  || echo 'kubelet-arg: ["fail-swap-on=false"]' >> /etc/rancher/k3s/config.yaml
systemctl restart k3s
```

If `config.yaml` already has a `kubelet-arg` list, add `"fail-swap-on=false"` to the
existing list rather than creating a duplicate key.

---

## Step 4: Verify

Run all verification commands on the staging VPS:

```bash
# Swap is visible and has a non-zero size
free -h

# Swapfile is listed as an active swap device
grep swapfile /proc/swaps
# or:
swapon --show

# Swap entry is persisted in fstab
grep swap /etc/fstab

# k3s is running (must print "active")
systemctl is-active k3s

# Node is Ready (requires admin kubeconfig on the VPS)
kubectl get nodes
```

Expected results:

| Check | Expected |
|-------|----------|
| `free -h` Swap row | Shows configured size (e.g. `2.0G total`) |
| `/proc/swaps` | `/swapfile` entry present |
| `/etc/fstab` | `/swapfile swap swap defaults 0 0` line present |
| `systemctl is-active k3s` | `active` |
| `kubectl get nodes` | Node status `Ready` |

**Reboot-survival test** (operator discretion — not required for PREP-02 sign-off):

```bash
reboot
# After boot:
free -h
grep swapfile /proc/swaps
systemctl is-active k3s
kubectl get nodes
```

---

## Notes

- **vm.swappiness=10** keeps the kernel from swapping aggressively; the host will only
  use swap as a last resort before an OOM condition.
- **NoSwap is the default** k3s behaviour. This runbook makes it explicit in the drop-in
  so a future k3s upgrade or kubelet restart cannot silently change it.
- **Pod memory limits remain mandatory.** Swap does not change the eviction model:
  kubelet evicts by PriorityClass first, QoS second. Guaranteed QoS pods (requests ==
  limits) are the last evicted by the kubelet and receive lower OOM scores from the
  kernel OOM killer.
