# Testing Patterns

**Analysis Date:** 2026-06-13

## Project Model: No Unit Tests

This project has **no unit-test framework** (no Jest, pytest, Vitest, etc.). Instead, testing is performed through validation scripts, dry-run gates, and live operational verification. The project follows a "validation before execution" model where code correctness and safety are asserted through offline checks and staged rollout.

## Validation Framework (The Testing Substitute)

The project uses **offline validation scripts** and **kubectl dry-run** as its primary testing mechanism. All validation is designed to run without a live cluster connection.

### Validation Scripts

**Location:** `scripts/` directory

**Main validators:**
- `scripts/validate-staging.py` — comprehensive staging environment validation
- `scripts/validate-edge.py` — edge (Phase 7) environment validation
- `scripts/validate-s3-lifecycle.py` — S3 lifecycle configuration validator

**Pattern (from `scripts/validate-staging.py`):**

```python
def main() -> int:
    checks = [
        ("script syntax", validate_scripts),
        ("manifest shape", validate_manifest_shape),
        ("drill manifest safety", validate_drill_manifest),
        ("workload safety", validate_workload_safety),
        ("app image pins", validate_app_image_pins),
        ("rendered secret structure", validate_rendered_secrets),
        ("s3 lifecycle config", validate_s3_lifecycle_config),
        ("s3 lifecycle runbook", validate_s3_lifecycle_docs),
        ("cutover artifacts", validate_cutover_artifacts),
    ]
    try:
        for label, check in checks:
            check()
            print(f"ok: {label}")
    except (OSError, ValidationError, py_compile.PyCompileError, json.JSONDecodeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
```

Each check is a standalone function that raises `ValidationError` on failure; main() prints `ok: [label]` for each passed check or exits with code 1 on first failure.

## Run Commands

**Validation:**
```bash
# Run full validation suite (CI gate)
python3 scripts/validate-staging.py

# Run edge validation
python3 scripts/validate-edge.py

# Run S3 lifecycle validation
python3 scripts/validate-s3-lifecycle.py
```

**Syntax checking:**
```bash
# Bash script syntax check (done by validators)
bash -n scripts/backup-postgres-now.sh

# Python compilation check (done by validators)
python3 -m py_compile scripts/render-staging-secrets.py

# Kubernetes dry-run (done by validators when kubectl is available)
kubectl apply --dry-run=client --validate=false -f k8s/staging/
```

**Operational tests (live cluster required):**
```bash
# Manual backup with evidence collection
bash scripts/backup-postgres-now.sh

# Restore drill (on-demand test of backup restore path)
bash scripts/restore-drill.sh

# Cutover script (final safety gate before production traffic)
bash scripts/cutover.sh
```

## Test File Organization

**No test files.** Validation is organized by concern, not by test location:

- `scripts/validate-staging.py` — validates all staging manifests, secrets, workloads
- `scripts/validate-edge.py` — validates edge automation artifacts (nginx, systemd, bootstrap scripts)
- `scripts/validate-s3-lifecycle.py` — validates S3 lifecycle rules

Each validator imports only stdlib. They are self-contained and runnable offline.

## Test Structure

### Offline Validation Pattern

**From `scripts/validate-staging.py` (lines 103–125):**

```python
def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)

def _has_yaml_content(lines: list[str]) -> bool:
    return any(part.strip() and not part.lstrip().startswith("#") for part in lines)

def split_documents(text: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            if _has_yaml_content(current):
                docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if _has_yaml_content(current):
        docs.append("\n".join(current))
    return docs
```

Each validation function:
1. Uses `require(condition, message)` to assert invariants
2. Raises `ValidationError` on first failure
3. Performs only static checks (no cluster connection)

### Example: Manifest Shape Validation

**From `scripts/validate-staging.py` (lines 214–271):**

