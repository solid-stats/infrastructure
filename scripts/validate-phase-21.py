#!/usr/bin/env python3
"""Validate value-free Phase 21 evidence and transition chains offline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import sys
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HANDOFF = (
    ROOT
    / ".planning/phases/20-local-corpus-migration/20-PHASE21-HANDOFF.json"
)
DEFAULT_PARITY = (
    ROOT / ".planning/phases/20-local-corpus-migration/20-PARITY-REPORT.json"
)
STAGE_SCHEMA = "solidstats-memory-phase21-stage/v1"
EVIDENCE_SCHEMA = "solidstats-memory-phase21-evidence/v1"
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
EVIDENCE_FIELDS = {
    "schema",
    "run_id",
    "stage",
    "prior_evidence_sha256",
    "input_digests",
    "checks",
    "started_at",
    "completed_at",
    "verdict",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FORBIDDEN_KEY_PARTS = {
    "alias",
    "collection",
    "corpus",
    "credential",
    "document",
    "identifier",
    "metadata",
    "password",
    "path",
    "payload",
    "query",
    "response",
    "secret",
    "token",
    "vector",
}


class Phase21ValidationError(ValueError):
    """A value-free Phase 21 contract failure."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the stable bytes used by evidence digest chaining."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise Phase21ValidationError("evidence is not canonical JSON") from error


def sha256_file(path: Path) -> str:
    """Hash one regular, non-symlink public evidence file."""
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise OSError
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as error:
        raise Phase21ValidationError("public evidence file is unsafe") from error


