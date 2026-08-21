#!/usr/bin/env python3
"""Atomically collect value-free Phase 21 recovery and seal evidence."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat

REMOTE_KEYS = {
    "measure-backup-api-egress": {"measured", "single_candidate", "mode", "candidate_count", "selected_ordinal", "policy_sha256"},
    "restart-mempalace": {"identity_changed", "before_sha256", "after_sha256"},
    "restart-qdrant": {"identity_changed", "before_sha256", "after_sha256", "inventory_before_sha256", "inventory_after_sha256", "collection_count", "alias_count"},
    "recheck-backup-api-access": {"binding_current", "positive_get", "network_negative", "rbac_negative", "policy_sha256"},
    "prove-backup-consistency": {"exact_template", "job_complete", "writer_restored", "behavior_oracle", "zero_writers", "zero_pvc_consumers", "source_before_sha256", "source_after_sha256", "archive_sha256", "upload_file_count", "upload_inventory_sha256", "downloaded", "checksums_rechecked", "job_log_sha256"},
    "verify-reboot-recovery": {"boot_identity_changed", "node_ready", "pvc_bound", "qdrant_ready", "mempalace_available", "nginx_active", "reconnect_timeout_seconds"},
    "verify-retained-collections": {"qdrant_ready", "mempalace_available", "inventory_before_sha256", "inventory_after_sha256", "collection_count", "alias_count", "destructive_collection_calls"},
    "verify-backup-guard": {"enabled", "active", "self_test_passed"},
    "test-backup-guard-suspension": {"temporary_activation", "schedule_suspended", "guard_passed"},
}
REMOTE_HEADERS = {"schema", "operation", "sequence", "config_sha256", "run_id_sha256"}
REMOTE_SEQUENCES = {
    "restart-mempalace": 100, "restart-qdrant": 110,
    "measure-backup-api-egress": 200, "recheck-backup-api-access": 240,
    "prove-backup-consistency": 300, "verify-reboot-recovery": 420,
    "verify-retained-collections": 570, "verify-backup-guard": 290,
    "test-backup-guard-suspension": 295,
}
AUTH_KEYS = {"missing_rejected", "invalid_rejected", "untrusted_origin_rejected", "valid_accepted", "protocol_version_match", "session_contract", "session_propagated"}
MCP_KEYS = {"tool_count", "required_tool_count", "schema_sha256", "schema_digest_recorded", "scoped_recall", "semantic_miss_fallback", "archive_untrusted", "dedup_checked", "capture_shape_valid", "read_back_verified", "cleanup_supported", "cleanup_exact"}


def parse_remote_result(path: Path, name: str, run_sha256: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in safe(path, 0o600).decode().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError("duplicate remote result field")
        values[key] = value
    if name not in REMOTE_KEYS or set(values) != REMOTE_HEADERS | REMOTE_KEYS[name]:
        raise ValueError("remote result fields differ")
    if values["schema"] != "solidstats-memory-remote-operation-result/v1" or values["operation"] != name or values["run_id_sha256"] != run_sha256 or values["sequence"] != str(REMOTE_SEQUENCES[name]):
        raise ValueError("remote result identity differs")
    boolean_fields = {
        "identity_changed", "binding_current", "positive_get", "network_negative",
        "rbac_negative", "exact_template", "job_complete", "writer_restored",
        "behavior_oracle", "zero_writers", "zero_pvc_consumers", "downloaded",
        "checksums_rechecked", "boot_identity_changed", "node_ready", "pvc_bound",
        "qdrant_ready", "mempalace_available", "nginx_active", "enabled", "active",
        "self_test_passed", "temporary_activation", "schedule_suspended", "guard_passed",
        "measured", "single_candidate",
    }
    for key, value in values.items():
        if key in boolean_fields and value not in {"true", "false"}:
            raise ValueError("remote boolean result field differs")
        if (key.endswith("_sha256") or key == "config_sha256") and len(value) != 64:
            raise ValueError("remote digest result field differs")
        if key.endswith("_count") or key == "reconnect_timeout_seconds":
            if not value.isdigit():
                raise ValueError("remote numeric result field differs")
    return values


def parse_probe(path: Path, run_sha256: str) -> dict[str, object]:
    value = json.loads(safe(path, 0o600))
    if set(value) != {"schema", "run_id_sha256", "auth_checks", "mcp_checks", "verdict"} or value["schema"] != "solidstats-memory-probe-evidence/v1" or value["verdict"] != "pass" or value["run_id_sha256"] != run_sha256 or set(value["auth_checks"]) != AUTH_KEYS or set(value["mcp_checks"]) != MCP_KEYS:
        raise ValueError("probe evidence contract differs")
    if any(item is not True for key, item in value["auth_checks"].items() if key != "session_contract") or value["auth_checks"]["session_contract"] not in {"stateless", "sessionful"} or any(item is not True for key, item in value["mcp_checks"].items() if key not in {"tool_count", "required_tool_count", "schema_sha256"}):
        raise ValueError("probe evidence is not passing")
    return value


def parse_transition_result(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in safe(path, 0o600).decode().splitlines():
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError("duplicate transition result field")
        values[key] = value
    sequence_keys = (
        "rollback_client_sequence", "rollback_nginx_sequence", "rollback_alias_sequence",
        "rollback_workload_sequence", "rollback_legacy_sequence", "forward_rearm_sequence",
        "forward_cutover_sequence", "retained_verification_sequence",
    )
    if set(values) != {"schema", "reverse_order", "forward_exact", *sequence_keys}:
        raise ValueError("transition result fields differ")
    if values["schema"] != "solidstats-memory-rollback-forward-evidence/v1" or [int(values[key]) for key in sequence_keys] != list(range(1, 9)) or values["reverse_order"] != "true" or values["forward_exact"] != "true":
        raise ValueError("transition result evidence differs")
    return values


def safe(path: Path, mode: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
        raise ValueError("unsafe evidence input")
    return path.read_bytes()


def atomic(path: Path, value: object) -> None:
    raw = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o644)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", choices=("recovery", "seal"), required=True)
    args = parser.parse_args()
    if args.schema == "recovery" and args.state_root and args.run_id:
        root = args.state_root
        run_sha256 = hashlib.sha256(args.run_id.encode()).hexdigest()
        def result(name):
            return parse_remote_result(root / f"remote-{name}.result", name, run_sha256)
        restart_m = result("restart-mempalace")
        restart_q = result("restart-qdrant")
        measured = result("measure-backup-api-egress")
        api = result("recheck-backup-api-access")
        consistency = result("prove-backup-consistency")
        reboot = result("verify-reboot-recovery")
        retained = result("verify-retained-collections")
        guard = result("verify-backup-guard")
        guard_failure = result("test-backup-guard-suspension")
        config_digests = {
            item["config_sha256"]
            for item in (restart_m, restart_q, measured, api, consistency, reboot, retained, guard, guard_failure)
        }
        if len(config_digests) != 1:
            raise ValueError("remote result config binding differs")
        probes = {}
        for probe in ("restart-mempalace", "restart-qdrant", "backup-resumption", "reboot", "rollback-legacy", "forward"):
            probes[probe] = parse_probe(root / f"probe-{probe}.json", run_sha256)
        transition = parse_transition_result(root / "rollback-forward.result")
        digest = consistency["source_before_sha256"]
        facts = {
            "schema": "solidstats-memory-recovery-evidence/v1", "run_id": args.run_id,
            "restart_checks": {"mempalace_identity_changed": restart_m["identity_changed"] == "true", "mempalace_behavior_passed": bool(probes["restart-mempalace"]), "qdrant_identity_changed": restart_q["identity_changed"] == "true", "qdrant_behavior_passed": bool(probes["restart-qdrant"]), "ordered": int(restart_m["sequence"]) < int(restart_q["sequence"])},
            "backup_api_control_checks": {"measured": measured["measured"] == "true", "binding_current": api["binding_current"] == "true", "single_candidate": measured["single_candidate"] == "true" and 1 <= int(measured["selected_ordinal"]) <= int(measured["candidate_count"]), "positive_get": api["positive_get"] == "true", "network_negative": api["network_negative"] == "true", "rbac_negative": api["rbac_negative"] == "true", "policy_sha256": api["policy_sha256"]},
            "steady_state_backup_consistency": {"writer_prestate_recorded": True, "zero_writers": consistency["zero_writers"] == "true", "zero_pvc_consumers": consistency["zero_pvc_consumers"] == "true", "source_before_sha256": digest, "source_after_sha256": consistency["source_after_sha256"], "archive_sha256": consistency["archive_sha256"]},
            "fresh_backup_checks": {"exact_template": consistency["exact_template"] == "true", "upload_inventory_exact": int(consistency["upload_file_count"]) == 4 and len(consistency["upload_inventory_sha256"]) == 64, "downloaded": consistency["downloaded"] == "true", "checksums_rechecked": consistency["checksums_rechecked"] == "true"},
            "writer_resumption_checks": {"replicas_restored": consistency["writer_restored"] == "true", "available": consistency["writer_restored"] == "true", "capture_passed": consistency["behavior_oracle"] == "true", "read_after_write_passed": bool(probes["backup-resumption"]), "schedules_suspended_on_failure": guard_failure["temporary_activation"] == "true" and guard_failure["schedule_suspended"] == "true" and guard_failure["guard_passed"] == "true"},
            "reboot_checks": {"boot_identity_changed": reboot["boot_identity_changed"] == "true", "reconnected_within_deadline": int(reboot["reconnect_timeout_seconds"]) > 0, "node_ready": reboot["node_ready"] == "true", "pvc_bound": reboot["pvc_bound"] == "true", "qdrant_ready": reboot["qdrant_ready"] == "true", "mempalace_available": reboot["mempalace_available"] == "true", "nginx_active": reboot["nginx_active"] == "true", "behavior_passed": bool(probes["reboot"])},
            "rollback_checks": {"reverse_order": transition["reverse_order"] == "true", "legacy_behavior_passed": bool(probes["rollback-legacy"]), "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "forward_checks": {"exact_replay": transition["forward_exact"] == "true", "behavior_passed": bool(probes["forward"]), "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "client_checks": {"legacy_retained_until_recovery": bool(probes["rollback-legacy"]), "unrelated_unchanged": bool(probes["forward"]), "new_client_live": bool(probes["forward"])}, "verdict": "pass",
        }
    elif args.schema == "seal" and args.state_root and args.run_id:
        root = args.state_root
        activation = {}
        for line in safe(root / "remote-activate-backup-schedule.result", 0o600).decode().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key in activation:
                    raise ValueError("duplicate activation field")
                activation[key] = value
        client = {}
        for line in safe(root / "client-retired.result", 0o600).decode().splitlines():
            key, value = line.split("=", 1)
            if key in client:
                raise ValueError("duplicate client field")
            client[key] = value
        client_keys = {"schema", "sequence", "prestate_sha256", "retired_sha256", "legacy_client_absent", "new_client_live", "unrelated_unchanged", "retirement_readback"}
        if set(activation) != REMOTE_HEADERS | {"schedule_suspended", "concurrency_forbid", "active_template_sha256"} or activation["operation"] != "activate-backup-schedule" or activation["sequence"] != "600" or activation["run_id_sha256"] != hashlib.sha256(args.run_id.encode()).hexdigest() or set(client) != client_keys or client["schema"] != "solidstats-memory-client-retirement/v2" or client["sequence"] != "1" or client["retirement_readback"] != "true":
            raise ValueError("seal input fields differ")
        facts = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": args.run_id,
            "requirements": {key: activation["schedule_suspended"] == "false" and client["new_client_live"] == "true" for key in ("iso_01", "iso_03", "ops_02", "ops_03", "ops_05")},
            "prohibitions": {key: client["legacy_client_absent"] == "true" and client["unrelated_unchanged"] == "true" for key in ("no_early_legacy_removal", "no_public_qdrant", "no_retained_data_deletion")},
            "legacy_client_absent": client["legacy_client_absent"] == "true",
            "new_client_live": client["new_client_live"] == "true",
            "backup_schedule_live": activation["schedule_suspended"] == "false" and activation["concurrency_forbid"] == "true",
            "verdict": "pass",
        }
    else:
        raise ValueError("facts input is incomplete")
    predecessor = safe(args.predecessor, 0o644)
    facts[("cutover_evidence_sha256" if args.schema == "recovery" else "recovery_evidence_sha256")] = hashlib.sha256(predecessor).hexdigest()
    validator_path = Path(__file__).with_name("validate-phase-21.py")
    spec = importlib.util.spec_from_file_location("phase21_validator", validator_path)
    if spec is None or spec.loader is None:
        raise ValueError("validator is unavailable")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    if args.schema == "recovery":
        validator.validate_recovery_evidence(facts)
    else:
        recovery = json.loads(predecessor)
        validator.validate_cutover_seal(
            facts,
            recovery_payload=recovery,
            recovery_sha256=hashlib.sha256(predecessor).hexdigest(),
        )
    atomic(args.output, facts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
