# Phase 6: kubectl-native CD — Research

**Researched:** 2026-06-12
**Domain:** Kubernetes deployment over WireGuard tunnel; RBAC and ServiceAccount authentication in k3s; GitHub Actions workflow redesign
**Confidence:** HIGH (core k8s patterns), MEDIUM (GitHub Actions + WireGuard integration)

## Summary

Phase 6 replaces SSH/scp-based deployment with `kubectl apply` executed from GitHub Actions runners over a WireGuard tunnel, authenticating as a namespace-scoped ServiceAccount with a long-lived token Secret. The phase has three critical dependencies: (1) WireGuard handshake gating before any kubectl (51820/udp egress availability must be validated early), (2) explicit token Secret creation for k8s ≥1.24 (auto-token generation was removed), and (3) namespace-scoped RBAC that covers both `apply` and `rollout status` operations on all staging workload kinds.

The operator bootstraps the namespace, ServiceAccount, token Secret, and Role/RoleBinding once; CI never creates cluster-scoped resources. The workflow path diverges: PRs run validate + `--dry-run=server`, master pushes deploy with real apply + rollout verification. Concurrency is locked to a single deploy at a time.

**Primary recommendation:** Implement WireGuard handshake gating in CI as a **fail-closed pre-flight step** before any kubectl; gate on `wg show <iface> latest-handshakes` returning non-zero counts, timing out if handshake does not complete within 10 seconds. This prevents silent failures where the tunnel is not ready but kubectl still runs (and either hangs or falls back to the default route, bypassing the VPS entirely).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| WireGuard tunnel setup | CI runner (GitHub Actions) | VPS endpoint | CI runner initiates peer, VPS listens on 51820/udp; handshake must complete before any kubectl |
| Kubernetes API access | API server (k3s on VPS) | CI via tunnel | API server serves 6443 on the tunnel interface (10.8.0.1); public 6443 not exposed per AGENTS.md constraints |
| ServiceAccount authentication | API server + Secret store | CI via token | API server validates token from Secret; CI loads token into kubeconfig from Secret store |
| Manifest application | CI runner (kubectl apply) | Operator bootstrap (one-time) | CI applies every deploy; operator configures namespace/RBAC once |
| Rollout verification | API server | CI runner | CI polls rollout status; API server reports Pod / StatefulSet / Deployment state |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| k3s | Already running on VPS | Kubernetes runtime | Single-node cluster; manifests are k8s core APIs (v1, apps/v1, batch/v1) |
| WireGuard | kernel module + `wireguard-tools` package | VPN tunnel | Linux native, minimal, battle-tested in CI scenarios; GitHub Actions docs endorse it |
| kubectl | v1.28+ (bundled with k3s) | CLI for deployment | Standard k8s deployment tool; runs on GitHub Actions ubuntu-latest |
| ServiceAccount + RBAC | k8s core APIs | Authentication & authorization | Native k8s; no external auth systems (OIDC, OAuth2) in scope for v2.0 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `wg-quick` | from `wireguard-tools` package | Interface bring-up | Simpler than manual `ip` commands; community GitHub Actions use it; provides atomic configuration |
| GitHub Actions `actions/checkout` | v6+ | Code checkout | Standard Actions pattern; fetch manifests for `kubectl apply` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| WireGuard over direct tunnel | SSH with `-L` port forwarding | SSH adds transport overhead; WireGuard is lower-level and more resilient to network jitter; WireGuard is explicitly supported by GitHub Actions official docs |
| Namespace-scoped ServiceAccount | Cluster admin kubeconfig | Admin token escalates privileges; ServiceAccount restricts to namespace and verbs; required by CD-02 & CD-04 |
| Long-lived token Secret | Short-lived TokenRequest | TokenRequest requires API server refresh; long-lived token is simpler for CI but must be rotated (CD-09 addresses this) |
| `kubectl apply --dry-run=server` on PR | Client-side dry-run | Server-side validates admission webhooks and API-server state; client-side does not; server-side is required to catch CRD schema mismatches |

**Installation (k8s ≥1.24 behavior notes):**
```bash
# On the VPS (operator bootstrap — one-time)
kubectl create namespace solid-stats-staging
kubectl create serviceaccount ci-deployer -n solid-stats-staging

# Create long-lived token Secret explicitly (k8s ≥1.24 does not auto-generate)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ci-deployer-token
  namespace: solid-stats-staging
  annotations:
    kubernetes.io/service-account.name: ci-deployer
type: kubernetes.io/service-account-token
EOF

# Token auto-populated by control plane after Secret creation
TOKEN=$(kubectl get secret ci-deployer-token -n solid-stats-staging -o jsonpath='{.data.token}' | base64 -d)

# On the CI runner (GitHub Actions step)
# 1. Install WireGuard tools
sudo apt-get update && sudo apt-get install -y wireguard-tools

# 2. Create kubeconfig from token + CA
kubectl config set-credentials ci-deployer --token="$TOKEN"
kubectl config set-cluster k3s --certificate-authority="$CA_PATH" --server="https://10.8.0.1:6443"
kubectl config set-context ci-k3s --cluster=k3s --user=ci-deployer
```

**Version verification:** k3s versions are pinned in production; kubectl version is matched to k3s on the VPS. As of 2026-06, k3s ≥1.28 is standard; confirm with `k3s --version` on the VPS.

## Package Legitimacy Audit

