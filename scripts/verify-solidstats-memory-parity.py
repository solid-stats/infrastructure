#!/usr/bin/env python3
"""Verify a private, isolated SolidStats memory transform without value logs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import struct
import subprocess
import sys
import tempfile
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
PINNED_QDRANT_IMAGE = re.compile(r"^ghcr\.io/qdrant/qdrant/qdrant:v1\.19\.0-unprivileged@sha256:[0-9a-f]{64}$")
SAFE_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SOURCE_QUERY_PROGRAM = r"""
import argparse, hashlib, importlib.metadata, json, sys
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--oracle-root', required=True)
parser.add_argument('--palace-path', required=True)
parser.add_argument('--collection-name', required=True)
parser.add_argument('--fixtures', required=True)
parser.add_argument('--eligible-wings', required=True)
parser.add_argument('--excluded-indices', required=True)
args = parser.parse_args()
root = Path(args.oracle_root).resolve()
sys.path.insert(0, str(root))
import mempalace, chromadb
if importlib.metadata.version('mempalace') != '3.5.0' or root not in Path(mempalace.__file__).resolve().parents:
    raise RuntimeError('unapproved oracle')
fixtures = json.loads(Path(args.fixtures).read_text(encoding='utf-8'))
eligible_wings = json.loads(args.eligible_wings)
excluded_indices = set(json.loads(args.excluded_indices))
if not isinstance(eligible_wings, list) or not eligible_wings or not all(isinstance(wing, str) and wing for wing in eligible_wings) or not all(isinstance(index, int) for index in excluded_indices):
    raise RuntimeError('invalid eligible source scope')
from mempalace.backends.chroma import ChromaCollection
client = chromadb.PersistentClient(path=args.palace_path)
raw = client.get_collection(args.collection_name)
collection = ChromaCollection(raw, palace_path=args.palace_path)
count = collection.count()
by_digest = {}
for offset in range(0, count, 1000):
    page = collection.get(limit=1000, offset=offset, include=['embeddings'])
    for source_id, vector in zip(page.ids, page.embeddings or [], strict=True):
        by_digest[hashlib.sha256(source_id.encode('utf-8')).hexdigest()] = vector
for index, fixture in enumerate(fixtures):
    if index in excluded_indices:
        print(json.dumps({'index': index, 'excluded': True}, separators=(',', ':'), sort_keys=True), flush=True)
        continue
    vector = by_digest.get(fixture['query_record_digest'])
    if vector is None:
        raise RuntimeError('query digest did not resolve')
    filters = fixture['filters']
    eligible_filter = {'wing': {'$in': eligible_wings}}
    where = eligible_filter if not filters else {'$and': [eligible_filter, filters]}
    result = collection.query(query_embeddings=[vector], n_results=fixture['top_k'], where=where, include=['distances'])
    ranked = sorted(zip(result.ids[0], result.distances[0], strict=True), key=lambda item: (item[1], item[0]))
    print(json.dumps({'index': index, 'vector': vector, 'ranked': ranked}, separators=(',', ':'), sort_keys=True), flush=True)
