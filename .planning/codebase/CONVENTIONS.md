# Coding Conventions

**Analysis Date:** 2026-06-13

## Naming Patterns

**Files:**
- Kubernetes manifests: numeric prefix for apply ordering + semantic name (e.g., `10-postgres.yaml`, `35-server-2-deployment.yaml`, `70-restore-drill.yaml`)
- Bash scripts: lowercase with hyphens (e.g., `wg-tunnel-up.sh`, `kubeconfig-setup.sh`, `backup-postgres-now.sh`)
- Python scripts: lowercase with hyphens (e.g., `render-staging-secrets.py`, `validate-staging.py`)
- Documentation: markdown files in `docs/` with semantic names (e.g., `backup-restore.md`, `staging.md`)

**Functions (Bash):**
- Helper functions use underscores: `_lines_for_container()`, `_has_yaml_content()`
- Descriptive verbs: `validate_*()`, `required()`, `run()`

**Variables:**
- Bash: UPPERCASE for env vars and constants (`K8S_NAMESPACE`, `BACKUP_TIMEOUT`), lowercase for locals (`namespace`, `timeout`, `job_name`)
- Python: lowercase with underscores for functions and variables, UPPERCASE for module-level constants (`ROOT`, `MANIFEST_DIR`, `NAMESPACE`)

**Labels (Kubernetes):**
- Standard Kubernetes app labels: `app.kubernetes.io/name`, `app.kubernetes.io/part-of`
- Custom labels: `solid-stats.io/environment` (e.g., `solid-stats.io/environment: staging`)

## Code Style

**Formatting:**
- No external formatter enforced; manually maintained consistency
- Kubernetes YAML: 2-space indentation (verified by hand-parsing validators)
- Bash scripts: logical grouping with `# ---` divider lines and section headers
- Python: standard 4-space indentation, PEP 8 style (no black/ruff enforced)

**Linting:**
- Bash: checked via `bash -n` syntax validation in CI (`.github/workflows/deploy-staging.yml`)
- Python: checked via `py_compile.compile()` in `scripts/validate-staging.py` (lines 201–203)
- Kubernetes: validated offline via hand-parsing (YAML structure check), online via `kubectl apply --dry-run=client` when cluster is reachable (line 254–267 in `validate-staging.py`)

## Import Organization

**Python:**
1. Standard library imports (stdlib only — no external packages)
   - `import json`, `import os`, `import sys`, `import subprocess`
   - `from pathlib import Path`
   - `from base64 import b64encode, b64decode`
   - `from urllib.parse import quote`
   - `import re`, `import py_compile`, `import importlib.util`, `import tempfile`, `import shutil`

2. Module-level definitions follow immediately (constants, helper functions)

Example from `scripts/validate-staging.py` (lines 1–16):
```python
#!/usr/bin/env python3
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from base64 import b64decode
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "k8s" / "staging"
```

**Bash:**
- Shebang: `#!/usr/bin/env bash` (line 1 in all scripts)
- Strict mode: `set -euo pipefail` (line 2 in all scripts)
- Comments precede code sections
- No external tooling imports (only POSIX/GNU `bash` builtins and standard CLI tools: `kubectl`, `aws`, `nginx`, `certbot`, `ufw`)

## Error Handling

**Bash Pattern:**
- Exit code `64` for missing required configuration (convention across all scripts)
- Example from `scripts/wg-tunnel-up.sh` (lines 27–38):
  ```bash
  if [[ -z "${WG_PRIVATE_KEY:-}" ]]; then
    echo "FATAL: WG_PRIVATE_KEY is required" >&2
    exit 64
  fi
  ```
- Exit code `1` for runtime failures
- All error messages go to stderr (`>&2`)
- Optional checks use `|| true` to suppress error exit (e.g., line 12 in `backup-postgres-now.sh`)

**Python Pattern:**
- `exit(64)` for missing required environment variables
- `ValidationError` exception class for validation failures (custom exception in both `validate-staging.py` and `validate-edge.py`)
- Example from `scripts/render-staging-secrets.py` (lines 12–17, 53–55):
  ```python
  def required(name: str) -> str:
      value = os.environ.get(name)
      if not value:
          missing.append(name)
          return ""
      return value

  if missing:
      print(f"Missing required environment variables: {', '.join(sorted(set(missing)))}", file=sys.stderr)
      sys.exit(64)
  ```

**Kubernetes Validation:**
- `require(condition, message)` helper (used in both `validate-staging.py` and `validate-edge.py`)
- Raises `ValidationError` on assertion failure; caught by main() handler (lines 532–537 in `validate-staging.py`)

## Logging

**Bash:**
- Use `echo` for user-facing output, `echo "..." >&2` for errors
- Status markers: `echo "=== [Section Name] ==="` for major phase logging
- Informational lines: plain `echo` (e.g., "Installing...", "Validating...")

**Python:**
- `print()` for stdout (normal output)
- `print(..., file=sys.stderr)` for warnings/errors
- Validation checks print `ok: [label]` on success (line 535 in `validate-staging.py`)
- Exceptions caught at module level and printed as `error: [message]` (line 537)

## Comments

