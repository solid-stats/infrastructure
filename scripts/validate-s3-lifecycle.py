#!/usr/bin/env python3
"""Offline structural validator for Phase 10 S3 lifecycle retention artifacts.

Checks S3-01 (Expiration rule on backups/postgres/) and S3-02
(AbortIncompleteMultipartUpload rule) without touching the live S3 endpoint.
Every check is an OFFLINE CHECK — no AWS credentials required.
"""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_lifecycle_json() -> None:  # OFFLINE CHECK
    """Validate config/s3/backups-lifecycle.json structure (S3-01, S3-02)."""
    lifecycle_path = ROOT / "config" / "s3" / "backups-lifecycle.json"
    require(lifecycle_path.exists(), "config/s3/backups-lifecycle.json missing")

    content = lifecycle_path.read_text()
    parsed = json.loads(content)

    require(isinstance(parsed, dict), "lifecycle JSON must be a dict")
    require("Rules" in parsed, "lifecycle JSON missing 'Rules' key")
    require(isinstance(parsed["Rules"], list), "Rules must be a list")
    require(len(parsed["Rules"]) > 0, "Rules must be a non-empty list")

    has_expiration = False
    has_abort = False

    for rule in parsed["Rules"]:
        require(isinstance(rule, dict), "each Rule must be a dict")

        # Check for Expiration rule scoped to backups/postgres/
        if (
            isinstance(rule.get("Filter"), dict)
            and rule["Filter"].get("Prefix") == "backups/postgres/"
            and isinstance(rule.get("Expiration"), dict)
        ):
            require(
                rule.get("Status") == "Enabled",
                "Expiration rule for backups/postgres/ must have Status 'Enabled'",
            )
            days = rule["Expiration"].get("Days")
            require(
                isinstance(days, int) and days >= 30,
                f"Expiration.Days must be an integer >= 30, got: {days}",
            )
            has_expiration = True

        # Check for AbortIncompleteMultipartUpload rule
        if "AbortIncompleteMultipartUpload" in rule:
            abort = rule["AbortIncompleteMultipartUpload"]
            require(
                rule.get("Status") == "Enabled",
                "AbortIncompleteMultipartUpload rule must have Status 'Enabled'",
            )
            require(
                isinstance(abort, dict),
                "AbortIncompleteMultipartUpload must be a dict",
            )
            days_init = abort.get("DaysAfterInitiation")
            require(
                isinstance(days_init, int) and days_init >= 1,
                f"AbortIncompleteMultipartUpload.DaysAfterInitiation must be an integer >= 1, got: {days_init}",
            )
            has_abort = True

    require(has_expiration, "missing Expiration rule for backups/postgres/ with Days >= 30")
    require(has_abort, "missing AbortIncompleteMultipartUpload rule with DaysAfterInitiation >= 1")

    print("ok: s3 lifecycle JSON")


def validate_apply_script_syntax() -> None:  # OFFLINE CHECK
    """Validate scripts/apply-s3-lifecycle.sh syntax and required markers."""
    script_path = ROOT / "scripts" / "apply-s3-lifecycle.sh"
    require(script_path.exists(), "scripts/apply-s3-lifecycle.sh missing")

    result = subprocess.run(
        ["bash", "-n", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        result.returncode == 0,
        f"scripts/apply-s3-lifecycle.sh failed bash -n syntax check: {result.stderr.strip()}",
    )

    content = script_path.read_text()
    require(
        "set -euo pipefail" in content,
        "scripts/apply-s3-lifecycle.sh missing 'set -euo pipefail' (project convention)",
    )
    require(
        "exit 64" in content,
        "scripts/apply-s3-lifecycle.sh missing 'exit 64' (missing-config exit code, project convention)",
    )
    require(
        "get-bucket-lifecycle-configuration" in content,
        "scripts/apply-s3-lifecycle.sh missing GET-before-PUT 'get-bucket-lifecycle-configuration'",
    )
    require(
        "put-bucket-lifecycle-configuration" in content,
        "scripts/apply-s3-lifecycle.sh missing 'put-bucket-lifecycle-configuration'",
    )
    require(
        "https://s3.twcstorage.ru" in content,
        "scripts/apply-s3-lifecycle.sh missing endpoint 'https://s3.twcstorage.ru'",
    )
    require(
        "backups-lifecycle.json" in content,
        "scripts/apply-s3-lifecycle.sh missing reference to 'backups-lifecycle.json'",
    )

    print("ok: apply script syntax and markers")


def main() -> int:
    checks = [
        ("s3 lifecycle JSON", validate_lifecycle_json),
        ("apply script syntax and markers", validate_apply_script_syntax),
    ]
    try:
        for _label, check in checks:
            check()
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
