#!/usr/bin/env python3
"""Validate the SolidStats memory policy and an optional offline bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


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
    "synthetic_parity_is_non_production": True,
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
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
    """Return a safe bundle path without following malformed references."""
    if not isinstance(relative, str):
        return None
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return bundle_dir / candidate


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
    return errors


def validate_bundle(bundle_dir: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_json(bundle_dir / "manifest.json")
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
    for item in files:
        if not isinstance(item, dict):
            errors.append("every bundle file entry must be an object")
            continue
        relative = item.get("path")
        expected_digest = item.get("sha256")
        candidate = resolve_bundle_path(bundle_dir, relative)
        if candidate is None:
            errors.append(f"unsafe bundle path: {relative!r}")
            continue
        if not is_sha256(expected_digest):
            errors.append(f"invalid sha256 for {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"missing bundle file: {relative}")
            continue
        if sha256(candidate) != expected_digest.lower():
            errors.append(f"checksum mismatch: {relative}")
            continue
        if relative in files_by_path:
            errors.append(f"duplicate bundle file: {relative}")
            continue
        files_by_path[relative] = candidate
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
        inventory = load_json(files_by_path["source-inventory.json"])
        transform = load_json(files_by_path["transform-manifest.json"])
        parity = load_json(files_by_path["parity-report.json"])
    except ValueError as error:
        return [str(error)]
    errors.extend(validate_inventory(inventory, manifest))
    errors.extend(validate_transform_manifest(transform, manifest))
    errors.extend(validate_parity_report(parity))
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
