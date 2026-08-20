#!/usr/bin/env python3
"""Build a bounded, private inventory from a frozen MemPalace snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from typing import Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "solidstats-memory" / "migration-policy.json"
SECRET_KEY_PATTERN = re.compile(
    r"(?:authorization|credential|password|secret|token|api[_-]?key|dsn|connection)",
    re.IGNORECASE,
)
UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
CANONICAL_REPOSITORY_WINGS = frozenset(
    {
        "infrastructure",
        "replay-parser-2",
        "replays-fetcher",
        "server-2",
        "web",
    }
)
MAX_ATTESTATION_BYTES = 64 * 1024


class InventoryLimits:
    """Explicit bounded-work contract loaded from the migration policy."""

    def __init__(
        self,
        *,
        max_records: int,
        max_document_bytes: int,
        max_metadata_bytes: int,
        max_vector_dimension: int,
        max_record_bytes: int,
        max_metadata_depth: int = 16,
        max_queries: int = 64,
        max_top_k: int = 20,
        max_elapsed_seconds: int = 300,
    ) -> None:
        self.max_records = max_records
        self.max_document_bytes = max_document_bytes
        self.max_metadata_bytes = max_metadata_bytes
        self.max_vector_dimension = max_vector_dimension
        self.max_record_bytes = max_record_bytes
        self.max_metadata_depth = max_metadata_depth
        self.max_queries = max_queries
        self.max_top_k = max_top_k
        self.max_elapsed_seconds = max_elapsed_seconds


def canonical_json_bytes(value: object) -> bytes:
    """Return strict canonical JSON bytes without coercing unsupported values."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_error(index: int, value: object) -> ValueError:
    return ValueError(f"record-{index}-{sha256_bytes(canonical_json_bytes(value))}")


def _lstat_kind(path: Path) -> int:
    try:
        return path.lstat().st_mode
    except OSError as error:
        raise ValueError("unsafe snapshot component") from error


def _require_directory(path: Path, *, label: str) -> Path:
    mode = _lstat_kind(path)
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"unsafe {label}")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"unsafe {label}") from error


def _assert_safe_tree(root: Path, *, label: str) -> None:
    _require_directory(root, label=label)
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in [*directories, *filenames]:
            candidate = Path(current) / name
            mode = _lstat_kind(candidate)
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f"unsafe {label} component")


def _safe_file(root: Path, relative: Path, *, max_bytes: int) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe snapshot component")
    candidate = root.joinpath(relative)
    mode = _lstat_kind(candidate)
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError("unsafe snapshot component")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError("unsafe snapshot component") from error
    if root not in (resolved, *resolved.parents) or candidate.stat().st_size > max_bytes:
        raise ValueError("unsafe snapshot component")
    return candidate


def _read_bytes_no_follow(root: Path, relative: Path, *, max_bytes: int) -> bytes:
    candidate = _safe_file(root, relative, max_bytes=max_bytes)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as source:
            contents = source.read(max_bytes + 1)
    except OSError as error:
        raise ValueError("unsafe snapshot component") from error
    if len(contents) > max_bytes:
        raise ValueError("unsafe snapshot component")
    return contents


def _load_json(root: Path, relative: Path, *, max_bytes: int) -> object:
    try:
        return json.loads(_read_bytes_no_follow(root, relative, max_bytes=max_bytes))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid snapshot contract") from error


