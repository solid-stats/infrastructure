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
DUMMY_SECRET_VALUE = "dummy-secret-value-for-structure-validation"


def _load_s3_lifecycle_validator():
    """Load the standalone validate-s3-lifecycle.py as a module so CI enforces
    the SAME assertions (Days >= 30 floor, AbortIncompleteMultipartUpload) as the
    operator-run validator. Single source of truth — no divergence (WR-01/IN-04).
    The filename has a hyphen, so it cannot be a plain `import`; load it by path
    with importlib (stdlib only)."""
    module_path = ROOT / "scripts" / "validate-s3-lifecycle.py"
    spec = importlib.util.spec_from_file_location("validate_s3_lifecycle", module_path)
    if spec is None or spec.loader is None:
        raise ValidationError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

EXPECTED_MANIFESTS = [
    "00-namespace.yaml",
    "10-postgres.yaml",
    "20-rabbitmq.yaml",
    "30-server-2.yaml",
    "35-server-2-deployment.yaml",
    "36-web.yaml",
    "37-web-deployment.yaml",
    "40-replay-parser-2.yaml",
    "50-replays-fetcher.yaml",
    "60-postgres-backup.yaml",
]

EXPECTED_SECRETS = {
    "ghcr-pull": {
        "type": "kubernetes.io/dockerconfigjson",
        "keys": {".dockerconfigjson"},
    },
    "postgres-auth": {"type": "Opaque", "keys": {"POSTGRES_PASSWORD"}},
    "rabbitmq-auth": {"type": "Opaque", "keys": {"RABBITMQ_PASSWORD"}},
    "server-2-runtime": {
        "type": "Opaque",
        "keys": {"DATABASE_URL", "RABBITMQ_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"},
    },
    "replay-parser-2-runtime": {
        "type": "Opaque",
        "keys": {"REPLAY_PARSER_AMQP_URL", "REPLAY_PARSER_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"},
    },
    "replays-fetcher-runtime": {
        "type": "Opaque",
        "keys": {"DATABASE_URL", "REPLAY_SOURCE_URL", "REPLAY_SOURCE_TRANSPORT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"},
    },
}

EXPECTED_WORKLOADS = {
    "postgres": {"kind": "StatefulSet", "file": "10-postgres.yaml", "long_running": True},
    "rabbitmq": {"kind": "StatefulSet", "file": "20-rabbitmq.yaml", "long_running": True},
    "server-2": {"kind": "Deployment", "file": "35-server-2-deployment.yaml", "long_running": True},
    "web": {"kind": "Deployment", "file": "37-web-deployment.yaml", "long_running": True},
    "replay-parser-2": {"kind": "Deployment", "file": "40-replay-parser-2.yaml", "long_running": True},
    "replays-fetcher": {"kind": "CronJob", "file": "50-replays-fetcher.yaml", "long_running": False},
    "postgres-backup": {"kind": "CronJob", "file": "60-postgres-backup.yaml", "long_running": False},
}

APP_IMAGES = {
    "server-2": "k8s/staging/35-server-2-deployment.yaml",
    "replay-parser-2": "k8s/staging/40-replay-parser-2.yaml",
    "replays-fetcher": "k8s/staging/50-replays-fetcher.yaml",
}


class ValidationError(Exception):
    pass


