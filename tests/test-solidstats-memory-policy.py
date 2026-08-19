#!/usr/bin/env python3
"""Tests for the SolidStats memory migration policy validator."""

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


class PolicyTests(unittest.TestCase):
    def test_committed_policy_is_valid(self) -> None:
        policy = VALIDATOR.load_json(
            ROOT / "config" / "solidstats-memory" / "migration-policy.json"
        )
        self.assertEqual([], VALIDATOR.validate_policy(policy))

    def test_enabled_legacy_feature_is_rejected(self) -> None:
        policy = VALIDATOR.load_json(
            ROOT / "config" / "solidstats-memory" / "migration-policy.json"
        )
        policy["mirror_kg"] = True
        self.assertIn("mirror_kg: must be false", VALIDATOR.validate_policy(policy))

    def test_archive_extractors_cannot_write(self) -> None:
        policy = VALIDATOR.load_json(
            ROOT / "config" / "solidstats-memory" / "migration-policy.json"
        )
        distillation = dict(policy["archive_distillation"])
        distillation["extractors_can_write"] = True
        policy["archive_distillation"] = distillation
        self.assertTrue(
            any(
                error.startswith("archive_distillation:")
                for error in VALIDATOR.validate_policy(policy)
            )
        )

    def test_bundle_requires_matching_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            payload = bundle / "payload.jsonl"
            payload.write_text("{}\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "source_backend": "chroma",
                "target_backend": "qdrant",
                "legacy_writes_frozen": True,
                "embedding_strategy_recorded": True,
                "embedding_model_recorded": True,
                "embedding_dimension_recorded": True,
                "corpus_checksum_recorded": True,
                "parity_evaluation_recorded": True,
                "files": [{"path": payload.name, "sha256": "0" * 64}],
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                ["checksum mismatch: payload.jsonl"],
                VALIDATOR.validate_bundle(bundle),
            )

    def test_bundle_rejects_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            manifest = {
                "schema_version": 1,
                "source_backend": "chroma",
                "target_backend": "qdrant",
                "legacy_writes_frozen": True,
                "embedding_strategy_recorded": True,
                "embedding_model_recorded": True,
                "embedding_dimension_recorded": True,
                "corpus_checksum_recorded": True,
                "parity_evaluation_recorded": True,
                "files": [{"path": "../payload", "sha256": "0" * 64}],
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                ["unsafe bundle path: '../payload'"],
                VALIDATOR.validate_bundle(bundle),
            )

    def test_bundle_requires_embedding_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            payload = bundle / "payload.jsonl"
            payload.write_text("{}\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "source_backend": "chroma",
                "target_backend": "qdrant",
                "legacy_writes_frozen": True,
                "embedding_strategy_recorded": False,
                "embedding_model_recorded": True,
                "embedding_dimension_recorded": True,
                "corpus_checksum_recorded": True,
                "parity_evaluation_recorded": True,
                "files": [
                    {"path": payload.name, "sha256": VALIDATOR.sha256(payload)}
                ],
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                ["bundle embedding_strategy_recorded must be True"],
                VALIDATOR.validate_bundle(bundle),
            )


if __name__ == "__main__":
    unittest.main()
