#!/usr/bin/env python3
"""Build a private, approval-bound MemPalace v3.5.0 Qdrant bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
UUID_NAMESPACE = uuid.UUID("c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1")
CONTRACT_SCHEMA = "solidstats-memory-mapping-contract/v1"
MAX_RECORDS = 1_000_000
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_VECTOR_DIMENSION = 65_536
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_PRIVATE_SOURCE_ARTIFACT_BYTES = 512 * 1024 * 1024
RESERVED_METADATA_KEY = "_solidstats_migration"
PINNED_QDRANT_IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}$")


class VectorStrategy:
    """Closed vector decision evidence without importing application packages."""

    def __init__(self, strategy: str, reason: str, model_artifact_sha256: str | None = None) -> None:
        self.strategy = strategy
        self.reason = reason
        self.model_artifact_sha256 = model_artifact_sha256


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, *, label: str, max_bytes: int = MAX_JSON_BYTES) -> Path:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.stat().st_size > max_bytes:
            raise ValueError
        return path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} is unsafe") from error
    except ValueError as error:
        raise ValueError(f"{label} is unsafe") from error


def _contained_regular_file(root: Path, relative: object, *, label: str, max_bytes: int = MAX_JSON_BYTES) -> Path:
    if not _nonempty_string(relative):
        raise ValueError(f"{label} is unsafe")
    candidate_relative = Path(str(relative))
    if candidate_relative.is_absolute() or ".." in candidate_relative.parts:
        raise ValueError(f"{label} is unsafe")
    candidate = root / candidate_relative
    resolved = _regular_file(candidate, label=label, max_bytes=max_bytes)
    if root not in (resolved, *resolved.parents):
        raise ValueError(f"{label} is unsafe")
    return resolved


def _regular_executable(path: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as error:
        raise ValueError(f"{label} is unsafe") from error
    if not stat.S_ISREG(mode) or not os.access(resolved, os.X_OK):
        raise ValueError(f"{label} is unsafe")
    return resolved


def _safe_directory(path: Path, *, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError
        resolved = path.resolve(strict=True)
        for current, directories, files in os.walk(resolved, followlinks=False):
            for name in [*directories, *files]:
                child_mode = (Path(current) / name).lstat().st_mode
                if stat.S_ISLNK(child_mode) or not (stat.S_ISDIR(child_mode) or stat.S_ISREG(child_mode)):
                    raise ValueError
        return resolved
    except OSError as error:
        raise ValueError(f"{label} is unsafe") from error
    except ValueError as error:
        raise ValueError(f"{label} is unsafe") from error


def _load_json(path: Path, *, label: str, max_bytes: int = MAX_JSON_BYTES) -> dict[str, object]:
    safe_path = _regular_file(path, label=label, max_bytes=max_bytes)
    try:
        value = json.loads(safe_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return value


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _validate_contract_shape(contract: Mapping[str, object]) -> None:
    if contract.get("contract_schema") != CONTRACT_SCHEMA or contract.get("status") != "approved":
        raise ValueError("mapping contract is not approved")
    if not _nonempty_string(contract.get("approved_at")) or not _nonempty_string(contract.get("approval_digest")):
        raise ValueError("mapping contract approval is incomplete")
    required = (
        "timestamp_semantics", "source_wing_to_target_wing", "legacy_room_label_treatment",
        "legacy_archive_label_treatment", "excluded_source_disposition", "preservation_representation",
    )
    if any(not isinstance(contract.get(key), dict) or not contract[key] for key in required):
        raise ValueError("mapping contract is incomplete")
    timestamps = contract["timestamp_semantics"]
    if not isinstance(timestamps, dict) or not isinstance(timestamps.get("preserved_fields"), list) or not all(
        _nonempty_string(field) for field in timestamps["preserved_fields"]
    ) or any(not _nonempty_string(timestamps.get(key)) for key in ("rule", "missing_or_invalid", "target_updated_at")):
        raise ValueError("mapping contract timestamp rules are incomplete")
    routing = contract["source_wing_to_target_wing"]
    if not isinstance(routing, dict) or not _nonempty_string(routing.get("routing_authority")):
        raise ValueError("mapping contract routing rules are incomplete")
    routes = routing.get("canonical_repository_rules")
    shared = routing.get("shared_source_rule")
    if not isinstance(routes, dict) or not routes or not isinstance(shared, dict) or not shared or not _nonempty_string(routing.get("excluded_source_rule")) or not all(
        _nonempty_string(source) and _nonempty_string(target) for source, target in [*routes.items(), *shared.items()]
    ):
        raise ValueError("mapping contract routing rules are incomplete")
    for key, fields in (
        ("legacy_room_label_treatment", ("rule", "active_semantic_room_effect")),
        ("legacy_archive_label_treatment", ("source_observation", "unexpected_or_unbound", "target_label_rule")),
        ("excluded_source_disposition", ("rule", "retention")),
    ):
        rules = contract[key]
        if not isinstance(rules, dict) or any(not _nonempty_string(rules.get(field)) for field in fields):
            raise ValueError("mapping contract preservation rules are incomplete")
    preservation = contract["preservation_representation"]
    if not isinstance(preservation, dict) or any(not _nonempty_string(preservation.get(field)) for field in (
        "approval_token", "standard_fields", "operational_metadata", "parity_rule", "independent_safety_copy", "duplication_acceptance"
    )):
        raise ValueError("mapping contract preservation rules are incomplete")
    metadata_copy = preservation.get("source_metadata_copy")
    recovery = preservation.get("archive_immutability_and_recovery")
    collision_rule = metadata_copy.get("collision_rule") if isinstance(metadata_copy, dict) else None
    normalized_collision_rule = " ".join(collision_rule.lower().split()) if isinstance(collision_rule, str) else ""
    if not isinstance(metadata_copy, dict) or metadata_copy.get("reserved_key") != RESERVED_METADATA_KEY or not (
        normalized_collision_rule.startswith("fail closed")
        and f"already contains {RESERVED_METADATA_KEY}" in normalized_collision_rule
    ):
        raise ValueError("mapping contract preservation rules are incomplete")
    shape = metadata_copy.get("value_shape")
    if not isinstance(shape, dict) or shape.get("schema_version") != 1 or shape.get("source_metadata") != "exact original metadata dictionary":
        raise ValueError("mapping contract preservation rules are incomplete")
    if not isinstance(recovery, dict) or any(not _nonempty_string(recovery.get(field)) for field in (
        "agent_rule", "adjacent_contract", "recovery_boundary", "accepted_residual_risk"
    )):
        raise ValueError("mapping contract preservation rules are incomplete")
    expected_rules = (
        (timestamps.get("rule"), "Preserve each observed source timestamp field exactly as found; apply no precedence, normalization, or synthesized source_timestamp or effective_source_date."),
        (timestamps.get("missing_or_invalid"), "A missing or invalid timestamp candidate neither rejects nor drops a record; it remains absent or invalid exactly as found in source metadata."),
        (contract["legacy_room_label_treatment"].get("rule"), "Preserve every legacy room value unchanged for imported archive records."),
        (contract["legacy_archive_label_treatment"].get("unexpected_or_unbound"), "Fail closed rather than remapping an unexpected or unbound label."),
        (contract["excluded_source_disposition"].get("rule"), "Do not import agent or other-wing records into target Qdrant."),
        (preservation.get("operational_metadata"), "Use a copy of source metadata with only operational wing changed for archive routing; retain original room and every other field unchanged."),
    )
    if any(actual != expected for actual, expected in expected_rules):
        raise ValueError("mapping contract semantic rules are incompatible")


def load_approved_mapping_contract(inventory_proof: Path, mapping_contract: Path) -> dict[str, object]:
    proof = _regular_file(inventory_proof, label="source inventory proof", max_bytes=MAX_JSON_BYTES)
    contract_path = _regular_file(mapping_contract, label="mapping contract", max_bytes=MAX_JSON_BYTES)
    contract = _load_json(contract_path, label="mapping contract")
    _validate_contract_shape(contract)
    if contract.get("source_inventory_sha256") != sha256_file(proof):
        raise ValueError("mapping contract inventory binding is invalid")
    approval_digest = contract.get("approval_digest")
    canonical = dict(contract)
    canonical.pop("approval_digest", None)
    if approval_digest != sha256_bytes(canonical_json_bytes(canonical)):
        raise ValueError("mapping contract approval digest is invalid")
    return contract


def select_vector_strategy(
    source: Mapping[str, object], target: Mapping[str, object], *, reembed_model_artifact: Path | None = None
) -> VectorStrategy:
    checks = (
        ("embedder_identity", source.get("embedder_identity") == target.get("embedder_identity")),
        ("embedder_configuration", source.get("embedder_configuration") == target.get("embedder_configuration")),
        ("dimension", source.get("dimension") == target.get("dimension")),
        ("source_metric", source.get("metric") == "cosine"),
        ("target_metric", target.get("metric") == "Cosine"),
        ("serialization", source.get("serialization") == target.get("serialization")),
    )
    mismatch = next((name for name, matched in checks if not matched), None)
    if mismatch is None:
        return VectorStrategy("reuse", "all D-07 predicates matched")
    if reembed_model_artifact is None:
        return VectorStrategy("reembed", f"{mismatch} mismatch")
    return VectorStrategy("reembed", f"{mismatch} mismatch")


def _lossless_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("source metadata is invalid")
    try:
        encoded = canonical_json_bytes(value)
        if len(encoded) > MAX_METADATA_BYTES or json.loads(encoded) != value:
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("source metadata is invalid") from error
    return value


def _route_wing(metadata: Mapping[str, object], contract: Mapping[str, object]) -> str | None:
    source_wing = metadata.get("wing")
    if not isinstance(source_wing, str) or not source_wing:
        raise ValueError("source wing is invalid")
    routing = contract["source_wing_to_target_wing"]
    assert isinstance(routing, dict)
    routes = routing["canonical_repository_rules"]
    shared = routing["shared_source_rule"]
    assert isinstance(routes, dict) and isinstance(shared, dict)
    if source_wing in routes:
        target = routes[source_wing]
        assert isinstance(target, str)
        return target
    if source_wing in shared:
        target = shared[source_wing]
        assert isinstance(target, str)
        return target
    if source_wing.endswith("-archive"):
        raise ValueError("unexpected archive wing")
    return None


def build_target_points(
    sources: Iterable[Mapping[str, object]], contract: Mapping[str, object], *, target_updated_at: str
) -> tuple[list[dict[str, object]], list[dict[str, str]], list[str]]:
    _validate_contract_shape(contract)
    points: list[dict[str, object]] = []
    mappings: list[dict[str, str]] = []
    excluded: list[str] = []
    seen_ids: set[str] = set()
    for source in sorted(sources, key=lambda item: sha256_bytes(str(item.get("id", "")).encode("utf-8"))):
        source_id = source.get("id")
        document = source.get("document")
        metadata = _lossless_metadata(source.get("metadata"))
        vector = source.get("vector")
        if not isinstance(source_id, str) or not source_id or source_id in seen_ids or not isinstance(document, str) or len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise ValueError("source record is invalid")
        if not isinstance(vector, list) or not 0 < len(vector) <= MAX_VECTOR_DIMENSION or any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in vector
        ):
            raise ValueError("source vector is invalid")
        seen_ids.add(source_id)
        target_wing = _route_wing(metadata, contract)
        if target_wing is None:
            excluded.append(source_id)
            continue
        if RESERVED_METADATA_KEY in metadata:
            raise ValueError("reserved metadata collision")
        operational_metadata = dict(metadata)
        operational_metadata["wing"] = target_wing
        operational_metadata[RESERVED_METADATA_KEY] = {"schema_version": 1, "source_metadata": metadata}
        point_id = str(uuid.uuid5(UUID_NAMESPACE, source_id))
        points.append({
            "id": point_id,
            "vector": vector,
            "payload": {"mempalace_id": source_id, "document": document, "metadata": operational_metadata, "updated_at": target_updated_at},
        })
        mappings.append({"source_id": source_id, "mempalace_id": source_id, "point_id": point_id})
    if len({item["source_id"] for item in mappings}) != len(mappings) or len({item["point_id"] for item in mappings}) != len(mappings):
        raise ValueError("source ID bijection is invalid")
    return points, mappings, excluded


def _safe_output_dir(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ValueError("output directory must be new")
    parent = path.parent
    try:
        parent_mode = parent.lstat().st_mode
        if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
            raise ValueError
    except OSError as error:
        raise ValueError("output directory parent is unsafe") from error
    path.mkdir(mode=0o700)
    return path


def _write_private(path: Path, value: object, *, jsonl: bool = False) -> str:
    payload = b"".join(canonical_json_bytes(item) + b"\n" for item in value) if jsonl else canonical_json_bytes(value) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
    return sha256_bytes(payload)


def _read_jsonl_pairs(records_path: Path, vectors_path: Path) -> list[dict[str, object]]:
    records = _regular_file(records_path, label="source records", max_bytes=MAX_PRIVATE_SOURCE_ARTIFACT_BYTES)
    vectors = _regular_file(vectors_path, label="source vectors", max_bytes=MAX_PRIVATE_SOURCE_ARTIFACT_BYTES)
    merged: list[dict[str, object]] = []
    with records.open(encoding="utf-8") as records_file, vectors.open(encoding="utf-8") as vectors_file:
        for index, (record_line, vector_line) in enumerate(zip(records_file, vectors_file, strict=True), 1):
            if len(record_line.encode("utf-8")) > MAX_DOCUMENT_BYTES + MAX_METADATA_BYTES + 4096:
                raise ValueError("source record exceeds bounds")
            try:
                record, vector = json.loads(record_line), json.loads(vector_line)
            except json.JSONDecodeError as error:
                raise ValueError("source records are invalid") from error
            if not isinstance(record, dict) or not isinstance(vector, dict) or record.get("id") != vector.get("id"):
                raise ValueError("source records are invalid")
            merged.append({"id": record.get("id"), "document": record.get("document"), "metadata": record.get("metadata"), "vector": vector.get("vector")})
            if index > MAX_RECORDS:
                raise ValueError("source record limit exceeded")
        if next(records_file, None) is not None or next(vectors_file, None) is not None:
            raise ValueError("source records are invalid")
    if not merged:
        raise ValueError("source records are empty")
    return merged


def _loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise ValueError("qdrant URL must be loopback-only")
    return value.rstrip("/")


def _qdrant_request(base_url: str, method: str, path: str, body: object | None = None) -> dict[str, object]:
    data = canonical_json_bytes(body) if body is not None else None
    request = Request(f"{base_url}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            decoded = json.loads(response.read(MAX_JSON_BYTES + 1))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise ValueError("local Qdrant request failed") from error
    if not isinstance(decoded, dict) or decoded.get("status") not in ("ok", "completed"):
        raise ValueError("local Qdrant response is invalid")
    return decoded


def load_pinned_qdrant_image(manifest_path: Path) -> str:
    manifest = _regular_file(manifest_path, label="Qdrant manifest", max_bytes=4 * 1024 * 1024)
    try:
        images = [
            match.group(1)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if (match := re.fullmatch(r"\s*image:\s*([^\s#]+)\s*", line))
        ]
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("Qdrant image is unavailable") from error
    pinned = [image for image in images if "qdrant" in image]
    if len(pinned) != 1 or not PINNED_QDRANT_IMAGE_PATTERN.fullmatch(pinned[0]):
        raise ValueError("Qdrant image is not exactly pinned by digest")
    return pinned[0]


def point_id_set_sha256(points: Iterable[Mapping[str, object]]) -> str:
    point_ids: list[str] = []
    for point in points:
        point_id = point.get("id")
        if not _nonempty_string(point_id):
            raise ValueError("target point ID is invalid")
        point_ids.append(str(point_id))
    if len(point_ids) != len(set(point_ids)):
        raise ValueError("target point IDs are not unique")
    return sha256_bytes(canonical_json_bytes(sorted(point_ids)))


def verify_empty_target(base_url: str, collection: str) -> dict[str, int]:
    result = _qdrant_request(base_url, "POST", f"/collections/{quote(collection, safe='')}/points/count", {"exact": True})
    payload = result.get("result")
    if not isinstance(payload, dict) or payload.get("count") != 0:
        raise ValueError("target collection is not empty")
    return {"exact_count": 0}


def verify_collection_schema(base_url: str, collection: str, *, dimension: int) -> None:
    result = _qdrant_request(base_url, "GET", f"/collections/{quote(collection, safe='')}")
    payload = result.get("result")
    if not isinstance(payload, dict):
        raise ValueError("local Qdrant collection schema is invalid")
    config = payload.get("config")
    params = config.get("params") if isinstance(config, dict) else None
    vectors = params.get("vectors") if isinstance(params, dict) else None
    if not isinstance(vectors, dict) or vectors.get("size") != dimension or vectors.get("distance") != "Cosine":
        raise ValueError("local Qdrant collection schema is invalid")


def _completed_operation(result: Mapping[str, object]) -> bool:
    payload = result.get("result")
    return isinstance(payload, dict) and isinstance(payload.get("operation_id"), int) and payload.get("status") == "completed"


def target_point_id_set_sha256(base_url: str, collection: str, *, expected_count: int) -> str:
    if not 0 < expected_count <= MAX_RECORDS:
        raise ValueError("target point count is invalid")
    point_ids: list[str] = []
    offset: object | None = None
    encoded = quote(collection, safe="")
    while True:
        body: dict[str, object] = {"limit": min(1000, expected_count), "with_payload": False, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        response = _qdrant_request(base_url, "POST", f"/collections/{encoded}/points/scroll", body)
        payload = response.get("result")
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
            raise ValueError("local Qdrant target IDs are invalid")
        for point in payload["points"]:
            if not isinstance(point, dict) or not _nonempty_string(point.get("id")):
                raise ValueError("local Qdrant target IDs are invalid")
            point_ids.append(str(point["id"]))
        if len(point_ids) > expected_count:
            raise ValueError("local Qdrant target IDs are invalid")
        offset = payload.get("next_page_offset")
        if offset is None:
            break
    if len(point_ids) != expected_count:
        raise ValueError("local Qdrant target IDs are invalid")
    return point_id_set_sha256({"id": point_id} for point_id in point_ids)


def import_batches(
    base_url: str, collection: str, points: list[dict[str, object]], *, dimension: int,
    batch_size: int, expected_point_id_digest: str, qdrant_run_id: str | None = None,
) -> dict[str, object]:
    if not 0 < batch_size <= 1000:
        raise ValueError("batch size is invalid")
    encoded = quote(collection, safe="")
    create_result = _qdrant_request(base_url, "PUT", f"/collections/{encoded}", {"vectors": {"size": dimension, "distance": "Cosine"}})
    if create_result.get("result") is not True:
        raise ValueError("local Qdrant collection creation was not acknowledged")
    empty_target_proof = verify_empty_target(base_url, collection)
    verify_collection_schema(base_url, collection, dimension=dimension)
    acknowledgements = 0
    for index in range(0, len(points), batch_size):
        result = _qdrant_request(base_url, "PUT", f"/collections/{encoded}/points?wait=true", {"points": points[index:index + batch_size]})
        if not _completed_operation(result):
            raise ValueError("local Qdrant batch was not acknowledged")
        acknowledgements += 1
    final = _qdrant_request(base_url, "POST", f"/collections/{encoded}/points/count", {"exact": True})
    count = final.get("result", {}).get("count") if isinstance(final.get("result"), dict) else None
    if count != len(points):
        raise ValueError("local Qdrant point count is invalid")
    target_digest = target_point_id_set_sha256(base_url, collection, expected_count=len(points))
    if target_digest != expected_point_id_digest:
        raise ValueError("local Qdrant target point IDs are invalid")
    result = {
        "batch_acknowledgements": acknowledgements,
        "empty_target_proof": empty_target_proof,
        "point_count": count,
        "target_point_id_set_sha256": target_digest,
    }
    if qdrant_run_id is not None:
        result["qdrant_run_id"] = qdrant_run_id
    return result


def derive_collection_with_oracle(oracle_python: Path, oracle_source_dir: Path, palace_id: str, namespace: str, source_collection: str) -> dict[str, str]:
    python = _regular_executable(oracle_python, label="oracle python")
    oracle_root = _safe_directory(oracle_source_dir, label="oracle source")
    source = _regular_file(oracle_root / "mempalace" / "backends" / "qdrant.py", label="oracle source", max_bytes=4 * 1024 * 1024)
    program = """import json,sys