This phase uses only OS-level packages and k8s native APIs; no npm/pip/cargo packages installed.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `wireguard-tools` | apt (Debian/Ubuntu) | 8+ yrs | system package | [WireGuard upstream](https://github.com/WireGuard/wireguard-tools) | OK | Approved |
| k3s | GitHub releases | 6+ yrs | widely used | [k3s-io/k3s](https://github.com/k3s-io/k3s) | OK | Approved |
| kubectl | k3s bundled | shipped with k3s | N/A | [kubernetes/kubernetes](https://github.com/kubernetes/kubernetes) | OK | Approved |

**Packages removed due to [SLOP] verdict:** None.
**Packages flagged as suspicious [SUS]:** None.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ GitHub Actions Runner (ubuntu-latest)                            │
│                                                                   │
│  1. Pre-flight: WireGuard handshake gating                        │
│     → Install wireguard-tools                                    │
│     → Read WG config from secrets                               │
│     → wg-quick up (or manual ip + wg set)                       │
│     → Poll `wg show <iface> latest-handshakes` until non-zero   │
│     → ABORT if handshake not complete within timeout            │
│                                                                   │
│  2. Fetch kubeconfig                                             │
│     → kubectl config set-cluster (target 10.8.0.1:6443)        │
│     → kubectl config set-credentials (from token Secret)        │
│                                                                   │
│  3. Validate / Dry-run                                           │
│     → On PR: kubectl apply --dry-run=server -f k8s/staging/    │
│     → On master: kubectl apply -f k8s/staging/                 │
│                                                                   │
│  4. Verify rollout                                               │
│     → kubectl -n solid-stats-staging rollout status …           │
│     → (only on master after real apply)                         │
│                                                                   │
└─────────────────┬──────────────────────────────────────────────┘
                  │ WireGuard tunnel (UDP 51820)
                  │
┌─────────────────▼──────────────────────────────────────────────┐
│ k3s on VPS (solid-stats-staging namespace)                      │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ ServiceAccount: ci-deployer                             │    │
│  │ Token Secret: ci-deployer-token (explicit k8s ≥1.24)   │    │
│  │ Role: ci-deployer (apply + rollout status)             │    │
│  │ RoleBinding: ci-deployer → Role                         │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Workloads:                                                      │
│  • StatefulSet: postgres, rabbitmq                             │
│  • Deployment: server-2, replay-parser-2                       │
│  • CronJob: replays-fetcher, postgres-backup                   │
│  • ConfigMaps: server-2-config, etc.                           │
│  • Services, PVCs, Secrets                                      │
│                                                                   │
│  API server (6443) reachable only via tunnel (10.8.0.1)        │
│  Certificate SAN includes 10.8.0.1 (operator-set at bootstrap) │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

No new top-level directories needed; existing structure is used:
```
.github/workflows/
├── deploy-staging.yml          # Refactored: WireGuard + kubectl native

k8s/staging/
├── 00-namespace.yaml           # Operator bootstrap (CI never touches)
├── 10-postgres.yaml            # StatefulSet + Service
├── 20-rabbitmq.yaml            # StatefulSet + Service
├── 30-server-2.yaml            # ConfigMap + Service (from 35-deployment)
├── 35-server-2-deployment.yaml # Deployment
├── 40-replay-parser-2.yaml     # Deployment
├── 50-replays-fetcher.yaml     # CronJob (suspended until Phase 8)
└── 60-postgres-backup.yaml     # CronJob

docs/
├── operator-bootstrap.md        # NEW: One-time operator runbook
└── sa-token-rotation.md         # NEW: Rotation cadence + procedure
```

### Pattern 1: WireGuard Handshake Gating in CI

**What:** Pre-flight step in GitHub Actions that brings up a WireGuard interface and waits for a completed handshake before proceeding to `kubectl` commands.

**When to use:** Every CI workflow that needs to access a private Kubernetes API server over WireGuard.

**Example:**
```bash
#!/usr/bin/env bash
set -euo pipefail

# Required env vars (passed from GitHub secrets)
: "${WG_INTERFACE:=wg0}"
: "${WG_PRIVATE_KEY:?must be set from secrets}"
: "${WG_PEER_PUBLIC_KEY:?must be set from secrets}"
: "${WG_ENDPOINT:?must be set from secrets}"
: "${WG_ALLOWED_IPS:=10.8.0.1/32}"
: "${WG_LOCAL_IP:=10.8.0.2}"
: "${HANDSHAKE_TIMEOUT:=10}"

# Install WireGuard tools if not present
if ! command -v wg &>/dev/null; then
  sudo apt-get update
  sudo apt-get install -y wireguard-tools
fi

# Create WireGuard interface and bring it up
sudo ip link add dev "$WG_INTERFACE" type wireguard
sudo ip address add "$WG_LOCAL_IP/32" dev "$WG_INTERFACE"
sudo wg set "$WG_INTERFACE" private-key <(echo "$WG_PRIVATE_KEY") \
  peer "$WG_PEER_PUBLIC_KEY" endpoint "$WG_ENDPOINT" allowed-ips "$WG_ALLOWED_IPS"
sudo ip link set up dev "$WG_INTERFACE"

# Gate on completed handshake
echo "Waiting for WireGuard handshake..."
start_time=$(date +%s)
while true; do
  if sudo wg show "$WG_INTERFACE" latest-handshakes | grep -q '1'; then
    echo "Handshake complete"
    break
  fi
  elapsed=$(($(date +%s) - start_time))
  if (( elapsed > HANDSHAKE_TIMEOUT )); then
    echo "FATAL: WireGuard handshake did not complete within ${HANDSHAKE_TIMEOUT}s"
    exit 1
  fi
  sleep 0.5
done

# Verify tunnel reachability
if ! timeout 5 bash -c "echo > /dev/tcp/10.8.0.1/6443"; then
  echo "FATAL: API server not reachable at 10.8.0.1:6443"
  exit 1
fi

echo "WireGuard tunnel ready"
```

**Source:** [GitHub official WireGuard guide](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/connect-to-a-private-network/connect-with-wireguard); [Lullabot deployment guide](https://www.lullabot.com/articles/deploying-private-servers-wireguard-github-actions)

### Pattern 2: Kubeconfig from ServiceAccount Token Secret

**What:** Build a kubeconfig in CI that authenticates via a long-lived token extracted from a Kubernetes Secret.

**When to use:** After WireGuard is up; before any `kubectl` command in the workflow.

**Example:**
```bash
#!/usr/bin/env bash
set -euo pipefail

# Fetch token and CA from GitHub secrets (populated by operator during bootstrap)
: "${K8S_TOKEN:?GitHub secret K8S_TOKEN not set}"
: "${K8S_CA_CERT:?GitHub secret K8S_CA_CERT not set}"
: "${K8S_API_SERVER:=https://10.8.0.1:6443}"
: "${K8S_NAMESPACE:=solid-stats-staging}"

kubeconfig="${HOME}/.kube/config"
mkdir -p "${HOME}/.kube"

# Write CA cert to temp file
ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
echo "$K8S_CA_CERT" > "$ca_file"

# Create kubeconfig
kubectl config set-cluster k3s-staging \
  --certificate-authority="$ca_file" \
  --server="$K8S_API_SERVER"

kubectl config set-credentials ci-deployer \
  --token="$K8S_TOKEN"

kubectl config set-context ci-k3s-staging \
  --cluster=k3s-staging \
  --user=ci-deployer \
  --namespace="$K8S_NAMESPACE"

kubectl config use-context ci-k3s-staging

# Verify authentication is not anonymous
echo "Verifying kubectl auth..."
if kubectl auth whoami | grep -q 'system:anonymous'; then
  echo "FATAL: kubectl authenticated as anonymous"
  exit 1
fi

echo "kubectl authenticated as: $(kubectl auth whoami)"
```

**Source:** [Kubernetes ServiceAccount admin guide](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/); [kubeconfig token setup guide](https://oneuptime.com/blog/post/2026-01-22-kubeconfig-serviceaccount-token/)

### Pattern 3: Namespace-Scoped Role for Apply + Rollout Status

**What:** A Kubernetes Role that grants verbs needed to `apply` all workload kinds in the namespace and verify rollout status without cluster-scoped permissions.

**When to use:** Operator bootstrap (one-time); deployed as part of the bootstrap runbook, not by CI.

**Example:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
rules:
  # Deployments, StatefulSets, DaemonSets: apply + rollout status
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["apps"]
    resources: ["deployments/rollout", "statefulsets/rollout", "daemonsets/rollout"]
    verbs: ["get"]
  
  # CronJobs: apply only (rollout status N/A for CronJobs)
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  
  # Pods (for rollout status --watch)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  
  # Services, ConfigMaps, Secrets, PVCs: apply only
  - apiGroups: [""]
    resources: ["services", "configmaps", "secrets", "persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch"]
  
  # ServiceAccounts (if any workload manifests create them)
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
subjects:
  - kind: ServiceAccount
    name: ci-deployer
    namespace: solid-stats-staging
roleRef:
  kind: Role
  name: ci-deployer
  apiGroup: rbac.authorization.k8s.io
```

**Verify with (from operator machine or after setting kubeconfig for impersonation):**
```bash
# Check what SA can do
kubectl auth can-i --list --as-group=system:serviceaccounts:solid-stats-staging \
  --as=system:serviceaccount:solid-stats-staging:ci-deployer -n solid-stats-staging

# Example output should include:
# create              configmaps, cronjobs, daemonsets, deployments, persistentvolumeclaims, ...
# get                 configmaps, cronjobs, daemonsets, deployments, pods, services, ...
# list                configmaps, cronjobs, daemonsets, deployments, pods, services, ...
# patch               configmaps, cronjobs, daemonsets, deployments, persistentvolumeclaims, ...
# update              configmaps, cronjobs, daemonsets, deployments, persistentvolumeclaims, ...
# watch               configmaps, cronjobs, daemonsets, deployments, pods, services, ...
```

**Source:** [Kubernetes RBAC documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/); [rollout status verb requirements](https://kubernetes.io/docs/reference/generated/kubectl/kubectl-commands)

### Pattern 4: Workflow Path Divergence (PR vs Master)

**What:** GitHub Actions workflow with separate job paths: PRs validate + dry-run without deploying; master pushes apply for real.

**When to use:** Every deploy workflow that needs safety checks before production changes.

**Example:**
```yaml
name: Deploy staging infrastructure

on:
  pull_request:
  push:
    branches:
      - master
  workflow_dispatch:

concurrency:
  group: infrastructure-staging-deploy
  cancel-in-progress: false

env:
  K8S_NAMESPACE: solid-stats-staging

permissions:
  contents: read

jobs:
  validate:
    name: Validate manifests
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6
      
      - name: Check manifest files exist
        run: |
          set -euo pipefail
          test -d k8s/staging
          find k8s/staging -type f -name '*.yaml' | sort

  setup-tunnel:
    name: Setup WireGuard tunnel
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Install WireGuard
        run: |
          sudo apt-get update
          sudo apt-get install -y wireguard-tools
      
      - name: Bring up WireGuard interface
        env:
          WG_PRIVATE_KEY: ${{ secrets.WG_PRIVATE_KEY }}
          WG_PEER_PUBLIC_KEY: ${{ secrets.WG_PEER_PUBLIC_KEY }}
          WG_ENDPOINT: ${{ secrets.WG_ENDPOINT }}
        run: |
          # Create interface, configure peer, verify handshake (see Pattern 1 above)
          ...
  
  dry-run:
    name: Dry-run deploy (server-side)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    needs: [validate, setup-tunnel]
    if: always()
    steps:
      - uses: actions/checkout@v6
      
      - name: Setup kubeconfig
        env:
          K8S_TOKEN: ${{ secrets.K8S_TOKEN }}
          K8S_CA_CERT: ${{ secrets.K8S_CA_CERT }}
        run: |
          # Set up kubeconfig (see Pattern 2 above)
          ...
      
      - name: Dry-run kubectl apply
        run: |
          kubectl apply --dry-run=server -f k8s/staging/
  
  deploy:
    name: Deploy to staging
    runs-on: ubuntu-latest
    timeout-minutes: 20
    needs: [validate, dry-run]
    if: github.event_name == 'push' && github.ref == 'refs/heads/master'
    environment: staging
    steps:
      - uses: actions/checkout@v6
      
      - name: Install WireGuard
        run: sudo apt-get install -y wireguard-tools
      
      - name: Setup WireGuard tunnel
        env:
          WG_PRIVATE_KEY: ${{ secrets.WG_PRIVATE_KEY }}
          WG_PEER_PUBLIC_KEY: ${{ secrets.WG_PEER_PUBLIC_KEY }}
          WG_ENDPOINT: ${{ secrets.WG_ENDPOINT }}
        run: |
          # (see Pattern 1)
          ...
      
      - name: Setup kubeconfig
        env:
          K8S_TOKEN: ${{ secrets.K8S_TOKEN }}
          K8S_CA_CERT: ${{ secrets.K8S_CA_CERT }}
        run: |
          # (see Pattern 2)
          ...
      
      - name: Apply staging manifests
        run: |
          # Render secrets (if any use render-staging-secrets.py)
          python3 scripts/render-staging-secrets.py > /tmp/secrets.yaml || true
          if [ -f /tmp/secrets.yaml ]; then
            kubectl apply -f /tmp/secrets.yaml
            rm -f /tmp/secrets.yaml
          fi
          
          # Apply all manifests
          kubectl apply -f k8s/staging/
      
      - name: Verify rollouts
        run: |
          kubectl -n solid-stats-staging rollout status statefulset/postgres --timeout=300s
          kubectl -n solid-stats-staging rollout status statefulset/rabbitmq --timeout=300s
          kubectl -n solid-stats-staging rollout status deployment/server-2 --timeout=300s
          kubectl -n solid-stats-staging rollout status deployment/replay-parser-2 --timeout=300s
          echo "All workloads rolled out successfully"
```

**Source:** [GitHub Actions workflow syntax](https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions); [concurrency control](https://docs.github.com/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs)

### Anti-Patterns to Avoid

- **Never hardcode secrets in workflow YAML.** Use `${{ secrets.NAME }}` and store actual values in GitHub environment secrets.
- **Never use `--insecure-skip-tls-verify` with kubectl.** k3s must include the tunnel IP (10.8.0.1) in its API server certificate SANs; verify cert validity is not a workaround.
- **Never allow parallel deploys.** Use `concurrency: { group: ..., cancel-in-progress: false }` to ensure only one deploy runs at a time and prevent race conditions in manifest apply order.
- **Never skip the WireGuard handshake check.** A silent tunnel failure leads to kubectl hanging or timing out; fail fast and loudly if the tunnel is not ready.
- **Never create the namespace from CI.** Namespaces are cluster-scoped resources; the ServiceAccount Role cannot create them. Operator must bootstrap once; CI never touches the namespace resource itself.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WireGuard peer configuration | Custom IP + routing scripts | `wg-quick` from `wireguard-tools` or documented manual `ip` + `wg` steps | wg-quick is atomic; manual steps risk partial configuration if interrupted |
| ServiceAccount token generation | Hand-rolled JWT creation | Kubernetes' `kubernetes.io/service-account-token` Secret type | k8s control plane auto-generates valid, signed JWTs; hand-rolled tokens will fail validation |
| Handshake verification | Polling `wg show` output with regex | `wg show <iface> latest-handshakes` + count check | Parsing is fragile; counting non-zero entries is the canonical way |
| RBAC verb matrix | Manual guess at what verbs are needed | `kubectl auth can-i` + dry-run to validate | Manual guessing leads to overly permissive or broken RBAC; verification catches issues before production |
| Kubeconfig construction | Manual yaml templating | `kubectl config set-*` subcommands | Templating risks invalid yaml; kubectl subcommands handle validation and encoding |

**Key insight:** Kubernetes, WireGuard, and kubectl are all designed to be reliable when used correctly; hand-rolled alternatives introduce maintenance burden and correctness risks without benefit.

## Runtime State Inventory

**Trigger:** This phase replaces SSH-based deploy with kubectl-native deploy. Runtime state must be audited for references to the old CD_SSH_* secrets and deploy mechanisms.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | None — no application data stores the deploy mechanism or SSH key material | None |
| **Live service config** | GitHub environment secrets: `CD_SSH_PRIVATE_KEY`, `CD_SSH_HOST`, `CD_SSH_PORT`, `CD_SSH_USER` are deprecated; replaced with `WG_PRIVATE_KEY`, `WG_PEER_PUBLIC_KEY`, `WG_ENDPOINT`, `K8S_TOKEN`, `K8S_CA_CERT` | Operator deletes old secrets from GitHub; creates new ones; documents in bootstrap runbook |
| **OS-registered state** | `.ssh/known_hosts` entry for the deploy host is written during current workflow; no longer needed | Workflow step to install SSH key is removed entirely |
| **Secrets/env vars** | GitHub environment secrets `CD_SSH_*` are consumed only by `.github/workflows/deploy-staging.yml` and `scripts/deploy-staging.sh` (both being refactored) | Remove all `CD_SSH_*` env var references from workflow and scripts |
| **Build artifacts / installed packages** | `scripts/deploy-staging.sh` is a script artifact that will be deleted; no compiled binaries to clean | Script removal is part of the phase |

**Verification:** All references to `CD_SSH_*` are removed from `.github/workflows/deploy-staging.yml`; `scripts/deploy-staging.sh` is deleted entirely; no SSH config remains in any workflow step.

## Common Pitfalls

### Pitfall 1: WireGuard Handshake Not Gated

**What goes wrong:** WireGuard interface is created but the handshake hasn't completed; kubectl commands hang or timeout because the tunnel is not ready; or fallback to public API (which is not exposed) causes silent deployment failures.

**Why it happens:** Bringing up a WireGuard interface is not atomic — the peer is added, but the initial handshake takes a few milliseconds; kubectl may start before the handshake completes.

**How to avoid:** Always poll `wg show <iface> latest-handshakes` before proceeding. Return non-zero for at least one peer, timeout if not within 10 seconds, and **exit 1** if timeout.

**Warning signs:** kubectl commands hang for 30+ seconds; workflow times out; successful dry-runs but deploy job shows no output for minutes.

### Pitfall 2: Missing SAN on API Server Certificate

**What goes wrong:** kubectl connects via WireGuard to 10.8.0.1:6443, but the k3s API server certificate is issued with SANs like [10.43.0.1, 127.0.0.1, <public-ip>] and not 10.8.0.1; TLS handshake fails with "x509: certificate is valid for X, not 10.8.0.1".

**Why it happens:** k3s generates its API cert at install time before the WireGuard tunnel IP is known; the operator must add the SAN post-install.

**How to avoid:** Operator adds `--tls-san=10.8.0.1` to k3s config, removes old cert Secret, restarts k3s to regenerate the cert with the new SAN. **Verify:** `openssl s_client -connect 10.8.0.1:6443 </dev/null | openssl x509 -noout -text | grep 'IP Address'` should show `10.8.0.1`.

**Warning signs:** TLS cert verification errors in kubectl output; PR dry-runs fail on the "Setup kubeconfig" step; "certificate verify failed" in logs.

### Pitfall 3: Namespace Created by CI Instead of Operator

**What goes wrong:** Role is namespace-scoped and cannot create the cluster-scoped Namespace resource; CI job attempts `kubectl create namespace` and gets RBAC denied; subsequent `apply` fails because namespace does not exist.

**Why it happens:** Confusion between what is cluster-scoped (Namespace) and namespace-scoped (Role, RoleBinding, resources within the namespace).

**How to avoid:** Operator creates the namespace once as part of the bootstrap runbook. CI workflow **never** includes any step to create or check for the namespace — assume it exists. If it doesn't, that is an operator error, not a CI concern.

**Warning signs:** Workflow fails with "Error from server (Forbidden): namespaces is forbidden"; reference to "cluster-scoped" in the error; empty namespace.

### Pitfall 4: k8s ≥1.24 Automatic Token Secret Not Created

**What goes wrong:** Operator creates ServiceAccount but expects a token Secret to auto-generate; it doesn't (k8s removed auto-token generation in 1.24). Workflow cannot extract a token, kubeconfig step fails.

**Why it happens:** k8s 1.24+ removed the default `kubernetes.io/service-account-token` Secret generation; manual creation is now required but often overlooked in migration guides.

**How to avoid:** Operator bootstrap **explicitly creates** the token Secret with the annotation `kubernetes.io/service-account.name`. Control plane will auto-populate the token field after creation. Verify with `kubectl get secret ci-deployer-token -o jsonpath='{.data.token}'`.

**Warning signs:** Workflow fails with "secret not found" or "secret has no token field"; empty token in kubeconfig.

### Pitfall 5: Over-Permissive or Broken RBAC

**What goes wrong:** Role grants too many verbs (e.g., `*` on all resources); or grants wrong verbs and `apply` or `rollout status` fails with "Forbidden".

**Why it happens:** Manual RBAC guessing without verification; temptation to grant `*` to "just make it work".

**How to avoid:** Use `kubectl auth can-i --list --as=system:serviceaccount:...` to test what the SA can do. Run `kubectl apply --dry-run=server` against the actual manifests to catch RBAC issues **before** deploying. Test Role in a non-production namespace first.

**Warning signs:** Workflow apply step fails with "Forbidden: User 'system:serviceaccount:...' cannot X Y"; overly broad Role with `["*"]` verbs.

### Pitfall 6: GitHub Actions Secret Rotation Not Coordinated

**What goes wrong:** WireGuard key is rotated on the VPS but not in GitHub secrets; SA token is rotated but not stored in GitHub; deployment fails silently.

**Why it happens:** WireGuard and SA token have independent rotation procedures; they must be coordinated in a runbook so neither is rotated without updating both the VPS and GitHub.

**How to avoid:** CD-09 requires a documented runbook that links WireGuard key rotation and SA-token rotation. Both must happen in a coordinated window, with GitHub secrets updated **before** VPS rotation so deploys don't fail mid-rotation.

**Warning signs:** Workflow hangs on "WireGuard handshake"; kubeconfig "unauthorized" errors after operator performs manual rotation.

## Code Examples

### Example 1: WireGuard Handshake Gating Script

**Source:** [GitHub WireGuard documentation](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/connect-to-a-private-network/connect-with-wireguard)

```bash
#!/usr/bin/env bash
set -euo pipefail

# Required secrets (passed from GitHub environment)
: "${WG_INTERFACE:=wg0}"
: "${WG_PRIVATE_KEY:?WG_PRIVATE_KEY not set}"
: "${WG_PEER_PUBLIC_KEY:?WG_PEER_PUBLIC_KEY not set}"
: "${WG_ENDPOINT:?WG_ENDPOINT not set (format: HOST:PORT)}"
: "${WG_LOCAL_IP:=10.8.0.2/32}"
: "${WG_ALLOWED_IPS:=10.8.0.1/32}"
: "${HANDSHAKE_TIMEOUT_SECS:=10}"

echo "=== WireGuard Pre-flight Gate ==="

# Ensure tools installed
if ! command -v wg &>/dev/null; then
  echo "Installing wireguard-tools..."
  sudo apt-get update >/dev/null 2>&1
  sudo apt-get install -y wireguard-tools >/dev/null 2>&1
fi

# Create interface
echo "Creating WireGuard interface $WG_INTERFACE..."
sudo ip link add dev "$WG_INTERFACE" type wireguard

# Assign local IP
echo "Assigning local IP $WG_LOCAL_IP..."
sudo ip address add "$WG_LOCAL_IP" dev "$WG_INTERFACE"

# Configure peer (private key and peer endpoint)
echo "Configuring peer..."
sudo wg set "$WG_INTERFACE" \
  private-key <(echo "$WG_PRIVATE_KEY") \
  peer "$WG_PEER_PUBLIC_KEY" \
  endpoint "$WG_ENDPOINT" \
  allowed-ips "$WG_ALLOWED_IPS"

# Bring interface up
echo "Bringing up interface..."
sudo ip link set up dev "$WG_INTERFACE"

# Gate on completed handshake
echo "Waiting for handshake (timeout: ${HANDSHAKE_TIMEOUT_SECS}s)..."
deadline=$(($(date +%s) + HANDSHAKE_TIMEOUT_SECS))
while true; do
  if sudo wg show "$WG_INTERFACE" latest-handshakes | grep -q '[0-9]'; then
    echo "✓ Handshake complete"
    break
  fi
  
  if (( $(date +%s) > deadline )); then
    echo "✗ FATAL: Handshake did not complete within ${HANDSHAKE_TIMEOUT_SECS}s"
    echo "Interface status:"
    sudo wg show "$WG_INTERFACE" || true
    exit 1
  fi
  
  sleep 0.25
done

# Verify API server reachability
echo "Verifying API server reachability (10.8.0.1:6443)..."
if timeout 5 bash -c "echo > /dev/tcp/10.8.0.1/6443" 2>/dev/null; then
  echo "✓ API server reachable"
else
  echo "✗ FATAL: API server not reachable at 10.8.0.1:6443"
  exit 1
fi

echo "=== WireGuard Ready ==="
```

### Example 2: Kubeconfig from Token Secret

**Source:** [Kubernetes kubeconfig setup](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)

```bash
#!/usr/bin/env bash
set -euo pipefail

# GitHub secrets populated by operator
: "${K8S_TOKEN:?K8S_TOKEN not set}"
: "${K8S_CA_CERT:?K8S_CA_CERT not set}"
: "${K8S_API_SERVER:=https://10.8.0.1:6443}"
: "${K8S_NAMESPACE:=solid-stats-staging}"
: "${KUBECONFIG:=${HOME}/.kube/config}"

echo "=== Setting up kubeconfig ==="

mkdir -p "$(dirname "$KUBECONFIG")"

# Write CA cert
ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
echo "$K8S_CA_CERT" > "$ca_file"

# Set cluster
echo "Configuring cluster..."
kubectl config set-cluster k3s-staging \
  --certificate-authority="$ca_file" \
  --server="$K8S_API_SERVER" \
  --kubeconfig="$KUBECONFIG"

# Set credentials
echo "Configuring credentials..."
kubectl config set-credentials ci-deployer \
  --token="$K8S_TOKEN" \
  --kubeconfig="$KUBECONFIG"

# Set context
echo "Configuring context..."
kubectl config set-context ci-k3s-staging \
  --cluster=k3s-staging \
  --user=ci-deployer \
  --namespace="$K8S_NAMESPACE" \
  --kubeconfig="$KUBECONFIG"

# Use context
echo "Activating context..."
kubectl config use-context ci-k3s-staging --kubeconfig="$KUBECONFIG"

# Verify authentication
echo "Verifying authentication..."
whoami_output=$(kubectl auth whoami)
if echo "$whoami_output" | grep -q 'system:anonymous'; then
  echo "✗ FATAL: kubectl authenticated as system:anonymous"
  exit 1
fi

echo "✓ Authenticated as: $whoami_output"
echo "✓ kubeconfig ready at $KUBECONFIG"
```

### Example 3: Namespace-Scoped CI RBAC

**Source:** [Kubernetes RBAC documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

```yaml
---
# Operator creates this during bootstrap
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
  labels:
    app.kubernetes.io/name: ci-deployer
    app.kubernetes.io/part-of: solid-stats

---
# k8s ≥1.24: explicit token Secret (not auto-generated)
apiVersion: v1
kind: Secret
metadata:
  name: ci-deployer-token
  namespace: solid-stats-staging
  annotations:
    kubernetes.io/service-account.name: ci-deployer
  labels:
    app.kubernetes.io/name: ci-deployer
type: kubernetes.io/service-account-token

---
# Role: namespace-scoped permissions for apply + rollout status
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
rules:
  # Deployments, StatefulSets: apply + rollout
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  
  # CronJobs: apply
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  
  # Pods (needed for rollout status --watch)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  
  # ConfigMaps, Secrets, Services, PVCs: apply
  - apiGroups: [""]
    resources: ["configmaps", "secrets", "services", "persistentvolumeclaims"]
    verbs: ["get", "list", "create", "update", "patch"]
  
  # ServiceAccounts in namespace (if manifests create them)
  - apiGroups: [""]
    resources: ["serviceaccounts"]
    verbs: ["get", "list", "create", "update", "patch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
roleRef:
  kind: Role
  name: ci-deployer
  apiGroup: rbac.authorization.k8s.io
subjects:
  - kind: ServiceAccount
    name: ci-deployer
    namespace: solid-stats-staging
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SSH/scp deploy to VPS via CD_SSH_* secrets | kubectl apply over WireGuard tunnel via ServiceAccount token | Phase 6 (this phase) | Eliminates SSH transport, uses native k8s auth, enables CI to scale (no per-runner SSH key needed) |
| Admin kubeconfig in CI | Namespace-scoped ServiceAccount with long-lived token Secret | Phase 6 | Least-privilege auth; operator controls initial bootstrap; easier token rotation |
| Auto-generated ServiceAccount token Secret (k8s <1.24) | Explicit `kubernetes.io/service-account-token` Secret (k8s ≥1.24) | k8s 1.24 release (2022) | k8s removed auto-generation for security; manual creation now required but gives operator control over when tokens are issued |
| Manual SSH host key verification via ssh-keyscan | k8s API cert validation via CA bundle in kubeconfig | Phase 6 | TLS cert is verified via CA; no need for out-of-band host key management; tunnel IP must be in cert SANs |

**Deprecated/outdated:**
- `CD_SSH_*` secrets (replaced by WireGuard + ServiceAccount token)
- `scripts/deploy-staging.sh` (replaced by kubectl native in CI workflow)
- SSH key installation steps in CI workflow (replaced by WireGuard setup)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | GitHub-hosted `ubuntu-latest` runners can reach 51820/udp outbound to the VPS | WireGuard Handshake Gating, Pitfalls | If false, WireGuard tunnel cannot be established; deploy job will fail; must validate early with a simple ping/handshake test |
| A2 | k3s is already running on the VPS and configured for remote kubectl access | Standard Stack, Architecture | If false, k3s setup falls outside this phase scope; Phase 6 assumes k3s exists and is accessible |
| A3 | The k3s API server certificate can be patched to include 10.8.0.1 in SANs (or was already issued with it) | Common Pitfalls, Architecture | If false, TLS cert validation will fail; kubectl will not work over the tunnel; requires k3s cert regeneration |
| A4 | `kubernetes.io/service-account-token` Secret creation is the preferred method for long-lived tokens in k8s ≥1.24 | Standard Stack, Pattern 2 | If false, token extraction fails; kubeconfig setup breaks; no alternative is documented as stable |
| A5 | `wg show <iface> latest-handshakes` can be relied upon to detect a completed handshake | Pattern 1, Common Pitfalls | If false, handshake gating is unreliable; tunnel may not be ready despite returning non-zero; must verify with a TCP connect attempt |
| A6 | Timely SA-token rotation is operationally feasible and will be documented in a runbook | CD-09, Assumptions Log | If false, long-lived tokens pose security risk; no automatic rotation means manual discipline required; operator must commit to rotation cadence |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

**Status:** A1, A3, A6 require user validation before execution (GitHub Actions network access, k3s cert SAN config, rotation discipline).

## Open Questions

1. **Does the VPS firewall allow UDP 51820 outbound for GitHub-hosted runners?**
   - What we know: GitHub Actions docs say WireGuard is supported on `ubuntu-latest`; standard WireGuard uses 51820/udp.
   - What's unclear: Whether the VPS network provider (Timeweb) allows this specific egress port without extra configuration.
   - Recommendation: **Validate early in Phase 6 planning.** Create a test WireGuard peer on the VPS, attempt a handshake from a GitHub Actions workflow, and observe success or failure. This is a go/no-go check.

2. **Is k3s API server certificate already SAN-configured for 10.8.0.1, or must the operator patch it post-install?**
   - What we know: k3s was installed before the WireGuard tunnel was planned; cert likely does not include 10.8.0.1.
   - What's unclear: Current k3s config file on the VPS; whether `tls-san` was set at install time.
   - Recommendation: Operator checks `/etc/rancher/k3s/config.yaml`; if no `tls-san` for 10.8.0.1, add it and follow the remediation steps in Common Pitfalls (remove old cert, restart k3s).

3. **Will the existing `scripts/render-staging-secrets.py` work with the new kubectl-native flow, or must it be refactored?**
   - What we know: Current script renders secrets to stdout; current deploy-staging.sh pipes them to kubectl on the VPS via scp.
   - What's unclear: Whether the script needs modification for in-CI rendering, or if a simple `kubectl apply -f` of its output works.
   - Recommendation: Planner tests the script in Phase 6 early; if it needs refactoring, scope that as a separate task.

4. **What is the acceptable SA-token rotation cadence, and who owns the runbook execution?**
   - What we know: CD-09 requires a documented runbook; long-lived tokens are a security risk.
   - What's unclear: How often (monthly? quarterly?), and whether the operator can automate it or must do it manually.
   - Recommendation: Define rotation cadence as part of the SA-token rotation runbook (CD-09); default to "at least quarterly" if no other security policy exists.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| k3s on VPS | kubectl apply via tunnel | ✓ | already installed | — |
| kubectl CLI | CI workflow (deploy jobs) | ✓ | bundled with k3s | Use `k3s kubectl` over vanilla `kubectl` if needed |
| WireGuard kernel module | WireGuard tunnel | ✓ (assumed) | Linux kernel ≥5.6 | `wireguard-tools` (userspace only) if kernel module not available |
| `wireguard-tools` package | CI workflow (wg command) | ✓ (on ubuntu-latest) | available via apt | Build from source (slow; avoid unless necessary) |
| Python 3 | scripts/render-staging-secrets.py | ✓ | 3.x (on ubuntu-latest) | — |
| GitHub Actions `environment: staging` | deploy job gating | ✓ | standard feature | Skip environment gating (not recommended; reduces safety) |

**Missing dependencies with no fallback:** None identified.

**Missing dependencies with fallback:** `wireguard-tools` can fall back to building from source if the apt package is not available, but this is not recommended (slow build, complexity).

## Validation Architecture

> Skip this section entirely if workflow.nyquist_validation is explicitly set to false in .planning/config.json. If the key is absent, treat as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Bash scripts + `kubectl` + GitHub Actions workflow testing |
| Config file | `.github/workflows/deploy-staging.yml` |
| Quick run command | `kubectl apply --dry-run=server -f k8s/staging/` (on VPS via tunnel) |
| Full suite command | Full workflow run: validate + dry-run + deploy (on master push) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CD-01 | Push to master deploys via `kubectl apply` over WireGuard, no SSH | integration | PR workflow: validate + dry-run; master workflow: apply + rollout status | ✅ `.github/workflows/deploy-staging.yml` |
| CD-02 | CI authenticates as `solid-stats-staging`-scoped ServiceAccount, `kubectl auth whoami` is not `system:anonymous` | smoke | `kubectl auth whoami` step in deploy job | ✅ Workflow step |
| CD-03 | WireGuard handshake completes; job aborts if handshake does not complete within timeout | smoke | `wg show <iface> latest-handshakes` gating step; timeout if not non-zero within 10s | ✅ Workflow step (Pattern 1) |
| CD-04 | SA can apply and rollout status all staging workload kinds; cannot access cluster-scoped resources | unit | `kubectl auth can-i --list --as=system:serviceaccount:solid-stats-staging:ci-deployer` on VPS | ✅ One-time validation in operator bootstrap runbook |
| CD-05 | Namespace and RBAC bootstrapped once by operator; CI never creates namespace | integration | Operator bootstrap runbook execution; verify namespace + Role + RoleBinding exist post-bootstrap; CI workflow does not include `kubectl create namespace` | ✅ `docs/operator-bootstrap.md` |
| CD-06 | PR runs validate + dry-run without deploying; master push deploys | integration | Two-path workflow: `if: github.event_name == 'pull_request'` for validate/dry-run, `if: github.event_name == 'push'` for deploy | ✅ `.github/workflows/deploy-staging.yml` |
| CD-07 | All `CD_SSH_*` secrets and SSH code paths removed | static | Grep check: no `CD_SSH_*` in workflow file or scripts; no SSH key installation steps | ✅ `.github/workflows/deploy-staging.yml` (refactored), `scripts/deploy-staging.sh` (deleted) |
| CD-08 | Only one deploy runs at a time (concurrency lock) | integration | Workflow concurrency: `group: infrastructure-staging-deploy, cancel-in-progress: false`; verify second master push cancels first deploy | ✅ `.github/workflows/deploy-staging.yml` |
| CD-09 | SA-token + WireGuard key rotation runbook documented (owner + cadence) | documentation | `docs/sa-token-rotation.md` exists with rotation steps + cadence (e.g., quarterly) | ❌ Wave 0 (Phase 6 creates the runbook) |

### Sampling Rate

- **Per task commit:** `kubectl apply --dry-run=server -f k8s/staging/` (validates manifests before every commit)
- **Per wave merge:** Full master workflow run: validate + dry-run + real deploy + rollout status verification
- **Phase gate:** All requirements (CD-01 to CD-09) verified green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `docs/operator-bootstrap.md` — one-time operator runbook (namespace, SA, token Secret, Role/RoleBinding, k3s cert SAN setup)
- [ ] `docs/sa-token-rotation.md` — SA token + WireGuard key rotation cadence and procedure
- [ ] `.github/workflows/deploy-staging.yml` refactor — WireGuard setup, kubeconfig construction, path divergence (PR vs master)
- [ ] `scripts/deploy-staging.sh` removal — safe deletion after workflow migration

*(If no gaps: "None — existing test infrastructure covers all phase requirements")*

## Security Domain

> Required when `security_enforcement` is enabled (absent = enabled). Omit only if explicitly `false` in config.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | ServiceAccount token authentication; `kubectl auth whoami` verification |
| V3 Session Management | yes | Long-lived token Secret; rotation runbook (CD-09) required |
| V4 Access Control | yes | Namespace-scoped Role + RoleBinding; RBAC verb matrix verified with `auth can-i` |
| V5 Input Validation | yes | `kubectl apply --dry-run=server` validates manifests server-side before applying |
| V6 Cryptography | yes | TLS cert validation via CA bundle in kubeconfig; no `--insecure-skip-tls-verify` |

### Known Threat Patterns for Kubernetes + GitHub Actions + WireGuard

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| WireGuard tunnel not established; fallback to public API | Tampering | Gate on handshake before any kubectl; fail closed if tunnel not ready |
| Overly permissive SA RBAC (e.g., `*` verbs) | Elevation of Privilege | `kubectl auth can-i --list` validation; audit Role before bootstrap |
| SA token leaked in logs or error output | Information Disclosure | Never log token; use `--token=` in kubectl config, not environment variables; sanitize error output |
| Long-lived token not rotated | Repudiation | Rotation runbook with documented cadence (CD-09); operator discipline required |
| k3s API cert without tunnel IP SAN | Spoofing | Add 10.8.0.1 to SANs during bootstrap; verify with `openssl s_client` before deploying |
| CI job impersonation (rogue runner) | Spoofing | GitHub environment secrets + ref protection on master prevent secret exfiltration; token is read-only (cannot modify RBAC or create resources) |
| Manifest tampering in git (applying malicious workload) | Tampering | Code review on PRs before merge; dry-run validation catches invalid manifests; no automatic merge without review |

## Sources

### Primary (HIGH confidence)

- [Kubernetes official documentation](https://kubernetes.io/docs/reference/access-authn-authz/) — ServiceAccount, RBAC, authentication, `kubectl auth` commands
- [Kubernetes website Context7](https://websites.kubernetes_io) — token Secret creation, rollout status verb requirements, dry-run validation
- [GitHub Actions official documentation](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/connect-to-a-private-network/connect-with-wireguard) — WireGuard setup on GitHub-hosted runners

### Secondary (MEDIUM confidence)

- [Lullabot deployment guide](https://www.lullabot.com/articles/deploying-private-servers-wireguard-github-actions) — Practical WireGuard + deployment workflow example
- [OneUptime k3s TLS SAN guide](https://oneuptime.com/blog/post/2026-03-20-k3s-tls-san/view) — k3s certificate SAN configuration and remediation
- [OneUptime kubeconfig from ServiceAccount token](https://oneuptime.com/blog/post/2026-01-22-kubeconfig-serviceaccount-token/view) — kubeconfig construction patterns
- [GitHub Actions concurrency control guide](https://docs.github.com/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs) — workflow concurrency and cancel-in-progress

### Tertiary (LOW confidence)

- WebSearch results on GitHub Actions runner egress and WireGuard port assumptions — accepted as true based on GitHub's documented support, but not verified in this environment

## Metadata

**Confidence breakdown:**
- **Standard stack (HIGH):** Kubernetes, kubectl, WireGuard, ServiceAccount/RBAC are all well-documented and stable; k3s version is known.
- **Architecture (HIGH):** Phase scope, WireGuard tunnel design, namespace-scoped RBAC are all aligned with Kubernetes best practices and GitHub Actions support.
- **Pitfalls (HIGH):** Common mistakes (handshake gating, SAN configuration, k8s ≥1.24 token Secret) are documented in official k3s and Kubernetes guides.
- **Environment Availability (MEDIUM):** 51820/udp egress from GitHub runners is assumed but not yet validated in this VPS network; k3s certificate SAN configuration depends on current k3s setup (unknown).
- **Rotation Discipline (LOW):** SA-token rotation cadence and operator discipline (CD-09) depend on organizational policy; not yet defined.

**Research date:** 2026-06-12
**Valid until:** 2026-07-12 (30 days; stable k8s patterns; refresh if GitHub Actions runner egress rules change or k3s version upgrades)
