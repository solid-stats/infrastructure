#!/usr/bin/env python3
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

EXPECTED_MANIFESTS = [
    "00-namespace.yaml",
    "10-postgres.yaml",
    "20-rabbitmq.yaml",
    "30-server-2.yaml",
    "35-server-2-deployment.yaml",
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
    "replay-parser-2": {"kind": "Deployment", "file": "40-replay-parser-2.yaml", "long_running": True},
    "replays-fetcher": {"kind": "CronJob", "file": "50-replays-fetcher.yaml", "long_running": False},
    "postgres-backup": {"kind": "CronJob", "file": "60-postgres-backup.yaml", "long_running": False},
}


class ValidationError(Exception):
    pass


def run(cmd: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def split_documents(text: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            if any(part.strip() for part in current):
                docs.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if any(part.strip() for part in current):
        docs.append("\n".join(current))
    return docs


def top_value(doc: str, key: str) -> str | None:
    prefix = f"{key}:"
    for line in doc.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def metadata_name(doc: str) -> str | None:
    lines = doc.splitlines()
    in_metadata = False
    for line in lines:
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line and not line.startswith(" "):
            return None
        if in_metadata and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return None


def string_data(doc: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_string_data = False
    for line in doc.splitlines():
        if line == "stringData:":
            in_string_data = True
            continue
        if in_string_data and line and not line.startswith(" "):
            break
        if in_string_data and line.startswith("  ") and ":" in line:
            key, raw_value = line.strip().split(":", 1)
            raw_value = raw_value.strip()
            try:
                values[key] = json.loads(raw_value)
            except json.JSONDecodeError:
                values[key] = raw_value
    return values


def validate_scripts() -> None:
    py_compile.compile(str(ROOT / "scripts" / "render-staging-secrets.py"), doraise=True)
    for script in ["scripts/deploy-staging.sh", "scripts/backup-postgres-now.sh"]:
        result = run(["bash", "-n", script])
        require(result.returncode == 0, f"{script} failed bash syntax check: {result.stderr.strip()}")


def validate_manifest_shape() -> list[tuple[str, str, str]]:
    missing = [name for name in EXPECTED_MANIFESTS if not (MANIFEST_DIR / name).is_file()]
    require(not missing, f"missing expected manifests: {', '.join(missing)}")

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
            manifests.append((kind, name, path.name))
            combined_docs.append("---\n" + doc)

    if shutil.which("kubectl"):
        result = run(["kubectl", "apply", "--dry-run=client", "--validate=false", "-f", "-"], input_text="\n".join(combined_docs))
        if result.returncode != 0 and "connection refused" not in result.stderr.lower():
            raise ValidationError(f"kubectl dry-run failed: {result.stderr.strip() or result.stdout.strip()}")
        if result.returncode != 0:
            print("warn: kubectl dry-run skipped because configured cluster is unreachable")

    return manifests


def validate_workload_safety() -> None:
    docs_text = (ROOT / "docs" / "staging.md").read_text()
    has_network_policy = any("kind: NetworkPolicy" in path.read_text() for path in MANIFEST_DIR.glob("*.yaml"))
    require(has_network_policy or "NetworkPolicy exception" in docs_text, "missing NetworkPolicy manifests or documented NetworkPolicy exception")

    for name, expected in EXPECTED_WORKLOADS.items():
        path = MANIFEST_DIR / expected["file"]
        text = path.read_text()
        require(f"name: {name}" in text, f"{path.relative_to(ROOT)} missing workload name {name}")
        require("serviceAccountName:" in text, f"{path.relative_to(ROOT)} workload {name} missing serviceAccountName")
        require("automountServiceAccountToken: false" in text, f"{path.relative_to(ROOT)} workload {name} must disable API token automount")
        require("resources:" in text, f"{path.relative_to(ROOT)} workload {name} missing resources")
        require("requests:" in text and "limits:" in text, f"{path.relative_to(ROOT)} workload {name} missing requests or limits")
        require("securityContext:" in text, f"{path.relative_to(ROOT)} workload {name} missing securityContext")
        if expected["long_running"]:
            require("readinessProbe:" in text, f"{path.relative_to(ROOT)} workload {name} missing readinessProbe")
            require("livenessProbe:" in text, f"{path.relative_to(ROOT)} workload {name} missing livenessProbe")


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
        ("workload safety", validate_workload_safety),
        ("rendered secret structure", validate_rendered_secrets),
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
