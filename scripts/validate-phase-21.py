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
BACKUP_RESTORE_SCHEMA = "solidstats-memory-backup-restore-evidence/v1"
RECOVERY_SCHEMA = "solidstats-memory-recovery-evidence/v1"
CUTOVER_SEAL_SCHEMA = "solidstats-memory-cutover-seal/v1"
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
BACKUP_RESTORE_FIELDS = {
    "schema",
    "run_id",
    "phase20_bindings",
    "quiescence",
    "capacity",
    "package_checks",
    "object_checks",
    "target_absence",
    "restore_checks",
    "parity_checks",
    "alias_compatibility",
    "rollback_state",
    "verdict",
}
BACKUP_RESTORE_SECTION_FIELDS = {
    "quiescence": {
        "stable",
        "writer_count",
        "kubernetes_reachable",
        "qdrant_reachable",
        "s3_reachable",
    },
    "capacity": {
        "sufficient",
        "snapshot_bytes",
        "baseline_snapshot_bytes",
        "baseline_bound_bytes",
        "reserve_bytes",
        "required_bytes",
        "pvc_requested_bytes",
        "pvc_capacity_bytes",
        "pvc_free_bytes",
        "node_free_bytes",
    },
    "package_checks": {
        "complete",
        "member_count",
        "package_sha256",
        "snapshot_bytes",
        "metadata_archive_bytes",
        "local_hashes_rechecked",
        "job_count",
    },
    "object_checks": {
        "verified",
        "inventory_exact",
        "downloaded",
        "hashes_rechecked",
        "object_count",
        "package_sha256",
    },
    "target_absence": {
        "confirmed",
        "collection_inventory_checked",
        "alias_inventory_checked",
        "target_lookup_checked",
    },
    "restore_checks": {
        "green",
        "configuration_match",
        "count_match",
        "parity_exact",
        "record_count",
        "snapshot_priority",
    },
    "parity_checks": {
        "exact",
        "record_count",
        "field_exact",
        "id_exact",
        "metadata_exact",
        "timestamp_exact",
        "vector_exact",
        "exclusion_exact",
        "ann_exact",
    },
    "alias_compatibility": {
        "probe_passed",
        "prestate_sha256",
        "poststate_sha256",
        "restored",
        "exact_image",
    },
    "rollback_state": {
        "active_state_unchanged",
        "routing_unchanged",
        "nginx_unchanged",
        "registration_unchanged",
        "legacy_runtime_unchanged",
        "recurring_schedule_unchanged",
    },
}
RECOVERY_FIELDS = {
    "schema",
    "run_id",
    "cutover_evidence_sha256",
    "restart_checks",
    "backup_api_control_checks",
    "steady_state_backup_consistency",
    "fresh_backup_checks",
    "writer_resumption_checks",
    "reboot_checks",
    "rollback_checks",
    "forward_checks",
    "client_checks",
    "verdict",
}
RECOVERY_SECTION_FIELDS = {
    "restart_checks": {
        "mempalace_identity_changed",
        "mempalace_behavior_passed",
        "qdrant_identity_changed",
        "qdrant_behavior_passed",
        "ordered",
    },
    "backup_api_control_checks": {
        "measured",
        "binding_current",
        "single_candidate",
        "positive_get",
        "network_negative",
        "rbac_negative",
        "policy_sha256",
    },
    "steady_state_backup_consistency": {
        "writer_prestate_recorded",
        "zero_writers",
        "zero_pvc_consumers",
        "source_before_sha256",
        "source_after_sha256",
        "archive_sha256",
    },
    "fresh_backup_checks": {
        "exact_template",
        "upload_inventory_exact",
        "downloaded",
        "checksums_rechecked",
    },
    "writer_resumption_checks": {
        "replicas_restored",
        "available",
        "capture_passed",
        "read_after_write_passed",
        "schedules_suspended_on_failure",
    },
    "reboot_checks": {
        "boot_identity_changed",
        "reconnected_within_deadline",
        "node_ready",
        "pvc_bound",
        "qdrant_ready",
        "mempalace_available",
        "nginx_active",
        "behavior_passed",
    },
    "rollback_checks": {
        "reverse_order",
        "legacy_behavior_passed",
        "retained_data_preserved",
    },
    "forward_checks": {
        "exact_replay",
        "behavior_passed",
        "retained_data_preserved",
    },
    "client_checks": {
        "legacy_retained_until_recovery",
        "unrelated_unchanged",
        "new_client_live",
    },
}
CUTOVER_SEAL_FIELDS = {
    "schema",
    "run_id",
    "recovery_evidence_sha256",
    "requirements",
    "prohibitions",
    "legacy_client_absent",
    "new_client_live",
    "backup_schedule_live",
    "verdict",
}
CUTOVER_SEAL_REQUIREMENTS = {"iso_01", "iso_03", "ops_02", "ops_03", "ops_05"}
CUTOVER_SEAL_PROHIBITIONS = {
    "no_early_legacy_removal",
    "no_public_qdrant",
    "no_retained_data_deletion",
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
AGGREGATE_SAFE_KEYS = {
    "alias_inventory_checked",
    "collection_inventory_checked",
    "metadata_archive_bytes",
    "metadata_exact",
    "vector_exact",
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


def _validate_value_free_node(
    value: object,
    *,
    key: str,
    depth: int,
    allow_alias_compatibility: bool,
) -> None:
    if depth > 12:
        raise Phase21ValidationError("evidence nesting exceeds the public bound")
    if key and (
        not SAFE_KEY.fullmatch(key)
        or (
            key not in AGGREGATE_SAFE_KEYS
            and not _is_digest_key(key)
            and not (
                allow_alias_compatibility
                and depth == 1
                and key == "alias_compatibility"
            )
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
            _validate_value_free_node(
                child,
                key=child_key,
                depth=depth + 1,
                allow_alias_compatibility=allow_alias_compatibility,
            )
        return
    if isinstance(value, list):
        if len(value) > 128:
            raise Phase21ValidationError("evidence list exceeds the public bound")
        for child in value:
            _validate_value_free_node(
                child,
                key=key,
                depth=depth + 1,
                allow_alias_compatibility=allow_alias_compatibility,
            )
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
    if key == "schema" and value in {
        STAGE_SCHEMA,
        EVIDENCE_SCHEMA,
        BACKUP_RESTORE_SCHEMA,
        RECOVERY_SCHEMA,
        CUTOVER_SEAL_SCHEMA,
    }:
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
    allow_alias_compatibility = (
        isinstance(payload, Mapping)
        and payload.get("schema") == BACKUP_RESTORE_SCHEMA
    )
    _validate_value_free_node(
        payload,
        key="",
        depth=0,
        allow_alias_compatibility=allow_alias_compatibility,
    )


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


def _require_passing_check(
    section: Mapping[str, object], key: str, message: str
) -> None:
    if section.get(key) is not True:
        raise Phase21ValidationError(message)


def validate_backup_restore_evidence(payload: object) -> dict[str, object]:
    """Validate the exact aggregate backup and isolated-restore evidence."""
    validate_value_free_payload(payload)
    if not isinstance(payload, Mapping) or set(payload) != BACKUP_RESTORE_FIELDS:
        raise Phase21ValidationError("backup and restore evidence fields are invalid")
    if payload.get("schema") != BACKUP_RESTORE_SCHEMA:
        raise Phase21ValidationError("backup and restore evidence schema is invalid")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise Phase21ValidationError("backup and restore run identity is invalid")
    bindings = payload.get("phase20_bindings")
    if not isinstance(bindings, Mapping) or not bindings:
        raise Phase21ValidationError("backup and restore bindings are invalid")
    if any(
        not isinstance(key, str)
        or not _is_digest_key(key)
        or not isinstance(value, str)
        or not SHA256.fullmatch(value)
        for key, value in bindings.items()
    ):
        raise Phase21ValidationError("backup and restore bindings are invalid")
    sections: dict[str, Mapping[str, object]] = {}
    for name in BACKUP_RESTORE_FIELDS - {
        "schema",
        "run_id",
        "phase20_bindings",
        "verdict",
    }:
        section = payload.get(name)
        if (
            not isinstance(section, Mapping)
            or set(section) != BACKUP_RESTORE_SECTION_FIELDS[name]
            or not _checks_pass(section)
        ):
            raise Phase21ValidationError(
                "backup and restore checks are not all passing"
            )
        sections[name] = section
    required_checks = {
        "quiescence": (
            "stable",
            "kubernetes_reachable",
            "qdrant_reachable",
            "s3_reachable",
        ),
        "capacity": ("sufficient",),
        "package_checks": ("complete", "local_hashes_rechecked"),
        "object_checks": (
            "verified",
            "inventory_exact",
            "downloaded",
            "hashes_rechecked",
        ),
        "target_absence": (
            "confirmed",
            "collection_inventory_checked",
            "alias_inventory_checked",
            "target_lookup_checked",
        ),
        "restore_checks": (
            "green",
            "configuration_match",
            "count_match",
            "snapshot_priority",
        ),
        "parity_checks": (
            "exact",
            "field_exact",
            "id_exact",
            "metadata_exact",
            "timestamp_exact",
            "vector_exact",
            "exclusion_exact",
            "ann_exact",
        ),
        "alias_compatibility": ("probe_passed", "restored", "exact_image"),
        "rollback_state": (
            "active_state_unchanged",
            "routing_unchanged",
            "nginx_unchanged",
            "registration_unchanged",
            "legacy_runtime_unchanged",
            "recurring_schedule_unchanged",
        ),
    }
    for section_name, keys in required_checks.items():
        for key in keys:
            _require_passing_check(
                sections[section_name],
                key,
                "backup and restore checks are not all passing",
            )
    alias = sections["alias_compatibility"]
    if alias.get("prestate_sha256") != alias.get("poststate_sha256"):
        raise Phase21ValidationError("alias prestate was not restored")
    capacity = sections["capacity"]
    if (
        capacity.get("required_bytes")
        != capacity.get("snapshot_bytes", 0) * 2 + capacity.get("reserve_bytes", 0)
        or capacity.get("pvc_capacity_bytes", 0)
        < capacity.get("pvc_requested_bytes", 0)
        or capacity.get("pvc_free_bytes", 0) < capacity.get("required_bytes", 0)
        or capacity.get("node_free_bytes", 0) < capacity.get("required_bytes", 0)
        or capacity.get("snapshot_bytes", 0)
        > capacity.get("baseline_bound_bytes", 0)
        or capacity.get("baseline_snapshot_bytes", 0)
        > capacity.get("baseline_bound_bytes", 0)
    ):
        raise Phase21ValidationError("backup and restore capacity is invalid")
    package = sections["package_checks"]
    objects = sections["object_checks"]
    restore = sections["restore_checks"]
    parity = sections["parity_checks"]
    if (
        package.get("member_count") != 4
        or package.get("job_count") != 1
        or objects.get("object_count") != 4
        or package.get("package_sha256") != objects.get("package_sha256")
        or restore.get("record_count") != parity.get("record_count")
    ):
        raise Phase21ValidationError("backup and restore aggregate binding is invalid")
    if payload.get("verdict") != "pass":
        raise Phase21ValidationError("backup and restore verdict is not passing")
    return dict(payload)


def validate_recovery_evidence(payload: object) -> dict[str, object]:
    """Validate exact behavior, consistency, and recovery aggregates."""
    validate_value_free_payload(payload)
    if not isinstance(payload, Mapping) or set(payload) != RECOVERY_FIELDS:
        raise Phase21ValidationError("recovery evidence fields are invalid")
    if payload.get("schema") != RECOVERY_SCHEMA:
        raise Phase21ValidationError("recovery evidence schema is invalid")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise Phase21ValidationError("recovery run identity is invalid")
    cutover_digest = payload.get("cutover_evidence_sha256")
    if not isinstance(cutover_digest, str) or not SHA256.fullmatch(cutover_digest):
        raise Phase21ValidationError("recovery predecessor digest is invalid")
    sections: dict[str, Mapping[str, object]] = {}
    for name, expected_fields in RECOVERY_SECTION_FIELDS.items():
        section = payload.get(name)
        if not isinstance(section, Mapping) or set(section) != expected_fields:
            raise Phase21ValidationError("recovery check fields are invalid")
        sections[name] = section
        for key, value in section.items():
            if key.endswith("_sha256"):
                if not isinstance(value, str) or not SHA256.fullmatch(value):
                    raise Phase21ValidationError("recovery digest is invalid")
            elif value is not True:
                raise Phase21ValidationError("recovery checks are not all passing")
    consistency = sections["steady_state_backup_consistency"]
    if not (
        consistency["source_before_sha256"]
        == consistency["source_after_sha256"]
        == consistency["archive_sha256"]
    ):
        raise Phase21ValidationError("steady-state metadata digests differ")
    if payload.get("verdict") != "pass":
        raise Phase21ValidationError("recovery verdict is not passing")
    return dict(payload)


def validate_cutover_seal(
    payload: object,
    *,
    recovery_payload: object | None = None,
    recovery_sha256: str | None = None,
) -> dict[str, object]:
    """Validate the final seal and its exact recovery predecessor."""
    validate_value_free_payload(payload)
    if not isinstance(payload, Mapping) or set(payload) != CUTOVER_SEAL_FIELDS:
        raise Phase21ValidationError("cutover seal fields are invalid")
    if payload.get("schema") != CUTOVER_SEAL_SCHEMA:
        raise Phase21ValidationError("cutover seal schema is invalid")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise Phase21ValidationError("cutover seal run identity is invalid")
    requirements = payload.get("requirements")
    prohibitions = payload.get("prohibitions")
    if (
        not isinstance(requirements, Mapping)
        or set(requirements) != CUTOVER_SEAL_REQUIREMENTS
        or any(value is not True for value in requirements.values())
        or not isinstance(prohibitions, Mapping)
        or set(prohibitions) != CUTOVER_SEAL_PROHIBITIONS
        or any(value is not True for value in prohibitions.values())
    ):
        raise Phase21ValidationError("cutover seal gates are not all passing")
    for key in (
        "legacy_client_absent",
        "new_client_live",
        "backup_schedule_live",
    ):
        if payload.get(key) is not True:
            raise Phase21ValidationError("cutover seal gates are not all passing")
    digest = payload.get("recovery_evidence_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise Phase21ValidationError("cutover seal predecessor digest is invalid")
    if recovery_payload is not None:
        recovery = validate_recovery_evidence(recovery_payload)
        if recovery["run_id"] != run_id:
            raise Phase21ValidationError("cutover seal run identity differs")
        expected = recovery_sha256 or hashlib.sha256(
            canonical_json_bytes(recovery)
        ).hexdigest()
        if digest != expected:
            raise Phase21ValidationError("cutover seal predecessor digest differs")
    if payload.get("verdict") != "pass":
        raise Phase21ValidationError("cutover seal verdict is not passing")
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


def validate_phase_artifact_chain(directory: Path) -> dict[str, object]:
    """Validate the committed aggregate chain through its current live stage."""
    if not directory.is_dir():
        raise Phase21ValidationError("evidence chain directory is invalid")
    backup_path = directory / "21-BACKUP-RESTORE-EVIDENCE.json"
    cutover_path = directory / "21-CUTOVER-EVIDENCE.json"
    backup = validate_backup_restore_evidence(_load_json(backup_path))
    cutover = validate_evidence_envelope(_load_json(cutover_path))
    backup_digest = sha256_file(backup_path)
    if (
        cutover.get("stage") != "CLIENT_ADDED"
        or cutover.get("prior_evidence_sha256") != backup_digest
        or not isinstance(cutover.get("input_digests"), Mapping)
        or cutover["input_digests"].get("backup_restore_evidence_sha256")
        != backup_digest
        or cutover.get("verdict") != "pass"
    ):
        raise Phase21ValidationError("cutover evidence predecessor is invalid")
    stage = "CLIENT_ADDED"
    recovery_path = directory / "21-RECOVERY-EVIDENCE.json"
    seal_path = directory / "21-CUTOVER-SEAL.json"
    if recovery_path.exists():
        recovery = validate_recovery_evidence(_load_json(recovery_path))
        if recovery.get("cutover_evidence_sha256") != sha256_file(cutover_path):
            raise Phase21ValidationError("recovery cutover digest differs")
        stage = "RECOVERY_PROVEN"
        if seal_path.exists():
            seal = validate_cutover_seal(
                _load_json(seal_path), recovery_payload=recovery
            )
            if seal.get("recovery_evidence_sha256") != sha256_file(recovery_path):
                raise Phase21ValidationError("seal recovery file digest differs")
            stage = "SEALED"
    elif seal_path.exists():
        raise Phase21ValidationError("cutover seal lacks recovery evidence")
    return {"stage": stage, "verdict": "pass"}


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
            validate_phase_artifact_chain(args.check_chain)
            print("PASS: Phase 21 evidence chain validated")
            return 0
        if not paths:
            raise Phase21ValidationError("evidence input is required")
        payloads = [_load_json(path) for path in paths]
        if (
            len(payloads) == 2
            and payloads[0].get("schema") == RECOVERY_SCHEMA
            and payloads[1].get("schema") == CUTOVER_SEAL_SCHEMA
        ):
            recovery = validate_recovery_evidence(payloads[0])
            validate_cutover_seal(
                payloads[1], recovery_payload=recovery,
                recovery_sha256=sha256_file(paths[0]),
            )
            if payloads[1].get("recovery_evidence_sha256") != sha256_file(paths[0]):
                raise Phase21ValidationError("seal recovery file digest differs")
            print("PASS: Phase 21 recovery and seal chain validated")
            return 0
        if len(payloads) == 1 and args.handoff is None and args.check_chain is None:
            if payloads[0].get("schema") == BACKUP_RESTORE_SCHEMA:
                validate_backup_restore_evidence(payloads[0])
                message = "PASS: Phase 21 backup and restore evidence validated"
            elif payloads[0].get("schema") == RECOVERY_SCHEMA:
                validate_recovery_evidence(payloads[0])
                message = "PASS: Phase 21 recovery evidence validated"
            elif payloads[0].get("schema") == CUTOVER_SEAL_SCHEMA:
                raise Phase21ValidationError(
                    "cutover seal requires paired recovery evidence"
                )
            else:
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
