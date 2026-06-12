#!/usr/bin/env python3
"""Offline structural validator for Phase 7 edge automation artifacts.

Checks all EDGE-01..05 artifacts without touching the live VPS.
Every check is an # OFFLINE CHECK — no nginx, certbot, or ufw required.
"""
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def validate_nginx_vhost() -> None:  # OFFLINE CHECK
    """Validate config/nginx/sites-available/stats-staging-solid-stats.conf structure."""
    vhost_path = ROOT / "config" / "nginx" / "sites-available" / "stats-staging-solid-stats.conf"
    # D-1: filename must match the live host file exactly
    require(vhost_path.exists(), "config/nginx/sites-available/stats-staging-solid-stats.conf missing")
    content = vhost_path.read_text()

    # a. Named upstream block (D-2, D-3)
    require(
        "upstream solid_stats_staging_server2" in content,
        "vhost missing 'upstream solid_stats_staging_server2' named upstream block",
    )
    # b. Real ClusterIP upstream (D-3); reject 127.0.0.1-only placeholder
    require(
        "10.43.94.103:3000" in content,
        "vhost missing real ClusterIP upstream 10.43.94.103:3000 (D-3)",
    )
    if "127.0.0.1:3000" in content and "10.43.94.103:3000" not in content:
        raise ValidationError(
            "vhost uses greenfield placeholder 127.0.0.1:3000 instead of real ClusterIP 10.43.94.103:3000"
        )
    # c. keepalive in upstream block
    require("keepalive" in content, "vhost upstream block missing keepalive directive")
    # d. proxy_pass to named upstream
    require(
        "proxy_pass http://solid_stats_staging_server2" in content,
        "vhost missing 'proxy_pass http://solid_stats_staging_server2'",
    )
    # e. ACME webroot path
    require(
        "location /.well-known/acme-challenge/" in content,
        "vhost missing 'location /.well-known/acme-challenge/' ACME webroot block",
    )
    # f. HTTP→HTTPS redirect
    require("return 301" in content, "vhost missing HTTP→HTTPS 'return 301' redirect")
    # g. TLS cert reference
    require("ssl_certificate" in content, "vhost missing ssl_certificate directive")
    # h. certbot-managed SSL options include (D-2)
    require(
        "options-ssl-nginx.conf" in content,
        "vhost missing 'include /etc/letsencrypt/options-ssl-nginx.conf' (certbot-managed, D-2)",
    )
    # i. certbot-managed DH params (D-2)
    require(
        "ssl-dhparams.pem" in content,
        "vhost missing ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem (certbot-managed, D-2)",
    )
    # j. HSTS header (ASVS V9)
    require(
        "Strict-Transport-Security" in content,
        "vhost missing Strict-Transport-Security HSTS header (ASVS V9)",
    )
    # k. Phase 11 cutover lever marker (D-2)
    require(
        "# CUTOVER:" in content,
        "vhost missing '# CUTOVER:' comment marker on upstream server line (Phase 11 lever, D-2)",
    )
    # l. http2 on 443 listen directives (FIX 5 — must mirror live vhost exactly)
    has_http2 = bool(re.search(r"listen.*443.*http2", content))
    require(
        has_http2,
        "vhost 443 listen missing http2 — repo copy must mirror live vhost exactly (live: 'listen 443 ssl http2;')",
    )
    print("warn: full nginx -t requires live host — operator must run after bootstrap")
    print("ok: nginx vhost structure")


