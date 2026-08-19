#!/usr/bin/env python3
"""Contract tests for synthetic SolidStats memory migration bundles."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-solidstats-memory-policy.py"
SPEC = importlib.util.spec_from_file_location("memory_policy_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def write_synthetic_bundle(bundle: Path) -> dict[str, object]:
    records = bundle / "source-records.jsonl"
    records.write_text(
        '{"document":"synthetic document","id":"source-1",'
        '"metadata":{"source_timestamp":"2026-08-20T00:00:00Z"}}\n',
        encoding="utf-8",
    )
    snapshot_checksum = VALIDATOR.sha256(records)
    inventory = {
        "record_count": 1,
        "source_records_checksum": snapshot_checksum,
        "source_records_reference": records.name,
        "source_snapshot_checksum": snapshot_checksum,
    }
    transform = {
        "mapping_oracle": {
            "checksum": "a" * 64,
            "revision": "v3.5.0",
        },
        "source_inventory_reference": "source-inventory.json",
        "source_snapshot_checksum": snapshot_checksum,
        "vector_strategy": {
            "evidence": "synthetic-only",
            "strategy": "reembed",
        },
    }
    parity = {
        "field_comparison": {"passed": True},
        "real_parity_evidence": False,
        "recall_comparison": {"passed": True},
        "source_run_id": "synthetic-source-run",
        "status": "passed",
        "synthetic": True,
        "target_collection_evidence": {"derived": True, "name": "synthetic"},
        "target_run_id": "synthetic-target-run",
        "vector_comparison": {"passed": True},
    }
    for name, artifact in (
        ("source-inventory.json", inventory),
        ("transform-manifest.json", transform),
        ("parity-report.json", parity),
    ):
        write_json(bundle / name, artifact)
    manifest = {
        "corpus_checksum_recorded": True,
        "embedding_dimension_recorded": True,
        "embedding_model_recorded": True,
        "embedding_strategy_recorded": True,
        "files": [
            {
                "path": name,
                "sha256": VALIDATOR.sha256(bundle / name),
            }
            for name in (
                records.name,
                "source-inventory.json",
                "transform-manifest.json",
                "parity-report.json",
            )
        ],
        "legacy_writes_frozen": True,
        "parity_evaluation_recorded": True,
        "schema_version": 1,
        "source_backend": "chroma",
        "source_inventory_reference": "source-inventory.json",
        "source_snapshot_checksum": snapshot_checksum,
        "target_backend": "qdrant",
        "transform_manifest_reference": "transform-manifest.json",
        "write_freeze_at": "2026-08-20T00:00:00Z",
        "parity_report_reference": "parity-report.json",
    }
    write_json(bundle / "manifest.json", manifest)
    return manifest


class MigrationContractTests(unittest.TestCase):
    def test_synthetic_bundle_passes_the_public_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            self.assertEqual([], VALIDATOR.validate_bundle(bundle))

    def test_missing_freeze_or_artifact_reference_fails_precisely(self) -> None:
        missing_cases = {
            "write_freeze_at": "bundle write_freeze_at must be a UTC timestamp",
            "source_snapshot_checksum": "bundle source_snapshot_checksum must be a lowercase sha256",
            "source_inventory_reference": "bundle source_inventory_reference is required",
            "transform_manifest_reference": "bundle transform_manifest_reference is required",
            "parity_report_reference": "bundle parity_report_reference is required",
        }
        for field, expected_error in missing_cases.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                bundle = Path(temporary)
                manifest = write_synthetic_bundle(bundle)
                manifest.pop(field)
                write_json(bundle / "manifest.json", manifest)
                self.assertIn(expected_error, VALIDATOR.validate_bundle(bundle))

    def test_passing_parity_requires_isolated_target_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            parity_path = bundle / "parity-report.json"
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity.pop("target_run_id")
            write_json(parity_path, parity)
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            for item in manifest["files"]:
                if item["path"] == parity_path.name:
                    item["sha256"] = VALIDATOR.sha256(parity_path)
            write_json(bundle / "manifest.json", manifest)
            self.assertIn(
                "parity-report.json target_run_id is required for a passing report",
                VALIDATOR.validate_bundle(bundle),
            )


if __name__ == "__main__":
    unittest.main()
