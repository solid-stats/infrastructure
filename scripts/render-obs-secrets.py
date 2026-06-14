#!/usr/bin/env python3
# scripts/render-obs-secrets.py
# Renders observability Secrets from GitHub env secrets into Kubernetes Secret YAML.
# Output is a multi-document YAML covering BOTH the monitoring and error-tracking namespaces.
# Apply with kubectl (no -n flag — each Secret carries its own namespace in metadata):
#   python3 scripts/render-obs-secrets.py | kubectl apply -f -
# Or split by namespace (see deploy-observability.yml) for scoped CI tokens.
# Never committed — values come from env only.
#
# Usage (monitoring secrets only):
#   GRAFANA_ADMIN_PASSWORD=... PG_MONITOR_PASSWORD=... python3 scripts/render-obs-secrets.py
#
# Usage (monitoring + GlitchTip error-tracking secrets):
#   GRAFANA_ADMIN_PASSWORD=... PG_MONITOR_PASSWORD=... \
#   GLITCHTIP_SECRET_KEY=... GLITCHTIP_POSTGRES_PASSWORD=... \
#   GLITCHTIP_SUPERUSER_EMAIL=... GLITCHTIP_SUPERUSER_PASSWORD=... \
#   python3 scripts/render-obs-secrets.py
#
# Exits 64 if any required env var is missing (same convention as render-staging-secrets.py).
# Implements DEP-04: no secret values in git — values come from env only.

import json
import os
import sys
from urllib.parse import quote


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        missing.append(name)
        return ""
    return value


def secret(name: str, namespace: str, values: dict[str, str], secret_type: str = "Opaque") -> str:
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        f"type: {secret_type}",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {namespace}",
        "stringData:",
    ]
    for key, value in values.items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


missing: list[str] = []

# ---------------------------------------------------------------------------
# monitoring namespace — Grafana + postgres-exporter
# ---------------------------------------------------------------------------
grafana_admin_password = required("GRAFANA_ADMIN_PASSWORD")
pg_monitor_password = required("PG_MONITOR_PASSWORD")

# ---------------------------------------------------------------------------
# error-tracking namespace — GlitchTip secrets
# ---------------------------------------------------------------------------
glitchtip_secret_key = required("GLITCHTIP_SECRET_KEY")
glitchtip_postgres_password = required("GLITCHTIP_POSTGRES_PASSWORD")
glitchtip_superuser_email = required("GLITCHTIP_SUPERUSER_EMAIL")
glitchtip_superuser_password = required("GLITCHTIP_SUPERUSER_PASSWORD")

if missing:
    print(f"Missing required environment variables: {', '.join(sorted(set(missing)))}", file=sys.stderr)
    sys.exit(64)

# ---------------------------------------------------------------------------
# monitoring namespace documents
# ---------------------------------------------------------------------------

# Grafana admin Secret — consumed by the Grafana chart via admin.existingSecret +
# userKey/passwordKey. Both keys are required: the chart's env (GF_SECURITY_ADMIN_USER/
# _PASSWORD) and the dashboard-reload sidecar (REQ_USERNAME/REQ_PASSWORD) reference
# admin-user AND admin-password — emitting only admin-password causes the pod to fail
# with CreateContainerConfigError.
grafana_secret = secret(
    "grafana-secrets",
    "monitoring",
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
    "monitoring",
    {"dsn": pg_dsn},
)

# ---------------------------------------------------------------------------
# error-tracking namespace documents — GlitchTip
# ---------------------------------------------------------------------------

# glitchtip-postgres-auth: POSTGRES_PASSWORD consumed by the glitchtip-postgres
# StatefulSet (k8s/observability/90-glitchtip-postgres.yaml).
glitchtip_postgres_auth_secret = secret(
    "glitchtip-postgres-auth",
    "error-tracking",
    {"POSTGRES_PASSWORD": glitchtip_postgres_password},
)

# glitchtip-secrets: consumed by glitchtip-web, glitchtip-worker, migrate Job,
# and seed Job (91–93 manifests). Includes the full DATABASE_URL with url-encoded
# password.
#
# DATABASE_URL sslmode=disable rationale: same as postgres-exporter above —
# the GlitchTip-internal postgres serves no TLS; `prefer` is not supported by
# all Django postgres drivers and would cause a handshake failure. `disable`
# is the correct value for intra-cluster connections until Phase 17 adds
# server-side TLS (then switch to sslmode=require with a mounted CA).
glitchtip_db_url = (
    "postgresql://glitchtip:"
    + quote(glitchtip_postgres_password, safe="")
    + "@glitchtip-postgres.error-tracking.svc:5432/glitchtip?sslmode=disable"
)
glitchtip_secrets = secret(
    "glitchtip-secrets",
    "error-tracking",
    {
        "SECRET_KEY": glitchtip_secret_key,
        "DATABASE_URL": glitchtip_db_url,
        "GLITCHTIP_SUPERUSER_EMAIL": glitchtip_superuser_email,
        "GLITCHTIP_SUPERUSER_PASSWORD": glitchtip_superuser_password,
    },
)

documents = [grafana_secret, pg_secret, glitchtip_postgres_auth_secret, glitchtip_secrets]

print("\n---\n".join(documents))
