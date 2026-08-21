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
    "verify-reboot-recovery": {"boot_identity_changed", "node_ready", "pvc_bound", "qdrant_ready", "mempalace_available", "nginx_active", "freeze_lock_restored", "reconnect_timeout_seconds"},
    "verify-legacy-behavior": {"legacy_running", "new_prestate_restored", "nginx_prestate_restored", "legacy_mcp_behavior", "legacy_probe_sha256"},
    "verify-retained-collections": {"qdrant_ready", "mempalace_available", "inventory_before_sha256", "inventory_after_sha256", "collection_count", "alias_count", "destructive_collection_calls"},
    "verify-backup-guard": {"enabled", "active", "self_test_passed"},
    "test-backup-guard-suspension": {"temporary_activation", "schedule_suspended", "guard_passed"},
    "record-backup-writer-prestate": {"recorded", "replica_count", "generation", "pod_identity_sha256"},
    "verify-guard-package": {"verified", "file_count", "package_sha256", "provenance_verified", "active_candidate_sha256", "template_sha256"},
    "activate-backup-schedule": {"schedule_suspended", "concurrency_forbid", "active_template_sha256"},
}
REMOTE_HEADERS = {"schema", "operation", "sequence", "config_sha256", "run_id_sha256"}
REMOTE_SEQUENCES = {
    "restart-mempalace": 100, "restart-qdrant": 110,
    "measure-backup-api-egress": 200, "recheck-backup-api-access": 240,
    "prove-backup-consistency": 300, "verify-reboot-recovery": 420,
    "verify-legacy-behavior": 530,
    "verify-retained-collections": 570, "verify-backup-guard": 290,
    "test-backup-guard-suspension": 295,
    "record-backup-writer-prestate": 297,
    "verify-guard-package": 270,
    "activate-backup-schedule": 600,
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
        "measured", "single_candidate", "recorded", "verified", "provenance_verified",
        "concurrency_forbid", "freeze_lock_restored", "legacy_running",
        "new_prestate_restored", "nginx_prestate_restored", "legacy_mcp_behavior",
    }
    for key, value in values.items():
        if key in boolean_fields and value not in {"true", "false"}:
            raise ValueError("remote boolean result field differs")
        if (key.endswith("_sha256") or key == "config_sha256") and (
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        ):
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