oracle_root,palace_id,namespace,collection=sys.argv[1:]
sys.path.insert(0, oracle_root)
from mempalace.backends.qdrant import QdrantBackend, _QdrantConfig
from mempalace.backends.base import PalaceRef
config=_QdrantConfig(url='http://127.0.0.1:9', api_key=None, timeout=1.0, namespace=namespace)
palace=PalaceRef(id=palace_id, local_path='/nonexistent', namespace=namespace)
print(json.dumps({'derived_collection': QdrantBackend()._remote_collection_name(palace=palace, collection_name=collection, config=config)}))"""
    try:
        result = subprocess.run([str(python), "-I", "-c", program, str(oracle_root), palace_id, namespace, source_collection], capture_output=True, text=True, timeout=20, check=False, env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1", "HOME": "/nonexistent"})
        derived = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise ValueError("oracle collection derivation failed") from error
    if result.returncode != 0 or not isinstance(derived, dict) or not _nonempty_string(derived.get("derived_collection")):
        raise ValueError("oracle collection derivation failed")
    return {"oracle_revision": "v3.5.0", "oracle_checksum": sha256_file(source), "palace_id": palace_id, "namespace": namespace, "source_collection": source_collection, "derived_collection": str(derived["derived_collection"])}


def _snapshot_identity(snapshot_dir: Path) -> tuple[str, str, str, dict[str, object]]:
    root = _safe_directory(snapshot_dir, label="snapshot")
    manifest = _load_json(root / "snapshot-manifest.json", label="snapshot manifest")
    identity = _load_json(_contained_regular_file(root, manifest.get("identity_sidecar"), label="snapshot identity"), label="snapshot identity")
    config = _load_json(_contained_regular_file(root, manifest.get("config_sidecar"), label="snapshot config"), label="snapshot config")
    palace_id, namespace, collection = identity.get("palace_id"), identity.get("namespace"), config.get("collection_name")
    if not all(_nonempty_string(value) for value in (palace_id, namespace, collection)):
        raise ValueError("snapshot identity is invalid")
    embedder = _load_json(_contained_regular_file(root, manifest.get("embedder_sidecar"), label="snapshot embedder"), label="snapshot embedder")
    source_identity = embedder.get(collection)
    if not isinstance(source_identity, dict):
        raise ValueError("snapshot identity is invalid")
    return str(palace_id), str(namespace), str(collection), source_identity


def _public_manifest(payload: Mapping[str, object]) -> None:
    allowed = {"transform_schema", "source_inventory_sha256", "oracle_version", "oracle_revision", "mapping_contract_sha256", "collection_derivation_sha256", "source_vector_contract", "target_vector_contract", "vector_strategy", "vector_strategy_reason", "model_artifact_sha256", "point_count", "source_id_set_sha256", "point_id_set_sha256", "bundle_sha256", "qdrant_image", "qdrant_run_id", "empty_target_proof", "import_result", "created_at"}
    if (
        set(payload) - allowed
        or payload.get("transform_schema") != "solidstats-memory-transform/v1"
        or not isinstance(payload.get("qdrant_image"), str)
        or not PINNED_QDRANT_IMAGE_PATTERN.fullmatch(str(payload["qdrant_image"]))
    ):
        raise ValueError("transform manifest is unsafe")
    for key, value in payload.items():
        if key in {"qdrant_image", "transform_schema"}:
            continue
        serialized = canonical_json_bytes(value).decode("utf-8")
        if "/" in serialized or "\\" in serialized:
            raise ValueError("transform manifest is unsafe")
    target = ROOT / ".planning/phases/20-local-corpus-migration/20-TRANSFORM-MANIFEST.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(canonical_json_bytes(payload) + b"\n")
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--source-inventory-proof", required=True)
    parser.add_argument("--mapping-contract", required=True)
    parser.add_argument("--source-records", required=True)
    parser.add_argument("--source-vectors", required=True)
    parser.add_argument("--recall-fixtures", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--oracle-python", required=True)
    parser.add_argument("--oracle-source-dir", required=True)
    parser.add_argument("--reembed-model-artifact")
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--qdrant-image", required=True)
    parser.add_argument("--qdrant-image-manifest", default=ROOT / "k8s/memory/10-qdrant.yaml", type=Path)
    parser.add_argument("--snapshot-dir", required=True, help="private immutable snapshot used only for identity sidecars")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = load_approved_mapping_contract(Path(args.source_inventory_proof), Path(args.mapping_contract))
        _load_json(Path(args.inventory), label="private inventory")
        _regular_file(Path(args.recall_fixtures), label="recall fixtures")
        records = _read_jsonl_pairs(Path(args.source_records), Path(args.source_vectors))
        palace_id, namespace, collection, source_embedder = _snapshot_identity(Path(args.snapshot_dir))
        model_name = source_embedder.get("model_name")
        dimension = source_embedder.get("dimension")
        if not _nonempty_string(model_name) or not isinstance(dimension, int) or isinstance(dimension, bool) or dimension != len(records[0]["vector"]):
            raise ValueError("private source embedder evidence is invalid")
        source_identity = {"embedder_identity": model_name, "embedder_configuration": source_embedder, "dimension": dimension, "metric": "cosine", "serialization": "json-f32"}
        target_identity = dict(source_identity, metric="Cosine")
        reembed_artifact = Path(args.reembed_model_artifact) if args.reembed_model_artifact else None
        strategy = select_vector_strategy(source_identity, target_identity, reembed_model_artifact=reembed_artifact)
        if strategy.strategy != "reuse":
            if reembed_artifact is None:
                raise ValueError("approved local reembedding artifact is required")
            _regular_file(reembed_artifact, label="reembed model artifact")
            raise ValueError("approved local reembedding runner is required")
        derivation = derive_collection_with_oracle(Path(args.oracle_python), Path(args.oracle_source_dir), palace_id, namespace, collection)
        points, mappings, excluded = build_target_points(records, contract, target_updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if args.check_only:
            print("PASS: mapping contract and private bundle inputs validated")
            return 0
        output_dir = _safe_output_dir(Path(args.output_dir))
        try:
            points_digest = _write_private(output_dir / "points.jsonl", points, jsonl=True)
            ids_digest = _write_private(output_dir / "id-map.jsonl", mappings, jsonl=True)
            bundle = {"bundle_schema": "solidstats-memory-private-bundle/v1", "points_sha256": points_digest, "id_map_sha256": ids_digest, "point_count": len(points), "excluded_count": len(excluded)}
            bundle_digest = _write_private(output_dir / "bundle-manifest.json", bundle)
            pinned_qdrant_image = load_pinned_qdrant_image(Path(args.qdrant_image_manifest))
            if args.qdrant_image != pinned_qdrant_image:
                raise ValueError("Qdrant image does not match the pinned manifest")
            qdrant_run_id = uuid.uuid4().hex
            result = import_batches(
                _loopback_url(args.qdrant_url), derivation["derived_collection"], points,
                dimension=len(points[0]["vector"]), batch_size=args.batch_size,
                expected_point_id_digest=point_id_set_sha256(points), qdrant_run_id=qdrant_run_id,
            )
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise
        _public_manifest({"transform_schema": "solidstats-memory-transform/v1", "source_inventory_sha256": sha256_file(Path(args.source_inventory_proof)), "oracle_version": "3.5.0", "oracle_revision": "v3.5.0", "mapping_contract_sha256": sha256_file(Path(args.mapping_contract)), "collection_derivation_sha256": sha256_bytes(canonical_json_bytes(derivation)), "source_vector_contract": "v3.5.0-source-cosine", "target_vector_contract": "qdrant-cosine", "vector_strategy": strategy.strategy, "vector_strategy_reason": strategy.reason, "model_artifact_sha256": strategy.model_artifact_sha256, "point_count": len(points), "source_id_set_sha256": sha256_bytes(canonical_json_bytes(sorted(item["source_id"] for item in mappings))), "point_id_set_sha256": point_id_set_sha256(points), "bundle_sha256": bundle_digest, "qdrant_image": pinned_qdrant_image, "qdrant_run_id": qdrant_run_id, "empty_target_proof": result["empty_target_proof"], "import_result": result, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        print("PASS: private bundle imported into loopback Qdrant")
        return 0
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
