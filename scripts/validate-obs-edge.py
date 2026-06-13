#!/usr/bin/env python3
"""Offline structural validator for Phase 14 obs-edge bootstrap artifacts.

Checks bootstrap-obs-edge.sh, both nginx vhosts (grafana. and errors.), and
shared systemd artifacts without touching the live VPS.
Every check is an # OFFLINE CHECK — no nginx, certbot, or dig required.
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


def validate_bootstrap_script() -> None:  # OFFLINE CHECK
    """Validate scripts/bootstrap-obs-edge.sh structure and idempotency markers."""
    path = ROOT / "scripts" / "bootstrap-obs-edge.sh"
    require(path.exists(), "scripts/bootstrap-obs-edge.sh missing")

    # Syntax check via bash -n (subprocess, mirrors validate-edge.py pattern)
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        result.returncode == 0,
        f"scripts/bootstrap-obs-edge.sh failed bash -n syntax check: {result.stderr.strip()}",
    )

    content = path.read_text()

    # Safety markers
    require(
        "set -euo pipefail" in content,
        "bootstrap-obs-edge.sh missing 'set -euo pipefail' (project convention)",
    )
    require(
        "exit 64" in content,
        "bootstrap-obs-edge.sh missing 'exit 64' (missing-config exit code, project convention)",
    )

    # Idempotency markers
    require(
        "mkdir -p" in content,
        "bootstrap-obs-edge.sh missing 'mkdir -p' (idempotent directory creation)",
    )
    require(
        "ln -sf" in content,
        "bootstrap-obs-edge.sh missing 'ln -sf' (idempotent symlink creation)",
    )

    # Backup step (backup-before-overwrite)
    has_backup = ".bak" in content or re.search(r"cp.*\.bak|\.bak.*cp", content)
    require(
        has_backup,
        "bootstrap-obs-edge.sh missing backup step (.bak reference for live-vhost backup)",
    )

    # nginx -t gate before reload
    require(
        "nginx -t" in content,
        "bootstrap-obs-edge.sh missing 'nginx -t' gate before reload",
    )

    # ClusterIP discovery via kubectl
    require(
        "kubectl get svc grafana -n monitoring" in content,
        "bootstrap-obs-edge.sh missing 'kubectl get svc grafana -n monitoring' (runtime ClusterIP discovery)",
    )

    # Certbot per-domain issuance
    require(
        "certbot certonly" in content,
        "bootstrap-obs-edge.sh missing 'certbot certonly' (per-domain issuance; full-renew is forbidden)",
    )

    # Lineage guard (skip re-issuance if cert already exists)
    require(
        "letsencrypt/live" in content,
        "bootstrap-obs-edge.sh missing letsencrypt lineage guard 'letsencrypt/live' (SKIP_CERTBOT path, rate-limit safety)",
    )

    # NEGATIVE ASSERT: the certbot full-renew flag must NOT appear as an executed command.
    # This is the VPS-hang anti-pattern (RESEARCH Pitfall 1 / T-14-10 mitigation).
    # NOTE: the literal dangerous flag is intentionally NOT written here — only the
    # combined hyphenated token is checked for absence.
    dangerous_flag = "--" + "full-renew"
    require(
        dangerous_flag not in content,
        "bootstrap-obs-edge.sh must NOT contain the certbot '--full-renew' flag "
        "(VPS-hang anti-pattern, Pitfall 1 — use 'certbot certonly -d <domain>' instead)",
    )

    print("ok: bootstrap-obs-edge.sh structure and idempotency markers")


def validate_grafana_vhost() -> None:  # OFFLINE CHECK
    """Validate config/nginx/sites-available/grafana-stats-staging-solid-stats.conf."""
    vhost_path = (
        ROOT
        / "config"
        / "nginx"
        / "sites-available"
        / "grafana-stats-staging-solid-stats.conf"
    )
    require(
        vhost_path.exists(),
        "config/nginx/sites-available/grafana-stats-staging-solid-stats.conf missing",
    )
    content = vhost_path.read_text()

    # Named upstream block with keepalive
    require(
        "upstream grafana_obs" in content,
        "grafana vhost missing 'upstream grafana_obs' named upstream block",
    )
    require(
        "keepalive" in content,
        "grafana vhost upstream block missing 'keepalive' directive",
    )

    # ACME webroot block
    require(
        "location /.well-known/acme-challenge/" in content,
        "grafana vhost missing 'location /.well-known/acme-challenge/' ACME webroot block",
    )

    # HTTP→HTTPS redirect
    require(
        "return 301" in content,
        "grafana vhost missing 'return 301' HTTP→HTTPS redirect",
    )

    # TLS directives
    require(
        "ssl_certificate" in content,
        "grafana vhost missing 'ssl_certificate' directive",
    )
    require(
        "options-ssl-nginx.conf" in content,
        "grafana vhost missing 'options-ssl-nginx.conf' certbot include",
    )
    require(
        "ssl-dhparams.pem" in content,
        "grafana vhost missing 'ssl-dhparams.pem' certbot DH params",
    )

    # HSTS
    require(
        "Strict-Transport-Security" in content,
        "grafana vhost missing 'Strict-Transport-Security' HSTS header (ASVS V9)",
    )

    # WebSocket upgrade headers (Grafana Live)
    require(
        "proxy_set_header Upgrade" in content,
        "grafana vhost missing 'proxy_set_header Upgrade' (WebSocket upgrade for Grafana Live)",
    )

    # http2 on EVERY 443 listen directive (mirrors validate-edge.py per-listen assertion)
    listen_443 = [
        line for line in content.splitlines() if re.search(r"^\s*listen\b.*\b443\b", line)
    ]
    require(listen_443, "grafana vhost has no 443 listen directive")
    require(
        all("http2" in line for line in listen_443),
        "grafana vhost: every 443 listen directive must include 'http2' "
        "(mirrors validate-edge.py per-listen assertion)",
    )

    # NOT a hardcoded ClusterIP — accept UPSTREAM_PLACEHOLDER token or a 10.x.x.x address.
    # Reject a bare 127.0.0.1-only placeholder (would indicate a broken local-only stub).
    if "127.0.0.1" in content and "UPSTREAM_PLACEHOLDER" not in content:
        # Check that at least one 10.x.x.x address is present alongside 127.0.0.1
        has_clusterip = bool(re.search(r"\b10\.\d+\.\d+\.\d+\b", content))
        require(
            has_clusterip,
            "grafana vhost upstream appears to use bare 127.0.0.1 without a ClusterIP "
            "— must use UPSTREAM_PLACEHOLDER token or a 10.x.x.x ClusterIP address",
        )

    print("ok: grafana vhost structure")


def validate_errors_vhost() -> None:  # OFFLINE CHECK
    """Validate config/nginx/sites-available/errors-stats-staging-solid-stats.conf."""
    vhost_path = (
        ROOT
        / "config"
        / "nginx"
        / "sites-available"
        / "errors-stats-staging-solid-stats.conf"
    )
    require(
        vhost_path.exists(),
        "config/nginx/sites-available/errors-stats-staging-solid-stats.conf missing",
    )
    content = vhost_path.read_text()

    # ACME webroot block
    require(
        "location /.well-known/acme-challenge/" in content,
        "errors vhost missing 'location /.well-known/acme-challenge/' ACME webroot block",
    )

    # HTTP→HTTPS redirect
    require(
        "return 301" in content,
        "errors vhost missing 'return 301' HTTP→HTTPS redirect",
    )

    # Placeholder 503 response
    require(
        "return 503" in content,
        "errors vhost missing 'return 503' (placeholder — no upstream until Phase 16)",
    )

    # Full TLS block
    require(
        "ssl_certificate" in content,
        "errors vhost missing 'ssl_certificate' directive",
    )
    require(
        "options-ssl-nginx.conf" in content,
        "errors vhost missing 'options-ssl-nginx.conf' certbot include",
    )
    require(
        "ssl-dhparams.pem" in content,
        "errors vhost missing 'ssl-dhparams.pem' certbot DH params",
    )
    require(
        "Strict-Transport-Security" in content,
        "errors vhost missing 'Strict-Transport-Security' HSTS header (ASVS V9)",
    )

    # NEGATIVE ASSERT: no proxy_pass (errors. has no upstream until Phase 16)
    require(
        "proxy_pass" not in content,
        "errors vhost must NOT contain 'proxy_pass' — it is a placeholder "
        "(no upstream; Phase 16 wires the GlitchTip ClusterIP)",
    )

    print("ok: errors vhost structure")


def validate_docs_and_shared_artifacts() -> None:  # OFFLINE CHECK
    """Validate docs/obs-edge-bootstrap.md exists and shared Phase 07 systemd artifacts are still present."""
    # Operator runbook (authored in this plan)
    runbook_path = ROOT / "docs" / "obs-edge-bootstrap.md"
    require(
        runbook_path.exists(),
        "docs/obs-edge-bootstrap.md missing (operator runbook for obs-edge bootstrap)",
    )

    # Shared Phase 07 systemd artifacts — obs bootstrap reuses these via idempotent cp
    hook_path = ROOT / "config" / "systemd" / "certbot-deploy-hook.sh"
    dropin_path = ROOT / "config" / "systemd" / "certbot.service.d" / "onfailure.conf"
    failure_svc_path = ROOT / "config" / "systemd" / "certbot-renew-failure.service"

    require(
        hook_path.exists(),
        "config/systemd/certbot-deploy-hook.sh missing (shared Phase 07 deploy hook; obs bootstrap reuses it)",
    )
    require(
        dropin_path.exists(),
        "config/systemd/certbot.service.d/onfailure.conf missing (shared Phase 07 OnFailure drop-in; obs bootstrap reuses it)",
    )
    require(
        failure_svc_path.exists(),
        "config/systemd/certbot-renew-failure.service missing (shared Phase 07 failure handler; obs bootstrap reuses it)",
    )

    print("warn: live nginx -t / dig / curl checks are OPERATOR-ONLY (DNS-gated) — run after DNS propagation")
    print("ok: docs/obs-edge-bootstrap.md and shared systemd artifacts present")


def main() -> int:
    checks = [
        ("bootstrap script", validate_bootstrap_script),
        ("grafana vhost", validate_grafana_vhost),
        ("errors vhost", validate_errors_vhost),
        ("docs and shared artifacts", validate_docs_and_shared_artifacts),
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
