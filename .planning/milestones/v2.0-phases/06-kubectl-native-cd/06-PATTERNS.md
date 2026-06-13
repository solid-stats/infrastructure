# Phase 6: kubectl-native CD - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 7 new/modified files
**Analogs found:** 6 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `.github/workflows/deploy-staging.yml` | workflow | request-response | (self — existing workflow) | exact |
| `scripts/wg-tunnel-up.sh` | script | request-response | `scripts/backup-postgres-now.sh` | role-match |
| `scripts/kubeconfig-setup.sh` | script | request-response | `scripts/backup-postgres-now.sh` | role-match |
| `k8s/staging/01-ci-rbac.yaml` | manifest (RBAC) | config | `k8s/staging/10-postgres.yaml` | role-match |
| `docs/operator-bootstrap.md` | documentation (runbook) | reference | `docs/backup-restore.md` | role-match |
| `docs/sa-token-rotation.md` | documentation (runbook) | reference | `docs/backup-restore.md` | role-match |

## Pattern Assignments

### `.github/workflows/deploy-staging.yml` (workflow, request-response)

**Current State:** Analog is the file itself; this file is being refactored.

**Structure reference** (lines 1-45):
```yaml
name: Deploy staging infrastructure

on:
  pull_request:
  push:
    branches:
      - main
      - master
  workflow_dispatch:

concurrency:
  group: infrastructure-staging-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

env:
  K8S_NAMESPACE: solid-stats-staging

jobs:
  validate:
    name: Validate
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout
        uses: actions/checkout@v6
```

**Changes to implement:**

1. **Concurrency group** (update line 12): Change from `cancel-in-progress: true` to `cancel-in-progress: false` to prevent concurrent deploys.
   ```yaml
   concurrency:
     group: infrastructure-staging-deploy
     cancel-in-progress: false
   ```

2. **Validate job** (keep as-is but remove SSH validation, add manifest checks):
   - Keep checkout and YAML validation
   - Remove reference to `scripts/deploy-staging.sh`
   - Check k8s/staging directory exists

3. **New setup-tunnel job** (add):
   - Install `wireguard-tools`
   - Run `scripts/wg-tunnel-up.sh` with WireGuard secrets
   - Gate on handshake completion

4. **New dry-run job** (for PRs):
   - Checkout
   - Run `scripts/kubeconfig-setup.sh`
   - Run `kubectl apply --dry-run=server -f k8s/staging/`

5. **deploy job** (refactor, only on master push):
   - Remove SSH key installation steps (lines 50-56)
   - Remove SSH trust step (lines 58-62)
   - Add WireGuard setup (call wg-tunnel-up.sh)
   - Add kubeconfig setup (call kubeconfig-setup.sh)
   - Run `kubectl apply -f k8s/staging/` locally (not via SSH)
   - Run `kubectl rollout status` locally (not via SSH)
   - Remove all `CD_SSH_*` secret references

---

### `scripts/wg-tunnel-up.sh` (script, request-response)

**Analog:** `scripts/backup-postgres-now.sh`

**Shebang & error handling pattern** (lines 1-2 from backup-postgres-now.sh):
```bash
#!/usr/bin/env bash
set -euo pipefail
```

**Variable initialization pattern** (lines 4-6 from backup-postgres-now.sh):
```bash
# Named parameters with defaults and required checks
namespace="${K8S_NAMESPACE:-solid-stats-staging}"
timeout="${BACKUP_TIMEOUT:-900s}"
```

**Required environment variable pattern** (from deploy-staging.sh lines 6-7):
```bash
target="${CD_SSH_USER:?CD_SSH_USER is required}@${CD_SSH_HOST:?CD_SSH_HOST is required}"
```

**Apply this pattern for wg-tunnel-up.sh:**
```bash
#!/usr/bin/env bash
set -euo pipefail

: "${WG_INTERFACE:=wg0}"
: "${WG_PRIVATE_KEY:?WG_PRIVATE_KEY is required}"
: "${WG_PEER_PUBLIC_KEY:?WG_PEER_PUBLIC_KEY is required}"
: "${WG_ENDPOINT:?WG_ENDPOINT is required}"
: "${WG_LOCAL_IP:=10.8.0.2/32}"
: "${WG_ALLOWED_IPS:=10.8.0.1/32}"
: "${HANDSHAKE_TIMEOUT_SECS:=10}"
```

**Logging & error reporting pattern** (from backup-postgres-now.sh lines 28-32):
```bash
echo
echo "Message here"
echo "key1=${var1:-MISSING}"
echo "key2=${var2:-MISSING}"

if [[ -z "$var1" || -z "$var2" ]]; then
  echo "Error message" >&2
  exit 1
fi
```

