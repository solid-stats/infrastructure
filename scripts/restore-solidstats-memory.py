#!/usr/bin/env python3
"""Fail-closed backup and isolated-restore control for SolidStats memory."""

from __future__ import annotations

import argparse
from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Callable, Mapping, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


ROOT = Path(__file__).resolve().parents[1]
PHASE20_DIR = ROOT / ".planning/phases/20-local-corpus-migration"
DEFAULT_HANDOFF = PHASE20_DIR / "20-PHASE21-HANDOFF.json"
DEFAULT_EVIDENCE_DIR = ROOT / ".planning/phases/21-restore-cutover-recovery"
BACKUP_PACKAGE_SCHEMA = "solidstats-memory-backup-package/v1"
LOCK_SCHEMA = "solidstats-memory-restore-lock/v1"
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
PACKAGE_MEMBERS = {
    "SHA256SUMS",
    "manifest.json",
    "mempalace-metadata.tar",
    "qdrant.snapshot",
}
CHECKSUM_MEMBERS = (
    "manifest.json",
    "mempalace-metadata.tar",
    "qdrant.snapshot",
)
RUN_STAGES = (
    "preflight",
    "backup",
    "isolated-restore",
    "verify-restore",
)
OPERATOR_MARKERS = (
    "backup_cidr",
    "mempalace_image",
    "mempalace_storage",
    "private_collection",
    "qdrant_storage",
    "uploader_image",
)
OPERATOR_TARGETS = (
    "k8s/memory/10-qdrant.yaml",
    "k8s/memory/20-mempalace.yaml",
    "k8s/memory/30-network-policy.yaml",
    "k8s/memory/40-backup.yaml",
)
AGGREGATE_EVIDENCE_NAME = "21-BACKUP-RESTORE-EVIDENCE.json"
AGGREGATE_EVIDENCE_SCHEMA = "solidstats-memory-backup-restore-evidence/v1"


class RestoreControlError(ValueError):
    """A fail-closed restore-control contract failure."""


class QdrantNotFound(RestoreControlError):
    """A target-specific Qdrant lookup returned HTTP 404."""


class StageInputs:
    """Exact public and private bindings for one restartable operator run."""

    def __init__(
        self,
        *,
        run_id: str,
        handoff_path: Path,
        parity_path: Path,
        source_inventory_path: Path,
        mapping_contract_path: Path,
        transform_manifest_path: Path,
        bundle_dir: Path,
        private_run_root: Path,
        evidence_dir: Path,
        target_collection: str,
        protected_collection: str,
        probe_alias: str,
        expected_vector_config: Mapping[str, object],
        expected_count: int,
    ) -> None:
        self.run_id = run_id
        self.handoff_path = Path(handoff_path)
        self.parity_path = Path(parity_path)
        self.source_inventory_path = Path(source_inventory_path)
        self.mapping_contract_path = Path(mapping_contract_path)
        self.transform_manifest_path = Path(transform_manifest_path)
        self.bundle_dir = Path(bundle_dir)
        self.private_run_root = Path(private_run_root)
        self.evidence_dir = Path(evidence_dir)
        self.target_collection = target_collection
        self.protected_collection = protected_collection
        self.probe_alias = probe_alias
        self.expected_vector_config = dict(expected_vector_config)
        self.expected_count = expected_count


class StageAdapter(Protocol):
    """Bounded live operations injected into the fail-closed stage machine."""

    def inspect_preflight(
        self, *, bindings: dict[str, str], expected_count: int
    ) -> Mapping[str, object]: ...

    def render_manifests(
        self,
        *,
        operator_markers: dict[str, str],
        target_set: tuple[str, ...],
    ) -> object: ...

    def validate_manifests(
        self, rendered: object, *, mode: str
    ) -> Mapping[str, object]: ...

    def apply_manifests(self, rendered: object) -> Mapping[str, object]: ...

    def inspect_runtime(self) -> Mapping[str, object]: ...

    def load_backup_inputs(
        self,
    ) -> tuple[dict[str, object], dict[str, str]]: ...

    def run_command(
        self, command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]: ...

    def apply_backup_job(self, job_path: Path) -> Mapping[str, object]: ...

    def wait_backup_job(self) -> Mapping[str, object]: ...

    def remote_package_inventory(self) -> list[str]: ...

    def download_backup_package(self, package_dir: Path) -> None: ...

    def qdrant_request(
        self, method: str, path: str, body: object = None, **kwargs: object
    ) -> object: ...

    def run_phase20_parity(self) -> Mapping[str, object]: ...

    def run_exact_image_probe(self) -> object: ...

    def verify_prestate(
        self, prestate: dict[str, str]
    ) -> Mapping[str, object]: ...


