#!/usr/bin/env python3
# scripts/render-obs-secrets.py
# Renders observability Secrets from GitHub env secrets into Kubernetes Secret YAML.
# Output is piped to `kubectl apply -n monitoring -f -` in CI; never committed.
#
# Usage:
#   GRAFANA_ADMIN_PASSWORD=... PG_MONITOR_PASSWORD=... python3 scripts/render-obs-secrets.py
#
# Exits 64 if any required env var is missing (same convention as render-staging-secrets.py).
# Implements DEP-04: no secret values in git — values come from env only.

import json
import os
import sys
from urllib.parse import quote


NAMESPACE = "monitoring"


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        missing.append(name)
        return ""
    return value


def secret(name: str, values: dict[str, str], secret_type: str = "Opaque") -> str:
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        f"type: {secret_type}",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {NAMESPACE}",
        "stringData:",
    ]
    for key, value in values.items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


missing: list[str] = []

grafana_admin_password = required("GRAFANA_ADMIN_PASSWORD")
pg_monitor_password = required("PG_MONITOR_PASSWORD")

if missing:
    print(f"Missing required environment variables: {', '.join(sorted(set(missing)))}", file=sys.stderr)
    sys.exit(64)

# Grafana admin Secret — consumed by the Grafana chart via admin.existingSecret +
# userKey/passwordKey. Both keys are required: the chart's env (GF_SECURITY_ADMIN_USER/
# _PASSWORD) and the dashboard-reload sidecar (REQ_USERNAME/REQ_PASSWORD) reference
# admin-user AND admin-password — emitting only admin-password causes the pod to fail
# with CreateContainerConfigError.
grafana_secret = secret(
    "grafana-secrets",
    {"admin-user": "admin", "admin-password": grafana_admin_password},
)

# postgres-exporter DSN Secret — consumed by DATA_SOURCE_NAME env var in postgres-exporter.
# Uses the pg_monitor built-in non-superuser role (available since PostgreSQL 10).
# sslmode=disable: the postgres-exporter lib/pq driver only accepts require/verify-full/
# verify-ca/disable (NOT libpq's `prefer`), and the staging postgres serves no TLS, so
# `require`/`verify-*` fail the handshake. `disable` is therefore the only working value here.
# Security tradeoff (accepted): the connection is intra-cluster pod-to-pod on a private overlay
# and gets default-deny NetworkPolicy isolation in Phase 17; enforcing TLS is a follow-up gated
# on configuring postgres server-side TLS (then switch to verify-full with a mounted CA).
pg_dsn = (
    "postgresql://solid_monitor:"
    + quote(pg_monitor_password, safe="")
    + "@postgres.solid-stats-staging.svc:5432/solid_stats?sslmode=disable"
)
pg_secret = secret(
    "postgres-monitor-secret",
    {"dsn": pg_dsn},
)

documents = [grafana_secret, pg_secret]

print("\n---\n".join(documents))
