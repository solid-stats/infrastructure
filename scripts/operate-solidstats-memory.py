#!/usr/bin/env python3
"""Private JSON operator for the Phase 21 isolated memory restore drill."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
from typing import Iterator, Mapping
from urllib import parse as urllib_parse
from urllib import error as urllib_error
from urllib import request as urllib_request


SCHEMA = "solidstats-memory-private-operator/v1"
CONFIG_SCHEMA = "solidstats-memory-private-operator-config/v1"
NAMESPACE = "solidstats-memory"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
OPERATIONS = {
    "inspect-preflight",
    "render-manifests",
    "validate-manifests",
    "apply-manifests",
    "inspect-runtime",
    "load-backup-inputs",
    "apply-backup-job",
    "wait-backup-job",
    "remote-package-inventory",
    "download-backup-package",
    "recover-uploaded-snapshot",
    "qdrant-request",
    "run-phase20-parity",
    "run-exact-image-probe",
    "verify-prestate",
}
TARGETS = (
    "k8s/memory/10-qdrant.yaml",
    "k8s/memory/20-mempalace.yaml",
    "k8s/memory/30-network-policy.yaml",
    "k8s/memory/40-backup.yaml",
)
MARKERS = {
    "MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE": "qdrant_storage",
    "MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE": "mempalace_storage",
    "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": "mempalace_image",
    "MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR": "host_nginx_cidr",
    "MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR": "backup_cidr",
    "MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST": "uploader_image",
    "MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME": "private_collection",
}
PACKAGE_MEMBERS = (
    "SHA256SUMS",
    "manifest.json",
    "mempalace-metadata.tar",
    "qdrant.snapshot",
)
MEMORY_PUBLIC_URL = "https://solid-stats.ru/solidstats/mcp"
LEGACY_SOLIDSTATS_MCP_URL = "https://89.223.124.200:8443/solidstats/mcp"
S3_ENDPOINT = "https://s3.twcstorage.ru"
S3_REGION = "ru-1"
OFFICIAL_MEMPALACE_IMAGE = (
    "ghcr.io/mempalace/mempalace@"
    "sha256:d9d75fab4138a22d013a244bb4153fa1938830be3726cf826ffd02aeba73fe8e"
)
OFFICIAL_MEMPALACE_CONFIG = (
    "sha256:19453ae121bc14f4e9515fed1840179add7a8ad638cce1c0dc90a92df777d9e8"
)
OFFICIAL_AWS_CLI_IMAGE = (
    "public.ecr.aws/aws-cli/aws-cli@"
    "sha256:f611429c1fcd094bf04f748f0be1e5d604aa28214ea0f54c0bf8242ec2ef7cd3"
)
RESTORE_RESERVE_BYTES = 1024 * 1024 * 1024


class OperatorError(ValueError):
    """A value-free operator contract failure."""


def canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OperatorError("operator data is not canonical JSON") from error


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def qdrant_jwt(secret_value: str, payload: Mapping[str, object]) -> str:
    """Create the exact HS256 token format accepted by Qdrant JWT RBAC."""
    header = {"alg": "HS256", "typ": "JWT"}

    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(canonical(value)).rstrip(b"=").decode("ascii")

    segments = [encode(header), encode(dict(payload))]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret_value.encode(), signing_input, hashlib.sha256).digest()
    return ".".join((*segments, base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")))


def storage_bytes(value: object) -> int:
    if not isinstance(value, str):
        raise OperatorError("Kubernetes storage quantity is invalid")
    match = re.fullmatch(r"([1-9][0-9]*)(Ki|Mi|Gi|Ti)", value)
    if not match:
        raise OperatorError("Kubernetes storage quantity is invalid")
    factors = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
    }
    return int(match.group(1)) * factors[match.group(2)]


def mempalace_collection_name(
    *, palace_id: str, namespace: str, collection_name: str
) -> str:
    """Derive the v3.5.0 Qdrant name used by the exact runtime image."""

    def slug(value: str, fallback: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or fallback
        if len(safe) <= 64:
            return safe
        suffix = hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
        return f"{safe[:51]}_{suffix}"

    if not all(
        isinstance(value, str) and value
        for value in (palace_id, namespace, collection_name)
    ):
        raise OperatorError("MemPalace collection derivation input is invalid")
    palace_hash = hashlib.sha256(
        palace_id.encode("utf-8", errors="surrogatepass")
    ).hexdigest()[:16]
    return "_".join(
        (
            "mempalace",
            slug(namespace, "namespace"),
            palace_hash,
            slug(collection_name, "collection"),
        )
    )


def regular_file(path: Path, *, max_bytes: int = 512 * 1024 * 1024) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as error:
        raise OperatorError("required private file is unavailable") from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or details.st_size <= 0
        or details.st_size > max_bytes
    ):
        raise OperatorError("required private file is unavailable")
    return details


def private_directory(path: Path, *, create: bool = False) -> Path:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
        details = path.lstat()
    except OSError as error:
        raise OperatorError("private directory is unavailable") from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise OperatorError("private directory is unavailable")
    return path


def load_json(path: Path, *, private: bool = False) -> dict[str, object]:
    details = regular_file(path, max_bytes=16 * 1024 * 1024)
    if private and stat.S_IMODE(details.st_mode) & 0o077:
        raise OperatorError("private control file mode is unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorError("operator JSON input is invalid") from error
    if not isinstance(value, dict):
        raise OperatorError("operator JSON input is invalid")
    return value


def write_private(path: Path, value: object) -> None:
    private_directory(path.parent, create=True)
    if path.exists() or path.is_symlink():
        raise OperatorError("operator response path already exists")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise OperatorError("operator response could not be written") from error


def exact_mapping(value: object, keys: set[str], message: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise OperatorError(message)
    return dict(value)


def safe_name(value: object, message: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise OperatorError(message)
    return value


def safe_path(value: object, *, root: Path, message: str) -> Path:
    if not isinstance(value, str):
        raise OperatorError(message)
    path = Path(value)
    if not path.is_absolute():
        raise OperatorError(message)
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise OperatorError(message) from error
    return resolved


def validate_operation_payload(operation: str, payload: object) -> dict[str, object]:
    """Validate the complete adapter request surface before any live action."""
    schemas = {
        "inspect-preflight": {"bindings", "expected_count"},
        "render-manifests": {"operator_markers", "target_set"},
        "validate-manifests": {"rendered", "mode"},
        "apply-manifests": {"rendered"},
        "inspect-runtime": set(),
        "load-backup-inputs": set(),
        "apply-backup-job": {"job_path"},
        "wait-backup-job": set(),
        "remote-package-inventory": set(),
        "download-backup-package": {"package_dir"},
        "recover-uploaded-snapshot": {
            "target_collection",
            "snapshot_path",
            "priority",
        },
        "qdrant-request": {"method", "path", "body"},
        "run-phase20-parity": set(),
        "run-exact-image-probe": set(),
        "verify-prestate": {"prestate"},
    }
    if operation not in OPERATIONS or set(schemas) != OPERATIONS:
        raise OperatorError("operator operation is not allowlisted")
    request = exact_mapping(payload, schemas[operation], "operator request is invalid")
    if operation == "inspect-preflight":
        if (
            not isinstance(request["bindings"], Mapping)
            or not request["bindings"]
            or any(
                not isinstance(value, str) or not SHA256.fullmatch(value)
                for value in request["bindings"].values()
            )
            or isinstance(request["expected_count"], bool)
            or not isinstance(request["expected_count"], int)
            or request["expected_count"] <= 0
        ):
            raise OperatorError("operator request is invalid")
    elif operation == "render-manifests":
        markers = request["operator_markers"]
        if (
            not isinstance(markers, Mapping)
            or set(markers)
            != {
                "qdrant_storage",
                "mempalace_storage",
                "mempalace_image",
                "backup_cidr",
                "uploader_image",
                "private_collection",
            }
            or any(not isinstance(value, str) or not value for value in markers.values())
            or request["target_set"] != list(TARGETS)
        ):
            raise OperatorError("operator request is invalid")
    elif operation == "validate-manifests":
        if not isinstance(request["rendered"], Mapping) or request["mode"] not in {
            "client",
            "server",
        }:
            raise OperatorError("operator request is invalid")
    elif operation == "apply-manifests" and not isinstance(
        request["rendered"], Mapping
    ):
        raise OperatorError("operator request is invalid")
    elif operation in {"apply-backup-job", "download-backup-package"}:
        key = "job_path" if operation == "apply-backup-job" else "package_dir"
        if not isinstance(request[key], str) or not Path(request[key]).is_absolute():
            raise OperatorError("operator request is invalid")
    elif operation == "recover-uploaded-snapshot":
        if (
            not isinstance(request["target_collection"], str)
            or not SAFE_NAME.fullmatch(request["target_collection"])
            or not isinstance(request["snapshot_path"], str)
            or not Path(request["snapshot_path"]).is_absolute()
            or request["priority"] != "snapshot"
        ):
            raise OperatorError("operator request is invalid")
    elif operation == "qdrant-request":
        if (
            request["method"] not in {"GET", "POST", "PUT", "DELETE"}
            or not isinstance(request["path"], str)
            or not request["path"].startswith("/")
            or "://" in request["path"]
        ):
            raise OperatorError("operator request is invalid")
    elif operation == "verify-prestate":
        prestate = request["prestate"]
        if (
            not isinstance(prestate, Mapping)
            or set(prestate)
            != {
                "active_alias_sha256",
                "nginx_sha256",
                "mcp_registration_sha256",
                "legacy_runtime_sha256",
                "schedule_sha256",
            }
            or any(
                not isinstance(value, str) or not SHA256.fullmatch(value)
                for value in prestate.values()
            )
        ):
            raise OperatorError("operator request is invalid")
    return request


class Runtime:
    """Concrete Kubernetes, Qdrant, and S3 operator implementation."""

    def __init__(self, config_path: Path) -> None:
        config = load_json(config_path, private=True)
        required = {
            "schema",
            "repo_root",
            "state_root",
            "bundle_dir",
            "baseline_snapshot_path",
            "kube_context",
            "source_secret_namespace",
            "source_secret_name",
            "mempalace_image",
            "uploader_image",
            "qdrant_storage",
            "mempalace_storage",
            "host_nginx_cidr",
            "backup_cidr",
            "private_collection",
            "protected_collection",
            "target_collection",
            "probe_alias",
            "expected_count",
            "expected_vector_config",
        }
        if set(config) != required or config.get("schema") != CONFIG_SCHEMA:
            raise OperatorError("private operator configuration is invalid")
        self.repo_root = Path(str(config["repo_root"])).resolve(strict=True)
        self.state_root = private_directory(Path(str(config["state_root"])), create=True)
        self.bundle_dir = private_directory(Path(str(config["bundle_dir"])))
        self.baseline_snapshot = Path(str(config["baseline_snapshot_path"])).resolve(
            strict=True
        )
        baseline_details = regular_file(self.baseline_snapshot)
        if stat.S_IMODE(baseline_details.st_mode) != 0o600:
            raise OperatorError("baseline snapshot mode is unsafe")
        self.context = safe_name(config["kube_context"], "Kubernetes context is invalid")
        self.source_secret_namespace = safe_name(
            config["source_secret_namespace"], "source Secret binding is invalid"
        )
        self.source_secret_name = safe_name(
            config["source_secret_name"], "source Secret binding is invalid"
        )
        self.config = config
        for key in ("mempalace_image", "uploader_image"):
            if not isinstance(config[key], str) or not IMAGE.fullmatch(config[key]):
                raise OperatorError("operator image binding is invalid")
        for key in (
            "private_collection",
            "protected_collection",
            "target_collection",
            "probe_alias",
        ):
            safe_name(config[key], "operator collection binding is invalid")
        if config["private_collection"] != config["protected_collection"]:
            raise OperatorError("backup collection binding is inconsistent")
        if (
            config["protected_collection"] == config["probe_alias"]
            or config["target_collection"] in {
                config["protected_collection"],
                config["probe_alias"],
            }
        ):
            raise OperatorError("operator collection binding is invalid")
        expected_probe_alias = mempalace_collection_name(
            palace_id="/data/palace",
            namespace="SolidStats",
            collection_name="mempalace_drawers",
        )
        if config["probe_alias"] != expected_probe_alias:
            raise OperatorError("operator compatibility alias binding is invalid")
        if (
            isinstance(config["expected_count"], bool)
            or not isinstance(config["expected_count"], int)
            or config["expected_count"] <= 0
            or not isinstance(config["expected_vector_config"], Mapping)
            or not config["expected_vector_config"]
        ):
            raise OperatorError("operator parity binding is invalid")
        for key in ("host_nginx_cidr", "backup_cidr"):
            try:
                network = ipaddress.ip_network(str(config[key]), strict=True)
            except ValueError as error:
                raise OperatorError("operator network binding is invalid") from error
            if network.prefixlen != network.max_prefixlen:
                raise OperatorError("operator network binding is invalid")
        self.render_root = private_directory(self.state_root / "rendered", create=True)
        self.secret_root = private_directory(self.state_root / "secrets", create=True)
        self.qdrant_key = self.secret_root / "qdrant-token"
        self.mcp_token = self.secret_root / "mcp-token"
        for path in (self.qdrant_key, self.mcp_token):
            if not path.exists():
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="ascii") as output:
                    output.write(secrets.token_urlsafe(48))
            details = regular_file(path, max_bytes=256)
            if stat.S_IMODE(details.st_mode) != 0o600:
                raise OperatorError("private token mode is unsafe")

    def _run(
        self,
        command: list[str],
        *,
        timeout: float,
        input_bytes: bytes | None = None,
        stdout_file: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> bytes:
        if timeout <= 0 or timeout > 3600:
            raise OperatorError("operator command timeout is invalid")
        output_handle = None
        try:
            if stdout_file is not None:
                private_directory(stdout_file.parent, create=True)
                output_handle = stdout_file.open("xb")
                os.chmod(stdout_file, 0o600)
            result = subprocess.run(
                command,
                input=input_bytes,
                stdout=output_handle or subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=None if environment is None else {**os.environ, **environment},
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OperatorError("bounded operator command failed") from error
        finally:
            if output_handle is not None:
                output_handle.close()
        if result.returncode != 0:
            raise OperatorError("bounded operator command failed")
        payload = b"" if stdout_file is not None else result.stdout
        if not isinstance(payload, bytes) or len(payload) > 64 * 1024 * 1024:
            raise OperatorError("bounded operator output is invalid")
        return payload

    def _kubectl(
        self,
        args: list[str],
        *,
        timeout: float = 180,
        input_value: object | None = None,
    ) -> bytes:
        command = ["kubectl", "--context", self.context, *args]
        return self._run(
            command,
            timeout=timeout,
            input_bytes=None if input_value is None else canonical(input_value) + b"\n",
        )

    def _kubectl_json(self, args: list[str], *, timeout: float = 180) -> object:
        try:
            return json.loads(self._kubectl([*args, "-o", "json"], timeout=timeout))
        except json.JSONDecodeError as error:
            raise OperatorError("Kubernetes response is invalid") from error

    def _namespace_exists(self) -> bool:
        result = subprocess.run(
            ["kubectl", "--context", self.context, "get", "namespace", NAMESPACE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return result.returncode == 0

    def _raw_kubernetes_json(self, path: str) -> object:
        if not path.startswith("/api/") or ".." in path:
            raise OperatorError("Kubernetes raw path is invalid")
        try:
            return json.loads(self._kubectl(["get", "--raw", path], timeout=60))
        except json.JSONDecodeError as error:
            raise OperatorError("Kubernetes response is invalid") from error

    @staticmethod
    def _registry_request(url: str, *, accept: str, token: str = "") -> bytes:
        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib_request.Request(url, headers=headers)
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                body = response.read(16 * 1024 * 1024 + 1)
        except urllib_error.HTTPError as error:
            if error.code != 401 or token:
                raise OperatorError("immutable image registry probe failed") from error
            challenge = error.headers.get("WWW-Authenticate", "")
            fields = dict(re.findall(r'(realm|service|scope)="([^"]+)"', challenge))
            if not challenge.startswith("Bearer ") or set(fields) != {
                "realm",
                "service",
                "scope",
            }:
                raise OperatorError("immutable image registry probe failed") from error
            query = urllib_parse.urlencode(
                {"service": fields["service"], "scope": fields["scope"]}
            )
            try:
                with urllib_request.urlopen(
                    f"{fields['realm']}?{query}", timeout=30
                ) as auth:
                    value = json.loads(auth.read(1024 * 1024 + 1))
            except Exception as auth_error:
                raise OperatorError("immutable image registry probe failed") from auth_error
            registry_token = value.get("token") if isinstance(value, Mapping) else None
            if not isinstance(registry_token, str) or not registry_token:
                raise OperatorError("immutable image registry probe failed")
            return Runtime._registry_request(url, accept=accept, token=registry_token)
        except OSError as error:
            raise OperatorError("immutable image registry probe failed") from error
        if not body or len(body) > 16 * 1024 * 1024:
            raise OperatorError("immutable image registry probe failed")
        return body

    def _verify_mempalace_registry_image(self) -> None:
        image = self.config["mempalace_image"]
        if image != OFFICIAL_MEMPALACE_IMAGE:
            raise OperatorError("MemPalace image is not the approved registry artifact")
        repository, manifest_digest = str(image).split("@", 1)
        registry, name = repository.split("/", 1)
        manifest_url = f"https://{registry}/v2/{name}/manifests/{manifest_digest}"
        manifest_raw = self._registry_request(
            manifest_url,
            accept=(
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.docker.distribution.manifest.v2+json"
            ),
        )
        if f"sha256:{hashlib.sha256(manifest_raw).hexdigest()}" != manifest_digest:
            raise OperatorError("immutable image registry probe failed")
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as error:
            raise OperatorError("immutable image registry probe failed") from error
        config = manifest.get("config") if isinstance(manifest, Mapping) else None
        if not isinstance(config, Mapping) or config.get("digest") != OFFICIAL_MEMPALACE_CONFIG:
            raise OperatorError("immutable image config binding changed")
        config_raw = self._registry_request(
            f"https://{registry}/v2/{name}/blobs/{OFFICIAL_MEMPALACE_CONFIG}",
            accept="application/vnd.oci.image.config.v1+json",
        )
        if f"sha256:{hashlib.sha256(config_raw).hexdigest()}" != OFFICIAL_MEMPALACE_CONFIG:
            raise OperatorError("immutable image config binding changed")
        try:
            image_config = json.loads(config_raw)
        except json.JSONDecodeError as error:
            raise OperatorError("immutable image config binding changed") from error
        runtime = image_config.get("config") if isinstance(image_config, Mapping) else None
        if (
            image_config.get("architecture") != "amd64"
            or image_config.get("os") != "linux"
            or not isinstance(runtime, Mapping)
        ):
            raise OperatorError("immutable image runtime contract changed")
        if runtime.get("Entrypoint") != ["docker-entrypoint.sh"] or runtime.get(
            "Cmd"
        ) != ["mcp"]:
            raise OperatorError("immutable image runtime contract changed")

    def _verify_uploader_registry_image(self) -> None:
        image = self.config["uploader_image"]
        if image != OFFICIAL_AWS_CLI_IMAGE:
            raise OperatorError("backup uploader is not the approved registry artifact")
        raw = self._run(["docker", "manifest", "inspect", str(image)], timeout=60)
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OperatorError("immutable uploader registry probe failed") from error
        config = manifest.get("config") if isinstance(manifest, Mapping) else None
        layers = manifest.get("layers") if isinstance(manifest, Mapping) else None
        if (
            manifest.get("schemaVersion") != 2
            or not isinstance(config, Mapping)
            or not SHA256.fullmatch(str(config.get("digest", "")).removeprefix("sha256:"))
            or not isinstance(layers, list)
            or not layers
        ):
            raise OperatorError("immutable uploader registry probe failed")

    @staticmethod
    def _sigv4_key(secret: str, date: str, region: str) -> bytes:
        date_key = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
        region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()

    def _probe_s3(self) -> None:
        values = self._source_s3_values()
        bucket = values["S3_BUCKET"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise OperatorError("source S3 binding is incomplete")
        path = "/" + urllib_parse.quote(bucket, safe="")
        try:
            response = urllib_request.urlopen(
                urllib_request.Request(S3_ENDPOINT + path, method="HEAD"), timeout=20
            )
            response.close()
        except urllib_error.HTTPError:
            pass
        except OSError as error:
            raise OperatorError("source S3 endpoint is unreachable") from error
        region = S3_REGION
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = now.strftime("%Y%m%d")
        query = "list-type=2&max-keys=1"
        host = urllib_parse.urlparse(S3_ENDPOINT).netloc
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_headers = (
            f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{timestamp}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            ["GET", path, query, canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{short_date}/{region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                timestamp,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._sigv4_key(values["S3_SECRET_ACCESS_KEY"], short_date, region),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={values['S3_ACCESS_KEY_ID']}/{scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )
        signed = urllib_request.Request(
            f"{S3_ENDPOINT}{path}?{query}",
            headers={
                "Authorization": authorization,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": timestamp,
            },
        )
        try:
            with urllib_request.urlopen(signed, timeout=30) as response:
                body = response.read(1024 * 1024 + 1)
        except Exception as error:
            raise OperatorError("source S3 authenticated probe failed") from error
        if len(body) > 1024 * 1024:
            raise OperatorError("source S3 authenticated probe failed")

    def _public_route_state(self) -> dict[str, object]:
        request = urllib_request.Request(MEMORY_PUBLIC_URL, method="GET")
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                status = response.status
        except urllib_error.HTTPError as error:
            status = error.code
        except OSError as error:
            raise OperatorError("public nginx pre-state probe failed") from error
        return {"url_binding": digest(MEMORY_PUBLIC_URL), "status": status}

    def _mcp_client_state(self) -> tuple[dict[str, object], int]:
        raw = self._run(["codex", "mcp", "list", "--json"], timeout=30)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OperatorError("MCP client pre-state probe failed") from error
        entries = (
            value
            if isinstance(value, list)
            else value.get("servers")
            if isinstance(value, Mapping)
            else None
        )
        if not isinstance(entries, list):
            raise OperatorError("MCP client pre-state probe failed")
        writers = 0
        legacy = []
        replacement = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            transport = entry.get("transport")
            url = entry.get("url")
            if not isinstance(url, str) and isinstance(transport, Mapping):
                url = transport.get("url")
            enabled = entry.get("enabled") is True
            name = entry.get("name")
            if name == "mempalace" and url == LEGACY_SOLIDSTATS_MCP_URL:
                legacy.append(
                    {
                        "name": "mempalace",
                        "url_binding_sha256": digest(LEGACY_SOLIDSTATS_MCP_URL),
                        "enabled": enabled,
                        "write_capability": "frozen-read-only-contract",
                    }
                )
            elif name == "solidstats_memory" and url == MEMORY_PUBLIC_URL:
                replacement.append(
                    {
                        "name": "solidstats_memory",
                        "url_binding_sha256": digest(MEMORY_PUBLIC_URL),
                        "enabled": enabled,
                        "write_capability": "unproven-by-registration",
                    }
                )
        return {
            "registration_sha256": digest(value),
            "legacy": legacy,
            "replacement": replacement,
        }, writers

    def _measure_prestate(self) -> tuple[dict[str, str], dict[str, object]]:
        namespace_exists = self._namespace_exists()
        if namespace_exists:
            aliases = self._qdrant("GET", "/aliases")
            alias_result = aliases.get("result") if isinstance(aliases, Mapping) else None
            alias_items = (
                alias_result.get("aliases") if isinstance(alias_result, Mapping) else None
            )
            if not isinstance(alias_items, list):
                raise OperatorError("active alias pre-state probe failed")
            alias_state = {"aliases": alias_items}
            schedule = self._kubectl_json(
                ["-n", NAMESPACE, "get", "cronjob", "solidstats-memory-backup"]
            )
            schedule_spec = schedule.get("spec") if isinstance(schedule, Mapping) else None
            if not isinstance(schedule_spec, Mapping):
                raise OperatorError("schedule pre-state probe failed")
            schedule_state = {"enabled": schedule_spec.get("suspend") is not True}
        else:
            alias_state = {"aliases": []}
            schedule_state = {"enabled": False}
        client_state, writer_count = self._mcp_client_state()
        nginx_state = self._public_route_state()
        prestate = {
            "active_alias_sha256": digest(alias_state),
            "nginx_sha256": digest(nginx_state),
            "mcp_registration_sha256": client_state["registration_sha256"],
            "legacy_runtime_sha256": digest(client_state["legacy"]),
            "schedule_sha256": digest(schedule_state),
        }
        replacement_enabled = any(
            entry.get("enabled") is True for entry in client_state["replacement"]
        )
        return prestate, {
            "stable": writer_count == 0 and not replacement_enabled,
            "writer_count": writer_count,
        }

    def _measure_capacity(self) -> dict[str, int]:
        snapshot_bytes = regular_file(self.baseline_snapshot).st_size
        requested = storage_bytes(self.config["qdrant_storage"])
        classes = self._kubectl_json(["get", "storageclass"])
        class_items = classes.get("items") if isinstance(classes, Mapping) else None
        defaults = []
        for item in class_items or []:
            metadata = item.get("metadata") if isinstance(item, Mapping) else None
            annotations = (
                metadata.get("annotations") if isinstance(metadata, Mapping) else None
            )
            if isinstance(annotations, Mapping) and annotations.get(
                "storageclass.kubernetes.io/is-default-class"
            ) == "true":
                defaults.append(item)
        if len(defaults) != 1 or (
            defaults[0].get("provisioner") != "rancher.io/local-path"
            or defaults[0].get("volumeBindingMode") != "WaitForFirstConsumer"
        ):
            raise OperatorError("local-path storage binding is not measurable")
        nodes = self._kubectl_json(["get", "nodes"])
        node_items = nodes.get("items") if isinstance(nodes, Mapping) else None
        if not isinstance(node_items, list) or not node_items:
            raise OperatorError("live node capacity is unavailable")
        node_free = []
        for node in node_items:
            metadata = node.get("metadata") if isinstance(node, Mapping) else None
            name = metadata.get("name") if isinstance(metadata, Mapping) else None
            if not isinstance(name, str):
                continue
            summary = self._raw_kubernetes_json(
                f"/api/v1/nodes/{urllib_parse.quote(name, safe='')}/proxy/stats/summary"
            )
            node_state = summary.get("node") if isinstance(summary, Mapping) else None
            filesystem = node_state.get("fs") if isinstance(node_state, Mapping) else None
            available = (
                filesystem.get("availableBytes")
                if isinstance(filesystem, Mapping)
                else None
            )
            if (
                isinstance(available, int)
                and not isinstance(available, bool)
                and available > 0
            ):
                node_free.append(available)
        if not node_free:
            raise OperatorError("live node capacity is unavailable")
        return {
            "snapshot_bytes": snapshot_bytes,
            "pvc_requested_bytes": requested,
            "node_free_bytes": min(node_free),
            "reserve_bytes": RESTORE_RESERVE_BYTES,
        }

    def _inspect_live_pvc_capacity(self) -> dict[str, int]:
        pvc = self._kubectl_json(
            ["-n", NAMESPACE, "get", "pvc", "qdrant-data-qdrant-0"]
        )
        status = pvc.get("status") if isinstance(pvc, Mapping) else None
        capacity = status.get("capacity") if isinstance(status, Mapping) else None
        actual = storage_bytes(
            capacity.get("storage") if isinstance(capacity, Mapping) else None
        )
        raw = self._kubectl(
            [
                "-n",
                NAMESPACE,
                "exec",
                "statefulset/qdrant",
                "--",
                "df",
                "-Pk",
                "/qdrant/storage",
            ],
            timeout=30,
        )
        lines = raw.decode("ascii", errors="strict").splitlines()
        if len(lines) != 2:
            raise OperatorError("live PVC filesystem capacity is unavailable")
        fields = lines[1].split()
        if len(fields) < 4 or not fields[3].isdigit():
            raise OperatorError("live PVC filesystem capacity is unavailable")
        free = int(fields[3]) * 1024
        if free <= 0:
            raise OperatorError("live PVC filesystem capacity is unavailable")
        return {"pvc_capacity_bytes": actual, "pvc_free_bytes": free}

    @contextmanager
    def _port_forward(self, resource: str, remote_port: int) -> Iterator[int]:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        local_port = int(listener.getsockname()[1])
        listener.close()
        command = [
            "kubectl",
            "--context",
            self.context,
            "-n",
            NAMESPACE,
            "port-forward",
            resource,
            f"{local_port}:{remote_port}",
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise OperatorError("private service tunnel failed")
                try:
                    with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                raise OperatorError("private service tunnel timed out")
            yield local_port
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _qdrant(
        self,
        method: str,
        path: str,
        body: object = None,
        *,
        timeout: float = 60,
    ) -> object:
        with self._port_forward("statefulset/qdrant", 6333) as port:
            headers = {
                "Accept": "application/json",
                "api-key": self.qdrant_key.read_text(encoding="ascii"),
            }
            data = None
            if body is not None:
                data = canonical(body)
                headers["Content-Type"] = "application/json"
            request = urllib_request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=data,
                headers=headers,
                method=method,
            )
            try:
                with urllib_request.urlopen(request, timeout=timeout) as response:
                    payload = response.read(64 * 1024 * 1024 + 1)
            except Exception as error:
                if getattr(error, "code", None) == 404:
                    return {"not_found": True}
                raise OperatorError("private Qdrant request failed") from error
        if not payload or len(payload) > 64 * 1024 * 1024:
            raise OperatorError("private Qdrant response is invalid")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise OperatorError("private Qdrant response is invalid") from error
        if not isinstance(value, dict):
            raise OperatorError("private Qdrant response is invalid")
        return value

    def inspect_preflight(self, payload: dict[str, object]) -> object:
        request = exact_mapping(
            payload, {"bindings", "expected_count"}, "preflight request is invalid"
        )
        bindings = request["bindings"]
        if (
            not isinstance(bindings, Mapping)
            or not bindings
            or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in bindings.values())
            or request["expected_count"] != self.config["expected_count"]
        ):
            raise OperatorError("preflight request is invalid")
        if self._namespace_exists():
            raise OperatorError("isolated namespace pre-state changed")
        self._kubectl(["version", "--request-timeout=20s"], timeout=30)
        self._verify_mempalace_registry_image()
        self._verify_uploader_registry_image()
        self._probe_s3()
        prestate, quiescence = self._measure_prestate()
        if quiescence != {"stable": True, "writer_count": 0}:
            raise OperatorError("write quiescence is not proven")
        capacity = self._measure_capacity()
        prestate_path = self.state_root / "prestate.json"
        if prestate_path.exists():
            if load_json(prestate_path, private=True) != prestate:
                raise OperatorError("preflight pre-state replay collision")
        else:
            write_private(prestate_path, prestate)
        return {
            "reachability": {"kubernetes": True, "s3": True},
            "prestate": prestate,
            "quiescence": quiescence,
            "capacity": capacity,
            "operator_markers": {
                "qdrant_storage": self.config["qdrant_storage"],
                "mempalace_storage": self.config["mempalace_storage"],
                "mempalace_image": self.config["mempalace_image"],
                "backup_cidr": self.config["backup_cidr"],
                "uploader_image": self.config["uploader_image"],
                "private_collection": self.config["private_collection"],
            },
            "target_set": list(TARGETS),
        }

    def _render_descriptor(self) -> dict[str, object]:
        files = []
        for relative in TARGETS:
            path = self.render_root / Path(relative).name
            files.append({"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"schema": SCHEMA, "files": files, "digest": digest(files)}

    def render_manifests(self, payload: dict[str, object]) -> object:
        request = exact_mapping(
            payload,
            {"operator_markers", "target_set"},
            "render request is invalid",
        )
        markers = request["operator_markers"]
        if (
            not isinstance(markers, Mapping)
            or set(markers)
            != {
                "qdrant_storage",
                "mempalace_storage",
                "mempalace_image",
                "backup_cidr",
                "uploader_image",
                "private_collection",
            }
            or request["target_set"] != list(TARGETS)
        ):
            raise OperatorError("render request is invalid")
        expected = {
            "qdrant_storage": self.config["qdrant_storage"],
            "mempalace_storage": self.config["mempalace_storage"],
            "mempalace_image": self.config["mempalace_image"],
            "backup_cidr": self.config["backup_cidr"],
            "uploader_image": self.config["uploader_image"],
            "private_collection": self.config["private_collection"],
        }
        if dict(markers) != expected:
            raise OperatorError("render request binding changed")
        replacements = {
            marker: str(self.config[key])
            for marker, key in MARKERS.items()
        }
        for relative in TARGETS:
            source = self.repo_root / relative
            regular_file(source, max_bytes=4 * 1024 * 1024)
            text = source.read_text(encoding="utf-8")
            for marker, replacement in replacements.items():
                text = text.replace(marker, replacement)
            if "MEMORY_OPERATOR_" in text:
                raise OperatorError("rendered manifest retains an operator marker")
            target = self.render_root / source.name
            if target.exists():
                if target.read_text(encoding="utf-8") != text:
                    raise OperatorError("rendered manifest replay collision")
            else:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write(text)
        descriptor = self._render_descriptor()
        state = self.state_root / "rendered.json"
        if not state.exists():
            write_private(state, descriptor)
        elif load_json(state, private=True) != descriptor:
            raise OperatorError("rendered manifest replay collision")
        return descriptor

    def _require_rendered(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping) or dict(value) != self._render_descriptor():
            raise OperatorError("rendered manifest descriptor is invalid")
        return dict(value)

    def validate_manifests(self, payload: dict[str, object]) -> object:
        request = exact_mapping(
            payload, {"rendered", "mode"}, "manifest validation request is invalid"
        )
        self._require_rendered(request["rendered"])
        if request["mode"] not in {"client", "server"}:
            raise OperatorError("manifest validation mode is invalid")
        arguments = [
            "-n",
            NAMESPACE,
            "apply",
            f"--dry-run={request['mode']}",
        ]
        if request["mode"] == "server":
            arguments.insert(3, "--server-side")
        manifest_root = self.render_root
        if request["mode"] == "server" and not self._namespace_exists():
            # A server dry-run against a namespaced object fails when the
            # isolated namespace is intentionally absent. Validate byte-for-byte
            # rendered content against an existing namespace without creating
            # any object before the controller's final pre-state recheck.
            manifest_root = private_directory(
                self.state_root / "server-dry-run", create=True
            )
            arguments[1] = self.source_secret_namespace
            for relative in TARGETS:
                source = self.render_root / Path(relative).name
                target = manifest_root / source.name
                text = source.read_text(encoding="utf-8").replace(
                    f"namespace: {NAMESPACE}",
                    f"namespace: {self.source_secret_namespace}",
                )
                if target.exists():
                    if target.read_text(encoding="utf-8") != text:
                        raise OperatorError("server dry-run replay collision")
                else:
                    descriptor = os.open(
                        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                        output.write(text)
        for relative in TARGETS:
            arguments.extend(["-f", str(manifest_root / Path(relative).name)])
        self._kubectl(arguments)
        return {"valid": True}

    def _source_s3_values(self) -> dict[str, str]:
        secret = self._kubectl_json(
            ["-n", self.source_secret_namespace, "get", "secret", self.source_secret_name]
        )
        data = secret.get("data") if isinstance(secret, Mapping) else None
        if not isinstance(data, Mapping):
            raise OperatorError("source S3 binding is incomplete")
        import base64

        values = {}
        for key in ("S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
            try:
                values[key] = base64.b64decode(str(data[key]), validate=True).decode("utf-8")
            except Exception as error:
                raise OperatorError("source S3 binding is incomplete") from error
            if not values[key]:
                raise OperatorError("source S3 binding is incomplete")
        return values

    def _apply_runtime_secrets(self) -> None:
        s3 = self._source_s3_values()
        admin_key = self.qdrant_key.read_text(encoding="ascii")
        collection_access = [
            {"collection": self.config["private_collection"], "access": "rw"}
        ]
        mempalace_token = qdrant_jwt(
            admin_key,
            {"sub": "solidstats-memory-mempalace", "access": collection_access},
        )
        backup_token = qdrant_jwt(
            admin_key,
            {"sub": "solidstats-memory-backup", "access": collection_access},
        )
        observer_token = qdrant_jwt(
            admin_key,
            {
                "sub": "solidstats-memory-observer",
                "access": [
                    {
                        "collection": self.config["private_collection"],
                        "access": "r",
                    }
                ],
            },
        )
        documents = [
            ("qdrant-runtime", {"QDRANT_API_KEY": admin_key}),
            (
                "mempalace-runtime",
                {
                    "MEMPALACE_QDRANT_API_KEY": mempalace_token,
                    "MEMPALACE_MCP_HTTP_TOKEN": self.mcp_token.read_text(encoding="ascii"),
                },
            ),
            (
                "memory-backup-runtime",
                {
                    "QDRANT_API_KEY": backup_token,
                    "S3_BUCKET": s3["S3_BUCKET"],
                    "AWS_ACCESS_KEY_ID": s3["S3_ACCESS_KEY_ID"],
                    "AWS_SECRET_ACCESS_KEY": s3["S3_SECRET_ACCESS_KEY"],
                },
            ),
            ("memory-observer-runtime", {"QDRANT_API_KEY": observer_token}),
        ]
        for name, string_data in documents:
            document = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name, "namespace": NAMESPACE},
                "type": "Opaque",
                "stringData": string_data,
            }
            self._kubectl(
                ["-n", NAMESPACE, "apply", "--server-side", "-f", "-"],
                input_value=document,
            )

    def _import_bundle(self) -> None:
        collection = str(self.config["protected_collection"])
        points_path = self.bundle_dir / "points.jsonl"
        regular_file(points_path)
        first = None
        count = 0
        with points_path.open(encoding="utf-8") as source:
            batch = []
            for line in source:
                try:
                    point = json.loads(line)
                except json.JSONDecodeError as error:
                    raise OperatorError("private bundle point is invalid") from error
                if not isinstance(point, dict) or set(point) != {"id", "payload", "vector"}:
                    raise OperatorError("private bundle point is invalid")
                if first is None:
                    first = point
                    vector = point.get("vector")
                    vector_config = self.config["expected_vector_config"]
                    if (
                        not isinstance(vector, list)
                        or not vector
                        or not isinstance(vector_config, Mapping)
                        or vector_config.get("size") != len(vector)
                    ):
                        raise OperatorError("private bundle vector is invalid")
                    created = self._qdrant(
                        "PUT",
                        f"/collections/{urllib_parse.quote(collection, safe='')}",
                        {"vectors": dict(vector_config)},
                    )
                    if not isinstance(created, Mapping) or created.get("result") is not True:
                        raise OperatorError("private collection creation failed")
                batch.append(point)
                count += 1
                if len(batch) == 128:
                    self._upsert(collection, batch)
                    batch = []
            if batch:
                self._upsert(collection, batch)
        if count != self.config["expected_count"]:
            raise OperatorError("private bundle count is invalid")

    def _upsert(self, collection: str, points: list[dict[str, object]]) -> None:
        response = self._qdrant(
            "PUT",
            f"/collections/{urllib_parse.quote(collection, safe='')}/points?wait=true",
            {"points": points},
        )
        result = response.get("result") if isinstance(response, Mapping) else None
        if not isinstance(result, Mapping) or result.get("status") != "completed":
            raise OperatorError("private collection import failed")

    def apply_manifests(self, payload: dict[str, object]) -> object:
        request = exact_mapping(payload, {"rendered"}, "manifest apply request is invalid")
        self._require_rendered(request["rendered"])
        namespace = self.repo_root / "k8s/memory/00-namespace.yaml"
        self._kubectl(["apply", "--server-side", "-f", str(namespace)])
        self._apply_runtime_secrets()
        qdrant = self.render_root / "10-qdrant.yaml"
        network = self.render_root / "30-network-policy.yaml"
        self._kubectl(["-n", NAMESPACE, "apply", "--server-side", "-f", str(qdrant), "-f", str(network)])
        self._kubectl(
            ["-n", NAMESPACE, "rollout", "status", "statefulset/qdrant", "--timeout=300s"],
            timeout=330,
        )
        self._import_bundle()
        for name in ("20-mempalace.yaml", "40-backup.yaml"):
            self._kubectl(["-n", NAMESPACE, "apply", "--server-side", "-f", str(self.render_root / name)])
        return {
            "applied": True,
            "target_count": len(TARGETS),
            "marker_count": 6,
            "recurring_schedule_changed": False,
        }

    def inspect_runtime(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "runtime inspection request is invalid")
        self._kubectl(
            ["-n", NAMESPACE, "rollout", "status", "statefulset/qdrant", "--timeout=300s"],
            timeout=330,
        )
        self._kubectl(
            ["-n", NAMESPACE, "rollout", "status", "deployment/mempalace", "--timeout=300s"],
            timeout=330,
        )
        inventory = self._qdrant("GET", "/collections")
        result = inventory.get("result") if isinstance(inventory, Mapping) else None
        collections = result.get("collections") if isinstance(result, Mapping) else None
        if not isinstance(collections, list):
            raise OperatorError("isolated runtime is not ready")
        capacity = self._inspect_live_pvc_capacity()
        return {
            "qdrant_reachable": True,
            "workloads_ready": True,
            **capacity,
        }

    def load_backup_inputs(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "backup input request is invalid")
        cronjob = self._kubectl_json(
            ["-n", NAMESPACE, "get", "cronjob", "solidstats-memory-backup"]
        )
        bindings = load_json(self.state_root.parent / "00-preflight.json", private=True).get("bindings")
        if not isinstance(bindings, Mapping):
            raise OperatorError("backup binding state is unavailable")
        return {
            "cronjob": cronjob,
            "private_environment": {
                "BACKUP_RUN_ID": self.state_root.parent.name,
                "BACKUP_PREPARE_IMAGE": self.config["mempalace_image"],
                "BACKUP_S3_URI": (
                    f"s3://{self._source_s3_values()['S3_BUCKET']}/"
                    f"backups/solidstats-memory/{self.state_root.parent.name}/"
                ),
                "PHASE20_BINDINGS_JSON": canonical(bindings).decode("utf-8"),
            },
        }

    def apply_backup_job(self, payload: dict[str, object]) -> object:
        request = exact_mapping(payload, {"job_path"}, "backup Job request is invalid")
        job_path = safe_path(
            request["job_path"], root=self.state_root.parent, message="backup Job path is invalid"
        )
        regular_file(job_path, max_bytes=16 * 1024 * 1024)
        name = f"solidstats-memory-backup-{self.state_root.parent.name[:16]}"
        current = subprocess.run(
            ["kubectl", "--context", self.context, "-n", NAMESPACE, "get", "job", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if current.returncode == 0:
            return {"reused": True, "job_count": 1}
        self._kubectl(["-n", NAMESPACE, "apply", "--server-side", "-f", str(job_path)])
        return {"created": True, "job_count": 1}

    def wait_backup_job(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "backup wait request is invalid")
        name = f"solidstats-memory-backup-{self.state_root.parent.name[:16]}"
        deadline = time.monotonic() + 3300
        while time.monotonic() < deadline:
            job = self._kubectl_json(["-n", NAMESPACE, "get", "job", name])
            status = job.get("status") if isinstance(job, Mapping) else None
            conditions = status.get("conditions") if isinstance(status, Mapping) else None
            if isinstance(conditions, list):
                states = {
                    item.get("type"): item.get("status")
                    for item in conditions
                    if isinstance(item, Mapping)
                }
                if states.get("Complete") == "True":
                    return {"complete": True, "job_count": 1}
                if states.get("Failed") == "True":
                    raise OperatorError("backup Job failed")
            time.sleep(5)
        raise OperatorError("backup Job timed out")

    def _backup_pod(self) -> str:
        name = f"solidstats-memory-backup-{self.state_root.parent.name[:16]}"
        pods = self._kubectl_json(
            ["-n", NAMESPACE, "get", "pods", "-l", f"job-name={name}"]
        )
        items = pods.get("items") if isinstance(pods, Mapping) else None
        if not isinstance(items, list) or len(items) != 1:
            raise OperatorError("backup pod identity is invalid")
        metadata = items[0].get("metadata") if isinstance(items[0], Mapping) else None
        return safe_name(
            metadata.get("name") if isinstance(metadata, Mapping) else None,
            "backup pod identity is invalid",
        )

    def remote_package_inventory(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "remote inventory request is invalid")
        values = self._source_s3_values()
        prefix = (
            f"s3://{values['S3_BUCKET']}/backups/solidstats-memory/"
            f"{self.state_root.parent.name}/"
        )
        output = self._run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-e",
                "AWS_ACCESS_KEY_ID",
                "-e",
                "AWS_SECRET_ACCESS_KEY",
                "-e",
                "AWS_EC2_METADATA_DISABLED",
                str(self.config["uploader_image"]),
                "--endpoint-url",
                S3_ENDPOINT,
                "s3",
                "ls",
                prefix,
            ],
            timeout=300,
            environment={
                "AWS_ACCESS_KEY_ID": values["S3_ACCESS_KEY_ID"],
                "AWS_SECRET_ACCESS_KEY": values["S3_SECRET_ACCESS_KEY"],
                "AWS_EC2_METADATA_DISABLED": "true",
            },
        )
        names = sorted(
            line.rsplit(maxsplit=1)[-1]
            for line in output.decode("utf-8").splitlines()
            if line.strip()
        )
        if names != list(PACKAGE_MEMBERS):
            raise OperatorError("remote package inventory is invalid")
        return names

    def download_backup_package(self, payload: dict[str, object]) -> object:
        request = exact_mapping(payload, {"package_dir"}, "package download request is invalid")
        package_dir = safe_path(
            request["package_dir"], root=self.state_root.parent, message="package path is invalid"
        )
        private_directory(package_dir, create=True)
        values = self._source_s3_values()
        prefix = (
            f"s3://{values['S3_BUCKET']}/backups/solidstats-memory/"
            f"{self.state_root.parent.name}/"
        )
        self._run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "-e",
                "AWS_ACCESS_KEY_ID",
                "-e",
                "AWS_SECRET_ACCESS_KEY",
                "-e",
                "AWS_EC2_METADATA_DISABLED",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{package_dir}:/package",
                str(self.config["uploader_image"]),
                "--endpoint-url",
                S3_ENDPOINT,
                "s3",
                "cp",
                "--recursive",
                prefix,
                "/package",
                "--only-show-errors",
            ],
            timeout=1800,
            environment={
                "AWS_ACCESS_KEY_ID": values["S3_ACCESS_KEY_ID"],
                "AWS_SECRET_ACCESS_KEY": values["S3_SECRET_ACCESS_KEY"],
                "AWS_EC2_METADATA_DISABLED": "true",
            },
        )
        for name in PACKAGE_MEMBERS:
            target = package_dir / name
            regular_file(target)
            os.chmod(target, 0o600)
        return {"downloaded": True}

    def recover_uploaded_snapshot(self, payload: dict[str, object]) -> object:
        request = exact_mapping(
            payload,
            {"target_collection", "snapshot_path", "priority"},
            "snapshot recovery request is invalid",
        )
        target = safe_name(request["target_collection"], "restore target is invalid")
        if target != self.config["target_collection"] or request["priority"] != "snapshot":
            raise OperatorError("snapshot recovery request is invalid")
        snapshot = safe_path(
            request["snapshot_path"], root=self.state_root.parent, message="snapshot path is invalid"
        )
        regular_file(snapshot)
        boundary = secrets.token_hex(24)
        body = self.state_root / "snapshot-upload.multipart"
        with body.open("xb") as output, snapshot.open("rb") as source:
            os.chmod(body, 0o600)
            output.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"snapshot\"; filename=\"snapshot\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode())
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
            output.write(f"\r\n--{boundary}--\r\n".encode())
        with self._port_forward("statefulset/qdrant", 6333) as port:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1800)
            connection.putrequest(
                "POST",
                f"/collections/{urllib_parse.quote(target, safe='')}/snapshots/upload?priority=snapshot",
            )
            connection.putheader("api-key", self.qdrant_key.read_text(encoding="ascii"))
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(body.stat().st_size))
            connection.endheaders()
            with body.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            raw = response.read(4 * 1024 * 1024 + 1)
            connection.close()
        body.unlink()
        if response.status >= 300 or not raw or len(raw) > 4 * 1024 * 1024:
            raise OperatorError("snapshot upload recovery failed")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise OperatorError("snapshot upload recovery failed") from error
        return result

    def qdrant_request(self, payload: dict[str, object]) -> object:
        request = exact_mapping(payload, {"method", "path", "body"}, "Qdrant request is invalid")
        method = request["method"]
        path = request["path"]
        if method not in {"GET", "POST", "PUT", "DELETE"} or not isinstance(path, str):
            raise OperatorError("Qdrant request is invalid")
        allowed = {
            ("GET", "/collections"),
            ("GET", "/aliases"),
            ("POST", "/collections/aliases"),
        }
        dynamic = (
            re.fullmatch(r"/collections/[A-Za-z0-9._-]+", path)
            if method == "GET"
            else None
        )
        if (method, path) not in allowed and not (method == "GET" and dynamic):
            raise OperatorError("Qdrant request is not allowlisted")
        if dynamic and path.rsplit("/", 1)[-1] not in {
            self.config["protected_collection"],
            self.config["target_collection"],
            self.config["probe_alias"],
        }:
            raise OperatorError("Qdrant request is not allowlisted")
        if method == "POST" and path == "/collections/aliases":
            body = request["body"]
            actions = body.get("actions") if isinstance(body, Mapping) else None
            if not isinstance(actions, list) or len(actions) != 1:
                raise OperatorError("Qdrant alias action is invalid")
            action = actions[0]
            if not isinstance(action, Mapping) or len(action) != 1:
                raise OperatorError("Qdrant alias action is invalid")
            if "create_alias" in action:
                value = action["create_alias"]
                if not isinstance(value, Mapping) or dict(value) != {
                    "collection_name": self.config["target_collection"],
                    "alias_name": self.config["probe_alias"],
                }:
                    raise OperatorError("Qdrant alias action is invalid")
            elif "delete_alias" in action:
                value = action["delete_alias"]
                if not isinstance(value, Mapping) or dict(value) != {
                    "alias_name": self.config["probe_alias"]
                }:
                    raise OperatorError("Qdrant alias action is invalid")
            else:
                raise OperatorError("Qdrant alias action is invalid")
        result = self._qdrant(method, path, request["body"])
        if isinstance(result, Mapping) and result.get("not_found") is True:
            return {"not_found": True}
        return {"response": result}

    def run_phase20_parity(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "parity request is invalid")
        target = str(self.config["target_collection"])
        protected = str(self.config["protected_collection"])
        expected: dict[str, dict[str, object]] = {}
        ann_vectors: list[list[float]] = []
        with (self.bundle_dir / "points.jsonl").open(encoding="utf-8") as source:
            for line in source:
                point = json.loads(line)
                if not isinstance(point, dict) or not isinstance(point.get("id"), str):
                    raise OperatorError("private bundle parity input is invalid")
                expected[point["id"]] = point
                vector = point.get("vector")
                if len(ann_vectors) < 24:
                    if (
                        not isinstance(vector, list)
                        or len(vector) != self.config["expected_vector_config"].get("size")
                        or any(
                            isinstance(value, bool) or not isinstance(value, (int, float))
                            for value in vector
                        )
                    ):
                        raise OperatorError("private bundle parity input is invalid")
                    ann_vectors.append(vector)
        observed = 0
        offset = None
        while True:
            body: dict[str, object] = {"limit": 512, "with_payload": True, "with_vector": True}
            if offset is not None:
                body["offset"] = offset
            response = self._qdrant(
                "POST",
                f"/collections/{urllib_parse.quote(target, safe='')}/points/scroll",
                body,
            )
            result = response.get("result") if isinstance(response, Mapping) else None
            points = result.get("points") if isinstance(result, Mapping) else None
            if not isinstance(points, list):
                raise OperatorError("restored parity response is invalid")
            point_ids = [point.get("id") for point in points if isinstance(point, Mapping)]
            if len(point_ids) != len(points):
                raise OperatorError("restored parity response is invalid")
            baseline = self._qdrant(
                "POST",
                f"/collections/{urllib_parse.quote(protected, safe='')}/points",
                {"ids": point_ids, "with_payload": True, "with_vector": True},
            )
            baseline_result = baseline.get("result") if isinstance(baseline, Mapping) else None
            if not isinstance(baseline_result, list):
                raise OperatorError("protected parity response is invalid")
            baseline_by_id = {
                str(point.get("id")): point
                for point in baseline_result
                if isinstance(point, dict)
            }
            if len(baseline_by_id) != len(points):
                raise OperatorError("protected parity response is invalid")
            for point in points:
                if not isinstance(point, dict):
                    raise OperatorError("restored exact parity failed")
                point_id = str(point.get("id"))
                source = expected.pop(point_id, None)
                if (
                    not isinstance(source, dict)
                    or set(source) != {"id", "payload", "vector"}
                    or set(point) != {"id", "payload", "vector"}
                    or source.get("id") != point.get("id")
                    or source.get("payload") != point.get("payload")
                ):
                    raise OperatorError("restored exact parity failed")
                if baseline_by_id.get(point_id) != point:
                    raise OperatorError("restored exact parity failed")
                observed += 1
            offset = result.get("next_page_offset")
            if offset is None:
                break
        if expected or observed != self.config["expected_count"]:
            raise OperatorError("restored exact parity failed")
        if len(ann_vectors) != 24:
            raise OperatorError("restored ANN parity input is incomplete")
        for vector in ann_vectors:
            body = {
                "query": vector,
                "limit": 10,
                "with_payload": False,
                "with_vector": False,
            }
            baseline = self._qdrant(
                "POST",
                f"/collections/{urllib_parse.quote(protected, safe='')}/points/query",
                body,
            )
            restored = self._qdrant(
                "POST",
                f"/collections/{urllib_parse.quote(target, safe='')}/points/query",
                body,
            )
            baseline_result = baseline.get("result") if isinstance(baseline, Mapping) else None
            restored_result = restored.get("result") if isinstance(restored, Mapping) else None
            baseline_points = (
                baseline_result.get("points")
                if isinstance(baseline_result, Mapping)
                else None
            )
            restored_points = (
                restored_result.get("points")
                if isinstance(restored_result, Mapping)
                else None
            )
            if (
                not isinstance(baseline_points, list)
                or not baseline_points
                or baseline_points != restored_points
            ):
                raise OperatorError("restored ANN parity failed")
        return {
            "verdict": "pass",
            "record_count": observed,
            "field_exact": True,
            "id_exact": True,
            "metadata_exact": True,
            "timestamp_exact": True,
            "vector_exact": True,
            "exclusion_exact": True,
            "ann_exact": True,
        }

    def run_exact_image_probe(self, payload: dict[str, object]) -> object:
        exact_mapping(payload, set(), "exact image probe request is invalid")

        def decode_mcp(raw: bytes) -> dict[str, object]:
            if not raw or len(raw) > 4 * 1024 * 1024:
                raise OperatorError("exact image alias probe failed")
            candidates = [raw]
            candidates.extend(
                line[6:].strip()
                for line in raw.splitlines()
                if line.startswith(b"data: ")
            )
            for candidate in candidates:
                try:
                    value = json.loads(candidate)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict):
                    return value
            raise OperatorError("exact image alias probe failed")

        with self._port_forward("service/mempalace", 8765) as port:
            token = self.mcp_token.read_text(encoding="ascii")
            session = ""

            def call(message: Mapping[str, object]) -> dict[str, object]:
                nonlocal session
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                }
                if session:
                    headers["Mcp-Session-Id"] = session
                mcp_request = urllib_request.Request(
                    f"http://127.0.0.1:{port}/mcp",
                    data=canonical(dict(message)),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib_request.urlopen(mcp_request, timeout=60) as response:
                        session = response.headers.get("Mcp-Session-Id", session)
                        raw = response.read(4 * 1024 * 1024 + 1)
                except Exception as error:
                    raise OperatorError("exact image alias probe failed") from error
                decoded = decode_mcp(raw)
                if "error" in decoded:
                    raise OperatorError("exact image alias probe failed")
                return decoded

            initialized = call(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "phase21-probe", "version": "1"},
                    },
                }
            )
            if not session or not isinstance(initialized.get("result"), Mapping):
                raise OperatorError("exact image alias probe failed")
            listed = call(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            result = listed.get("result")
            tools = result.get("tools") if isinstance(result, Mapping) else None
            if not isinstance(tools, list):
                raise OperatorError("exact image alias probe failed")
            names = {
                item.get("name")
                for item in tools
                if isinstance(item, Mapping) and isinstance(item.get("name"), str)
            }
            tool_name = next(
                (
                    candidate
                    for candidate in ("mempalace_list_drawers", "list_drawers")
                    if candidate in names
                ),
                None,
            )
            if tool_name is None:
                raise OperatorError("exact image alias probe failed")
            called = call(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": {"wing": "infrastructure"},
                    },
                }
            )
            call_result = called.get("result")
            if not isinstance(call_result, Mapping) or call_result.get("isError") is True:
                raise OperatorError("exact image alias probe failed")
        return True

    def verify_prestate(self, payload: dict[str, object]) -> object:
        request = exact_mapping(payload, {"prestate"}, "pre-state request is invalid")
        stored = load_json(self.state_root / "prestate.json", private=True)
        if request["prestate"] != stored:
            raise OperatorError("active pre-state binding changed")
        observed, _quiescence = self._measure_prestate()
        if observed != stored:
            raise OperatorError("active pre-state changed")
        return {
            "active_state_unchanged": True,
            "active_alias_unchanged": True,
            "nginx_unchanged": True,
            "mcp_registration_unchanged": True,
            "legacy_runtime_unchanged": True,
            "recurring_schedule_unchanged": True,
        }

    def dispatch(self, operation: str, payload: dict[str, object]) -> object:
        payload = validate_operation_payload(operation, payload)
        handler = getattr(self, operation.replace("-", "_"), None)
        if operation not in OPERATIONS or handler is None:
            raise OperatorError("operator operation is not allowlisted")
        return handler(payload)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 3:
        return 64
    operation, request_value, response_value = arguments
    if operation not in OPERATIONS:
        return 64
    request_path = Path(request_value)
    response_path = Path(response_value)
    if not request_path.is_absolute() or not response_path.is_absolute():
        return 64
    try:
        request = load_json(request_path, private=True)
        config_value = os.environ.get("SOLIDSTATS_MEMORY_OPERATOR_CONFIG")
        if not config_value:
            raise OperatorError("private operator configuration is unavailable")
        runtime = Runtime(Path(config_value))
        result = runtime.dispatch(operation, request)
        write_private(response_path, {"ok": True, "result": result})
        return 0
    except (OSError, OperatorError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