```python
def validate_manifest_shape() -> list[tuple[str, str, str]]:
    missing = [name for name in EXPECTED_MANIFESTS if not (MANIFEST_DIR / name).is_file()]
    require(not missing, f"missing expected manifests: {', '.join(missing)}")

    # DRILL-04: drill manifests must live in a subdirectory, never at depth-1
    drill_depth1 = [
        f for f in MANIFEST_DIR.glob("*.yaml")
        if any(tok in f.stem.lower() for tok in ("drill", "restore-drill"))
    ]
    require(
        not drill_depth1,
        "DRILL-04 violation: drill manifests must be in a subdirectory "
        f"(k8s/staging/restore-drill/), not depth-1; found: "
        + ", ".join(f.name for f in drill_depth1),
    )

    manifests: list[tuple[str, str, str]] = []
    combined_docs: list[str] = []
    for path in sorted(MANIFEST_DIR.glob("*.yaml")):
        docs = split_documents(path.read_text())
        require(docs, f"{path.relative_to(ROOT)} has no YAML documents")
        for doc in docs:
            api_version = top_value(doc, "apiVersion")
            kind = top_value(doc, "kind")
            name = metadata_name(doc)
            require(api_version is not None, f"{path.relative_to(ROOT)} document missing apiVersion")
            require(kind is not None, f"{path.relative_to(ROOT)} document missing kind")
            require(name is not None, f"{path.relative_to(ROOT)} {kind} document missing metadata.name")
            # ... version checks for each API kind
            manifests.append((kind, name, path.name))
            combined_docs.append("---\n" + doc)

    # Dry-run if kubectl is available (graceful fallback if cluster unreachable)
    if shutil.which("kubectl"):
        try:
            result = run(
                ["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", "-"],
                input_text="\n".join(combined_docs),
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            print("warn: kubectl dry-run skipped because configured cluster is unreachable")
        else:
            if result.returncode != 0 and "connection refused" not in result.stderr.lower():
                raise ValidationError(f"kubectl dry-run failed: {result.stderr.strip() or result.stdout.strip()}")

    return manifests
```

## Mocking

**Not used.** Validators work with real files on disk, never mocked. Example:
- `validate_manifest_shape()` reads actual YAML files from `k8s/staging/`
- `validate_rendered_secrets()` calls `scripts/render-staging-secrets.py` with dummy env vars to verify secret structure
- `validate_drill_manifest()` parses the real drill Job manifest

## Fixtures and Factories

**Test data:**
- Dummy environment variables (not fixtures, but injected at runtime)
- Example from `scripts/validate-staging.py` (lines 463–488):

```python
def validate_rendered_secrets() -> None:
    env = os.environ.copy()
    env.update(
        {
            "GHCR_USERNAME": "dummy-ghcr-user",
            "GHCR_TOKEN": "dummy-secret-value-for-structure-validation",
            "POSTGRES_PASSWORD": "dummy-secret-value-for-structure-validation",
            # ... other dummy values
        }
    )
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as output:
        result = subprocess.run(
            [str(ROOT / "scripts" / "render-staging-secrets.py")],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
        require(result.returncode == 0, f"secret renderer failed with dummy env: {result.stderr.strip()}")
        # ... verify rendered secrets
```

No factory or fixture framework — test data is injected directly as subprocess env.

## Coverage

**No coverage tool.** The project tracks validation completeness through explicit check markers in code:

- `EXPECTED_MANIFESTS` list (line 33–44 in `validate-staging.py`) — documents which manifests must exist
- `EXPECTED_SECRETS` dict (line 46–65) — documents required secret structure
- `EXPECTED_WORKLOADS` dict (line 67–75) — documents required workloads and their safety properties
- Check comments reference specification markers (e.g., "WR-01", "DRILL-04", "CUT-03") to link validation to requirements

**View validation completeness:**
```bash
python3 scripts/validate-staging.py     # Exit 0 if all checks pass
python3 scripts/validate-edge.py        # Exit 0 if all checks pass
echo $?                                 # Check exit code
```

## Test Types

### Type 1: Offline Static Validation

**Scope:** Manifest structure, secret generation, script syntax, image pins

**Approach:** Read files, parse YAML/bash syntax, validate against known invariants

**Run without cluster:** Yes

**Examples:**
- `validate_manifest_shape()` — checks manifest files exist, have valid YAML structure, declare required fields
- `validate_workload_safety()` — verifies all workloads have serviceAccountName, resources, security contexts
- `validate_app_image_pins()` — ensures app images use explicit SHAs, not `:latest`
- `validate_scripts()` — runs `bash -n` and `py_compile` on all scripts

### Type 2: Offline Dry-Run (Optional)

**Scope:** Kubernetes API schema validation

**Approach:** `kubectl apply --dry-run=client` when cluster is reachable; graceful fallback if not

**Run without cluster:** Yes (skips dry-run, passes if offline)

