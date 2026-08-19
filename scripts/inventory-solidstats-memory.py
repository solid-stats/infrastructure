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


def lossless_metadata(metadata: object, limits: InventoryLimits) -> dict[str, object]:
    """Validate metadata without normalizing values or discarding fields."""
    if not isinstance(metadata, dict) or _reject_secret_shape(metadata):
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
    entries: list[dict[str, str]] = []
    for current, _directories, filenames in os.walk(snapshot_dir, followlinks=False):
        for filename in sorted(filenames):
            path = Path(current) / filename
            relative = path.relative_to(snapshot_dir).as_posix()
            entries.append({"path": relative, "sha256": sha256_bytes(path.read_bytes())})
    return sha256_bytes(canonical_json_bytes(entries))


def _validate_oracle(oracle_source_dir: Path) -> dict[str, str]:
    oracle_root = _require_directory(oracle_source_dir, label="oracle source")
    _assert_safe_tree(oracle_root, label="oracle source")
    project = _read_bytes_no_follow(oracle_root, Path("pyproject.toml"), max_bytes=MAX_ATTESTATION_BYTES)
    contract = _read_bytes_no_follow(
        oracle_root,
        Path("mempalace/backends/qdrant.py"),
        max_bytes=2 * 1024 * 1024,
    )
    if b'version = "3.5.0"' not in project or b"uuid.uuid5" not in contract or b"mempalace_id" not in contract:
        raise ValueError("invalid v3.5.0 oracle contract")
    return {"revision": "v3.5.0", "checksum": sha256_bytes(project + contract)}


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
        if not isinstance(metadata.get("source_timestamp"), str) or not UTC_TIMESTAMP_PATTERN.fullmatch(metadata["source_timestamp"]):
            raise ValueError("invalid source timestamp")
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


def build_source_inventory(
    *,
    snapshot_dir: Path,
    freeze_attestation: Path,
    oracle_source_dir: Path,
    output_dir: Path,
    page_size: int = 500,
    max_records: int | None = None,
    max_record_bytes: int | None = None,
    policy_path: Path = DEFAULT_POLICY,
    check_only: bool = False,
) -> dict[str, object]:
    """Validate a frozen snapshot and write only private source evidence."""
    started = time.monotonic()
    policy, policy_limits = load_policy(policy_path)
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
    freeze = _validate_freeze(snapshot_root, freeze_attestation)
    oracle = _validate_oracle(oracle_source_dir)
    if page_size <= 0:
        raise ValueError("invalid page size")
    if check_only:
        return {"check_only": True, "oracle": oracle, "freeze_attestation_digest": freeze["digest"]}
    bundle_contract = policy.get("bundle_contract")
    if not isinstance(bundle_contract, dict) or not isinstance(bundle_contract.get("bounds"), dict):
        raise ValueError("invalid migration policy")
    max_snapshot_json_bytes = bundle_contract["bounds"].get("max_artifact_bytes")
    if not isinstance(max_snapshot_json_bytes, int) or max_snapshot_json_bytes <= 0:
        raise ValueError("invalid migration policy")
    collection_value = _load_json(
        snapshot_root,
        Path("chroma-collection.json"),
        max_bytes=max_snapshot_json_bytes,
    )
    if not isinstance(collection_value, dict) or not isinstance(collection_value.get("collection"), dict) or not isinstance(collection_value.get("records"), list):
        raise ValueError("invalid snapshot contract")
    collection = collection_value["collection"]
    required_collection = ("palace_id", "namespace", "name", "embedder")
    if any(not collection.get(key) for key in required_collection) or _reject_secret_shape(collection):
        raise ValueError("invalid snapshot contract")
    active_rooms = policy.get("active_rooms")
    archive_wings = policy.get("archive_wings")
    common_wing = policy.get("common_wing")
    if not isinstance(active_rooms, list) or not isinstance(archive_wings, list) or not isinstance(common_wing, str):
        raise ValueError("invalid migration policy")
    source_records: list[dict[str, object]] = []
    vector_records: list[dict[str, object]] = []
    fixture_records: list[dict[str, object]] = []
    for index, row in iter_chroma_records(
        collection_value["records"],
        page_size=min(page_size, limits.max_records),
        limits=limits,
    ):
        source, vector = _validated_record(index, row, limits)
        metadata = source["metadata"]
        if metadata.get("room") not in active_rooms or metadata.get("wing") not in [common_wing, *archive_wings]:
            raise safe_error(index, {"kind": "scope"})
        source_records.append(source)
        vector_records.append(vector)
        fixture_records.append({"id": source["id"], "metadata": metadata, "vector": vector["vector"]})
        if time.monotonic() - started > limits.max_elapsed_seconds:
            raise ValueError("inventory elapsed-work limit exceeded")
    if not source_records:
        raise ValueError("snapshot has no records")
    fixtures = derive_recall_fixtures(fixture_records, max_queries=limits.max_queries, top_k=min(limits.max_top_k, len(source_records)))
    destination = _create_output_dir(output_dir)
    records_checksum = _write_private_json(destination, "source-records.jsonl", source_records, jsonl=True)
    vectors_checksum = _write_private_json(destination, "source-vectors.jsonl", vector_records, jsonl=True)
    fixtures_checksum = _write_private_json(destination, "recall-fixtures.json", fixtures)
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
        "record_count": len(source_records),
        "schema_version": 1,
        "source_snapshot_checksum": _snapshot_digest(snapshot_root),
        "synthetic_or_private_source_evidence": True,
    }
    _write_private_json(destination, "source-inventory.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--freeze-attestation", required=True, type=Path)
    parser.add_argument("--oracle-source-dir", required=True, type=Path)
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