"""


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


def _contained_file(root: Path, value: object, label: str, *, max_bytes: int = MAX_RESPONSE_BYTES) -> Path:
    if not isinstance(value, str) or not value:
        raise ParityFailure(f"{label} provenance is unsafe")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ParityFailure(f"{label} provenance is unsafe")
    resolved = _regular_file(root / candidate, label, max_bytes=max_bytes)
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
    if any(not isinstance(item[0], str) for item in baseline):
        raise ParityFailure("source repeatability evidence is invalid")
    worst_delta = 0.0
    for run in repeat_runs[1:]:
        if len(run) != len(baseline) or [item[0] for item in run] != [item[0] for item in baseline]:
            raise ParityFailure("source ranking is unstable")
        for previous, current in zip(baseline, run, strict=True):
            if not isinstance(current[1], (int, float)):
                raise ParityFailure("source repeatability evidence is invalid")
            worst_delta = max(worst_delta, abs(float(previous[1]) - float(current[1])))
    return {
        "kind": "source-repeatability-plus-serialization-floor",
        "max_distance_delta": max(worst_delta, float(serialization_floor)),
        "source_runs": len(repeat_runs),
    }


def compare_recall_rankings(source: Sequence[tuple[str, float]], target: Sequence[tuple[str, float]], rule: Mapping[str, object]) -> dict[str, int]:
    tolerance = rule.get("max_distance_delta")
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ParityFailure("distance rule is invalid")
    failures = int(len(source) != len(target))
    for expected, observed in zip(source, target):
        if expected[0] != observed[0] or abs(expected[1] - observed[1]) > tolerance:
            failures += 1
    return {"compared": len(source), "failures": failures}


def _scroll_points(base_url: str, collection: str, expected_count: int) -> Iterable[dict[str, object]]:
    if not 0 < expected_count <= MAX_RECORDS:
        raise ParityFailure("target count is invalid")
    observed = 0
    offset: object | None = None
    while True:
        body: dict[str, object] = {"limit": min(1000, expected_count), "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        result = _qdrant_request(base_url, "POST", f"/collections/{quote(collection, safe='')}/points/scroll", body).get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise ParityFailure("target response is invalid")
        for point in result["points"]:
            if not isinstance(point, dict):
                raise ParityFailure("target response is invalid")
            observed += 1
            if observed > expected_count:
                raise ParityFailure("target response exceeds bounds")
            yield point
        offset = result.get("next_page_offset")
        if offset is None:
            break
    if observed != expected_count:
        raise ParityFailure("target count mismatch")


def _safe_digest(value: object) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ParityFailure("public proof is invalid")
    return value


def _safe_public_value(value: object, *, key: str = "") -> None:
    """Allow only aggregate proof types; never infer privacy from safe schema keys."""
    forbidden = {"document", "metadata", "vector", "query", "source_id", "mempalace_id", "path", "url", "token", "secret", "filters"}
    if key in forbidden:
        raise ParityFailure("report privacy validation failed")
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str) or not SAFE_ARTIFACT_NAME.fullmatch(child_key):
                raise ParityFailure("report privacy validation failed")
            _safe_public_value(child_value, key=child_key)
        return
    if isinstance(value, list):
        for child in value:
            _safe_public_value(child, key=key)
        return
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return
    if not isinstance(value, str) or "\\" in value or value.startswith("/") or re.search(r"(?:sk-|bearer\s|password=)", value, re.IGNORECASE):
        raise ParityFailure("report privacy validation failed")


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ParityFailure("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json_bytes(payload) + b"\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _validate_result_summary(value: object, *, recall: bool = False) -> None:
    if not isinstance(value, Mapping):
        raise ParityFailure("report schema is invalid")
    allowed = {"compared", "failures"}
    if recall:
        allowed |= {"excluded_fixtures", "source_repeat_runs", "rule", "worst_safe_delta"}
    if set(value) - allowed or not {"compared", "failures"} <= set(value):
        raise ParityFailure("report schema is invalid")
    if any(isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float)) or value.get(key) < 0 for key in ("compared", "failures")):
        raise ParityFailure("report schema is invalid")
    if recall and (not isinstance(value.get("excluded_fixtures"), int) or value["excluded_fixtures"] < 0 or value.get("rule") != "source-repeatability-plus-serialization-floor" or not isinstance(value.get("source_repeat_runs"), int) or value["source_repeat_runs"] < 3 or not isinstance(value.get("worst_safe_delta"), (int, float)) or value["worst_safe_delta"] < 0):
        raise ParityFailure("report schema is invalid")


def write_parity_report(path: Path, payload: Mapping[str, object]) -> None:
    allowed = {"parity_schema", "verdict", "source_inventory_sha256", "mapping_contract_sha256", "transform_manifest_sha256", "bundle_sha256", "oracle_version", "oracle_revision", "qdrant_image", "qdrant_run_id", "target_collection_derivation_sha256", "vector_strategy", "field_parity", "id_parity", "vector_parity", "recall_parity", "exclusion_parity", "bounds", "created_at"}
    required = allowed - {"created_at"}
    if set(payload) - allowed or not required <= set(payload) or payload.get("parity_schema") != "solidstats-memory-parity/v1" or payload.get("verdict") not in {"pass", "fail"}:
        raise ParityFailure("report schema is invalid")
    _safe_public_value(payload)
    if not PINNED_QDRANT_IMAGE.fullmatch(str(payload.get("qdrant_image"))) or payload.get("oracle_version") != "3.5.0" or payload.get("oracle_revision") != "v3.5.0" or payload.get("vector_strategy") not in {"reuse", "reembed"} or not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("qdrant_run_id"))):
        raise ParityFailure("report schema is invalid")
    for key in ("source_inventory_sha256", "mapping_contract_sha256", "transform_manifest_sha256", "bundle_sha256", "target_collection_derivation_sha256"):
        _safe_digest(payload.get(key))
    for key in ("field_parity", "id_parity", "vector_parity"):
        _validate_result_summary(payload.get(key))
    _validate_result_summary(payload.get("recall_parity"), recall=True)
    exclusion = payload.get("exclusion_parity")
    if not isinstance(exclusion, Mapping) or set(exclusion) != {"excluded_records", "failures"} or not isinstance(exclusion.get("excluded_records"), int) or exclusion["excluded_records"] < 0 or exclusion.get("failures") != 0:
        raise ParityFailure("report schema is invalid")
    if payload.get("bounds") != {"max_records": MAX_RECORDS, "max_response_bytes": MAX_RESPONSE_BYTES, "max_top_k": MAX_TOP_K} or not isinstance(payload.get("created_at"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(payload["created_at"])):
        raise ParityFailure("report schema is invalid")
    _atomic_json(path, payload)


def write_phase21_handoff(path: Path, payload: Mapping[str, object]) -> None:
    allowed = {"handoff_schema", "source_inventory_sha256", "mapping_contract_sha256", "parity_report_sha256", "bundle_manifest_sha256", "bundle_file_digests", "oracle_version", "oracle_revision", "qdrant_image", "target_collection_derivation_sha256", "target_vector_contract", "vector_strategy", "record_count", "phase21_required_checks"}
    if set(payload) != allowed or payload.get("handoff_schema") != "solidstats-memory-phase21-handoff/v1":
        raise ParityFailure("handoff schema is invalid")
    _safe_public_value(payload)
    if payload.get("oracle_version") != "3.5.0" or payload.get("oracle_revision") != "v3.5.0" or not PINNED_QDRANT_IMAGE.fullmatch(str(payload.get("qdrant_image"))) or payload.get("target_vector_contract") != "qdrant-cosine" or payload.get("vector_strategy") not in {"reuse", "reembed"}:
        raise ParityFailure("handoff schema is invalid")
    for key in ("source_inventory_sha256", "mapping_contract_sha256", "parity_report_sha256", "bundle_manifest_sha256", "target_collection_derivation_sha256"):
        _safe_digest(payload.get(key))
    file_digests = payload.get("bundle_file_digests")
    if not isinstance(file_digests, Mapping) or not file_digests or any(not isinstance(name, str) or not SAFE_ARTIFACT_NAME.fullmatch(name) for name in file_digests):
        raise ParityFailure("handoff schema is invalid")
    for digest in file_digests.values():
        _safe_digest(digest)
    if file_digests.get("bundle-manifest.json") != payload.get("bundle_manifest_sha256") or not isinstance(payload.get("record_count"), int) or payload["record_count"] < 1 or payload.get("phase21_required_checks") != ["recompute-provenance-digests", "verify-pinned-oracle-and-image", "verify-retained-bundle-digests", "perform-live-restore-only-in-phase-21"]:
        raise ParityFailure("handoff schema is invalid")
    _atomic_json(path, payload)


def map_fixture_filters(filters: Mapping[str, object], contract: Mapping[str, object]) -> dict[str, object]:
    """Map only approved source wing filters; room/archive fields are preserved."""
    if not isinstance(filters, Mapping) or any(key not in {"wing", "room", "archive_state"} for key in filters):
        raise ParityFailure("fixture filter is invalid")
    routing = contract.get("source_wing_to_target_wing")
    if not isinstance(routing, Mapping):
        raise ParityFailure("mapping contract routing is invalid")
    routes = routing.get("canonical_repository_rules")
    shared = routing.get("shared_source_rule")
    if not isinstance(routes, Mapping) or not isinstance(shared, Mapping):
        raise ParityFailure("mapping contract routing is invalid")
    mapped = dict(filters)
    wing = mapped.get("wing")
    if wing is not None:
        target = routes.get(wing) if isinstance(wing, str) else None
        target = target if isinstance(target, str) else shared.get(wing) if isinstance(wing, str) else None
        if not isinstance(target, str) or not target:
            raise ParityFailure("fixture wing is unbound")
        mapped["wing"] = target
    return mapped


def _approved_source_wings(contract: Mapping[str, object]) -> tuple[str, ...]:
    routing = contract.get("source_wing_to_target_wing")
    routes = routing.get("canonical_repository_rules") if isinstance(routing, Mapping) else None
    shared = routing.get("shared_source_rule") if isinstance(routing, Mapping) else None
    if not isinstance(routes, Mapping) or not isinstance(shared, Mapping):
        raise ParityFailure("mapping contract routing is invalid")
    wings = sorted({*routes.keys(), *shared.keys()})
    if not wings or any(not isinstance(wing, str) or not wing for wing in wings):
        raise ParityFailure("mapping contract routing is invalid")
    return tuple(wings)


def classify_fixture(fixture: Mapping[str, object], contract: Mapping[str, object], source_proof: Mapping[str, object]) -> str:
    """Accept only evidence-bound Agent/other-wing exclusions from the approved contract."""
    filters = fixture.get("filters")
    if not isinstance(filters, Mapping):
        raise ParityFailure("recall fixtures are invalid")
    wing = filters.get("wing")
    if wing is None or wing in _approved_source_wings(contract):
        return "eligible"
    if not isinstance(wing, str) or not wing or wing.endswith("-archive"):
        raise ParityFailure("fixture wing is unbound")
    routing = contract.get("source_wing_to_target_wing")
    excluded_rule = routing.get("excluded_source_rule") if isinstance(routing, Mapping) else None
    labels = source_proof.get("source_label_observation_counts")
    wing_observation = labels.get("wing") if isinstance(labels, Mapping) else None
    other_count = wing_observation.get("other_string") if isinstance(wing_observation, Mapping) else None
    suffix_count = wing_observation.get("suffix_marked") if isinstance(wing_observation, Mapping) else None
    if not isinstance(excluded_rule, str) or "Agent and other-wing" not in excluded_rule or not isinstance(other_count, int) or other_count < 1 or suffix_count != 0:
        raise ParityFailure("fixture wing is unbound")
    return "excluded"


def validate_exclusion_reconciliation(source_proof: Mapping[str, object], private_inventory: Mapping[str, object], bundle_manifest: Mapping[str, object], transform: Mapping[str, object]) -> int:
    counts = source_proof.get("counts")
    source_total = counts.get("source_records") if isinstance(counts, Mapping) else None
    private_total = private_inventory.get("record_count")
    bundle_total = bundle_manifest.get("point_count")
    excluded = bundle_manifest.get("excluded_count")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (source_total, private_total, bundle_total, excluded)) or private_total != source_total or bundle_total != transform.get("point_count") or source_total != bundle_total + excluded:
        raise ParityFailure("source bundle exclusion reconciliation is invalid")
    return excluded


def validate_container_attestation(container: str, transform: Mapping[str, object]) -> None:
    if not isinstance(container, str) or not container or not PINNED_QDRANT_IMAGE.fullmatch(str(transform.get("qdrant_image"))):
        raise ParityFailure("isolated target identity is invalid")
    expected_run = transform.get("qdrant_run_id")
    if not isinstance(expected_run, str) or not expected_run:
        raise ParityFailure("isolated target identity is invalid")
    inspected = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, timeout=20, check=False)
    try:
        values = json.loads(inspected.stdout)
        value = values[0] if inspected.returncode == 0 and isinstance(values, list) and len(values) == 1 and isinstance(values[0], dict) else None
        config = value.get("Config") if isinstance(value, dict) else None
        host = value.get("HostConfig") if isinstance(value, dict) else None
        labels = config.get("Labels") if isinstance(config, dict) else None
        bindings = host.get("PortBindings") if isinstance(host, dict) else None
        port = bindings.get("6333/tcp") if isinstance(bindings, dict) else None
        binding = port[0] if isinstance(port, list) and len(port) == 1 else None
    except (json.JSONDecodeError, TypeError, KeyError, IndexError) as error:
        raise ParityFailure("isolated target identity is invalid") from error
    if not isinstance(config, dict) or config.get("Image") != transform["qdrant_image"] or not isinstance(labels, dict) or labels.get("solidstats.plan") != "20-05" or labels.get("solidstats.qdrant-run-id") != expected_run:
        raise ParityFailure("isolated target is not run-bound")
    if not isinstance(binding, dict) or binding.get("HostIp") != "127.0.0.1" or binding.get("HostPort") != "6333":
        raise ParityFailure("isolated target is not loopback-bound")


def _load_fixture_list(path: Path) -> list[dict[str, object]]:
    safe = _regular_file(path, "recall fixtures", max_bytes=MAX_RESPONSE_BYTES)
    try:
        fixtures = json.loads(safe.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParityFailure("recall fixtures are invalid") from error
    if not isinstance(fixtures, list) or not fixtures or len(fixtures) > MAX_RECORDS:
        raise ParityFailure("recall fixtures are invalid")
    checked: list[dict[str, object]] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != {"filters", "query_record_digest", "source_distances", "source_metric", "source_ordered_ids", "source_runs", "top_k"}:
            raise ParityFailure("recall fixtures are invalid")
        if not isinstance(fixture["filters"], dict) or not SHA256.fullmatch(str(fixture["query_record_digest"])) or fixture["source_metric"] != "cosine-distance" or not isinstance(fixture["top_k"], int) or not 0 < fixture["top_k"] <= MAX_TOP_K:
            raise ParityFailure("recall fixtures are invalid")
        if not isinstance(fixture["source_runs"], int) or fixture["source_runs"] < 2 or not isinstance(fixture["source_ordered_ids"], list) or not isinstance(fixture["source_distances"], list) or len(fixture["source_ordered_ids"]) != len(fixture["source_distances"]) or len(fixture["source_ordered_ids"]) > fixture["top_k"]:
            raise ParityFailure("recall fixtures are invalid")
        if any(not isinstance(source_id, str) or not source_id for source_id in fixture["source_ordered_ids"]) or len(set(fixture["source_ordered_ids"])) != len(fixture["source_ordered_ids"]) or any(isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance) for distance in fixture["source_distances"]):
            raise ParityFailure("recall fixtures are invalid")
        checked.append(fixture)
    return checked


def validate_fixture_provenance(fixtures_path: Path, inventory_proof: Path) -> None:
    proof = _load_json(inventory_proof, "source inventory proof")
    expected = proof.get("recall_fixtures_sha256")
    if not isinstance(expected, str) or not SHA256.fullmatch(expected) or sha256_file(_regular_file(fixtures_path, "recall fixtures")) != expected:
        raise ParityFailure("recall fixture provenance is invalid")


def _load_inventory_contract() -> object:
    source = ROOT / "scripts" / "inventory-solidstats-memory.py"
    spec = importlib.util.spec_from_file_location("solidstats_inventory", source)
    if not spec or not spec.loader:
        raise ParityFailure("source oracle is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _derive_collection(snapshot_dir: Path, oracle_python: Path, oracle_source_dir: Path) -> dict[str, str]:
    bundle = _load_bundle_contract()
    try:
        palace_id, namespace, collection, _embedder = bundle._snapshot_identity(snapshot_dir)
        return bundle.derive_collection_with_oracle(oracle_python, oracle_source_dir, palace_id, namespace, collection)
    except (AttributeError, OSError, ValueError) as error:
        raise ParityFailure("target collection derivation failed") from error


def parse_source_oracle_rows(stdout: str) -> list[dict[str, object]]:
    """Accept exactly one non-overlapping row form for each source fixture."""
    rows: list[dict[str, object]] = []
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ParityFailure("source oracle protocol is invalid") from error
        if not isinstance(row, dict) or not isinstance(row.get("index"), int) or row["index"] < 0:
            raise ParityFailure("source oracle protocol is invalid")
        if set(row) == {"index", "excluded"} and row.get("excluded") is True:
            rows.append(row)
            continue
        if set(row) != {"index", "vector", "ranked"} or not isinstance(row.get("vector"), list) or not isinstance(row.get("ranked"), list):
            raise ParityFailure("source oracle protocol is invalid")
        _vector_bytes(row["vector"])
        ranked = row["ranked"]
        if any(not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str) or not item[0] or isinstance(item[1], bool) or not isinstance(item[1], (int, float)) or not math.isfinite(item[1]) for item in ranked):
            raise ParityFailure("source oracle protocol is invalid")
        rows.append(row)
    return rows


def _run_source_queries(*, snapshot_dir: Path, fixtures_path: Path, oracle_python: Path, oracle_source_dir: Path, eligible_wings: Sequence[str], excluded_indices: Sequence[int]) -> list[dict[str, object]]:
    inventory = _load_inventory_contract()
    try:
        _policy, limits = inventory.load_policy(inventory.DEFAULT_POLICY)
        root = inventory._require_directory(snapshot_dir, label="snapshot")
        inventory._assert_safe_tree(root, label="snapshot")
        contract = inventory._load_snapshot_contract(root, limits)
        oracle_root, _oracle = inventory._validate_oracle(oracle_source_dir)
        palace_root = contract["palace_root"]
        if not isinstance(palace_root, Path):
            raise ValueError
        python = inventory._resolve_oracle_python(oracle_python)
    except (AttributeError, OSError, ValueError) as error:
        raise ParityFailure("source oracle is invalid") from error
    with tempfile.TemporaryDirectory(prefix="solidstats-memory-parity-") as temporary:
        scratch = Path(temporary) / "palace"
        try:
            shutil.copytree(palace_root, scratch, symlinks=True)
            inventory._normalize_oracle_scratch_modes(scratch)
            inventory._assert_safe_tree(scratch, label="oracle scratch")
            result = subprocess.run([str(python), "-I", "-c", SOURCE_QUERY_PROGRAM, "--oracle-root", str(oracle_root), "--palace-path", str(scratch), "--collection-name", str(contract["collection_name"]), "--fixtures", str(fixtures_path), "--eligible-wings", json.dumps(list(eligible_wings)), "--excluded-indices", json.dumps(list(excluded_indices))], capture_output=True, text=True, timeout=300, check=False, env={"HOME": "/nonexistent", "PATH": os.defpath, "PYTHONNOUSERSITE": "1"})
        except (OSError, subprocess.TimeoutExpired, shutil.Error) as error:
            raise ParityFailure("source oracle failed") from error
    if result.returncode != 0:
        raise ParityFailure("source oracle failed")
    return parse_source_oracle_rows(result.stdout)


def _target_query(base_url: str, collection: str, vector: object, filters: Mapping[str, object], top_k: int) -> list[tuple[str, float]]:
    conditions = [{"key": f"metadata.{key}", "match": {"value": value}} for key, value in filters.items()]
    result = _qdrant_request(base_url, "POST", f"/collections/{quote(collection, safe='')}/points/query", {"query": vector, "filter": {"must": conditions} if conditions else None, "limit": top_k, "with_payload": False, "with_vector": False}).get("result")
    points = result.get("points") if isinstance(result, dict) else None
    if not isinstance(points, list):
        raise ParityFailure("target recall response is invalid")
    ranked: list[tuple[str, float]] = []
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), str) or not isinstance(point.get("score"), (int, float)):
            raise ParityFailure("target recall response is invalid")
        ranked.append((str(point["id"]), 1.0 - float(point["score"])))
    return ranked


def _verify_recall(*, base_url: str, collection: str, fixtures: Sequence[Mapping[str, object]], contract: Mapping[str, object], source_proof: Mapping[str, object], snapshot_dir: Path, fixtures_path: Path, oracle_python: Path, oracle_source_dir: Path, repeats: int) -> dict[str, object]:
    classifications = [classify_fixture(fixture, contract, source_proof) for fixture in fixtures]
    excluded_indices = [index for index, classification in enumerate(classifications) if classification == "excluded"]
    eligible_wings = _approved_source_wings(contract)
    runs = [_run_source_queries(snapshot_dir=snapshot_dir, fixtures_path=fixtures_path, oracle_python=oracle_python, oracle_source_dir=oracle_source_dir, eligible_wings=eligible_wings, excluded_indices=excluded_indices) for _ in range(repeats)]
    if any(len(run) != len(fixtures) for run in runs):
        raise ParityFailure("source oracle fixture count is invalid")
    compared = failures = 0
    worst_delta = 0.0
    for index, fixture in enumerate(fixtures):
        if classifications[index] == "excluded":
            if any(run[index] != {"index": index, "excluded": True} for run in runs):
                raise ParityFailure("source oracle exclusion protocol is invalid")
            continue
        source_runs: list[list[tuple[str, float]]] = []
        source_vectors: list[bytes] = []
        query_vector: object | None = None
        for run in runs:
            row = run[index]
            if row.get("index") != index or not isinstance(row.get("vector"), list):
                raise ParityFailure("source oracle protocol is invalid")
            source_vectors.append(_vector_bytes(row["vector"]))
            if query_vector is None:
                query_vector = row["vector"]
            ranked = row["ranked"]
            if not isinstance(ranked, list):
                raise ParityFailure("source oracle protocol is invalid")
            source_runs.append([(str(item[0]), float(item[1])) for item in ranked if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], (int, float))])
        if any(len(run) != len(source_runs[0]) for run in source_runs):
            raise ParityFailure("source oracle protocol is invalid")
        if any(vector != source_vectors[0] for vector in source_vectors[1:]):
            raise ParityFailure("source query vector is unstable")
        rule = derive_source_distance_rule(source_runs, serialization_floor=2 ** -24)
        expected = source_runs[0]
        target = _target_query(base_url, collection, query_vector, map_fixture_filters(fixture.get("filters", {}), contract), int(fixture["top_k"]))
        normalized = [(str(uuid.uuid5(UUID_NAMESPACE, source_id)), distance) for source_id, distance in expected]
        result = compare_recall_rankings(normalized, target, rule)
        compared += result["compared"]
        failures += result["failures"]
        worst_delta = max(worst_delta, float(rule["max_distance_delta"]))
    if compared == 0:
        raise ParityFailure("recall evidence is non-vacuous")
    return {"compared": compared, "failures": failures, "excluded_fixtures": len(excluded_indices), "source_repeat_runs": repeats, "rule": "source-repeatability-plus-serialization-floor", "worst_safe_delta": worst_delta}


def _stream_field_parity(*, bundle_dir: Path, base_url: str, collection: str, expected_count: int, contract: Mapping[str, object], work_root: Path) -> dict[str, dict[str, int]]:
    points_path = _contained_file(bundle_dir, "points.jsonl", "bundle points", max_bytes=512 * 1024 * 1024)
    if points_path.stat().st_size > 512 * 1024 * 1024:
        raise ParityFailure("bundle points exceed bounds")
    with tempfile.TemporaryDirectory(prefix="solidstats-memory-parity-index-", dir=work_root) as temporary:
        approved_wings = _approved_source_wings(contract)
        database = sqlite3.connect(Path(temporary) / "expected.sqlite3")
        database.execute("CREATE TABLE expected (point_id TEXT PRIMARY KEY, source_id TEXT UNIQUE, field_sha TEXT NOT NULL, vector_sha TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0)")
        count = 0
        with points_path.open(encoding="utf-8") as source:
            for line in source:
                count += 1
                if count > expected_count or len(line.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ParityFailure("bundle points exceed bounds")
                try:
                    point = json.loads(line)
                    source_id, document, metadata, vector = _source_record(point)
                    point_id = point.get("id") if isinstance(point, dict) else None
                    payload = point.get("payload") if isinstance(point, dict) else None
                    target_metadata = payload.get("metadata") if isinstance(payload, dict) else None
                except (json.JSONDecodeError, ParityFailure) as error:
                    raise ParityFailure("bundle field evidence is invalid") from error
                if not isinstance(point_id, str) or point_id != str(uuid.uuid5(UUID_NAMESPACE, source_id)) or not isinstance(target_metadata, dict):
                    raise ParityFailure("bundle identity evidence is invalid")
                source_metadata = json.loads(metadata)
                if source_metadata.get("wing") not in approved_wings:
                    raise ParityFailure("bundle contains excluded source evidence")
                field_sha = hashlib.sha256(canonical_json_bytes({"source_id": source_id, "document": document.decode("utf-8"), "source_metadata": source_metadata, "target_metadata": target_metadata})).hexdigest()
                vector_sha = hashlib.sha256(_vector_bytes(vector)).hexdigest()
                try:
                    database.execute("INSERT INTO expected(point_id, source_id, field_sha, vector_sha) VALUES (?, ?, ?, ?)", (point_id, source_id, field_sha, vector_sha))
                except sqlite3.IntegrityError as error:
                    raise ParityFailure("bundle identity evidence is invalid") from error
        if count != expected_count:
            raise ParityFailure("bundle count mismatch")
        database.commit()
        field_failures = id_failures = vector_failures = 0
        for point in _scroll_points(base_url, collection, expected_count):
            point_id = point.get("id")
            payload = point.get("payload")
            if not isinstance(point_id, str) or not isinstance(payload, dict):
                id_failures += 1
                continue
            row = database.execute("SELECT source_id, field_sha, vector_sha, seen FROM expected WHERE point_id = ?", (point_id,)).fetchone()
            if row is None or row[3]:
                id_failures += 1
                continue
            source_id = payload.get("mempalace_id")
            document = payload.get("document")
            try:
                source_metadata = _source_metadata(payload)
                field_sha = hashlib.sha256(canonical_json_bytes({"source_id": source_id, "document": document, "source_metadata": source_metadata, "target_metadata": payload.get("metadata")})).hexdigest()
                vector_sha = hashlib.sha256(_vector_bytes(point.get("vector"))).hexdigest()
            except ParityFailure:
                field_failures += 1
                continue
            if source_id != row[0] or point_id != str(uuid.uuid5(UUID_NAMESPACE, str(source_id))):
                id_failures += 1
            if field_sha != row[1]:
                field_failures += 1
            if vector_sha != row[2]:
                vector_failures += 1
            database.execute("UPDATE expected SET seen = 1 WHERE point_id = ?", (point_id,))
        missing = database.execute("SELECT COUNT(*) FROM expected WHERE seen = 0").fetchone()[0]
        database.close()
    return {"field_parity": {"compared": expected_count, "failures": field_failures + int(missing)}, "id_parity": {"compared": expected_count, "failures": id_failures + int(missing)}, "vector_parity": {"compared": expected_count, "failures": vector_failures + int(missing)}}


def make_parity_report(*, provenance: Mapping[str, object], transform: Mapping[str, object], results: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    required = ("field_parity", "id_parity", "vector_parity", "recall_parity")
    if any(not isinstance(results.get(key), Mapping) for key in required):
        raise ParityFailure("parity results are invalid")
    verdict = "pass" if all(int(results[key].get("failures", 1)) == 0 for key in required) else "fail"
    recall = dict(results["recall_parity"])
    recall.setdefault("excluded_fixtures", 0)
    recall.setdefault("source_repeat_runs", 3)
    recall.setdefault("rule", "source-repeatability-plus-serialization-floor")
    recall.setdefault("worst_safe_delta", 0.0)
    return {
        "parity_schema": "solidstats-memory-parity/v1", "verdict": verdict,
        "source_inventory_sha256": _safe_digest(provenance.get("source_inventory_sha256")), "mapping_contract_sha256": _safe_digest(provenance.get("mapping_contract_sha256")), "transform_manifest_sha256": _safe_digest(provenance.get("transform_manifest_sha256")),
        "bundle_sha256": _safe_digest(transform.get("bundle_sha256")), "oracle_version": "3.5.0", "oracle_revision": "v3.5.0", "qdrant_image": transform.get("qdrant_image"), "qdrant_run_id": transform.get("qdrant_run_id"), "target_collection_derivation_sha256": _safe_digest(transform.get("collection_derivation_sha256")), "vector_strategy": transform.get("vector_strategy"),
        "field_parity": dict(results["field_parity"]), "id_parity": dict(results["id_parity"]), "vector_parity": dict(results["vector_parity"]), "recall_parity": recall, "exclusion_parity": {"excluded_records": int(results.get("exclusion_parity", {}).get("excluded_records", 0)) if isinstance(results.get("exclusion_parity"), Mapping) else 0, "failures": 0},
        "bounds": {"max_records": MAX_RECORDS, "max_response_bytes": MAX_RESPONSE_BYTES, "max_top_k": MAX_TOP_K}, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def make_phase21_handoff(report_path: Path, report: Mapping[str, object], bundle_file_digests: Mapping[str, object]) -> dict[str, object]:
    if report.get("verdict") != "pass":
        raise ParityFailure("handoff requires passing parity report")
    names = {str(name): _safe_digest(digest) for name, digest in bundle_file_digests.items()}
    if not names or "bundle-manifest.json" not in names or any(not SAFE_ARTIFACT_NAME.fullmatch(name) for name in names):
        raise ParityFailure("handoff bundle evidence is invalid")
    return {
        "handoff_schema": "solidstats-memory-phase21-handoff/v1", "source_inventory_sha256": _safe_digest(report.get("source_inventory_sha256")), "mapping_contract_sha256": _safe_digest(report.get("mapping_contract_sha256")), "parity_report_sha256": sha256_file(_regular_file(report_path, "parity report")), "bundle_manifest_sha256": names.get("bundle-manifest.json", ""), "bundle_file_digests": names,
        "oracle_version": report.get("oracle_version"), "oracle_revision": report.get("oracle_revision"), "qdrant_image": report.get("qdrant_image"), "target_collection_derivation_sha256": _safe_digest(report.get("target_collection_derivation_sha256")), "target_vector_contract": "qdrant-cosine", "vector_strategy": report.get("vector_strategy"), "record_count": report.get("field_parity", {}).get("compared") if isinstance(report.get("field_parity"), Mapping) else None,
        "phase21_required_checks": ["recompute-provenance-digests", "verify-pinned-oracle-and-image", "verify-retained-bundle-digests", "perform-live-restore-only-in-phase-21"],
    }


def validate_cleanup_binding(report_path: Path, handoff_path: Path, *, expected_run_id: str, expected_collection: str) -> None:
    report = _load_json(report_path, "parity report")
    handoff = _load_json(handoff_path, "Phase 21 handoff")
    if report.get("verdict") != "pass" or report.get("qdrant_run_id") != expected_run_id or not expected_collection or handoff.get("parity_report_sha256") != sha256_file(report_path):
        raise ParityFailure("cleanup requires passing handoff report binding")


def cleanup_isolated_target(*, report_path: Path | None = None, handoff_path: Path | None = None, handoff: Mapping[str, object] | None = None, expected_run_id: str, collection: str, container: str, data_dir: Path, private_root: Path, retained_roots: Sequence[Path], qdrant_url: str, retained_digests: Mapping[Path, str] | None = None) -> None:
    if report_path is None or handoff_path is None:
        raise ParityFailure("cleanup requires passing handoff report binding")
    validate_cleanup_binding(report_path, handoff_path, expected_run_id=expected_run_id, expected_collection=collection)
    root = private_root.resolve(strict=True)
    runtime = data_dir.resolve(strict=True)
    if root not in (runtime, *runtime.parents) or any(runtime == item.resolve(strict=True) or item.resolve(strict=True) in runtime.parents for item in retained_roots):
        raise ParityFailure("cleanup overlaps retained evidence")
    if not container or not collection:
        raise ParityFailure("cleanup target is invalid")
    for retained, digest in (retained_digests or {}).items():
        if sha256_file(_regular_file(retained, "retained evidence")) != digest:
            raise ParityFailure("retained evidence changed")
    validate_container_attestation(container, {"qdrant_image": _load_json(report_path, "parity report").get("qdrant_image"), "qdrant_run_id": expected_run_id})
    _qdrant_request(_loopback_url(qdrant_url), "DELETE", f"/collections/{quote(collection, safe='')}")
    removed = subprocess.run(["docker", "rm", "-f", container], capture_output=True, text=True, timeout=20, check=False)
    if removed.returncode != 0:
        raise ParityFailure("cleanup container removal failed")
    shutil.rmtree(runtime)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inventory", "source-inventory-proof", "mapping-contract", "transform-manifest", "bundle-dir", "recall-fixtures", "oracle-python", "oracle-source-dir", "snapshot-dir", "qdrant-url", "qdrant-container", "qdrant-data-dir", "output", "handoff-output"):
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
        source_proof = _load_json(Path(args.source_inventory_proof), "source inventory proof")
        private_inventory = _load_json(Path(args.inventory), "private inventory")
        bundle_dir = Path(args.bundle_dir).resolve(strict=True)
        bundle_manifest_path = _contained_file(bundle_dir, "bundle-manifest.json", "bundle manifest")
        manifest = _load_json(bundle_manifest_path, "bundle manifest")
        transform = provenance["transform"]
        if not isinstance(transform, dict) or sha256_file(bundle_manifest_path) != transform.get("bundle_sha256") or manifest.get("point_count") != transform.get("point_count"):
            raise ParityFailure("private bundle provenance is invalid")
        for name, digest_key in (("points.jsonl", "points_sha256"), ("id-map.jsonl", "id_map_sha256")):
            if sha256_file(_contained_file(bundle_dir, name, "bundle artifact", max_bytes=512 * 1024 * 1024)) != manifest.get(digest_key):
                raise ParityFailure("private bundle provenance is invalid")
        excluded_records = validate_exclusion_reconciliation(source_proof, private_inventory, manifest, transform)
        derivation = _derive_collection(Path(args.snapshot_dir), Path(args.oracle_python), Path(args.oracle_source_dir))
        if hashlib.sha256(canonical_json_bytes(derivation)).hexdigest() != transform.get("collection_derivation_sha256"):
            raise ParityFailure("target collection derivation mismatch")
        fixtures = _load_fixture_list(Path(args.recall_fixtures))
        validate_fixture_provenance(Path(args.recall_fixtures), Path(args.source_inventory_proof))
        if any(fixture["top_k"] != args.top_k for fixture in fixtures):
            raise ParityFailure("recall fixture bounds are invalid")
        if args.check_only:
            print("PASS: parity provenance validated")
            return 0
        validate_container_attestation(args.qdrant_container, transform)
        base_url = _loopback_url(args.qdrant_url)
        collection = derivation["derived_collection"]
        expected_count = transform.get("point_count")
        if not isinstance(expected_count, int) or not 0 < expected_count <= MAX_RECORDS:
            raise ParityFailure("target count is invalid")
        contract = _load_bundle_contract().load_approved_mapping_contract(Path(args.source_inventory_proof), Path(args.mapping_contract))
        recall_result = _verify_recall(base_url=base_url, collection=collection, fixtures=fixtures, contract=contract, source_proof=source_proof, snapshot_dir=Path(args.snapshot_dir), fixtures_path=Path(args.recall_fixtures), oracle_python=Path(args.oracle_python), oracle_source_dir=Path(args.oracle_source_dir), repeats=args.source_repeat_runs)
        schema = _qdrant_request(base_url, "GET", f"/collections/{quote(collection, safe='')}").get("result")
        vectors = schema.get("config", {}).get("params", {}).get("vectors") if isinstance(schema, dict) and isinstance(schema.get("config"), dict) else None
        if not isinstance(vectors, dict) or vectors.get("distance") != "Cosine" or not isinstance(vectors.get("size"), int):
            raise ParityFailure("target schema is invalid")
        target_count = _qdrant_request(base_url, "POST", f"/collections/{quote(collection, safe='')}/points/count", {"exact": True}).get("result")
        if not isinstance(target_count, dict) or target_count.get("count") != expected_count:
            raise ParityFailure("target count mismatch")
        work_root = Path(args.qdrant_data_dir).resolve(strict=True).parent
        results = _stream_field_parity(bundle_dir=bundle_dir, base_url=base_url, collection=collection, expected_count=expected_count, contract=contract, work_root=work_root)
        results["recall_parity"] = recall_result
        results["exclusion_parity"] = {"excluded_records": excluded_records}
        report = make_parity_report(provenance=provenance, transform=transform, results=results)
        if report["verdict"] != "pass":
            raise ParityFailure("parity comparison failed")
        output, handoff_output = Path(args.output), Path(args.handoff_output)
        write_parity_report(output, report)
        bundle_digests = {"bundle-manifest.json": sha256_file(_contained_file(bundle_dir, "bundle-manifest.json", "bundle manifest")), "points.jsonl": sha256_file(_contained_file(bundle_dir, "points.jsonl", "bundle points", max_bytes=512 * 1024 * 1024)), "id-map.jsonl": sha256_file(_contained_file(bundle_dir, "id-map.jsonl", "bundle map", max_bytes=512 * 1024 * 1024))}
        write_phase21_handoff(handoff_output, make_phase21_handoff(output, report, bundle_digests))
        if args.cleanup_after_pass:
            cleanup_isolated_target(report_path=output, handoff_path=handoff_output, expected_run_id=str(transform["qdrant_run_id"]), collection=collection, container=args.qdrant_container, data_dir=Path(args.qdrant_data_dir), private_root=work_root, retained_roots=[Path(args.snapshot_dir), bundle_dir, Path(args.recall_fixtures), output, handoff_output], qdrant_url=base_url, retained_digests={output: sha256_file(output), handoff_output: sha256_file(handoff_output), _contained_file(bundle_dir, "bundle-manifest.json", "bundle manifest"): sha256_file(_contained_file(bundle_dir, "bundle-manifest.json", "bundle manifest"))})
        print("PASS: isolated parity verified")
        return 0
    except (OSError, ParityFailure) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