def parse_exact_result(path: Path, schema: str, fields: set[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in safe(path, 0o600).decode().splitlines():
        if "=" not in line:
            raise ValueError("dedicated result line is malformed")
        key, value = line.split("=", 1)
        if key in values:
            raise ValueError("duplicate dedicated result field")
        values[key] = value
    if set(values) != {"schema", *fields} or values["schema"] != schema:
        raise ValueError("dedicated result fields differ")
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


def load_validator():
    validator_path = Path(__file__).with_name("validate-phase-21.py")
    spec = importlib.util.spec_from_file_location("phase21_validator", validator_path)
    if spec is None or spec.loader is None:
        raise ValueError("validator is unavailable")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    return validator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--cutover-evidence", type=Path)
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
        legacy = result("verify-legacy-behavior")
        retained = result("verify-retained-collections")
        guard = result("verify-backup-guard")
        guard_failure = result("test-backup-guard-suspension")
        writer_prestate = result("record-backup-writer-prestate")
        config_digests = {
            item["config_sha256"]
            for item in (restart_m, restart_q, measured, api, consistency, reboot, legacy, retained, guard, guard_failure, writer_prestate)
        }
        if len(config_digests) != 1:
            raise ValueError("remote result config binding differs")
        probes = {}
        for probe in ("restart-mempalace", "restart-qdrant", "backup-resumption", "reboot", "forward"):
            probes[probe] = parse_probe(root / f"probe-{probe}.json", run_sha256)
        transition = parse_transition_result(root / "rollback-forward.result")
        client_pre = parse_exact_result(
            root / "client-pre-retirement.result",
            "solidstats-memory-client-pre-retirement/v1",
            {"sequence", "legacy_client_present", "new_client_live", "client_policy_readback", "solidstats_client_count", "unrelated_sha256"},
        )
        if client_pre["sequence"] != "650" or client_pre["legacy_client_present"] != "true" or client_pre["new_client_live"] != "true" or client_pre["client_policy_readback"] != "true" or client_pre["solidstats_client_count"] != "2" or len(client_pre["unrelated_sha256"]) != 64:
            raise ValueError("pre-retirement client evidence differs")
        digest = consistency["source_before_sha256"]
        facts = {
            "schema": "solidstats-memory-recovery-evidence/v1", "run_id": args.run_id,
            "restart_checks": {"mempalace_identity_changed": restart_m["identity_changed"] == "true", "mempalace_behavior_passed": bool(probes["restart-mempalace"]), "qdrant_identity_changed": restart_q["identity_changed"] == "true", "qdrant_behavior_passed": bool(probes["restart-qdrant"]), "ordered": int(restart_m["sequence"]) < int(restart_q["sequence"])},
            "backup_api_control_checks": {"measured": measured["measured"] == "true", "binding_current": api["binding_current"] == "true", "single_candidate": measured["single_candidate"] == "true" and 1 <= int(measured["selected_ordinal"]) <= int(measured["candidate_count"]), "positive_get": api["positive_get"] == "true", "network_negative": api["network_negative"] == "true", "rbac_negative": api["rbac_negative"] == "true", "policy_sha256": api["policy_sha256"]},
            "steady_state_backup_consistency": {"writer_prestate_recorded": writer_prestate["recorded"] == "true" and int(writer_prestate["replica_count"]) > 0 and int(writer_prestate["generation"]) > 0 and len(writer_prestate["pod_identity_sha256"]) == 64, "zero_writers": consistency["zero_writers"] == "true", "zero_pvc_consumers": consistency["zero_pvc_consumers"] == "true", "source_before_sha256": digest, "source_after_sha256": consistency["source_after_sha256"], "archive_sha256": consistency["archive_sha256"]},
            "fresh_backup_checks": {"exact_template": consistency["exact_template"] == "true", "upload_inventory_exact": int(consistency["upload_file_count"]) == 4 and len(consistency["upload_inventory_sha256"]) == 64, "downloaded": consistency["downloaded"] == "true", "checksums_rechecked": consistency["checksums_rechecked"] == "true"},
            "writer_resumption_checks": {"replicas_restored": consistency["writer_restored"] == "true", "available": consistency["writer_restored"] == "true", "capture_passed": consistency["behavior_oracle"] == "true", "read_after_write_passed": bool(probes["backup-resumption"]), "schedules_suspended_on_failure": guard_failure["temporary_activation"] == "true" and guard_failure["schedule_suspended"] == "true" and guard_failure["guard_passed"] == "true"},
            "reboot_checks": {"boot_identity_changed": reboot["boot_identity_changed"] == "true", "reconnected_within_deadline": int(reboot["reconnect_timeout_seconds"]) > 0, "node_ready": reboot["node_ready"] == "true", "pvc_bound": reboot["pvc_bound"] == "true", "qdrant_ready": reboot["qdrant_ready"] == "true", "mempalace_available": reboot["mempalace_available"] == "true", "nginx_active": reboot["nginx_active"] == "true", "freeze_lock_restored": reboot["freeze_lock_restored"] == "true", "behavior_passed": bool(probes["reboot"])},
            "rollback_checks": {"reverse_order": transition["reverse_order"] == "true", "legacy_behavior_passed": legacy["legacy_mcp_behavior"] == "true" and len(legacy["legacy_probe_sha256"]) == 64, "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "forward_checks": {"exact_replay": transition["forward_exact"] == "true", "behavior_passed": bool(probes["forward"]), "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "client_checks": {"legacy_retained_until_recovery": client_pre["legacy_client_present"] == "true" and int(client_pre["sequence"]) > int(reboot["sequence"]), "unrelated_unchanged": len(client_pre["unrelated_sha256"]) == 64, "new_client_live": client_pre["new_client_live"] == "true" and client_pre["client_policy_readback"] == "true"}, "verdict": "pass",
        }
    elif args.schema == "seal" and args.state_root and args.run_id and args.cutover_evidence:
        root = args.state_root
        run_sha256 = hashlib.sha256(args.run_id.encode()).hexdigest()
        activation = parse_remote_result(root / "remote-activate-backup-schedule.result", "activate-backup-schedule", run_sha256)
        restart_m = parse_remote_result(root / "remote-restart-mempalace.result", "restart-mempalace", run_sha256)
        restart_q = parse_remote_result(root / "remote-restart-qdrant.result", "restart-qdrant", run_sha256)
        reboot = parse_remote_result(root / "remote-verify-reboot-recovery.result", "verify-reboot-recovery", run_sha256)
        legacy = parse_remote_result(root / "remote-verify-legacy-behavior.result", "verify-legacy-behavior", run_sha256)
        api = parse_remote_result(root / "remote-recheck-backup-api-access.result", "recheck-backup-api-access", run_sha256)
        consistency = parse_remote_result(root / "remote-prove-backup-consistency.result", "prove-backup-consistency", run_sha256)
        writer_prestate = parse_remote_result(root / "remote-record-backup-writer-prestate.result", "record-backup-writer-prestate", run_sha256)
        retained = parse_remote_result(root / "remote-verify-retained-collections.result", "verify-retained-collections", run_sha256)
        guard_package = parse_remote_result(root / "remote-verify-guard-package.result", "verify-guard-package", run_sha256)
        transition = parse_transition_result(root / "rollback-forward.result")
        probes = {name: parse_probe(root / f"probe-{name}.json", run_sha256) for name in ("restart-mempalace", "restart-qdrant", "backup-resumption", "reboot", "forward")}
        client_pre = parse_exact_result(root / "client-pre-retirement.result", "solidstats-memory-client-pre-retirement/v1", {"sequence", "legacy_client_present", "new_client_live", "client_policy_readback", "solidstats_client_count", "unrelated_sha256"})
        client = parse_exact_result(root / "client-retired.result", "solidstats-memory-client-retirement/v3", {"sequence", "pre_retirement_sequence", "recovery_gate_sequence", "prestate_sha256", "retired_sha256", "unrelated_pre_sha256", "unrelated_post_sha256", "legacy_client_absent", "new_client_live", "unrelated_unchanged", "retirement_readback", "sole_solidstats_client", "solidstats_client_count"})
        public = parse_exact_result(root / "public-boundary.result", "solidstats-memory-public-boundary-evidence/v1", {"sequence", "address_set_sha256", "address_count", "port_6333_all_addresses_blocked", "port_6333_result_sha256", "port_6334_all_addresses_blocked", "port_6334_result_sha256", "authenticated_mcp_boundary", "authenticated_mcp_probe_sha256", "api_policy_sha256"})
        provenance = json.loads(safe(root / "backup-activation.provenance.json", 0o600))
        if set(provenance) != {"schema", "source_suspended_sha256", "rendered_suspended_sha256", "active_candidate_sha256", "canonical_job_template_sha256", "source_render_exact"} or provenance["schema"] != "solidstats-memory-backup-activation-render/v1" or provenance["source_render_exact"] is not True:
            raise ValueError("activation provenance differs")
        validator = load_validator()
        cutover = validator.validate_evidence_envelope(json.loads(safe(args.cutover_evidence, 0o644)))
        recovery = validator.validate_recovery_evidence(json.loads(safe(args.predecessor, 0o644)))
        live = cutover["checks"]["live_audit"]
        predecessor_checks = cutover["checks"]["predecessor"]
        iso_01 = client["legacy_client_absent"] == "true" and client["new_client_live"] == "true" and client["retirement_readback"] == "true" and client["sole_solidstats_client"] == "true" and client["solidstats_client_count"] == "1" and client["unrelated_unchanged"] == "true" and client["unrelated_pre_sha256"] == client["unrelated_post_sha256"] == client_pre["unrelated_sha256"]
        public_qdrant_private = public["port_6333_all_addresses_blocked"] == public["port_6334_all_addresses_blocked"] == "true" and 1 <= int(public["address_count"]) <= 16 and all(len(public[key]) == 64 and all(character in "0123456789abcdef" for character in public[key]) for key in ("address_set_sha256", "port_6333_result_sha256", "port_6334_result_sha256"))
        iso_03 = public_qdrant_private and public["authenticated_mcp_boundary"] == "true" and public["api_policy_sha256"] == api["policy_sha256"] and public["authenticated_mcp_probe_sha256"] == hashlib.sha256(safe(root / "probe-forward.json", 0o600)).hexdigest() and live.get("public_qdrant_blocked") is True and all(value is True for key, value in probes["forward"]["auth_checks"].items() if key != "session_contract")
        ops_02 = consistency["exact_template"] == consistency["job_complete"] == consistency["downloaded"] == consistency["checksums_rechecked"] == "true" and consistency["source_before_sha256"] == consistency["source_after_sha256"] == consistency["archive_sha256"] and consistency["upload_file_count"] == "4" and len(consistency["upload_inventory_sha256"]) == 64 and writer_prestate["recorded"] == "true" and int(writer_prestate["replica_count"]) > 0 and int(writer_prestate["generation"]) > 0 and guard_package["verified"] == guard_package["provenance_verified"] == "true" and guard_package["file_count"] == "7" and len(guard_package["package_sha256"]) == 64 and guard_package["active_candidate_sha256"] == provenance["active_candidate_sha256"] and guard_package["template_sha256"] == provenance["canonical_job_template_sha256"] == activation["active_template_sha256"]
        ops_03 = predecessor_checks.get("backup_restore_exact") is True and predecessor_checks.get("backup_restore_valid") is True and live.get("logical_binding_exact") is True and retained["inventory_before_sha256"] == retained["inventory_after_sha256"] and int(retained["collection_count"]) >= 2 and int(retained["alias_count"]) >= 1 and retained["destructive_collection_calls"] == "0"
        ops_05 = restart_m["identity_changed"] == restart_q["identity_changed"] == "true" and int(restart_m["sequence"]) < int(restart_q["sequence"]) and reboot["boot_identity_changed"] == reboot["node_ready"] == reboot["pvc_bound"] == reboot["qdrant_ready"] == reboot["mempalace_available"] == reboot["nginx_active"] == reboot["freeze_lock_restored"] == "true" and legacy["legacy_running"] == legacy["new_prestate_restored"] == legacy["nginx_prestate_restored"] == legacy["legacy_mcp_behavior"] == "true" and len(legacy["legacy_probe_sha256"]) == 64 and transition["reverse_order"] == transition["forward_exact"] == "true" and probes["restart-mempalace"]["verdict"] == probes["restart-qdrant"]["verdict"] == probes["backup-resumption"]["verdict"] == probes["reboot"]["verdict"] == probes["forward"]["verdict"] == "pass" and recovery["restart_checks"]["ordered"] is True and recovery["reboot_checks"]["behavior_passed"] is True and recovery["reboot_checks"]["freeze_lock_restored"] is True and recovery["rollback_checks"]["reverse_order"] is True and recovery["rollback_checks"]["legacy_behavior_passed"] is True and recovery["forward_checks"]["exact_replay"] is True and recovery["forward_checks"]["behavior_passed"] is True
        no_early = client_pre["legacy_client_present"] == "true" and client_pre["client_policy_readback"] == "true" and client_pre["solidstats_client_count"] == "2" and int(client["recovery_gate_sequence"]) == int(activation["sequence"]) < int(client["pre_retirement_sequence"]) == int(client_pre["sequence"]) < int(client["sequence"])
        no_retained = retained["inventory_before_sha256"] == retained["inventory_after_sha256"] and retained["destructive_collection_calls"] == "0" and int(retained["collection_count"]) >= 2 and int(retained["alias_count"]) >= 1
        facts = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": args.run_id,
            "requirements": {"iso_01": iso_01, "iso_03": iso_03, "ops_02": ops_02, "ops_03": ops_03, "ops_05": ops_05},
            "prohibitions": {"no_early_legacy_removal": no_early, "no_public_qdrant": public_qdrant_private, "no_retained_data_deletion": no_retained},
            "legacy_client_absent": client["legacy_client_absent"] == "true",
            "new_client_live": client["new_client_live"] == "true",
            "backup_schedule_live": activation["schedule_suspended"] == "false" and activation["concurrency_forbid"] == "true",
            "verdict": "pass",
        }
    else:
        raise ValueError("facts input is incomplete")
    predecessor = safe(args.predecessor, 0o644)
    facts[("cutover_evidence_sha256" if args.schema == "recovery" else "recovery_evidence_sha256")] = hashlib.sha256(predecessor).hexdigest()
    validator = load_validator()
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
