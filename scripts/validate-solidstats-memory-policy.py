#!/usr/bin/env python3
"""Validate the SolidStats memory policy and an optional offline bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import uuid


EXPECTED_ACTIVE_ROOMS = [
    "decisions",
    "contracts",
    "conventions",
    "operations",
    "incidents",
    "migrations",
]
EXPECTED_ARCHIVE_WINGS = [
    "server-2-archive",
    "replays-fetcher-archive",
    "replay-parser-2-archive",
    "web-archive",
    "infrastructure-archive",
]
DISABLED_FEATURES = (
    "recall_on_plan",
    "mirror_kg",
    "diary_journal",
    "auto_capture_hooks",
    "semantic_tunnels",
)
CAPTURE_SHAPE = ["task", "outcome", "decisions", "validation", "sources"]
ARCHIVE_DISTILLATION = {
    "stage": "post-cutover",
    "extractor_access": "read-only",
    "extractors_can_write": False,
    "archive_drawers_mutable": False,
    "promotion_owner": "curator",
    "current_source_verification_required": True,
    "shard_ledger_required": True,
}
BUNDLE_CONTRACT = {
    "bounds": {
        "max_artifact_bytes": 1024 * 1024,
        "max_document_bytes": 256 * 1024,
        "max_manifest_bytes": 64 * 1024,
        "max_metadata_bytes": 64 * 1024,
        "max_recall_fixture_count": 10_000,
        "max_record_count": 1_000_000,
        "max_vector_dimension": 65_536,
    },
    "required_artifacts": [
        "source-inventory.json",
        "transform-manifest.json",
        "parity-report.json",
    ],
    "required_manifest_fields": [
        "write_freeze_at",
        "source_snapshot_checksum",
        "source_inventory_reference",
        "transform_manifest_reference",
        "parity_report_reference",
    ],
    "mapping_contract": {
        "payload_id_field": "mempalace_id",
        "point_id_strategy": "mempalace-v3.5.0-uuidv5",
        "source_timestamp_metadata_key": "source_timestamp",
    },
    "synthetic_parity_is_non_production": True,
}
BUNDLE_BOUNDS = BUNDLE_CONTRACT["bounds"]
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
SECRET_KEY_PATTERN = re.compile(
    r"(?:authorization|credential|password|secret|token|api[_-]?key|dsn|connection)",
    re.IGNORECASE,
)
MEMPALACE_UUID_NAMESPACE = uuid.UUID("c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1")


def load_json(
    path: Path, *, label: str | None = None, max_bytes: int | None = None
) -> dict[str, object]:
    display_name = label or path.name
    try:
        if max_bytes is not None and path.stat().st_size > max_bytes:
            raise ValueError(f"{display_name} exceeds its byte limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON from {display_name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{display_name} must contain a JSON object")
    return value


def validate_policy(policy: dict[str, object]) -> list[str]:
    errors: list[str] = []
    required_values = {
        "schema_version": 1,
        "service_name": "solidstats_memory",
        "kubernetes_name": "solidstats-memory",
        "active_rooms": EXPECTED_ACTIVE_ROOMS,
        "archive_wings": EXPECTED_ARCHIVE_WINGS,
        "common_wing": "SolidStats",
        "archive_trust": "untrusted-historical-evidence",
        "legacy_writes_frozen": True,
        "capture_shape": CAPTURE_SHAPE,
        "migration_mode": "local-build-and-validation-transform-blocked",
        "bundle_contract": BUNDLE_CONTRACT,
        "delete_legacy_requires_exact_ids": True,
        "archive_distillation": ARCHIVE_DISTILLATION,
    }
    for key, expected in required_values.items():
        if policy.get(key) != expected:
            errors.append(f"{key}: expected {expected!r}, got {policy.get(key)!r}")
    for key in DISABLED_FEATURES:
        if policy.get(key) is not False:
            errors.append(f"{key}: must be false")
    return errors


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def resolve_bundle_path(bundle_dir: Path, relative: object) -> Path | None:
    """Return one existing regular file contained by the bundle root."""
    if not isinstance(relative, str):
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        root = bundle_dir.resolve(strict=True)
    except OSError:
        return None
    unresolved = bundle_dir
    for component in candidate.parts:
        unresolved = unresolved / component
        if unresolved.is_symlink():
            return None
    try:
        resolved = (bundle_dir / candidate).resolve(strict=True)
    except OSError:
        return None
    if root not in (resolved, *resolved.parents) or not resolved.is_file():
        return None
    return resolved


def bundle_path_contains_symlink(bundle_dir: Path, relative: object) -> bool:
    if not isinstance(relative, str):
        return False
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    current = bundle_dir
    for component in candidate.parts:
        current = current / component
        if current.is_symlink():
            return True
    return False


def validate_source_records(
    records_path: Path,
    inventory: dict[str, object],
    expected_source_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    record_count = 0
    try:
        with records_path.open("r", encoding="utf-8") as source:
            for line_number, raw_line in enumerate(source, start=1):
                if len(raw_line.encode("utf-8")) > (
                    BUNDLE_BOUNDS["max_document_bytes"]
                    + BUNDLE_BOUNDS["max_metadata_bytes"]
                    + 4096
                ):
                    errors.append(f"source-records.jsonl record {line_number} exceeds byte limit")
                    break
                if not raw_line.strip():
                    errors.append(f"source-records.jsonl record {line_number} must be an object")
                    continue
                try:
                    record = json.loads(
                        raw_line,
                        parse_constant=lambda _value: float("nan"),
                    )
                except (json.JSONDecodeError, ValueError):
                    errors.append(f"source-records.jsonl record {line_number} is invalid JSON")
                    continue
                if not isinstance(record, dict):
                    errors.append(f"source-records.jsonl record {line_number} must be an object")
                    continue
                record_count += 1
                source_id = record.get("id")
                if not isinstance(source_id, str) or not source_id:
                    errors.append(f"source-records.jsonl record {line_number} ID is required")
                elif source_id in seen_ids:
                    errors.append(
                        f"source-records.jsonl duplicate source ID at record {line_number}"
                    )
                else:
                    seen_ids.add(source_id)
                document = record.get("document")
                if not isinstance(document, str):
                    errors.append(
                        f"source-records.jsonl record {line_number} document must be a string"
                    )
                elif len(document.encode("utf-8")) > BUNDLE_BOUNDS["max_document_bytes"]:
                    errors.append(f"source-records.jsonl record {line_number} document exceeds byte limit")
                metadata = record.get("metadata")
                if not isinstance(metadata, dict):
                    errors.append(
                        f"source-records.jsonl record {line_number} metadata must be an object"
                    )
                    continue
                try:
                    canonical_metadata = json.dumps(
                        metadata,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    if json.loads(canonical_metadata) != metadata:
                        raise ValueError("metadata round trip")
                except (TypeError, ValueError, json.JSONDecodeError):
                    errors.append(
                        f"source-records.jsonl record {line_number} metadata is not lossless JSON"
                    )
                    continue
                if len(canonical_metadata.encode("utf-8")) > BUNDLE_BOUNDS["max_metadata_bytes"]:
                    errors.append(f"source-records.jsonl record {line_number} metadata exceeds byte limit")
                if not isinstance(metadata.get("source_timestamp"), str) or not UTC_TIMESTAMP_PATTERN.fullmatch(
                    metadata["source_timestamp"]
                ):
                    errors.append(
                        f"source-records.jsonl record {line_number} source timestamp is required"
                    )
                if record_count > BUNDLE_BOUNDS["max_record_count"]:
                    errors.append("source-records.jsonl exceeds max record count")
                    break
    except OSError:
        return ["source-records.jsonl cannot be read"]
    if inventory.get("record_count") != record_count:
        errors.append("source-inventory.json record_count must match source records")
    if expected_source_ids is not None and seen_ids != expected_source_ids:
        errors.append("transform-manifest.json mappings must cover every source ID")
    return errors


def is_credential_value(value: str) -> bool:
    if value.lower().startswith("bearer ") or "://" in value:
        parsed = urlsplit(value)
        return parsed.username is not None or value.lower().startswith("bearer ")
    return False


def validate_evidence_secrets(value: object, artifact: str, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if SECRET_KEY_PATTERN.search(str(key)):
                errors.append(
                    f"{artifact} contains credential-shaped value at {nested_path}"
                )
                continue
            errors.extend(validate_evidence_secrets(nested, artifact, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            errors.extend(validate_evidence_secrets(nested, artifact, f"{path}[{index}]"))
    elif isinstance(value, str) and is_credential_value(value):
        errors.append(f"{artifact} contains credential-shaped value at {path}")
    return errors


def validate_freeze_attestation(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest.get("write_freeze_at"), str) or not UTC_TIMESTAMP_PATTERN.fullmatch(
        manifest["write_freeze_at"]
    ):
        errors.append("bundle write_freeze_at must be a UTC timestamp")
    if not is_sha256(manifest.get("source_snapshot_checksum")):
        errors.append("bundle source_snapshot_checksum must be a lowercase sha256")
    return errors


def validate_inventory(
    inventory: dict[str, object], manifest: dict[str, object]
) -> list[str]:
    errors: list[str] = []
    if inventory.get("source_snapshot_checksum") != manifest.get(
        "source_snapshot_checksum"
    ):
        errors.append("source-inventory.json snapshot checksum must match the bundle")
    if not isinstance(inventory.get("source_records_reference"), str):
        errors.append("source-inventory.json source_records_reference is required")
    if not is_sha256(inventory.get("source_records_checksum")):
        errors.append("source-inventory.json source_records_checksum must be a lowercase sha256")
    if not isinstance(inventory.get("record_count"), int) or isinstance(
        inventory.get("record_count"), bool
    ) or inventory["record_count"] < 1:
        errors.append("source-inventory.json record_count must be a positive integer")
    return errors


def validate_transform_manifest(
    transform: dict[str, object], manifest: dict[str, object]
) -> list[str]:
    errors: list[str] = []
    if transform.get("source_inventory_reference") != "source-inventory.json":
        errors.append("transform-manifest.json source_inventory_reference is invalid")
    if transform.get("source_snapshot_checksum") != manifest.get(
        "source_snapshot_checksum"
    ):
        errors.append("transform-manifest.json snapshot checksum must match the bundle")
    oracle = transform.get("mapping_oracle")
    if not isinstance(oracle, dict) or not isinstance(oracle.get("revision"), str):
        errors.append("transform-manifest.json mapping oracle revision is required")
    elif not is_sha256(oracle.get("checksum")):
        errors.append("transform-manifest.json mapping oracle checksum is required")
    strategy = transform.get("vector_strategy")
    if not isinstance(strategy, dict) or not isinstance(strategy.get("strategy"), str):
        errors.append("transform-manifest.json vector strategy evidence is required")
        return errors
    errors.extend(validate_mapping_contract(transform, manifest))
    errors.extend(validate_collection_derivation(transform))
    errors.extend(validate_vector_strategy(strategy))
    if transform.get("source_timestamp_metadata_key") != "source_timestamp":
        errors.append("transform-manifest.json source timestamp metadata key is required")
    excluded_fields = transform.get("target_fields_excluded")
    if not isinstance(excluded_fields, list) or "updated_at" not in excluded_fields:
        errors.append("transform-manifest.json must exclude target updated_at from source parity")
    return errors


def validate_mapping_contract(
    transform: dict[str, object], manifest: dict[str, object]
) -> list[str]:
    errors: list[str] = []
    mappings = transform.get("mappings")
    expected_count = transform.get("source_record_count")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1:
        return ["transform-manifest.json source_record_count must be a positive integer"]
    if not isinstance(mappings, list) or len(mappings) != expected_count:
        return ["transform-manifest.json mappings must match source_record_count"]
    source_ids: set[str] = set()
    point_ids: set[str] = set()
    for index, mapping in enumerate(mappings, start=1):
        if not isinstance(mapping, dict):
            errors.append(f"transform-manifest.json mapping {index} must be an object")
            continue
        source_id = mapping.get("source_id")
        payload_id = mapping.get("mempalace_id")
        point_id = mapping.get("point_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"transform-manifest.json mapping {index} source_id is required")
            continue
        if source_id in source_ids:
            errors.append(f"transform-manifest.json mapping {index} duplicates source_id")
        source_ids.add(source_id)
        if payload_id != source_id:
            errors.append(
                f"transform-manifest.json mapping {index} mempalace_id must equal source_id"
            )
        expected_point_id = str(uuid.uuid5(MEMPALACE_UUID_NAMESPACE, source_id))
        if point_id != expected_point_id:
            errors.append(
                f"transform-manifest.json mapping {index} point_id must use MemPalace UUIDv5"
            )
        elif not isinstance(point_id, str):
            errors.append(f"transform-manifest.json mapping {index} point_id must be a string")
        elif point_id in point_ids:
            errors.append(f"transform-manifest.json mapping {index} duplicates point_id")
        if isinstance(point_id, str):
            point_ids.add(point_id)
    return errors


def validate_collection_derivation(transform: dict[str, object]) -> list[str]:
    derivation = transform.get("collection_derivation")
    if not isinstance(derivation, dict):
        return ["transform-manifest.json collection derivation must include oracle evidence"]
    required_strings = (
        "palace_id",
        "namespace",
        "source_collection",
        "oracle_revision",
        "derived_collection",
    )
    if any(not isinstance(derivation.get(key), str) or not derivation[key] for key in required_strings) or not is_sha256(
        derivation.get("oracle_checksum")
    ):
        return ["transform-manifest.json collection derivation must include oracle evidence"]
    return []


def validate_vector_strategy(strategy: dict[str, object]) -> list[str]:
    selected = strategy.get("strategy")
    dimension = strategy.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or not 0 < dimension <= BUNDLE_BOUNDS[
        "max_vector_dimension"
    ]:
        return ["transform-manifest.json vector dimension is invalid"]
    if selected == "reuse":
        required = (
            "embedding_model",
            "embedding_configuration",
            "source_metric",
            "serialization",
        )
        if (
            any(not isinstance(strategy.get(key), str) or not strategy[key] for key in required)
            or strategy.get("target_metric") != "Cosine"
            or strategy.get("compatibility_verified") is not True
        ):
            return ["transform-manifest.json reuse strategy lacks compatibility evidence"]
        return []
    if selected == "reembed":
        required = ("local_model_artifact", "model_revision")
        if (
            any(not isinstance(strategy.get(key), str) or not strategy[key] for key in required)
            or not is_sha256(strategy.get("model_checksum"))
            or not is_sha256(strategy.get("corpus_checksum"))
        ):
            return ["transform-manifest.json reembed strategy lacks pinned local model evidence"]
        return []
    return ["transform-manifest.json vector strategy must be reuse or reembed"]


def validate_parity_report(parity: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if parity.get("status") != "passed":
        errors.append("parity-report.json status must be passed")
    if parity.get("synthetic") is not True:
        errors.append("parity-report.json synthetic must be true for an offline fixture")
    if parity.get("real_parity_evidence") is not False:
        errors.append("parity-report.json synthetic evidence cannot be real parity")
    for key in ("source_run_id", "target_run_id"):
        if not isinstance(parity.get(key), str) or not parity[key]:
            errors.append(f"parity-report.json {key} is required for a passing report")
    target = parity.get("target_collection_evidence")
    if not isinstance(target, dict) or target.get("derived") is not True:
        errors.append("parity-report.json target collection evidence is required")
    for key in ("field_comparison", "vector_comparison", "recall_comparison"):
        if not isinstance(parity.get(key), dict) or parity[key].get("passed") is not True:
            errors.append(f"parity-report.json {key} must pass")
    field_comparison = parity.get("field_comparison")
    if not isinstance(field_comparison, dict) or not isinstance(
        field_comparison.get("source_fields"), list
    ) or not field_comparison["source_fields"]:
        errors.append("parity-report.json field comparison must name source fields")
    vector_comparison = parity.get("vector_comparison")
    if not isinstance(vector_comparison, dict) or vector_comparison.get("target_metric") != "Cosine":
        errors.append("parity-report.json vector comparison must record target Cosine")
    recall_comparison = parity.get("recall_comparison")
    fixtures = (
        recall_comparison.get("fixtures") if isinstance(recall_comparison, dict) else None
    )
    if not isinstance(fixtures, list) or not fixtures:
        errors.append("parity-report.json recall comparison must contain ranked fixtures")
    elif len(fixtures) > BUNDLE_BOUNDS["max_recall_fixture_count"]:
        errors.append("parity-report.json recall fixtures exceed maximum count")
    elif not isinstance(recall_comparison.get("comparator"), str):
        errors.append("parity-report.json recall comparison must record a comparator")
    else:
        for index, fixture in enumerate(fixtures, start=1):
            if not isinstance(fixture, dict) or any(
                key not in fixture
                for key in ("filters", "ordered_ids", "source_distances", "target_distances")
            ):
                errors.append(f"parity-report.json recall fixture {index} is incomplete")
                continue
            if not isinstance(fixture["ordered_ids"], list) or not isinstance(
                fixture["source_distances"], list
            ) or not isinstance(fixture["target_distances"], list):
                errors.append(f"parity-report.json recall fixture {index} is malformed")
            elif len(fixture["ordered_ids"]) != len(fixture["source_distances"]) or len(
                fixture["ordered_ids"]
            ) != len(fixture["target_distances"]):
                errors.append(f"parity-report.json recall fixture {index} has unequal rankings")
    return errors


def validate_bundle(bundle_dir: Path) -> list[str]:
    errors: list[str] = []
    if bundle_dir.is_symlink():
        return ["bundle root must not be a symlink"]
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.is_symlink():
        return ["manifest.json must not be a symlink"]
    try:
        manifest = load_json(
            manifest_path,
            label="manifest.json",
            max_bytes=BUNDLE_BOUNDS["max_manifest_bytes"],
        )
    except ValueError as error:
        return [str(error)]
    attestations = {
        "schema_version": 1,
        "source_backend": "chroma",
        "target_backend": "qdrant",
        "legacy_writes_frozen": True,
        "embedding_strategy_recorded": True,
        "embedding_model_recorded": True,
        "embedding_dimension_recorded": True,
        "corpus_checksum_recorded": True,
        "parity_evaluation_recorded": True,
    }
    for key, expected in attestations.items():
        if manifest.get(key) != expected:
            errors.append(f"bundle {key} must be {expected!r}")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return errors + ["bundle files must be a non-empty list"]
    files_by_path: dict[str, Path] = {}
    digests_by_path: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            errors.append("every bundle file entry must be an object")
            continue
        relative = item.get("path")
        expected_digest = item.get("sha256")
        candidate = resolve_bundle_path(bundle_dir, relative)
        if candidate is None:
            if bundle_path_contains_symlink(bundle_dir, relative):
                errors.append(f"bundle path contains a symlink: {relative}")
                continue
            errors.append(f"unsafe bundle path: {relative!r}")
            continue
        if not is_sha256(expected_digest):
            errors.append(f"invalid sha256 for {relative}")
            continue
        if candidate.stat().st_size > BUNDLE_BOUNDS["max_artifact_bytes"]:
            errors.append(f"{relative} exceeds max artifact bytes")
            continue
        if sha256(candidate) != expected_digest.lower():
            errors.append(f"checksum mismatch: {relative}")
            continue
        if relative in files_by_path:
            errors.append(f"duplicate bundle file: {relative}")
            continue
        files_by_path[relative] = candidate
        digests_by_path[relative] = expected_digest
    if errors:
        return errors
    errors.extend(validate_freeze_attestation(manifest))
    references = {
        "source_inventory_reference": "source-inventory.json",
        "transform_manifest_reference": "transform-manifest.json",
        "parity_report_reference": "parity-report.json",
    }
    for key, expected_name in references.items():
        reference = manifest.get(key)
        if not isinstance(reference, str):
            errors.append(f"bundle {key} is required")
        elif reference != expected_name:
            errors.append(f"bundle {key} must reference {expected_name}")
        elif reference not in files_by_path:
            errors.append(f"bundle {expected_name} must be checksum-listed")
    if errors:
        return errors
    try:
        inventory = load_json(
            files_by_path["source-inventory.json"], label="source-inventory.json"
        )
        transform = load_json(
            files_by_path["transform-manifest.json"], label="transform-manifest.json"
        )
        parity = load_json(files_by_path["parity-report.json"], label="parity-report.json")
    except ValueError as error:
        return [str(error)]
    errors.extend(validate_inventory(inventory, manifest))
    errors.extend(validate_transform_manifest(transform, manifest))
    errors.extend(validate_parity_report(parity))
    records_reference = inventory.get("source_records_reference")
    records_path = resolve_bundle_path(bundle_dir, records_reference)
    if records_path is None:
        errors.append("source-inventory.json source_records_reference is unsafe")
    elif records_reference not in files_by_path:
        errors.append("source-inventory.json source records must be checksum-listed")
    else:
        if inventory.get("source_records_checksum") != digests_by_path[records_reference]:
            errors.append(
                "source-inventory.json source_records_checksum must match its bundle file"
            )
        mappings = transform.get("mappings")
        expected_source_ids = {
            mapping["source_id"]
            for mapping in mappings
            if isinstance(mapping, dict) and isinstance(mapping.get("source_id"), str)
        } if isinstance(mappings, list) else None
        errors.extend(validate_source_records(records_path, inventory, expected_source_ids))
    mapping_oracle = transform.get("mapping_oracle")
    collection_derivation = transform.get("collection_derivation")
    if isinstance(mapping_oracle, dict) and isinstance(collection_derivation, dict):
        if (
            mapping_oracle.get("revision") != collection_derivation.get("oracle_revision")
            or mapping_oracle.get("checksum") != collection_derivation.get("oracle_checksum")
        ):
            errors.append(
                "transform-manifest.json collection oracle must match the mapping oracle"
            )
    for artifact, evidence in (
        ("source-inventory.json", inventory),
        ("transform-manifest.json", transform),
        ("parity-report.json", parity),
    ):
        errors.extend(validate_evidence_secrets(evidence, artifact))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("config/solidstats-memory/migration-policy.json"),
    )
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        policy = load_json(args.policy)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    errors = validate_policy(policy)
    if args.bundle:
        errors.extend(validate_bundle(args.bundle))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: SolidStats memory migration policy is valid")
    if args.bundle:
        print(f"PASS: offline bundle checksums are valid: {args.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
