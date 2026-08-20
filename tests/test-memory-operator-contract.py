#!/usr/bin/env python3
"""Observable contract tests for the private Phase 21 operator boundary."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/operate-solidstats-memory.py"
SPEC = importlib.util.spec_from_file_location("solidstats_memory_operator", MODULE_PATH)
assert SPEC and SPEC.loader
OPERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OPERATOR)


class MemoryOperatorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.rendered = {
            "schema": OPERATOR.SCHEMA,
            "files": [{"name": "10-qdrant.yaml", "sha256": "1" * 64}],
            "digest": "2" * 64,
        }
        self.prestate = {
            "active_alias_sha256": "1" * 64,
            "nginx_sha256": "2" * 64,
            "mcp_registration_sha256": "3" * 64,
            "legacy_runtime_sha256": "4" * 64,
            "schedule_sha256": "5" * 64,
        }
        self.valid = {
            "inspect-preflight": {
                "bindings": {"binding_sha256": "1" * 64},
                "expected_count": 3,
            },
            "render-manifests": {
                "operator_markers": {
                    "qdrant_storage": "4Gi",
                    "mempalace_storage": "2Gi",
                    "mempalace_image": "example.invalid/mempalace@sha256:" + "1" * 64,
                    "backup_cidr": "192.0.2.1/32",
                    "uploader_image": "example.invalid/uploader@sha256:" + "2" * 64,
                    "private_collection": "candidate",
                },
                "target_set": list(OPERATOR.TARGETS),
            },
            "validate-manifests": {"rendered": self.rendered, "mode": "client"},
            "apply-manifests": {"rendered": self.rendered},
            "inspect-runtime": {},
            "load-backup-inputs": {},
            "apply-backup-job": {"job_path": str(self.root / "job.json")},
            "wait-backup-job": {},
            "remote-package-inventory": {},
            "download-backup-package": {"package_dir": str(self.root / "package")},
            "recover-uploaded-snapshot": {
                "target_collection": "restored",
                "snapshot_path": str(self.root / "snapshot"),
                "priority": "snapshot",
            },
            "qdrant-request": {"method": "GET", "path": "/collections", "body": None},
            "run-phase20-parity": {},
            "run-exact-image-probe": {},
            "verify-prestate": {"prestate": self.prestate},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_every_adapter_operation_has_one_exact_accepted_shape(self) -> None:
        self.assertEqual(OPERATOR.OPERATIONS, set(self.valid))
        for operation, payload in self.valid.items():
            with self.subTest(operation=operation):
                self.assertEqual(
                    payload,
                    OPERATOR.validate_operation_payload(operation, payload),
                )

    def test_every_adapter_operation_rejects_missing_and_extra_fields(self) -> None:
        for operation, payload in self.valid.items():
            with self.subTest(operation=operation, mutation="extra"):
                invalid = dict(payload)
                invalid["unexpected"] = True
                with self.assertRaises(OPERATOR.OperatorError):
                    OPERATOR.validate_operation_payload(operation, invalid)
            if payload:
                with self.subTest(operation=operation, mutation="missing"):
                    invalid = dict(payload)
                    invalid.pop(next(iter(invalid)))
                    with self.assertRaises(OPERATOR.OperatorError):
                        OPERATOR.validate_operation_payload(operation, invalid)

    def test_high_risk_payloads_reject_bypass_shapes(self) -> None:
        mutations = [
            ("inspect-preflight", {"bindings": {}, "expected_count": 3}),
            (
                "render-manifests",
                {
                    **self.valid["render-manifests"],
                    "target_set": ["k8s/memory/10-qdrant.yaml"],
                },
            ),
            (
                "validate-manifests",
                {"rendered": self.rendered, "mode": "apply"},
            ),
            ("apply-backup-job", {"job_path": "relative.json"}),
            ("download-backup-package", {"package_dir": "relative"}),
            (
                "recover-uploaded-snapshot",
                {
                    "target_collection": "restored",
                    "snapshot_path": str(self.root / "snapshot"),
                    "priority": "replica",
                },
            ),
            (
                "qdrant-request",
                {"method": "PATCH", "path": "/collections", "body": None},
            ),
            ("verify-prestate", {"prestate": {"active_alias_sha256": "1" * 64}}),
        ]
        for operation, payload in mutations:
            with self.subTest(operation=operation):
                with self.assertRaises(OPERATOR.OperatorError):
                    OPERATOR.validate_operation_payload(operation, payload)

    def test_unknown_operation_and_non_mapping_payload_are_denied(self) -> None:
        for operation, payload in (("shell", {}), ("inspect-runtime", [])):
            with self.subTest(operation=operation):
                with self.assertRaises(OPERATOR.OperatorError):
                    OPERATOR.validate_operation_payload(operation, payload)

    def test_private_response_is_exclusive_mode_0600_and_value_preserving(self) -> None:
        response = self.root / "response.json"
        value = {"ok": True, "result": {"valid": True}}
        OPERATOR.write_private(response, value)
        self.assertEqual(0o600, stat.S_IMODE(response.stat().st_mode))
        self.assertEqual(value, json.loads(response.read_bytes()))
        with self.assertRaises(OPERATOR.OperatorError):
            OPERATOR.write_private(response, value)

    def test_private_input_rejects_group_readable_mode(self) -> None:
        request = self.root / "request.json"
        request.write_text("{}\n", encoding="utf-8")
        os.chmod(request, 0o640)
        with self.assertRaisesRegex(OPERATOR.OperatorError, "mode"):
            OPERATOR.load_json(request, private=True)

    def test_cli_denies_wrong_arity_unknown_operation_and_relative_paths(self) -> None:
        self.assertEqual(64, OPERATOR.main([]))
        self.assertEqual(64, OPERATOR.main(["shell", "/request", "/response"]))
        self.assertEqual(
            64,
            OPERATOR.main(["inspect-runtime", "request.json", "response.json"]),
        )


if __name__ == "__main__":
    unittest.main()