**When to Comment:**
- Block comments before major sections (bash uses `# --- Section Name ---` dividers)
- Inline comments explain non-obvious logic, especially YAML/shell parsing rules
- Example from `scripts/validate-staging.py` (lines 127–136):
  ```python
  # NOTE: These helpers are intentionally minimal, line-based parsers — NOT a full
  # YAML implementation. The project convention is "standard library only" for
  # scripts, so PyYAML is deliberately not imported.
  ```

**Docstrings (Python):**
- Used for module-level validators (e.g., line 2–3 in `validate-edge.py`)
- Function docstrings explain purpose for public functions
- Helper functions use short docstrings

## Function Design

**Size (Bash):**
- Small scripts: linear flow with section dividers (e.g., `wg-tunnel-up.sh` lines 40–121)
- Validation scripts: break logic into testable functions (`validate_*()` pattern)

**Size (Python):**
- Validators: 10–50 lines each
- Helpers: small utilities like `require()` (3 lines), `top_value()` (7 lines)
- Main entry: linear sequence of checks with labels (lines 520–539 in `validate-staging.py`)

**Parameters:**
- Bash: use environment variables for configuration (no function parameters), positional args for one-off values
- Python: standard function signatures with type hints where helpful

**Return Values:**
- Bash: exit codes only; use `echo` or variable assignment for data passing
- Python: explicit return types; functions return values

## Module Design

**Kubernetes Manifests:**
- One manifest file per logical unit or closely related group (e.g., `10-postgres.yaml` has ServiceAccount + Service + StatefulSet)
- Multiple YAML documents in a file separated by `---` (e.g., `35-server-2-deployment.yaml` has ServiceAccount + Deployment)
- Files grouped by numeric prefix for apply order: databases (10–20), infrastructure (30–40), jobs (50–60), special/on-demand (70–80+)

**Secrets Handling:**
- Secrets are generated by `scripts/render-staging-secrets.py` from environment variables (no hardcoded secrets)
- Sensitive values (passwords, tokens, keys) come from GitHub environment secrets
- Secret manifests use `stringData:` with JSON-escaped values
- No secret files committed to git; secrets live only in GitHub environments and live cluster state

## Security Contexts (Kubernetes)

**Pod Level:**
- `automountServiceAccountToken: false` (disable default API token automount) — mandatory on all workloads
- `fsGroup: 70` (for drill: make emptyDir group-writable by postgres uid)
- Per-container `securityContext` preferred over pod-level

**Container Level:**
- `allowPrivilegeEscalation: false` (mandatory on long-running workloads)
- `capabilities: drop: ["ALL"]` (drop all Linux capabilities)
- `runAsNonRoot: true` (long-running services) / `runAsUser: X` (explicit uid when non-default)
- Init containers that require root (e.g., `apk add`) declare `runAsUser: 0` + `runAsNonRoot: false` explicitly
- Example from `k8s/staging/35-server-2-deployment.yaml` (lines 79–82):
  ```yaml
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
  ```

## Resource Management (Kubernetes)

**All workloads:**
- `resources: requests:` and `limits:` defined (mandatory)
- CPU: requests 100m–250m, limits 1 CPU
- Memory: requests 256Mi–512Mi, limits 1Gi–2Gi
- Example from `k8s/staging/35-server-2-deployment.yaml` (lines 72–78):
  ```yaml
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: "1"
      memory: 1Gi
  ```

## ServiceAccount & RBAC

**All workloads:**
- Explicit `serviceAccountName: workload-name` (never default)
- Dedicated ServiceAccount per workload (created alongside Deployment/StatefulSet)

## Image Policies (Kubernetes)

**All images:**
- `imagePullPolicy: IfNotPresent` (for pinned images to reduce pull latency and registry calls)
- Application images: pinned to full SHA (e.g., `ghcr.io/solid-stats/server-2:3866f6b422c506a429e12658aaaedb0dd5c16b8e`)
- Infrastructure images: explicit tags (e.g., `postgres:17-alpine`, `busybox:1.37`)
- No `:latest` tags in manifests (enforced by `validate_app_image_pins()` in `validate-staging.py` line 303)

## Probe Design (Kubernetes)

**Long-running workloads (Deployments, StatefulSets):**
- `readinessProbe:` + `livenessProbe:` required (enforced at line 292 in `validate-staging.py`)
- HTTP probes preferred for web services (e.g., `/ready` and `/live` endpoints)
- Exec probes for databases (e.g., `pg_isready` for PostgreSQL)

**Jobs/CronJobs:**
- No probes needed (one-shot tasks; success/failure determined by exit code)

## Config File Locations

**Kubernetes manifests:** `k8s/staging/` (depth-1) and `k8s/staging/restore-drill/` (subdirectory for on-demand jobs)

**Scripts:** `scripts/` directory
- Validation: `validate-staging.py`, `validate-edge.py`, `validate-s3-lifecycle.py`
- Operational: `backup-postgres-now.sh`, `restore-drill.sh`, `cutover.sh`
- Bootstrap/infra: `wg-tunnel-up.sh`, `kubeconfig-setup.sh`, `bootstrap-edge.sh`, `teardown-edge.sh`
- S3 ops: `apply-s3-lifecycle.sh`

**Configuration:** `config/` directory
- Nginx vhost: `config/nginx/sites-available/stats-staging-solid-stats.conf`
- Systemd: `config/systemd/certbot.service.d/`, `config/systemd/certbot-deploy-hook.sh`

---

*Convention analysis: 2026-06-13*
