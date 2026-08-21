#!/usr/bin/env python3
"""Contract tests for the value-free Phase 21 transition chain."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import errno
import hashlib
import fcntl
import inspect
from http import server as http_server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-phase-21.py"
SPEC = importlib.util.spec_from_file_location("phase21_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

RESTORE_PATH = ROOT / "scripts" / "restore-solidstats-memory.py"
RESTORE_SPEC = importlib.util.spec_from_file_location(
    "solidstats_memory_restore", RESTORE_PATH
)
assert RESTORE_SPEC and RESTORE_SPEC.loader
RESTORE = importlib.util.module_from_spec(RESTORE_SPEC)
RESTORE_SPEC.loader.exec_module(RESTORE)

PROBE_PATH = ROOT / "scripts" / "probe-solidstats-memory.py"
PROBE_SPEC = importlib.util.spec_from_file_location("solidstats_memory_probe", PROBE_PATH)
assert PROBE_SPEC and PROBE_SPEC.loader
PROBE = importlib.util.module_from_spec(PROBE_SPEC)
PROBE_SPEC.loader.exec_module(PROBE)
CUTOVER_PATH = ROOT / "scripts" / "cutover-solidstats-memory.sh"
REMOTE_CUTOVER_PATH = (
    ROOT / "scripts" / "operate-solidstats-memory-cutover-remote.sh"
)
BACKUP_GUARD_PATH = ROOT / "scripts" / "guard-solidstats-memory-backup.sh"
BACKUP_SUSPEND_PATH = ROOT / "scripts" / "suspend-solidstats-memory-backup.sh"
ACTIVATION_RENDERER_PATH = ROOT / "scripts" / "render-solidstats-memory-backup-activation.py"
ACTIVATION_SPEC = importlib.util.spec_from_file_location(
    "solidstats_memory_activation", ACTIVATION_RENDERER_PATH
)
assert ACTIVATION_SPEC and ACTIVATION_SPEC.loader
ACTIVATION = importlib.util.module_from_spec(ACTIVATION_SPEC)
ACTIVATION_SPEC.loader.exec_module(ACTIVATION)
EVIDENCE_COLLECTOR_PATH = ROOT / "scripts" / "collect-phase-21-recovery-evidence.py"
CLIENT_POLICY_PATH = ROOT / "scripts" / "configure-solidstats-memory-client.py"
CLIENT_POLICY_SPEC = importlib.util.spec_from_file_location(
    "solidstats_memory_client_policy", CLIENT_POLICY_PATH
)
assert CLIENT_POLICY_SPEC and CLIENT_POLICY_SPEC.loader
CLIENT_POLICY = importlib.util.module_from_spec(CLIENT_POLICY_SPEC)
CLIENT_POLICY_SPEC.loader.exec_module(CLIENT_POLICY)
COLLECTOR_PATH = ROOT / "scripts" / "collect-phase-21-recovery-evidence.py"
COLLECTOR_SPEC = importlib.util.spec_from_file_location("phase21_collector", COLLECTOR_PATH)
assert COLLECTOR_SPEC and COLLECTOR_SPEC.loader
COLLECTOR = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(COLLECTOR)

STAGES = (
    "PREPARED",
    "STAGED",
    "RESTORE_PROVEN",
    "PRIVATE_LIVE",
    "DATA_SWITCHED",
    "PUBLIC_LIVE",
    "CLIENT_ADDED",
    "RECOVERY_PROVEN",
    "SEALED",
)


class MemoryCutoverContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.parity = self.root / "20-PARITY-REPORT.json"
        self.handoff = self.root / "20-PHASE21-HANDOFF.json"
        self.parity.write_text(
            json.dumps(
                {
                    "parity_schema": "solidstats-memory-parity/v1",
                    "verdict": "pass",
                    "record_count": 3,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.parity_digest = VALIDATOR.sha256_file(self.parity)
        self.handoff.write_text(
            json.dumps(
                {
                    "handoff_schema": "solidstats-memory-phase21-handoff/v1",
                    "parity_report_sha256": self.parity_digest,
                    "record_count": 3,
                    "phase21_required_checks": [
                        "recompute-provenance-digests",
                        "verify-retained-bundle-digests",
                    ],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.handoff_digest = VALIDATOR.sha256_file(self.handoff)
        self.run_id = "21" * 16

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_public_qdrant_boundary_requires_complete_conclusive_address_coverage(self) -> None:
        addresses = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.2", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 0)),
        ]

        class FakeSocket:
            def __init__(self, outcome: object, calls: list[tuple[object, ...]]) -> None:
                self.outcome = outcome
                self.calls = calls

            def settimeout(self, timeout: float) -> None:
                self.calls.append(("timeout", timeout))

            def connect(self, address: tuple[object, ...]) -> None:
                self.calls.append(("connect", *address))
                if isinstance(self.outcome, BaseException):
                    raise self.outcome

            def close(self) -> None:
                self.calls.append(("close",))

        def invoke(outcomes: list[object], resolved: object = addresses) -> tuple[dict[str, object], list[tuple[object, ...]]]:
            calls: list[tuple[object, ...]] = []
            iterator = iter(outcomes)
            result = PROBE.probe_private_boundary(
                "memory.example.test",
                resolver=lambda *args, **kwargs: resolved,
                socket_factory=lambda *args: FakeSocket(next(iterator), calls),
                timeout=0.25,
            )
            return result, calls

        refused = OSError(errno.ECONNREFUSED, "refused")
        timeout = socket.timeout("bounded timeout")
        result, calls = invoke([refused, refused, refused, refused])
        self.assertEqual(2, result["address_count"])
        self.assertTrue(result["port_6333_all_addresses_blocked"])
        self.assertTrue(result["port_6334_all_addresses_blocked"])
        self.assertEqual(4, sum(call[0] == "connect" for call in calls))
        self.assertNotIn("192.0.2", json.dumps(result))
        self.assertEqual(2, invoke([timeout, timeout, timeout, timeout])[0]["address_count"])

        with self.assertRaises(PROBE.ProbeError):
            PROBE.probe_private_boundary(
                "memory.example.test",
                resolver=lambda *args, **kwargs: (_ for _ in ()).throw(socket.gaierror()),
            )
        for outcomes in (
            [refused, None],
            [OSError(errno.ENETUNREACH, "unreachable")],
            [OSError(errno.EPERM, "denied")],
        ):
            with self.subTest(outcomes=outcomes):
                with self.assertRaises(PROBE.ProbeError):
                    invoke(outcomes)
        collector_source = COLLECTOR_PATH.read_text(encoding="utf-8")
        cutover_source = CUTOVER_PATH.read_text(encoding="utf-8")
        self.assertIn('"address_set_sha256"', collector_source)
        self.assertIn('public["port_6333_all_addresses_blocked"]', collector_source)
        self.assertIn('"no_public_qdrant": public_qdrant_private', collector_source)
        self.assertNotIn('public["qdrant_6333_blocked"]', collector_source)
        self.assertIn("address_set_sha256=%s", cutover_source)

    def test_preflight_bootstraps_runtime_before_capturing_final_alias_state(self) -> None:
        source = CUTOVER_PATH.read_text(encoding="utf-8")
        preflight_start = source.index("preflight()")
        preflight_end = source.index("\n}", preflight_start)
        preflight = source[preflight_start:preflight_end]
        self.assertLess(
            preflight.index("run_runtime_bootstrap"),
            preflight.index("alias-prestate >/dev/null"),
        )
        self.assertLess(
            preflight.index("run_runtime_bootstrap"),
            source.index("run_remote_batch stop-legacy-start-new"),
        )
        self.assertIn("bootstrap-runtime-palace", source)
        self.assertIn('chmod 600 "${request}"', source)
        self.assertIn('stat -c \'%a\' "${response}"', source)

    def make_chain(self, limit: int = len(STAGES)) -> list[dict[str, object]]:
        chain: list[dict[str, object]] = []
        prior = self.handoff_digest
        for index, stage in enumerate(STAGES[:limit]):
            payload: dict[str, object] = {
                "schema": (
                    "solidstats-memory-phase21-evidence/v1"
                    if stage == "SEALED"
                    else "solidstats-memory-phase21-stage/v1"
                ),
                "run_id": self.run_id,
                "stage": stage,
                "prior_evidence_sha256": prior,
                "input_digests": {
                    "phase20_handoff_sha256": self.handoff_digest,
                    "phase20_parity_report_sha256": self.parity_digest,
                },
                "checks": {
                    "aggregate_count": index,
                    "gate_passed": True,
                    "stage_lock": {
                        "acquired": True,
                        "owner_run_sha256": hashlib.sha256(
                            self.run_id.encode("ascii")
                        ).hexdigest(),
                    },
                },
                "started_at": f"2026-08-20T12:{index:02d}:00Z",
                "completed_at": f"2026-08-20T12:{index:02d}:01Z",
                "verdict": "pass",
            }
            chain.append(payload)
            prior = hashlib.sha256(
                VALIDATOR.canonical_json_bytes(payload)
            ).hexdigest()
        return chain

    def validate_chain(
        self,
        chain: list[dict[str, object]],
        *,
        require_complete: bool = False,
    ) -> dict[str, object]:
        return VALIDATOR.validate_transition_chain(
            chain,
            handoff_path=self.handoff,
            parity_path=self.parity,
            require_complete=require_complete,
        )

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        path.write_bytes(
            json.dumps(
                value,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def make_phase20_fixture(self) -> dict[str, Path]:
        phase20 = self.root / "phase20"
        bundle = phase20 / "bundle"
        bundle.mkdir(parents=True)
        source = phase20 / "20-SOURCE-INVENTORY.json"
        mapping = phase20 / "20-MAPPING-CONTRACT.json"
        transform = phase20 / "20-TRANSFORM-MANIFEST.json"
        parity = phase20 / "20-PARITY-REPORT.json"
        handoff = phase20 / "20-PHASE21-HANDOFF.json"
        self.write_json(
            source,
            {
                "schema": "solidstats-memory-source-inventory/v1",
                "record_count": 3,
            },
        )
        source_sha = self.sha256(source)
        self.write_json(
            mapping,
            {
                "schema": "solidstats-memory-mapping-contract/v1",
                "source_inventory_sha256": source_sha,
                "record_count": 3,
            },
        )
        mapping_sha = self.sha256(mapping)
        (bundle / "id-map.json").write_bytes(b"{}\n")
        (bundle / "points.ndjson").write_bytes(b'{"id":"fixture"}\n')
        bundle_manifest = bundle / "bundle-manifest.json"
        self.write_json(
            bundle_manifest,
            {
                "schema": "solidstats-memory-bundle/v1",
                "record_count": 3,
                "files": {
                    "id-map.json": self.sha256(bundle / "id-map.json"),
                    "points.ndjson": self.sha256(bundle / "points.ndjson"),
                },
            },
        )
        bundle_digests = {
            path.name: self.sha256(path)
            for path in sorted(bundle.iterdir())
        }
        self.write_json(
            transform,
            {
                "schema": "solidstats-memory-transform-manifest/v1",
                "record_count": 3,
                "source_inventory_sha256": source_sha,
                "mapping_contract_sha256": mapping_sha,
                "bundle_file_sha256": bundle_digests,
            },
        )
        transform_sha = self.sha256(transform)
        self.write_json(
            parity,
            {
                "parity_schema": "solidstats-memory-parity/v1",
                "verdict": "pass",
                "record_count": 3,
                "transform_manifest_sha256": transform_sha,
            },
        )
        parity_sha = self.sha256(parity)
        self.write_json(
            handoff,
            {
                "handoff_schema": "solidstats-memory-phase21-handoff/v1",
                "record_count": 3,
                "source_inventory_sha256": source_sha,
                "mapping_contract_sha256": mapping_sha,
                "transform_manifest_sha256": transform_sha,
                "parity_report_sha256": parity_sha,
                "bundle_file_sha256": bundle_digests,
            },
        )
        return {
            "bundle": bundle,
            "source": source,
            "mapping": mapping,
            "transform": transform,
            "parity": parity,
            "handoff": handoff,
        }

    def make_backup_package(
        self,
        package: Path,
        *,
        run_id: str,
        bindings: dict[str, str],
    ) -> None:
        package.mkdir()
        (package / "qdrant.snapshot").write_bytes(b"snapshot-fixture")
        (package / "mempalace-metadata.tar").write_bytes(b"metadata-fixture")
        manifest = {
            "schema": "solidstats-memory-backup-package/v1",
            "run_id": run_id,
            "phase20_bindings": bindings,
            "members": {
                "mempalace_metadata_tar_sha256": self.sha256(
                    package / "mempalace-metadata.tar"
                ),
                "qdrant_snapshot_sha256": self.sha256(
                    package / "qdrant.snapshot"
                ),
            },
        }
        self.write_json(package / "manifest.json", manifest)
        lines = [
            f"{self.sha256(package / name)}  {name}"
            for name in (
                "manifest.json",
                "mempalace-metadata.tar",
                "qdrant.snapshot",
            )
        ]
        (package / "SHA256SUMS").write_text(
            "\n".join(lines) + "\n", encoding="ascii"
        )

    def backup_evidence(self, bindings: dict[str, str]) -> dict[str, object]:
        digest = "a" * 64
        return {
            "schema": "solidstats-memory-backup-restore-evidence/v1",
            "run_id": self.run_id,
            "phase20_bindings": bindings,
            "quiescence": {
                "stable": True,
                "writer_count": 0,
                "kubernetes_reachable": True,
                "qdrant_reachable": True,
                "s3_reachable": True,
            },
            "capacity": {
                "sufficient": True,
                "snapshot_bytes": 10,
                "baseline_snapshot_bytes": 10,
                "baseline_bound_bytes": 10 + 1024 * 1024,
                "reserve_bytes": 10,
                "required_bytes": 30,
                "pvc_requested_bytes": 40,
                "pvc_capacity_bytes": 40,
                "pvc_free_bytes": 40,
                "node_free_bytes": 50,
            },
            "package_checks": {
                "complete": True,
                "member_count": 4,
                "package_sha256": digest,
                "snapshot_bytes": 10,
                "metadata_archive_bytes": 20,
                "local_hashes_rechecked": True,
                "job_count": 1,
            },
            "object_checks": {
                "verified": True,
                "inventory_exact": True,
                "downloaded": True,
                "hashes_rechecked": True,
                "object_count": 4,
                "package_sha256": digest,
            },
            "target_absence": {
                "confirmed": True,
                "collection_inventory_checked": True,
                "alias_inventory_checked": True,
                "target_lookup_checked": True,
            },
            "restore_checks": {
                "green": True,
                "configuration_match": True,
                "count_match": True,
                "parity_exact": True,
                "record_count": 3,
                "snapshot_priority": True,
            },
            "parity_checks": {
                "exact": True,
                "record_count": 3,
                "field_exact": True,
                "id_exact": True,
                "metadata_exact": True,
                "timestamp_exact": True,
                "vector_exact": True,
                "exclusion_exact": True,
                "ann_exact": True,
            },
            "alias_compatibility": {
                "probe_passed": True,
                "prestate_sha256": digest,
                "poststate_sha256": digest,
                "restored": True,
                "exact_image": True,
            },
            "rollback_state": {
                "active_state_unchanged": True,
                "routing_unchanged": True,
                "nginx_unchanged": True,
                "registration_unchanged": True,
                "legacy_runtime_unchanged": True,
                "recurring_schedule_unchanged": True,
            },
            "verdict": "pass",
        }

    def test_live_snapshot_capacity_is_bound_to_retained_baseline(self) -> None:
        capacity = {
            "pvc_requested_bytes": 8 * 1024 * 1024,
            "pvc_capacity_bytes": 8 * 1024 * 1024,
            "pvc_free_bytes": 8 * 1024 * 1024,
            "node_free_bytes": 8 * 1024 * 1024,
            "reserve_bytes": 1024 * 1024,
        }
        accepted = RESTORE.require_live_snapshot_capacity(
            baseline_snapshot_bytes=1024 * 1024,
            live_snapshot_bytes=2 * 1024 * 1024,
            capacity=capacity,
        )
        self.assertEqual(accepted["snapshot_bytes"], 2 * 1024 * 1024)
        self.assertEqual(accepted["baseline_snapshot_bytes"], 1024 * 1024)
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "baseline"):
            RESTORE.require_live_snapshot_capacity(
                baseline_snapshot_bytes=1024 * 1024,
                live_snapshot_bytes=2 * 1024 * 1024 + 1,
                capacity=capacity,
            )
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "insufficient"):
            RESTORE.require_live_snapshot_capacity(
                baseline_snapshot_bytes=1024 * 1024,
                live_snapshot_bytes=2 * 1024 * 1024,
                capacity={**capacity, "pvc_requested_bytes": 4 * 1024 * 1024},
            )

    def test_complete_synthetic_chain_reaches_sealed(self) -> None:
        result = self.validate_chain(self.make_chain(), require_complete=True)

        self.assertEqual("SEALED", result["stage"])
        self.assertEqual(len(STAGES), result["stage_count"])
        self.assertEqual("pass", result["verdict"])

    def test_missing_empty_null_and_out_of_order_evidence_fails_closed(self) -> None:
        mutations: list[tuple[str, list[dict[str, object]]]] = []
        for key in (
            "schema",
            "run_id",
            "stage",
            "prior_evidence_sha256",
            "input_digests",
            "checks",
            "started_at",
            "completed_at",
            "verdict",
        ):
            chain = self.make_chain(1)
            del chain[0][key]
            mutations.append((f"missing-{key}", chain))
        for key, value in (
            ("run_id", ""),
            ("stage", None),
            ("prior_evidence_sha256", ""),
            ("input_digests", {}),
            ("checks", {}),
            ("completed_at", None),
        ):
            chain = self.make_chain(1)
            chain[0][key] = value
            mutations.append((f"empty-or-null-{key}", chain))
        reordered = self.make_chain(3)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        mutations.append(("reordered", reordered))
        skipped = self.make_chain(3)
        del skipped[1]
        mutations.append(("skipped", skipped))

        for name, chain in mutations:
            with self.subTest(name=name), self.assertRaises(
                VALIDATOR.Phase21ValidationError
            ):
                self.validate_chain(chain)

    def test_exact_replay_is_idempotent_but_unequal_collision_is_rejected(self) -> None:
        chain = self.make_chain(3)
        chain.insert(2, deepcopy(chain[1]))
        result = self.validate_chain(chain)
        self.assertEqual("RESTORE_PROVEN", result["stage"])
        self.assertEqual(3, result["stage_count"])

        collision = deepcopy(chain)
        collision[2]["checks"]["gate_passed"] = False
        with self.assertRaisesRegex(
            VALIDATOR.Phase21ValidationError, "stage index 2"
        ):
            self.validate_chain(collision)

    def test_stage_lock_blocks_another_run_and_allows_exact_resume(self) -> None:
        interrupted = self.make_chain(4)
        result = self.validate_chain(interrupted[:3])
        self.assertEqual("RESTORE_PROVEN", result["stage"])
        self.assertEqual("PRIVATE_LIVE", self.validate_chain(interrupted)["stage"])

        colliding_run = deepcopy(interrupted)
        colliding_run[3]["run_id"] = "42" * 16
        with self.assertRaisesRegex(
            VALIDATOR.Phase21ValidationError, "stage lock"
        ):
            self.validate_chain(colliding_run)

        stale_resume = deepcopy(interrupted)
        stale_resume[3]["prior_evidence_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            VALIDATOR.Phase21ValidationError, "prior evidence"
        ):
            self.validate_chain(stale_resume)

    def test_prepared_stage_is_bound_to_current_phase20_public_digests(self) -> None:
        chain = self.make_chain(1)
        chain[0]["input_digests"]["phase20_parity_report_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            VALIDATOR.Phase21ValidationError, "Phase 20 binding"
        ):
            self.validate_chain(chain)

        self.parity.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            VALIDATOR.Phase21ValidationError, "parity digest"
        ):
            self.validate_chain(self.make_chain(1))

    def test_private_values_are_rejected_without_echoing_them(self) -> None:
        mutations = {
            "api_token": "sk-private-fixture",
            "corpus_document": "private corpus fixture",
            "private_path": "/private/fixture",
            "collection_identifier": "private-collection-fixture",
            "vector": [0.1, 0.2],
            "metadata_value": "private metadata fixture",
            "raw_response_body": "private response fixture",
            "secret": "fixture-secret-value",
        }

        for key, value in mutations.items():
            with self.subTest(key=key):
                payload = self.make_chain(1)[0]
                payload["checks"][key] = value
                with self.assertRaises(
                    VALIDATOR.Phase21ValidationError
                ) as caught:
                    VALIDATOR.validate_value_free_payload(payload)
                self.assertNotIn(str(value), str(caught.exception))

    def test_cli_emits_one_value_free_result_line(self) -> None:
        evidence_paths: list[Path] = []
        for index, payload in enumerate(self.make_chain()):
            path = self.root / f"21-STAGE-{index:02d}.json"
            path.write_bytes(VALIDATOR.canonical_json_bytes(payload) + b"\n")
            evidence_paths.append(path)
        command = [
            sys.executable,
            str(MODULE_PATH),
            "--handoff",
            str(self.handoff),
        ]
        for path in evidence_paths:
            command.extend(("--evidence", str(path)))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["PASS: Phase 21 evidence chain validated"], result.stdout.splitlines())
        self.assertEqual([], result.stderr.splitlines())

    def test_phase20_drift_stops_before_private_bundle_reads(self) -> None:
        paths = self.make_phase20_fixture()
        paths["mapping"].write_bytes(b"{}\n")
        private_reads: list[Path] = []

        def tracking_digest(path: Path) -> str:
            if paths["bundle"] in path.parents:
                private_reads.append(path)
            return self.sha256(path)

        with self.assertRaisesRegex(
            RESTORE.RestoreControlError, "Phase 20 public binding"
        ):
            RESTORE.recompute_phase20_bindings(
                handoff_path=paths["handoff"],
                parity_path=paths["parity"],
                source_inventory_path=paths["source"],
                mapping_contract_path=paths["mapping"],
                transform_manifest_path=paths["transform"],
                bundle_dir=paths["bundle"],
                digest_file=tracking_digest,
            )

        self.assertEqual([], private_reads)

    def test_phase20_bindings_cover_public_and_retained_bundle_digests(self) -> None:
        paths = self.make_phase20_fixture()
        bindings = RESTORE.recompute_phase20_bindings(
            handoff_path=paths["handoff"],
            parity_path=paths["parity"],
            source_inventory_path=paths["source"],
            mapping_contract_path=paths["mapping"],
            transform_manifest_path=paths["transform"],
            bundle_dir=paths["bundle"],
        )

        self.assertEqual(self.sha256(paths["handoff"]), bindings["handoff_sha256"])
        self.assertEqual(self.sha256(paths["parity"]), bindings["parity_report_sha256"])
        self.assertRegex(bindings["binding_sha256"], r"^[0-9a-f]{64}$")

    def test_package_rejects_missing_empty_and_checksum_mismatch(self) -> None:
        bindings = {"binding_sha256": "b" * 64}
        mutations = ("missing", "empty", "checksum")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                package = self.root / f"package-{mutation}"
                self.make_backup_package(
                    package, run_id=self.run_id, bindings=bindings
                )
                if mutation == "missing":
                    os.unlink(package / "qdrant.snapshot")
                elif mutation == "empty":
                    (package / "qdrant.snapshot").write_bytes(b"")
                else:
                    (package / "qdrant.snapshot").write_bytes(b"changed")
                with self.assertRaises(RESTORE.RestoreControlError):
                    RESTORE.verify_backup_package(
                        package,
                        expected_run_id=self.run_id,
                        expected_phase20_bindings=bindings,
                    )

    def test_package_builder_accepts_exactly_one_complete_package(self) -> None:
        bindings = {"binding_sha256": "9" * 64}
        package = self.root / "built-package"
        package.mkdir(mode=0o700)
        (package / "qdrant.snapshot").write_bytes(b"snapshot")
        (package / "mempalace-metadata.tar").write_bytes(b"metadata")

        result = RESTORE.create_backup_package(
            package,
            run_id=self.run_id,
            phase20_bindings=bindings,
        )

        self.assertTrue(result["complete"])
        self.assertEqual(
            {"SHA256SUMS", "manifest.json", "mempalace-metadata.tar", "qdrant.snapshot"},
            {path.name for path in package.iterdir()},
        )
        with self.assertRaises(RESTORE.RestoreControlError):
            RESTORE.create_backup_package(
                package,
                run_id=self.run_id,
                phase20_bindings=bindings,
            )

    def test_exact_package_replay_is_idempotent_but_collision_is_refused(self) -> None:
        bindings = {"binding_sha256": "c" * 64}
        package = self.root / "package"
        remote = self.root / "object-store"
        self.make_backup_package(package, run_id=self.run_id, bindings=bindings)
        first = RESTORE.store_backup_package(
            package, remote, prefix="backups/run", binding_sha256="c" * 64
        )
        second = RESTORE.store_backup_package(
            package, remote, prefix="backups/run", binding_sha256="c" * 64
        )
        self.assertEqual("uploaded", first["status"])
        self.assertEqual("reused", second["status"])

        (package / "qdrant.snapshot").write_bytes(b"collision")
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "collision"):
            RESTORE.store_backup_package(
                package, remote, prefix="backups/run", binding_sha256="c" * 64
            )

    def test_run_lock_blocks_parallel_work_and_resumes_verified_stage(self) -> None:
        evidence_dir = self.root / "evidence"
        lock = RESTORE.acquire_run_lock(
            evidence_dir,
            run_id=self.run_id,
            binding_sha256="d" * 64,
            resume_run=False,
        )
        self.addCleanup(lock.release)
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "locked"):
            RESTORE.acquire_run_lock(
                evidence_dir,
                run_id="42" * 16,
                binding_sha256="e" * 64,
                resume_run=False,
            )
        RESTORE.checkpoint_run(lock, "preflight", "e" * 64)
        RESTORE.checkpoint_run(lock, "backup", "f" * 64)
        lock.release()

        resumed = RESTORE.acquire_run_lock(
            evidence_dir,
            run_id=self.run_id,
            binding_sha256="d" * 64,
            resume_run=True,
        )
        self.addCleanup(resumed.release)
        self.assertEqual("backup", resumed.state["last_stage"])
        self.assertEqual("f" * 64, resumed.state["last_evidence_sha256"])

    def test_operator_adapter_resumes_after_incomplete_private_call(self) -> None:
        executable = self.root / "operator"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        private = self.root / "operator-state"
        private.mkdir(mode=0o700)
        previous = private / "001-inspect-preflight-request.json"
        previous.write_text("{}\n", encoding="utf-8")
        previous.chmod(0o600)
        adapter = RESTORE.JsonOperatorAdapter(executable, private)

        def respond(command: tuple[str, ...], **_kwargs: object) -> mock.Mock:
            response = Path(command[3])
            RESTORE.write_private_json(response, {"ok": True, "result": {}})
            return mock.Mock(returncode=0)

        with mock.patch.object(RESTORE.subprocess, "run", side_effect=respond):
            result = adapter._call("inspect-runtime", {}, timeout=1)

        self.assertEqual({}, result)
        self.assertTrue((private / "002-inspect-runtime-request.json").is_file())
        self.assertTrue((private / "002-inspect-runtime-response.json").is_file())

    def test_operator_adapter_rejects_unsafe_private_call_history(self) -> None:
        executable = self.root / "operator"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        private = self.root / "operator-state"
        private.mkdir(mode=0o700)
        previous = private / "001-inspect-preflight-request.json"
        previous.write_text("{}\n", encoding="utf-8")
        previous.chmod(0o640)

        with self.assertRaisesRegex(RESTORE.RestoreControlError, "unsafe"):
            RESTORE.JsonOperatorAdapter(executable, private)

    def test_target_capacity_recovery_and_alias_probe_fail_closed(self) -> None:
        calls: list[tuple[str, str, object]] = []
        aliases: dict[str, str] = {"active": "protected"}

        def request(method: str, path: str, body: object = None) -> object:
            calls.append((method, path, body))
            if path == "/collections":
                return {"result": {"collections": [{"name": "protected"}]}}
            if path == "/aliases":
                return {
                    "result": {
                        "aliases": [
                            {"alias_name": alias, "collection_name": collection}
                            for alias, collection in aliases.items()
                        ]
                    }
                }
            if path.startswith("/collections/isolated") and method == "GET":
                raise RESTORE.QdrantNotFound("absent")
            if path == "/collections/aliases" and method == "POST":
                for action in body["actions"]:
                    if "create_alias" in action:
                        item = action["create_alias"]
                        aliases[item["alias_name"]] = item["collection_name"]
                    if "delete_alias" in action:
                        aliases.pop(action["delete_alias"]["alias_name"], None)
                return {"status": "ok"}
            return {"status": "ok", "result": True}

        absence = RESTORE.require_absent_target(
            request,
            target_collection="isolated",
            protected_collection="protected",
        )
        self.assertTrue(absence["confirmed"])
        capacity = RESTORE.require_restore_capacity(
            snapshot_bytes=10,
            pvc_requested_bytes=30,
            node_free_bytes=31,
            reserve_bytes=5,
        )
        self.assertEqual(25, capacity["required_bytes"])
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "insufficient"):
            RESTORE.require_restore_capacity(
                snapshot_bytes=10,
                pvc_requested_bytes=24,
                node_free_bytes=31,
                reserve_bytes=5,
            )
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "priority"):
            RESTORE.recover_snapshot(
                lambda **_kwargs: {"status": "ok", "result": True},
                target_collection="isolated",
                snapshot_path=self.root / "missing.snapshot",
                priority="replica",
            )

        probe = RESTORE.probe_alias_compatibility(
            request,
            restored_collection="isolated",
            probe_alias="probe",
            exact_image_probe=lambda: True,
        )
        self.assertTrue(probe["restored"])
        self.assertNotIn("probe", aliases)
        self.assertEqual("protected", aliases["active"])

    def test_occupied_target_and_probe_alias_collision_stop_before_mutation(self) -> None:
        mutation_calls: list[str] = []

        def request(method: str, path: str, body: object = None) -> object:
            if method != "GET":
                mutation_calls.append(path)
            if path == "/collections":
                return {"result": {"collections": [{"name": "isolated"}]}}
            if path == "/aliases":
                return {
                    "result": {
                        "aliases": [
                            {"alias_name": "probe", "collection_name": "protected"}
                        ]
                    }
                }
            if path == "/collections/isolated":
                return {"result": {"status": "green"}}
            raise AssertionError(path)

        with self.assertRaisesRegex(RESTORE.RestoreControlError, "collision"):
            RESTORE.require_absent_target(
                request,
                target_collection="isolated",
                protected_collection="protected",
            )
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "collision"):
            RESTORE.probe_alias_compatibility(
                request,
                restored_collection="isolated",
                probe_alias="probe",
                exact_image_probe=lambda: True,
            )
        self.assertEqual([], mutation_calls)

    def test_qdrant_adapter_covers_create_download_recover_and_verify(self) -> None:
        calls: list[tuple[str, str, object, bool]] = []

        def request(
            method: str,
            path: str,
            body: object = None,
            *,
            binary: bool = False,
        ) -> object:
            calls.append((method, path, body, binary))
            if path.endswith("/snapshots?wait=true") and method == "POST":
                return {"status": "ok", "result": {"name": "fixture.snapshot"}}
            if path.endswith("/fixture.snapshot") and method == "GET":
                return b"snapshot-bytes"
            if path.endswith("/snapshots/upload?priority=snapshot"):
                return {"status": "ok", "result": True}
            if path == "/collections/isolated" and method == "GET":
                return {
                    "status": "ok",
                    "result": {
                        "status": "green",
                        "optimizer_status": "ok",
                        "points_count": 3,
                        "config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}},
                    },
                }
            raise AssertionError((method, path))

        snapshot_name = RESTORE.create_snapshot(request, "source")
        destination = self.root / "qdrant.snapshot"
        download = RESTORE.download_snapshot(
            request, "source", snapshot_name, destination
        )
        recovery = RESTORE.recover_snapshot(
            lambda **kwargs: request(
                "POST",
                f"/collections/{kwargs['target_collection']}/snapshots/upload?priority=snapshot",
                {"snapshot_path": str(kwargs["snapshot_path"])},
            ),
            target_collection="isolated",
            snapshot_path=destination,
            priority="snapshot",
        )
        verification = RESTORE.verify_restored_collection(
            request,
            target_collection="isolated",
            expected_vector_config={"size": 3, "distance": "Cosine"},
            expected_count=3,
            parity_check=lambda: {"verdict": "pass", "record_count": 3},
        )

        self.assertEqual("fixture.snapshot", snapshot_name)
        self.assertEqual(b"snapshot-bytes", destination.read_bytes())
        self.assertEqual(len(b"snapshot-bytes"), download["snapshot_bytes"])
        self.assertTrue(recovery["accepted"])
        self.assertTrue(verification["green"])
        self.assertTrue(verification["parity_exact"])
        self.assertTrue(any(binary for _method, _path, _body, binary in calls))

    def test_qdrant_http_timeout_and_malformed_json_are_value_free(self) -> None:
        class Response:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return self.payload

        def timeout_opener(*_args: object, **_kwargs: object) -> object:
            raise TimeoutError("private host detail")

        for opener in (timeout_opener, lambda *_args, **_kwargs: Response(b"not-json")):
            with self.subTest(opener=opener), self.assertRaises(
                RESTORE.RestoreControlError
            ) as caught:
                RESTORE.qdrant_request(
                    "http://127.0.0.1:6333",
                    "GET",
                    "/collections",
                    api_key="private-token",
                    opener=opener,
                )
            self.assertNotIn("private", str(caught.exception))

    def test_metadata_archive_is_deterministic_and_rejects_symlinks(self) -> None:
        metadata = self.root / "metadata"
        metadata.mkdir()
        (metadata / "a.json").write_text("{}\n", encoding="utf-8")
        nested = metadata / "nested"
        nested.mkdir()
        (nested / "b.bin").write_bytes(b"fixture")
        first = self.root / "first.tar"
        second = self.root / "second.tar"

        result = RESTORE.archive_quiescent_metadata(metadata, first)
        RESTORE.archive_quiescent_metadata(metadata, second)
        self.assertTrue(result["stable"])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first, "r:") as archive:
            self.assertEqual(["a.json", "nested", "nested/b.bin"], archive.getnames())

        (metadata / "escape").symlink_to(self.root / "outside")
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "unsafe"):
            RESTORE.archive_quiescent_metadata(metadata, self.root / "unsafe.tar")

    def test_backup_job_generation_keeps_private_values_out_of_evidence(self) -> None:
        cronjob = {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": "backup", "namespace": "memory"},
            "spec": {
                "suspend": True,
                "jobTemplate": {
                    "spec": {
                        "template": {
                            "metadata": {"labels": {"app": "backup"}},
                            "spec": {
                                "restartPolicy": "Never",
                                "containers": [{"name": "backup", "env": []}],
                            },
                        }
                    }
                },
            },
        }
        job = RESTORE.generate_backup_job(
            cronjob,
            run_id=self.run_id,
            private_environment={
                "BACKUP_RUN_ID": self.run_id,
                "BACKUP_PREPARE_IMAGE": "example.invalid/mempalace@sha256:" + "1" * 64,
                "BACKUP_S3_URI": f"s3://private-bucket/backups/solidstats-memory/{self.run_id}/",
                "AWS_ACCESS_KEY_ID": "synthetic-access",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                "PHASE20_BINDINGS_JSON": json.dumps(
                    {"binding_sha256": "1" * 64}, separators=(",", ":")
                ),
                "QDRANT_API_KEY": "synthetic-qdrant-key",
                "QDRANT_COLLECTION": "private-collection",
                "QDRANT_URL": "http://qdrant:6333",
            },
        )
        output = self.root / "private" / "job.json"
        RESTORE.write_private_json(output, job)

        self.assertEqual("Job", job["kind"])
        self.assertNotIn("schedule", job["spec"])
        self.assertEqual(0o600, output.stat().st_mode & 0o777)
        public = RESTORE.backup_job_evidence(job)
        self.assertNotIn("private-collection", json.dumps(public))
        self.assertTrue(public["generated"])
        pod_spec = job["spec"]["template"]["spec"]
        self.assertEqual(1, len(pod_spec["initContainers"]))
        self.assertEqual(1, len(pod_spec["containers"]))
        prepare = pod_spec["initContainers"][0]
        uploader = pod_spec["containers"][0]
        self.assertEqual(["python3", "-c"], prepare["command"])
        self.assertIn("solidstats-memory-backup-package/v1", prepare["args"][0])
        self.assertIn("for attempt in range(12):", prepare["args"][0])
        self.assertIn("time.sleep(5)", prepare["args"][0])
        self.assertIn('output.add("/metadata", arcname="palace")', prepare["args"][0])
        self.assertNotIn('output.add("/metadata/palace"', prepare["args"][0])
        self.assertLess(
            prepare["args"][0].index("for attempt in range(12):"),
            prepare["args"][0].index("method=\"POST\""),
        )
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", json.dumps(prepare["env"]))
        self.assertEqual(["aws"], uploader["command"])
        self.assertIn("s3", uploader["args"])
        self.assertIn("cp", uploader["args"])
        self.assertNotIn("hmac", prepare["args"][0])
        self.assertNotIn("Authorization", prepare["args"][0])
        dry_runs: list[tuple[str, ...]] = []

        def runner(command: tuple[str, ...], **_kwargs: object) -> object:
            dry_runs.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        validation = RESTORE.validate_backup_job(output, runner=runner)
        self.assertTrue(validation["client_dry_run"])
        self.assertTrue(validation["server_dry_run"])
        self.assertEqual(2, len(dry_runs))
        self.assertIn("--dry-run=client", dry_runs[0])
        self.assertIn("--dry-run=server", dry_runs[1])

    def test_alias_probe_restores_prestate_after_probe_failure(self) -> None:
        aliases: dict[str, str] = {}

        def request(method: str, path: str, body: object = None) -> object:
            if path == "/aliases":
                return {
                    "result": {
                        "aliases": [
                            {"alias_name": alias, "collection_name": collection}
                            for alias, collection in aliases.items()
                        ]
                    }
                }
            for action in body["actions"]:
                if "create_alias" in action:
                    item = action["create_alias"]
                    aliases[item["alias_name"]] = item["collection_name"]
                if "delete_alias" in action:
                    aliases.pop(action["delete_alias"]["alias_name"], None)
            return {"status": "ok"}

        with self.assertRaisesRegex(RESTORE.RestoreControlError, "probe failed"):
            RESTORE.probe_alias_compatibility(
                request,
                restored_collection="isolated",
                probe_alias="probe",
                exact_image_probe=lambda: False,
            )
        self.assertEqual({}, aliases)

    def test_alias_probe_restores_prestate_after_lost_create_ack(self) -> None:
        aliases: dict[str, str] = {}
        lost_ack = True

        def request(method: str, path: str, body: object = None) -> object:
            nonlocal lost_ack
            if path == "/aliases":
                return {"result": {"aliases": [
                    {"alias_name": name, "collection_name": collection}
                    for name, collection in aliases.items()
                ]}}
            for action in body["actions"]:
                if "create_alias" in action:
                    item = action["create_alias"]
                    aliases[item["alias_name"]] = item["collection_name"]
                    if lost_ack:
                        lost_ack = False
                        raise TimeoutError("synthetic lost acknowledgement")
                else:
                    aliases.pop(action["delete_alias"]["alias_name"], None)
            return {"status": "ok"}

        with self.assertRaisesRegex(RESTORE.RestoreControlError, "probe failed"):
            RESTORE.probe_alias_compatibility(
                request,
                restored_collection="isolated",
                probe_alias="probe",
                exact_image_probe=lambda: True,
            )
        self.assertEqual({}, aliases)

    def test_alias_probe_retries_ambiguous_cleanup_until_observed_absent(self) -> None:
        for apply_before_raise in (False, True):
            with self.subTest(apply_before_raise=apply_before_raise):
                aliases: dict[str, str] = {}
                failed_cleanup = False

                def request(method: str, path: str, body: object = None) -> object:
                    nonlocal failed_cleanup
                    if path == "/aliases":
                        return {"result": {"aliases": [
                            {"alias_name": name, "collection_name": collection}
                            for name, collection in aliases.items()
                        ]}}
                    action = body["actions"][0]
                    if "create_alias" in action:
                        item = action["create_alias"]
                        aliases[item["alias_name"]] = item["collection_name"]
                    else:
                        alias = action["delete_alias"]["alias_name"]
                        if not failed_cleanup:
                            failed_cleanup = True
                            if apply_before_raise:
                                aliases.pop(alias, None)
                            raise TimeoutError("synthetic ambiguous cleanup")
                        aliases.pop(alias, None)
                    return {"status": "ok"}

                result = RESTORE.probe_alias_compatibility(
                    request,
                    restored_collection="isolated",
                    probe_alias="probe",
                    exact_image_probe=lambda: True,
                )
                self.assertTrue(result["restored"])
                self.assertEqual({}, aliases)

    def test_backup_restore_evidence_schema_is_strict_and_value_free(self) -> None:
        bindings = {"binding_sha256": "1" * 64}
        evidence = self.backup_evidence(bindings)
        result = VALIDATOR.validate_backup_restore_evidence(evidence)
        self.assertEqual("pass", result["verdict"])

        evidence_path = self.root / "21-BACKUP-RESTORE-EVIDENCE.json"
        self.write_json(evidence_path, evidence)
        cli = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--evidence", str(evidence_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, cli.returncode, cli.stderr)
        self.assertEqual(
            ["PASS: Phase 21 backup and restore evidence validated"],
            cli.stdout.splitlines(),
        )
        self.assertEqual([], cli.stderr.splitlines())

        for mutation in ("missing", "private", "failed"):
            with self.subTest(mutation=mutation):
                invalid = deepcopy(evidence)
                if mutation == "missing":
                    del invalid["package_checks"]
                elif mutation == "private":
                    invalid["restore_checks"]["collection_identifier"] = "private"
                else:
                    invalid["restore_checks"]["green"] = False
                with self.assertRaises(VALIDATOR.Phase21ValidationError):
                    VALIDATOR.validate_backup_restore_evidence(invalid)

    def test_cli_stage_machine_executes_backup_restore_parity_and_rollback(self) -> None:
        paths = self.make_phase20_fixture()
        private_root = self.root / "private"
        evidence_dir = self.root / "evidence"
        private_root.mkdir(mode=0o700)
        events: list[str] = []
        aliases: dict[str, str] = {"active": "protected"}

        class SyntheticOperator:
            def inspect_preflight(
                self, *, bindings: dict[str, str], expected_count: int
            ) -> dict[str, object]:
                events.append("inspect-preflight")
                self.assert_binding(bindings)
                self.assert_count(expected_count)
                return {
                    "reachability": {
                        "kubernetes": True,
                        "s3": True,
                    },
                    "prestate": {
                        "active_alias_sha256": "1" * 64,
                        "nginx_sha256": "2" * 64,
                        "mcp_registration_sha256": "3" * 64,
                        "legacy_runtime_sha256": "4" * 64,
                        "schedule_sha256": "5" * 64,
                    },
                    "quiescence": {"stable": True, "writer_count": 0},
                    "capacity": {
                        "snapshot_bytes": 10,
                        "pvc_requested_bytes": 30,
                        "node_free_bytes": 31,
                        "reserve_bytes": 5,
                    },
                    "operator_markers": {
                        "qdrant_storage": "measured-qdrant",
                        "mempalace_storage": "measured-mempalace",
                        "mempalace_image": "measured-mempalace-image",
                        "backup_cidr": "measured-cidr",
                        "uploader_image": "measured-uploader-image",
                        "private_collection": "isolated",
                    },
                    "target_set": list(RESTORE.OPERATOR_TARGETS),
                }

            @staticmethod
            def assert_binding(bindings: dict[str, str]) -> None:
                if not bindings.get("binding_sha256"):
                    raise AssertionError("missing binding")

            @staticmethod
            def assert_count(expected_count: int) -> None:
                if expected_count != 3:
                    raise AssertionError("wrong count")

            def render_manifests(
                self,
                *,
                operator_markers: dict[str, str],
                target_set: tuple[str, ...],
            ) -> object:
                events.append("render-manifests")
                self.assertEqual(
                    set(RESTORE.OPERATOR_MARKERS), set(operator_markers)
                )
                self.assertEqual(RESTORE.OPERATOR_TARGETS, target_set)
                return {"rendered": True}

            def validate_manifests(
                self, rendered: object, *, mode: str
            ) -> dict[str, object]:
                events.append(f"dry-run-{mode}")
                self.assertEqual({"rendered": True}, rendered)
                return {"valid": True}

            def apply_manifests(self, rendered: object) -> dict[str, object]:
                events.append("apply-manifests")
                self.assertEqual({"rendered": True}, rendered)
                return {
                    "applied": True,
                    "target_count": len(RESTORE.OPERATOR_TARGETS),
                    "marker_count": len(RESTORE.OPERATOR_MARKERS),
                    "recurring_schedule_changed": False,
                }

            def inspect_runtime(self) -> dict[str, object]:
                events.append("inspect-runtime")
                return {
                    "qdrant_reachable": True,
                    "workloads_ready": True,
                    "pvc_capacity_bytes": 30,
                    "pvc_free_bytes": 30,
                }

            def load_backup_inputs(self) -> tuple[dict[str, object], dict[str, str]]:
                events.append("load-backup-inputs")
                return (
                    {
                        "apiVersion": "batch/v1",
                        "kind": "CronJob",
                        "metadata": {"name": "backup", "namespace": "memory"},
                        "spec": {
                            "suspend": True,
                            "jobTemplate": {
                                "spec": {
                                    "template": {
                                        "spec": {
                                            "restartPolicy": "Never",
                                            "containers": [
                                                {"name": "backup", "env": []}
                                            ],
                                        }
                                    }
                                }
                            },
                        },
                    },
                    {
                        "AWS_ACCESS_KEY_ID": "synthetic-access",
                        "AWS_EC2_METADATA_DISABLED": "true",
                        "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                        "BACKUP_PREPARE_IMAGE": "example.invalid/mempalace@sha256:" + "1" * 64,
                        "BACKUP_RUN_ID": self_run_id,
                        "BACKUP_S3_URI": f"s3://private-bucket/backups/solidstats-memory/{self_run_id}/",
                        "PHASE20_BINDINGS_JSON": json.dumps(
                            current_bindings, separators=(",", ":"), sort_keys=True
                        ),
                        "PRIVATE_BINDING": "synthetic-value",
                        "QDRANT_API_KEY": "synthetic-qdrant-key",
                        "QDRANT_COLLECTION": "private-collection",
                        "QDRANT_URL": "http://qdrant:6333",
                    },
                )

            def run_command(self, command: tuple[str, ...], **_kwargs: object) -> object:
                events.append(
                    "job-client-dry-run"
                    if "--dry-run=client" in command
                    else "job-server-dry-run"
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            def apply_backup_job(self, job_path: Path) -> dict[str, object]:
                events.append("apply-backup-job")
                self.assertTrue(job_path.is_file())
                return {"created": True, "job_count": 1}

            def wait_backup_job(self) -> dict[str, object]:
                events.append("wait-backup-job")
                return {"complete": True, "job_count": 1}

            def remote_package_inventory(self) -> list[str]:
                events.append("remote-inventory")
                return sorted(RESTORE.PACKAGE_MEMBERS)

            def download_backup_package(self, package_dir: Path) -> None:
                events.append("download-package")
                package_dir.mkdir(mode=0o700)
                (package_dir / "qdrant.snapshot").write_bytes(b"snapshot")
                (package_dir / "mempalace-metadata.tar").write_bytes(b"metadata")
                RESTORE.create_backup_package(
                    package_dir,
                    run_id=self_run_id,
                    phase20_bindings=current_bindings,
                )

            def recover_uploaded_snapshot(
                self,
                *,
                target_collection: str,
                snapshot_path: Path,
                priority: str,
            ) -> dict[str, object]:
                events.append("recovered")
                self.assertEqual("isolated", target_collection)
                self.assertTrue(snapshot_path.is_file())
                self.assertEqual("snapshot", priority)
                return {"status": "ok", "result": True}

            def qdrant_request(
                self,
                method: str,
                path: str,
                body: object = None,
                **_kwargs: object,
            ) -> object:
                events.append(f"qdrant:{method}:{path}")
                if path == "/collections":
                    collections = ["protected"]
                    if "recovered" in events:
                        collections.append("isolated")
                    return {
                        "result": {
                            "collections": [{"name": name} for name in collections]
                        }
                    }
                if path == "/aliases":
                    return {
                        "result": {
                            "aliases": [
                                {
                                    "alias_name": alias,
                                    "collection_name": collection,
                                }
                                for alias, collection in aliases.items()
                            ]
                        }
                    }
                if path == "/collections/isolated" and method == "GET":
                    if "recovered" not in events:
                        raise RESTORE.QdrantNotFound("absent")
                    return {
                        "result": {
                            "status": "green",
                            "optimizer_status": "ok",
                            "points_count": 3,
                            "config": {
                                "params": {
                                    "vectors": {
                                        "size": 3,
                                        "distance": "Cosine",
                                    }
                                }
                            },
                        }
                    }
                if path == "/collections/aliases":
                    for action in body["actions"]:
                        if "create_alias" in action:
                            item = action["create_alias"]
                            aliases[item["alias_name"]] = item["collection_name"]
                        else:
                            aliases.pop(action["delete_alias"]["alias_name"], None)
                    return {"status": "ok"}
                raise AssertionError((method, path))

            def run_phase20_parity(self) -> dict[str, object]:
                events.append("phase20-parity")
                return {
                    "verdict": "pass",
                    "record_count": 3,
                    "field_exact": True,
                    "id_exact": True,
                    "metadata_exact": True,
                    "timestamp_exact": True,
                    "vector_exact": True,
                    "exclusion_exact": True,
                    "ann_exact": True,
                }

            def run_exact_image_probe(self) -> bool:
                events.append("exact-image-probe")
                return aliases.get("probe") == "isolated"

            def verify_prestate(
                self, prestate: dict[str, str]
            ) -> dict[str, object]:
                events.append("verify-prestate")
                self.assertEqual("1" * 64, prestate["active_alias_sha256"])
                return {
                    "active_state_unchanged": True,
                    "active_alias_unchanged": True,
                    "nginx_unchanged": True,
                    "mcp_registration_unchanged": True,
                    "legacy_runtime_unchanged": True,
                    "recurring_schedule_unchanged": True,
                }

            assertEqual = self.assertEqual
            assertTrue = self.assertTrue

        self_run_id = self.run_id
        current_bindings = RESTORE.recompute_phase20_bindings(
            handoff_path=paths["handoff"],
            parity_path=paths["parity"],
            source_inventory_path=paths["source"],
            mapping_contract_path=paths["mapping"],
            transform_manifest_path=paths["transform"],
            bundle_dir=paths["bundle"],
        )
        operator = SyntheticOperator()
        live_environment = {
            "SOLIDSTATS_MEMORY_BUNDLE_DIR": str(paths["bundle"]),
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private_root),
            "SOLIDSTATS_MEMORY_TARGET_COLLECTION": "isolated",
            "SOLIDSTATS_MEMORY_PROTECTED_COLLECTION": "protected",
            "SOLIDSTATS_MEMORY_PROBE_ALIAS": "probe",
            "SOLIDSTATS_MEMORY_VECTOR_CONFIG_JSON": json.dumps(
                {"size": 3, "distance": "Cosine"}
            ),
        }
        with mock.patch.dict(os.environ, live_environment, clear=False):
            for index, stage in enumerate(RESTORE.RUN_STAGES):
                arguments = [
                    stage,
                    "--handoff",
                    str(paths["handoff"]),
                    "--evidence-dir",
                    str(evidence_dir),
                    "--run-id",
                    self.run_id,
                ]
                if index > 0:
                    arguments.append("--resume-run")
                output = io.StringIO()
                errors = io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    result = RESTORE.main(arguments, adapter=operator)
                self.assertEqual(0, result, errors.getvalue())
                self.assertEqual([f"PASS: {stage} completed"], output.getvalue().splitlines())
                self.assertEqual([], errors.getvalue().splitlines())

        evidence_path = evidence_dir / "21-BACKUP-RESTORE-EVIDENCE.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        VALIDATOR.validate_backup_restore_evidence(evidence)
        self.assertEqual({}, {key: value for key, value in aliases.items() if key == "probe"})
        self.assertEqual("protected", aliases["active"])
        self.assertEqual(
            [
                "inspect-preflight",
                "render-manifests",
                "dry-run-client",
                "dry-run-server",
                "apply-manifests",
                "inspect-runtime",
                "load-backup-inputs",
                "job-client-dry-run",
                "job-server-dry-run",
                "apply-backup-job",
                "wait-backup-job",
                "remote-inventory",
                "download-package",
            ],
            events[:13],
        )
        self.assertLess(events.index("phase20-parity"), events.index("exact-image-probe"))
        self.assertLess(events.index("exact-image-probe"), events.index("verify-prestate"))

        before = list(events)
        with mock.patch.dict(os.environ, live_environment, clear=False):
            output = io.StringIO()
            with redirect_stdout(output):
                result = RESTORE.main(
                    [
                        "verify-restore",
                        "--handoff",
                        str(paths["handoff"]),
                        "--evidence-dir",
                        str(evidence_dir),
                        "--run-id",
                        self.run_id,
                        "--resume-run",
                    ],
                    adapter=operator,
                )
        self.assertEqual(0, result)
        self.assertEqual(before, events)

    def test_cli_preflight_rechecks_provenance_before_manifest_apply(self) -> None:
        paths = self.make_phase20_fixture()
        private_root = self.root / "private-drift"
        evidence_dir = self.root / "evidence-drift"
        private_root.mkdir(mode=0o700)
        applied: list[bool] = []

        class DriftingOperator:
            def inspect_preflight(self, **_kwargs: object) -> dict[str, object]:
                return {
                    "reachability": {
                        "kubernetes": True,
                        "s3": True,
                    },
                    "prestate": {
                        "active_alias_sha256": "1" * 64,
                        "nginx_sha256": "2" * 64,
                        "mcp_registration_sha256": "3" * 64,
                        "legacy_runtime_sha256": "4" * 64,
                        "schedule_sha256": "5" * 64,
                    },
                    "quiescence": {"stable": True, "writer_count": 0},
                    "capacity": {
                        "snapshot_bytes": 10,
                        "pvc_requested_bytes": 30,
                        "node_free_bytes": 31,
                        "reserve_bytes": 5,
                    },
                    "operator_markers": {
                        name: f"measured-{name}"
                        for name in RESTORE.OPERATOR_MARKERS
                    },
                    "target_set": list(RESTORE.OPERATOR_TARGETS),
                }

            def render_manifests(self, **_kwargs: object) -> object:
                paths["mapping"].write_bytes(b"{}\n")
                return {"rendered": True}

            @staticmethod
            def validate_manifests(
                _rendered: object, *, mode: str
            ) -> dict[str, object]:
                return {"valid": mode in {"client", "server"}}

            @staticmethod
            def apply_manifests(_rendered: object) -> dict[str, object]:
                applied.append(True)
                return {}

        environment = {
            "SOLIDSTATS_MEMORY_BUNDLE_DIR": str(paths["bundle"]),
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private_root),
            "SOLIDSTATS_MEMORY_TARGET_COLLECTION": "isolated",
            "SOLIDSTATS_MEMORY_PROTECTED_COLLECTION": "protected",
            "SOLIDSTATS_MEMORY_PROBE_ALIAS": "probe",
            "SOLIDSTATS_MEMORY_VECTOR_CONFIG_JSON": json.dumps(
                {"size": 3, "distance": "Cosine"}
            ),
        }
        output = io.StringIO()
        errors = io.StringIO()
        with (
            mock.patch.dict(os.environ, environment, clear=False),
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            result = RESTORE.main(
                [
                    "preflight",
                    "--handoff",
                    str(paths["handoff"]),
                    "--evidence-dir",
                    str(evidence_dir),
                    "--run-id",
                    self.run_id,
                ],
                adapter=DriftingOperator(),
            )

        self.assertEqual(1, result)
        self.assertEqual([], applied)
        self.assertEqual([], output.getvalue().splitlines())
        self.assertEqual(1, len(errors.getvalue().splitlines()))
        self.assertNotIn("measured", errors.getvalue())

    @staticmethod
    def load_probe() -> object:
        specification = importlib.util.spec_from_file_location(
            "solidstats_memory_probe", PROBE_PATH
        )
        assert specification and specification.loader
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def test_alias_cutover_refuses_race_before_mutation(self) -> None:
        aliases = {"active": "concurrent"}
        mutations: list[object] = []

        def request(method: str, path: str, body: object = None) -> object:
            if method == "GET" and path == "/aliases":
                return {
                    "result": {
                        "aliases": [
                            {
                                "alias_name": alias,
                                "collection_name": collection,
                            }
                            for alias, collection in aliases.items()
                        ]
                    }
                }
            mutations.append(body)
            return {"status": "ok"}

        with self.assertRaisesRegex(RESTORE.RestoreControlError, "concurrent"):
            RESTORE.compare_and_switch_alias(
                request,
                alias_name="active",
                target_collection="restored",
                recorded_prestate={"active": "protected"},
            )

        self.assertEqual([], mutations)
        self.assertEqual({"active": "concurrent"}, aliases)

    def test_alias_writer_lease_rejects_interleaving_writer(self) -> None:
        private = self.root / "alias-lease"
        private.mkdir(mode=0o700)
        with mock.patch.dict(os.environ, {
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private),
            "SOLIDSTATS_MEMORY_RUN_ID": "phase21-lock-test",
        }, clear=False):
            with RESTORE.alias_writer_lease():
                with self.assertRaisesRegex(
                    RESTORE.RestoreControlError, "lease is held"
                ):
                    with RESTORE.alias_writer_lease():
                        self.fail("second writer acquired the lease")
        owner = json.loads(
            (private / ".solidstats-memory-alias.lock").read_text()
        )
        self.assertEqual("solidstats-memory-alias-lock/v1", owner["schema"])
        self.assertEqual(
            hashlib.sha256(b"phase21-lock-test").hexdigest(),
            owner["run_id_sha256"],
        )

    def test_alias_writer_lease_rejects_arbitrary_inherited_regular_fd(self) -> None:
        private = self.root / "alias-inherited"
        private.mkdir(mode=0o700)
        arbitrary = private / "arbitrary"
        arbitrary.write_text('{"schema":"fake"}\n', encoding="ascii")
        arbitrary.chmod(0o600)
        descriptor = os.open(arbitrary, os.O_RDWR)
        self.addCleanup(os.close, descriptor)
        with mock.patch.dict(os.environ, {
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private),
            "SOLIDSTATS_MEMORY_RUN_ID": "phase21-inherited-test",
            "SOLIDSTATS_MEMORY_ALIAS_LOCK_FD": str(descriptor),
        }, clear=False):
            with self.assertRaisesRegex(
                RESTORE.RestoreControlError, "ownership is invalid"
            ):
                with RESTORE.alias_writer_lease():
                    self.fail("arbitrary inherited descriptor was accepted")

    def test_alias_writer_lease_accepts_exact_inherited_owner(self) -> None:
        private = self.root / "alias-valid-inherited"
        private.mkdir(mode=0o700)
        path = private / ".solidstats-memory-alias.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(fcntl.flock, descriptor, fcntl.LOCK_UN)
        run_id = "phase21-valid-inherited"
        owner = json.dumps({
            "schema": "solidstats-memory-alias-lock/v1",
            "pid": os.getpid(),
            "run_id_sha256": hashlib.sha256(run_id.encode("ascii")).hexdigest(),
        }, separators=(",", ":"), sort_keys=True).encode("ascii") + b"\n"
        os.write(descriptor, owner)
        os.fsync(descriptor)
        with mock.patch.dict(os.environ, {
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private),
            "SOLIDSTATS_MEMORY_RUN_ID": run_id,
            "SOLIDSTATS_MEMORY_ALIAS_LOCK_FD": str(descriptor),
        }, clear=False):
            with RESTORE.alias_writer_lease():
                pass

    def test_alias_switch_blocks_writer_between_compare_and_post(self) -> None:
        private = self.root / "alias-interleaving"
        private.mkdir(mode=0o700)
        aliases = {"active": "protected"}
        interleaving_blocked = False

        def request(method: str, path: str, body: object = None) -> object:
            nonlocal interleaving_blocked
            if method == "GET":
                return {"result": {"aliases": [
                    {"alias_name": name, "collection_name": collection}
                    for name, collection in aliases.items()
                ]}}
            try:
                with RESTORE.alias_writer_lease():
                    aliases["active"] = "concurrent"
            except RESTORE.RestoreControlError:
                interleaving_blocked = True
            for action in body["actions"]:
                if "delete_alias" in action:
                    aliases.pop(action["delete_alias"]["alias_name"], None)
                else:
                    item = action["create_alias"]
                    aliases[item["alias_name"]] = item["collection_name"]
            return {"status": "ok"}

        with mock.patch.dict(os.environ, {
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private),
            "SOLIDSTATS_MEMORY_RUN_ID": "phase21-interleaving",
        }, clear=False):
            with RESTORE.alias_writer_lease():
                RESTORE.compare_and_switch_alias(
                    request,
                    alias_name="active",
                    target_collection="restored",
                    recorded_prestate={"active": "protected"},
                )
        self.assertTrue(interleaving_blocked)
        self.assertEqual({"active": "restored"}, aliases)

    def test_alias_cutover_and_rollback_restore_exact_prestate(self) -> None:
        aliases = {"active": "protected", "other": "untouched"}
        action_batches: list[list[dict[str, object]]] = []

        def request(method: str, path: str, body: object = None) -> object:
            if method == "GET" and path == "/aliases":
                return {
                    "result": {
                        "aliases": [
                            {
                                "alias_name": alias,
                                "collection_name": collection,
                            }
                            for alias, collection in aliases.items()
                        ]
                    }
                }
            self.assertEqual(("POST", "/collections/aliases"), (method, path))
            actions = body["actions"]
            action_batches.append(actions)
            for action in actions:
                if "delete_alias" in action:
                    aliases.pop(action["delete_alias"]["alias_name"], None)
                if "create_alias" in action:
                    item = action["create_alias"]
                    aliases[item["alias_name"]] = item["collection_name"]
            return {"status": "ok"}

        switched = RESTORE.compare_and_switch_alias(
            request,
            alias_name="active",
            target_collection="restored",
            recorded_prestate={"active": "protected", "other": "untouched"},
        )
        self.assertTrue(switched["read_back_verified"])
        self.assertEqual("restored", aliases["active"])
        self.assertEqual(2, len(action_batches[0]))

        rolled_back = RESTORE.restore_alias_prestate(
            request,
            alias_name="active",
            prestate={"active": "protected", "other": "untouched"},
        )
        self.assertTrue(rolled_back["restored"])
        self.assertEqual(
            {"active": "protected", "other": "untouched"}, aliases
        )

    def test_probe_fixture_covers_auth_session_schema_and_behavior(self) -> None:
        probe = self.load_probe()
        calls: list[tuple[str, str | None, str]] = []
        synthetic_content = (
            "Task: phase21-cutover-uat\n"
            "Outcome: synthetic probe conclusion\n"
            "Decisions: disposable exact-id fixture\n"
            "Validation: read-back then exact cleanup\n"
            "Sources: phase21-cutover-uat"
        )

        tool_schemas = {
            name: {"type": "object", "properties": {}}
            for name in (
                "mempalace_search",
                "mempalace_list_rooms",
                "mempalace_list_drawers",
                "mempalace_get_drawer",
                "mempalace_check_duplicate",
                "mempalace_add_drawer",
                "mempalace_delete_drawer",
                "mempalace_create_tunnel",
            )
        }

        class FixtureTransport:
            def __init__(self) -> None:
                self.capture_created = False

            def request(
                self,
                message: dict[str, object],
                *,
                session_id: str | None,
                token_mode: str,
                protocol_version: str | None,
            ) -> object:
                method = str(message.get("method"))
                calls.append((method, session_id, token_mode))
                if token_mode == "missing":
                    return probe.HttpProbeResult(401, {}, None, "1" * 64)
                if token_mode == "invalid":
                    return probe.HttpProbeResult(403, {}, None, "2" * 64)
                if token_mode == "untrusted-origin":
                    return probe.HttpProbeResult(403, {}, None, "7" * 64)
                if method == "initialize":
                    return probe.HttpProbeResult(
                        200,
                        {"mcp-session-id": "fixture-session"},
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {"tools": {}},
                                "serverInfo": {
                                    "name": "fixture",
                                    "version": "1",
                                },
                            },
                        },
                        "3" * 64,
                    )
                self.assertEqual("fixture-session", session_id)
                self.assertEqual("2025-06-18", protocol_version)
                if method == "notifications/initialized":
                    return probe.HttpProbeResult(202, {}, None, "4" * 64)
                if method == "tools/list":
                    return probe.HttpProbeResult(
                        200,
                        {},
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {
                                "tools": [
                                    {"name": name, "inputSchema": schema}
                                    for name, schema in tool_schemas.items()
                                ]
                            },
                        },
                        "5" * 64,
                    )
                params = message["params"]
                name = params["name"]
                arguments = params["arguments"]
                structured: dict[str, object]
                if name == "mempalace_search":
                    structured = {"results": []}
                elif name == "mempalace_list_rooms":
                    structured = {"rooms": ["operations"]}
                elif name == "mempalace_list_drawers":
                    structured = {
                        "drawers": [
                            {"drawer_id": "archive-fixture", "count": 1}
                        ],
                        "total": 1,
                        "count": 1,
                        "offset": int(arguments.get("offset", 0)),
                        "limit": int(arguments.get("limit", 20)),
                    }
                elif name == "mempalace_check_duplicate":
                    self.assertEqual(synthetic_content, arguments["content"])
                    structured = {"duplicate": False, "match_count": 0}
                elif name == "mempalace_add_drawer":
                    self.assertEqual("infrastructure", arguments["wing"])
                    self.assertEqual("migrations", arguments["room"])
                    self.capture_created = True
                    structured = {"drawer_id": "capture-fixture", "created": True}
                elif name == "mempalace_get_drawer":
                    if arguments["drawer_id"] == "capture-fixture":
                        self.assertTrue(self.capture_created)
                        structured = {
                            "drawer_id": "capture-fixture",
                            "content": synthetic_content,
                        }
                    else:
                        structured = {
                            "drawer_id": "archive-fixture",
                            "content": "untrusted archive lead",
                        }
                elif name == "mempalace_delete_drawer":
                    self.assertEqual("capture-fixture", arguments["drawer_id"])
                    structured = {
                        "success": True,
                        "drawer_id": "capture-fixture",
                        "deleted_ids": ["capture-fixture"],
                        "chunks_deleted": 1,
                    }
                else:
                    raise AssertionError(name)
                return probe.HttpProbeResult(
                    200,
                    {},
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {"structuredContent": structured},
                    },
                    "6" * 64,
                )

            assertEqual = self.assertEqual
            assertTrue = self.assertTrue

        transport = FixtureTransport()
        auth, session = probe.probe_auth_matrix(transport)
        tools = probe.mcp_list_tools(session)
        behavior = probe.probe_behavior_matrix(
            session,
            tools,
            wing="infrastructure",
            archive_wing="infrastructure-archive",
            synthetic_content=synthetic_content,
        )
        evidence = {"auth_checks": auth, "mcp_checks": behavior}
        probe.validate_probe_evidence(evidence)

        self.assertTrue(auth["missing_rejected"])
        self.assertTrue(auth["invalid_rejected"])
        self.assertTrue(auth["untrusted_origin_rejected"])
        self.assertTrue(auth["valid_accepted"])
        self.assertTrue(auth["session_propagated"])
        self.assertTrue(behavior["schema_digest_recorded"])
        self.assertTrue(behavior["scoped_recall"])
        self.assertTrue(behavior["semantic_miss_fallback"])
        self.assertTrue(behavior["archive_untrusted"])
        self.assertTrue(behavior["dedup_checked"])
        self.assertTrue(behavior["capture_shape_valid"])
        self.assertTrue(behavior["read_back_verified"])
        self.assertTrue(behavior["cleanup_exact"])
        serialized = json.dumps(evidence, sort_keys=True)
        for forbidden in (
            synthetic_content,
            "capture-fixture",
            "archive-fixture",
            "fixture-session",
            "untrusted archive lead",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(
            all(
                session_id == "fixture-session"
                for method, session_id, mode in calls
                if mode == "valid" and method != "initialize"
            )
        )

    def test_behavior_probe_cleans_exact_capture_after_lost_add_ack(self) -> None:
        probe = self.load_probe()
        content = (
            "Task: phase21-cutover-uat\nOutcome: synthetic probe conclusion\n"
            "Decisions: disposable exact-id fixture\nValidation: exact cleanup\n"
            "Sources: phase21-cutover-uat"
        )
        stored: dict[str, str] = {}

        def call(_session, name: str, arguments: dict[str, object]):
            if name == "mempalace_list_drawers":
                ids = sorted(stored)
                offset = int(arguments["offset"])
                limit = int(arguments["limit"])
                return {"structuredContent": {
                    "drawers": [
                        {"drawer_id": drawer_id}
                        for drawer_id in ids[offset : offset + limit]
                    ],
                    "total": len(ids),
                    "count": len(ids[offset : offset + limit]),
                    "offset": offset,
                    "limit": limit,
                }}
            if name == "mempalace_search":
                return {"structuredContent": {"results": [
                    {"drawer_id": drawer_id}
                    for drawer_id, value in stored.items()
                    if value == arguments.get("query")
                ]}}
            if name == "mempalace_add_drawer":
                stored["capture-lost-ack"] = str(arguments["content"])
                raise probe.ProbeError("synthetic lost acknowledgement")
            if name == "mempalace_get_drawer":
                drawer_id = str(arguments["drawer_id"])
                return {"structuredContent": {
                    "drawer_id": drawer_id, "content": stored[drawer_id]
                }}
            if name == "mempalace_delete_drawer":
                drawer_id = str(arguments["drawer_id"])
                stored.pop(drawer_id)
                return {"structuredContent": {
                    "success": True, "drawer_id": drawer_id,
                    "deleted_ids": [drawer_id], "chunks_deleted": 1,
                }}
            return {"structuredContent": {}}

        with mock.patch.object(probe, "mcp_call", side_effect=call):
            with self.assertRaisesRegex(probe.ProbeError, "probe failed"):
                probe.probe_behavior_matrix(
                    object(),
                    {name: {} for name in probe.REQUIRED_TOOLS},
                    wing="infrastructure",
                    archive_wing="archive",
                    synthetic_content=content,
                )
        self.assertEqual({}, stored)

    def test_probe_cleanup_inventory_is_paginated_not_ann_derived(self) -> None:
        probe = self.load_probe()
        pages = {
            0: {"drawers": [{"drawer_id": f"drawer-{index}"} for index in range(100)], "total": 101, "count": 100, "offset": 0, "limit": 100},
            100: {"drawers": [{"drawer_id": "drawer-100"}], "total": 101, "count": 1, "offset": 100, "limit": 100},
        }

        def call(_session, name: str, arguments: dict[str, object]):
            self.assertEqual("mempalace_list_drawers", name)
            return {"structuredContent": pages[int(arguments["offset"])]}

        with mock.patch.object(probe, "mcp_call", side_effect=call):
            self.assertEqual(
                101,
                len(probe._listed_drawer_ids(object(), wing="infrastructure")),
            )
        self.assertNotIn("mempalace_search", inspect.getsource(probe._listed_drawer_ids))

    def test_probe_accepts_only_exact_v350_delete_success_schema(self) -> None:
        probe = self.load_probe()
        drawer_id = "capture-fixture"
        exact = {
            "success": True,
            "drawer_id": drawer_id,
            "deleted_ids": [drawer_id, f"{drawer_id}_chunk_000001"],
            "chunks_deleted": 2,
        }
        probe._validate_delete_result(exact, drawer_id=drawer_id)

        near_misses = (
            {"deleted": True},
            {
                "success": False,
                "drawer_id": drawer_id,
                "deleted_ids": [drawer_id],
                "chunks_deleted": 1,
            },
            {
                "success": True,
                "drawer_id": "different-drawer",
                "deleted_ids": [drawer_id],
                "chunks_deleted": 1,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "chunks_deleted": 1,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": [],
                "chunks_deleted": 0,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": [drawer_id],
                "chunks_deleted": True,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": [drawer_id],
                "chunks_deleted": 2,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": drawer_id,
                "chunks_deleted": 1,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": [drawer_id],
                "chunks_deleted": 1,
                "deleted": True,
            },
            {
                "success": True,
                "drawer_id": drawer_id,
                "deleted_ids": [drawer_id],
                "chunks_deleted": 1,
                "error": "ambiguous",
            },
        )
        for payload in near_misses:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    probe.ProbeError, "synthetic capture cleanup failed"
                ):
                    probe._validate_delete_result(payload, drawer_id=drawer_id)

    def test_probe_accepts_stateless_streamable_http_contract(self) -> None:
        probe = self.load_probe()

        class StatelessTransport:
            def request(
                self,
                message: dict[str, object],
                *,
                session_id: str | None,
                token_mode: str,
                protocol_version: str | None,
            ) -> object:
                if token_mode in {"missing", "invalid"}:
                    return probe.HttpProbeResult(401, {}, None, "1" * 64)
                if token_mode == "untrusted-origin":
                    return probe.HttpProbeResult(403, {}, None, "2" * 64)
                self.assertIsNone(session_id)
                if message.get("method") == "initialize":
                    return probe.HttpProbeResult(
                        200,
                        {},
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "fixture", "version": "1"},
                            },
                        },
                        "3" * 64,
                    )
                self.assertEqual("2025-06-18", protocol_version)
                return probe.HttpProbeResult(202, {}, None, "4" * 64)

            assertEqual = self.assertEqual
            assertIsNone = self.assertIsNone

        auth, session = probe.probe_auth_matrix(StatelessTransport())
        self.assertIsNone(session.session_id)
        self.assertEqual("stateless", auth["session_contract"])
        self.assertTrue(auth["session_propagated"])

    def test_probe_evidence_recursively_rejects_private_surfaces(self) -> None:
        probe = self.load_probe()
        for payload in (
            {"auth_checks": {"token": "private"}},
            {"mcp_checks": {"schema_sha256": "not-a-digest"}},
            {"mcp_checks": {"raw_response_body": "private"}},
            {"mcp_checks": ["private"]},
        ):
            with self.subTest(payload=payload), self.assertRaises(probe.ProbeError):
                probe.validate_probe_evidence(payload)

    def test_http_transport_bounds_raw_storage_and_forwards_session(self) -> None:
        probe = self.load_probe()
        raw_root = self.root / "raw-probe"
        raw_root.mkdir(mode=0o700)
        observed_headers: list[dict[str, str]] = []

        class Response:
            status = 200

            def __init__(self, payload: bytes) -> None:
                self.payload = payload
                self.headers = {"Content-Type": "application/json"}

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                return self.payload[:limit]

        def opener(request: object, **_kwargs: object) -> Response:
            observed_headers.append(
                {key.lower(): value for key, value in request.header_items()}
            )
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": 9, "result": {"ok": True}},
                separators=(",", ":"),
            ).encode("utf-8")
            return Response(payload)

        transport = probe.StreamableHttpTransport(
            "http://127.0.0.1/solidstats/mcp",
            "private-fixture-token",
            opener=opener,
            raw_root=raw_root,
        )
        result = probe.http_probe(
            transport,
            {"jsonrpc": "2.0", "id": 9, "method": "ping"},
            session_id="fixture-session",
            protocol_version="2025-06-18",
        )

        self.assertEqual(200, result.status)
        self.assertEqual([], list(raw_root.iterdir()))
        self.assertEqual("Bearer private-fixture-token", observed_headers[0]["authorization"])
        self.assertEqual("fixture-session", observed_headers[0]["mcp-session-id"])
        self.assertEqual("2025-06-18", observed_headers[0]["mcp-protocol-version"])

        def echoing_opener(_request: object, **_kwargs: object) -> Response:
            return Response(b'"private-fixture-token"')

        echoing = probe.StreamableHttpTransport(
            "http://127.0.0.1/solidstats/mcp",
            "private-fixture-token",
            opener=echoing_opener,
            raw_root=raw_root,
        )
        with self.assertRaisesRegex(probe.ProbeError, "authorization") as caught:
            probe.http_probe(
                echoing,
                {"jsonrpc": "2.0", "id": 9, "method": "ping"},
            )
        self.assertNotIn("private-fixture-token", str(caught.exception))

    def test_http_transport_handles_real_auth_rejections_and_strict_successes(
        self,
    ) -> None:
        probe = self.load_probe()
        state: dict[str, object] = {"scenario": "auth"}

        class Handler(http_server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return None

            def send_fixture(
                self,
                status: int,
                body: bytes,
                *,
                content_type: str = "text/html;charset=utf-8",
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (extra_headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length)
                request_id = json.loads(request_body).get("id")
                scenario = state["scenario"]
                authorization = self.headers.get("Authorization")
                origin = self.headers.get("Origin")

                if scenario == "auth":
                    if authorization in {None, "Bearer phase21-invalid-probe"}:
                        self.send_fixture(401, b"<html>Unauthorized</html>")
                        return
                    if origin == "https://phase21-untrusted.invalid":
                        self.send_fixture(403, b"<html>Forbidden</html>")
                        return
                    body = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {"tools": {}},
                            },
                        },
                        separators=(",", ":"),
                    ).encode("utf-8")
                    self.send_fixture(200, body, content_type="application/json")
                    return
                if scenario == "notification":
                    self.send_fixture(202, b"", content_type="application/json")
                    return
                if scenario == "sse":
                    body = (
                        b"event: message\n"
                        + b"data: "
                        + json.dumps(
                            {"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}},
                            separators=(",", ":"),
                        ).encode("utf-8")
                        + b"\n\n"
                    )
                    self.send_fixture(200, body, content_type="text/event-stream")
                    return
                if scenario == "malformed-success":
                    self.send_fixture(200, b"not-json", content_type="application/json")
                    return
                if scenario == "wrong-success-type":
                    self.send_fixture(200, b"{}", content_type="text/plain")
                    return
                if scenario == "echo-body":
                    self.send_fixture(401, b"phase21-invalid-probe")
                    return
                if scenario == "echo-header":
                    self.send_fixture(
                        403,
                        b"forbidden",
                        extra_headers={"X-Probe": "fixture-valid-token"},
                    )
                    return
                if scenario == "oversized":
                    self.send_fixture(401, b"x" * (probe.MAX_BODY_BYTES + 1))
                    return
                if scenario == "redirect":
                    self.send_fixture(302, b"redirect")
                    return
                if scenario == "server-error":
                    self.send_fixture(500, b"server error")
                    return
                raise AssertionError(scenario)

        server = http_server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        raw_root = self.root / "real-http-probe"
        raw_root.mkdir(mode=0o700)
        transport = probe.StreamableHttpTransport(
            f"http://127.0.0.1:{server.server_port}/solidstats/mcp",
            "fixture-valid-token",
            timeout=5,
            raw_root=raw_root,
        )

        for mode, expected_status in (
            ("missing", 401),
            ("invalid", 401),
            ("untrusted-origin", 403),
        ):
            with self.subTest(auth_mode=mode):
                result = probe.http_probe(
                    transport,
                    probe._initialize_message(),
                    token_mode=mode,
                )
                self.assertEqual(expected_status, result.status)
                self.assertIsNone(result.payload)
        initialized = probe.http_probe(transport, probe._initialize_message())
        self.assertEqual(200, initialized.status)
        self.assertEqual(1, initialized.payload["id"])

        state["scenario"] = "notification"
        notification = probe.http_probe(
            transport,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        self.assertEqual(202, notification.status)
        self.assertIsNone(notification.payload)

        state["scenario"] = "sse"
        sse = probe.http_probe(
            transport,
            {"jsonrpc": "2.0", "id": 9, "method": "ping"},
        )
        self.assertEqual(9, sse.payload["id"])

        for scenario, message in (
            ("malformed-success", "malformed"),
            ("wrong-success-type", "content type"),
            ("echo-body", "authorization"),
            ("echo-header", "authorization"),
            ("oversized", "exceeds"),
        ):
            with self.subTest(rejection=scenario):
                state["scenario"] = scenario
                token_mode = "untrusted-origin" if scenario == "echo-header" else "invalid"
                with self.assertRaisesRegex(probe.ProbeError, message):
                    probe.http_probe(
                        transport,
                        {"jsonrpc": "2.0", "id": 9, "method": "ping"},
                        token_mode=token_mode,
                    )

        for scenario in ("redirect", "server-error"):
            with self.subTest(auth_status=scenario):
                state["scenario"] = scenario
                with self.assertRaisesRegex(probe.ProbeError, "auth rejection"):
                    probe.probe_auth_matrix(transport)

    def test_client_command_builder_is_exact_and_preserves_legacy(self) -> None:
        probe = self.load_probe()
        commands = probe.build_client_commands(
            name="solidstats_memory",
            url="https://memory.example/solidstats/mcp",
            token_env="SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertEqual(
            (
                "codex",
                "mcp",
                "add",
                "solidstats_memory",
                "--url",
                "https://memory.example/solidstats/mcp",
                "--bearer-token-env-var",
                "SOLIDSTATS_MEMORY_TOKEN",
            ),
            commands["add"],
        )
        self.assertEqual(
            ("codex", "mcp", "get", "solidstats_memory"), commands["get"]
        )
        self.assertEqual(
            ("codex", "mcp", "remove", "solidstats_memory"),
            commands["remove"],
        )
        self.assertNotIn("mempalace", " ".join(commands["add"]))

        invalid = (
            {"name": "mempalace"},
            {"url": "https://memory.example/mcp"},
            {"token_env": "not-valid"},
        )
        for mutation in invalid:
            arguments = {
                "name": "solidstats_memory",
                "url": "https://memory.example/solidstats/mcp",
                "token_env": "SOLIDSTATS_MEMORY_TOKEN",
                **mutation,
            }
            with self.subTest(mutation=mutation), self.assertRaises(
                probe.ProbeError
            ):
                probe.build_client_commands(**arguments)

    def test_client_policy_add_validate_and_exact_rollback(self) -> None:
        private = self.root / "client-state"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "config.prestate.toml"
        original = (
            b'# unrelated bytes stay byte-identical\nmodel = "gpt-5.6-sol"\n'
            b"\n[mcp_servers.unrelated]\nurl = \"https://other.example/mcp\"\n"
        )
        config.write_bytes(original)
        config.chmod(0o600)

        def policy(command: str, *arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(CLIENT_POLICY_PATH),
                    command,
                    "--config",
                    str(config),
                    *arguments,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        captured = policy("capture", "--prestate", str(prestate))
        self.assertEqual(0, captured.returncode, captured.stderr)
        registration = (
            b"\n[mcp_servers.solidstats_memory]\n"
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
        )
        config.write_bytes(original + registration)
        config.chmod(0o600)
        applied = policy(
            "apply",
            "--prestate",
            str(prestate),
            "--url",
            "https://memory.example/solidstats/mcp",
            "--token-env",
            "SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertEqual(0, applied.returncode, applied.stderr)
        configured = config.read_bytes()
        self.assertTrue(configured.startswith(original))
        self.assertEqual(1, configured.count(b"enabled_tools ="))
        for allowed in (
            b"mempalace_search",
            b"mempalace_list_rooms",
            b"mempalace_list_drawers",
            b"mempalace_get_drawer",
            b"mempalace_check_duplicate",
            b"mempalace_add_drawer",
            b"mempalace_delete_drawer",
        ):
            self.assertIn(allowed, configured)
        for forbidden in (b"tunnel", b"_kg_", b"diary", b"update_drawer"):
            self.assertNotIn(forbidden, configured)
        validated = policy(
            "validate",
            "--url",
            "https://memory.example/solidstats/mcp",
            "--token-env",
            "SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertEqual(0, validated.returncode, validated.stderr)
        probe_validated = subprocess.run(
            [
                sys.executable,
                str(PROBE_PATH),
                "client-policy",
                "--config",
                str(config),
                "--url",
                "https://memory.example/solidstats/mcp",
                "--token-env",
                "SOLIDSTATS_MEMORY_TOKEN",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, probe_validated.returncode, probe_validated.stderr)
        rolled_back = policy("rollback", "--prestate", str(prestate))
        self.assertEqual(0, rolled_back.returncode, rolled_back.stderr)
        self.assertEqual(original, config.read_bytes())

    def test_client_policy_rejects_conflicts_duplicates_and_unsafe_files(self) -> None:
        private = self.root / "policy-rejections"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "prestate.toml"
        prestate.write_bytes(b'model = "prestate"\n')
        prestate.chmod(0o600)
        base = (
            b"[mcp_servers.solidstats_memory]\n"
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
        )

        def run(command: str, *extra: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(CLIENT_POLICY_PATH), command, "--config", str(config), *extra],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        for suffix in (
            b'disabled_tools = ["mempalace_sync"]\n',
            b'enabled_tools = ["mempalace_search"]\n',
            base,
        ):
            with self.subTest(suffix=suffix[-20:]):
                config.write_bytes(base + suffix)
                config.chmod(0o600)
                result = run(
                    "validate" if b"enabled_tools" in suffix else "apply",
                    "--prestate",
                    str(prestate),
                    "--url",
                    "https://memory.example/solidstats/mcp",
                    "--token-env",
                    "SOLIDSTATS_MEMORY_TOKEN",
                )
                self.assertNotEqual(0, result.returncode)
        config.write_bytes(b'model = "no target"\n')
        config.chmod(0o600)
        missing = run(
            "validate",
            "--url",
            "https://memory.example/solidstats/mcp",
            "--token-env",
            "SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertNotEqual(0, missing.returncode)
        config.write_bytes(base)
        config.chmod(0o600)
        for invalid in (
            ("--url", "http://memory.example/solidstats/mcp"),
            ("--token-env", "not-valid"),
            ("--name", "mempalace"),
        ):
            arguments = [
                "--url",
                "https://memory.example/solidstats/mcp",
                "--token-env",
                "SOLIDSTATS_MEMORY_TOKEN",
                *invalid,
            ]
            with self.subTest(invalid=invalid):
                rejected = run("validate", *arguments)
                self.assertNotEqual(0, rejected.returncode)
        config.write_bytes(base)
        config.chmod(0o644)
        unsafe_mode = run(
            "validate",
            "--url",
            "https://memory.example/solidstats/mcp",
            "--token-env",
            "SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertNotEqual(0, unsafe_mode.returncode)
        config.unlink()
        target = private / "target.toml"
        target.write_bytes(base)
        target.chmod(0o600)
        config.symlink_to(target)
        unsafe_link = run(
            "validate",
            "--url",
            "https://memory.example/solidstats/mcp",
            "--token-env",
            "SOLIDSTATS_MEMORY_TOKEN",
        )
        self.assertNotEqual(0, unsafe_link.returncode)

    def test_client_policy_interrupted_write_remains_exactly_rollbackable(self) -> None:
        private = self.root / "policy-interrupt"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "prestate.toml"
        original = b'model = "gpt-5.6-sol"\n'
        config.write_bytes(original)
        config.chmod(0o600)
        capture = subprocess.run(
            [sys.executable, str(CLIENT_POLICY_PATH), "capture", "--config", str(config), "--prestate", str(prestate)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, capture.returncode, capture.stderr)
        registered = original + (
            b"\n[mcp_servers.solidstats_memory]\n"
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
        )
        config.write_bytes(registered)
        config.chmod(0o600)
        temporary = config.with_name(f".{config.name}.solidstats-memory.tmp")
        temporary.write_bytes(b"occupied")
        temporary.chmod(0o600)
        apply = subprocess.run(
            [
                sys.executable,
                str(CLIENT_POLICY_PATH),
                "apply",
                "--config",
                str(config),
                "--prestate",
                str(prestate),
                "--url",
                "https://memory.example/solidstats/mcp",
                "--token-env",
                "SOLIDSTATS_MEMORY_TOKEN",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(0, apply.returncode)
        self.assertEqual(registered, config.read_bytes())
        temporary.unlink()
        rollback = subprocess.run(
            [sys.executable, str(CLIENT_POLICY_PATH), "rollback", "--config", str(config), "--prestate", str(prestate)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(0, rollback.returncode, rollback.stderr)
        self.assertEqual(original, config.read_bytes())

    def test_client_retirement_is_one_pre_authorized_transaction(self) -> None:
        private = self.root / "client-retirement"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "prestate.toml"
        result = private / "retirement.result"
        unrelated = (
            b'[mcp_servers.unrelated]\nurl = "https://other.example/mcp"\n\n'
        )
        legacy = b'[mcp_servers.mempalace]\ncommand = "legacy"\n\n'
        current = unrelated + legacy + (
            b'[mcp_servers.solidstats_memory]\n'
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
            b'enabled_tools = ["mempalace_search","mempalace_list_rooms",'
            b'"mempalace_list_drawers","mempalace_get_drawer",'
            b'"mempalace_check_duplicate","mempalace_add_drawer",'
            b'"mempalace_delete_drawer"]\n'
        )
        config.write_bytes(current)
        config.chmod(0o600)
        prestate.write_bytes(unrelated)
        prestate.chmod(0o600)
        metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
        metadata.write_text(
            json.dumps(
                {
                    "schema": "solidstats-memory-client-policy/v1",
                    "accepted_sha256": [hashlib.sha256(current).hexdigest()],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="ascii",
        )
        metadata.chmod(0o600)

        for failed_stage in ("removed", "readback", "policy", "evidence"):
            with self.subTest(stage=failed_stage):
                config.write_bytes(current)
                config.chmod(0o600)
                result.unlink(missing_ok=True)

                def remove(expected: bytes) -> None:
                    config.write_bytes(expected)
                    config.chmod(0o600)

                def stage(name: str) -> None:
                    if name == failed_stage:
                        raise CLIENT_POLICY.PolicyError("injected retirement failure")

                with self.assertRaises(CLIENT_POLICY.PolicyError):
                    CLIENT_POLICY.retire_transaction(
                        config,
                        prestate,
                        result,
                        url="https://memory.example/solidstats/mcp",
                        token_env="SOLIDSTATS_MEMORY_TOKEN",
                        remove=remove,
                        stage=stage,
                    )
                self.assertEqual(current, config.read_bytes())
                self.assertFalse(result.exists())

        config.write_bytes(current)
        config.chmod(0o600)
        def partial_remove(_expected: bytes) -> None:
            config.write_bytes(b"partial external mutation\n")
            raise CLIENT_POLICY.PolicyError("injected partial remove failure")
        with self.assertRaises(CLIENT_POLICY.PolicyError):
            CLIENT_POLICY.retire_transaction(
                config, prestate, result,
                url="https://memory.example/solidstats/mcp",
                token_env="SOLIDSTATS_MEMORY_TOKEN",
                remove=partial_remove,
            )
        self.assertEqual(b"partial external mutation\n", config.read_bytes())

        config.write_bytes(current)
        config.chmod(0o600)
        CLIENT_POLICY.retire_transaction(
            config,
            prestate,
            result,
            url="https://memory.example/solidstats/mcp",
            token_env="SOLIDSTATS_MEMORY_TOKEN",
            remove=lambda expected: config.write_bytes(expected),
        )
        retired = config.read_bytes()
        self.assertNotIn(b"[mcp_servers.mempalace]", retired)
        self.assertIn(unrelated, retired)
        self.assertEqual(1, retired.count(b"[mcp_servers.unrelated]"))
        fields = dict(
            line.split("=", 1) for line in result.read_text().splitlines()
        )
        self.assertEqual("solidstats-memory-client-retirement/v3", fields["schema"])
        self.assertEqual("true", fields["unrelated_unchanged"])
        self.assertEqual(fields["unrelated_pre_sha256"], fields["unrelated_post_sha256"])
        self.assertEqual("true", fields["sole_solidstats_client"])
        pre_fields = dict(
            line.split("=", 1)
            for line in (private / "client-pre-retirement.result").read_text().splitlines()
        )
        self.assertEqual("true", pre_fields["legacy_client_present"])
        self.assertEqual("2", pre_fields["solidstats_client_count"])
        config.write_bytes(retired + b"# drift\n")
        with self.assertRaises(CLIENT_POLICY.PolicyError):
            CLIENT_POLICY.restore_retirement(config, result)
        config.write_bytes(retired)
        CLIENT_POLICY.restore_retirement(config, result)
        self.assertEqual(current, config.read_bytes())

    def test_client_rollback_preserves_unrelated_current_config(self) -> None:
        private = self.root / "client-rollback-current"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "prestate.toml"
        result = private / "rollback.result"
        legacy = b'[mcp_servers.mempalace]\ncommand = "legacy"\ntimeout = 30\n\n'
        original = b'model = "gpt-5.6-sol"\n\n' + legacy
        current_legacy = (
            b'[mcp_servers.mempalace]\ntimeout = 30\ncommand = "legacy"\n\n'
        )
        drift = b'[plugins.current]\nenabled = true\n\n'
        replacement = (
            b'[mcp_servers.solidstats_memory]\n'
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
            b'enabled_tools = ["mempalace_search","mempalace_list_rooms",'
            b'"mempalace_list_drawers","mempalace_get_drawer",'
            b'"mempalace_check_duplicate","mempalace_add_drawer",'
            b'"mempalace_delete_drawer"]\n'
        )
        current = b'model = "gpt-5.6-sol"\n\n' + current_legacy + drift + replacement
        expected = b'model = "gpt-5.6-sol"\n\n' + current_legacy + drift
        config.write_bytes(current)
        config.chmod(0o600)
        prestate.write_bytes(original)
        prestate.chmod(0o600)
        metadata = prestate.with_suffix(prestate.suffix + ".policy.json")

        def write_metadata() -> None:
            metadata.write_text(
                json.dumps(
                    {
                        "schema": "solidstats-memory-client-policy/v1",
                        "accepted_sha256": [hashlib.sha256(current).hexdigest()],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="ascii",
            )
            metadata.chmod(0o600)

        write_metadata()
        for failed_stage in ("removed", "readback", "prestate", "evidence"):
            with self.subTest(stage=failed_stage):
                config.write_bytes(current)
                config.chmod(0o600)
                prestate.write_bytes(original)
                prestate.chmod(0o600)
                if not metadata.exists():
                    write_metadata()
                result.unlink(missing_ok=True)

                def remove(updated: bytes) -> None:
                    config.write_bytes(updated)
                    config.chmod(0o600)

                def stage(name: str) -> None:
                    if name == failed_stage:
                        raise CLIENT_POLICY.PolicyError("injected rollback failure")

                with self.assertRaises(CLIENT_POLICY.PolicyError):
                    CLIENT_POLICY.rollback_registration_transaction(
                        config,
                        prestate,
                        result,
                        url="https://memory.example/solidstats/mcp",
                        token_env="SOLIDSTATS_MEMORY_TOKEN",
                        remove=remove,
                        stage=stage,
                    )
                self.assertEqual(current, config.read_bytes())
                self.assertEqual(original, prestate.read_bytes())
                self.assertTrue(metadata.exists())
                self.assertFalse(result.exists())

        CLIENT_POLICY.rollback_registration_transaction(
            config,
            prestate,
            result,
            url="https://memory.example/solidstats/mcp",
            token_env="SOLIDSTATS_MEMORY_TOKEN",
            remove=lambda updated: config.write_bytes(updated),
        )
        self.assertEqual(expected, config.read_bytes())
        self.assertEqual(expected, prestate.read_bytes())
        self.assertFalse(metadata.exists())
        self.assertIn(b"unrelated_current_bytes_preserved=true", result.read_bytes())

        config.write_bytes(current)
        config.chmod(0o600)
        prestate.write_bytes(original)
        prestate.chmod(0o600)
        write_metadata()
        result.unlink()
        external = b'[plugins.rollback_late_edit]\nenabled = true\n\n'

        def late_stage(name: str) -> None:
            if name == "prepared_replace":
                replacement_path = config.with_name("external-rollback-config")
                replacement_path.write_bytes(current + external)
                replacement_path.chmod(0o600)
                os.replace(replacement_path, config)

        with self.assertRaises(CLIENT_POLICY.PolicyError):
            CLIENT_POLICY.rollback_registration_transaction(
                config, prestate, result,
                url="https://memory.example/solidstats/mcp",
                token_env="SOLIDSTATS_MEMORY_TOKEN",
                stage=late_stage,
            )
        self.assertEqual(current + external, config.read_bytes())
        self.assertFalse(result.exists())
        self.assertFalse(config.with_name(f".{config.name}.solidstats-memory.tmp").exists())

    def test_client_retirement_rebases_unrelated_edit_before_replace(self) -> None:
        private = self.root / "client-retirement-rebase"
        private.mkdir(mode=0o700)
        config = private / "config.toml"
        prestate = private / "prestate.toml"
        result = private / "retirement.result"
        legacy = b'[mcp_servers.mempalace]\ncommand = "legacy"\n\n'
        replacement = (
            b'[mcp_servers.solidstats_memory]\n'
            b'url = "https://memory.example/solidstats/mcp"\n'
            b'bearer_token_env_var = "SOLIDSTATS_MEMORY_TOKEN"\n'
            b'enabled_tools = ["mempalace_search","mempalace_list_rooms",'
            b'"mempalace_list_drawers","mempalace_get_drawer",'
            b'"mempalace_check_duplicate","mempalace_add_drawer",'
            b'"mempalace_delete_drawer"]\n'
        )
        current = b'model = "gpt-5.6-sol"\n\n' + legacy + replacement
        concurrent = b'[plugins.concurrent]\nenabled = true\n\n'
        config.write_bytes(current)
        config.chmod(0o600)
        prestate.write_bytes(b'model = "gpt-5.6-sol"\n')
        prestate.chmod(0o600)
        metadata = prestate.with_suffix(prestate.suffix + ".policy.json")
        metadata.write_text(json.dumps({
            "schema": "solidstats-memory-client-policy/v1",
            "accepted_sha256": [hashlib.sha256(current).hexdigest()],
        }, separators=(",", ":"), sort_keys=True) + "\n", encoding="ascii")
        metadata.chmod(0o600)

        def stage(name: str) -> None:
            if name == "before_replace":
                config.write_bytes(current + concurrent)
                config.chmod(0o600)

        CLIENT_POLICY.retire_transaction(
            config, prestate, result,
            url="https://memory.example/solidstats/mcp",
            token_env="SOLIDSTATS_MEMORY_TOKEN",
            stage=stage,
        )
        observed = config.read_bytes()
        self.assertIn(concurrent, observed)
        self.assertNotIn(b"[mcp_servers.mempalace]", observed)
        self.assertIn(b"[mcp_servers.solidstats_memory]", observed)

        config.write_bytes(current)
        config.chmod(0o600)
        result.unlink(missing_ok=True)
        result.with_suffix(result.suffix + ".prestate").unlink(missing_ok=True)
        (private / "client-pre-retirement.result").unlink(missing_ok=True)
        external = b'[plugins.after_final_read]\nenabled = true\n\n'

        def late_stage(name: str) -> None:
            if name == "prepared_replace":
                replacement_path = config.with_name("external-retirement-config")
                replacement_path.write_bytes(current + external)
                replacement_path.chmod(0o600)
                os.replace(replacement_path, config)

        with self.assertRaisesRegex(CLIENT_POLICY.PolicyError, "failed"):
            CLIENT_POLICY.retire_transaction(
                config, prestate, result,
                url="https://memory.example/solidstats/mcp",
                token_env="SOLIDSTATS_MEMORY_TOKEN",
                stage=late_stage,
            )
        self.assertEqual(current + external, config.read_bytes())
        self.assertFalse(result.exists())
        self.assertFalse(config.with_name(f".{config.name}.solidstats-memory.tmp").exists())

    def test_cutover_self_test_exercises_reverse_order_rollback(self) -> None:
        result = subprocess.run(
            ["bash", str(CUTOVER_PATH), "--self-test"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("SELF_TEST PASSED", result.stdout)
        self.assertIn(
            "client nginx alias workload legacy",
            result.stdout,
        )

    def test_remote_operator_executes_exact_shared_site_lifecycle(self) -> None:
        remote = self.root / "remote-operator"
        remote.mkdir(mode=0o700)
        operator = remote / "operate-solidstats-memory-cutover-remote.sh"
        renderer = remote / "render-solidstats-memory-shared-nginx.py"
        shutil.copy2(ROOT / "scripts" / operator.name, operator)
        shutil.copy2(ROOT / "scripts" / renderer.name, renderer)
        operator.chmod(0o700)
        renderer.chmod(0o700)

        fixture = self.root / "fixture"
        fixture.mkdir(mode=0o700)
        legacy_state = fixture / "legacy.state"
        freeze_state = fixture / "freeze.state"
        new_state = fixture / "new.state"
        mempalace_uid = fixture / "mempalace.uid"
        qdrant_uid = fixture / "qdrant.uid"
        backup_schedule = fixture / "backup.schedule"
        inventory_output = fixture / "inventory.output"
        events = fixture / "events"
        legacy_state.write_text("running\n", encoding="ascii")
        freeze_state.write_text("running\n", encoding="ascii")
        new_state.write_text("stopped\n", encoding="ascii")
        mempalace_uid.write_text("mempalace-before\n", encoding="ascii")
        qdrant_uid.write_text("qdrant-before\n", encoding="ascii")
        backup_schedule.write_text("true\n", encoding="ascii")
        inventory_output.write_text("0" * 64 + " 2 1\n", encoding="ascii")

        runuser_path = fixture / "runuser"
        runuser_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            '[[ "$1" == -u && "$2" == palace && "$3" == -- ]] || exit 9\n'
            'shift 3\nexec "$@"\n',
            encoding="utf-8",
        )
        docker_path = fixture / "docker"
        docker_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f"legacy={legacy_state}\nfreeze={freeze_state}\nlog={events}\n"
            '[[ "$1" == --host && "$2" == unix:///run/user/1001/docker.sock ]] || exit 9\n'
            'shift 2\naction=$1\nshift\n'
            'if [[ "$action" == exec ]]; then [[ "$1" == solidstats-container ]] || exit 9; printf "%064d\\n" 0; exit 0; fi\n'
            'container=${@: -1}\n'
            'case "$container" in solidstats-container) state="$legacy" ;; freeze-lock-container) state="$freeze" ;; *) exit 9 ;; esac\n'
            'case "$action" in inspect) [[ "$(cat "$state")" == running ]] && echo true || echo false ;; start) printf "running\\n" >"$state"; printf "%s:start\\n" "$container" >>"$log" ;; stop) printf "stopped\\n" >"$state"; printf "%s:stop\\n" "$container" >>"$log" ;; *) exit 9 ;; esac\n',
            encoding="utf-8",
        )
        kubectl_path = fixture / "kubectl"
        kubectl_path.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            f"state={new_state}\nmem_uid={mempalace_uid}\nqdrant_uid={qdrant_uid}\nschedule={backup_schedule}\ninventory={inventory_output}\nlog={events}\n"
            '[[ " $* " == *" --context fixture-context "* && " $* " == *" -n solidstats-memory "* ]] || exit 9\n'
            'if [[ " $* " == *" get deployment mempalace "* && " $* " == *"containers[?(@.name==\\\"mempalace\\\")].image"* ]]; then printf "ghcr.io/solid-stats/mempalace@sha256:%064d" 0; '
            'elif [[ " $* " == *" get deployment mempalace "* ]]; then replicas=$(cat "$state"); [[ "$replicas" == running ]] && replicas=1 || replicas=0; echo -n "$replicas"; '
            'elif [[ " $* " == *" get pods -l app.kubernetes.io/name=mempalace "* ]]; then cat "$mem_uid"; '
            'elif [[ " $* " == *" get pods -l app.kubernetes.io/name=qdrant "* ]]; then cat "$qdrant_uid"; '
            'elif [[ " $* " == *" exec deployment/mempalace "* ]]; then exit 88; '
            'elif [[ " $* " == *" delete pod phase21-qdrant-inventory-"* ]]; then printf "inventory:pod-cleanup\\n" >>"$log"; '
            'elif [[ " $* " == *" delete networkpolicy phase21-qdrant-inventory-"* ]]; then printf "inventory:policy-cleanup\\n" >>"$log"; '
            'elif [[ " $* " == *" apply -f "* ]]; then printf "inventory:apply\\n" >>"$log"; '
            'elif [[ " $* " == *" wait --for=jsonpath={.status.phase}=Succeeded pod/phase21-qdrant-inventory-"* ]]; then true; '
            'elif [[ " $* " == *" logs pod/phase21-qdrant-inventory-"* ]]; then cat "$inventory"; '
            'elif [[ " $* " == *" rollout restart deployment/mempalace "* ]]; then printf "mempalace-after\\n" >"$mem_uid"; printf "mempalace:restart\\n" >>"$log"; '
            'elif [[ " $* " == *" rollout restart statefulset/qdrant "* ]]; then printf "qdrant-after\\n" >"$qdrant_uid"; printf "qdrant:restart\\n" >>"$log"; '
            'elif [[ " $* " == *" scale deployment/mempalace "* ]]; then [[ " $* " == *"--replicas=1"* ]] && printf "running\\n" >"$state" || printf "stopped\\n" >"$state"; printf "new:scale\\n" >>"$log"; '
            'elif [[ " $* " == *" rollout status deployment/mempalace "* ]]; then [[ "$(cat "$state")" == running ]]; '
            'elif [[ " $* " == *" rollout status statefulset/qdrant "* ]]; then true; '
            'elif [[ " $* " == *" get cronjob solidstats-memory-backup "* && " $* " == *" -o json "* ]]; then printf "{\\"kind\\":\\"CronJob\\",\\"metadata\\":{\\"name\\":\\"solidstats-memory-backup\\"},\\"spec\\":{\\"jobTemplate\\":{\\"spec\\":{}}}}"; '
            'elif [[ " $* " == *" get cronjob solidstats-memory-backup "* ]]; then printf "%s:Forbid" "$(cat "$schedule")"; '
            'elif [[ " $* " == *" patch cronjob solidstats-memory-backup "* ]]; then [[ " $* " == *"\\\"suspend\\\":false"* ]] && printf "false\\n" >"$schedule" || printf "true\\n" >"$schedule"; '
            'elif [[ " $* " == *" delete job solidstats-memory-backup-"* ]]; then true; '
            'elif [[ " $* " == *" create job solidstats-memory-backup-"* ]]; then printf "stopped\\n" >"$state"; printf "backup:job-started\\n" >>"$log"; '
            'elif [[ " $* " == *" wait --for=condition=Complete job/solidstats-memory-backup-"* ]]; then exit 7; '
            'else exit 9; fi\n',
            encoding="utf-8",
        )
        curl_path = fixture / "curl"
        curl_path.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            f"[[ \"${{@: -1}}\" == http://10.23.45.67:8765/healthz && \"$(cat '{new_state}')\" == running ]]\n",
            encoding="utf-8",
        )
        nginx_path = fixture / "nginx-binary"
        nginx_path.write_text(
            f"#!/usr/bin/env bash\nset -eu\n[[ \"$1\" == -t ]]\nprintf 'nginx:test\\n' >>'{events}'\n",
            encoding="utf-8",
        )
        systemctl_path = fixture / "systemctl"
        systemctl_path.write_text(
            f"#!/usr/bin/env bash\nset -eu\n[[ \"$1\" == reload && \"$2\" == nginx.service ]]\nprintf 'nginx:reload\\n' >>'{events}'\n",
            encoding="utf-8",
        )
        python_path = fixture / "python"
        shutil.copy2(Path(sys.executable).resolve(), python_path)
        for binary in (runuser_path, docker_path, kubectl_path, curl_path, nginx_path, systemctl_path):
            binary.chmod(0o700)
        python_path.chmod(0o700)

        nginx_root = fixture / "nginx"
        available_dir = nginx_root / "sites-available"
        enabled_dir = nginx_root / "sites-enabled"
        available_dir.mkdir(parents=True)
        enabled_dir.mkdir()
        available = available_dir / "shared-memory.conf"
        enabled = enabled_dir / "shared-memory.conf"
        original = (
            b"server {\n"
            b"    listen 8443 ssl http2 default_server;\n"
            b"    listen [::]:8443 ssl http2 default_server;\n"
            b"    ssl_certificate /private/certificate;\n"
            b"    ssl_certificate_key /private/key;\n"
            b"    location /personal/ {\n"
            b"        proxy_pass http://127.0.0.1:8766;\n"
            b"    }\n"
            b"    location /solidstats/ {\n"
            b"        proxy_pass http://127.0.0.1:8767/;\n"
            b"    }\n"
            b"}\n"
        )
        available.write_bytes(original)
        available.chmod(0o640)
        enabled.symlink_to(available)
        state_root = fixture / "state"
        config = Path(f"{operator}.config")
        config.write_text(
            "\n".join(
                (
                    "schema=solidstats-memory-remote-cutover-config/v1",
                    f"state_root={state_root}",
                    f"runuser_path={runuser_path}",
                    f"docker_path={docker_path}",
                    f"kubectl_path={kubectl_path}",
                    f"curl_path={curl_path}",
                    f"nginx_path={nginx_path}",
                    f"systemctl_path={systemctl_path}",
                    f"python_path={python_path}",
                    "nginx_unit=nginx.service",
                    "kube_context=fixture-context",
                    "new_namespace=solidstats-memory",
                    "new_deployment=mempalace",
                    "new_expected_replicas=1",
                    f"nginx_root={nginx_root}",
                    f"nginx_available_path={available}",
                    f"nginx_enabled_path={enabled}",
                    "command_timeout_seconds=10",
                    "backup_timeout_seconds=30",
                    "legacy_user=palace",
                    "legacy_socket=/run/user/1001/docker.sock",
                    "legacy_container=solidstats-container",
                    "freeze_lock_container=freeze-lock-container",
                    "old_upstream=http://127.0.0.1:8767/",
                    "new_upstream=http://10.23.45.67:8765/",
                    "new_health_url=http://10.23.45.67:8765/healthz",
                )
            )
            + "\n",
            encoding="ascii",
        )
        config.chmod(0o600)
        run_id = "a" * 64
        template = (
            ROOT
            / "config/nginx/sites-available/solidstats-memory-shared-cutover.patch.template"
        ).read_bytes()

        def run(operation: str, *, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                ["bash", str(operator), operation, run_id],
                input=stdin,
                capture_output=True,
                timeout=20,
                check=False,
            )

        self.assertEqual(0, run("capture-prestate").returncode)
        self.assertEqual(0, run("capture-prestate").returncode)
        self.assertEqual(0o700, state_root.stat().st_mode & 0o777)
        run_root = state_root / run_id
        self.assertEqual(0o700, run_root.stat().st_mode & 0o777)
        self.assertTrue(all((path.stat().st_mode & 0o777) == 0o600 for path in run_root.iterdir()))
        prestate = (run_root / "prestate").read_text(encoding="ascii")
        self.assertIn("freeze_lock_state=running", prestate)

        self.assertEqual(0, run("stop-legacy-start-new").returncode)
        self.assertEqual("stopped", legacy_state.read_text().strip())
        self.assertEqual("running", new_state.read_text().strip())
        self.assertEqual("running", freeze_state.read_text().strip())
        before_idempotent = events.read_bytes()
        self.assertEqual(0, run("stop-legacy-start-new").returncode)
        self.assertEqual(before_idempotent, events.read_bytes())

        for operation in ("restart-mempalace", "restart-qdrant"):
            result = run(operation)
            self.assertEqual(0, result.returncode, result.stderr.decode())
            result_path = run_root / f"{operation}.result"
            self.assertEqual(0o600, result_path.stat().st_mode & 0o777)
            public_result = result_path.read_text(encoding="ascii")
            self.assertNotIn("10.23.45.67", public_result)
            self.assertNotIn("Bearer", public_result)
            self.assertNotIn("/private/", public_result)

        inventory_manifest = (run_root / "qdrant-inventory.yaml").read_text()
        self.assertIn("secretKeyRef:", inventory_manifest)
        self.assertIn("name: qdrant-runtime", inventory_manifest)
        self.assertIn("key: QDRANT_API_KEY", inventory_manifest)
        self.assertIn("solidstats.memory/role: qdrant-admin-inventory", inventory_manifest)
        self.assertIn("kind: NetworkPolicy", inventory_manifest)
        self.assertIn("policyTypes: [Egress]", inventory_manifest)
        self.assertIn("policyTypes: [Ingress]", inventory_manifest)
        self.assertIn("app.kubernetes.io/name: qdrant", inventory_manifest)
        self.assertIn('get("/aliases")', inventory_manifest)
        self.assertNotIn('get("/collections/aliases")', inventory_manifest)
        self.assertIn("automountServiceAccountToken: false", inventory_manifest)
        self.assertIn("readOnlyRootFilesystem: true", inventory_manifest)
        self.assertNotIn("MEMPALACE_QDRANT_API_KEY", operator.read_text())
        self.assertNotIn("exec deployment/mempalace", operator.read_text())
        successful_events = events.read_text()
        self.assertGreaterEqual(successful_events.count("inventory:pod-cleanup"), 4)
        self.assertGreaterEqual(successful_events.count("inventory:policy-cleanup"), 4)
        inventory_output.write_text("0" * 64 + " 2 1\nextra\n", encoding="ascii")
        cleanup_before = events.read_text().count("inventory:pod-cleanup")
        malformed = run("verify-retained-collections")
        self.assertNotEqual(0, malformed.returncode)
        self.assertGreater(events.read_text().count("inventory:pod-cleanup"), cleanup_before)
        self.assertNotIn("QDRANT_API_KEY", malformed.stdout.decode())
        inventory_output.write_text("0" * 64 + " 2 1\n", encoding="ascii")

        self.assertEqual(0, run("suspend-backup-schedule").returncode)
        self.assertEqual("true", backup_schedule.read_text().strip())
        package = run_root / "guard-package"
        package.mkdir(mode=0o700)
        candidate_digest = hashlib.sha256(b'{}').hexdigest()
        (package / "candidate-template.sha256").write_text(
            candidate_digest + "\n", encoding="ascii"
        )
        (package / "candidate-template.sha256").chmod(0o600)
        self.assertEqual(0, run("capture-backup-template-digest").returncode)

        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
        (run_root / "recheck-backup-api-access.state").write_text(
            "complete\n", encoding="ascii"
        )
        (run_root / "recheck-backup-api-access.result").write_text(
            "\n".join(
                (
                    "schema=solidstats-memory-remote-operation-result/v1",
                    "operation=recheck-backup-api-access",
                    "sequence=240",
                    f"config_sha256={config_sha}",
                    f"run_id_sha256={run_id}",
                    "binding_current=true",
                )
            )
            + "\n",
            encoding="ascii",
        )
        for path in (
            run_root / "recheck-backup-api-access.state",
            run_root / "recheck-backup-api-access.result",
        ):
            path.chmod(0o600)
        writer_prestate = run("record-backup-writer-prestate")
        self.assertEqual(0, writer_prestate.returncode, writer_prestate.stderr.decode())
        consistency = run("prove-backup-consistency")
        self.assertNotEqual(0, consistency.returncode)
        self.assertEqual("running", new_state.read_text().strip())
        self.assertIn(
            "backup:job-started",
            events.read_text(),
            (consistency.stderr.decode(), sorted(path.name for path in run_root.iterdir())),
        )
        self.assertIn("new:scale", events.read_text())

        self.assertNotEqual(0, run("install-nginx").returncode)
        self.assertEqual(original, available.read_bytes())
        self.assertEqual(0, run("install-nginx", stdin=template).returncode)
        installed = available.read_bytes()
        expected = original.replace(
            b"proxy_pass http://127.0.0.1:8767/;",
            b"proxy_pass http://10.23.45.67:8765/;",
            1,
        )
        self.assertEqual(expected, installed)
        self.assertIn(b"proxy_pass http://10.23.45.67:8765/;", installed)
        self.assertIn(b"proxy_pass http://127.0.0.1:8766;", installed)
        self.assertIn(b"ssl_certificate /private/certificate;", installed)
        self.assertNotIn(b"proxy_pass http://127.0.0.1:8767/;", installed)
        self.assertEqual(0o640, available.stat().st_mode & 0o777)
        self.assertEqual(str(available), os.readlink(enabled))
        request_path = "/solidstats/mcp"
        location_prefix = "/solidstats/"
        upstream_root_path = "/"
        self.assertEqual(
            "/mcp",
            upstream_root_path + request_path.removeprefix(location_prefix),
        )
        self.assertEqual(
            original,
            installed.replace(
                b"proxy_pass http://10.23.45.67:8765/;",
                b"proxy_pass http://127.0.0.1:8767/;",
                1,
            ),
        )

        self.assertEqual(0, run("rollback-nginx").returncode)
        self.assertEqual(original, available.read_bytes())
        self.assertEqual(0o640, available.stat().st_mode & 0o777)
        self.assertEqual(str(available), os.readlink(enabled))
        self.assertEqual(0, run("stop-new").returncode)
        self.assertEqual(0, run("start-legacy").returncode)
        legacy_probe = run("verify-legacy-behavior")
        self.assertEqual(0, legacy_probe.returncode, legacy_probe.stderr.decode())
        self.assertIn(b"legacy_mcp_behavior=true", legacy_probe.stdout)
        self.assertEqual("running", legacy_state.read_text().strip())
        self.assertEqual("stopped", new_state.read_text().strip())
        self.assertEqual("running", freeze_state.read_text().strip())

        for cycle in range(2):
            self.assertEqual(0, run("rearm-forward-cycle").returncode, cycle)
            self.assertEqual(0, run("stop-legacy-start-new").returncode, cycle)
            self.assertEqual(0, run("install-nginx", stdin=template).returncode, cycle)
            if cycle == 0:
                self.assertEqual(0, run("rollback-nginx").returncode)
                self.assertEqual(0, run("stop-new").returncode)
                self.assertEqual(0, run("start-legacy").returncode)
        self.assertEqual(0, run("rollback-nginx").returncode)
        self.assertEqual(0, run("stop-new").returncode)
        self.assertEqual(0, run("start-legacy").returncode)

        race_run = "b" * 64
        run_id = race_run
        self.assertEqual(0, run("capture-prestate").returncode)
        legacy_state.write_text("stopped\n", encoding="ascii")
        raced = run("stop-legacy-start-new")
        self.assertNotEqual(0, raced.returncode)
        self.assertEqual("stopped", new_state.read_text().strip())
        legacy_state.write_text("running\n", encoding="ascii")

        nginx_race_run = "c" * 64
        run_id = nginx_race_run
        self.assertEqual(0, run("capture-prestate").returncode)
        enabled.unlink()
        enabled.symlink_to(available_dir / "other.conf")
        nginx_race = run("install-nginx", stdin=template)
        self.assertNotEqual(0, nginx_race.returncode)
        self.assertEqual(original, available.read_bytes())

        enabled.unlink()
        enabled.symlink_to(available)
        run_id = "d" * 64
        self.assertEqual(0, run("capture-prestate").returncode)
        original_config = config.read_text(encoding="ascii")
        config.write_text(
            original_config.replace(
                "command_timeout_seconds=10", "command_timeout_seconds=11"
            ),
            encoding="ascii",
        )
        config.chmod(0o600)
        self.assertNotEqual(0, run("stop-legacy-start-new").returncode)
        config.write_text(original_config, encoding="ascii")
        config.chmod(0o600)
        remote.chmod(0o755)
        run_id = "e" * 64
        self.assertNotEqual(0, run("capture-prestate").returncode)
        remote.chmod(0o700)

        original_config = config.read_text(encoding="ascii")
        invalid_bindings = (
            (
                "old_upstream=http://127.0.0.1:8767/",
                "old_upstream=http://127.0.0.1:8767",
            ),
            (
                "old_upstream=http://127.0.0.1:8767/",
                "old_upstream=http://127.0.0.1:8767//",
            ),
            (
                "old_upstream=http://127.0.0.1:8767/",
                "old_upstream=http://127.0.0.1:8767/mcp/",
            ),
            (
                "new_upstream=http://10.23.45.67:8765/",
                "new_upstream=http://10.23.45.67:8765",
            ),
            (
                "new_upstream=http://10.23.45.67:8765/",
                "new_upstream=http://10.23.45.67:8765/?query=1",
            ),
            (
                "new_upstream=http://10.23.45.67:8765/",
                "new_upstream=http://10.23.45.67:8765/#fragment",
            ),
        )
        for index, (valid, invalid) in enumerate(invalid_bindings):
            with self.subTest(remote_binding=invalid):
                config.write_text(
                    original_config.replace(valid, invalid), encoding="ascii"
                )
                config.chmod(0o600)
                run_id = f"{index + 10:064x}"
                self.assertNotEqual(0, run("capture-prestate").returncode)
        config.write_text(original_config, encoding="ascii")
        config.chmod(0o600)

    def test_shared_nginx_renderer_requires_origin_roots_with_one_slash(self) -> None:
        site = self.root / "shared-8443.conf"
        shared_server = (
            b"server {\n"
            b"    listen 8443 ssl http2 default_server;\n"
            b"    listen [::]:8443 ssl http2 default_server;\n"
            b"    server_name synthetic.example.invalid;\n"
            b"    ssl_certificate /synthetic/tls.crt;\n"
            b"    ssl_certificate_key /synthetic/tls.key;\n"
            b"    add_header X-Synthetic \"sibling-bytes\" always;\n"
            b"    location /personal/ {\n"
            b"        proxy_pass http://127.0.0.1:8766/;\n"
            b"    }\n"
            b"    location /solidstats/ {\n"
            b"        proxy_pass http://127.0.0.1:8767/;\n"
            b"    }\n"
            b"}\n"
        )
        site.write_bytes(
            b"server {\n"
            b"    listen 8080;\n"
            b"    location /health/ { return 204; }\n"
            b"}\n"
            + shared_server
        )
        renderer = ROOT / "scripts/render-solidstats-memory-shared-nginx.py"

        def render(
            old: str, new: str, index: int
        ) -> subprocess.CompletedProcess[str]:
            descriptor = self.root / f"descriptor-{index}"
            output = self.root / f"rendered-{index}.conf"
            descriptor.write_text(
                "\n".join(
                    (
                        "schema=solidstats-memory-nginx-patch/v1",
                        "public_port=8443",
                        "public_location=/solidstats/",
                        f"old_upstream={old}",
                        f"new_upstream={new}",
                    )
                )
                + "\n",
                encoding="ascii",
            )
            descriptor.chmod(0o600)
            return subprocess.run(
                [
                    sys.executable,
                    str(renderer),
                    str(site),
                    str(descriptor),
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        accepted = render(
            "http://127.0.0.1:8767/", "http://192.168.50.20:8765/", 0
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        rendered = (self.root / "rendered-0.conf").read_bytes()
        self.assertEqual(
            site.read_bytes().replace(
                b"proxy_pass http://127.0.0.1:8767/;",
                b"proxy_pass http://192.168.50.20:8765/;",
                1,
            ),
            rendered,
        )
        self.assertEqual(
            "/mcp", "/" + "/solidstats/mcp".removeprefix("/solidstats/")
        )

        invalid_pairs = (
            ("http://127.0.0.1:8767", "http://192.168.50.20:8765/"),
            ("http://127.0.0.1:8767//", "http://192.168.50.20:8765/"),
            ("http://127.0.0.1:8767/mcp/", "http://192.168.50.20:8765/"),
            ("http://127.0.0.1:8767/", "http://192.168.50.20:8765"),
            ("http://127.0.0.1:8767/", "http://192.168.50.20:8765/?query=1"),
            ("http://127.0.0.1:8767/", "http://192.168.50.20:8765/#fragment"),
        )
        for index, pair in enumerate(invalid_pairs, start=1):
            with self.subTest(upstreams=pair):
                self.assertNotEqual(0, render(*pair, index).returncode)

        valid_site = site.read_bytes()
        invalid_sites = {
            "wrong-port": valid_site.replace(b"8443", b"9443"),
            "missing-ipv6": valid_site.replace(
                b"    listen [::]:8443 ssl http2 default_server;\n", b""
            ),
            "missing-ssl": valid_site.replace(
                b"listen 8443 ssl http2 default_server;",
                b"listen 8443 http2 default_server;",
            ),
            "missing-default-server": valid_site.replace(
                b"listen [::]:8443 ssl http2 default_server;",
                b"listen [::]:8443 ssl http2;",
            ),
            "duplicate-server": valid_site + shared_server,
            "duplicate-location": valid_site.replace(
                b"    location /solidstats/ {\n"
                b"        proxy_pass http://127.0.0.1:8767/;\n"
                b"    }\n",
                b"    location /solidstats/ {\n"
                b"        proxy_pass http://127.0.0.1:8767/;\n"
                b"    }\n"
                b"    location /solidstats/ {\n"
                b"        return 409;\n"
                b"    }\n",
            ),
            "split-locations": (
                b"server {\n"
                b"    listen 8443 ssl http2 default_server;\n"
                b"    listen [::]:8443 ssl http2 default_server;\n"
                b"    location /personal/ {\n"
                b"        proxy_pass http://127.0.0.1:8766/;\n"
                b"    }\n"
                b"}\n"
                b"server {\n"
                b"    listen 9443 ssl http2 default_server;\n"
                b"    listen [::]:9443 ssl http2 default_server;\n"
                b"    location /solidstats/ {\n"
                b"        proxy_pass http://127.0.0.1:8767/;\n"
                b"    }\n"
                b"}\n"
            ),
        }
        for index, (case, invalid_site) in enumerate(invalid_sites.items(), start=20):
            with self.subTest(shared_server_boundary=case):
                site.write_bytes(invalid_site)
                self.assertNotEqual(
                    0,
                    render(
                        "http://127.0.0.1:8767/",
                        "http://192.168.50.20:8765/",
                        index,
                    ).returncode,
                )

    def test_remote_operator_rejects_unsafe_sibling_config(self) -> None:
        remote = self.root / "unsafe-remote"
        remote.mkdir(mode=0o700)
        operator = remote / "operate-solidstats-memory-cutover-remote.sh"
        renderer = remote / "render-solidstats-memory-shared-nginx.py"
        shutil.copy2(ROOT / "scripts" / operator.name, operator)
        shutil.copy2(ROOT / "scripts" / renderer.name, renderer)
        operator.chmod(0o700)
        renderer.chmod(0o700)
        config = Path(f"{operator}.config")
        config.write_text("schema=wrong\n", encoding="ascii")
        config.chmod(0o640)
        command = ["bash", str(operator), "capture-prestate", "d" * 64]
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        self.assertNotEqual(0, result.returncode)

        template = (
            ROOT / "config/solidstats-memory/remote-cutover-operator.config.template"
        ).read_text(encoding="ascii")
        keys = {line.split("=", 1)[0] for line in template.splitlines()}
        self.assertEqual(
            {
                "schema",
                "state_root",
                "runuser_path",
                "docker_path",
                "kubectl_path",
                "curl_path",
                "nginx_path",
                "systemctl_path",
                "python_path",
                "nginx_unit",
                "kube_context",
                "new_namespace",
                "new_deployment",
                "new_expected_replicas",
                "nginx_root",
                "nginx_available_path",
                "nginx_enabled_path",
                "command_timeout_seconds",
                "backup_timeout_seconds",
                "legacy_user",
                "legacy_socket",
                "legacy_container",
                "freeze_lock_container",
                "old_upstream",
                "new_upstream",
                "new_health_url",
            },
            keys,
        )
        config.chmod(0o600)
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        self.assertNotEqual(0, result.returncode)
        safe = remote / "safe-config"
        safe.write_text("schema=wrong\n", encoding="ascii")
        safe.chmod(0o600)
        config.unlink()
        config.symlink_to(safe)
        result = subprocess.run(command, capture_output=True, timeout=10, check=False)
        self.assertNotEqual(0, result.returncode)

    def test_cutover_ssh_binding_has_no_ambient_fallback(self) -> None:
        content = CUTOVER_PATH.read_text(encoding="utf-8")
        for exact in (
            "-F /dev/null",
            '-i "${SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE}"',
            "-o IdentitiesOnly=yes",
            "-o StrictHostKeyChecking=yes",
            'UserKnownHostsFile=${SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE}',
        ):
            self.assertIn(exact, content)

        identity = self.root / "identity"
        known_hosts = self.root / "known-hosts"
        identity.write_text("fixture\n", encoding="ascii")
        known_hosts.write_text("fixture\n", encoding="ascii")
        identity.chmod(0o640)
        known_hosts.chmod(0o600)
        private = self.root / "cutover-private"
        private.mkdir(mode=0o700)
        environment = {
            **os.environ,
            "SOLIDSTATS_MEMORY_RUN_ID": "phase21-ssh-fixture",
            "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": str(private),
            "SOLIDSTATS_MEMORY_SSH_TARGET": "root@example.invalid",
            "SOLIDSTATS_MEMORY_REMOTE_OPERATOR": "/private/operator",
            "SOLIDSTATS_MEMORY_SSH_IDENTITY_FILE": str(identity),
            "SOLIDSTATS_MEMORY_SSH_KNOWN_HOSTS_FILE": str(known_hosts),
        }
        result = subprocess.run(
            ["bash", str(CUTOVER_PATH), "preflight"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("SSH identity mode is unsafe", result.stderr)
        identity.chmod(0o600)
        identity_real = self.root / "identity-real"
        identity.rename(identity_real)
        identity.symlink_to(identity_real)
        result = subprocess.run(
            ["bash", str(CUTOVER_PATH), "preflight", "--resume-run"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("SSH binding is unavailable or unsafe", result.stderr)

    def recovery_evidence(self) -> dict[str, object]:
        digest = "a" * 64
        return {
            "schema": "solidstats-memory-recovery-evidence/v1",
            "run_id": "phase21-recovery-fixture",
            "cutover_evidence_sha256": digest,
            "restart_checks": {
                "mempalace_identity_changed": True,
                "mempalace_behavior_passed": True,
                "qdrant_identity_changed": True,
                "qdrant_behavior_passed": True,
                "ordered": True,
            },
            "backup_api_control_checks": {
                "measured": True,
                "binding_current": True,
                "single_candidate": True,
                "positive_get": True,
                "network_negative": True,
                "rbac_negative": True,
                "policy_sha256": digest,
            },
            "steady_state_backup_consistency": {
                "writer_prestate_recorded": True,
                "zero_writers": True,
                "zero_pvc_consumers": True,
                "source_before_sha256": digest,
                "source_after_sha256": digest,
                "archive_sha256": digest,
            },
            "fresh_backup_checks": {
                "exact_template": True,
                "upload_inventory_exact": True,
                "downloaded": True,
                "checksums_rechecked": True,
            },
            "writer_resumption_checks": {
                "replicas_restored": True,
                "available": True,
                "capture_passed": True,
                "read_after_write_passed": True,
                "schedules_suspended_on_failure": True,
            },
            "reboot_checks": {
                "boot_identity_changed": True,
                "reconnected_within_deadline": True,
                "node_ready": True,
                "pvc_bound": True,
                "qdrant_ready": True,
                "mempalace_available": True,
                "nginx_active": True,
                "freeze_lock_restored": True,
                "behavior_passed": True,
            },
            "rollback_checks": {
                "reverse_order": True,
                "legacy_behavior_passed": True,
                "retained_data_preserved": True,
            },
            "forward_checks": {
                "exact_replay": True,
                "behavior_passed": True,
                "retained_data_preserved": True,
            },
            "client_checks": {
                "legacy_retained_until_recovery": True,
                "unrelated_unchanged": True,
                "new_client_live": True,
            },
            "verdict": "pass",
        }

    def test_recovery_evidence_requires_behavior_not_readiness(self) -> None:
        evidence = self.recovery_evidence()
        VALIDATOR.validate_recovery_evidence(evidence)
        for section, key in (
            ("restart_checks", "mempalace_behavior_passed"),
            ("reboot_checks", "boot_identity_changed"),
            ("reboot_checks", "freeze_lock_restored"),
            ("reboot_checks", "behavior_passed"),
            ("rollback_checks", "legacy_behavior_passed"),
            ("forward_checks", "behavior_passed"),
            ("writer_resumption_checks", "capture_passed"),
        ):
            with self.subTest(section=section, key=key):
                invalid = deepcopy(evidence)
                invalid[section][key] = False
                with self.assertRaises(VALIDATOR.Phase21ValidationError):
                    VALIDATOR.validate_recovery_evidence(invalid)

    def test_recovery_evidence_rejects_api_and_metadata_false_positives(self) -> None:
        evidence = self.recovery_evidence()
        mutations = (
            ("backup_api_control_checks", "measured", False),
            ("backup_api_control_checks", "network_negative", False),
            ("backup_api_control_checks", "rbac_negative", False),
            ("steady_state_backup_consistency", "zero_writers", False),
            ("steady_state_backup_consistency", "source_after_sha256", "b" * 64),
            ("steady_state_backup_consistency", "archive_sha256", "c" * 64),
            ("writer_resumption_checks", "replicas_restored", False),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                invalid = deepcopy(evidence)
                invalid[section][key] = value
                with self.assertRaises(VALIDATOR.Phase21ValidationError):
                    VALIDATOR.validate_recovery_evidence(invalid)

    def test_cutover_seal_is_predecessor_bound_and_all_green(self) -> None:
        recovery = self.recovery_evidence()
        digest = hashlib.sha256(
            VALIDATOR.canonical_json_bytes(recovery)
        ).hexdigest()
        seal = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": recovery["run_id"],
            "recovery_evidence_sha256": digest,
            "requirements": {
                "iso_01": True,
                "iso_03": True,
                "ops_02": True,
                "ops_03": True,
                "ops_05": True,
            },
            "prohibitions": {
                "no_early_legacy_removal": True,
                "no_public_qdrant": True,
                "no_retained_data_deletion": True,
            },
            "legacy_client_absent": True,
            "new_client_live": True,
            "backup_schedule_live": True,
            "verdict": "pass",
        }
        VALIDATOR.validate_cutover_seal(seal, recovery_payload=recovery)
        for key in ("legacy_client_absent", "new_client_live", "backup_schedule_live"):
            invalid = deepcopy(seal)
            invalid[key] = False
            with self.subTest(key=key), self.assertRaises(
                VALIDATOR.Phase21ValidationError
            ):
                VALIDATOR.validate_cutover_seal(
                    invalid, recovery_payload=recovery
                )

    def test_recovery_cli_surface_is_fail_closed_and_self_tested(self) -> None:
        source = CUTOVER_PATH.read_text(encoding="utf-8")
        for function in (
            "restart_recovery()",
            "reboot_recovery()",
            "measure_backup_api_egress()",
            "prove_backup_api_access()",
            "prove_backup_consistency()",
            "activate_backup_schedule()",
            "exercise_live_rollback()",
            "seal_cutover()",
        ):
            self.assertIn(function, source)
        for command in (
            "restart-recovery",
            "reboot-recovery",
            "prove-backup-api-access",
            "prove-backup-consistency",
            "exercise-rollback",
            "activate-backup-schedule",
            "seal",
            "--reconnect-timeout",
        ):
            self.assertIn(command, source)
        self.assertIn('stat -c \'%a:%u\' "${derived}"', source)
        self.assertIn('rm -f -- "${derived}"', source)
        self.assertIn('install -m 755 "${SCRIPT_DIR}/guard-solidstats-memory-backup.sh"', source)
        self.assertIn('install -m 644 "${SCRIPT_DIR}/solidstats-memory-backup-guard.service"', source)
        self.assertIn('install -m 600 "${BACKUP_RENDERED_CANDIDATE}"', source)
        self.assertNotIn('"$(<"${gate}")" == pass', source)
        result = subprocess.run(
            ["bash", str(CUTOVER_PATH), "--self-test"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("RECOVERY_SELF_TEST PASSED", result.stdout)

    def test_remote_operator_allowlists_every_controller_operation(self) -> None:
        controller = CUTOVER_PATH.read_text(encoding="utf-8")
        operator = REMOTE_CUTOVER_PATH.read_text(encoding="utf-8")
        self.assertIn('command: ["python3", "-c"]', operator)
        self.assertIn("urllib.request.urlopen(request,timeout=8", operator)
        self.assertIn('key=lambda row: (row[0] != "service", row)', operator)
        self.assertNotIn("curl --config", operator)
        self.assertIn("attempt <= 3", operator)
        self.assertIn("poll <= 30", operator)
        self.assertIn("Succeeded) status=0; break", operator)
        self.assertIn("Failed) status=1; break", operator)
        self.assertIn("decoder.raw_decode(raw,index)", operator)
        self.assertIn('value.get("kind")=="CronJob"', operator)
        self.assertIn("install -d -o 0 -g 0 -m 0755 /usr/local/libexec", operator)
        self.assertIn("rmdir /usr/local/libexec || fatal", operator)
        self.assertIn("state-root.state", operator)
        self.assertIn("record_operation install-backup-guard pending", operator)
        self.assertIn("validate_guard_prestate", operator)
        self.assertIn("'    runAsNonRoot: true'", operator)
        self.assertIn("'    fsGroup: 1000'", operator)
        self.assertIn("'    fsGroupChangePolicy: OnRootMismatch'", operator)
        self.assertIn("'      type: RuntimeDefault'", operator)
        self.assertIn(
            "'        - ipBlock:'\n    printf '            cidr:",
            operator,
        )
        self.assertNotIn("'        - ipBlock:' \\\n    printf", operator)
        emitted = set(
            re.findall(r"run_remote_batch\s+([a-z0-9-]+)", controller)
        )
        self.assertEqual(
            {
                "activate-backup-schedule",
                "capture-boot-identity",
                "capture-prestate",
                "capture-backup-template-digest",
                "install-backup-guard",
                "install-nginx",
                "measure-backup-api-egress",
                "prove-backup-api-network-negative",
                "prove-backup-api-positive",
                "prove-backup-api-rbac-negative",
                "prove-backup-consistency",
                "prepare-guard-package",
                "record-backup-writer-prestate",
                "reboot-host",
                "recheck-backup-api-access",
                "rearm-forward-cycle",
                "restart-mempalace",
                "restart-qdrant",
                "restore-backup-writer",
                "rollback-nginx",
                "start-legacy",
                "stop-legacy-start-new",
                "stop-new",
                "suspend-backup-schedule",
                "verify-legacy-behavior",
                "verify-reboot-recovery",
                "verify-retained-collections",
                "verify-backup-guard",
                "verify-guard-package",
                "test-backup-guard-suspension",
            },
            emitted,
        )
        for operation in emitted:
            with self.subTest(operation=operation):
                self.assertIsNotNone(
                    re.search(
                        rf"(?:^|[|\s]){re.escape(operation)}(?:[|)])",
                        operator,
                        re.MULTILINE,
                    ),
                )

    def test_remote_operator_reboot_payload_schema_is_exact(self) -> None:
        operator_source = REMOTE_CUTOVER_PATH.read_text(encoding="utf-8")
        self.assertNotIn('-H "Authorization: Bearer $(cat', operator_source)

        valid = subprocess.run(
            [
                "bash",
                str(REMOTE_CUTOVER_PATH),
                "verify-reboot-recovery",
                "a" * 64,
                "900",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(64, valid.returncode)
        self.assertEqual([], valid.stdout.splitlines())
        self.assertNotRegex(valid.stderr, r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|Bearer")

        for timeout_value in ("0", "0900", "900s", "10000"):
            with self.subTest(timeout=timeout_value):
                denied = subprocess.run(
                    [
                        "bash",
                        str(REMOTE_CUTOVER_PATH),
                        "verify-reboot-recovery",
                        "a" * 64,
                        timeout_value,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(64, denied.returncode)
                self.assertEqual([], denied.stdout.splitlines())

    def test_plan04_static_safety_contract_is_complete(self) -> None:
        cutover = CUTOVER_PATH.read_text(encoding="utf-8")
        remote = REMOTE_CUTOVER_PATH.read_text(encoding="utf-8")
        backup = (ROOT / "k8s/memory/40-backup.yaml").read_text(encoding="utf-8")
        renderer = (ROOT / "scripts/render-memory-manifests.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "recover_backup_failure",
            "collect_recovery_evidence",
            "prepare_backup_activation",
            "commit_backup_activation",
            "rearm-forward-cycle",
            "install-backup-guard",
            "verify-backup-guard",
        ):
            self.assertIn(required, cutover + remote)
        self.assertIn("backup_timeout_seconds", remote)
        self.assertIn("set_freeze_lock_state", remote)
        self.assertIn('"freeze_lock_restored=true"', remote)
        self.assertIn("expected_error=-32001", remote)
        self.assertIn("Peer MCP writer active; this server is read-only", remote)
        self.assertIn("codex mcp get solidstats_memory", cutover)
        activation = cutover[cutover.index("activate_backup_schedule()") : cutover.index("stage_guard_package()")]
        self.assertLess(
            activation.index("prepare_backup_activation"),
            activation.index("stage_guard_package"),
        )
        commit = cutover[cutover.index("commit_backup_activation()") : cutover.index("restore_suspended_backup_source()")]
        self.assertIn('cmp -s -- "${source}" "${BACKUP_SOURCE_CANDIDATE}"', commit)
        self.assertIn('--allow-operator-placeholders', commit)
        self.assertNotIn('--manifest-dir "${SOLIDSTATS_MEMORY_RENDERED_MANIFEST_DIR}"', commit)
        activation_body = cutover[
            cutover.index("record_public_boundary_evidence") :
            cutover.index("collect_cutover_seal")
        ]
        self.assertLess(
            activation_body.index("retire_legacy_client"),
            activation_body.index("ACTIVATION_CLIENT_CHANGED=1"),
        )
        self.assertIn("restore_retired_client", cutover)
        self.assertIn(
            'BACKUP_REMOTE_TIMEOUT_SECONDS="${SOLIDSTATS_MEMORY_BACKUP_REMOTE_TIMEOUT_SECONDS:-3600}"',
            cutover,
        )
        self.assertRegex(
            cutover,
            r"prove-backup-consistency\)\n\s+max_attempts=1\n"
            r'\s+call_timeout="\$\{BACKUP_REMOTE_TIMEOUT_SECONDS\}s"',
        )
        self.assertIn("inventory_before_sha256", remote)
        self.assertIn("inventory_after_sha256", remote)
        self.assertIn("behavior-oracle=pass", backup)
        self.assertIn("writer-restored=pass", backup)
        self.assertIn("OPERATOR_ONLY", renderer)
        self.assertTrue(BACKUP_GUARD_PATH.is_file())
        self.assertTrue(EVIDENCE_COLLECTOR_PATH.is_file())

    def test_standalone_cutover_seal_is_rejected(self) -> None:
        recovery = self.recovery_evidence()
        seal = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": recovery["run_id"],
            "recovery_evidence_sha256": hashlib.sha256(
                VALIDATOR.canonical_json_bytes(recovery)
            ).hexdigest(),
            "requirements": {
                key: True for key in VALIDATOR.CUTOVER_SEAL_REQUIREMENTS
            },
            "prohibitions": {
                key: True for key in VALIDATOR.CUTOVER_SEAL_PROHIBITIONS
            },
            "legacy_client_absent": True,
            "new_client_live": True,
            "backup_schedule_live": True,
            "verdict": "pass",
        }
        path = self.root / "seal.json"
        path.write_bytes(VALIDATOR.canonical_json_bytes(seal) + b"\n")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(1, VALIDATOR.main(["--evidence", str(path)]))
        self.assertIn("recovery", stderr.getvalue())

    def test_evidence_collector_rejects_result_and_probe_near_misses(self) -> None:
        run_sha = "a" * 64
        valid = "\n".join(
            (
                "schema=solidstats-memory-remote-operation-result/v1",
                "operation=restart-mempalace",
                "sequence=100",
                "config_sha256=" + "b" * 64,
                "run_id_sha256=" + run_sha,
                "identity_changed=true",
                "before_sha256=" + "c" * 64,
                "after_sha256=" + "d" * 64,
            )
        ) + "\n"
        path = self.root / "remote.result"
        path.write_text(valid, encoding="ascii")
        path.chmod(0o600)
        self.assertEqual(
            "restart-mempalace",
            COLLECTOR.parse_remote_result(path, "restart-mempalace", run_sha)[
                "operation"
            ],
        )
        for near_miss in (
            "",
            valid + "operation=restart-mempalace\n",
            valid.replace("operation=restart-mempalace", "operation=restart-qdrant"),
            valid.replace("run_id_sha256=" + run_sha, "run_id_sha256=" + "e" * 64),
            valid.replace("identity_changed=true", "identity_changed=1"),
        ):
            path.write_text(near_miss, encoding="ascii")
            with self.assertRaises(ValueError):
                COLLECTOR.parse_remote_result(path, "restart-mempalace", run_sha)
        probe = self.root / "probe.json"
        probe.write_text("{}\n", encoding="ascii")
        probe.chmod(0o600)
        with self.assertRaises(ValueError):
            COLLECTOR.parse_probe(probe, run_sha)

        transition = self.root / "transition.result"
        transition.write_text(
            "schema=solidstats-memory-rollback-forward-evidence/v1\n"
            "rollback_client_sequence=1\nrollback_nginx_sequence=2\n"
            "rollback_alias_sequence=3\nrollback_workload_sequence=4\n"
            "rollback_legacy_sequence=5\nforward_rearm_sequence=6\n"
            "forward_cutover_sequence=7\nretained_verification_sequence=8\n"
            "reverse_order=true\nforward_exact=true\n",
            encoding="ascii",
        )
        transition.chmod(0o600)
        self.assertTrue(COLLECTOR.parse_transition_result(transition)["reverse_order"])
        transition.write_text(transition.read_text().replace("sequence=4", "sequence=3"))
        with self.assertRaises(ValueError):
            COLLECTOR.parse_transition_result(transition)

    def test_seal_requires_one_remote_config_revision(self) -> None:
        same = {"config_sha256": "a" * 64}
        self.assertEqual(
            "a" * 64,
            COLLECTOR.require_one_config_revision(same, dict(same)),
        )
        with self.assertRaisesRegex(ValueError, "config binding"):
            COLLECTOR.require_one_config_revision(
                same, {"config_sha256": "b" * 64}
            )

    def test_remote_batch_requires_one_bound_result_and_one_pass(self) -> None:
        source = CUTOVER_PATH.read_text(encoding="utf-8")
        body = source[source.index("run_remote_batch()") : source.index("run_alias()")]
        self.assertIn('${result_count}" -eq 1', body)
        self.assertIn("grep -c '^PASS: remote cutover boundary acknowledged$'", body)
        self.assertIn("grep -c '^sequence='", body)
        self.assertNotIn('${result_count}" -eq 0', body)

    def test_seal_mapping_uses_each_dedicated_source_without_proxy_claims(self) -> None:
        source = COLLECTOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"writer_prestate_recorded": True', source)
        self.assertNotIn('"legacy_retained_until_recovery": bool(probes', source)
        for required in (
            'remote-record-backup-writer-prestate.result',
            'client-pre-retirement.result',
            'client-retired.result',
            'public-boundary.result',
            'remote-verify-retained-collections.result',
            'backup-activation.provenance.json',
            '"requirements": {"iso_01": iso_01, "iso_03": iso_03, "ops_02": ops_02, "ops_03": ops_03, "ops_05": ops_05}',
            '"prohibitions": {"no_early_legacy_removal": no_early, "no_public_qdrant": public_qdrant_private, "no_retained_data_deletion": no_retained}',
        ):
            self.assertIn(required, source)

        dedicated = self.root / "dedicated.result"
        dedicated.write_text(
            "schema=solidstats-memory-public-boundary-evidence/v1\n"
            f"sequence=620\naddress_set_sha256={'c' * 64}\naddress_count=2\n"
            f"port_6333_all_addresses_blocked=true\nport_6333_result_sha256={'d' * 64}\n"
            f"port_6334_all_addresses_blocked=true\nport_6334_result_sha256={'e' * 64}\n"
            "authenticated_mcp_boundary=true\n"
            f"authenticated_mcp_probe_sha256={'a' * 64}\napi_policy_sha256={'b' * 64}\n",
            encoding="ascii",
        )
        dedicated.chmod(0o600)
        fields = {"sequence", "address_set_sha256", "address_count", "port_6333_all_addresses_blocked", "port_6333_result_sha256", "port_6334_all_addresses_blocked", "port_6334_result_sha256", "authenticated_mcp_boundary", "authenticated_mcp_probe_sha256", "api_policy_sha256"}
        self.assertEqual("620", COLLECTOR.parse_exact_result(dedicated, "solidstats-memory-public-boundary-evidence/v1", fields)["sequence"])
        dedicated.unlink()
        with self.assertRaises(FileNotFoundError):
            COLLECTOR.parse_exact_result(dedicated, "solidstats-memory-public-boundary-evidence/v1", fields)

        for schema, source_fields in (
            ("solidstats-memory-client-pre-retirement/v1", {"sequence", "legacy_client_present"}),
            ("solidstats-memory-client-retirement/v3", {"sequence", "legacy_client_absent"}),
            ("solidstats-memory-public-boundary-evidence/v1", {"sequence", "address_set_sha256"}),
        ):
            dedicated.write_text(
                f"schema={schema}\n" + "\n".join(f"{key}=true" for key in source_fields) + "\n",
                encoding="ascii",
            )
            dedicated.chmod(0o600)
            values = COLLECTOR.parse_exact_result(dedicated, schema, source_fields)
            self.assertEqual({"schema", *source_fields}, set(values))
            dedicated.write_text(dedicated.read_text().replace(f"schema={schema}", "schema=wrong/v1"))
            with self.assertRaises(ValueError):
                COLLECTOR.parse_exact_result(dedicated, schema, source_fields)
            dedicated.unlink()
            with self.assertRaises(FileNotFoundError):
                COLLECTOR.parse_exact_result(dedicated, schema, source_fields)

        public = self.root / "public-evidence.json"
        public.write_text("{}\n", encoding="ascii")
        for mode in (0o644, 0o664):
            public.chmod(mode)
            self.assertEqual(b"{}\n", COLLECTOR.safe(public, 0o644))
        public.chmod(0o600)
        with self.assertRaises(ValueError):
            COLLECTOR.safe(public, 0o644)

    def test_backup_activation_renderer_binds_source_render_and_template(self) -> None:
        source = self.root / "source.yaml"
        rendered = self.root / "rendered.yaml"
        manifest = b"""apiVersion: batch/v1