**Example from `validate_manifest_shape()` (lines 253–270):**
```python
if shutil.which("kubectl"):
    try:
        result = run(
            ["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", "-"],
            input_text="\n".join(combined_docs),
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        print("warn: kubectl dry-run skipped because configured cluster is unreachable")
    else:
        if result.returncode != 0 and "connection refused" not in result.stderr.lower():
            raise ValidationError(f"kubectl dry-run failed: {result.stderr.strip() or result.stdout.strip()}")
```

### Type 3: Live Operational Verification (Manual, On-Demand)

**Scope:** Backup creation, restore drill, manifest application, rollout completion

**Approach:** Scripts that execute against live cluster with evidence collection

**Run without cluster:** No (requires kubectl access)

**Tools:**
- `scripts/backup-postgres-now.sh` — triggers manual backup job, collects evidence (backup_id, dump_object, list_object, manifest_object, dump_size_bytes)
- `scripts/restore-drill.sh` — applies restore-drill Job, waits for completion, scans logs for `DRILL_RESULT=PASS` or `DRILL_RESULT=FAIL`
- `scripts/cutover.sh` — final gate before production; verifies backup status, diff coverage, rollback capability, smoke checks

**Evidence markers:**
- Backup: `backup_id=...`, `dump_object=...`, `list_object=...`, `manifest_object=...`, `dump_size_bytes=...`
- Drill: `DRILL_RESULT=PASS` or `DRILL_RESULT=FAIL` (from Job logs)
- Cutover: grep for `Status: verified` (backup gate), `strict_failures: 0` (diff gate)

## CI/CD Integration

**Validation in GitHub Actions (`.github/workflows/deploy-staging.yml`):**

1. **validate job** (lines 21–37): runs `python3 scripts/validate-staging.py`
   - Checks manifest files exist
   - Validates YAML structure, API versions, metadata
   - Verifies script syntax (bash -n, py_compile)
   - Verifies secrets can be rendered with dummy env
   - Verifies S3 lifecycle config matches hard requirements
   - Verifies cutover script and runbook exist with required markers

2. **dry-run job** (lines 39–73): runs `kubectl apply --dry-run=server`
   - Requires WireGuard tunnel to k3s API
   - Requires kubeconfig setup from GitHub secrets
   - Skips 00-namespace.yaml and 01-ci-rbac.yaml (operator-bootstrapped)
   - Performs server-side schema validation

3. **deploy job** (lines 75–148): runs actual `kubectl apply` + rollout verification
   - Applies rendered secrets
   - Applies manifests
   - Waits for StatefulSet and Deployment rollouts (300s timeout)
   - Verifies services and CronJobs are created

## Test Coverage Gaps

**What IS tested:**
- Manifest presence and structure
- Workload safety (serviceAccount, security contexts, resources, probes)
- Secret rendering and structure
- Script syntax and required markers
- Image pin enforcement
- S3 lifecycle rules
- Drill manifest (isolation barriers, security, S3 access)
- Cutover artifacts (backup gate, diff gate, rollback function)

**What is NOT tested (live-only verification):**
- Actual pod startup and readiness (verified live in deploy job)
- Database initialization and migration (verified on first deploy)
- RabbitMQ clustering (verified on rollout)
- Full end-to-end restore from backup (verified by restore-drill.sh on-demand)
- Nginx reverse proxy functionality (verified on edge bootstrap)
- Certbot certificate renewal (verified on edge by cron)

**Risk mitigation:** Live failures are caught immediately during deploy rollout verification (lines 133–148 in CI workflow); on-demand drills (restore-drill.sh) verify critical paths before cutover to production.

## Restore Drill as Live Verification

The **restore-drill Job** (`k8s/staging/restore-drill/70-restore-drill.yaml`) serves as a critical live test of the backup/restore path. It:

1. Runs on-demand (not automatic, per safety constraints in AGENTS.md)
2. Starts with empty volume (emptyDir)
3. Fetches latest backup from S3
4. Initializes fresh PostgreSQL (scratch database)
5. Restores dump from backup
6. Validates integrity
7. Logs `DRILL_RESULT=PASS` or `DRILL_RESULT=FAIL`

Triggered via:
```bash
bash scripts/restore-drill.sh
```

The script (`scripts/restore-drill.sh`) applies the manifest, waits for job completion, scans logs for evidence, and exits 0 only if `DRILL_RESULT=PASS` is found (line 38 in restore-drill.sh).

---

*Testing analysis: 2026-06-13*