def canonical_json_bytes(value: object) -> bytes:
    """Return stable JSON bytes for public digests and private control state."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RestoreControlError("control data is not canonical JSON") from error


def _regular_file(path: Path, *, nonempty: bool = True) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError as error:
        raise RestoreControlError("required file is missing or unsafe") from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise RestoreControlError("required file is missing or unsafe")
    if nonempty and details.st_size <= 0:
        raise RestoreControlError("required file is empty")
    return details


def sha256_file(path: Path) -> str:
    """Hash one regular, non-symlink file without exposing its contents."""
    _regular_file(path)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RestoreControlError("required file could not be read") from error
    return digest.hexdigest()


def _load_json(path: Path, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, object]:
    details = _regular_file(path)
    if details.st_size > max_bytes:
        raise RestoreControlError("JSON control file exceeds its size bound")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreControlError("JSON control file is invalid") from error
    if not isinstance(value, dict):
        raise RestoreControlError("JSON control root is invalid")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_digest(value: object, message: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RestoreControlError(message)
    return value


def _require_positive_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RestoreControlError(message)
    return value


def _require_name(value: object, message: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise RestoreControlError(message)
    return value


def _require_run_id(value: object) -> str:
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise RestoreControlError("run identity is invalid")
    return value


def load_phase20_handoff(path: Path = DEFAULT_HANDOFF) -> dict[str, object]:
    """Load and validate the public Phase 20 handoff before private access."""
    handoff = _load_json(Path(path))
    if handoff.get("handoff_schema") != "solidstats-memory-phase21-handoff/v1":
        raise RestoreControlError("Phase 20 handoff schema is invalid")
    _require_positive_int(
        handoff.get("record_count"), "Phase 20 handoff count is invalid"
    )
    for key in (
        "source_inventory_sha256",
        "mapping_contract_sha256",
        "parity_report_sha256",
    ):
        _require_digest(handoff.get(key), "Phase 20 handoff digest is invalid")
    bundle = handoff.get("bundle_file_digests", handoff.get("bundle_file_sha256"))
    if not isinstance(bundle, Mapping) or not bundle:
        raise RestoreControlError("Phase 20 bundle binding is invalid")
    for name, digest in bundle.items():
        _require_name(name, "Phase 20 bundle binding is invalid")
        _require_digest(digest, "Phase 20 bundle binding is invalid")
    return handoff


def recompute_phase20_public_bindings(
    *,
    handoff_path: Path = DEFAULT_HANDOFF,
    parity_path: Path | None = None,
    source_inventory_path: Path | None = None,
    mapping_contract_path: Path | None = None,
    transform_manifest_path: Path | None = None,
    digest_file: Callable[[Path], str] = sha256_file,
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    """Recompute all public bindings without opening retained private files."""
    handoff_path = Path(handoff_path)
    phase20_dir = handoff_path.parent
    parity_path = Path(parity_path or phase20_dir / "20-PARITY-REPORT.json")
    source_inventory_path = Path(
        source_inventory_path or phase20_dir / "20-SOURCE-INVENTORY.json"
    )
    mapping_contract_path = Path(
        mapping_contract_path or phase20_dir / "20-MAPPING-CONTRACT.json"
    )
    transform_manifest_path = Path(
        transform_manifest_path or phase20_dir / "20-TRANSFORM-MANIFEST.json"
    )
    handoff = load_phase20_handoff(handoff_path)

    public_paths = {
        "source_inventory_sha256": source_inventory_path,
        "mapping_contract_sha256": mapping_contract_path,
        "parity_report_sha256": parity_path,
    }
    public_digests: dict[str, str] = {}
    for key, path in public_paths.items():
        actual = digest_file(path)
        if handoff.get(key) != actual:
            raise RestoreControlError("Phase 20 public binding drift detected")
        public_digests[key] = actual

    parity = _load_json(parity_path)
    if parity.get("parity_schema") != "solidstats-memory-parity/v1":
        raise RestoreControlError("Phase 20 public binding schema is invalid")
    if parity.get("verdict") != "pass":
        raise RestoreControlError("Phase 20 public parity is not passing")
    if parity.get("record_count", parity.get("field_parity", {}).get("compared")) != handoff.get(
        "record_count"
    ):
        raise RestoreControlError("Phase 20 public binding count drift detected")
    for key in ("source_inventory_sha256", "mapping_contract_sha256"):
        if key in parity and parity.get(key) != handoff.get(key):
            raise RestoreControlError("Phase 20 public binding drift detected")

    transform_digest = digest_file(transform_manifest_path)
    expected_transform = parity.get(
        "transform_manifest_sha256", handoff.get("transform_manifest_sha256")
    )
    if expected_transform != transform_digest:
        raise RestoreControlError("Phase 20 public binding drift detected")
    public_digests["transform_manifest_sha256"] = transform_digest
    transform = _load_json(transform_manifest_path)
    transform_schema = transform.get("transform_schema", transform.get("schema"))
    if transform_schema not in {
        "solidstats-memory-transform/v1",
        "solidstats-memory-transform-manifest/v1",
    }:
        raise RestoreControlError("Phase 20 public binding schema is invalid")
    if transform.get("record_count", transform.get("point_count")) != handoff.get(
        "record_count"
    ):
        raise RestoreControlError("Phase 20 public binding count drift detected")
    for key in ("source_inventory_sha256", "mapping_contract_sha256"):
        if transform.get(key) != handoff.get(key):
            raise RestoreControlError("Phase 20 public binding drift detected")

    expected_bundle = handoff.get(
        "bundle_file_digests", handoff.get("bundle_file_sha256")
    )
    assert isinstance(expected_bundle, Mapping)
    transform_bundle_digest = transform.get("bundle_sha256")
    if transform_bundle_digest is not None:
        manifest_digest = expected_bundle.get("bundle-manifest.json")
        if transform_bundle_digest != manifest_digest:
            raise RestoreControlError("Phase 20 public bundle binding drift detected")
    transform_bundle_files = transform.get("bundle_file_sha256")
    if transform_bundle_files is not None and transform_bundle_files != expected_bundle:
        raise RestoreControlError("Phase 20 public bundle binding drift detected")

    normalized_bundle = {
        str(name): str(digest) for name, digest in expected_bundle.items()
    }
    public_digests["handoff_sha256"] = digest_file(handoff_path)
    return handoff, public_digests, normalized_bundle


def recompute_phase20_bindings(
    *,
    handoff_path: Path = DEFAULT_HANDOFF,
    parity_path: Path | None = None,
    source_inventory_path: Path | None = None,
    mapping_contract_path: Path | None = None,
    transform_manifest_path: Path | None = None,
    bundle_dir: Path,
    digest_file: Callable[[Path], str] = sha256_file,
) -> dict[str, str]:
    """Recompute public bindings first, then retained private bundle files."""
    _handoff, public_digests, expected_bundle = recompute_phase20_public_bindings(
        handoff_path=handoff_path,
        parity_path=parity_path,
        source_inventory_path=source_inventory_path,
        mapping_contract_path=mapping_contract_path,
        transform_manifest_path=transform_manifest_path,
        digest_file=digest_file,
    )

    bundle_dir = Path(bundle_dir)
    try:
        bundle_details = bundle_dir.lstat()
        actual_names = {
            entry.name
            for entry in bundle_dir.iterdir()
            if entry.name not in {".", ".."}
        }
    except OSError as error:
        raise RestoreControlError("retained bundle is missing or unsafe") from error
    if stat.S_ISLNK(bundle_details.st_mode) or not stat.S_ISDIR(bundle_details.st_mode):
        raise RestoreControlError("retained bundle is missing or unsafe")
    if actual_names != set(expected_bundle):
        raise RestoreControlError("retained bundle membership drift detected")
    bundle_digests: dict[str, str] = {}
    for name in sorted(expected_bundle):
        path = bundle_dir / name
        actual = digest_file(path)
        if actual != expected_bundle[name]:
            raise RestoreControlError("retained bundle digest drift detected")
        bundle_digests[name] = actual

    bindings = {
        **public_digests,
        "retained_bundle_sha256": _digest(bundle_digests),
    }
    bindings["binding_sha256"] = _digest(bindings)
    return bindings


def qdrant_request(
    base_url: str,
    method: str,
    path: str,
    *,
    api_key: str | None = None,
    body: object = None,
    timeout: float = 15.0,
    opener: Callable[..., object] = urllib_request.urlopen,
    binary: bool = False,
    max_response_bytes: int = 64 * 1024 * 1024,
) -> object:
    """Call a bounded Qdrant API without surfacing private response data."""
    parsed = urllib_parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise RestoreControlError("Qdrant endpoint is invalid")
    if not path.startswith("/") or "://" in path:
        raise RestoreControlError("Qdrant request path is invalid")
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        raise RestoreControlError("Qdrant request method is invalid")
    if not isinstance(timeout, (int, float)) or timeout <= 0 or not math.isfinite(timeout):
        raise RestoreControlError("Qdrant timeout is invalid")
    headers = {"Accept": "application/octet-stream" if binary else "application/json"}
    data = None
    if body is not None:
        data = canonical_json_bytes(body)
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["api-key"] = api_key
    request = urllib_request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read(max_response_bytes + 1)
    except urllib_error.HTTPError as error:
        if error.code == 404:
            raise QdrantNotFound("Qdrant target is absent") from error
        raise RestoreControlError("Qdrant request failed") from error
    except (OSError, TimeoutError, socket.timeout, urllib_error.URLError) as error:
        raise RestoreControlError("Qdrant request failed") from error
    if not isinstance(payload, bytes) or not payload or len(payload) > max_response_bytes:
        raise RestoreControlError("Qdrant response is empty or exceeds its bound")
    if binary:
        return payload
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreControlError("Qdrant response is malformed") from error
    if not isinstance(value, dict):
        raise RestoreControlError("Qdrant response is malformed")
    return value


def _request(
    request: Callable[..., object],
    method: str,
    path: str,
    body: object = None,
    *,
    binary: bool = False,
) -> object:
    if binary:
        return request(method, path, body=body, binary=True)
    return request(method, path, body=body)


def _result_mapping(value: object) -> Mapping[str, object]:
    if (
        not isinstance(value, Mapping)
        or value.get("status") not in ("ok", None)
        or not isinstance(value.get("result"), Mapping)
    ):
        raise RestoreControlError("Qdrant response contract is invalid")
    return value["result"]


def _collection_names(value: object) -> set[str]:
    result = _result_mapping(value)
    collections = result.get("collections")
    if not isinstance(collections, list):
        raise RestoreControlError("Qdrant collection inventory is invalid")
    names: set[str] = set()
    for item in collections:
        if not isinstance(item, Mapping):
            raise RestoreControlError("Qdrant collection inventory is invalid")
        names.add(_require_name(item.get("name"), "Qdrant collection inventory is invalid"))
    return names


def _alias_map(value: object) -> dict[str, str]:
    result = _result_mapping(value)
    aliases = result.get("aliases")
    if not isinstance(aliases, list):
        raise RestoreControlError("Qdrant alias inventory is invalid")
    mapped: dict[str, str] = {}
    for item in aliases:
        if not isinstance(item, Mapping):
            raise RestoreControlError("Qdrant alias inventory is invalid")
        alias = _require_name(item.get("alias_name"), "Qdrant alias inventory is invalid")
        collection = _require_name(
            item.get("collection_name"), "Qdrant alias inventory is invalid"
        )
        if alias in mapped:
            raise RestoreControlError("Qdrant alias inventory is invalid")
        mapped[alias] = collection
    return mapped


def require_absent_target(
    request: Callable[..., object],
    *,
    target_collection: str,
    protected_collection: str,
) -> dict[str, object]:
    """Prove target absence through inventory, aliases, and direct lookup."""
    target = _require_name(target_collection, "restore target is invalid")
    protected = _require_name(protected_collection, "protected target is invalid")
    if target == protected:
        raise RestoreControlError("restore target equals the protected collection")

    collections_response: object | None = None
    aliases_response: object | None = None
    target_present = False
    failures: list[RestoreControlError] = []
    try:
        collections_response = _request(request, "GET", "/collections")
    except RestoreControlError as error:
        failures.append(error)
    try:
        aliases_response = _request(request, "GET", "/aliases")
    except RestoreControlError as error:
        failures.append(error)
    try:
        _request(request, "GET", f"/collections/{urllib_parse.quote(target, safe='')}")
        target_present = True
    except QdrantNotFound:
        target_present = False
    except RestoreControlError as error:
        failures.append(error)
    if failures:
        raise RestoreControlError("target absence proof is incomplete")
    collections = _collection_names(collections_response)
    aliases = _alias_map(aliases_response)
    collision = (
        target_present
        or target in collections
        or target in aliases
        or target in aliases.values()
    )
    if collision:
        raise RestoreControlError("restore target or alias collision detected")
    return {
        "confirmed": True,
        "collection_inventory_checked": True,
        "alias_inventory_checked": True,
        "target_lookup_checked": True,
    }


def require_restore_capacity(
    *,
    snapshot_bytes: int,
    pvc_free_bytes: int,
    node_free_bytes: int,
    reserve_bytes: int,
) -> dict[str, object]:
    """Require two snapshot sizes plus a fixed reserve on PVC and node."""
    snapshot = _require_positive_int(snapshot_bytes, "snapshot size is invalid")
    reserve = _require_positive_int(reserve_bytes, "restore reserve is invalid")
    pvc = _require_positive_int(pvc_free_bytes, "PVC free space is invalid")
    node = _require_positive_int(node_free_bytes, "node free space is invalid")
    required = snapshot * 2 + reserve
    if pvc < required or node < required:
        raise RestoreControlError("restore capacity is insufficient")
    return {
        "sufficient": True,
        "snapshot_bytes": snapshot,
        "reserve_bytes": reserve,
        "required_bytes": required,
        "pvc_free_bytes": pvc,
        "node_free_bytes": node,
    }


def create_snapshot(request: Callable[..., object], source_collection: str) -> str:
    """Create a collection snapshot and return its validated opaque name."""
    source = _require_name(source_collection, "snapshot source is invalid")
    response = _request(
        request,
        "POST",
        f"/collections/{urllib_parse.quote(source, safe='')}/snapshots?wait=true",
    )
    result = _result_mapping(response)
    return _require_name(result.get("name"), "snapshot response is invalid")


def download_snapshot(
    request: Callable[..., object],
    source_collection: str,
    snapshot_name: str,
    destination: Path,
) -> dict[str, object]:
    """Download one non-empty snapshot to an exclusive restrictive file."""
    source = _require_name(source_collection, "snapshot source is invalid")
    snapshot = _require_name(snapshot_name, "snapshot name is invalid")
    payload = _request(
        request,
        "GET",
        f"/collections/{urllib_parse.quote(source, safe='')}/snapshots/"
        f"{urllib_parse.quote(snapshot, safe='')}",
        binary=True,
    )
    if not isinstance(payload, bytes) or not payload:
        raise RestoreControlError("snapshot download is empty")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
    except OSError as error:
        raise RestoreControlError("snapshot destination is unavailable") from error
    return {
        "downloaded": True,
        "snapshot_bytes": len(payload),
        "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _metadata_entries(root: Path) -> list[tuple[Path, str, os.stat_result]]:
    try:
        root_details = root.lstat()
    except OSError as error:
        raise RestoreControlError("metadata source is missing or unsafe") from error
    if stat.S_ISLNK(root_details.st_mode) or not stat.S_ISDIR(root_details.st_mode):
        raise RestoreControlError("metadata source is missing or unsafe")
    entries: list[tuple[Path, str, os.stat_result]] = []
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
        for path in paths:
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode) or not (
                stat.S_ISDIR(details.st_mode) or stat.S_ISREG(details.st_mode)
            ):
                raise RestoreControlError("metadata source contains an unsafe entry")
            entries.append((path, path.relative_to(root).as_posix(), details))
    except OSError as error:
        raise RestoreControlError("metadata source contains an unsafe entry") from error
    if not any(stat.S_ISREG(details.st_mode) for _path, _name, details in entries):
        raise RestoreControlError("metadata source is empty")
    return entries


def _metadata_tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_count = 0
    for path, relative, details in _metadata_entries(root):
        kind = b"d" if stat.S_ISDIR(details.st_mode) else b"f"
        digest.update(kind + b"\0" + relative.encode("utf-8") + b"\0")
        if kind == b"f":
            file_count += 1
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest(), file_count


def _extract_safe_tar(archive_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:") as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if (
                    relative.is_absolute()
                    or not relative.parts
                    or ".." in relative.parts
                    or not (member.isdir() or member.isreg())
                ):
                    raise RestoreControlError("metadata archive contains an unsafe entry")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = archive.extractfile(member)
                if source is None:
                    raise RestoreControlError("metadata archive is incomplete")
                descriptor = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                with source, os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(source, output)
    except (OSError, tarfile.TarError) as error:
        raise RestoreControlError("metadata archive is invalid") from error


def archive_quiescent_metadata(source_dir: Path, archive_path: Path) -> dict[str, object]:
    """Archive stable metadata deterministically and verify an isolated extract."""
    source_dir = Path(source_dir)
    archive_path = Path(archive_path)
    try:
        archive_path.resolve(strict=False).relative_to(source_dir.resolve(strict=True))
    except ValueError:
        pass
    except OSError as error:
        raise RestoreControlError("metadata source is missing or unsafe") from error
    else:
        raise RestoreControlError("metadata archive must be outside its source")
    before, file_count = _metadata_tree_digest(source_dir)
    archive_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".metadata-", suffix=".tar", dir=archive_path.parent
        )
        os.close(descriptor)
        os.chmod(temporary_name, 0o600)
        with tarfile.open(temporary_name, "w", format=tarfile.GNU_FORMAT) as archive:
            for path, relative, details in _metadata_entries(source_dir):
                info = tarfile.TarInfo(relative)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                info.mode = 0o700 if stat.S_ISDIR(details.st_mode) else 0o600
                if stat.S_ISDIR(details.st_mode):
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.size = details.st_size
                    with path.open("rb") as source:
                        archive.addfile(info, source)
        after, _after_count = _metadata_tree_digest(source_dir)
        if before != after:
            raise RestoreControlError("metadata changed during archive creation")
        if archive_path.exists() or archive_path.is_symlink():
            raise RestoreControlError("metadata archive destination already exists")
        os.replace(temporary_name, archive_path)
        temporary_name = ""
    except (OSError, tarfile.TarError) as error:
        raise RestoreControlError("metadata archive could not be created") from error
    finally:
        if "temporary_name" in locals() and temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
    with tempfile.TemporaryDirectory(prefix="metadata-verify-", dir=archive_path.parent) as temporary:
        extracted = Path(temporary)
        _extract_safe_tar(archive_path, extracted)
        extracted_digest, extracted_count = _metadata_tree_digest(extracted)
    if extracted_digest != before or extracted_count != file_count:
        raise RestoreControlError("metadata archive verification failed")
    return {
        "stable": True,
        "file_count": file_count,
        "tree_sha256": before,
        "archive_sha256": sha256_file(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "extracted_match": True,
    }


def _validate_bindings(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise RestoreControlError("Phase 20 package bindings are invalid")
    bindings: dict[str, str] = {}
    for key, digest in value.items():
        if (
            not isinstance(key, str)
            or not key.endswith("sha256")
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
        ):
            raise RestoreControlError("Phase 20 package bindings are invalid")
        bindings[key] = digest
    return bindings


def verify_backup_package(
    package_dir: Path,
    *,
    expected_run_id: str,
    expected_phase20_bindings: Mapping[str, str],
) -> dict[str, object]:
    """Verify one exact, complete, non-empty backup package."""
    package_dir = Path(package_dir)
    _require_run_id(expected_run_id)
    expected_bindings = _validate_bindings(expected_phase20_bindings)
    try:
        details = package_dir.lstat()
        names = {entry.name for entry in package_dir.iterdir()}
    except OSError as error:
        raise RestoreControlError("backup package is missing or unsafe") from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise RestoreControlError("backup package is missing or unsafe")
    if names != PACKAGE_MEMBERS:
        raise RestoreControlError("backup package membership is incomplete")
    sizes = {name: _regular_file(package_dir / name).st_size for name in names}

    try:
        checksum_text = (package_dir / "SHA256SUMS").read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise RestoreControlError("backup checksums are invalid") from error
    lines = checksum_text.splitlines()
    if len(lines) != len(CHECKSUM_MEMBERS):
        raise RestoreControlError("backup checksums are incomplete")
    parsed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None or match.group(2) in parsed:
            raise RestoreControlError("backup checksums are invalid")
        parsed[match.group(2)] = match.group(1)
    if tuple(parsed) != CHECKSUM_MEMBERS:
        raise RestoreControlError("backup checksums are not deterministic")
    for name in CHECKSUM_MEMBERS:
        if sha256_file(package_dir / name) != parsed[name]:
            raise RestoreControlError("backup checksum mismatch detected")

    manifest = _load_json(package_dir / "manifest.json")
    if set(manifest) != {"schema", "run_id", "phase20_bindings", "members"}:
        raise RestoreControlError("backup manifest fields are invalid")
    if manifest.get("schema") != BACKUP_PACKAGE_SCHEMA:
        raise RestoreControlError("backup manifest schema is invalid")
    if manifest.get("run_id") != expected_run_id:
        raise RestoreControlError("backup run binding mismatch detected")
    manifest_bindings = _validate_bindings(manifest.get("phase20_bindings"))
    if manifest_bindings != expected_bindings:
        raise RestoreControlError("backup provenance binding mismatch detected")
    members = manifest.get("members")
    expected_members = {
        "mempalace_metadata_tar_sha256": parsed["mempalace-metadata.tar"],
        "qdrant_snapshot_sha256": parsed["qdrant.snapshot"],
    }
    if members != expected_members:
        raise RestoreControlError("backup manifest member mismatch detected")
    file_digests = {name: sha256_file(package_dir / name) for name in sorted(names)}
    return {
        "complete": True,
        "member_count": len(PACKAGE_MEMBERS),
        "package_sha256": _digest(file_digests),
        "snapshot_bytes": sizes["qdrant.snapshot"],
        "metadata_archive_bytes": sizes["mempalace-metadata.tar"],
    }


def create_backup_package(
    package_dir: Path,
    *,
    run_id: str,
    phase20_bindings: Mapping[str, str],
) -> dict[str, object]:
    """Create deterministic manifest/checksums around snapshot and metadata."""
    package_dir = Path(package_dir)
    run_id = _require_run_id(run_id)
    bindings = _validate_bindings(phase20_bindings)
    try:
        details = package_dir.lstat()
        existing = {entry.name for entry in package_dir.iterdir()}
    except OSError as error:
        raise RestoreControlError("backup package directory is invalid") from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise RestoreControlError("backup package directory is invalid")
    if existing != {"mempalace-metadata.tar", "qdrant.snapshot"}:
        raise RestoreControlError("backup package inputs are incomplete")
    snapshot_sha256 = sha256_file(package_dir / "qdrant.snapshot")
    metadata_sha256 = sha256_file(package_dir / "mempalace-metadata.tar")
    manifest = {
        "schema": BACKUP_PACKAGE_SCHEMA,
        "run_id": run_id,
        "phase20_bindings": bindings,
        "members": {
            "mempalace_metadata_tar_sha256": metadata_sha256,
            "qdrant_snapshot_sha256": snapshot_sha256,
        },
    }
    write_private_json(package_dir / "manifest.json", manifest)
    lines = [
        f"{sha256_file(package_dir / name)}  {name}"
        for name in CHECKSUM_MEMBERS
    ]
    checksum_path = package_dir / "SHA256SUMS"
    try:
        descriptor = os.open(
            checksum_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as output:
            output.write("\n".join(lines) + "\n")
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise RestoreControlError("backup checksums could not be written") from error
    return verify_backup_package(
        package_dir,
        expected_run_id=run_id,
        expected_phase20_bindings=bindings,
    )


def _package_digests(package_dir: Path) -> dict[str, str]:
    try:
        names = {entry.name for entry in package_dir.iterdir()}
    except OSError as error:
        raise RestoreControlError("backup package is missing or unsafe") from error
    if names != PACKAGE_MEMBERS:
        raise RestoreControlError("backup package membership is incomplete")
    return {name: sha256_file(package_dir / name) for name in sorted(names)}


def store_backup_package(
    package_dir: Path,
    object_root: Path,
    *,
    prefix: str,
    binding_sha256: str,
) -> dict[str, object]:
    """Store a local synthetic object replica without overwrite semantics."""
    _require_digest(binding_sha256, "backup object binding is invalid")
    relative = PurePosixPath(prefix)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RestoreControlError("backup object prefix is invalid")
    for part in relative.parts:
        _require_name(part, "backup object prefix is invalid")
    source = Path(package_dir)
    source_digests = _package_digests(source)
    destination = Path(object_root).joinpath(*relative.parts)
    if destination.exists() or destination.is_symlink():
        if not destination.is_dir() or _package_digests(destination) != source_digests:
            raise RestoreControlError("backup object prefix collision detected")
        return {
            "status": "reused",
            "verified": True,
            "object_count": len(PACKAGE_MEMBERS),
            "package_sha256": _digest(source_digests),
        }
    try:
        destination.mkdir(parents=True, mode=0o700)
        for name in sorted(PACKAGE_MEMBERS):
            source_path = source / name
            target_path = destination / name
            descriptor = os.open(
                target_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with source_path.open("rb") as input_file, os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
    except OSError as error:
        raise RestoreControlError("backup object write failed without overwrite") from error
    if _package_digests(destination) != source_digests:
        raise RestoreControlError("backup object read-after-write verification failed")
    return {
        "status": "uploaded",
        "verified": True,
        "object_count": len(PACKAGE_MEMBERS),
        "package_sha256": _digest(source_digests),
    }


class RunLock:
    """An acquired OS lock plus its durable exact-run checkpoint state."""

    def __init__(self, path: Path, descriptor: int, state: dict[str, object]) -> None:
        self.path = path
        self.descriptor = descriptor
        self.state = state

    def release(self) -> None:
        if self.descriptor < 0:
            return
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = -1

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _read_descriptor_json(descriptor: int) -> dict[str, object] | None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, 64 * 1024 + 1)
    if not raw:
        return None
    if len(raw) > 64 * 1024:
        raise RestoreControlError("run lock state exceeds its size bound")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RestoreControlError("run lock state is invalid") from error
    if not isinstance(value, dict):
        raise RestoreControlError("run lock state is invalid")
    return value


def _write_descriptor_json(descriptor: int, value: object) -> None:
    raw = canonical_json_bytes(value) + b"\n"
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    os.write(descriptor, raw)
    os.fsync(descriptor)


def _validate_lock_state(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "run_id_sha256",
        "binding_sha256",
        "last_stage",
        "last_evidence_sha256",
    }:
        raise RestoreControlError("run lock state is invalid")
    if value.get("schema") != LOCK_SCHEMA:
        raise RestoreControlError("run lock state is invalid")
    _require_digest(value.get("run_id_sha256"), "run lock state is invalid")
    _require_digest(value.get("binding_sha256"), "run lock state is invalid")
    if value.get("last_stage") not in {"unstarted", *RUN_STAGES}:
        raise RestoreControlError("run lock state is invalid")
    last_evidence = value.get("last_evidence_sha256")
    if last_evidence != "unstarted" and (
        not isinstance(last_evidence, str) or not SHA256.fullmatch(last_evidence)
    ):
        raise RestoreControlError("run lock state is invalid")
    return dict(value)


def acquire_run_lock(
    evidence_dir: Path,
    *,
    run_id: str,
    binding_sha256: str,
    resume_run: bool,
) -> RunLock:
    """Acquire an exclusive lock and allow only an exact explicit resume."""
    run_id = _require_run_id(run_id)
    binding_sha256 = _require_digest(binding_sha256, "run binding is invalid")
    evidence_dir = Path(evidence_dir)
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        details = evidence_dir.lstat()
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise OSError
        path = evidence_dir / ".21-02-restore.lock"
        descriptor = os.open(
            path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.chmod(path, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError) as error:
        if "descriptor" in locals():
            os.close(descriptor)
        raise RestoreControlError("restore run is locked") from error
    try:
        existing = _read_descriptor_json(descriptor)
        run_digest = hashlib.sha256(run_id.encode("ascii")).hexdigest()
        if existing is None:
            state: dict[str, object] = {
                "schema": LOCK_SCHEMA,
                "run_id_sha256": run_digest,
                "binding_sha256": binding_sha256,
                "last_stage": "unstarted",
                "last_evidence_sha256": "unstarted",
            }
            _write_descriptor_json(descriptor, state)
        else:
            state = _validate_lock_state(existing)
            if (
                state["run_id_sha256"] != run_digest
                or state["binding_sha256"] != binding_sha256
            ):
                raise RestoreControlError("restore run is locked by another binding")
            if not resume_run:
                raise RestoreControlError("existing run requires explicit resume")
        return RunLock(path, descriptor, state)
    except Exception:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        raise


def checkpoint_run(lock: RunLock, stage: str, evidence_sha256: str) -> None:
    """Persist only a forward, digest-chained stage for exact resume."""
    if lock.descriptor < 0:
        raise RestoreControlError("run lock is not acquired")
    if stage not in RUN_STAGES:
        raise RestoreControlError("run checkpoint stage is invalid")
    evidence_sha256 = _require_digest(
        evidence_sha256, "run checkpoint digest is invalid"
    )
    prior = str(lock.state["last_stage"])
    prior_index = -1 if prior == "unstarted" else RUN_STAGES.index(prior)
    next_index = RUN_STAGES.index(stage)
    if next_index < prior_index or next_index > prior_index + 1:
        raise RestoreControlError("run checkpoint transition is invalid")
    if next_index == prior_index:
        if lock.state["last_evidence_sha256"] != evidence_sha256:
            raise RestoreControlError("run checkpoint replay collision detected")
        return
    lock.state["last_stage"] = stage
    lock.state["last_evidence_sha256"] = evidence_sha256
    _write_descriptor_json(lock.descriptor, lock.state)


def recover_snapshot(
    request: Callable[..., object],
    *,
    target_collection: str,
    snapshot_location: str,
    priority: str,
) -> dict[str, object]:
    """Recover only with Qdrant's snapshot-priority conflict policy."""
    if priority != "snapshot":
        raise RestoreControlError("recovery priority must be snapshot")
    target = _require_name(target_collection, "restore target is invalid")
    if not isinstance(snapshot_location, str) or not snapshot_location:
        raise RestoreControlError("snapshot location is invalid")
    response = _request(
        request,
        "POST",
        f"/collections/{urllib_parse.quote(target, safe='')}/snapshots/recover?wait=true",
        {"location": snapshot_location, "priority": "snapshot"},
    )
    if not isinstance(response, Mapping) or response.get("status") not in ("ok", None):
        raise RestoreControlError("snapshot recovery was not accepted")
    if response.get("result") is not True and response.get("result") is not None:
        raise RestoreControlError("snapshot recovery was not accepted")
    return {"accepted": True, "snapshot_priority": True}