kind: CronJob
metadata:
  name: solidstats-memory-backup
spec:
  suspend: true
  jobTemplate:
    spec:
      template:
        spec:
          initContainers:
            - name: prepare
              image: MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST
            - name: upload
              image: MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST
            - name: download
              image: MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST
          containers:
            - name: verify
              image: MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST
              env:
                - name: QDRANT_COLLECTION
                  value: MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME
          restartPolicy: Never
"""
        mempalace_image = "ghcr.io/mempalace/mempalace@sha256:" + "1" * 64
        uploader_image = "public.ecr.aws/aws-cli/aws-cli@sha256:" + "2" * 64
        collection = "solidstats_memory_test"
        rendered_manifest = (
            manifest.replace(
                b"MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST",
                mempalace_image.encode(),
            )
            .replace(
                b"MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST",
                uploader_image.encode(),
            )
            .replace(
                b"MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME",
                collection.encode(),
            )
        )
        source.write_bytes(manifest)
        rendered.write_bytes(rendered_manifest)
        config = self.root / "operator-config.json"
        config.write_text(
            json.dumps(
                {
                    "mempalace_image": mempalace_image,
                    "uploader_image": uploader_image,
                    "private_collection": collection,
                }
            ),
            encoding="ascii",
        )
        config.chmod(0o600)

        def invoke(suffix: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(ACTIVATION_RENDERER_PATH), str(source), str(rendered),
                 str(self.root / f"active-source-{suffix}.yaml"),
                 str(self.root / f"active-rendered-{suffix}.yaml"),
                 str(self.root / f"descriptor-{suffix}.json"),
                 "--operator-config", str(config)],
                capture_output=True, text=True, timeout=10, check=False,
            )

        accepted = invoke("accepted")
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        descriptor = json.loads((self.root / "descriptor-accepted.json").read_text())
        self.assertTrue(descriptor["source_render_exact"])
        self.assertNotEqual(descriptor["source_suspended_sha256"], descriptor["rendered_suspended_sha256"])
        self.assertNotEqual(
            (self.root / "active-source-accepted.yaml").read_bytes(),
            (self.root / "active-rendered-accepted.yaml").read_bytes(),
        )
        self.assertIn(mempalace_image.encode(), (self.root / "active-rendered-accepted.yaml").read_bytes())
        self.assertIn(b"MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST", (self.root / "active-source-accepted.yaml").read_bytes())
        template = {
            "spec": {
                "template": {
                    "spec": {
                        "serviceAccountName": "backup",
                        "containers": [
                            {
                                "env": [
                                    {
                                        "valueFrom": {
                                            "fieldRef": {"fieldPath": "metadata.name"}
                                        }
                                    }
                                ]
                            }
                        ],
                        "initContainers": [{"startupProbe": {"exec": {"command": ["true"]}}}],
                    }
                }
            }
        }
        defaulted = deepcopy(template)
        defaulted_pod = defaulted["spec"]["template"]["spec"]
        defaulted_pod.update(
            {
                "dnsPolicy": "ClusterFirst",
                "schedulerName": "default-scheduler",
                "serviceAccount": "backup",
            }
        )
        defaulted_pod["containers"][0].update(
            {
                "terminationMessagePath": "/dev/termination-log",
                "terminationMessagePolicy": "File",
            }
        )
        defaulted_pod["containers"][0]["env"][0]["valueFrom"]["fieldRef"]["apiVersion"] = "v1"
        defaulted_pod["initContainers"][0]["startupProbe"]["successThreshold"] = 1
        self.assertEqual(
            ACTIVATION.canonicalize_template(template),
            ACTIVATION.canonicalize_template(defaulted),
        )
        rendered.write_bytes(rendered_manifest + b"# render drift\n")
        self.assertNotEqual(0, invoke("render-drift").returncode)
        rendered.write_bytes(rendered_manifest)
        source.write_bytes(manifest + b"# source drift\n")
        self.assertNotEqual(0, invoke("source-drift").returncode)

    def test_backup_guard_fallback_uses_only_fixed_trust_helper(self) -> None:
        guard = BACKUP_GUARD_PATH.read_text(encoding="utf-8")
        helper = BACKUP_SUSPEND_PATH.read_text(encoding="utf-8")
        fallback = guard[guard.index("fallback_suspend()") : guard.index("trap fallback_suspend ERR")]
        self.assertNotIn("kubectl", fallback)
        self.assertIn("solidstats-memory-backup-suspend", fallback)
        self.assertIn("trusted_chain", helper)
        self.assertIn('^/usr(/local)?/bin/kubectl$', helper)
        self.assertIn("/etc/rancher/k3s/k3s.yaml", helper)
        self.assertIn("/proc/self/fd/${kubectl_fd}", helper)
        self.assertNotIn("SOLIDSTATS_MEMORY_GUARD_SELF_TEST", helper)

    def test_artifact_chain_uses_exact_recovery_file_digest(self) -> None:
        source = ROOT / ".planning/phases/21-restore-cutover-recovery"
        chain = self.root / "chain"
        chain.mkdir()
        for artifact in source.glob("*.json"):
            shutil.copy2(artifact, chain / artifact.name)
        cutover_path = chain / "21-CUTOVER-EVIDENCE.json"
        recovery = self.recovery_evidence()
        recovery["run_id"] = json.loads(cutover_path.read_text())["run_id"]
        recovery["cutover_evidence_sha256"] = hashlib.sha256(
            cutover_path.read_bytes()
        ).hexdigest()
        recovery_path = chain / "21-RECOVERY-EVIDENCE.json"
        recovery_path.write_bytes(VALIDATOR.canonical_json_bytes(recovery) + b"\n")
        seal = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": recovery["run_id"],
            "recovery_evidence_sha256": hashlib.sha256(
                recovery_path.read_bytes()
            ).hexdigest(),
            "requirements": {
                key: True for key in VALIDATOR.CUTOVER_SEAL_REQUIREMENTS
            },
            "prohibitions": {
                key: True for key in VALIDATOR.CUTOVER_SEAL_PROHIBITIONS
            },
            "legacy_client_absent": True,
            "new_client_live": True,
            "backup_schedule_live": True,
            "verdict": "pass",
        }
        (chain / "21-CUTOVER-SEAL.json").write_bytes(
            VALIDATOR.canonical_json_bytes(seal) + b"\n"
        )
        self.assertEqual("SEALED", VALIDATOR.validate_phase_artifact_chain(chain)["stage"])


if __name__ == "__main__":
    unittest.main()