def run(
    cmd: list[str], *, input_text: str | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


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


# NOTE: These helpers are intentionally minimal, line-based parsers — NOT a full
# YAML implementation. The project convention is "standard library only" for
# scripts, so PyYAML is deliberately not imported. They therefore ASSUME the
# canonical 2-space block style emitted by scripts/render-staging-secrets.py and
# used throughout k8s/staging/*.yaml: top-level keys unindented, one nesting level
# at exactly two spaces, plain (non-flow, non-multiline) scalars. Comment and
# blank lines are tolerated so key reordering / interleaved comments no longer
# break detection. If a manifest deviates from this style these helpers may
# misread it — the live `kubectl apply --dry-run` path in
# validate_manifest_shape() is the authoritative gate when a cluster is reachable.


def _is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def top_value(doc: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in doc.splitlines():
        # Top-level keys are unindented; require the prefix to be followed by a
        # space/tab/EOL so a deeper key that merely starts with the same text
        # (e.g. 'kindOf:') cannot satisfy top_value('kind').
        if line.startswith(prefix) and (line == prefix or line[len(prefix)] in (" ", "\t")):
            return line.split(":", 1)[1].strip()
    return None


def metadata_name(doc: str) -> str | None:
    in_metadata = False
    for line in doc.splitlines():
        if line.rstrip() == "metadata:":
            in_metadata = True
            continue
        if not in_metadata:
            continue
        if _is_comment_or_blank(line):
            continue
        # A non-indented, non-comment line ends the metadata block.
        if not line.startswith(" "):
            break
        # Match the direct child 'name:' at exactly two spaces of indent
        # (reject deeper 'name:' keys nested under labels/annotations).
        if line.startswith("  name:") and not line.startswith("   "):
            return line.split(":", 1)[1].strip()
    return None


def string_data(doc: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_string_data = False
    for line in doc.splitlines():
        if line.rstrip() == "stringData:":
            in_string_data = True
            continue
        if not in_string_data:
            continue
        if _is_comment_or_blank(line):
            continue
        # A non-indented line ends the stringData block.
        if not line.startswith(" "):
            break
        # Direct children at exactly two spaces of indent.
        if line.startswith("  ") and not line.startswith("   ") and ":" in line:
            key, raw_value = line.strip().split(":", 1)
            raw_value = raw_value.strip()
            try:
                values[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                values[key] = raw_value
    return values


def validate_scripts() -> None:
    py_compile.compile(str(ROOT / "scripts" / "render-staging-secrets.py"), doraise=True)
    py_compile.compile(str(ROOT / "scripts" / "validate-edge.py"), doraise=True)
    py_compile.compile(str(ROOT / "scripts" / "validate-s3-lifecycle.py"), doraise=True)
    for script in ["scripts/backup-postgres-now.sh", "scripts/restore-drill.sh", "scripts/apply-s3-lifecycle.sh"]:
        result = run(["bash", "-n", script])
        require(result.returncode == 0, f"{script} failed bash syntax check: {result.stderr.strip()}")


def validate_manifest_shape() -> list[tuple[str, str, str]]:
    missing = [name for name in EXPECTED_MANIFESTS if not (MANIFEST_DIR / name).is_file()]
    require(not missing, f"missing expected manifests: {', '.join(missing)}")

    # DRILL-04: drill manifests must live in a subdirectory, never at depth-1.
    # CD glob: find k8s/staging -maxdepth 1 -name '*.yaml' — would accidentally
    # schedule the drill Job on every deploy if any drill yaml leaks here.
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
            if kind in {"Namespace", "Secret", "Service", "ServiceAccount", "ConfigMap"}:
                require(api_version == "v1", f"{path.relative_to(ROOT)} {kind}/{name} must use apiVersion v1")
            if kind in {"Deployment", "StatefulSet"}:
                require(api_version == "apps/v1", f"{path.relative_to(ROOT)} {kind}/{name} must use apiVersion apps/v1")
            if kind == "CronJob":
                require(api_version == "batch/v1", f"{path.relative_to(ROOT)} CronJob/{name} must use apiVersion batch/v1")
            manifests.append((kind, name, path.name))
            combined_docs.append("---\n" + doc)

    if shutil.which("kubectl"):
        try:
            result = run(
                ["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", "-"],
                input_text="\n".join(combined_docs),
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            # An unreachable cluster (e.g. closed k3s API, VPN black-holing packets)
            # makes kubectl block on discovery instead of failing fast; treat the
            # timeout the same as a refused connection so validation stays local.
            print("warn: kubectl dry-run skipped because configured cluster is unreachable")
        else:
            if result.returncode != 0 and "connection refused" not in result.stderr.lower():
                raise ValidationError(f"kubectl dry-run failed: {result.stderr.strip() or result.stdout.strip()}")
            if result.returncode != 0:
                print("warn: kubectl dry-run skipped because configured cluster is unreachable")

    return manifests


def validate_workload_safety() -> None:
    docs_text = (ROOT / "docs" / "staging.md").read_text()
    has_network_policy = any("kind: NetworkPolicy" in path.read_text() for path in MANIFEST_DIR.glob("*.yaml"))
    require(has_network_policy or "NetworkPolicy exception" in docs_text, "missing NetworkPolicy manifests or documented NetworkPolicy exception")
    stateful_security_exception = "StatefulSet securityContext exception" in docs_text

    for name, expected in EXPECTED_WORKLOADS.items():
        path = MANIFEST_DIR / expected["file"]
        text = path.read_text()
        require(f"name: {name}" in text, f"{path.relative_to(ROOT)} missing workload name {name}")
        require("serviceAccountName:" in text, f"{path.relative_to(ROOT)} workload {name} missing serviceAccountName")
        require("automountServiceAccountToken: false" in text, f"{path.relative_to(ROOT)} workload {name} must disable API token automount")
        require("resources:" in text, f"{path.relative_to(ROOT)} workload {name} missing resources")
        require("requests:" in text and "limits:" in text, f"{path.relative_to(ROOT)} workload {name} missing requests or limits")
        if name in {"postgres", "rabbitmq"} and stateful_security_exception:
            pass
        else:
            require("securityContext:" in text, f"{path.relative_to(ROOT)} workload {name} missing securityContext")
        if expected["long_running"]:
            require("readinessProbe:" in text, f"{path.relative_to(ROOT)} workload {name} missing readinessProbe")
            require("livenessProbe:" in text, f"{path.relative_to(ROOT)} workload {name} missing livenessProbe")


def validate_app_image_pins() -> None:
    for app_name, rel_path in APP_IMAGES.items():
        text = (ROOT / rel_path).read_text()
        image_lines = [line.strip().split("image:", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("image: ghcr.io/solid-stats/")]
        require(image_lines, f"{rel_path} missing GHCR app image for {app_name}")
        for image in image_lines:
            require(":latest" not in image, f"{rel_path} uses mutable latest image tag: {image}")
            require(":" in image.rsplit("/", 1)[-1], f"{rel_path} image must use an explicit tag: {image}")


def validate_drill_manifest() -> None:
    # WR-05: the restore-drill manifest lives in a subdirectory (DRILL-04) and is
    # therefore never reached by validate_manifest_shape's depth-1 glob, so its
    # safety-critical fields escaped CI. Assert the invariants that make the Job
    # both runnable and safe here, WITHOUT re-adding it to the depth-1 glob.
    path = MANIFEST_DIR / "restore-drill" / "70-restore-drill.yaml"
    require(path.is_file(), f"missing drill manifest: {path.relative_to(ROOT)}")
    text = path.read_text()
    rel = path.relative_to(ROOT)

    # CR-01 — the MAIN container (restore-drill) must not run as root: pg_ctl/initdb
    # refuse to start as root.  The initContainer (fetch-backup) runs as root
    # intentionally so apk can write its package DB — do NOT fail on runAsUser: 0.
    #
    # Parse per-container security contexts by splitting on container name markers
    # so we can check each container independently.
    lines = text.splitlines()

    def _lines_for_container(name: str) -> str:
        """Return the text block starting from '- name: {name}' to the next
        sibling '- name:' line or end-of-document."""
        start = None
        for i, line in enumerate(lines):
            if line.strip() == f"- name: {name}":
                start = i
                break
        if start is None:
            return ""
        block: list[str] = []
        for line in lines[start + 1:]:
            # A sibling container starts with another '- name:' at the same indent.
            if line.strip().startswith("- name:") and line == line.lstrip():
                # top-level list item — stop (shouldn't happen inside spec, but safe)
                break
            if line.rstrip() and not line.startswith(" ") and not line.startswith("\t"):
                break
            block.append(line)
        return "\n".join(block)

    main_ctx = _lines_for_container("restore-drill")
    init_ctx = _lines_for_container("fetch-backup")

    require(main_ctx, f"{rel} missing main container 'restore-drill'")
    require(init_ctx, f"{rel} missing initContainer 'fetch-backup'")

    # Main container must run as the real postgres user (uid 70 in postgres:17-alpine).
    # initdb does getpwuid() and refuses a uid with no /etc/passwd entry, so an arbitrary
    # uid like 999 fails at runtime ("could not look up effective user ID 999"). Non-root + uid 70.
    require("runAsNonRoot: true" in main_ctx, f"{rel} main container missing runAsNonRoot: true (CR-01)")
    require("runAsUser: 70" in main_ctx, f"{rel} main container must run as uid 70 (the postgres user; 999 has no /etc/passwd entry and initdb getpwuid fails)")

    # initContainer is expected to run as root (apk add requires root).
    require("runAsUser: 0" in init_ctx, f"{rel} fetch-backup initContainer must declare runAsUser: 0 (apk needs root)")
    require("runAsNonRoot: false" in init_ctx, f"{rel} fetch-backup initContainer must declare runAsNonRoot: false")

    # WR-04 — both containers must have standard hardening.
    require("allowPrivilegeEscalation: false" in main_ctx, f"{rel} main container missing allowPrivilegeEscalation: false")
    require("allowPrivilegeEscalation: false" in init_ctx, f"{rel} fetch-backup initContainer missing allowPrivilegeEscalation: false")
    require('drop: ["ALL"]' in text or "drop: ['ALL']" in text, f"{rel} must drop ALL capabilities (WR-04)")

    # CR-02 — trust auth for the scratch DB; the live postgres-auth secret must
    # NOT be mounted anywhere in the drill.
    require("-A trust" in text, f"{rel} scratch initdb must use -A trust (CR-02)")
    require("name: postgres-auth" not in text, f"{rel} must not mount the live postgres-auth secret (CR-02)")

    # DRILL-01 — isolation barriers must stay intact.
    require("refusing drill to protect live data (DRILL-01)" in text, f"{rel} missing refuse-if-live-host barrier (DRILL-01)")
    require("solid_stats_drill" in text, f"{rel} missing guarded scratch DB name (DRILL-01)")
    require("name: postgres-data" not in text and "claimName: postgres-data" not in text, f"{rel} must not mount the live postgres-data PVC (DRILL-01)")
    require("emptyDir" in text, f"{rel} scratch volume must be emptyDir (DRILL-01)")
    require("automountServiceAccountToken: false" in text, f"{rel} must disable API token automount")

    # New invariant: S3 secret (server-2-runtime) must be referenced by the
    # initContainer, NOT the main container (main container has no S3 access).
    require("server-2-runtime" in init_ctx, f"{rel} fetch-backup initContainer must reference server-2-runtime secret for S3 access")
    require("server-2-runtime" not in main_ctx, f"{rel} main container must NOT reference server-2-runtime (S3 access belongs to initContainer only)")


def validate_s3_lifecycle_config() -> None:
    # WR-01/IN-04: delegate to the standalone validate-s3-lifecycle.py so CI
    # enforces the SAME assertions the operator-run validator does — including the
    # 30-day Expiration floor and the AbortIncompleteMultipartUpload presence
    # check. This is the single source of truth; the previous inline copy here
    # only required Days >= 1, so a future edit dropping the retention window to
    # 1 day would have silently passed CI.
    module = _load_s3_lifecycle_validator()
    try:
        module.validate_lifecycle_json()
    except module.ValidationError as exc:
        # Re-raise as this module's ValidationError so main()'s handler catches it.
        raise ValidationError(str(exc)) from exc


def validate_s3_lifecycle_docs() -> None:
    docs_path = ROOT / "docs" / "s3-lifecycle.md"
    require(docs_path.is_file(), "docs/s3-lifecycle.md missing")
    content = docs_path.read_text()
    require("apply-s3-lifecycle.sh" in content, "s3-lifecycle.md missing apply script reference")
    require("S3-03" in content, "s3-lifecycle.md missing S3-03 evidence section reference")
    require("AbortIncompleteMultipartUpload" in content, "s3-lifecycle.md missing AbortIncompleteMultipartUpload documentation (S3-02)")


def validate_rendered_secrets() -> None:
    env = os.environ.copy()
    env.update(
        {
            "GHCR_USERNAME": "dummy-ghcr-user",
            "GHCR_TOKEN": DUMMY_SECRET_VALUE,
            "POSTGRES_PASSWORD": DUMMY_SECRET_VALUE,
            "RABBITMQ_PASSWORD": DUMMY_SECRET_VALUE,
            "S3_BUCKET": "dummy-bucket",
            "S3_ACCESS_KEY_ID": "dummy-access-key",
            "S3_SECRET_ACCESS_KEY": DUMMY_SECRET_VALUE,
            "REPLAYS_FETCHER_REPLAY_SOURCE_URL": "https://example.invalid/replays",
            "REPLAYS_FETCHER_REPLAY_SOURCE_TRANSPORT": "direct",
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
        output.seek(0)
        docs = split_documents(output.read())

    secrets: dict[str, dict[str, object]] = {}
    for doc in docs:
        if top_value(doc, "kind") != "Secret":
            continue
        name = metadata_name(doc)
        require(name is not None, "rendered Secret missing metadata.name")
        secrets[name] = {
            "type": top_value(doc, "type") or "Opaque",
            "stringData": string_data(doc),
        }

    for name, expected in EXPECTED_SECRETS.items():
        require(name in secrets, f"rendered secrets missing {name}")
        secret = secrets[name]
        require(secret["type"] == expected["type"], f"{name} has unexpected type {secret['type']}")
        keys = set(secret["stringData"].keys())  # type: ignore[index,union-attr]
        missing_keys = expected["keys"] - keys
        require(not missing_keys, f"{name} missing keys: {', '.join(sorted(missing_keys))}")

    docker_config = secrets["ghcr-pull"]["stringData"][".dockerconfigjson"]  # type: ignore[index]
    parsed = json.loads(docker_config)
    ghcr = parsed["auths"]["ghcr.io"]
    require(ghcr.get("username") == "dummy-ghcr-user", "GHCR dockerconfigjson username mismatch")
    require(ghcr.get("password") == DUMMY_SECRET_VALUE, "GHCR dockerconfigjson password mismatch")
    decoded_auth = b64decode(ghcr.get("auth", "")).decode()
    require(decoded_auth == f"dummy-ghcr-user:{DUMMY_SECRET_VALUE}", "GHCR dockerconfigjson auth mismatch")


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
    ]
    try:
        for label, check in checks:
            check()
            print(f"ok: {label}")
    except (OSError, ValidationError, py_compile.PyCompileError, json.JSONDecodeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