def validate_shell_scripts() -> None:  # OFFLINE CHECK
    """Validate shell scripts syntax and required markers."""
    for script_name in ["scripts/bootstrap-edge.sh", "scripts/teardown-edge.sh"]:
        path = ROOT / script_name
        require(path.exists(), f"{script_name} missing")
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            result.returncode == 0,
            f"{script_name} failed bash -n syntax check: {result.stderr.strip()}",
        )
        content = path.read_text()
        require(
            "set -euo pipefail" in content,
            f"{script_name} missing 'set -euo pipefail' (project convention)",
        )

    # bootstrap-edge.sh: must have exit 64 for missing-config
    bootstrap_content = (ROOT / "scripts" / "bootstrap-edge.sh").read_text()
    require(
        "exit 64" in bootstrap_content,
        "scripts/bootstrap-edge.sh missing 'exit 64' (missing-config exit code, project convention)",
    )

    # certbot deploy hook
    hook_path = ROOT / "config" / "systemd" / "certbot-deploy-hook.sh"
    require(hook_path.exists(), "config/systemd/certbot-deploy-hook.sh missing")
    result = subprocess.run(
        ["bash", "-n", str(hook_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        result.returncode == 0,
        f"config/systemd/certbot-deploy-hook.sh failed bash -n: {result.stderr.strip()}",
    )
    hook_content = hook_path.read_text()
    require("nginx -t" in hook_content, "certbot-deploy-hook.sh missing 'nginx -t' validation gate")
    require(
        "systemctl reload nginx" in hook_content,
        "certbot-deploy-hook.sh missing 'systemctl reload nginx'",
    )
    print("ok: shell scripts syntax and markers")


def validate_systemd_units() -> None:  # OFFLINE CHECK
    """Validate systemd drop-in and failure-handler units shape (D-4, D-5)."""
    # Phase 7 uses drop-ins, NOT full replacement units (D-4, D-5)
    dropin_path = ROOT / "config" / "systemd" / "certbot.service.d" / "onfailure.conf"
    failure_svc_path = ROOT / "config" / "systemd" / "certbot-renew-failure.service"
    hook_path = ROOT / "config" / "systemd" / "certbot-deploy-hook.sh"

    require(dropin_path.exists(), "config/systemd/certbot.service.d/onfailure.conf missing (OnFailure= drop-in, D-5)")
    require(failure_svc_path.exists(), "config/systemd/certbot-renew-failure.service missing (failure handler, D-5)")
    require(hook_path.exists(), "config/systemd/certbot-deploy-hook.sh missing (deploy hook, D-4)")

    dropin_content = dropin_path.read_text()
    require("[Unit]" in dropin_content, "onfailure.conf missing [Unit] section")
    require(
        "OnFailure=certbot-renew-failure.service" in dropin_content,
        "onfailure.conf missing 'OnFailure=certbot-renew-failure.service'",
    )

    failure_content = failure_svc_path.read_text()
    require("[Unit]" in failure_content, "certbot-renew-failure.service missing [Unit] section")
    require("[Service]" in failure_content, "certbot-renew-failure.service missing [Service] section")
    require("ExecStart=" in failure_content, "certbot-renew-failure.service missing ExecStart=")
    require(
        "logger" in failure_content,
        "certbot-renew-failure.service missing 'logger' (journald logging via logger, D-5)",
    )
    require(
        "user.crit" in failure_content,
        "certbot-renew-failure.service missing 'user.crit' priority (D-5)",
    )
    print("warn: systemd-analyze verify requires live host — operator must run after bootstrap")
    print("ok: systemd units shape")


def validate_bootstrap_idempotency_markers() -> None:  # OFFLINE CHECK
    """Validate bootstrap-edge.sh idempotency and security markers."""
    path = ROOT / "scripts" / "bootstrap-edge.sh"
    require(path.exists(), "scripts/bootstrap-edge.sh missing")
    content = path.read_text()

    require("mkdir -p" in content, "bootstrap-edge.sh missing 'mkdir -p' (idempotent directory creation)")
    require("ln -sf" in content, "bootstrap-edge.sh missing 'ln -sf' (idempotent symlink)")
    # D-8: backup of live vhost before overwrite
    has_backup = "backup" in content or re.search(r"cp.*\.bak", content) or ".bak" in content
    require(
        has_backup,
        "bootstrap-edge.sh missing backup step (backup/cp .bak/.bak, per D-8)",
    )
    # D-7, FIX 4: interface-qualified ufw rule must be exact literal
    require(
        "ufw allow in on wg0 to any port 6443" in content,
        "bootstrap-edge.sh missing exact literal 'ufw allow in on wg0 to any port 6443' "
        "(interface-qualified rule required; bare 'ufw allow 6443' would expose k3s API publicly, D-7)",
    )
    require("ufw allow 80" in content, "bootstrap-edge.sh missing 'ufw allow 80'")
    require("ufw allow 443" in content, "bootstrap-edge.sh missing 'ufw allow 443'")
    require("nginx -t" in content, "bootstrap-edge.sh missing 'nginx -t' syntax gate before reload")
    # D-6, D-8: lineage existence check for skip-issuance guard
    has_lineage_check = "letsencrypt/live/$DOMAIN" in content or "letsencrypt/live" in content
    require(
        has_lineage_check,
        "bootstrap-edge.sh missing lineage existence check (/etc/letsencrypt/live/ guard, D-6, D-8)",
    )
    print("ok: bootstrap idempotency markers")


def validate_teardown_script() -> None:  # OFFLINE CHECK
    """Validate teardown-edge.sh has required cleanup markers."""
    path = ROOT / "scripts" / "teardown-edge.sh"
    require(path.exists(), "scripts/teardown-edge.sh missing")
    content = path.read_text()

    has_removal = "rm -f" in content or "unlink" in content
    require(has_removal, "teardown-edge.sh missing 'rm -f' or 'unlink' (vhost symlink removal)")
    has_restore = "bak" in content or "restore" in content or re.search(r"mv.*bak", content)
    require(
        has_restore,
        "teardown-edge.sh missing restore step (bak/restore/mv .bak, D-8)",
    )
    has_disable = "systemctl disable" in content or re.search(r"rm -f.*certbot", content)
    require(
        has_disable,
        "teardown-edge.sh missing 'systemctl disable' or certbot file removal (timer/drop-in cleanup)",
    )
    require("ufw delete" in content, "teardown-edge.sh missing 'ufw delete' (firewall rule removal)")
    print("ok: teardown script markers")


def main() -> int:
    checks = [
        ("nginx vhost", validate_nginx_vhost),
        ("shell scripts", validate_shell_scripts),
        ("systemd units", validate_systemd_units),
        ("bootstrap idempotency", validate_bootstrap_idempotency_markers),
        ("teardown script", validate_teardown_script),
    ]
    try:
        for _label, check in checks:
            check()
    except (OSError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
