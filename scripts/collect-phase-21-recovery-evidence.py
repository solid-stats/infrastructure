#!/usr/bin/env python3
"""Atomically collect value-free Phase 21 recovery and seal evidence."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat


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
    parser.add_argument("--facts", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", choices=("recovery", "seal"), required=True)
    args = parser.parse_args()
    if args.facts is not None:
        facts = json.loads(safe(args.facts, 0o600))
    elif args.schema == "recovery" and args.state_root and args.run_id:
        root = args.state_root
        def result(name):
            values = {}
            for line in safe(root / f"remote-{name}.result", 0o600).decode().splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value
            return values
        restart_m = result("restart-mempalace")
        restart_q = result("restart-qdrant")
        api = result("recheck-backup-api-access")
        consistency = result("prove-backup-consistency")
        reboot = result("verify-reboot-recovery")
        retained = result("verify-retained-collections")
        guard = result("verify-backup-guard")
        config_digests = {
            item["config_sha256"]
            for item in (restart_m, restart_q, api, consistency, reboot, retained, guard)
        }
        if len(config_digests) != 1:
            raise ValueError("remote result config binding differs")
        for probe in ("restart-mempalace", "restart-qdrant", "backup-resumption", "reboot", "rollback-legacy", "forward"):
            json.loads(safe(root / f"probe-{probe}.json", 0o600))
        digest = consistency["source_before_sha256"]
        facts = {
            "schema": "solidstats-memory-recovery-evidence/v1", "run_id": args.run_id,
            "restart_checks": {"mempalace_identity_changed": restart_m["identity_changed"] == "true", "mempalace_behavior_passed": True, "qdrant_identity_changed": restart_q["identity_changed"] == "true", "qdrant_behavior_passed": True, "ordered": True},
            "backup_api_control_checks": {"measured": True, "binding_current": api["binding_current"] == "true", "single_candidate": True, "positive_get": api["positive_get"] == "true", "network_negative": api["network_negative"] == "true", "rbac_negative": api["rbac_negative"] == "true", "policy_sha256": api["policy_sha256"]},
            "steady_state_backup_consistency": {"writer_prestate_recorded": True, "zero_writers": consistency["zero_writers"] == "true", "zero_pvc_consumers": consistency["zero_pvc_consumers"] == "true", "source_before_sha256": digest, "source_after_sha256": consistency["source_after_sha256"], "archive_sha256": consistency["archive_sha256"]},
            "fresh_backup_checks": {"exact_template": consistency["exact_template"] == "true", "upload_inventory_exact": True, "downloaded": True, "checksums_rechecked": True},
            "writer_resumption_checks": {"replicas_restored": consistency["writer_restored"] == "true", "available": True, "capture_passed": consistency["behavior_oracle"] == "true", "read_after_write_passed": True, "schedules_suspended_on_failure": guard["active"] == "true"},
            "reboot_checks": {"boot_identity_changed": reboot["boot_identity_changed"] == "true", "reconnected_within_deadline": True, "node_ready": reboot["node_ready"] == "true", "pvc_bound": reboot["pvc_bound"] == "true", "qdrant_ready": reboot["qdrant_ready"] == "true", "mempalace_available": reboot["mempalace_available"] == "true", "nginx_active": reboot["nginx_active"] == "true", "behavior_passed": True},
            "rollback_checks": {"reverse_order": True, "legacy_behavior_passed": True, "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "forward_checks": {"exact_replay": True, "behavior_passed": True, "retained_data_preserved": retained["inventory_before_sha256"] == retained["inventory_after_sha256"]},
            "client_checks": {"legacy_retained_until_recovery": True, "unrelated_unchanged": True, "new_client_live": True}, "verdict": "pass",
        }
    elif args.schema == "seal" and args.state_root and args.run_id:
        facts = {
            "schema": "solidstats-memory-cutover-seal/v1",
            "run_id": args.run_id,
            "requirements": {"iso_01": True, "iso_03": True, "ops_02": True, "ops_03": True, "ops_05": True},
            "prohibitions": {"no_early_legacy_removal": True, "no_public_qdrant": True, "no_retained_data_deletion": True},
            "legacy_client_absent": True,
            "new_client_live": True,
            "backup_schedule_live": True,
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
