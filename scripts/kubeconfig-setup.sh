#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# kubeconfig-setup.sh — kubeconfig construction from SA token + CA cert
#
# Builds a kubeconfig targeting the k3s API server over the WireGuard tunnel
# (https://10.8.0.1:6443).  Uses kubectl config set-* subcommands (no YAML
# templating).  Verifies that kubectl auth whoami returns a non-anonymous
# identity; exits 1 on system:anonymous.  Exits 64 on missing required config.
# Never uses --insecure-skip-tls-verify.
#
# Usage (called from GitHub Actions step with env vars from secrets):
#   K8S_TOKEN=<token> K8S_CA_CERT=<pem> scripts/kubeconfig-setup.sh
# ---------------------------------------------------------------------------

# --- Required vars (exit 64 if missing) ------------------------------------
if [[ -z "${K8S_TOKEN:-}" ]]; then
  echo "FATAL: K8S_TOKEN is required" >&2
  exit 64
fi
if [[ -z "${K8S_CA_CERT:-}" ]]; then
  echo "FATAL: K8S_CA_CERT is required" >&2
  exit 64
fi

# --- Optional vars with defaults -------------------------------------------
: "${K8S_API_SERVER:=https://10.8.0.1:6443}"
: "${K8S_NAMESPACE:=solid-stats-staging}"
: "${K8S_CLUSTER_NAME:=k3s-staging}"
: "${K8S_USER_NAME:=ci-deployer}"
: "${K8S_CONTEXT_NAME:=ci-k3s-staging}"
: "${KUBECONFIG:=${HOME}/.kube/config}"

echo "=== Setting up kubeconfig ==="

# --- 1. Ensure kubeconfig directory exists ----------------------------------
mkdir -p "$(dirname "$KUBECONFIG")"

# --- 2. Write CA cert to temp file (cleaned up on exit) --------------------
ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
printf '%s' "$K8S_CA_CERT" > "$ca_file"

# --- 3. Build kubeconfig via kubectl config set-* (no YAML templating) -----
echo "Configuring cluster $K8S_CLUSTER_NAME -> $K8S_API_SERVER..."
kubectl config set-cluster "$K8S_CLUSTER_NAME" \
  --certificate-authority="$ca_file" \
  --embed-certs=true \
  --server="$K8S_API_SERVER" \
  --kubeconfig="$KUBECONFIG"

echo "Configuring credentials for $K8S_USER_NAME..."
kubectl config set-credentials "$K8S_USER_NAME" \
  --token="$K8S_TOKEN" \
  --kubeconfig="$KUBECONFIG"

echo "Configuring context $K8S_CONTEXT_NAME..."
kubectl config set-context "$K8S_CONTEXT_NAME" \
  --cluster="$K8S_CLUSTER_NAME" \
  --user="$K8S_USER_NAME" \
  --namespace="$K8S_NAMESPACE" \
  --kubeconfig="$KUBECONFIG"

kubectl config use-context "$K8S_CONTEXT_NAME" \
  --kubeconfig="$KUBECONFIG"

# --- 4. Verify authentication (fail-closed — no anonymous identity) ---------
echo "Verifying authentication..."
whoami_output=$(kubectl auth whoami --kubeconfig="$KUBECONFIG" 2>&1)
if echo "$whoami_output" | grep -q 'system:anonymous'; then
  echo "FATAL: kubectl authenticated as system:anonymous — check K8S_TOKEN and RBAC" >&2
  exit 1
fi
echo "Authenticated as: $whoami_output"

# --- 5. Success -------------------------------------------------------------
echo "kubeconfig ready at $KUBECONFIG"