def verify_restored_collection(
    request: Callable[..., object],
    *,
    target_collection: str,
    expected_vector_config: Mapping[str, object],
    expected_count: int,
    parity_check: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    """Require green state, exact vector config/count, and exact parity."""
    target = _require_name(target_collection, "restore target is invalid")
    expected_count = _require_positive_int(expected_count, "expected count is invalid")
    if not isinstance(expected_vector_config, Mapping) or not expected_vector_config:
        raise RestoreControlError("expected vector configuration is invalid")
    result = _result_mapping(
        _request(request, "GET", f"/collections/{urllib_parse.quote(target, safe='')}")
    )
    if result.get("status") != "green" or result.get("optimizer_status") not in (
        "ok",
        "green",
    ):
        raise RestoreControlError("restored collection is not green")
    config = result.get("config")
    if not isinstance(config, Mapping):
        raise RestoreControlError("restored collection configuration is invalid")
    params = config.get("params")
    vectors = params.get("vectors") if isinstance(params, Mapping) else None
    if vectors != expected_vector_config:
        raise RestoreControlError("restored vector configuration does not match")
    if result.get("points_count") != expected_count:
        raise RestoreControlError("restored aggregate count does not match")
    try:
        parity = parity_check()
    except Exception as error:
        raise RestoreControlError("restored exact parity failed") from error
    if (
        not isinstance(parity, Mapping)
        or parity.get("verdict") != "pass"
        or parity.get("record_count", expected_count) != expected_count
    ):
        raise RestoreControlError("restored exact parity failed")
    return {
        "green": True,
        "configuration_match": True,
        "count_match": True,
        "parity_exact": True,
        "record_count": expected_count,
    }


def _alias_action(request: Callable[..., object], action: Mapping[str, object]) -> None:
    response = _request(
        request,
        "POST",
        "/collections/aliases",
        {"actions": [dict(action)]},
    )
    if not isinstance(response, Mapping) or response.get("status") not in ("ok", None):
        raise RestoreControlError("alias action failed")


def restore_alias_prestate(
    request: Callable[..., object],
    *,
    alias_name: str,
    prestate: Mapping[str, str],
) -> dict[str, object]:
    """Restore exactly the recorded alias map and verify no mutation remains."""
    alias_name = _require_name(alias_name, "probe alias is invalid")
    expected = dict(prestate)
    current = _alias_map(_request(request, "GET", "/aliases"))
    if alias_name in current and current.get(alias_name) != expected.get(alias_name):
        _alias_action(request, {"delete_alias": {"alias_name": alias_name}})
        current.pop(alias_name, None)
    if alias_name in expected and current.get(alias_name) != expected[alias_name]:
        _alias_action(
            request,
            {
                "create_alias": {
                    "alias_name": alias_name,
                    "collection_name": expected[alias_name],
                }
            },
        )
    final = _alias_map(_request(request, "GET", "/aliases"))
    if final != expected:
        raise RestoreControlError("alias prestate restoration failed")
    return {"restored": True, "poststate_sha256": _digest(final)}


def probe_alias_compatibility(
    request: Callable[..., object],
    *,
    restored_collection: str,
    probe_alias: str,
    exact_image_probe: Callable[[], object],
) -> dict[str, object]:
    """Create one temporary alias, probe it, and always restore exact absence."""
    restored = _require_name(restored_collection, "restored collection is invalid")
    alias = _require_name(probe_alias, "probe alias is invalid")
    prestate = _alias_map(_request(request, "GET", "/aliases"))
    if alias in prestate:
        raise RestoreControlError("probe alias collision detected")
    pre_digest = _digest(prestate)
    created = False
    probe_passed = False
    probe_error: Exception | None = None
    cleanup_error: Exception | None = None
    try:
        _alias_action(
            request,
            {
                "create_alias": {
                    "alias_name": alias,
                    "collection_name": restored,
                }
            },
        )
        created = True
        outcome = exact_image_probe()
        probe_passed = outcome is True or (
            isinstance(outcome, Mapping) and outcome.get("verdict") == "pass"
        )
    except Exception as error:
        probe_error = error
    finally:
        if created:
            try:
                restored_result = restore_alias_prestate(
                    request, alias_name=alias, prestate=prestate
                )
            except Exception as error:
                cleanup_error = error
                restored_result = {"restored": False, "poststate_sha256": "0" * 64}
        else:
            final = _alias_map(_request(request, "GET", "/aliases"))
            restored_result = {
                "restored": final == prestate,
                "poststate_sha256": _digest(final),
            }
    if cleanup_error is not None or not restored_result["restored"]:
        raise RestoreControlError("alias prestate restoration failed") from cleanup_error
    if probe_error is not None or not probe_passed:
        raise RestoreControlError("alias compatibility probe failed") from probe_error
    return {
        "probe_passed": True,
        "prestate_sha256": pre_digest,
        "poststate_sha256": restored_result["poststate_sha256"],
        "restored": True,
    }


def generate_backup_job(
    cronjob: Mapping[str, object],
    *,
    run_id: str,
    private_environment: Mapping[str, str],
) -> dict[str, object]:
    """Derive a one-shot Job from an explicitly suspended CronJob contract."""
    run_id = _require_run_id(run_id)
    if not isinstance(cronjob, Mapping) or cronjob.get("kind") != "CronJob":
        raise RestoreControlError("backup CronJob contract is invalid")
    spec = cronjob.get("spec")
    metadata = cronjob.get("metadata")
    if (
        not isinstance(spec, Mapping)
        or spec.get("suspend") is not True
        or not isinstance(metadata, Mapping)
    ):
        raise RestoreControlError("backup CronJob must be suspended")
    job_template = spec.get("jobTemplate")
    if not isinstance(job_template, Mapping) or not isinstance(job_template.get("spec"), Mapping):
        raise RestoreControlError("backup CronJob job template is invalid")
    job_spec = deepcopy(job_template["spec"])
    template = job_spec.get("template")
    pod_spec = template.get("spec") if isinstance(template, Mapping) else None
    containers = pod_spec.get("containers") if isinstance(pod_spec, Mapping) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise RestoreControlError("backup Job container contract is invalid")
    container = containers[0]
    if not isinstance(container, dict):
        raise RestoreControlError("backup Job container contract is invalid")
    existing_env = container.get("env", [])
    if not isinstance(existing_env, list):
        raise RestoreControlError("backup Job environment contract is invalid")
    existing_names = {
        item.get("name") for item in existing_env if isinstance(item, Mapping)
    }
    injected: list[dict[str, str]] = []
    for name, value in sorted(private_environment.items()):
        if (
            not isinstance(name, str)
            or not ENV_NAME.fullmatch(name)
            or not isinstance(value, str)
            or not value
            or name in existing_names
        ):
            raise RestoreControlError("private Job environment is invalid")
        injected.append({"name": name, "value": value})
    container["env"] = [*existing_env, *injected]
    labels = {}
    template_metadata = template.get("metadata")
    if isinstance(template_metadata, Mapping) and isinstance(
        template_metadata.get("labels"), Mapping
    ):
        labels = dict(template_metadata["labels"])
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"solidstats-memory-backup-{run_id[:16]}",
            "namespace": metadata.get("namespace"),
            "labels": labels,
        },
        "spec": job_spec,
    }


