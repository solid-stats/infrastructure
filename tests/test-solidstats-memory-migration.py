#!/usr/bin/env python3
"""Contract tests for synthetic SolidStats memory migration bundles."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-solidstats-memory-policy.py"
SPEC = importlib.util.spec_from_file_location("memory_policy_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
UUID_NAMESPACE = uuid.UUID("c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def refresh_manifest_digest(bundle: Path, name: str) -> None:
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["path"] == name:
            item["sha256"] = VALIDATOR.sha256(bundle / name)
    write_json(manifest_path, manifest)


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
        "collection_derivation": {
            "derived_collection": "mempalace-solidstats-synthetic",
            "namespace": "solidstats",
            "oracle_checksum": "a" * 64,
            "oracle_revision": "v3.5.0",
            "palace_id": "synthetic-palace",
            "source_collection": "records",
        },
        "mapping_oracle": {
            "checksum": "a" * 64,
            "revision": "v3.5.0",
        },
        "mappings": [
            {
                "mempalace_id": "source-1",
                "point_id": str(uuid.uuid5(UUID_NAMESPACE, "source-1")),
                "source_id": "source-1",
            }
        ],
        "source_record_count": 1,
        "source_inventory_reference": "source-inventory.json",
        "source_snapshot_checksum": snapshot_checksum,
        "source_timestamp_metadata_key": "source_timestamp",
        "target_fields_excluded": ["updated_at"],
        "vector_strategy": {
            "corpus_checksum": snapshot_checksum,
            "dimension": 3,
            "evidence": "synthetic-only",
            "local_model_artifact": "synthetic-model.bin",
            "model_checksum": "b" * 64,
            "model_revision": "synthetic-v1",
            "strategy": "reembed",
        },
    }
    parity = {
        "field_comparison": {"passed": True, "source_fields": ["document", "metadata"]},
        "real_parity_evidence": False,
        "recall_comparison": {
            "comparator": "ordered-id-and-distance",
            "fixtures": [
                {
                    "filters": {"wing": "SolidStats"},
                    "ordered_ids": ["source-1"],
                    "source_distances": [0.0],
                    "target_distances": [0.0],
                }
            ],
            "passed": True,
        },
        "source_run_id": "synthetic-source-run",
        "status": "passed",
        "synthetic": True,
        "target_collection_evidence": {"derived": True, "name": "synthetic"},
        "target_run_id": "synthetic-target-run",
        "vector_comparison": {"passed": True, "target_metric": "Cosine"},
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


class UntrustedBundleTests(unittest.TestCase):
    def test_symlinked_bundle_file_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            bundle.mkdir()
            write_synthetic_bundle(bundle)
            outside = root / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            linked = bundle / "linked-records.jsonl"
            linked.symlink_to(outside)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["files"]:
                if item["path"] == "source-records.jsonl":
                    item["path"] = linked.name
                    item["sha256"] = VALIDATOR.sha256(linked)
            write_json(manifest_path, manifest)
            errors = VALIDATOR.validate_bundle(bundle)
            self.assertIn("bundle path contains a symlink: linked-records.jsonl", errors)

    def test_lossy_source_records_are_rejected_without_echoing_values(self) -> None:
        cases = {
            '{"document":"secret document","id":"source-1","metadata":[]}\n':
                "source-records.jsonl record 1 metadata must be an object",
            '{"document":"secret document","id":"source-1","metadata":{}}\n':
                "source-records.jsonl record 1 source timestamp is required",
            '{"id":"source-1","metadata":{"source_timestamp":"2026-08-20T00:00:00Z"}}\n':
                "source-records.jsonl record 1 document must be a string",
        }
        for records_text, expected_error in cases.items():
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as temporary:
                bundle = Path(temporary)
                write_synthetic_bundle(bundle)
                records = bundle / "source-records.jsonl"
                records.write_text(records_text, encoding="utf-8")
                refresh_manifest_digest(bundle, records.name)
                errors = VALIDATOR.validate_bundle(bundle)
                self.assertIn(expected_error, errors)
                self.assertNotIn("secret document", "\n".join(errors))

    def test_duplicate_ids_and_non_lossless_metadata_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            records = bundle / "source-records.jsonl"
            records.write_text(
                '{"document":"first","id":"source-1",'
                '"metadata":{"source_timestamp":"2026-08-20T00:00:00Z"}}\n'
                '{"document":"second","id":"source-1",'
                '"metadata":{"source_timestamp":"2026-08-20T00:00:00Z","value":NaN}}\n',
                encoding="utf-8",
            )
            refresh_manifest_digest(bundle, records.name)
            errors = VALIDATOR.validate_bundle(bundle)
            self.assertIn("source-records.jsonl duplicate source ID at record 2", errors)
            self.assertIn("source-records.jsonl record 2 metadata is not lossless JSON", errors)

    def test_policy_bounds_stop_oversized_artifacts_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            records = bundle / "source-records.jsonl"
            records.write_bytes(
                b"x" * (VALIDATOR.BUNDLE_BOUNDS["max_artifact_bytes"] + 1)
            )
            refresh_manifest_digest(bundle, records.name)
            errors = VALIDATOR.validate_bundle(bundle)
            self.assertIn("source-records.jsonl exceeds max artifact bytes", errors)

    def test_secret_shaped_report_values_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            parity_path = bundle / "parity-report.json"
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["authorization"] = "Bearer private-test-token"
            write_json(parity_path, parity)
            refresh_manifest_digest(bundle, parity_path.name)
            errors = VALIDATOR.validate_bundle(bundle)
            diagnostics = "\n".join(errors)
            self.assertIn("parity-report.json contains credential-shaped value at $.authorization", errors)
            self.assertNotIn("private-test-token", diagnostics)


class MappingContractTests(unittest.TestCase):
    def test_mapping_requires_matching_payload_id_and_uuidv5_point_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            transform_path = bundle / "transform-manifest.json"
            transform = json.loads(transform_path.read_text(encoding="utf-8"))
            transform["mappings"][0]["mempalace_id"] = "wrong-id"
            write_json(transform_path, transform)
            refresh_manifest_digest(bundle, transform_path.name)
            self.assertIn(
                "transform-manifest.json mapping 1 mempalace_id must equal source_id",
                VALIDATOR.validate_bundle(bundle),
            )

    def test_collection_requires_oracle_derived_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            transform_path = bundle / "transform-manifest.json"
            transform = json.loads(transform_path.read_text(encoding="utf-8"))
            transform["collection_derivation"] = {"target_collection": "manual-name"}
            write_json(transform_path, transform)
            refresh_manifest_digest(bundle, transform_path.name)
            self.assertIn(
                "transform-manifest.json collection derivation must include oracle evidence",
                VALIDATOR.validate_bundle(bundle),
            )

    def test_vector_reuse_requires_full_compatibility_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            transform_path = bundle / "transform-manifest.json"
            transform = json.loads(transform_path.read_text(encoding="utf-8"))
            transform["vector_strategy"] = {
                "dimension": 3,
                "strategy": "reuse",
            }
            write_json(transform_path, transform)
            refresh_manifest_digest(bundle, transform_path.name)
            self.assertIn(
                "transform-manifest.json reuse strategy lacks compatibility evidence",
                VALIDATOR.validate_bundle(bundle),
            )

    def test_parity_requires_ranked_recall_comparison_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            write_synthetic_bundle(bundle)
            parity_path = bundle / "parity-report.json"
            parity = json.loads(parity_path.read_text(encoding="utf-8"))
            parity["recall_comparison"] = {"passed": True}
            write_json(parity_path, parity)
            refresh_manifest_digest(bundle, parity_path.name)
            self.assertIn(
                "parity-report.json recall comparison must contain ranked fixtures",
                VALIDATOR.validate_bundle(bundle),
            )


if __name__ == "__main__":
    unittest.main()
