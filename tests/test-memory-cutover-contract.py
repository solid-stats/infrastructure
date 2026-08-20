#!/usr/bin/env python3
"""Contract tests for the value-free Phase 21 transition chain."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-phase-21.py"
SPEC = importlib.util.spec_from_file_location("phase21_validator", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

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


if __name__ == "__main__":
    unittest.main()