def _metadata_depth(value: object, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max([depth, *(_metadata_depth(item, depth + 1) for item in value.values())])
    if isinstance(value, list):
        return max([depth, *(_metadata_depth(item, depth + 1) for item in value)])
    return depth


def _reject_secret_shape(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            SECRET_KEY_PATTERN.search(str(key)) or _reject_secret_shape(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_reject_secret_shape(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_KEY_PATTERN.search(value))
    return False


def _reject_secret_key_shape(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            SECRET_KEY_PATTERN.search(str(key)) or _reject_secret_key_shape(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_reject_secret_key_shape(item) for item in value)
    return False


def lossless_metadata(metadata: object, limits: InventoryLimits) -> dict[str, object]:
    """Validate metadata without normalizing values or discarding fields."""
    if not isinstance(metadata, dict) or _reject_secret_key_shape(metadata):
        raise ValueError("metadata is invalid")
    if _metadata_depth(metadata) > limits.max_metadata_depth:
        raise ValueError("metadata exceeds depth limit")
    try:
        encoded = canonical_json_bytes(metadata)
        if json.loads(encoded) != metadata:
            raise ValueError("metadata is not lossless")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("metadata is not lossless") from error
    if len(encoded) > limits.max_metadata_bytes:
        raise ValueError("metadata exceeds byte limit")
    return metadata


def _metadata_json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise ValueError("metadata is not lossless")


def _metadata_format(value: object) -> str:
    if isinstance(value, str):
        if UTC_TIMESTAMP_PATTERN.fullmatch(value):
            return "utc_timestamp"
        if DATE_PATTERN.fullmatch(value):
            return "date"
        return "other_string"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "finite_number"
    return "not_applicable"


def _label_category(value: object, *, field: str) -> str:
    if value is None:
        return "missing"
    if not isinstance(value, str):
        return "invalid_type"
    if field == "wing":
        if value in CANONICAL_REPOSITORY_WINGS:
            return "canonical_repository_unsuffixed"
        if value.endswith("-archive"):
            return "suffix_marked"
        return "other_string"
    if SLUG_PATTERN.fullmatch(value):
        return "slug_string"
    return "other_string"


def _new_source_shape_evidence() -> dict[str, object]:
    return {
        "fields": {},
        "source_labels": {
            "room": dict.fromkeys(("slug_string", "other_string", "missing", "invalid_type"), 0),
            "wing": dict.fromkeys(
                (
                    "canonical_repository_unsuffixed",
                    "suffix_marked",
                    "other_string",
                    "missing",
                    "invalid_type",
                ),
                0,
            ),
        },
    }


def _observe_source_shape(
    evidence: dict[str, object], metadata: Mapping[str, object], limits: InventoryLimits
) -> None:
    fields = evidence["fields"]
    labels = evidence["source_labels"]
    if not isinstance(fields, dict) or not isinstance(labels, dict):
        raise ValueError("invalid source shape evidence")
    for name, value in metadata.items():
        field = fields.get(name)
        if field is None:
            if len(fields) >= limits.max_metadata_bytes:
                raise ValueError("metadata shape limit exceeded")
            field = {"formats": {}, "present": 0, "types": {}}
            fields[name] = field
        if not isinstance(field, dict):
            raise ValueError("invalid source shape evidence")
        field["present"] = int(field["present"]) + 1
        for key, category in (("types", _metadata_json_type(value)), ("formats", _metadata_format(value))):
            counts = field[key]
            if not isinstance(counts, dict):
                raise ValueError("invalid source shape evidence")
            counts[category] = int(counts.get(category, 0)) + 1
    for name in ("wing", "room"):
        counts = labels.get(name)
        if not isinstance(counts, dict):
            raise ValueError("invalid source shape evidence")
        category = _label_category(metadata.get(name), field=name)
        counts[category] = int(counts.get(category, 0)) + 1


def _canonical_source_shape_evidence(evidence: dict[str, object]) -> dict[str, object]:
    fields = evidence["fields"]
    labels = evidence["source_labels"]
    if not isinstance(fields, dict) or not isinstance(labels, dict):
        raise ValueError("invalid source shape evidence")
    return {
        "fields": {
            name: {
                "formats": dict(sorted(field["formats"].items())),
                "present": field["present"],
                "types": dict(sorted(field["types"].items())),
            }
            for name, field in sorted(fields.items())
            if isinstance(field, dict)
            and isinstance(field.get("formats"), dict)
            and isinstance(field.get("types"), dict)
        },
        "source_labels": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(labels.items())
            if isinstance(counts, dict)
        },
    }


def load_policy(path: Path) -> tuple[dict[str, object], InventoryLimits]:
    try:
        policy = json.loads(path.read_bytes())
        bounds = policy["bundle_contract"]["bounds"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid migration policy") from error
    if not isinstance(policy, dict) or not isinstance(bounds, dict):
        raise ValueError("invalid migration policy")
    required = ("max_record_count", "max_document_bytes", "max_metadata_bytes", "max_vector_dimension")
    if any(not isinstance(bounds.get(key), int) or bounds[key] <= 0 for key in required):
        raise ValueError("invalid migration policy")
    limits = InventoryLimits(
        max_records=bounds["max_record_count"],
        max_document_bytes=bounds["max_document_bytes"],
        max_metadata_bytes=bounds["max_metadata_bytes"],
        max_vector_dimension=bounds["max_vector_dimension"],
        max_record_bytes=bounds["max_document_bytes"] + bounds["max_metadata_bytes"] + 4096,
    )
    return policy, limits


def _snapshot_digest(snapshot_dir: Path) -> str:
    digest = hashlib.sha256()
    for current, directories, filenames in os.walk(snapshot_dir, followlinks=False):
        directories.sort()
        for filename in sorted(filenames):
            path = Path(current) / filename
            relative = path.relative_to(snapshot_dir).as_posix()
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as source:
                    file_digest = hashlib.file_digest(source, "sha256").hexdigest()
            except OSError as error:
                raise ValueError("unsafe snapshot component") from error
            digest.update(canonical_json_bytes({"path": relative, "sha256": file_digest}))
    return digest.hexdigest()


def _validate_oracle(oracle_source_dir: Path) -> tuple[Path, dict[str, str]]:
    oracle_root = _require_directory(oracle_source_dir, label="oracle source")
    _assert_safe_tree(oracle_root, label="oracle source")
    metadata = _read_bytes_no_follow(
        oracle_root,
        Path("mempalace-3.5.0.dist-info/METADATA"),
        max_bytes=MAX_ATTESTATION_BYTES,
    )
    chroma_contract = _read_bytes_no_follow(
        oracle_root, Path("mempalace/backends/chroma.py"), max_bytes=4 * 1024 * 1024
    )
    qdrant_contract = _read_bytes_no_follow(
        oracle_root, Path("mempalace/backends/qdrant.py"), max_bytes=4 * 1024 * 1024
    )
    required_chroma = (b"class ChromaCollection", b"def get", b"limit", b"offset", b"embeddings")
    required_qdrant = (b"def _point_id", b"uuid.uuid5", b"_remote_collection_name")
    if (
        b"Name: mempalace" not in metadata
        or b"Version: 3.5.0" not in metadata
        or not all(value in chroma_contract for value in required_chroma)
        or not all(value in qdrant_contract for value in required_qdrant)
    ):
        raise ValueError("invalid v3.5.0 oracle contract")
    return oracle_root, {
        "revision": "v3.5.0",
        "checksum": sha256_bytes(metadata + chroma_contract + qdrant_contract),
    }


def _load_snapshot_contract(snapshot_root: Path, limits: InventoryLimits) -> dict[str, object]:
    """Load only required non-secret sidecars for a raw Chroma snapshot."""
    manifest = _load_json(snapshot_root, Path("snapshot-manifest.json"), max_bytes=MAX_ATTESTATION_BYTES)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("invalid snapshot contract")
    names = ("chroma_dir", "identity_sidecar", "config_sidecar", "embedder_sidecar")
    if any(not isinstance(manifest.get(name), str) for name in names):
        raise ValueError("invalid snapshot contract")
    chroma_dir = Path(str(manifest["chroma_dir"]))
    if chroma_dir.is_absolute() or ".." in chroma_dir.parts:
        raise ValueError("invalid snapshot contract")
    palace_root = snapshot_root / chroma_dir
    _require_directory(palace_root, label="Chroma palace")
    _safe_file(palace_root, Path("chroma.sqlite3"), max_bytes=limits.max_record_bytes * limits.max_records)
    identity = _load_json(snapshot_root, Path(str(manifest["identity_sidecar"])), max_bytes=MAX_ATTESTATION_BYTES)
    config = _load_json(snapshot_root, Path(str(manifest["config_sidecar"])), max_bytes=MAX_ATTESTATION_BYTES)
    embedder = _load_json(snapshot_root, Path(str(manifest["embedder_sidecar"])), max_bytes=MAX_ATTESTATION_BYTES)
    if not all(isinstance(value, dict) and not _reject_secret_shape(value) for value in (identity, config, embedder)):
        raise ValueError("invalid snapshot contract")
    palace_id = identity.get("palace_id")
    namespace = identity.get("namespace")
    collection_name = config.get("collection_name")
    if not all(isinstance(value, str) and value for value in (palace_id, namespace, collection_name)):
        raise ValueError("invalid snapshot contract")
    if config.get("backend") != "chroma":
        raise ValueError("invalid snapshot contract")
    embedder_identity = embedder.get(collection_name)
    if not isinstance(embedder_identity, dict) or not isinstance(embedder_identity.get("model_name"), str):
        raise ValueError("invalid snapshot contract")
    if not isinstance(embedder_identity.get("dimension"), int) or not 0 < embedder_identity["dimension"] <= limits.max_vector_dimension:
        raise ValueError("invalid snapshot contract")
    return {
        "collection_name": collection_name,
        "embedder": embedder_identity,
        "namespace": namespace,
        "palace_id": palace_id,
        "palace_root": palace_root,
    }


def _oracle_program() -> str:
    """Return the fixed v3.5.0-only reader, never assembled from snapshot data."""
    return """
import argparse, importlib.metadata, json, sys
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument('--oracle-root', required=True)
parser.add_argument('--palace-path', required=True)
parser.add_argument('--palace-id', required=True)
parser.add_argument('--namespace', required=True)
parser.add_argument('--collection-name', required=True)
parser.add_argument('--page-size', type=int, required=True)
parser.add_argument('--check-only', action='store_true')
args = parser.parse_args()
root = Path(args.oracle_root).resolve()
sys.path.insert(0, str(root))
import mempalace
if importlib.metadata.version('mempalace') != '3.5.0' or root not in Path(mempalace.__file__).resolve().parents:
    raise RuntimeError('unapproved oracle')
from mempalace.backends.base import PalaceRef
from mempalace.backends.chroma import ChromaCollection
from mempalace.backends.qdrant import QdrantBackend, _QdrantConfig, _point_id
import chromadb
client = chromadb.PersistentClient(path=args.palace_path)
raw = client.get_collection(args.collection_name)
collection = ChromaCollection(raw, palace_path=args.palace_path)
count = collection.count()
config = _QdrantConfig(url='http://127.0.0.1:9', api_key=None, timeout=1.0, namespace=args.namespace)
palace = PalaceRef(id=args.palace_id, local_path=args.palace_path, namespace=args.namespace)
target_name = QdrantBackend()._remote_collection_name(palace=palace, collection_name=args.collection_name, config=config)
identity = collection.get_stored_embedder_identity()
if identity is None:
    raise RuntimeError('missing embedder identity')
print(json.dumps({'type':'header','record_count':count,'collection':{'name':args.collection_name,'palace_id':args.palace_id,'namespace':args.namespace,'target_name':target_name,'embedder':{'model_name':identity.model_name,'dimension':identity.dimension},'source_metric':collection.distance_metric}}, separators=(',', ':'), sort_keys=True), flush=True)
if not args.check_only:
    for offset in range(0, count, args.page_size):
        page = collection.get(limit=args.page_size, offset=offset, include=['documents', 'metadatas', 'embeddings'])
        lengths = (len(page.ids), len(page.documents), len(page.metadatas), len(page.embeddings or []))
        if not page.ids or len(set(lengths)) != 1:
            raise RuntimeError('incomplete page')
        for index, (doc_id, document, metadata, embedding) in enumerate(zip(page.ids, page.documents, page.metadatas, page.embeddings, strict=True), offset + 1):
            print(json.dumps({'type':'record','index':index,'id':doc_id,'mempalace_id':doc_id,'point_id':_point_id(doc_id),'document':document,'metadata':metadata,'embedding':embedding}, separators=(',', ':'), sort_keys=True), flush=True)
print(json.dumps({'type':'done','record_count':count}, separators=(',', ':')), flush=True)
"""


def _resolve_oracle_python(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError("invalid oracle interpreter") from error
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError("invalid oracle interpreter")
    return resolved


def _oracle_rows(
    *, oracle_python: Path, oracle_root: Path, contract: Mapping[str, object], page_size: int, check_only: bool
) -> Iterator[dict[str, object]]:
    command = [
        str(_resolve_oracle_python(oracle_python)), "-I", "-c", _oracle_program(),
        "--oracle-root", str(oracle_root), "--palace-path", str(contract["palace_root"]),
        "--palace-id", str(contract["palace_id"]), "--namespace", str(contract["namespace"]),
        "--collection-name", str(contract["collection_name"]), "--page-size", str(page_size),
    ]
    if check_only:
        command.append("--check-only")
    environment = {"HOME": "/nonexistent", "PATH": os.defpath, "PYTHONNOUSERSITE": "1"}
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=environment)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            if len(line.encode("utf-8")) > 4 * 1024 * 1024:
                raise ValueError("invalid oracle protocol")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError("invalid oracle protocol") from error
            if not isinstance(row, dict):
                raise ValueError("invalid oracle protocol")
            yield row
    finally:
        process.stdout.close()
        return_code = process.wait(timeout=10)
    if return_code:
        raise ValueError("v3.5.0 oracle failed")


def _validate_freeze(snapshot_root: Path, freeze_attestation: Path) -> dict[str, object]:
    try:
        relative = freeze_attestation.relative_to(snapshot_root)
    except ValueError as error:
        raise ValueError("unsafe freeze attestation") from error
    value = _load_json(snapshot_root, relative, max_bytes=MAX_ATTESTATION_BYTES)
    if not isinstance(value, dict) or not isinstance(value.get("write_freeze_at"), str):
        raise ValueError("invalid freeze attestation")
    if not UTC_TIMESTAMP_PATTERN.fullmatch(value["write_freeze_at"]) or _reject_secret_shape(value):
        raise ValueError("invalid freeze attestation")
    return {"write_freeze_at": value["write_freeze_at"], "digest": sha256_bytes(canonical_json_bytes(value))}


def iter_chroma_records(
    records: Sequence[object], *, page_size: int, limits: InventoryLimits
) -> Iterator[tuple[int, Mapping[str, object]]]:
    """Yield bounded Chroma-shaped rows in deterministic source-page order."""
    if page_size <= 0:
        raise ValueError("invalid page size")
    if len(records) > limits.max_records:
        raise ValueError("record limit exceeded")
    seen: set[str] = set()
    previous_offset = -1
    for offset in range(0, len(records), page_size):
        if offset <= previous_offset:
            raise ValueError("page stalled")
        previous_offset = offset
        page = records[offset : offset + page_size]
        if not page:
            raise ValueError("page stalled")
        for index, record in enumerate(page, start=offset + 1):
            if not isinstance(record, dict):
                raise safe_error(index, {"kind": "record"})
            source_id = record.get("id")
            if not isinstance(source_id, str) or not source_id or source_id in seen:
                raise safe_error(index, {"kind": "id"})
            seen.add(source_id)
            yield index, record


def _validated_record(index: int, record: Mapping[str, object], limits: InventoryLimits) -> tuple[dict[str, object], dict[str, object]]:
    source_id = record["id"]
    document = record.get("document")
    vector = record.get("vector")
    try:
        if not isinstance(document, str) or len(document.encode("utf-8")) > limits.max_document_bytes:
            raise ValueError("invalid document")
        metadata = lossless_metadata(record.get("metadata"), limits)
        if not isinstance(vector, list) or not 0 < len(vector) <= limits.max_vector_dimension:
            raise ValueError("invalid vector")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in vector):
            raise ValueError("invalid vector")
        source = {"id": source_id, "document": document, "metadata": metadata}
        if len(canonical_json_bytes(source)) > limits.max_record_bytes:
            raise ValueError("record exceeds byte limit")
    except ValueError as error:
        raise safe_error(index, {"kind": "invalid"}) from error
    source["document_sha256"] = sha256_bytes(document.encode("utf-8"))
    source["metadata_sha256"] = sha256_bytes(canonical_json_bytes(metadata))
    vector_entry = {"id": source_id, "vector": vector, "vector_sha256": sha256_bytes(canonical_json_bytes(vector))}
    return source, vector_entry


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return float("inf")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return float("inf")
    return 1.0 - sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def derive_recall_fixtures(
    records: Sequence[Mapping[str, object]], *, max_queries: int, top_k: int
) -> list[dict[str, object]]:
    """Choose digest-stable source-only recall cases without query text."""
    if not 0 < max_queries or not 0 < top_k:
        raise ValueError("invalid recall limits")
    ordered = sorted(records, key=lambda record: str(record["id"]))
    strata: list[dict[str, str]] = [{}]
    for key in ("wing", "room", "archive_state"):
        values = sorted({str(record["metadata"][key]) for record in ordered if isinstance(record.get("metadata"), dict) and isinstance(record["metadata"].get(key), str)})
        strata.extend({key: value} for value in values)
    fixtures: list[dict[str, object]] = []
    for filters in strata[:max_queries]:
        eligible = [record for record in ordered if all(record["metadata"].get(key) == value for key, value in filters.items())]
        if not eligible:
            continue
        query = eligible[0]
        ranked = sorted(
            ((str(record["id"]), _cosine_distance(query["vector"], record["vector"])) for record in eligible),
            key=lambda item: (item[1], item[0]),
        )[:top_k]
        fixtures.append(
            {
                "filters": filters,
                "query_record_digest": sha256_bytes(str(query["id"]).encode("utf-8")),
                "source_distances": [distance for _source_id, distance in ranked],
                "source_metric": "cosine-distance",
                "source_ordered_ids": [source_id for source_id, _distance in ranked],
                "source_runs": 2,
                "top_k": top_k,
            }
        )
    return fixtures


def _derive_recall_fixtures_from_private_output(
    records_path: Path,
    vectors_path: Path,
    *,
    max_queries: int,
    top_k: int,
    limits: InventoryLimits,
) -> list[dict[str, object]]:
    """Derive bounded fixtures by rescanning private JSONL, not a corpus list."""
    candidates: dict[tuple[tuple[str, str], ...], tuple[str, dict[str, object], list[float]]] = {}
    with records_path.open(encoding="utf-8") as records_file, vectors_path.open(encoding="utf-8") as vectors_file:
        for index, (record_line, vector_line) in enumerate(zip(records_file, vectors_file, strict=True), 1):
            try:
                record = json.loads(record_line)
                vector = json.loads(vector_line)
            except json.JSONDecodeError as error:
                raise ValueError("invalid private inventory") from error
            if not isinstance(record, dict) or not isinstance(vector, dict) or record.get("id") != vector.get("id"):
                raise ValueError("invalid private inventory")
            source_id, metadata, embedding = record.get("id"), record.get("metadata"), vector.get("vector")
            if not isinstance(source_id, str) or not isinstance(metadata, dict) or not isinstance(embedding, list):
                raise ValueError("invalid private inventory")
            keys = [tuple()]
            for field in ("wing", "room", "archive_state"):
                value = metadata.get(field)
                if isinstance(value, str):
                    keys.append(((field, value),))
            for key in keys:
                old = candidates.get(key)
                if old is None and len(candidates) >= max_queries:
                    raise ValueError("recall fixture limit exceeded")
                if old is None or source_id < old[0]:
                    candidates[key] = (source_id, metadata, embedding)
            if index > limits.max_records:
                raise ValueError("record limit exceeded")
        if next(records_file, None) is not None or next(vectors_file, None) is not None:
            raise ValueError("invalid private inventory")
    fixtures: list[dict[str, object]] = []
    for filters, query in sorted(candidates.items(), key=lambda item: item[0]):
        ranked: list[tuple[float, str]] = []
        with records_path.open(encoding="utf-8") as records_file, vectors_path.open(encoding="utf-8") as vectors_file:
            for record_line, vector_line in zip(records_file, vectors_file, strict=True):
                record, vector = json.loads(record_line), json.loads(vector_line)
                if not isinstance(record, dict) or not isinstance(vector, dict):
                    raise ValueError("invalid private inventory")
                metadata = record.get("metadata")
                source_id, embedding = record.get("id"), vector.get("vector")
                if not isinstance(metadata, dict) or not isinstance(source_id, str) or not isinstance(embedding, list):
                    raise ValueError("invalid private inventory")
                if any(metadata.get(key) != value for key, value in filters):
                    continue
                ranked.append((_cosine_distance(query[2], embedding), source_id))
                if len(ranked) > top_k:
                    ranked.remove(max(ranked, key=lambda item: (item[0], item[1])))
        ranked.sort(key=lambda item: (item[0], item[1]))
        fixtures.append(
            {
                "filters": dict(filters),
                "query_record_digest": sha256_bytes(query[0].encode("utf-8")),
                "source_distances": [distance for distance, _source_id in ranked],
                "source_metric": "cosine-distance",
                "source_ordered_ids": [source_id for _distance, source_id in ranked],
                "source_runs": 2,
                "top_k": top_k,
            }
        )
    return fixtures


def _create_output_dir(output_dir: Path) -> Path:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must be new")
    parent = output_dir.parent
    _require_directory(parent, label="output ancestor")
    current = parent
    while current != current.parent:
        mode = _lstat_kind(current)
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError("unsafe output ancestor")
        current = current.parent
    output_dir.mkdir(mode=0o700)
    return output_dir


def _write_private_json(output_dir: Path, name: str, value: object, *, jsonl: bool = False) -> str:
    target = output_dir / name
    if jsonl:
        payload = b"".join(canonical_json_bytes(item) + b"\n" for item in value)
    else:
        payload = canonical_json_bytes(value) + b"\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(payload)
    return sha256_bytes(payload)


def _build_source_inventory(
    *,
    snapshot_dir: Path,
    freeze_attestation: Path,
    oracle_source_dir: Path,
    oracle_python: Path,
    output_dir: Path,
    page_size: int = 500,
    max_records: int | None = None,
    max_record_bytes: int | None = None,
    policy_path: Path = DEFAULT_POLICY,
    check_only: bool = False,
) -> dict[str, object]:
    """Validate a frozen snapshot and write only private source evidence."""
    started = time.monotonic()
    _policy, policy_limits = load_policy(policy_path)
    limits = InventoryLimits(
        max_records=min(policy_limits.max_records, max_records or policy_limits.max_records),
        max_document_bytes=policy_limits.max_document_bytes,
        max_metadata_bytes=policy_limits.max_metadata_bytes,
        max_vector_dimension=policy_limits.max_vector_dimension,
        max_record_bytes=min(policy_limits.max_record_bytes, max_record_bytes or policy_limits.max_record_bytes),
        max_metadata_depth=policy_limits.max_metadata_depth,
        max_queries=policy_limits.max_queries,
        max_top_k=policy_limits.max_top_k,
        max_elapsed_seconds=policy_limits.max_elapsed_seconds,
    )
    snapshot_root = _require_directory(snapshot_dir, label="snapshot")
    _assert_safe_tree(snapshot_root, label="snapshot")
    snapshot_digest_start = _snapshot_digest(snapshot_root)
    freeze = _validate_freeze(snapshot_root, freeze_attestation)
    oracle_root, oracle = _validate_oracle(oracle_source_dir)
    snapshot_contract = _load_snapshot_contract(snapshot_root, limits)
    if page_size <= 0:
        raise ValueError("invalid page size")
    rows = _oracle_rows(
        oracle_python=oracle_python,
        oracle_root=oracle_root,
        contract=snapshot_contract,
        page_size=min(page_size, limits.max_records),
        check_only=check_only,
    )
    try:
        header = next(rows)
    except StopIteration as error:
        raise ValueError("invalid oracle protocol") from error
    if header.get("type") != "header" or not isinstance(header.get("record_count"), int):
        raise ValueError("invalid oracle protocol")
    record_count = header["record_count"]
    collection = header.get("collection")
    if record_count > limits.max_records:
        raise ValueError("record limit exceeded")
    if not isinstance(collection, dict) or record_count < 0:
        raise ValueError("invalid oracle protocol")
    expected_collection = {
        "name": snapshot_contract["collection_name"],
        "palace_id": snapshot_contract["palace_id"],
        "namespace": snapshot_contract["namespace"],
        "embedder": snapshot_contract["embedder"],
    }
    if any(collection.get(key) != value for key, value in expected_collection.items()):
        raise ValueError("invalid oracle protocol")
    if not isinstance(collection.get("target_name"), str) or not collection["target_name"]:
        raise ValueError("invalid oracle protocol")
    if check_only:
        try:
            done = next(rows)
        except StopIteration as error:
            raise ValueError("invalid oracle protocol") from error
        if done != {"type": "done", "record_count": record_count}:
            raise ValueError("invalid oracle protocol")
        try:
            next(rows)
        except StopIteration:
            return {
                "check_only": True,
                "oracle": oracle,
                "freeze_attestation_digest": freeze["digest"],
                "record_count": record_count,
            }
        raise ValueError("invalid oracle protocol")
    destination = _create_output_dir(output_dir)
    records_path = destination / "source-records.jsonl"
    vectors_path = destination / "source-vectors.jsonl"
    seen_ids: set[str] = set()
    observed = 0
    records_digest = hashlib.sha256()
    source_shape_evidence = _new_source_shape_evidence()
    vectors_digest = hashlib.sha256()
    done_seen = False
    with records_path.open("xb") as records_file, vectors_path.open("xb") as vectors_file:
        os.chmod(records_path, 0o600)
        os.chmod(vectors_path, 0o600)
        for row in rows:
            if done_seen:
                raise ValueError("invalid oracle protocol")
            if row.get("type") == "done":
                if row != {"type": "done", "record_count": record_count}:
                    raise ValueError("invalid oracle protocol")
                done_seen = True
                continue
            observed += 1
            if row.get("type") != "record" or row.get("index") != observed:
                raise ValueError("invalid oracle protocol")
            source_id = row.get("id")
            if not isinstance(source_id, str) or not source_id or source_id in seen_ids:
                raise safe_error(observed, {"kind": "id"})
            seen_ids.add(source_id)
            if row.get("mempalace_id") != source_id or not isinstance(row.get("point_id"), str):
                raise safe_error(observed, {"kind": "mapping"})
            source, vector = _validated_record(observed, {
                "id": source_id,
                "document": row.get("document"),
                "metadata": row.get("metadata"),
                "vector": row.get("embedding"),
            }, limits)
            source["mempalace_id"] = source_id
            source["point_id"] = row["point_id"]
            _observe_source_shape(source_shape_evidence, source["metadata"], limits)
            record_line = canonical_json_bytes(source) + b"\n"
            vector_line = canonical_json_bytes(vector) + b"\n"
            records_file.write(record_line)
            vectors_file.write(vector_line)
            records_digest.update(record_line)
            vectors_digest.update(vector_line)
            if observed > limits.max_records or time.monotonic() - started > limits.max_elapsed_seconds:
                raise ValueError("inventory elapsed-work limit exceeded")
    if not done_seen or observed != record_count or not observed:
        raise ValueError("invalid oracle protocol")
    fixtures = _derive_recall_fixtures_from_private_output(
        records_path, vectors_path, max_queries=limits.max_queries,
        top_k=min(limits.max_top_k, observed), limits=limits,
    )
    records_checksum = records_digest.hexdigest()
    vectors_checksum = vectors_digest.hexdigest()
    fixtures_checksum = _write_private_json(destination, "recall-fixtures.json", fixtures)
    snapshot_digest_end = _snapshot_digest(snapshot_root)
    if snapshot_digest_start != snapshot_digest_end:
        raise ValueError("snapshot digest changed")
    summary = {
        "collection_evidence_digest": sha256_bytes(canonical_json_bytes(collection)),
        "fixture_count": len(fixtures),
        "freeze_attestation_digest": freeze["digest"],
        "oracle": oracle,
        "output_checksums": {
            "recall_fixtures": fixtures_checksum,
            "source_records": records_checksum,
            "source_vectors": vectors_checksum,
        },
        "record_count": observed,
        "schema_version": 1,
        "source_shape_evidence": _canonical_source_shape_evidence(source_shape_evidence),
        "source_snapshot_checksum": snapshot_digest_end,
        "synthetic_or_private_source_evidence": True,
    }
    _write_private_json(destination, "source-inventory.json", summary)
    return summary


def _discard_incomplete_output(output_dir: Path) -> None:
    """Remove only files this command may have created after a failed run."""
    try:
        mode = output_dir.lstat().st_mode
    except OSError:
        return
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return
    for name in ("source-records.jsonl", "source-vectors.jsonl", "recall-fixtures.json", "source-inventory.json"):
        target = output_dir / name
        try:
            target.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            return
    try:
        output_dir.rmdir()
    except OSError:
        return


def build_source_inventory(**kwargs: object) -> dict[str, object]:
    """Build a private inventory and leave no partial evidence on failure."""
    output_dir = kwargs.get("output_dir")
    if not isinstance(output_dir, Path):
        raise ValueError("invalid output directory")
    existed = output_dir.exists() or output_dir.is_symlink()
    try:
        return _build_source_inventory(**kwargs)  # type: ignore[arg-type]
    except Exception:
        if not existed:
            _discard_incomplete_output(output_dir)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--freeze-attestation", required=True, type=Path)
    parser.add_argument("--oracle-source-dir", required=True, type=Path)
    parser.add_argument("--oracle-python", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--page-size", default=500, type=int)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-record-bytes", type=int)
    parser.add_argument("--policy", default=DEFAULT_POLICY, type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        build_source_inventory(
            snapshot_dir=args.snapshot_dir,
            freeze_attestation=args.freeze_attestation,
            oracle_source_dir=args.oracle_source_dir,
            oracle_python=args.oracle_python,
            output_dir=args.output_dir,
            page_size=args.page_size,
            max_records=args.max_records,
            max_record_bytes=args.max_record_bytes,
            policy_path=args.policy,
            check_only=args.check_only,
        )
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 64
    print("PASS: source inventory contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