def write_private_json(path: Path, value: object) -> None:
    """Write private control data with directory 0700 and file 0600."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_details = path.parent.lstat()
        if (
            stat.S_ISLNK(parent_details.st_mode)
            or not stat.S_ISDIR(parent_details.st_mode)
            or stat.S_IMODE(parent_details.st_mode) & 0o077
        ):
            raise OSError
        if path.exists() or path.is_symlink():
            raise OSError
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json_bytes(value) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise RestoreControlError("private control file could not be written") from error


def backup_job_evidence(job: Mapping[str, object]) -> dict[str, object]:
    """Reduce a private Job to aggregate, value-free generation evidence."""
    spec = job.get("spec") if isinstance(job, Mapping) else None
    template = spec.get("template") if isinstance(spec, Mapping) else None
    pod_spec = template.get("spec") if isinstance(template, Mapping) else None
    containers = pod_spec.get("containers") if isinstance(pod_spec, Mapping) else None
    if job.get("kind") != "Job" or not isinstance(containers, list) or not containers:
        raise RestoreControlError("generated backup Job is invalid")
    env_count = 0
    for container in containers:
        if not isinstance(container, Mapping) or not isinstance(container.get("env", []), list):
            raise RestoreControlError("generated backup Job is invalid")
        env_count += len(container.get("env", []))
    return {
        "generated": True,
        "job_sha256": _digest(job),
        "container_count": len(containers),
        "environment_binding_count": env_count,
        "recurring_schedule_changed": False,
    }


def validate_backup_job(
    job_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = 30.0,
) -> dict[str, object]:
    """Run client and server dry-runs without retaining command output."""
    _regular_file(Path(job_path))
    if not isinstance(timeout, (int, float)) or timeout <= 0 or not math.isfinite(timeout):
        raise RestoreControlError("backup Job validation timeout is invalid")
    commands = (
        ("kubectl", "apply", "--dry-run=client", "-f", str(job_path)),
        (
            "kubectl",
            "apply",
            "--server-side",
            "--dry-run=server",
            "-f",
            str(job_path),
        ),
    )
    for command in commands:
        try:
            result = runner(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RestoreControlError("backup Job dry-run failed") from error
        if result.returncode != 0:
            raise RestoreControlError("backup Job dry-run failed")
    return {"client_dry_run": True, "server_dry_run": True}


def _stage_bindings(inputs: StageInputs) -> dict[str, str]:
    """Recompute every public binding before opening retained private files."""
    return recompute_phase20_bindings(
        handoff_path=inputs.handoff_path,
        parity_path=inputs.parity_path,
        source_inventory_path=inputs.source_inventory_path,
        mapping_contract_path=inputs.mapping_contract_path,
        transform_manifest_path=inputs.transform_manifest_path,
        bundle_dir=inputs.bundle_dir,
    )


def _validated_stage_inputs(inputs: StageInputs) -> StageInputs:
    _require_run_id(inputs.run_id)
    _require_name(inputs.target_collection, "restore target is invalid")
    _require_name(inputs.protected_collection, "protected target is invalid")
    _require_name(inputs.probe_alias, "probe alias is invalid")
    _require_positive_int(inputs.expected_count, "expected count is invalid")
    if (
        inputs.target_collection == inputs.protected_collection
        or not isinstance(inputs.expected_vector_config, Mapping)
        or not inputs.expected_vector_config
    ):
        raise RestoreControlError("stage inputs are invalid")
    return inputs


def _require_exact_true_map(
    value: object, keys: set[str], message: str
) -> dict[str, bool]:
    if (
        not isinstance(value, Mapping)
        or set(value) != keys
        or any(value.get(key) is not True for key in keys)
    ):
        raise RestoreControlError(message)
    return {key: True for key in sorted(keys)}


def _require_prestate(value: object) -> dict[str, str]:
    keys = {
        "active_alias_sha256",
        "nginx_sha256",
        "mcp_registration_sha256",
        "legacy_runtime_sha256",
        "schedule_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise RestoreControlError("active pre-state proof is incomplete")
    result: dict[str, str] = {}
    for key in sorted(keys):
        result[key] = _require_digest(
            value.get(key), "active pre-state proof is incomplete"
        )
    return result


def _require_quiescence(value: object) -> dict[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"stable", "writer_count"}
        or value.get("stable") is not True
        or value.get("writer_count") != 0
    ):
        raise RestoreControlError("write quiescence is not proven")
    return {"stable": True, "writer_count": 0}


def _require_operator_markers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(OPERATOR_MARKERS):
        raise RestoreControlError("measured operator markers are incomplete")
    markers: dict[str, str] = {}
    for key in OPERATOR_MARKERS:
        marker = value.get(key)
        if not isinstance(marker, str) or not marker or "\n" in marker or "\r" in marker:
            raise RestoreControlError("measured operator markers are incomplete")
        markers[key] = marker
    return markers


def _require_target_set(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) != len(OPERATOR_TARGETS)
        or tuple(value) != OPERATOR_TARGETS
    ):
        raise RestoreControlError("operator manifest target set is invalid")
    return OPERATOR_TARGETS


def _private_stage_dir(inputs: StageInputs) -> Path:
    root = Path(inputs.private_run_root)
    try:
        details = root.lstat()
    except OSError as error:
        raise RestoreControlError("private run root is missing or unsafe") from error
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise RestoreControlError("private run root is missing or unsafe")
    run_dir = root / inputs.run_id
    try:
        run_dir.mkdir(mode=0o700, exist_ok=True)
        run_details = run_dir.lstat()
    except OSError as error:
        raise RestoreControlError("private run directory is unavailable") from error
    if (
        stat.S_ISLNK(run_details.st_mode)
        or not stat.S_ISDIR(run_details.st_mode)
        or stat.S_IMODE(run_details.st_mode) & 0o077
    ):
        raise RestoreControlError("private run directory is unavailable")
    return run_dir


def _write_or_verify_private_json(path: Path, value: object) -> None:
    expected = canonical_json_bytes(value) + b"\n"
    if path.exists() or path.is_symlink():
        _regular_file(path)
        try:
            current = path.read_bytes()
        except OSError as error:
            raise RestoreControlError("private control file could not be read") from error
        if current != expected:
            raise RestoreControlError("private control replay collision detected")
        return
    write_private_json(path, value)


def _write_or_verify_evidence(path: Path, value: Mapping[str, object]) -> str:
    expected = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        _regular_file(path)
        try:
            current = path.read_bytes()
        except OSError as error:
            raise RestoreControlError("aggregate evidence could not be read") from error
        if current != expected:
            raise RestoreControlError("aggregate evidence collision detected")
        return hashlib.sha256(expected).hexdigest()
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(expected)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise RestoreControlError("aggregate evidence could not be written") from error
    return hashlib.sha256(expected).hexdigest()


def _validate_aggregate_evidence(value: Mapping[str, object]) -> None:
    validator_path = ROOT / "scripts" / "validate-phase-21.py"
    specification = importlib.util.spec_from_file_location(
        "solidstats_phase21_validator", validator_path
    )
    if specification is None or specification.loader is None:
        raise RestoreControlError("aggregate evidence validator is unavailable")
    validator = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(validator)
        validator.validate_backup_restore_evidence(value)
    except Exception as error:
        raise RestoreControlError("aggregate evidence validation failed") from error


def _load_stage_state(run_dir: Path, stage: str) -> dict[str, object]:
    return _load_json(run_dir / f"{RUN_STAGES.index(stage):02d}-{stage}.json")


def _save_stage_state(run_dir: Path, stage: str, state: Mapping[str, object]) -> str:
    path = run_dir / f"{RUN_STAGES.index(stage):02d}-{stage}.json"
    _write_or_verify_private_json(path, state)
    return _digest(state)


def _run_preflight(
    inputs: StageInputs,
    adapter: StageAdapter,
    bindings: dict[str, str],
) -> dict[str, object]:
    observed = adapter.inspect_preflight(
        bindings=bindings, expected_count=inputs.expected_count
    )
    if not isinstance(observed, Mapping) or set(observed) != {
        "reachability",
        "prestate",
        "quiescence",
        "capacity",
        "operator_markers",
        "target_set",
    }:
        raise RestoreControlError("preflight result is incomplete")
    reachability = _require_exact_true_map(
        observed.get("reachability"),
        {"kubernetes", "s3"},
        "required services are unreachable",
    )
    prestate = _require_prestate(observed.get("prestate"))
    quiescence = _require_quiescence(observed.get("quiescence"))
    capacity_source = observed.get("capacity")
    if not isinstance(capacity_source, Mapping) or set(capacity_source) != {
        "snapshot_bytes",
        "pvc_free_bytes",
        "node_free_bytes",
        "reserve_bytes",
    }:
        raise RestoreControlError("measured restore capacity is incomplete")
    capacity = require_restore_capacity(
        snapshot_bytes=capacity_source["snapshot_bytes"],
        pvc_free_bytes=capacity_source["pvc_free_bytes"],
        node_free_bytes=capacity_source["node_free_bytes"],
        reserve_bytes=capacity_source["reserve_bytes"],
    )
    markers = _require_operator_markers(observed.get("operator_markers"))
    target_set = _require_target_set(observed.get("target_set"))
    rendered = adapter.render_manifests(
        operator_markers=markers, target_set=target_set
    )
    for mode in ("client", "server"):
        result = adapter.validate_manifests(rendered, mode=mode)
        if not isinstance(result, Mapping) or result.get("valid") is not True:
            raise RestoreControlError("operator manifest dry-run failed")
    current = _stage_bindings(inputs)
    if current != bindings:
        raise RestoreControlError("Phase 20 binding drift detected before mutation")
    applied = adapter.apply_manifests(rendered)
    if (
        not isinstance(applied, Mapping)
        or applied.get("applied") is not True
        or applied.get("target_count") != len(OPERATOR_TARGETS)
        or applied.get("marker_count") != len(OPERATOR_MARKERS)
        or applied.get("recurring_schedule_changed") is not False
    ):
        raise RestoreControlError("operator manifest apply proof is invalid")
    runtime = adapter.inspect_runtime()
    if (
        not isinstance(runtime, Mapping)
        or set(runtime) != {"qdrant_reachable", "workloads_ready"}
        or runtime.get("qdrant_reachable") is not True
        or runtime.get("workloads_ready") is not True
    ):
        raise RestoreControlError("isolated runtime is not ready")
    reachability["qdrant"] = True
    return {
        "bindings": bindings,
        "reachability": reachability,
        "prestate": prestate,
        "quiescence": quiescence,
        "capacity": capacity,
        "manifest_checks": {
            "target_count": len(OPERATOR_TARGETS),
            "marker_count": len(OPERATOR_MARKERS),
            "client_dry_run": True,
            "server_dry_run": True,
            "applied": True,
            "recurring_schedule_changed": False,
        },
    }


def _run_backup(
    inputs: StageInputs,
    adapter: StageAdapter,
    bindings: dict[str, str],
    run_dir: Path,
) -> dict[str, object]:
    cronjob, private_environment = adapter.load_backup_inputs()
    job = generate_backup_job(
        cronjob,
        run_id=inputs.run_id,
        private_environment=private_environment,
    )
    job_path = run_dir / "backup-job.json"
    _write_or_verify_private_json(job_path, job)
    dry_run = validate_backup_job(job_path, runner=adapter.run_command)
    current = _stage_bindings(inputs)
    if current != bindings:
        raise RestoreControlError("Phase 20 binding drift detected before mutation")
    applied = adapter.apply_backup_job(job_path)
    if (
        not isinstance(applied, Mapping)
        or not (
            applied.get("created") is True
            or applied.get("reused") is True
        )
        or applied.get("job_count") != 1
    ):
        raise RestoreControlError("one-shot backup Job proof is invalid")
    completed = adapter.wait_backup_job()
    if (
        not isinstance(completed, Mapping)
        or completed.get("complete") is not True
        or completed.get("job_count") != 1
    ):
        raise RestoreControlError("one-shot backup Job did not complete")
    inventory = adapter.remote_package_inventory()
    if inventory != sorted(PACKAGE_MEMBERS):
        raise RestoreControlError("remote backup package inventory is invalid")
    package_dir = run_dir / "downloaded-package"
    adapter.download_backup_package(package_dir)
    package = verify_backup_package(
        package_dir,
        expected_run_id=inputs.run_id,
        expected_phase20_bindings=bindings,
    )
    return {
        "bindings": bindings,
        "package_dir_sha256": hashlib.sha256(
            str(package_dir).encode("utf-8")
        ).hexdigest(),
        "package_checks": {
            **package,
            "local_hashes_rechecked": True,
            "job_count": 1,
        },
        "object_checks": {
            "verified": True,
            "inventory_exact": True,
            "downloaded": True,
            "hashes_rechecked": True,
            "object_count": len(PACKAGE_MEMBERS),
            "package_sha256": package["package_sha256"],
        },
        "job_checks": {**backup_job_evidence(job), **dry_run},
    }


def _run_isolated_restore(
    inputs: StageInputs,
    adapter: StageAdapter,
    bindings: dict[str, str],
    run_dir: Path,
) -> dict[str, object]:
    preflight = _load_stage_state(run_dir, "preflight")
    backup = _load_stage_state(run_dir, "backup")
    if preflight.get("bindings") != bindings or backup.get("bindings") != bindings:
        raise RestoreControlError("restore stage binding collision detected")
    package_dir = run_dir / "downloaded-package"
    package = verify_backup_package(
        package_dir,
        expected_run_id=inputs.run_id,
        expected_phase20_bindings=bindings,
    )
    stored_package = backup.get("package_checks")
    if not isinstance(stored_package, Mapping) or any(
        stored_package.get(key) != value for key, value in package.items()
    ):
        raise RestoreControlError("downloaded backup package changed")
    absence = require_absent_target(
        adapter.qdrant_request,
        target_collection=inputs.target_collection,
        protected_collection=inputs.protected_collection,
    )
    capacity = preflight.get("capacity")
    if not isinstance(capacity, Mapping) or capacity.get("sufficient") is not True:
        raise RestoreControlError("restore capacity proof is unavailable")
    current = _stage_bindings(inputs)
    if current != bindings:
        raise RestoreControlError("Phase 20 binding drift detected before mutation")
    recovery = recover_snapshot(
        adapter.qdrant_request,
        target_collection=inputs.target_collection,
        snapshot_location=(package_dir / "qdrant.snapshot").resolve().as_uri(),
        priority="snapshot",
    )
    return {
        "bindings": bindings,
        "target_absence": absence,
        "recovery": recovery,
    }


def _normalize_rollback(value: object) -> dict[str, bool]:
    source_keys = {
        "active_state_unchanged",
        "active_alias_unchanged",
        "nginx_unchanged",
        "mcp_registration_unchanged",
        "legacy_runtime_unchanged",
        "recurring_schedule_unchanged",
    }
    _require_exact_true_map(value, source_keys, "active pre-state changed")
    return {
        "active_state_unchanged": True,
        "routing_unchanged": True,
        "nginx_unchanged": True,
        "registration_unchanged": True,
        "legacy_runtime_unchanged": True,
        "recurring_schedule_unchanged": True,
    }


def _run_verify_restore(
    inputs: StageInputs,
    adapter: StageAdapter,
    bindings: dict[str, str],
    run_dir: Path,
) -> dict[str, object]:
    preflight = _load_stage_state(run_dir, "preflight")
    backup = _load_stage_state(run_dir, "backup")
    restored = _load_stage_state(run_dir, "isolated-restore")
    if any(
        state.get("bindings") != bindings
        for state in (preflight, backup, restored)
    ):
        raise RestoreControlError("verification stage binding collision detected")
    package_dir = run_dir / "downloaded-package"
    package = verify_backup_package(
        package_dir,
        expected_run_id=inputs.run_id,
        expected_phase20_bindings=bindings,
    )
    parity_result: dict[str, object] = {}

    def exact_parity() -> Mapping[str, object]:
        nonlocal parity_result
        observed = adapter.run_phase20_parity()
        expected_fields = {
            "verdict",
            "record_count",
            "field_exact",
            "id_exact",
            "metadata_exact",
            "timestamp_exact",
            "vector_exact",
            "exclusion_exact",
            "ann_exact",
        }
        if (
            not isinstance(observed, Mapping)
            or set(observed) != expected_fields
            or observed.get("verdict") != "pass"
            or observed.get("record_count") != inputs.expected_count
            or any(
                observed.get(key) is not True
                for key in expected_fields - {"verdict", "record_count"}
            )
        ):
            raise RestoreControlError("restored exact parity failed")
        parity_result = dict(observed)
        return observed

    restore_checks = verify_restored_collection(
        adapter.qdrant_request,
        target_collection=inputs.target_collection,
        expected_vector_config=inputs.expected_vector_config,
        expected_count=inputs.expected_count,
        parity_check=exact_parity,
    )
    current = _stage_bindings(inputs)
    if current != bindings:
        raise RestoreControlError("Phase 20 binding drift detected before mutation")
    alias = probe_alias_compatibility(
        adapter.qdrant_request,
        restored_collection=inputs.target_collection,
        probe_alias=inputs.probe_alias,
        exact_image_probe=adapter.run_exact_image_probe,
    )
    rollback = _normalize_rollback(
        adapter.verify_prestate(dict(preflight["prestate"]))
    )
    quiescence = dict(preflight["quiescence"])
    reachability = preflight["reachability"]
    if not isinstance(reachability, Mapping):
        raise RestoreControlError("preflight reachability proof is unavailable")
    quiescence.update(
        {
            "kubernetes_reachable": reachability.get("kubernetes") is True,
            "qdrant_reachable": reachability.get("qdrant") is True,
            "s3_reachable": reachability.get("s3") is True,
        }
    )
    evidence = {
        "schema": AGGREGATE_EVIDENCE_SCHEMA,
        "run_id": inputs.run_id,
        "phase20_bindings": bindings,
        "quiescence": quiescence,
        "capacity": preflight["capacity"],
        "package_checks": backup["package_checks"],
        "object_checks": backup["object_checks"],
        "target_absence": restored["target_absence"],
        "restore_checks": {
            **restore_checks,
            "snapshot_priority": restored.get("recovery", {}).get(
                "snapshot_priority"
            )
            is True,
        },
        "parity_checks": {
            "exact": parity_result.get("verdict") == "pass",
            "record_count": parity_result.get("record_count"),
            "field_exact": parity_result.get("field_exact"),
            "id_exact": parity_result.get("id_exact"),
            "metadata_exact": parity_result.get("metadata_exact"),
            "timestamp_exact": parity_result.get("timestamp_exact"),
            "vector_exact": parity_result.get("vector_exact"),
            "exclusion_exact": parity_result.get("exclusion_exact"),
            "ann_exact": parity_result.get("ann_exact"),
        },
        "alias_compatibility": {**alias, "exact_image": True},
        "rollback_state": rollback,
        "verdict": "pass",
    }
    if package.get("package_sha256") != evidence["package_checks"].get(
        "package_sha256"
    ):
        raise RestoreControlError("downloaded backup package changed")
    _validate_aggregate_evidence(evidence)
    _write_or_verify_evidence(
        Path(inputs.evidence_dir) / AGGREGATE_EVIDENCE_NAME, evidence
    )
    return {"bindings": bindings, "evidence": evidence}


def execute_stage(
    stage: str,
    *,
    inputs: StageInputs,
    adapter: StageAdapter,
    resume_run: bool,
) -> dict[str, object]:
    """Execute one exact stage, or replay its verified checkpoint without I/O."""
    inputs = _validated_stage_inputs(inputs)
    if stage not in RUN_STAGES:
        raise RestoreControlError("run stage is invalid")
    bindings = _stage_bindings(inputs)
    run_dir = _private_stage_dir(inputs)
    with acquire_run_lock(
        inputs.evidence_dir,
        run_id=inputs.run_id,
        binding_sha256=bindings["binding_sha256"],
        resume_run=resume_run,
    ) as lock:
        prior = str(lock.state["last_stage"])
        prior_index = -1 if prior == "unstarted" else RUN_STAGES.index(prior)
        stage_index = RUN_STAGES.index(stage)
        if stage_index == prior_index:
            state = _load_stage_state(run_dir, stage)
            if _digest(state) != lock.state["last_evidence_sha256"]:
                raise RestoreControlError("run checkpoint content changed")
            return state
        if stage_index != prior_index + 1:
            raise RestoreControlError("run stage transition is invalid")
        if stage == "preflight":
            state = _run_preflight(inputs, adapter, bindings)
        elif stage == "backup":
            state = _run_backup(inputs, adapter, bindings, run_dir)
        elif stage == "isolated-restore":
            state = _run_isolated_restore(inputs, adapter, bindings, run_dir)
        else:
            state = _run_verify_restore(inputs, adapter, bindings, run_dir)
        checkpoint = _save_stage_state(run_dir, stage, state)
        checkpoint_run(lock, stage, checkpoint)
        return state


class JsonOperatorAdapter:
    """Run explicit bounded operator operations through one private executable."""

    def __init__(self, executable: Path, private_dir: Path) -> None:
        executable = Path(executable)
        if not executable.is_absolute():
            raise RestoreControlError("operator executable must be absolute")
        try:
            details = executable.lstat()
        except OSError as error:
            raise RestoreControlError("operator executable is unavailable") from error
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or not os.access(executable, os.X_OK)
        ):
            raise RestoreControlError("operator executable is unavailable")
        self.executable = executable
        self.private_dir = Path(private_dir)
        self.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.private_dir, 0o700)
        self.sequence = 0

    def _call(
        self,
        operation: str,
        payload: Mapping[str, object],
        *,
        timeout: float,
    ) -> object:
        if not SAFE_NAME.fullmatch(operation) or timeout <= 0:
            raise RestoreControlError("operator operation is invalid")
        self.sequence += 1
        stem = f"{self.sequence:03d}-{operation}"
        request_path = self.private_dir / f"{stem}-request.json"
        response_path = self.private_dir / f"{stem}-response.json"
        write_private_json(request_path, payload)
        command = (
            str(self.executable),
            operation,
            str(request_path),
            str(response_path),
        )
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RestoreControlError("operator operation failed") from error
        if result.returncode != 0:
            raise RestoreControlError("operator operation failed")
        response = _load_json(response_path)
        if set(response) != {"ok", "result"} or response.get("ok") is not True:
            raise RestoreControlError("operator response contract is invalid")
        return response["result"]

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise RestoreControlError("operator response contract is invalid")
        return dict(value)

    def inspect_preflight(
        self, *, bindings: dict[str, str], expected_count: int
    ) -> Mapping[str, object]:
        return self._mapping(
            self._call(
                "inspect-preflight",
                {"bindings": bindings, "expected_count": expected_count},
                timeout=180,
            )
        )

    def render_manifests(
        self,
        *,
        operator_markers: dict[str, str],
        target_set: tuple[str, ...],
    ) -> object:
        return self._call(
            "render-manifests",
            {"operator_markers": operator_markers, "target_set": list(target_set)},
            timeout=60,
        )

    def validate_manifests(
        self, rendered: object, *, mode: str
    ) -> Mapping[str, object]:
        if mode not in {"client", "server"}:
            raise RestoreControlError("operator dry-run mode is invalid")
        return self._mapping(
            self._call(
                "validate-manifests",
                {"rendered": rendered, "mode": mode},
                timeout=180,
            )
        )

    def apply_manifests(self, rendered: object) -> Mapping[str, object]:
        return self._mapping(
            self._call(
                "apply-manifests", {"rendered": rendered}, timeout=600
            )
        )

    def inspect_runtime(self) -> Mapping[str, object]:
        return self._mapping(self._call("inspect-runtime", {}, timeout=600))

    def load_backup_inputs(self) -> tuple[dict[str, object], dict[str, str]]:
        value = self._call("load-backup-inputs", {}, timeout=60)
        if (
            not isinstance(value, Mapping)
            or not isinstance(value.get("cronjob"), Mapping)
            or not isinstance(value.get("private_environment"), Mapping)
        ):
            raise RestoreControlError("operator backup inputs are invalid")
        environment = value["private_environment"]
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in environment.items()):
            raise RestoreControlError("operator backup inputs are invalid")
        return dict(value["cronjob"]), dict(environment)

    def run_command(
        self, command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        allowed = (
            ("kubectl", "apply", "--dry-run=client"),
            ("kubectl", "apply", "--server-side", "--dry-run=server"),
        )
        if not any(command[: len(prefix)] == prefix for prefix in allowed):
            raise RestoreControlError("external command is not allowlisted")
        timeout = kwargs.get("timeout")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise RestoreControlError("external command timeout is invalid")
        try:
            return subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RestoreControlError("external command failed") from error

    def apply_backup_job(self, job_path: Path) -> Mapping[str, object]:
        return self._mapping(
            self._call(
                "apply-backup-job", {"job_path": str(job_path)}, timeout=300
            )
        )

    def wait_backup_job(self) -> Mapping[str, object]:
        return self._mapping(self._call("wait-backup-job", {}, timeout=3600))

    def remote_package_inventory(self) -> list[str]:
        value = self._call("remote-package-inventory", {}, timeout=300)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RestoreControlError("remote backup package inventory is invalid")
        return value

    def download_backup_package(self, package_dir: Path) -> None:
        result = self._mapping(
            self._call(
                "download-backup-package",
                {"package_dir": str(package_dir)},
                timeout=1800,
            )
        )
        if result.get("downloaded") is not True:
            raise RestoreControlError("backup package download failed")

    def qdrant_request(
        self, method: str, path: str, body: object = None, **_kwargs: object
    ) -> object:
        value = self._call(
            "qdrant-request",
            {"method": method, "path": path, "body": body},
            timeout=60,
        )
        if isinstance(value, Mapping) and value.get("not_found") is True:
            raise QdrantNotFound("Qdrant target is absent")
        if not isinstance(value, Mapping) or set(value) != {"response"}:
            raise RestoreControlError("Qdrant response contract is invalid")
        return value["response"]

    def run_phase20_parity(self) -> Mapping[str, object]:
        return self._mapping(self._call("run-phase20-parity", {}, timeout=1800))

    def run_exact_image_probe(self) -> object:
        return self._call("run-exact-image-probe", {}, timeout=300)

    def verify_prestate(
        self, prestate: dict[str, str]
    ) -> Mapping[str, object]:
        return self._mapping(
            self._call("verify-prestate", {"prestate": prestate}, timeout=300)
        )


def _command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in RUN_STAGES:
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
        subparser.add_argument(
            "--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR
        )
        subparser.add_argument("--run-id")
        subparser.add_argument("--resume-run", action="store_true")
        subparser.add_argument("--check-only", action="store_true")
    return parser


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RestoreControlError("live execution inputs are incomplete")
    return value


def _stage_inputs_from_environment(
    *,
    handoff_path: Path,
    evidence_dir: Path,
    run_id: str,
    expected_count: int,
) -> StageInputs:
    phase20_dir = handoff_path.parent
    try:
        vector_config = json.loads(
            _required_environment("SOLIDSTATS_MEMORY_VECTOR_CONFIG_JSON")
        )
    except json.JSONDecodeError as error:
        raise RestoreControlError("live execution inputs are incomplete") from error
    if not isinstance(vector_config, Mapping) or not vector_config:
        raise RestoreControlError("live execution inputs are incomplete")
    return StageInputs(
        run_id=run_id,
        handoff_path=handoff_path,
        parity_path=phase20_dir / "20-PARITY-REPORT.json",
        source_inventory_path=phase20_dir / "20-SOURCE-INVENTORY.json",
        mapping_contract_path=phase20_dir / "20-MAPPING-CONTRACT.json",
        transform_manifest_path=phase20_dir / "20-TRANSFORM-MANIFEST.json",
        bundle_dir=Path(_required_environment("SOLIDSTATS_MEMORY_BUNDLE_DIR")),
        private_run_root=Path(
            _required_environment("SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT")
        ),
        evidence_dir=evidence_dir,
        target_collection=_required_environment(
            "SOLIDSTATS_MEMORY_TARGET_COLLECTION"
        ),
        protected_collection=_required_environment(
            "SOLIDSTATS_MEMORY_PROTECTED_COLLECTION"
        ),
        probe_alias=_required_environment("SOLIDSTATS_MEMORY_PROBE_ALIAS"),
        expected_vector_config=vector_config,
        expected_count=expected_count,
    )


def main(
    argv: list[str] | None = None,
    *,
    adapter: StageAdapter | None = None,
) -> int:
    """Execute one bounded stage and emit only a value-free result line."""
    parser = _command_parser()
    args = parser.parse_args(argv)
    try:
        handoff, _public_bindings, _expected_bundle = (
            recompute_phase20_public_bindings(handoff_path=args.handoff)
        )
        run_id = args.run_id or os.environ.get("SOLIDSTATS_MEMORY_RUN_ID")
        if run_id is not None:
            run_id = _require_run_id(run_id)
        if args.resume_run and run_id is None:
            raise RestoreControlError("resume requires an exact run identity")
        if args.check_only:
            print(f"PASS: {args.command} public contract validated")
            return 0
        if run_id is None:
            raise RestoreControlError("live execution inputs are incomplete")
        inputs = _stage_inputs_from_environment(
            handoff_path=args.handoff,
            evidence_dir=args.evidence_dir,
            run_id=run_id,
            expected_count=_require_positive_int(
                handoff.get("record_count"), "Phase 20 handoff count is invalid"
            ),
        )
        if adapter is None:
            adapter = JsonOperatorAdapter(
                Path(_required_environment("SOLIDSTATS_MEMORY_OPERATOR")),
                inputs.private_run_root / run_id / "operator",
            )
        execute_stage(
            args.command,
            inputs=inputs,
            adapter=adapter,
            resume_run=args.resume_run,
        )
        print(f"PASS: {args.command} completed")
        return 0
    except (OSError, RestoreControlError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