**Command availability check pattern** (from RESEARCH.md Pattern 1, lines 194-197):
```bash
if ! command -v wg &>/dev/null; then
  sudo apt-get update
  sudo apt-get install -y wireguard-tools
fi
```

---

### `scripts/kubeconfig-setup.sh` (script, request-response)

**Analog:** `scripts/backup-postgres-now.sh`

**Same shebang and error handling** (as wg-tunnel-up.sh above)

**Required environment variable pattern** (from deploy-staging.sh lines 6-7):
```bash
: "${K8S_TOKEN:?K8S_TOKEN is required}"
: "${K8S_CA_CERT:?K8S_CA_CERT is required}"
```

**Temporary file handling pattern** (from deploy-staging.sh lines 17-18):
```bash
tmp_secrets="$(mktemp)"
trap 'rm -f "$tmp_secrets"' EXIT

# Use $tmp_secrets...
```

**Apply this pattern for kubeconfig-setup.sh:**
- Create temp file for CA cert
- Write CA cert to temp file
- Call kubectl config set-* to build kubeconfig
- Verify auth with `kubectl auth whoami`
- Clean up temp file on exit

---

### `k8s/staging/01-ci-rbac.yaml` (manifest, config)

**Analog:** `k8s/staging/10-postgres.yaml`

**Namespace & label pattern** (lines 4-8 from 10-postgres.yaml, applied to all resources):
```yaml
metadata:
  name: postgres
  namespace: solid-stats-staging
  labels:
    app.kubernetes.io/name: postgres
    app.kubernetes.io/part-of: solid-stats
```

**Apply to 01-ci-rbac.yaml:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-deployer
  namespace: solid-stats-staging
  labels:
    app.kubernetes.io/name: ci-deployer
    app.kubernetes.io/part-of: solid-stats
```

**Annotation pattern for token Secret** (from RESEARCH.md Pattern 2, lines 752-757):
```yaml
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
```

**RBAC structure pattern** (standard k8s convention):
- Role resource with apiGroups/resources/verbs rules
- RoleBinding resource binding Role to ServiceAccount
- All resources in same namespace (solid-stats-staging)
- All resources labeled with `app.kubernetes.io/part-of: solid-stats`

---

### `docs/operator-bootstrap.md` (documentation, reference)

**Analog:** `docs/backup-restore.md`

**Structure pattern** (from backup-restore.md):
```markdown
# Title

Short intro paragraph.

## Section 1: Overview or Prerequisites

## Section 2: Step-by-step instructions

Each step numbered; inline bash code blocks with triple backticks.

## Section 3: Validation or troubleshooting
```

**Apply to operator-bootstrap.md:**
1. Title: "Operator Bootstrap: namespace, ServiceAccount, RBAC, and WireGuard Setup"
2. Intro: Explain this is one-time setup done by the operator, not by CI
3. Prerequisites: kubectl access, k8s ≥1.24 knowledge
4. Steps:
   - Create namespace
   - Create ServiceAccount
   - Create token Secret
   - Create Role
   - Create RoleBinding
   - Patch k3s API cert SAN (if needed)
   - Verify auth with `kubectl auth can-i --list`
5. Validation section with verification commands

**Code block style** (from backup-restore.md line 24-26):
```markdown
Run from a machine with `kubectl` access to the cluster:

\`\`\`bash
K8S_NAMESPACE=solid-stats-staging ./scripts/backup-postgres-now.sh
\`\`\`
```

---

### `docs/sa-token-rotation.md` (documentation, reference)

**Analog:** `docs/backup-restore.md`

**Same structure pattern:**
1. Title: "ServiceAccount Token and WireGuard Key Rotation"
2. Intro: Link rotation to operational discipline; explain cadence (quarterly)
3. Sections:
   - Overview: When/why/who rotates
   - SA Token Rotation (step-by-step)
   - WireGuard Key Rotation (step-by-step)
   - Coordination: Both must rotate together (window of coordination)
   - Verification: Test both new token and new WG key
4. Troubleshooting section

**Reference style** (from backup-restore.md):
- Use inline code for commands
- Use bash code blocks for multi-line scripts
- Document expected output or validation checks

---

## Shared Patterns

### Bash Script Conventions
**Applied to:** `scripts/wg-tunnel-up.sh`, `scripts/kubeconfig-setup.sh`

**Shebang & safeguards:**
```bash
#!/usr/bin/env bash
set -euo pipefail
```

