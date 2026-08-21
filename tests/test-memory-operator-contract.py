#!/usr/bin/env python3
"""Observable contract tests for the private Phase 21 operator boundary."""

from __future__ import annotations

import importlib.util
import base64
import hashlib
import hmac
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

    def test_probe_alias_derivation_matches_pinned_v350_contract(self) -> None:
        expected = (
            "mempalace_SolidStats_"
            + hashlib.sha256(b"/data/palace").hexdigest()[:16]
            + "_mempalace_drawers"
        )
        self.assertEqual(
            expected,
            OPERATOR.mempalace_collection_name(
                palace_id="/data/palace",
                namespace="SolidStats",
                collection_name="mempalace_drawers",
            ),
        )

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
            mock.patch.object(runtime, "_verify_uploader_registry_image") as uploader,
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
        uploader.assert_called_once_with()
        s3.assert_called_once_with()
        state.assert_called_once_with()
        measured.assert_called_once_with()

        with (
            mock.patch.object(runtime, "_namespace_exists", return_value=False),
            mock.patch.object(runtime, "_kubectl"),
            mock.patch.object(runtime, "_verify_mempalace_registry_image"),
            mock.patch.object(runtime, "_verify_uploader_registry_image"),
            mock.patch.object(runtime, "_probe_s3"),
            mock.patch.object(
                runtime,
                "_measure_prestate",
                return_value=(prestate, {"stable": True, "writer_count": 0}),
            ),
            mock.patch.object(runtime, "_measure_capacity", return_value=capacity),
        ):
            replay = runtime.inspect_preflight(self.valid["inspect-preflight"])
        self.assertEqual(result, replay)

        changed = {**prestate, "nginx_sha256": "6" * 64}
        with (
            mock.patch.object(runtime, "_namespace_exists", return_value=False),
            mock.patch.object(runtime, "_kubectl"),
            mock.patch.object(runtime, "_verify_mempalace_registry_image"),
            mock.patch.object(runtime, "_verify_uploader_registry_image"),
            mock.patch.object(runtime, "_probe_s3"),
            mock.patch.object(
                runtime,
                "_measure_prestate",
                return_value=(changed, {"stable": True, "writer_count": 0}),
            ),
            mock.patch.object(runtime, "_measure_capacity", return_value=capacity),
        ):
            with self.assertRaisesRegex(OPERATOR.OperatorError, "collision"):
                runtime.inspect_preflight(self.valid["inspect-preflight"])

    def test_s3_probe_uses_checked_in_region_without_vendor_head_header(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime._source_s3_values = mock.Mock(
            return_value={
                "S3_ACCESS_KEY_ID": "access-key",
                "S3_SECRET_ACCESS_KEY": "secret-key",
                "S3_BUCKET": "solidstats-backups",
            }
        )
        head_response = mock.Mock()
        signed_response = mock.MagicMock()
        signed_response.read.return_value = b"<ListBucketResult/>"
        with mock.patch.object(
            OPERATOR.urllib_request,
            "urlopen",
            side_effect=[head_response, signed_response],
        ) as urlopen:
            runtime._probe_s3()

        head_request = urlopen.call_args_list[0].args[0]
        signed_request = urlopen.call_args_list[1].args[0]
        self.assertEqual("HEAD", head_request.get_method())
        self.assertIn(
            f"/{OPERATOR.S3_REGION}/s3/aws4_request",
            signed_request.get_header("Authorization"),
        )
        head_response.close.assert_called_once_with()

    def test_server_dry_run_uses_the_existing_substitute_namespace(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.state_root = self.root
        runtime.render_root = self.root / "rendered"
        runtime.render_root.mkdir(mode=0o700)
        runtime.source_secret_namespace = "existing-runtime"
        for relative in OPERATOR.TARGETS:
            (runtime.render_root / Path(relative).name).write_text(
                f"metadata:\n  namespace: {OPERATOR.NAMESPACE}\n",
                encoding="utf-8",
            )
        with (
            mock.patch.object(runtime, "_require_rendered", return_value={}),
            mock.patch.object(runtime, "_namespace_exists", return_value=False),
            mock.patch.object(runtime, "_kubectl") as kubectl,
        ):
            result = runtime.validate_manifests({"rendered": {}, "mode": "server"})

        self.assertEqual({"valid": True}, result)
        arguments = kubectl.call_args.args[0]
        self.assertEqual(["-n", "existing-runtime", "apply"], arguments[:3])
        self.assertEqual("--server-side", arguments[3])
        self.assertEqual("--dry-run=server", arguments[4])
        for relative in OPERATOR.TARGETS:
            rendered = (
                runtime.state_root / "server-dry-run" / Path(relative).name
            ).read_text(encoding="utf-8")
            self.assertIn("namespace: existing-runtime", rendered)
            self.assertNotIn(f"namespace: {OPERATOR.NAMESPACE}", rendered)

    def test_client_state_matches_only_exact_solidstats_registrations(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        entries = [
            {
                "name": "mempalace",
                "enabled": True,
                "url": OPERATOR.LEGACY_SOLIDSTATS_MCP_URL,
            },
            {
                "name": "solidstats_memory",
                "enabled": True,
                "transport": {"url": OPERATOR.MEMORY_PUBLIC_URL},
            },
            {
                "name": "mempalace_personal",
                "enabled": True,
                "url": "https://personal.invalid/mempalace",
            },
            {
                "name": "vocalclub_memory",
                "enabled": True,
                "url": "https://vocalclub.invalid/solidstats-looking-path",
            },
            {
                "name": "mempalace",
                "enabled": True,
                "url": "https://foreign.invalid/solidstats/mcp",
            },
        ]
        with mock.patch.object(runtime, "_run", return_value=json.dumps(entries).encode()):
            state, writer_count = runtime._mcp_client_state()
        self.assertEqual(writer_count, 0)
        self.assertEqual(len(state["legacy"]), 1)
        self.assertEqual(len(state["replacement"]), 1)
        self.assertEqual(
            state["replacement"][0]["write_capability"],
            "unproven-by-registration",
        )
        self.assertEqual(
            state["legacy"][0]["write_capability"],
            "frozen-read-only-contract",
        )
        self.assertNotIn("personal.invalid", json.dumps(state))
        self.assertNotIn("vocalclub.invalid", json.dumps(state))

    def test_legacy_read_registration_is_not_counted_as_active_writer(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        entry = {
            "name": "mempalace",
            "enabled": True,
            "url": OPERATOR.LEGACY_SOLIDSTATS_MCP_URL,
        }
        with mock.patch.object(runtime, "_run", return_value=json.dumps([entry]).encode()):
            state, writer_count = runtime._mcp_client_state()
        self.assertEqual(writer_count, 0)
        self.assertTrue(state["legacy"][0]["enabled"])

    def test_enabled_replacement_blocks_quiescence_without_being_called_writer(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        client_state = {
            "registration_sha256": "1" * 64,
            "legacy": [],
            "replacement": [{"enabled": True}],
        }
        with (
            mock.patch.object(runtime, "_namespace_exists", return_value=False),
            mock.patch.object(
                runtime, "_mcp_client_state", return_value=(client_state, 0)
            ),
            mock.patch.object(
                runtime,
                "_public_route_state",
                return_value={"url_binding": "2" * 64, "status": 404},
            ),
        ):
            _prestate, quiescence = runtime._measure_prestate()
        self.assertEqual(quiescence, {"stable": False, "writer_count": 0})

    def test_runtime_secrets_never_distribute_admin_key_to_consumers(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.qdrant_key = self.root / "admin"
        runtime.mcp_token = self.root / "mcp"
        runtime.qdrant_key.write_text("synthetic-admin-key", encoding="ascii")
        runtime.mcp_token.write_text("synthetic-mcp-token", encoding="ascii")
        runtime.config = {"private_collection": "synthetic-own-collection"}
        applied = []

        def kubectl(_arguments, **kwargs):
            applied.append(kwargs["input_value"])
            return b""

        with (
            mock.patch.object(
                runtime,
                "_source_s3_values",
                return_value={
                    "S3_BUCKET": "bucket",
                    "S3_ACCESS_KEY_ID": "access",
                    "S3_SECRET_ACCESS_KEY": "secret",
                },
            ),
            mock.patch.object(runtime, "_kubectl", side_effect=kubectl),
        ):
            runtime._apply_runtime_secrets()
        by_name = {item["metadata"]["name"]: item["stringData"] for item in applied}
        self.assertEqual(by_name["qdrant-runtime"]["QDRANT_API_KEY"], "synthetic-admin-key")
        for name, key in (
            ("mempalace-runtime", "MEMPALACE_QDRANT_API_KEY"),
            ("memory-backup-runtime", "QDRANT_API_KEY"),
            ("memory-observer-runtime", "QDRANT_API_KEY"),
        ):
            self.assertNotEqual(by_name[name][key], "synthetic-admin-key")
            header, payload, signature = by_name[name][key].split(".")
            actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            expected = hmac.new(
                b"synthetic-admin-key",
                f"{header}.{payload}".encode("ascii"),
                hashlib.sha256,
            ).digest()
            self.assertTrue(hmac.compare_digest(actual, expected))
        mempalace_payload = by_name["mempalace-runtime"]["MEMPALACE_QDRANT_API_KEY"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(mempalace_payload + "=" * (-len(mempalace_payload) % 4)))
        self.assertEqual(
            claims["access"],
            [{"collection": "synthetic-own-collection", "access": "rw"}],
        )
        self.assertNotIn("synthetic-foreign-collection", json.dumps(claims))

    def test_capacity_uses_retained_snapshot_and_live_node_not_bundle_total(self) -> None:
        bundle = self.root / "bundle"
        bundle.mkdir(mode=0o700)
        (bundle / "qdrant.snapshot").write_bytes(b"snapshot")
        (bundle / "points.jsonl").write_bytes(b"x" * 4096)
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.bundle_dir = bundle
        runtime.baseline_snapshot = bundle / "qdrant.snapshot"
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
        runtime.baseline_snapshot = bundle / "qdrant.snapshot"
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

    def test_uploader_probe_rejects_unapproved_image_before_network(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.config = {
            "uploader_image": "example.invalid/uploader@sha256:" + "3" * 64
        }
        with (
            mock.patch.object(runtime, "_run") as run,
            self.assertRaisesRegex(OPERATOR.OperatorError, "approved registry"),
        ):
            runtime._verify_uploader_registry_image()
        run.assert_not_called()

    def test_remote_inventory_uses_only_pinned_aws_cli_without_secret_argv(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.state_root = self.root / "run-id" / "operator"
        runtime.config = {"uploader_image": OPERATOR.OFFICIAL_AWS_CLI_IMAGE}
        values = {
            "S3_BUCKET": "synthetic-bucket",
            "S3_ACCESS_KEY_ID": "synthetic-access",
            "S3_SECRET_ACCESS_KEY": "synthetic-secret",
        }
        listing = "".join(
            f"2026-08-21 00:00:00 1 {name}\n" for name in OPERATOR.PACKAGE_MEMBERS
        ).encode()
        with (
            mock.patch.object(runtime, "_source_s3_values", return_value=values),
            mock.patch.object(runtime, "_run", return_value=listing) as run,
        ):
            self.assertEqual(
                list(OPERATOR.PACKAGE_MEMBERS), runtime.remote_package_inventory({})
            )
        command = run.call_args.args[0]
        self.assertEqual("docker", command[0])
        self.assertIn(OPERATOR.OFFICIAL_AWS_CLI_IMAGE, command)
        self.assertNotIn("synthetic-access", command)
        self.assertNotIn("synthetic-secret", command)
        self.assertNotIn("hmac", " ".join(command))

    def test_remote_download_uses_pinned_aws_cli_and_modes_files_0600(self) -> None:
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.state_root = self.root / "run-id" / "operator"
        runtime.state_root.mkdir(parents=True, mode=0o700)
        runtime.config = {"uploader_image": OPERATOR.OFFICIAL_AWS_CLI_IMAGE}
        values = {
            "S3_BUCKET": "synthetic-bucket",
            "S3_ACCESS_KEY_ID": "synthetic-access",
            "S3_SECRET_ACCESS_KEY": "synthetic-secret",
        }
        package = runtime.state_root.parent / "downloaded"

        def download(_command, **_kwargs):
            for name in OPERATOR.PACKAGE_MEMBERS:
                (package / name).write_bytes(b"x")
            return b""

        with (
            mock.patch.object(runtime, "_source_s3_values", return_value=values),
            mock.patch.object(runtime, "_run", side_effect=download) as run,
        ):
            self.assertEqual(
                {"downloaded": True},
                runtime.download_backup_package({"package_dir": str(package)}),
            )
        command = run.call_args.args[0]
        self.assertIn(OPERATOR.OFFICIAL_AWS_CLI_IMAGE, command)
        self.assertNotIn("synthetic-access", command)
        self.assertNotIn("synthetic-secret", command)
        for name in OPERATOR.PACKAGE_MEMBERS:
            self.assertEqual(0o600, stat.S_IMODE((package / name).stat().st_mode))

    def test_live_parity_compares_protected_and_restored_ann_results(self) -> None:
        bundle = self.root / "bundle"
        bundle.mkdir(mode=0o700)
        points = [
            {"id": f"point-{index}", "payload": {"index": index}, "vector": [0.1, 0.2]}
            for index in range(24)
        ]
        (bundle / "points.jsonl").write_text(
            "".join(json.dumps(point, separators=(",", ":")) + "\n" for point in points),
            encoding="utf-8",
        )
        runtime = object.__new__(OPERATOR.Runtime)
        runtime.bundle_dir = bundle
        runtime.config = {
            "target_collection": "restored",
            "protected_collection": "protected",
            "expected_count": 24,
            "expected_vector_config": {"size": 2, "distance": "Cosine"},
        }
        ann = {"result": {"points": [{"id": "point-0", "score": 1.0}]}}

        def qdrant(_method, path, _body=None):
            if path.endswith("/points/scroll"):
                return {"result": {"points": points, "next_page_offset": None}}
            if path.endswith("/points/query"):
                return ann
            raise AssertionError(path)

        with mock.patch.object(runtime, "_qdrant", side_effect=qdrant) as request:
            result = runtime.run_phase20_parity({})
        self.assertTrue(result["ann_exact"])
        query_paths = [
            call.args[1]
            for call in request.call_args_list
            if call.args[1].endswith("/points/query")
        ]
        self.assertEqual(24, sum("/protected/" in path for path in query_paths))
        self.assertEqual(24, sum("/restored/" in path for path in query_paths))


if __name__ == "__main__":
    unittest.main()
