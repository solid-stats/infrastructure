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
    for item in files:
        if not isinstance(item, dict):
            errors.append("every bundle file entry must be an object")
            continue
        relative = item.get("path")
        expected_digest = item.get("sha256")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            errors.append(f"unsafe bundle path: {relative!r}")
            continue
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            errors.append(f"invalid sha256 for {relative}")
            continue
        candidate = bundle_dir / relative
        if not candidate.is_file():
            errors.append(f"missing bundle file: {relative}")
            continue
        if sha256(candidate) != expected_digest.lower():
            errors.append(f"checksum mismatch: {relative}")
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
