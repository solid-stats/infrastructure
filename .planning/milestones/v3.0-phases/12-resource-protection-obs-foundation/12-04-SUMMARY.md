---
phase: 12-resource-protection-obs-foundation
plan: "04"
subsystem: host-staging-node
status: complete
tags: [host, swap, k3s, kubelet, docs, prep-02]

dependency_graph:
  requires:
    - 12-01 (resource-preflight.sh to baseline disk before sizing swap)
  provides:
    - Persistent 2G host swap active on the staging node (host-process relief only)
    - docs/resource-protection.md operator runbook with the NoSwap caveat
  affects:
    - docs/resource-protection.md
    - "live staging VPS: /swapfile, /etc/fstab, /etc/sysctl.d/99-swap.conf, kubelet 20-swap.conf drop-in"

tech_stack:
  added: []
  patterns:
    - host swap as host-process relief only (NoSwap → pods get zero swap)
    - explicit kubelet drop-in pre-staged at /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf

key_files:
  created:
    - docs/resource-protection.md
  modified: []

decisions:
  - "Did NOT restart k3s: k3s v1.35 already ships failSwapOn:false in its managed kubelet default (00-k3s-defaults.conf), and the running kubelet configz confirms failSwapOn=False + memorySwap NoSwap. The running kubelet therefore already tolerates swap, so a restart was unnecessary for PREP-02 toleration. Restarting during the in-progress parity v6 baseline was avoided as needless risk. The explicit 20-swap.conf drop-in is pre-staged and will load on the next natural k3s restart."
  - "Used a dedicated 2G /swapfile (runbook spec) rather than the pre-existing commented-out /swap.img (585M) to avoid touching image-managed swap state."

requirements: [PREP-02]
---

# Plan 12-04 — Host Swap & k3s Kubelet Tolerance (PREP-02)

## What was built

- **Task 1 (autonomous, commit `66d244c`)**: authored `docs/resource-protection.md` — operator runbook covering swap provisioning, the kubelet drop-in, the fish-safe command forms, the fallback, verification, and the explicit "host-process relief ONLY — NOT a substitute for pod memory limits; pod OOM protection is PriorityClass + Guaranteed QoS" caveat (k3s NoSwap default + upstream #12677).
- **Task 2 (live, operator-authorized over SSH)**: provisioned a persistent 2G `/swapfile` on the staging node.

## Live evidence (staging node, k3s v1.35.4+k3s1)

```
free -h | Swap:  2.0Gi  0B  2.0Gi
/proc/swaps: /swapfile  file  2097148  0  -2
/etc/fstab:  /swapfile swap swap defaults 0 0
/etc/sysctl.d/99-swap.conf: vm.swappiness=10
kubelet configz: failSwapOn=False, memorySwap={} (NoSwap default)
kubectl get nodes: 1842817-afgan0r.twc1.net Ready control-plane
```

Explicit drop-in `/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/20-swap.conf` written
(`failSwapOn: false` + `memorySwap.swapBehavior: NoSwap`), pre-staged for the next k3s restart.

## Deviation

PREP-02 success criterion names "a k3s kubelet drop-in … k3s is restarted, node returns Ready".
The drop-in is in place but **k3s was not restarted** — see the decision above. Swap toleration is
already satisfied by the running kubelet config (`failSwapOn=False`), so the deviation is functionally
equivalent while avoiding restart risk to the live parity baseline. Reboot-survival of the fstab entry
remains operator-discretion (documented as Manual-Only in 12-VALIDATION.md).

## Requirements

- **PREP-02** — persistent host swap active, fstab-persisted, kubelet tolerant, documented as host-relief-only. ✓
