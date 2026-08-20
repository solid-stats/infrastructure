#!/usr/bin/env python3
"""Contract tests for the value-free Phase 21 transition chain."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


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
            "quiescence": {"stable": True, "tree_sha256": digest},
            "capacity": {
                "sufficient": True,
                "required_bytes": 30,
                "pvc_free_bytes": 40,
                "node_free_bytes": 50,
            },
            "package_checks": {
                "complete": True,
                "package_sha256": digest,
            },
            "object_checks": {"verified": True, "object_count": 4},
            "target_absence": {"confirmed": True},
            "restore_checks": {
                "green": True,
                "configuration_match": True,
                "count_match": True,
            },
            "parity_checks": {"exact": True, "record_count": 3},
            "alias_compatibility": {
                "probe_passed": True,
                "prestate_sha256": digest,
                "poststate_sha256": digest,
                "restored": True,
            },
            "rollback_state": {"active_state_unchanged": True},
            "verdict": "pass",
        }

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
            pvc_free_bytes=30,
            node_free_bytes=31,
            reserve_bytes=5,
        )
        self.assertEqual(25, capacity["required_bytes"])
        with self.assertRaisesRegex(RESTORE.RestoreControlError, "priority"):
            RESTORE.recover_snapshot(
                request,
                target_collection="isolated",
                snapshot_location="file:///snapshot",
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
            if path.endswith("/snapshots") and method == "POST":
                return {"status": "ok", "result": {"name": "fixture.snapshot"}}
            if path.endswith("/fixture.snapshot") and method == "GET":
                return b"snapshot-bytes"
            if path.endswith("/snapshots/recover?wait=true"):
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
            request,
            target_collection="isolated",
            snapshot_location="file:///snapshot",
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
            private_environment={"QDRANT_COLLECTION": "private-collection"},
        )
        output = self.root / "private" / "job.json"
        RESTORE.write_private_json(output, job)

        self.assertEqual("Job", job["kind"])
        self.assertNotIn("schedule", job["spec"])
        self.assertEqual(0o600, output.stat().st_mode & 0o777)
        public = RESTORE.backup_job_evidence(job)
        self.assertNotIn("private-collection", json.dumps(public))
        self.assertTrue(public["generated"])

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

    def test_backup_restore_evidence_schema_is_strict_and_value_free(self) -> None:
        bindings = {"binding_sha256": "1" * 64}
        evidence = self.backup_evidence(bindings)
        result = VALIDATOR.validate_backup_restore_evidence(evidence)
        self.assertEqual("pass", result["verdict"])

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


if __name__ == "__main__":
    unittest.main()
