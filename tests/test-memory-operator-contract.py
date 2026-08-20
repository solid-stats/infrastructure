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
from unittest import mock


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

    def test_preflight_uses_live_probes_when_target_namespace_is_absent(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.state_root = self.root
        runtime.config = {
            "expected_count": 3,
            "qdrant_storage": "4Gi",
            "mempalace_storage": "2Gi",
            "mempalace_image": OPERATOR.OFFICIAL_MEMPALACE_IMAGE,
            "backup_cidr": "192.0.2.1/32",
            "uploader_image": "example.invalid/uploader@sha256:" + "2" * 64,
            "private_collection": "candidate",
        }
        prestate = {
            "active_alias_sha256": "1" * 64,
            "nginx_sha256": "2" * 64,
            "mcp_registration_sha256": "3" * 64,
            "legacy_runtime_sha256": "4" * 64,
            "schedule_sha256": "5" * 64,
        }
        capacity = {
            "snapshot_bytes": 10,
            "pvc_requested_bytes": 4 * 1024**3,
            "node_free_bytes": 8 * 1024**3,
            "reserve_bytes": 1024**3,
        }
        with (
            mock.patch.object(runtime, "_namespace_exists", return_value=False),
            mock.patch.object(runtime, "_kubectl"),
            mock.patch.object(runtime, "_verify_mempalace_registry_image") as registry,
            mock.patch.object(runtime, "_probe_s3") as s3,
            mock.patch.object(
                runtime,
                "_measure_prestate",
                return_value=(prestate, {"stable": True, "writer_count": 0}),
            ) as state,
            mock.patch.object(runtime, "_measure_capacity", return_value=capacity) as measured,
        ):
            result = runtime.inspect_preflight(self.valid["inspect-preflight"])
        self.assertEqual(capacity, result["capacity"])
        registry.assert_called_once_with()
        s3.assert_called_once_with()
        state.assert_called_once_with()
        measured.assert_called_once_with()

    def test_capacity_uses_retained_snapshot_and_live_node_not_bundle_total(self) -> None:
        bundle = self.root / "bundle"
        bundle.mkdir(mode=0o700)
        (bundle / "qdrant.snapshot").write_bytes(b"snapshot")
        (bundle / "points.jsonl").write_bytes(b"x" * 4096)
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.bundle_dir = bundle
        runtime.config = {"qdrant_storage": "4Gi"}
        storage_classes = {
            "items": [
                {
                    "metadata": {
                        "annotations": {
                            "storageclass.kubernetes.io/is-default-class": "true"
                        }
                    },
                    "provisioner": "rancher.io/local-path",
                    "volumeBindingMode": "WaitForFirstConsumer",
                }
            ]
        }
        node_result = {"items": [{"metadata": {"name": "node-1"}}]}
        summary = {"node": {"fs": {"availableBytes": 7 * 1024**3}}}
        with (
            mock.patch.object(
                runtime,
                "_kubectl_json",
                side_effect=[storage_classes, node_result],
            ),
            mock.patch.object(runtime, "_raw_kubernetes_json", return_value=summary),
        ):
            capacity = runtime._measure_capacity()
        self.assertEqual(len(b"snapshot"), capacity["snapshot_bytes"])
        self.assertEqual(4 * 1024**3, capacity["pvc_requested_bytes"])
        self.assertEqual(7 * 1024**3, capacity["node_free_bytes"])

    def test_capacity_rejects_missing_retained_snapshot(self) -> None:
        bundle = self.root / "missing-snapshot"
        bundle.mkdir(mode=0o700)
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.bundle_dir = bundle
        runtime.config = {"qdrant_storage": "4Gi"}
        with self.assertRaisesRegex(OPERATOR.OperatorError, "private file"):
            runtime._measure_capacity()

    def test_runtime_capacity_uses_bound_pvc_and_in_volume_df(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        pvc = {"status": {"capacity": {"storage": "4Gi"}}}
        with (
            mock.patch.object(runtime, "_kubectl_json", return_value=pvc),
            mock.patch.object(
                runtime,
                "_kubectl",
                return_value=(
                    b"Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                    b"/dev/sda 4194304 1024 4193280 1% /qdrant/storage\n"
                ),
            ),
        ):
            capacity = runtime._inspect_live_pvc_capacity()
        self.assertEqual(4 * 1024**3, capacity["pvc_capacity_bytes"])
        self.assertEqual(4193280 * 1024, capacity["pvc_free_bytes"])

    def test_registry_probe_rejects_local_or_unapproved_image_before_network(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.config = {
            "mempalace_image": "local.invalid/mempalace@sha256:" + "3" * 64
        }
        with (
            mock.patch.object(runtime, "_registry_request") as request,
            self.assertRaisesRegex(OPERATOR.OperatorError, "approved registry"),
        ):
            runtime._verify_mempalace_registry_image()
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