**Required environment variables:**
```bash
: "${VAR_NAME:?VAR_NAME is required}"
```

**Optional environment variables with defaults:**
```bash
: "${VAR_NAME:=default_value}"
```

**Temporary file cleanup:**
```bash
tmp_file="$(mktemp)"
trap 'rm -f "$tmp_file"' EXIT
```

**Error reporting to stderr:**
```bash
echo "Error message" >&2
exit 1
```

**Command availability check:**
```bash
if ! command -v tool_name &>/dev/null; then
  # install tool
fi
```

**Source:** `scripts/backup-postgres-now.sh` (lines 1-2, 4-6, 17-18), `scripts/deploy-staging.sh` (lines 1-2, 6-7)

---

### Kubernetes Manifest Conventions
**Applied to:** `k8s/staging/01-ci-rbac.yaml`

**Namespace on all namespaced resources:**
```yaml
metadata:
  namespace: solid-stats-staging
```

**Standard labels on all resources:**
```yaml
labels:
  app.kubernetes.io/name: <service-name>
  app.kubernetes.io/part-of: solid-stats
```

**Explicit apiVersion and kind:**
```yaml
apiVersion: v1  # or apps/v1, rbac.authorization.k8s.io/v1, etc.
kind: <Kind>
```

**Multiple resources in one file separated by `---`:**
```yaml
---
apiVersion: v1
kind: Resource1
---
apiVersion: v1
kind: Resource2
```

**Source:** `k8s/staging/00-namespace.yaml`, `k8s/staging/10-postgres.yaml` (lines 1-8 example pattern)

---

### GitHub Actions Workflow Conventions
**Applied to:** `.github/workflows/deploy-staging.yml`

**Permissions block (read-only by default):**
```yaml
permissions:
  contents: read
```

**Concurrency control (single deploy at a time):**
```yaml
concurrency:
  group: infrastructure-staging-deploy
  cancel-in-progress: false
```

**Job structure (name, runs-on, timeout, needs, if conditions):**
```yaml
jobs:
  job_name:
    name: Human-readable name
    runs-on: ubuntu-latest
    timeout-minutes: 10
    needs: [prerequisite_job]
    if: github.event_name == 'push' && github.ref == 'refs/heads/master'
    steps:
      - uses: actions/checkout@v6
      - name: Step name
        run: command
```

**Environment secrets usage:**
```yaml
env:
  VAR_NAME: ${{ secrets.SECRET_NAME }}
run: |
  script.sh
```

**Source:** `.github/workflows/deploy-staging.yml` (lines 1-83, current format)

---

### Documentation Runbook Style
**Applied to:** `docs/operator-bootstrap.md`, `docs/sa-token-rotation.md`

**Title and intro:**
```markdown
# Runbook Title

One-sentence purpose. Link to related docs if applicable.
```

**Prerequisite section:**
```markdown
## Prerequisites

- kubectl access to the cluster
- Required packages or permissions
```

**Step-by-step instructions:**
```markdown
## Steps

1. **Step name**

   Explanation of what this step does.

   \`\`\`bash
   command
   \`\`\`

   Expected output or validation note.

2. **Next step**

   ...
```

**Verification section:**
```markdown
## Verification

Run this to verify the previous steps worked:

\`\`\`bash
command
\`\`\`

Expected output: ...
```

**Source:** `docs/backup-restore.md` (lines 1-60, structure and style pattern)

---

## No Analog Found

Files with codebase analogs: All 7 files have close analogs.

| File | Role | Data Flow | Analog Found |
|------|------|-----------|--------------|
| All files | Various | Various | Yes |

---

## Metadata

**Analog search scope:** 
- `.github/workflows/` (GitHub Actions workflows)
- `scripts/` (bash scripts)
- `k8s/staging/` (Kubernetes manifests)
- `docs/` (operational documentation)

**Files scanned:** 15+
**Pattern extraction date:** 2026-06-12

**Key analog sources:**
- `.github/workflows/deploy-staging.yml` (workflow structure, concurrency, job flow)
- `scripts/backup-postgres-now.sh` (bash script shebang, error handling, variable patterns)
- `scripts/deploy-staging.sh` (bash SSH script style, temp files, error reporting)
- `k8s/staging/10-postgres.yaml` (manifest labels, namespace, resource conventions)
- `k8s/staging/00-namespace.yaml` (namespace manifest structure)
- `docs/backup-restore.md` (runbook format, step-by-step instructions, code blocks)
- `docs/staging.md` (documentation structure, cross-references, scope definition)
