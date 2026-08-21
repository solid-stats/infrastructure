#!/usr/bin/env python3
"""Isolated real-Qdrant checks for the runtime JWT least-privilege matrix."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
OPERATOR_PATH = ROOT / "scripts" / "operate-solidstats-memory.py"
SPEC = importlib.util.spec_from_file_location("memory_operator", OPERATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
OPERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OPERATOR)

QDRANT_IMAGE = (
    "ghcr.io/qdrant/qdrant/qdrant:v1.19.0-unprivileged@"
    "sha256:18a245d16eb663d4f6ad054123371243248d8256a8067f352cd6e88d512fee0b"
)
ADMIN_KEY = "synthetic-qdrant-admin-key"


class RealQdrantJwtContractTests(unittest.TestCase):
    """Prove Qdrant authorizes an alias independently from its target."""

    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is unavailable")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.container = "solidstats-memory-jwt-" + uuid.uuid4().hex[:12]
        started = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--detach",
                "--name",
                cls.container,
                "--publish",
                f"127.0.0.1:{cls.port}:6333",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--env",
                f"QDRANT__SERVICE__API_KEY={ADMIN_KEY}",
                "--env",
                "QDRANT__SERVICE__JWT_RBAC=true",
                QDRANT_IMAGE,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if started.returncode != 0:
            raise unittest.SkipTest("pinned Qdrant image could not start")
        cls.base = f"http://127.0.0.1:{cls.port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if cls.request("GET", "/readyz", ADMIN_KEY)[0] == 200:
                break
            time.sleep(0.25)
        else:
            cls.stop_container()
            raise RuntimeError("pinned Qdrant image did not become ready")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stop_container()

    @classmethod
    def stop_container(cls) -> None:
        container = getattr(cls, "container", "")
        if container:
            subprocess.run(
                ["docker", "rm", "--force", container],
                capture_output=True,
                timeout=20,
                check=False,
            )

    @classmethod
    def request(
        cls, method: str, path: str, token: str, body: object | None = None
    ) -> tuple[int, bytes]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            cls.base + path,
            data=payload,
            method=method,
            headers={"api-key": token, "content-type": "application/json"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            try:
                return error.code, error.read()
            finally:
                error.close()
        except (OSError, URLError):
            return 0, b""

    def test_exact_alias_physical_and_observer_claims(self) -> None:
        physical = "synthetic-physical"
        alias = "synthetic-logical-alias"
        foreign = "synthetic-foreign"
        vectors = {"vectors": {"size": 4, "distance": "Cosine"}}
        self.assertEqual(200, self.request("PUT", f"/collections/{physical}", ADMIN_KEY, vectors)[0])
        self.assertEqual(200, self.request("PUT", f"/collections/{foreign}", ADMIN_KEY, vectors)[0])
        self.assertEqual(
            200,
            self.request(
                "POST",
                "/collections/aliases",
                ADMIN_KEY,
                {"actions": [{"create_alias": {"collection_name": physical, "alias_name": alias}}]},
            )[0],
        )

        alias_token = OPERATOR.qdrant_jwt(
            ADMIN_KEY,
            {"sub": "solidstats-memory-mempalace", "access": [{"collection": alias, "access": "rw"}]},
        )
        backup_token = OPERATOR.qdrant_jwt(
            ADMIN_KEY,
            {"sub": "solidstats-memory-backup", "access": [{"collection": physical, "access": "rw"}]},
        )
        observer_token = OPERATOR.qdrant_jwt(
            ADMIN_KEY,
            {"sub": "solidstats-memory-observer", "access": [{"collection": physical, "access": "r"}]},
        )

        point = {"points": [{"id": 1, "vector": [1, 0, 0, 0]}]}
        self.assertEqual(200, self.request("PUT", f"/collections/{alias}/points?wait=true", alias_token, point)[0])
        self.assertEqual(200, self.request("POST", f"/collections/{alias}/points/scroll", alias_token, {"limit": 1})[0])
        self.assertEqual(403, self.request("GET", f"/collections/{physical}", alias_token)[0])
        self.assertEqual(403, self.request("GET", f"/collections/{foreign}", alias_token)[0])

        self.assertEqual(200, self.request("POST", f"/collections/{physical}/snapshots?wait=true", backup_token)[0])
        self.assertEqual(403, self.request("GET", f"/collections/{alias}", backup_token)[0])
        self.assertEqual(403, self.request("GET", f"/collections/{foreign}", backup_token)[0])

        self.assertEqual(200, self.request("GET", f"/collections/{physical}", observer_token)[0])
        self.assertEqual(403, self.request("PUT", f"/collections/{physical}/points?wait=true", observer_token, point)[0])
        self.assertEqual(403, self.request("GET", f"/collections/{foreign}", observer_token)[0])

        for collection in (physical, alias, foreign):
            self.assertEqual(200, self.request("GET", f"/collections/{collection}", ADMIN_KEY)[0])


if __name__ == "__main__":
    unittest.main()
