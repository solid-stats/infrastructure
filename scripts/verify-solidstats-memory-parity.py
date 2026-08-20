#!/usr/bin/env python3
"""Verify a private, isolated SolidStats memory transform without value logs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
from typing import Iterable, Mapping, Sequence
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
UUID_NAMESPACE = uuid.UUID("c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_RECORDS = 1_000_000
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_TOP_K = 100
PRIVATE_REPORT_KEYS = {"document", "metadata", "vector", "query", "id", "path", "url", "token", "secret"}


class ParityFailure(ValueError):
    """A value-free parity validation failure."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str, *, max_bytes: int = MAX_RESPONSE_BYTES) -> Path:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path.stat().st_size > max_bytes:
            raise OSError
        return path.resolve(strict=True)
    except OSError as error:
        raise ParityFailure(f"{label} provenance is unsafe") from error


def _contained_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ParityFailure(f"{label} provenance is unsafe")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ParityFailure(f"{label} provenance is unsafe")
    resolved = _regular_file(root / candidate, label)
    if root.resolve(strict=True) not in (resolved, *resolved.parents):
        raise ParityFailure(f"{label} provenance is unsafe")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, object]:
    safe = _regular_file(path, label)
    try:
        parsed = json.loads(safe.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParityFailure(f"{label} provenance is invalid") from error
    if not isinstance(parsed, dict):
        raise ParityFailure(f"{label} provenance is invalid")
    return parsed


def _load_bundle_contract() -> object:
    source = ROOT / "scripts" / "build-solidstats-memory-bundle.py"
    spec = importlib.util.spec_from_file_location("solidstats_bundle", source)
    if not spec or not spec.loader:
        raise ParityFailure("mapping contract provenance is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_provenance(inventory_proof: Path, mapping_contract: Path, transform_manifest: Path) -> dict[str, object]:
    """Validate both current byte digests before private or target access."""
    proof = _regular_file(inventory_proof, "source inventory proof")
    contract_path = _regular_file(mapping_contract, "mapping contract")
    manifest = _load_json(transform_manifest, "transform manifest")
    if manifest.get("transform_schema") != "solidstats-memory-transform/v1":
        raise ParityFailure("transform manifest provenance is invalid")
    expected_proof = manifest.get("source_inventory_sha256")
    expected_contract = manifest.get("mapping_contract_sha256")
    if not isinstance(expected_proof, str) or not SHA256.fullmatch(expected_proof) or not isinstance(expected_contract, str) or not SHA256.fullmatch(expected_contract):
        raise ParityFailure("transform manifest provenance is incomplete")
    try:
        bundle = _load_bundle_contract()
        bundle.load_approved_mapping_contract(proof, contract_path)
    except (AttributeError, ValueError, OSError) as error:
        raise ParityFailure("mapping contract provenance is invalid") from error
    proof_digest = sha256_file(proof)
    contract_digest = sha256_file(contract_path)
    if proof_digest != expected_proof or contract_digest != expected_contract:
        raise ParityFailure("transform provenance digest mismatch")
    return {
        "source_inventory_sha256": proof_digest,
        "mapping_contract_sha256": contract_digest,
        "transform_manifest_sha256": sha256_file(_regular_file(transform_manifest, "transform manifest")),
        "transform": manifest,
    }


def _loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.path not in ("", "/"):
        raise ParityFailure("isolated target is invalid")
    return value.rstrip("/")


def _qdrant_request(base_url: str, method: str, path: str, body: object | None = None) -> dict[str, object]:
    request = Request(f"{base_url}{path}", data=canonical_json_bytes(body) if body is not None else None, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OSError
        decoded = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ParityFailure("isolated target request failed") from error
    if not isinstance(decoded, dict) or decoded.get("status") not in ("ok", "completed"):
        raise ParityFailure("isolated target response is invalid")
    return decoded


def _vector_bytes(vector: object) -> bytes:
    if not isinstance(vector, list) or not vector:
        raise ParityFailure("vector evidence is invalid")
    try:
        return b"".join(struct.pack("!f", float(value)) for value in vector)
    except (TypeError, ValueError, OverflowError) as error:
        raise ParityFailure("vector evidence is invalid") from error


def _source_metadata(payload: Mapping[str, object]) -> Mapping[str, object]:
    metadata = payload.get("metadata")
    nested = metadata.get("_solidstats_migration") if isinstance(metadata, dict) else None
    source = nested.get("source_metadata") if isinstance(nested, dict) else None
    if not isinstance(source, dict):
        raise ParityFailure("bundle field evidence is invalid")
    return source


def _source_record(record: Mapping[str, object]) -> tuple[str, bytes, bytes, object]:
    """Accept synthetic direct records and private bundle point records."""
    payload = record.get("payload")
    if isinstance(payload, dict):
        source_id = payload.get("mempalace_id")
        document = payload.get("document")
        metadata = _source_metadata(payload)
    else:
        source_id = record.get("id")
        document = record.get("document")
        metadata = record.get("metadata")
    if not isinstance(source_id, str) or not isinstance(document, str) or not isinstance(metadata, dict):
        raise ParityFailure("bundle field evidence is invalid")
    return source_id, document.encode("utf-8"), canonical_json_bytes(metadata), record.get("vector")


def compare_id_bijection(source: Sequence[Mapping[str, object]], target: Sequence[Mapping[str, object]]) -> dict[str, int]:
    expected: dict[str, str] = {}
    for point in source:
        payload = point.get("payload")
        source_id = payload.get("mempalace_id") if isinstance(payload, dict) else None
        point_id = point.get("id")
        if not isinstance(source_id, str) or not source_id or not isinstance(point_id, str):
            raise ParityFailure("bundle identity evidence is invalid")
        expected[source_id] = str(point_id)
    observed: dict[str, str] = {}
    failures = 0
    for point in target:
        payload = point.get("payload")
        source_id = payload.get("mempalace_id") if isinstance(payload, dict) else None
        point_id = point.get("id")
        if not isinstance(source_id, str) or not isinstance(point_id, str):
            failures += 1
            continue
        if str(uuid.uuid5(UUID_NAMESPACE, source_id)) != str(point_id) or source_id in observed:
            failures += 1
            continue
        observed[source_id] = str(point_id)
    failures += int(expected != observed)
    return {"compared": len(expected), "failures": failures}


def compare_documents_metadata_timestamps(source: Sequence[Mapping[str, object]], target: Sequence[Mapping[str, object]]) -> dict[str, int]:
    expected: dict[str, tuple[bytes, bytes]] = {}
    for point in source:
        source_id, document, metadata, _vector = _source_record(point)
        expected[source_id] = (document, metadata)
    failures = 0
    for point in target:
        payload = point.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("mempalace_id"), str) or not isinstance(payload.get("document"), str):
            failures += 1
            continue
        record = expected.get(payload["mempalace_id"])
        if record is None or record[0] != payload["document"].encode("utf-8"):
            failures += 1
            continue
        try:
            metadata = _source_metadata(payload) if isinstance(payload.get("metadata", {}).get("_solidstats_migration") if isinstance(payload.get("metadata"), dict) else None, dict) else payload.get("metadata")
            if not isinstance(metadata, dict) or record[1] != canonical_json_bytes(metadata):
                failures += 1
        except ParityFailure:
            failures += 1
    return {"compared": len(expected), "failures": failures}


def compare_vectors(source: Sequence[Mapping[str, object]], target: Sequence[Mapping[str, object]], *, strategy: str, dimension: int, metric: str) -> dict[str, int]:
    if strategy not in {"reuse", "reembed"} or not isinstance(dimension, int) or dimension < 1 or metric != "Cosine":
        raise ParityFailure("vector contract is invalid")
    expected = {
        str(point.get("id")) if isinstance(point.get("payload"), dict) else str(uuid.uuid5(UUID_NAMESPACE, _source_record(point)[0])): _vector_bytes(_source_record(point)[3])
        for point in source
    }
    failures = 0
    for point in target:
        point_id = str(point.get("id"))
        vector = _vector_bytes(point.get("vector"))
        if point_id not in expected or len(vector) != dimension * 4 or (strategy == "reuse" and vector != expected[point_id]):
            failures += 1
    return {"compared": len(expected), "failures": failures}


def derive_source_distance_rule(repeat_runs: Sequence[Sequence[tuple[str, float]]], *, serialization_floor: float) -> dict[str, object]:
    if len(repeat_runs) < 3 or serialization_floor <= 0:
        raise ParityFailure("source repeatability evidence is invalid")
    baseline = list(repeat_runs[0])
    if not baseline or any(not isinstance(item[0], str) for item in baseline):
        raise ParityFailure("source repeatability evidence is invalid")
    for run in repeat_runs[1:]:
        if list(run) != baseline:
            raise ParityFailure("source ranking is unstable")
    return {"kind": "source-repeatability-plus-serialization-floor", "max_distance_delta": serialization_floor, "source_runs": len(repeat_runs)}


def compare_recall_rankings(source: Sequence[tuple[str, float]], target: Sequence[tuple[str, float]], rule: Mapping[str, object]) -> dict[str, int]:
    tolerance = rule.get("max_distance_delta")
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ParityFailure("distance rule is invalid")
    failures = int(len(source) != len(target))
    for expected, observed in zip(source, target):
        if expected[0] != observed[0] or abs(expected[1] - observed[1]) > tolerance:
            failures += 1
    return {"compared": len(source), "failures": failures}


def _scroll_points(base_url: str, collection: str, expected_count: int) -> list[dict[str, object]]:
    if not 0 < expected_count <= MAX_RECORDS:
        raise ParityFailure("target count is invalid")
    points: list[dict[str, object]] = []
    offset: object | None = None
    while True:
        body: dict[str, object] = {"limit": min(1000, expected_count), "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        result = _qdrant_request(base_url, "POST", f"/collections/{quote(collection, safe='')}/points/scroll", body).get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise ParityFailure("target response is invalid")
        points.extend(point for point in result["points"] if isinstance(point, dict))
        if len(points) > expected_count:
            raise ParityFailure("target response exceeds bounds")
        offset = result.get("next_page_offset")
        if offset is None:
            break
    if len(points) != expected_count:
        raise ParityFailure("target count mismatch")
    return points


def _safe_report(payload: Mapping[str, object]) -> None:
    serialized = canonical_json_bytes(payload).decode("utf-8").lower()
    if any(key in serialized for key in PRIVATE_REPORT_KEYS):
        raise ParityFailure("report privacy validation failed")


def write_parity_report(path: Path, payload: Mapping[str, object]) -> None:
    allowed = {"parity_schema", "verdict", "source_inventory_sha256", "mapping_contract_sha256", "transform_manifest_sha256", "bundle_sha256", "oracle_version", "oracle_revision", "qdrant_image", "qdrant_run_id", "target_collection_derivation_sha256", "vector_strategy", "field_parity", "id_parity", "vector_parity", "recall_parity", "bounds", "created_at"}
    if set(payload) - allowed:
        raise ParityFailure("report schema is invalid")
    _safe_report(payload)
    target = path.resolve().with_suffix(".tmp")
    target.write_bytes(canonical_json_bytes(payload) + b"\n")
    os.replace(target, path)


def write_phase21_handoff(path: Path, payload: Mapping[str, object]) -> None:
    allowed = {"handoff_schema", "source_inventory_sha256", "mapping_contract_sha256", "parity_report_sha256", "bundle_manifest_sha256", "bundle_file_digests", "oracle_version", "oracle_revision", "qdrant_image", "target_collection_derivation_sha256", "target_vector_contract", "vector_strategy", "record_count", "phase21_required_checks"}
    if set(payload) - allowed:
        raise ParityFailure("handoff schema is invalid")
    _safe_report(payload)
    temporary = path.resolve().with_suffix(".tmp")
    temporary.write_bytes(canonical_json_bytes(payload) + b"\n")
    os.replace(temporary, path)


def cleanup_isolated_target(*, handoff: Mapping[str, object], expected_run_id: str, collection: str, container: str, data_dir: Path, private_root: Path, retained_roots: Sequence[Path], qdrant_url: str) -> None:
    if handoff.get("verdict") != "pass" or handoff.get("qdrant_run_id") != expected_run_id:
        raise ParityFailure("cleanup requires passing handoff")
    root = private_root.resolve(strict=True)
    runtime = data_dir.resolve(strict=True)
    if root not in (runtime, *runtime.parents) or any(runtime == item.resolve(strict=True) or item.resolve(strict=True) in runtime.parents for item in retained_roots):
        raise ParityFailure("cleanup overlaps retained evidence")
    if not container or not collection:
        raise ParityFailure("cleanup target is invalid")
    inspect = subprocess.run(["docker", "inspect", "--format", "{{index .Config.Labels \"solidstats.plan\"}}", container], capture_output=True, text=True, timeout=20, check=False)
    if inspect.returncode != 0 or inspect.stdout.strip() != "20-05":
        raise ParityFailure("cleanup container is not run-bound")
    _qdrant_request(_loopback_url(qdrant_url), "DELETE", f"/collections/{quote(collection, safe='')}")
    removed = subprocess.run(["docker", "rm", "-f", container], capture_output=True, text=True, timeout=20, check=False)
    if removed.returncode != 0:
        raise ParityFailure("cleanup container removal failed")
    shutil.rmtree(runtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inventory", "source-inventory-proof", "mapping-contract", "transform-manifest", "bundle-dir", "recall-fixtures", "oracle-python", "oracle-source-dir", "qdrant-url", "qdrant-container", "qdrant-data-dir", "output", "handoff-output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--source-repeat-runs", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--cleanup-after-pass", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.top_k <= MAX_TOP_K or args.source_repeat_runs < 3:
            raise ParityFailure("parity bounds are invalid")
        provenance = validate_provenance(Path(args.source_inventory_proof), Path(args.mapping_contract), Path(args.transform_manifest))
        _regular_file(Path(args.inventory), "private inventory")
        bundle_dir = Path(args.bundle_dir).resolve(strict=True)
        manifest = _load_json(_contained_file(bundle_dir, "bundle-manifest.json", "bundle manifest"), "bundle manifest")
        if args.check_only:
            print("PASS: parity provenance validated")
            return 0
        raise ParityFailure("real parity requires the exact v3.5.0 oracle runner")
    except (OSError, ParityFailure) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