def _load_json(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise OSError
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise Phase21ValidationError("public evidence file is invalid") from error
    if not isinstance(value, dict):
        raise Phase21ValidationError("public evidence root is invalid")
    return value


def _is_digest_key(key: str) -> bool:
    return key.endswith("_sha256") or key.endswith("_digest")


def _validate_value_free_node(value: object, *, key: str, depth: int) -> None:
    if depth > 12:
        raise Phase21ValidationError("evidence nesting exceeds the public bound")
    if key and (
        not SAFE_KEY.fullmatch(key)
        or (
            not _is_digest_key(key)
            and any(part in key for part in FORBIDDEN_KEY_PARTS)
        )
    ):
        raise Phase21ValidationError("evidence contains a prohibited field")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise Phase21ValidationError("evidence object exceeds the public bound")
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise Phase21ValidationError("evidence contains a prohibited field")
            _validate_value_free_node(child, key=child_key, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 128:
            raise Phase21ValidationError("evidence list exceeds the public bound")
        for child in value:
            _validate_value_free_node(child, key=key, depth=depth + 1)
        return
    if value is None:
        raise Phase21ValidationError("evidence contains a null value")
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, bool) or value < 0 or not math.isfinite(value):
            raise Phase21ValidationError("evidence contains an invalid aggregate")
        return
    if not isinstance(value, str) or not value:
        raise Phase21ValidationError("evidence contains an invalid public value")
    if _is_digest_key(key):
        if not SHA256.fullmatch(value):
            raise Phase21ValidationError("evidence contains an invalid digest")
        return
    if key == "schema" and value in {STAGE_SCHEMA, EVIDENCE_SCHEMA}:
        return
    if key == "run_id" and RUN_ID.fullmatch(value):
        return
    if key == "stage" and value in STAGES:
        return
    if key in {"started_at", "completed_at"} and UTC_TIMESTAMP.fullmatch(value):
        return
    if key == "verdict" and value in {"pass", "fail"}:
        return
    raise Phase21ValidationError("evidence contains a non-allowlisted string")


def validate_value_free_payload(payload: object) -> None:
    """Reject corpus-bearing, identifying, secret, or private-path content."""
    _validate_value_free_node(payload, key="", depth=0)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP.fullmatch(value):
        raise Phase21ValidationError("evidence timestamp is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise Phase21ValidationError("evidence timestamp is invalid") from error


def _checks_pass(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(value) and all(_checks_pass(child) for child in value.values())
    if isinstance(value, list):
        return bool(value) and all(_checks_pass(child) for child in value)
    if isinstance(value, bool):
        return value
    return value is not None


def validate_evidence_envelope(payload: object) -> dict[str, object]:
    """Validate the exact common stage-evidence envelope."""
    validate_value_free_payload(payload)
    if not isinstance(payload, Mapping) or set(payload) != EVIDENCE_FIELDS:
        raise Phase21ValidationError("evidence envelope fields are invalid")
    schema = payload.get("schema")
    run_id = payload.get("run_id")
    stage = payload.get("stage")
    prior = payload.get("prior_evidence_sha256")
    input_digests = payload.get("input_digests")
    checks = payload.get("checks")
    if schema not in {STAGE_SCHEMA, EVIDENCE_SCHEMA}:
        raise Phase21ValidationError("evidence schema is invalid")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise Phase21ValidationError("evidence run identity is invalid")
    if stage not in STAGES:
        raise Phase21ValidationError("evidence stage is invalid")
    if not isinstance(prior, str) or not SHA256.fullmatch(prior):
        raise Phase21ValidationError("prior evidence digest is invalid")
    if not isinstance(input_digests, Mapping) or not input_digests:
        raise Phase21ValidationError("evidence input digests are invalid")
    if any(
        not isinstance(key, str)
        or not _is_digest_key(key)
        or not isinstance(value, str)
        or not SHA256.fullmatch(value)
        for key, value in input_digests.items()
    ):
        raise Phase21ValidationError("evidence input digests are invalid")
    if not isinstance(checks, Mapping) or not checks or not _checks_pass(checks):
        raise Phase21ValidationError("evidence checks are not all passing")
    lock = checks.get("stage_lock")
    expected_owner = hashlib.sha256(run_id.encode("ascii")).hexdigest()
    if lock != {"acquired": True, "owner_run_sha256": expected_owner}:
        raise Phase21ValidationError("evidence stage lock is invalid")
    started = _parse_timestamp(payload.get("started_at"))
    completed = _parse_timestamp(payload.get("completed_at"))
    if completed < started:
        raise Phase21ValidationError("evidence timestamps are out of order")
    if payload.get("verdict") not in {"pass", "fail"}:
        raise Phase21ValidationError("evidence verdict is invalid")
    return dict(payload)


def _phase20_bindings(
    handoff_path: Path,
    parity_path: Path,
) -> tuple[str, str]:
    handoff = _load_json(handoff_path)
    parity_digest = sha256_file(parity_path)
    if handoff.get("handoff_schema") != "solidstats-memory-phase21-handoff/v1":
        raise Phase21ValidationError("Phase 20 handoff schema is invalid")
    if handoff.get("parity_report_sha256") != parity_digest:
        raise Phase21ValidationError("Phase 20 parity digest is stale")
    parity = _load_json(parity_path)
    if parity.get("parity_schema") != "solidstats-memory-parity/v1":
        raise Phase21ValidationError("Phase 20 parity schema is invalid")
    if parity.get("verdict") != "pass":
        raise Phase21ValidationError("Phase 20 parity verdict is not passing")
    return sha256_file(handoff_path), parity_digest


def validate_transition_chain(
    evidence: Sequence[Mapping[str, object]],
    *,
    handoff_path: Path = DEFAULT_HANDOFF,
    parity_path: Path = DEFAULT_PARITY,
    require_complete: bool = False,
) -> dict[str, object]:
    """Validate legal ordering, digest chaining, replay, locking, and resume."""
    if not evidence:
        raise Phase21ValidationError("evidence chain is empty")
    handoff_digest, parity_digest = _phase20_bindings(
        Path(handoff_path), Path(parity_path)
    )
    expected_inputs = {
        "phase20_handoff_sha256": handoff_digest,
        "phase20_parity_report_sha256": parity_digest,
    }
    accepted: list[dict[str, object]] = []
    accepted_digests: list[str] = []
    by_stage: dict[str, str] = {}
    locked_run: str | None = None
    for index, candidate in enumerate(evidence):
        if (
            locked_run is not None
            and isinstance(candidate, Mapping)
            and candidate.get("run_id") != locked_run
        ):
            raise Phase21ValidationError(
                f"stage lock collision at stage index {index}"
            )
        try:
            envelope = validate_evidence_envelope(candidate)
        except Phase21ValidationError as error:
            raise Phase21ValidationError(
                f"evidence at stage index {index} is invalid"
            ) from error
        stage = str(envelope["stage"])
        run_id = str(envelope["run_id"])
        digest = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
        if locked_run is None:
            locked_run = run_id
        elif run_id != locked_run:
            raise Phase21ValidationError(
                f"stage lock collision at stage index {index}"
            )
        if stage in by_stage:
            if by_stage[stage] == digest:
                continue
            raise Phase21ValidationError(
                f"unequal replay collision at stage index {index}"
            )
        expected_stage = STAGES[len(accepted)] if len(accepted) < len(STAGES) else None
        if stage != expected_stage:
            raise Phase21ValidationError(
                f"illegal transition at stage index {index}"
            )
        expected_prior = handoff_digest if not accepted else accepted_digests[-1]
        if envelope["prior_evidence_sha256"] != expected_prior:
            raise Phase21ValidationError(
                f"prior evidence mismatch at stage index {index}"
            )
        inputs = envelope["input_digests"]
        if not isinstance(inputs, Mapping) or any(
            inputs.get(key) != value for key, value in expected_inputs.items()
        ):
            raise Phase21ValidationError(
                f"Phase 20 binding mismatch at stage index {index}"
            )
        if envelope["verdict"] != "pass":
            raise Phase21ValidationError(
                f"failed verdict at stage index {index}"
            )
        by_stage[stage] = digest
        accepted.append(envelope)
        accepted_digests.append(digest)
    if require_complete and len(accepted) != len(STAGES):
        raise Phase21ValidationError("evidence chain is incomplete")
    return {
        "stage": accepted[-1]["stage"],
        "stage_count": len(accepted),
        "run_id_sha256": hashlib.sha256(locked_run.encode("ascii")).hexdigest(),
        "verdict": "pass",
    }


def _chain_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise Phase21ValidationError("evidence chain directory is invalid")
    selected: list[tuple[int, Path]] = []
    for path in directory.glob("*.json"):
        try:
            value = _load_json(path)
        except Phase21ValidationError:
            if path.name.startswith("21-STAGE-"):
                raise
            continue
        schema = value.get("schema")
        if schema not in {STAGE_SCHEMA, EVIDENCE_SCHEMA}:
            continue
        stage = value.get("stage")
        order = STAGES.index(stage) if stage in STAGES else len(STAGES)
        selected.append((order, path))
    if not selected:
        raise Phase21ValidationError("evidence chain is empty")
    return [path for _order, path in sorted(selected, key=lambda item: item[0])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--evidence", action="append", type=Path, default=[])
    parser.add_argument("--check-chain", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = list(args.evidence)
        if args.check_chain is not None:
            if paths:
                raise Phase21ValidationError("evidence inputs are ambiguous")
            paths = _chain_files(args.check_chain)
        if not paths:
            raise Phase21ValidationError("evidence input is required")
        payloads = [_load_json(path) for path in paths]
        if len(payloads) == 1 and args.handoff is None and args.check_chain is None:
            validate_evidence_envelope(payloads[0])
            message = "PASS: Phase 21 evidence validated"
        else:
            handoff = args.handoff or DEFAULT_HANDOFF
            parity = (
                handoff.with_name("20-PARITY-REPORT.json")
                if args.handoff is not None
                else DEFAULT_PARITY
            )
            validate_transition_chain(
                payloads,
                handoff_path=handoff,
                parity_path=parity,
                require_complete=args.check_chain is not None,
            )
            message = "PASS: Phase 21 evidence chain validated"
        print(message)
        return 0
    except (OSError, Phase21ValidationError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
