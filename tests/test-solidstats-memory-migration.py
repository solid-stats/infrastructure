#!/usr/bin/env python3
"""Contract tests for synthetic SolidStats memory migration bundles."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-solidstats-memory-policy.py"
SPEC = importlib.util.spec_from_file_location("memory_policy_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
INVENTORY_PATH = ROOT / "scripts" / "inventory-solidstats-memory.py"
BUNDLE_PATH = ROOT / "scripts" / "build-solidstats-memory-bundle.py"
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


def load_inventory_module() -> object:
    spec = importlib.util.spec_from_file_location("memory_inventory", INVENTORY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_bundle_module() -> object:
    spec = importlib.util.spec_from_file_location("memory_bundle", BUNDLE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_approved_mapping_contract(
    path: Path,
    inventory_proof: Path,
    *,
    infrastructure_target: str = "infrastructure-archive",
) -> dict[str, object]:
    """Write a complete synthetic approval-bound contract without corpus data."""
    contract: dict[str, object] = {
        "contract_schema": "solidstats-memory-mapping-contract/v1",
        "status": "approved",
        "source_inventory_sha256": hashlib.sha256(inventory_proof.read_bytes()).hexdigest(),
        "approved_at": "2026-08-20T00:00:00Z",
        "timestamp_semantics": {
            "preserved_fields": ["content_date", "filed_at", "source_mtime"],
            "rule": "Preserve each observed source timestamp field exactly as found; apply no precedence, normalization, or synthesized source_timestamp or effective_source_date.",
            "missing_or_invalid": "A missing or invalid timestamp candidate neither rejects nor drops a record; it remains absent or invalid exactly as found in source metadata.",
            "target_updated_at": "separate",
        },
        "source_wing_to_target_wing": {
            "routing_authority": "synthetic",
            "canonical_repository_rules": {
                "infrastructure": infrastructure_target,
                "replay-parser-2": "replay-parser-2-archive",
                "replays-fetcher": "replays-fetcher-archive",
                "server-2": "server-2-archive",
                "web": "web-archive",
            },
            "shared_source_rule": {"SolidStats": "SolidStats-archive"},
            "excluded_source_rule": "exclude",
        },
        "legacy_room_label_treatment": {
            "rule": "Preserve every legacy room value unchanged for imported archive records.",
            "active_semantic_room_effect": "no-effect",
        },
        "legacy_archive_label_treatment": {
            "source_observation": "none",
            "unexpected_or_unbound": "Fail closed rather than remapping an unexpected or unbound label.",
            "target_label_rule": "route-only",
        },
        "excluded_source_disposition": {"rule": "Do not import agent or other-wing records into target Qdrant.", "retention": "retain"},
        "preservation_representation": {
            "approval_token": "approve-complete-contract",
            "standard_fields": "preserve",
            "operational_metadata": "Use a copy of source metadata with only operational wing changed for archive routing; retain original room and every other field unchanged.",
            "source_metadata_copy": {
                "reserved_key": "_solidstats_migration",
                "value_shape": {
                    "schema_version": 1,
                    "source_metadata": "exact original metadata dictionary",
                },
                "collision_rule": "Fail closed when source metadata already contains _solidstats_migration.",
            },
            "parity_rule": "exact nested source metadata",
            "independent_safety_copy": "retain",
            "duplication_acceptance": "accepted",
            "archive_immutability_and_recovery": {
                "agent_rule": "no archive mutation",
                "adjacent_contract": "deferred",
                "recovery_boundary": "separate",
                "accepted_residual_risk": "accepted",
            },
        },
    }
    canonical = json.dumps(contract, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    contract["approval_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    write_json(path, contract)
    return contract


class InventoryContractTests(unittest.TestCase):
    def write_snapshot(self, root: Path) -> tuple[Path, Path, Path]:
        snapshot = root / "snapshot"
        oracle = root / "oracle"
        output = root / "inventory"
        palace = snapshot / "palace"
        palace.mkdir(parents=True)
        (oracle / "mempalace" / "backends").mkdir(parents=True)
        (oracle / "mempalace-3.5.0.dist-info").mkdir()
        (oracle / "mempalace-3.5.0.dist-info" / "METADATA").write_text(
            "Name: mempalace\nVersion: 3.5.0\n", encoding="utf-8"
        )
        (oracle / "mempalace" / "backends" / "chroma.py").write_text(
            "class ChromaCollection:\n"
            "    def get(self, *, limit=None, offset=None, include=['embeddings']): pass\n",
            encoding="utf-8",
        )
        (oracle / "mempalace" / "backends" / "qdrant.py").write_text(
            "import uuid\n"
            "def _point_id(doc_id): return uuid.uuid5(uuid.NAMESPACE_URL, doc_id)\n"
            "class QdrantBackend:\n"
            "    def _remote_collection_name(self): pass\n",
            encoding="utf-8",
        )
        (palace / "chroma.sqlite3").write_bytes(b"synthetic raw Chroma state")
        write_json(snapshot / "palace-identity.json", {
            "namespace": "solidstats", "palace_id": "synthetic-palace",
        })
        write_json(snapshot / "mempalace-config.json", {
            "backend": "chroma", "collection_name": "synthetic-records",
            "embedding_model": "synthetic-v1",
        })
        write_json(palace / "mempalace_embedder.json", {
            "synthetic-records": {"dimension": 3, "model_name": "synthetic-v1"},
        })
        write_json(snapshot / "snapshot-manifest.json", {
            "chroma_dir": "palace", "config_sidecar": "mempalace-config.json",
            "embedder_sidecar": "palace/mempalace_embedder.json",
            "identity_sidecar": "palace-identity.json",
            "schema_version": 1,
        })
        (snapshot / "freeze-attestation.json").write_text(
            '{"write_freeze_at":"2026-08-20T00:00:00Z"}', encoding="utf-8"
        )
        oracle_python = root / "fake-v350-oracle"
        oracle_python.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys, uuid\n"
            "check_only = '--check-only' in sys.argv\n"
            "collection = {'name':'synthetic-records','namespace':'solidstats',"
            "'palace_id':'synthetic-palace','target_name':'mempalace_solidstats_"
            "0000000000000000_synthetic-records','embedder':{'model_name':'synthetic-v1',"
            "'dimension':3},'source_metric':'cosine'}\n"
            "print(json.dumps({'type':'header','record_count':2,'collection':collection}))\n"
            "if not check_only:\n"
            "  rows=[('source-1','synthetic alpha',{'archive_state':'active','room':'decisions',"
            "'source_timestamp':'2026-08-20T00:00:00Z','wing':'SolidStats'},[0.0,1.0,0.0]),"
            "('source-2','synthetic beta',{'archive_state':'historical','room':'conventions',"
            "'source_timestamp':'2026-08-20T00:00:01Z','wing':'infrastructure-archive'},[1.0,0.0,0.0])]\n"
            "  ns=uuid.UUID('c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1')\n"
            "  for index,(doc_id,document,metadata,embedding) in enumerate(rows,1):\n"
            "    print(json.dumps({'type':'record','index':index,'id':doc_id,'mempalace_id':doc_id,"
            "'point_id':str(uuid.uuid5(ns, doc_id)),'document':document,'metadata':metadata,'embedding':embedding}))\n"
            "print(json.dumps({'type':'done','record_count':2}))\n",
            encoding="utf-8",
        )
        oracle_python.chmod(oracle_python.stat().st_mode | stat.S_IXUSR)
        self.oracle_python = oracle_python
        return snapshot, oracle, output

    def write_side_effecting_oracle(self, *, ready_file: Path | None = None) -> None:
        ready_write = ""
        if ready_file is not None:
            ready_write = (
                f"Path({str(ready_file)!r}).write_text('ready', encoding='utf-8')\n"
                "time.sleep(0.5)\n"
            )
        self.oracle_python.write_text(
            "#!/usr/bin/env python3\n"
            "import json, stat, sys, time, uuid\n"
            "from pathlib import Path\n"
            "check_only = '--check-only' in sys.argv\n"
            "palace_path = Path(sys.argv[sys.argv.index('--palace-path') + 1])\n"
            "if stat.S_IMODE(palace_path.stat().st_mode) != 0o700:\n"
            "  raise SystemExit('oracle scratch directory mode')\n"
            "if stat.S_IMODE((palace_path / 'chroma.sqlite3').stat().st_mode) != 0o600:\n"
            "  raise SystemExit('oracle scratch file mode')\n"
            "(palace_path / 'oracle-marker').write_text('synthetic marker', encoding='utf-8')\n"
            + ready_write
            + "collection = {'name':'synthetic-records','namespace':'solidstats',"
            "'palace_id':'synthetic-palace','target_name':'mempalace_solidstats_"
            "0000000000000000_synthetic-records','embedder':{'model_name':'synthetic-v1',"
            "'dimension':3},'source_metric':'cosine'}\n"
            "print(json.dumps({'type':'header','record_count':1,'collection':collection}), flush=True)\n"
            "if not check_only:\n"
            "  doc_id = 'source-1'\n"
            "  print(json.dumps({'type':'record','index':1,'id':doc_id,'mempalace_id':doc_id,"
            "'point_id':str(uuid.uuid5(uuid.UUID('c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1'), doc_id)),"
            "'document':'synthetic alpha','metadata':{'archive_state':'active','room':'decisions',"
            "'source_timestamp':'2026-08-20T00:00:00Z','wing':'SolidStats'},"
            "'embedding':[0.0,1.0,0.0]}), flush=True)\n"
            "print(json.dumps({'type':'done','record_count':1}), flush=True)\n",
            encoding="utf-8",
        )
        self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)

    def test_inventory_preserves_synthetic_records_without_values_in_summary(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            snapshot, oracle, output = self.write_snapshot(Path(temporary))
            result = inventory.build_source_inventory(
                snapshot_dir=snapshot,
                freeze_attestation=snapshot / "freeze-attestation.json",
                oracle_source_dir=oracle,
                oracle_python=self.oracle_python,
                output_dir=output,
            )
            self.assertEqual(2, result["record_count"])
            records = (output / "source-records.jsonl").read_text(encoding="utf-8")
            vectors = (output / "source-vectors.jsonl").read_text(encoding="utf-8")
            summary = (output / "source-inventory.json").read_text(encoding="utf-8")
            self.assertIn('"id":"source-1"', records)
            self.assertIn('"vector":[0.0,1.0,0.0]', vectors)
            self.assertNotIn("synthetic alpha", summary)
            self.assertNotIn("synthetic-v1", summary)

    def test_inventory_preserves_real_shaped_source_metadata_losslessly(self) -> None:
        inventory = load_inventory_module()
        records = [
            (
                "source-legacy-repository",
                "synthetic legacy repository document",
                {
                    "content_date": "2026-08-19",
                    "filed_at": "2026-08-20T00:00:00Z",
                    "room": "legacy-intake",
                    "source_mtime": 1724112000.0,
                    "wing": "server-2",
                },
                [0.0, 1.0, 0.0],
            ),
            (
                "source-agent-wing",
                "synthetic agent document",
                {
                    "filed_at": "2026-08-20T00:00:01Z",
                    "room": "agent-notes",
                    "wing": "agent-scratch",
                },
                [1.0, 0.0, 0.0],
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            self.oracle_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json, uuid\n"
                "collection={'name':'synthetic-records','namespace':'solidstats','palace_id':'synthetic-palace','target_name':'x','embedder':{'model_name':'synthetic-v1','dimension':3},'source_metric':'cosine'}\n"
                "print(json.dumps({'type':'header','record_count':2,'collection':collection}))\n"
                f"rows={records!r}\n"
                "namespace=uuid.UUID('c06c3fc7-5c14-4dc4-84c2-24a5f72d8dc1')\n"
                "for index,(source_id,document,metadata,embedding) in enumerate(rows, 1):\n"
                " print(json.dumps({'type':'record','index':index,'id':source_id,'mempalace_id':source_id,'point_id':str(uuid.uuid5(namespace, source_id)),'document':document,'metadata':metadata,'embedding':embedding}))\n"
                "print(json.dumps({'type':'done','record_count':2}))\n",
                encoding="utf-8",
            )
            self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)
            result = inventory.build_source_inventory(
                snapshot_dir=snapshot,
                freeze_attestation=snapshot / "freeze-attestation.json",
                oracle_source_dir=oracle,
                oracle_python=self.oracle_python,
                output_dir=output,
            )
            emitted = [
                json.loads(line)
                for line in (output / "source-records.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(2, result["record_count"])
            self.assertEqual([record[2] for record in records], [record["metadata"] for record in emitted])
            self.assertEqual(
                [
                    inventory.canonical_json_bytes(record[2])
                    for record in records
                ],
                [inventory.canonical_json_bytes(record["metadata"]) for record in emitted],
            )
            self.assertEqual(
                [inventory.sha256_bytes(inventory.canonical_json_bytes(record[2])) for record in records],
                [record["metadata_sha256"] for record in emitted],
            )
            for expected, actual in zip(records, emitted, strict=True):
                self.assertEqual(set(expected[2]), set(actual["metadata"]))
                self.assertNotIn("source_timestamp", actual["metadata"])
                self.assertNotIn("archive_state", actual["metadata"])
                self.assertNotIn("routing", actual["metadata"])

    def test_inventory_emits_deterministic_value_free_source_shapes(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, first_output = self.write_snapshot(root)
            second_output = root / "second-inventory"
            first = inventory.build_source_inventory(
                snapshot_dir=snapshot,
                freeze_attestation=snapshot / "freeze-attestation.json",
                oracle_source_dir=oracle,
                oracle_python=self.oracle_python,
                output_dir=first_output,
            )
            second = inventory.build_source_inventory(
                snapshot_dir=snapshot,
                freeze_attestation=snapshot / "freeze-attestation.json",
                oracle_source_dir=oracle,
                oracle_python=self.oracle_python,
                output_dir=second_output,
            )
            self.assertEqual(first["source_shape_evidence"], second["source_shape_evidence"])
            self.assertEqual(first["output_checksums"], second["output_checksums"])
            evidence = first["source_shape_evidence"]
            self.assertEqual(2, evidence["fields"]["source_timestamp"]["present"])
            self.assertEqual(
                {"string": 2},
                evidence["fields"]["source_timestamp"]["types"],
            )
            self.assertEqual(
                {"utc_timestamp": 2},
                evidence["fields"]["source_timestamp"]["formats"],
            )
            self.assertEqual(
                {
                    "canonical_repository_unsuffixed": 0,
                    "invalid_type": 0,
                    "missing": 0,
                    "other_string": 1,
                    "suffix_marked": 1,
                },
                evidence["source_labels"]["wing"],
            )
            summary = (first_output / "source-inventory.json").read_text(encoding="utf-8")
            for value in ("SolidStats", "decisions", "synthetic alpha", "source-1"):
                self.assertNotIn(value, summary)

    def test_inventory_rejects_snapshot_digest_drift(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            original_digest = inventory._snapshot_digest(snapshot)
            with mock.patch.object(
                inventory,
                "_snapshot_digest",
                side_effect=[original_digest, "0" * 64],
            ), self.assertRaisesRegex(ValueError, "snapshot digest changed"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                )
            self.assertFalse(output.exists())

    def test_inventory_isolates_side_effecting_oracle_from_snapshot(self) -> None:
        inventory = load_inventory_module()
        for check_only in (False, True):
            with self.subTest(check_only=check_only), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                snapshot, oracle, output = self.write_snapshot(root)
                self.write_side_effecting_oracle()
                for current, directories, filenames in os.walk(snapshot / "palace"):
                    for name in filenames:
                        (Path(current) / name).chmod(0o400)
                    for name in directories:
                        (Path(current) / name).chmod(0o500)
                (snapshot / "palace").chmod(0o500)
                authoritative_digest = inventory._snapshot_digest(snapshot)
                authoritative_modes = {
                    path.relative_to(snapshot).as_posix(): stat.S_IMODE(path.lstat().st_mode)
                    for path in (snapshot / "palace").rglob("*")
                }
                scratch_before = set(Path(tempfile.gettempdir()).glob("solidstats-memory-oracle-*"))
                result = inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                    check_only=check_only,
                )
                self.assertFalse((snapshot / "palace" / "oracle-marker").exists())
                self.assertEqual(authoritative_digest, inventory._snapshot_digest(snapshot))
                self.assertEqual(
                    authoritative_modes,
                    {
                        path.relative_to(snapshot).as_posix(): stat.S_IMODE(path.lstat().st_mode)
                        for path in (snapshot / "palace").rglob("*")
                    },
                )
                self.assertEqual(
                    scratch_before,
                    set(Path(tempfile.gettempdir()).glob("solidstats-memory-oracle-*")),
                )
                self.assertEqual(check_only, result.get("check_only", False))

    def test_inventory_detects_external_snapshot_drift_after_oracle_isolation(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            ready_file = root / "oracle-ready"
            self.write_side_effecting_oracle(ready_file=ready_file)
            scratch_before = set(Path(tempfile.gettempdir()).glob("solidstats-memory-oracle-*"))

            def mutate_authoritative_snapshot() -> None:
                deadline = time.monotonic() + 2
                while not ready_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if ready_file.exists():
                    (snapshot / "external-drift").write_text("synthetic change", encoding="utf-8")

            writer = threading.Thread(target=mutate_authoritative_snapshot)
            writer.start()
            with self.assertRaisesRegex(ValueError, "snapshot digest changed"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                )
            writer.join(timeout=2)
            self.assertFalse(writer.is_alive())
            self.assertTrue((snapshot / "external-drift").exists())
            self.assertFalse(output.exists())
            self.assertEqual(
                scratch_before,
                set(Path(tempfile.gettempdir()).glob("solidstats-memory-oracle-*")),
            )

    def test_inventory_rejects_duplicate_ids_and_symlinked_input(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            self.oracle_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "collection={'name':'synthetic-records','namespace':'solidstats','palace_id':'synthetic-palace','target_name':'x','embedder':{'model_name':'synthetic-v1','dimension':3},'source_metric':'cosine'}\n"
                "print(json.dumps({'type':'header','record_count':2,'collection':collection}))\n"
                "row={'type':'record','id':'source-1','mempalace_id':'source-1','point_id':'x','document':'synthetic alpha','metadata':{'archive_state':'active','room':'decisions','source_timestamp':'2026-08-20T00:00:00Z','wing':'SolidStats'},'embedding':[1.0]}\n"
                "for index in (1, 2): row['index']=index; print(json.dumps(row))\n"
                "print(json.dumps({'type':'done','record_count':2}))\n",
                encoding="utf-8",
            )
            self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)
            with self.assertRaisesRegex(ValueError, "record-[0-9]+-[0-9a-f]{64}"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                )
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            (snapshot / "snapshot-manifest.json").unlink()
            (snapshot / "snapshot-manifest.json").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "unsafe snapshot component"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=root / "second-output",
                )

    def test_deterministic_recall_fixtures_cover_available_filter_strata(self) -> None:
        inventory = load_inventory_module()
        records = [
            {"id": "source-2", "metadata": {"archive_state": "historical", "room": "conventions", "wing": "infrastructure-archive"}, "vector": [1.0, 0.0]},
            {"id": "source-1", "metadata": {"archive_state": "active", "room": "decisions", "wing": "SolidStats"}, "vector": [0.0, 1.0]},
        ]
        first = inventory.derive_recall_fixtures(records, max_queries=10, top_k=2)
        second = inventory.derive_recall_fixtures(list(reversed(records)), max_queries=10, top_k=2)
        self.assertEqual(first, second)
        self.assertEqual({}, first[0]["filters"])
        self.assertTrue(any("wing" in fixture["filters"] for fixture in first))
        self.assertTrue(any("room" in fixture["filters"] for fixture in first))
        self.assertTrue(any("archive_state" in fixture["filters"] for fixture in first))
        self.assertEqual(["source-1", "source-2"], first[0]["source_ordered_ids"])

    def test_cli_check_only_avoids_corpus_and_rejects_secret_named_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            command = [
                "python3", str(INVENTORY_PATH), "--snapshot-dir", str(snapshot),
                "--freeze-attestation", str(snapshot / "freeze-attestation.json"),
                "--oracle-source-dir", str(oracle), "--output-dir", str(output),
                "--oracle-python", str(self.oracle_python),
                "--check-only",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse(output.exists())
            (snapshot / "mempalace-config.json").write_text(
                '{"api_token":"synthetic-secret"}', encoding="utf-8"
            )
            completed = subprocess.run(
                command[:-1], capture_output=True, text=True, check=False, timeout=5
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertNotIn("synthetic-secret", completed.stderr)

    def test_control_plane_guards_reject_secret_shaped_values_value_free(self) -> None:
        cases = {
            "mempalace-config.json": (
                '{"backend":"chroma","collection_name":"synthetic-records",'
                '"embedding_model":"synthetic-v1","note":"synthetic-secret-value"}'
            ),
            "freeze-attestation.json": (
                '{"write_freeze_at":"2026-08-20T00:00:00Z",'
                '"note":"synthetic-secret-value"}'
            ),
        }
        for relative, payload in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                snapshot, oracle, output = self.write_snapshot(root)
                (snapshot / relative).write_text(payload, encoding="utf-8")
                command = [
                    "python3", str(INVENTORY_PATH), "--snapshot-dir", str(snapshot),
                    "--freeze-attestation", str(snapshot / "freeze-attestation.json"),
                    "--oracle-source-dir", str(oracle), "--output-dir", str(output),
                    "--oracle-python", str(self.oracle_python),
                ]
                completed = subprocess.run(
                    command, capture_output=True, text=True, check=False, timeout=5
                )
                self.assertNotEqual(0, completed.returncode)
                self.assertNotIn("synthetic-secret-value", completed.stderr)
                self.assertFalse(output.exists())

    def test_inventory_preserves_ordinary_lexical_secret_metadata_losslessly(self) -> None:
        inventory = load_inventory_module()
        sentence = "This public synthetic prose mentions secret without credentials."
        metadata = {"note": sentence}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            self.oracle_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "collection={'name':'synthetic-records','namespace':'solidstats','palace_id':'synthetic-palace','target_name':'x','embedder':{'model_name':'synthetic-v1','dimension':3},'source_metric':'cosine'}\n"
                "print(json.dumps({'type':'header','record_count':1,'collection':collection}))\n"
                f"metadata={metadata!r}\n"
                "print(json.dumps({'type':'record','index':1,'id':'source-1','mempalace_id':'source-1','point_id':'x','document':'synthetic alpha','metadata':metadata,'embedding':[1.0]}))\n"
                "print(json.dumps({'type':'done','record_count':1}))\n",
                encoding="utf-8",
            )
            self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)
            result = inventory.build_source_inventory(
                snapshot_dir=snapshot,
                freeze_attestation=snapshot / "freeze-attestation.json",
                oracle_source_dir=oracle,
                oracle_python=self.oracle_python,
                output_dir=output,
            )
            emitted = json.loads((output / "source-records.jsonl").read_text(encoding="utf-8"))
            summary = (output / "source-inventory.json").read_text(encoding="utf-8")
            self.assertEqual(metadata, emitted["metadata"])
            self.assertEqual(
                inventory.canonical_json_bytes(metadata),
                inventory.canonical_json_bytes(emitted["metadata"]),
            )
            self.assertNotIn(sentence, summary)
            self.assertNotIn(sentence, json.dumps(result, sort_keys=True))
            self.assertEqual(0o700, stat.S_IMODE(output.stat().st_mode))
            for name in (
                "source-records.jsonl",
                "source-vectors.jsonl",
                "recall-fixtures.json",
                "source-inventory.json",
            ):
                self.assertEqual(0o600, stat.S_IMODE((output / name).stat().st_mode))

    def test_inventory_rejects_secret_shaped_metadata_keys_before_writing(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            self.oracle_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "print(json.dumps({'type':'header','record_count':1,'collection':{'name':'synthetic-records','namespace':'solidstats','palace_id':'synthetic-palace','target_name':'x','embedder':{'model_name':'synthetic-v1','dimension':3},'source_metric':'cosine'}}))\n"
                "print(json.dumps({'type':'record','index':1,'id':'source-1','mempalace_id':'source-1','point_id':'x','document':'synthetic alpha','metadata':{'api_token':''},'embedding':[1.0]}))\n"
                "print(json.dumps({'type':'done','record_count':1}))\n",
                encoding="utf-8",
            )
            self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)
            with self.assertRaisesRegex(ValueError, "record-1-[0-9a-f]{64}") as context:
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                )
            self.assertNotIn("api_token", str(context.exception))
            self.assertFalse(output.exists())

    def test_inventory_applies_configured_record_bound_before_output(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            snapshot, oracle, output = self.write_snapshot(Path(temporary))
            with self.assertRaisesRegex(ValueError, "record limit exceeded"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                    max_records=1,
                )
            self.assertFalse(output.exists())

    def test_check_only_requires_raw_chroma_and_oracle_page_order(self) -> None:
        inventory = load_inventory_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot, oracle, output = self.write_snapshot(root)
            (snapshot / "palace" / "chroma.sqlite3").unlink()
            with self.assertRaisesRegex(ValueError, "unsafe snapshot component"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                    check_only=True,
                )
            self.assertFalse(output.exists())
            (snapshot / "palace" / "chroma.sqlite3").write_bytes(b"synthetic raw Chroma state")
            self.oracle_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "collection={'name':'synthetic-records','namespace':'solidstats','palace_id':'synthetic-palace','target_name':'x','embedder':{'model_name':'synthetic-v1','dimension':3},'source_metric':'cosine'}\n"
                "print(json.dumps({'type':'header','record_count':2,'collection':collection}))\n"
                "for index in (1, 3): print(json.dumps({'type':'record','index':index,'id':str(index),'mempalace_id':str(index),'point_id':'x','document':'x','metadata':{'archive_state':'active','room':'decisions','source_timestamp':'2026-08-20T00:00:00Z','wing':'SolidStats'},'embedding':[1.0]}))\n"
                "print(json.dumps({'type':'done','record_count':2}))\n",
                encoding="utf-8",
            )
            self.oracle_python.chmod(self.oracle_python.stat().st_mode | stat.S_IXUSR)
            with self.assertRaisesRegex(ValueError, "invalid oracle protocol"):
                inventory.build_source_inventory(
                    snapshot_dir=snapshot,
                    freeze_attestation=snapshot / "freeze-attestation.json",
                    oracle_source_dir=oracle,
                    oracle_python=self.oracle_python,
                    output_dir=output,
                )
            self.assertFalse(output.exists())


class TransformContractTests(unittest.TestCase):
    def write_contract_inputs(self, root: Path) -> tuple[Path, Path]:
        proof = root / "inventory-proof.json"
        write_json(proof, {"schema": "synthetic", "count": 2})
        contract = root / "mapping-contract.json"
        write_approved_mapping_contract(contract, proof)
        return proof, contract

    def test_preflight_rejects_unapproved_incomplete_stale_and_tampered_contracts(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proof, contract_path = self.write_contract_inputs(root)
            self.assertEqual(
                "approved",
                bundle.load_approved_mapping_contract(proof, contract_path)["status"],
            )
            for mutation in (
                lambda contract: contract.update(status="draft"),
                lambda contract: contract.pop("legacy_room_label_treatment"),
                lambda contract: contract.update(source_inventory_sha256="0" * 64),
                lambda contract: contract["preservation_representation"].update(
                    source_metadata_copy={"reserved_key": "_solidstats_migration"}
                ),
                lambda contract: contract["timestamp_semantics"].update(rule="tampered"),
            ):
                with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    ValueError, "mapping contract"
                ):
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
                    mutation(contract)
                    write_json(contract_path, contract)
                    bundle.load_approved_mapping_contract(proof, contract_path)
                write_approved_mapping_contract(contract_path, proof)

    def test_committed_contract_accepts_the_approved_fail_closed_sentence(self) -> None:
        """The approved public contract must pass before private inputs are read."""
        bundle = load_bundle_module()
        contract = ROOT / ".planning/phases/20-local-corpus-migration/20-MAPPING-CONTRACT.json"
        proof = ROOT / ".planning/phases/20-local-corpus-migration/20-SOURCE-INVENTORY.json"
        self.assertEqual("approved", bundle.load_approved_mapping_contract(proof, contract)["status"])

    def test_snapshot_identity_uses_contained_manifest_sidecars(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "sidecars").mkdir()
            write_json(snapshot / "sidecars" / "identity.json", {"palace_id": "synthetic-palace", "namespace": "solidstats"})
            write_json(snapshot / "sidecars" / "config.json", {"collection_name": "synthetic-records"})
            write_json(snapshot / "sidecars" / "embedder.json", {"synthetic-records": {"model_name": "synthetic", "dimension": 3}})
            write_json(snapshot / "snapshot-manifest.json", {
                "identity_sidecar": "sidecars/identity.json",
                "config_sidecar": "sidecars/config.json",
                "embedder_sidecar": "sidecars/embedder.json",
            })
            palace_id, namespace, collection, embedder = bundle._snapshot_identity(snapshot)
            self.assertEqual(("synthetic-palace", "solidstats", "synthetic-records"), (palace_id, namespace, collection))
            self.assertEqual("synthetic", embedder["model_name"])
            (snapshot / "escape.json").write_text("{}", encoding="utf-8")
            (snapshot / "sidecars" / "identity.json").unlink()
            (snapshot / "sidecars" / "identity.json").symlink_to(snapshot / "escape.json")
            with self.assertRaisesRegex(ValueError, "snapshot"):
                bundle._snapshot_identity(snapshot)

    def test_import_requires_operation_ack_schema_schema_and_target_id_digest(self) -> None:
        bundle = load_bundle_module()
        points = [
            {"id": "point-a", "vector": [1.0, 0.0], "payload": {"mempalace_id": "source-a"}},
            {"id": "point-b", "vector": [0.0, 1.0], "payload": {"mempalace_id": "source-b"}},
        ]
        expected_digest = bundle.point_id_set_sha256(points)
        responses = iter([
            {"status": "ok", "result": True},
            {"status": "ok", "result": {"count": 0}},
            {"status": "ok", "result": {"config": {"params": {"vectors": {"size": 2, "distance": "Cosine"}}}}},
            {"status": "ok", "result": {"status": "completed", "operation_id": 1}},
            {"status": "ok", "result": {"count": 2}},
            {"status": "ok", "result": {"points": [{"id": "point-a"}, {"id": "point-b"}], "next_page_offset": None}},
        ])
        with mock.patch.object(bundle, "_qdrant_request", side_effect=lambda *_args, **_kwargs: next(responses)):
            result = bundle.import_batches(
                "http://127.0.0.1:6333", "synthetic", points, dimension=2,
                batch_size=100, expected_point_id_digest=expected_digest,
            )
        self.assertEqual(1, result["batch_acknowledgements"])
        self.assertEqual(expected_digest, result["target_point_id_set_sha256"])

    def test_pinned_qdrant_image_must_match_the_manifest_digest(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "qdrant.yaml"
            image = "example.test/qdrant:v1@sha256:" + "a" * 64
            manifest.write_text("image: " + image + "\n", encoding="utf-8")
            self.assertEqual(image, bundle.load_pinned_qdrant_image(manifest))
            manifest.write_text("image: example.test/qdrant:v1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Qdrant image"):
                bundle.load_pinned_qdrant_image(manifest)

    def test_private_source_artifacts_have_a_separate_bounded_file_cap(self) -> None:
        bundle = load_bundle_module()
        self.assertGreater(
            bundle.MAX_PRIVATE_SOURCE_ARTIFACT_BYTES,
            bundle.MAX_JSON_BYTES,
        )

    def test_vector_strategy_requires_all_six_reuse_predicates(self) -> None:
        bundle = load_bundle_module()
        source = {
            "embedder_identity": "synthetic-embedder",
            "embedder_configuration": {"normalization": "none"},
            "dimension": 3,
            "metric": "cosine",
            "serialization": "json-f32",
        }
        target = {
            "embedder_identity": "synthetic-embedder",
            "embedder_configuration": {"normalization": "none"},
            "dimension": 3,
            "metric": "Cosine",
            "serialization": "json-f32",
        }
        self.assertEqual("reuse", bundle.select_vector_strategy(source, target).strategy)
        for key, replacement in (
            ("embedder_identity", "different-embedder"),
            ("embedder_configuration", {"normalization": "l2"}),
            ("dimension", 4),
            ("metric", "Dot"),
            ("serialization", "protobuf-f32"),
        ):
            with self.subTest(predicate=key):
                changed = dict(target)
                changed[key] = replacement
                strategy = bundle.select_vector_strategy(
                    source, changed, reembed_model_artifact=Path("/synthetic/model")
                )
                self.assertEqual("reembed", strategy.strategy)
                self.assertIn(key, strategy.reason)

    def test_transform_preserves_nested_metadata_and_bijective_v350_ids(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            proof, contract_path = self.write_contract_inputs(Path(temporary))
            contract = bundle.load_approved_mapping_contract(proof, contract_path)
            sources = [
                {
                    "id": "synthetic-eligible",
                    "document": "synthetic document",
                    "metadata": {"room": "legacy-room", "wing": "infrastructure", "filed_at": "opaque"},
                    "vector": [0.0, 1.0, 0.0],
                },
                {
                    "id": "synthetic-excluded",
                    "document": "synthetic excluded document",
                    "metadata": {"room": "legacy-room", "wing": "Agent"},
                    "vector": [1.0, 0.0, 0.0],
                },
            ]
            points, id_map, excluded = bundle.build_target_points(
                sources, contract, target_updated_at="2026-08-20T00:00:00Z"
            )
            self.assertEqual(1, len(points))
            self.assertEqual(["synthetic-excluded"], excluded)
            point = points[0]
            self.assertEqual("synthetic-eligible", point["payload"]["mempalace_id"])
            self.assertEqual(str(uuid.uuid5(UUID_NAMESPACE, "synthetic-eligible")), point["id"])
            self.assertEqual("infrastructure-archive", point["payload"]["metadata"]["wing"])
            self.assertEqual("legacy-room", point["payload"]["metadata"]["room"])
            self.assertEqual(
                sources[0]["metadata"],
                point["payload"]["metadata"]["_solidstats_migration"]["source_metadata"],
            )
            self.assertEqual("2026-08-20T00:00:00Z", point["payload"]["updated_at"])
            self.assertEqual(["synthetic-eligible"], [mapping["source_id"] for mapping in id_map])

    def test_contract_rules_change_routing_without_a_builtin_default(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proof = root / "inventory-proof.json"
            write_json(proof, {"schema": "synthetic"})
            standard = root / "standard.json"
            contrasting = root / "contrasting.json"
            write_approved_mapping_contract(standard, proof)
            write_approved_mapping_contract(
                contrasting, proof, infrastructure_target="synthetic-archive-b"
            )
            source = [{"id": "synthetic-id", "document": "synthetic", "metadata": {"wing": "infrastructure", "room": "legacy"}, "vector": [1.0]}]
            first, _first_map, _first_excluded = bundle.build_target_points(
                source, bundle.load_approved_mapping_contract(proof, standard), target_updated_at="fixed"
            )
            second, _second_map, _second_excluded = bundle.build_target_points(
                source, bundle.load_approved_mapping_contract(proof, contrasting), target_updated_at="fixed"
            )
            self.assertEqual("infrastructure-archive", first[0]["payload"]["metadata"]["wing"])
            self.assertEqual("synthetic-archive-b", second[0]["payload"]["metadata"]["wing"])

    def test_reserved_metadata_collision_fails_before_points_exist(self) -> None:
        bundle = load_bundle_module()
        with tempfile.TemporaryDirectory() as temporary:
            proof, contract_path = self.write_contract_inputs(Path(temporary))
            contract = bundle.load_approved_mapping_contract(proof, contract_path)
            with self.assertRaisesRegex(ValueError, "reserved metadata"):
                bundle.build_target_points(
                    [{"id": "synthetic", "document": "synthetic", "metadata": {"wing": "SolidStats", "_solidstats_migration": {}}, "vector": [1.0]}],
                    contract,
                    target_updated_at="fixed",
                )


if __name__ == "__main__":
    unittest.main()
