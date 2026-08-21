#!/usr/bin/env python3
"""Offline contract tests for the isolated SolidStats memory runtime."""

from __future__ import annotations

import os
import re
import importlib.util
import base64
import hashlib
import hmac
import io
import json
import shutil
import signal
import subprocess
import tempfile
import tarfile
import time
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-memory.yml"
TUNNEL = ROOT / "scripts" / "ssh-tunnel-up.sh"
MANIFEST_RENDERER = ROOT / "scripts" / "render-memory-manifests.py"
SECRET_RENDERER = ROOT / "scripts" / "render-memory-secrets.py"
VALIDATOR = ROOT / "scripts" / "validate-memory-manifests.py"
BOOTSTRAP_PATH = ROOT / "scripts" / "bootstrap-solidstats-memory-palace.py"
BOOTSTRAP_SPEC = importlib.util.spec_from_file_location(
    "solidstats_memory_runtime_bootstrap", BOOTSTRAP_PATH
)
assert BOOTSTRAP_SPEC and BOOTSTRAP_SPEC.loader
BOOTSTRAP = importlib.util.module_from_spec(BOOTSTRAP_SPEC)
BOOTSTRAP_SPEC.loader.exec_module(BOOTSTRAP)


def synthetic_environment(**values: str) -> dict[str, str]:
    """Use only declared synthetic values for renderer subprocesses."""
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        **values,
    }


class CheckedInMemoryConfigContractTests(unittest.TestCase):
    """Non-secret desired state must remain byte-identical and repository-owned."""

    def render(self, output_dir: Path, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(MANIFEST_RENDERER), str(output_dir)],
            env=synthetic_environment(**environment), text=True,
            capture_output=True, check=False, timeout=10,
        )

    def test_renderer_copies_exact_source_bytes_without_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "rendered"
            rendered = self.render(output_dir)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            source_files = sorted((ROOT / "k8s" / "memory").glob("*.yaml"))
            self.assertEqual([path.name for path in source_files], sorted(path.name for path in output_dir.glob("*.yaml")))
            for source in source_files:
                self.assertEqual(source.read_bytes(), (output_dir / source.name).read_bytes())

            overridden_dir = Path(directory) / "overridden"
            overridden = self.render(
                overridden_dir,
                MEMORY_MEMPALACE_IMAGE="example.invalid/mempalace@sha256:" + "0" * 64,
                MEMORY_QDRANT_PVC_SIZE="999Gi",
                MEMORY_HOST_NGINX_SOURCE_CIDR="203.0.113.0/24",
            )
            self.assertEqual(overridden.returncode, 0, overridden.stderr)
            for source in source_files:
                self.assertEqual((output_dir / source.name).read_bytes(), (overridden_dir / source.name).read_bytes())

    def test_backup_owns_endpoint_and_prefix_without_secret_refs(self) -> None:
        backup = (ROOT / "k8s" / "memory" / "40-backup.yaml").read_text()
        self.assertIn("name: S3_ENDPOINT\n                  value: https://s3.twcstorage.ru", backup)
        self.assertIn("name: S3_PREFIX\n                  value: backups/solidstats-memory/", backup)
        self.assertIn('"s3://${S3_BUCKET}/${S3_PREFIX}${backup_id}/"', backup)
        self.assertNotIn("key: S3_ENDPOINT", backup)
        self.assertNotIn("key: S3_PREFIX", backup)

    def test_mempalace_uses_the_pinned_exact_image_cli_contract(self) -> None:
        documents = list(
            yaml.safe_load_all(
                (ROOT / "k8s" / "memory" / "20-mempalace.yaml").read_text()
            )
        )
        deployment = next(document for document in documents if document["kind"] == "Deployment")
        self.assertEqual(
            "OnRootMismatch",
            deployment["spec"]["template"]["spec"]["securityContext"][
                "fsGroupChangePolicy"
            ],
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        init_container = deployment["spec"]["template"]["spec"]["initContainers"][0]
        embedding_resources = {
            "requests": {"cpu": "250m", "memory": "1Gi"},
            "limits": {"cpu": "1", "memory": "3Gi"},
        }
        self.assertEqual(embedding_resources, init_container["resources"])
        self.assertEqual(embedding_resources, container["resources"])
        self.assertEqual(init_container["name"], "runtime-bootstrap")
        self.assertEqual(
            init_container["image"], "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST"
        )
        self.assertEqual(
            init_container["command"],
            ["python", "/opt/mempalace-bootstrap/bootstrap.py"],
        )
        self.assertEqual(init_container["args"], ["offline"])
        init_env = {entry["name"]: entry for entry in init_container["env"]}
        self.assertEqual(init_env["MEMPALACE_EMBEDDING_MODEL"]["value"], "embeddinggemma")
        self.assertEqual(init_env["MEMPALACE_EMBEDDING_DEVICE"]["value"], "cpu")
        self.assertEqual(init_env["HF_HUB_OFFLINE"]["value"], "1")
        self.assertEqual(
            init_env["HF_HOME"]["value"], "/data/palace/.cache/huggingface"
        )
        self.assertEqual(container["command"], ["mempalace-mcp"])
        self.assertEqual(
            container["args"],
            [
                "--palace",
                "/data/palace",
                "--backend",
                "qdrant",
                "--transport",
                "http",
                "--host",
                "0.0.0.0",
                "--port",
                "8765",
            ],
        )
        main_env = {entry["name"]: entry for entry in container["env"]}
        self.assertEqual(main_env["MEMPALACE_EMBEDDING_MODEL"]["value"], "embeddinggemma")
        self.assertEqual(main_env["HF_HUB_OFFLINE"]["value"], "1")
        volumes = {
            volume["name"]: volume
            for volume in deployment["spec"]["template"]["spec"]["volumes"]
        }
        self.assertEqual(
            volumes["mempalace-bootstrap"]["configMap"],
            {"name": "mempalace-runtime-bootstrap", "defaultMode": 0o444},
        )


class RuntimePalaceBootstrapContractTests(unittest.TestCase):
    class Identity:
        def __init__(self, model_name: str, dimension: int):
            self.model_name = model_name
            self.dimension = dimension

        def __eq__(self, other: object) -> bool:
            return (
                isinstance(other, RuntimePalaceBootstrapContractTests.Identity)
                and (self.model_name, self.dimension)
                == (other.model_name, other.dimension)
            )

    class Result:
        def __init__(self, ids: list[str]):
            self.ids = ids

    class Backend:
        def __init__(self, palace: Path, initial_ids: list[str]):
            self.palace = palace
            self.ids = list(initial_ids)
            self.upserts = 0
            self.deletes = 0
            self.collection = RuntimePalaceBootstrapContractTests.Collection(self)

        def _marker_target(self, reference, config):
            palace_hash = hashlib.sha256(str(self.palace).encode()).hexdigest()[:16]
            return {
                "url": config.url,
                "namespace": config.namespace,
                "palace_hash": palace_hash,
                "remote_prefix": f"mempalace_SolidStats_{palace_hash}",
            }

        def _read_marker(self, _reference):
            return json.loads((self.palace / "qdrant_backend.json").read_text())

        def _validate_marker_target(self, reference, config):
            marker = self._read_marker(reference)
            if marker.get("qdrant") != self._marker_target(reference, config):
                raise ValueError("marker mismatch")

        def _get_embedder_identity(self, _reference, _collection):
            value = json.loads((self.palace / "mempalace_embedder.json").read_text())[
                BOOTSTRAP.COLLECTION
            ]
            return RuntimePalaceBootstrapContractTests.Identity(**value)

        def get_collection(self, **_kwargs):
            return self.collection

    class Collection:
        def __init__(self, backend):
            self.backend = backend

        def count(self):
            return len(self.backend.ids)

        def get(self, *, ids, include):
            return RuntimePalaceBootstrapContractTests.Result(
                [value for value in ids if value in self.backend.ids]
            )

        def upsert(self, *, documents, ids, metadatas, embeddings):
            self.backend.upserts += 1
            self.backend.ids.extend(ids)
            target = self.backend._marker_target(None, self.backend.config)
            marker = {
                "backend": "qdrant",
                "schema_version": 1,
                "created_at": "2026-08-21T00:00:00+00:00",
                "palace_id": str(self.backend.palace),
                "qdrant": target,
            }
            path = self.backend.palace / "qdrant_backend.json"
            path.write_text(json.dumps(marker))
            path.chmod(0o600)

        def delete(self, *, ids):
            self.backend.deletes += 1
            self.backend.ids = [value for value in self.backend.ids if value not in ids]

        def set_embedder_identity(self, identity):
            path = self.backend.palace / "mempalace_embedder.json"
            path.write_text(
                json.dumps(
                    {
                        BOOTSTRAP.COLLECTION: {
                            "model_name": identity.model_name,
                            "dimension": identity.dimension,
                        }
                    }
                )
            )
            path.chmod(0o600)

    class Config:
        url = BOOTSTRAP.QDRANT_URL
        api_key = "synthetic-alias-only-token"
        namespace = BOOTSTRAP.NAMESPACE

    def handles(self, palace: Path, backend):
        backend.config = self.Config()
        reference = object()
        return backend, reference, backend.config, self.Identity

    def test_probe_id_is_a_deterministic_reserved_uuid(self) -> None:
        self.assertEqual(
            "40c30eca-8b79-5d62-a3e2-1f2effc7f84f",
            BOOTSTRAP.PROBE_ID,
        )
        parsed = uuid.UUID(BOOTSTRAP.PROBE_ID)
        self.assertEqual(5, parsed.version)
        self.assertEqual(BOOTSTRAP.PROBE_ID, str(parsed))

    def test_regular_private_normalizes_owned_fs_group_mode_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            marker.write_text("bound\n", encoding="ascii")
            marker.chmod(0o660)

            self.assertTrue(BOOTSTRAP.regular_private(marker))
            self.assertEqual(0o600, marker.lstat().st_mode & 0o777)
            self.assertTrue(BOOTSTRAP.regular_private(marker))
            self.assertEqual(0o600, marker.lstat().st_mode & 0o777)

    def test_regular_private_rejects_wrong_owner_mode_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "marker"
            marker.write_text("bound\n", encoding="ascii")
            marker.chmod(0o660)
            details = marker.lstat()

            for uid, gid, mode in (
                (1001, 1000, 0o660),
                (1000, 1001, 0o660),
                (1000, 1000, 0o640),
                (1000, 1000, 0o600 | 0o100),
            ):
                unsafe = os.stat_result(
                    (
                        (details.st_mode & ~0o777) | mode,
                        details.st_ino,
                        details.st_dev,
                        details.st_nlink,
                        uid,
                        gid,
                        details.st_size,
                        details.st_atime,
                        details.st_mtime,
                        details.st_ctime,
                    )
                )
                with patch.object(BOOTSTRAP.os, "fstat", return_value=unsafe):
                    with self.assertRaises(BOOTSTRAP.BootstrapError):
                        BOOTSTRAP.regular_private(marker)

            link = root / "link"
            link.symlink_to(marker)
            with self.assertRaises(BOOTSTRAP.BootstrapError):
                BOOTSTRAP.regular_private(link)

    @staticmethod
    def cache_archive(*, unsafe_link: bool = False) -> bytes:
        output = io.BytesIO()
        repository = (
            "huggingface/hub/"
            "models--onnx-community--embeddinggemma-300m-ONNX"
        )
        revision = f"{repository}/snapshots/{BOOTSTRAP.MODEL_REVISION}"
        directories = [
            "huggingface",
            "huggingface/hub",
            repository,
            f"{repository}/blobs",
            f"{repository}/snapshots",
            revision,
            f"{revision}/onnx",
            "huggingface/assets",
            "huggingface/xet",
            "huggingface/xet/logs",
            "huggingface/xet/https___cas_serv-tGqkUaZf_CBPHQ6h",
            "huggingface/xet/https___cas_serv-tGqkUaZf_CBPHQ6h/staging",
            "huggingface/hub/.locks",
            "huggingface/hub/.locks/models--onnx-community--embeddinggemma-300m-ONNX",
        ]
        with tarfile.open(fileobj=output, mode="w") as archive:
            for name in directories:
                member = tarfile.TarInfo(name)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            for name in "abcdef":
                payload = name.encode()
                member = tarfile.TarInfo(f"{repository}/blobs/{name}")
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            links = [
                (f"{revision}/onnx/model.onnx", "../../../blobs/a"),
                (f"{revision}/onnx/model.onnx_data", "../../../blobs/b"),
                (
                    f"{revision}/tokenizer.json",
                    "/outside" if unsafe_link else "../../blobs/c",
                ),
            ]
            for name, target in links:
                member = tarfile.TarInfo(name)
                member.type = tarfile.SYMTYPE
                member.linkname = target
                archive.addfile(member)
        return output.getvalue()

    def test_cache_seed_verifies_exact_archive_and_is_idempotent(self) -> None:
        archive = self.cache_archive()
        archive_sha256 = hashlib.sha256(archive).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            palace = Path(directory) / "palace"
            palace.mkdir(mode=0o700)
            with patch.object(
                BOOTSTRAP.sys, "stdin", mock_stdin := unittest.mock.Mock()
            ):
                mock_stdin.buffer = io.BytesIO(archive)
                BOOTSTRAP.seed_cache(palace, archive_sha256, len(archive))
            BOOTSTRAP.cache_ready(palace, archive_sha256)
            marker = (
                palace
                / ".cache"
                / "huggingface"
                / BOOTSTRAP.MODEL_SEED_MARKER
            )
            marker.chmod(0o660)
            BOOTSTRAP.cache_ready(palace, archive_sha256)
            self.assertEqual(0o600, marker.stat().st_mode & 0o777)
            tokenizer = (
                palace
                / ".cache"
                / "huggingface"
                / "hub"
                / "models--onnx-community--embeddinggemma-300m-ONNX"
                / "snapshots"
                / BOOTSTRAP.MODEL_REVISION
                / "tokenizer.json"
            )
            self.assertTrue(tokenizer.is_symlink())
            self.assertEqual("../../blobs/c", os.readlink(tokenizer))

            with patch.object(
                BOOTSTRAP.sys, "stdin", mock_stdin := unittest.mock.Mock()
            ):
                mock_stdin.buffer = io.BytesIO(b"")
                BOOTSTRAP.seed_cache(palace, archive_sha256, len(archive))
            self.assertTrue(tokenizer.is_symlink())

    def test_cache_seed_refuses_escaping_symlink_without_partial_install(self) -> None:
        archive = self.cache_archive(unsafe_link=True)
        with tempfile.TemporaryDirectory() as directory:
            palace = Path(directory) / "palace"
            palace.mkdir(mode=0o700)
            with patch.object(
                BOOTSTRAP.sys, "stdin", mock_stdin := unittest.mock.Mock()
            ):
                mock_stdin.buffer = io.BytesIO(archive)
                with self.assertRaises(BOOTSTRAP.BootstrapError):
                    BOOTSTRAP.seed_cache(
                        palace, hashlib.sha256(archive).hexdigest(), len(archive)
                    )
            self.assertFalse((palace / ".cache" / "huggingface").exists())
            self.assertFalse((palace / ".cache" / "huggingface.seed").exists())

    def test_online_bootstrap_uses_official_write_path_and_leaves_zero_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            palace = Path(directory) / "palace"
            palace.mkdir(mode=0o700)
            backend = self.Backend(palace, ["one", "two", "three"])
            with (
                patch.object(
                    BOOTSTRAP,
                    "backend_handles",
                    return_value=self.handles(palace, backend),
                ),
                patch.object(BOOTSTRAP, "model_vector", return_value=[0.0] * 384),
            ):
                BOOTSTRAP.online_bootstrap(palace, 3)
                self.assertEqual(backend.ids, ["one", "two", "three"])
                self.assertEqual((backend.upserts, backend.deletes), (1, 1))
                for name in ("qdrant_backend.json", "mempalace_embedder.json"):
                    (palace / name).chmod(0o660)
                BOOTSTRAP.online_bootstrap(palace, 3)
            self.assertEqual((backend.upserts, backend.deletes), (1, 1))
            self.assertTrue(
                all(
                    (palace / name).stat().st_mode & 0o777 == 0o600
                    for name in ("qdrant_backend.json", "mempalace_embedder.json")
                )
            )
            marker = json.loads((palace / "qdrant_backend.json").read_text())
            self.assertNotIn("collection_name", marker)
            self.assertEqual(
                json.loads((palace / "mempalace_embedder.json").read_text())[
                    BOOTSTRAP.COLLECTION
                ],
                {"model_name": "embeddinggemma", "dimension": 384},
            )

    def test_online_bootstrap_refuses_count_drift_and_corrupt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            palace = Path(directory) / "palace"
            palace.mkdir(mode=0o700)
            backend = self.Backend(palace, ["one"])
            with patch.object(
                BOOTSTRAP,
                "backend_handles",
                return_value=self.handles(palace, backend),
            ):
                with self.assertRaises(BOOTSTRAP.BootstrapError):
                    BOOTSTRAP.online_bootstrap(palace, 2)
            self.assertEqual((backend.upserts, backend.deletes), (0, 0))

            marker = palace / "qdrant_backend.json"
            marker.write_text('{"backend":"qdrant","collection_name":"physical"}')
            marker.chmod(0o600)
            sidecar = palace / "mempalace_embedder.json"
            sidecar.write_text(
                json.dumps(
                    {
                        BOOTSTRAP.COLLECTION: {
                            "model_name": "embeddinggemma",
                            "dimension": 384,
                        }
                    }
                )
            )
            sidecar.chmod(0o600)
            with patch.object(
                BOOTSTRAP,
                "backend_handles",
                return_value=self.handles(palace, backend),
            ):
                with self.assertRaises(BOOTSTRAP.BootstrapError):
                    BOOTSTRAP.online_bootstrap(palace, 1)

    def test_online_bootstrap_removes_probe_and_new_marker_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            palace = Path(directory) / "palace"
            palace.mkdir(mode=0o700)
            backend = self.Backend(palace, ["one", "two"])
            with (
                patch.object(
                    BOOTSTRAP,
                    "backend_handles",
                    return_value=self.handles(palace, backend),
                ),
                patch.object(BOOTSTRAP, "model_vector", return_value=[0.0] * 384),
                patch.object(
                    backend.collection,
                    "set_embedder_identity",
                    side_effect=RuntimeError("synthetic sidecar failure"),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    BOOTSTRAP.online_bootstrap(palace, 2)

            self.assertEqual(["one", "two"], backend.ids)
            self.assertEqual((backend.upserts, backend.deletes), (1, 1))
            self.assertFalse((palace / "qdrant_backend.json").exists())
            self.assertFalse((palace / "mempalace_embedder.json").exists())

    def test_qdrant_has_a_bounded_writable_snapshot_mount(self) -> None:
        documents = list(
            yaml.safe_load_all(
                (ROOT / "k8s" / "memory" / "10-qdrant.yaml").read_text()
            )
        )
        statefulset = next(
            document for document in documents if document["kind"] == "StatefulSet"
        )
        pod = statefulset["spec"]["template"]["spec"]
        container = pod["containers"][0]
        mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        self.assertEqual("/qdrant/snapshots", mounts["snapshots"]["mountPath"])
        self.assertEqual({"sizeLimit": "1Gi"}, volumes["snapshots"]["emptyDir"])


class MemorySecretRendererContractTests(unittest.TestCase):
    """Secret rendering accepts only the approved secret-input inventory."""

    values = {
        "MEMORY_QDRANT_API_KEY": "synthetic-qdrant-key",
        "MEMORY_QDRANT_COLLECTION": "synthetic-own-collection",
        "MEMORY_QDRANT_LOGICAL_ALIAS": (
            "mempalace_SolidStats_"
            + hashlib.sha256(b"/data/palace").hexdigest()[:16]
            + "_mempalace_drawers"
        ),
        "MEMORY_MCP_HTTP_TOKEN": "synthetic-mcp-token",
        "S3_BUCKET": "synthetic-bucket",
        "S3_ACCESS_KEY_ID": "synthetic-access-key",
        "S3_SECRET_ACCESS_KEY": "synthetic-secret-key",
    }

    def render(self, values: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SECRET_RENDERER)], env=synthetic_environment(**values),
            text=True, capture_output=True, check=False, timeout=10,
        )

    def test_renderer_emits_exact_runtime_secrets(self) -> None:
        rendered = self.render(self.values)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        documents = list(yaml.safe_load_all(rendered.stdout))
        self.assertEqual([document["metadata"]["name"] for document in documents], ["qdrant-runtime", "mempalace-runtime", "memory-backup-runtime", "memory-observer-runtime"])
        self.assertTrue(all(document["metadata"]["namespace"] == "solidstats-memory" for document in documents))
        self.assertEqual(set(documents[0]["stringData"]), {"QDRANT_API_KEY"})
        self.assertEqual(
            set(documents[1]["stringData"]),
            {
                "MEMPALACE_QDRANT_API_KEY",
                "MEMPALACE_MCP_HTTP_TOKEN",
                "SOLIDSTATS_MEMORY_LOGICAL_ALIAS",
                "SOLIDSTATS_MEMORY_PHYSICAL_COLLECTION",
            },
        )
        self.assertEqual(
            documents[1]["stringData"]["SOLIDSTATS_MEMORY_LOGICAL_ALIAS"],
            self.values["MEMORY_QDRANT_LOGICAL_ALIAS"],
        )
        self.assertEqual(
            documents[1]["stringData"]["SOLIDSTATS_MEMORY_PHYSICAL_COLLECTION"],
            self.values["MEMORY_QDRANT_COLLECTION"],
        )
        self.assertEqual(set(documents[2]["stringData"]), {"QDRANT_API_KEY", "S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"})
        self.assertEqual(set(documents[3]["stringData"]), {"QDRANT_API_KEY"})
        self.assertEqual(
            documents[0]["stringData"]["QDRANT_API_KEY"],
            self.values["MEMORY_QDRANT_API_KEY"],
        )
        self.assertNotEqual(
            documents[1]["stringData"]["MEMPALACE_QDRANT_API_KEY"],
            self.values["MEMORY_QDRANT_API_KEY"],
        )
        self.assertNotEqual(
            documents[2]["stringData"]["QDRANT_API_KEY"],
            self.values["MEMORY_QDRANT_API_KEY"],
        )
        self.assertNotIn("S3_ENDPOINT", rendered.stdout)
        self.assertNotIn("S3_PREFIX", rendered.stdout)

    def decode_and_verify(self, token: str) -> dict[str, object]:
        header, payload, signature = token.split(".")
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        expected = hmac.new(
            self.values["MEMORY_QDRANT_API_KEY"].encode(),
            f"{header}.{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        self.assertTrue(hmac.compare_digest(expected, actual))
        return claims

    def test_renderer_signs_least_privilege_qdrant_tokens(self) -> None:
        documents = list(yaml.safe_load_all(self.render(self.values).stdout))
        claims = {
            document["metadata"]["name"]: self.decode_and_verify(
                document["stringData"][
                    "MEMPALACE_QDRANT_API_KEY"
                    if document["metadata"]["name"] == "mempalace-runtime"
                    else "QDRANT_API_KEY"
                ]
            )
            for document in documents[1:]
        }
        self.assertEqual(
            claims["mempalace-runtime"],
            {
                "sub": "solidstats-memory-mempalace",
                "access": [
                    {
                        "collection": self.values["MEMORY_QDRANT_LOGICAL_ALIAS"],
                        "access": "rw",
                    }
                ],
            },
        )
        self.assertEqual(
            claims["memory-backup-runtime"],
            {
                "sub": "solidstats-memory-backup",
                "access": [
                    {
                        "collection": self.values["MEMORY_QDRANT_COLLECTION"],
                        "access": "rw",
                    }
                ],
            },
        )
        self.assertEqual(
            claims["memory-observer-runtime"],
            {
                "sub": "solidstats-memory-observer",
                "access": [
                    {
                        "collection": self.values["MEMORY_QDRANT_COLLECTION"],
                        "access": "r",
                    }
                ],
            },
        )
        self.assertNotEqual(
            self.values["MEMORY_QDRANT_COLLECTION"],
            self.values["MEMORY_QDRANT_LOGICAL_ALIAS"],
        )
        self.assertNotIn("synthetic-foreign-collection", json.dumps(claims))

    def test_missing_input_fails_before_any_yaml_output(self) -> None:
        for missing in self.values:
            values = self.values.copy()
            values.pop(missing)
            rendered = self.render(values)
            self.assertEqual(rendered.returncode, 64)
            self.assertEqual(rendered.stdout, "")

    def test_renderer_rejects_drifting_or_physical_alias_binding(self) -> None:
        for overrides in (
            {"MEMORY_QDRANT_LOGICAL_ALIAS": "drifting-logical-alias"},
            {
                "MEMORY_QDRANT_COLLECTION": self.values[
                    "MEMORY_QDRANT_LOGICAL_ALIAS"
                ]
            },
        ):
            values = self.values | overrides
            rendered = self.render(values)
            self.assertEqual(rendered.returncode, 64)
            self.assertEqual(rendered.stdout, "")


class MemoryDeployWorkflowContractTests(unittest.TestCase):
    """The memory deploy workflow must never widen its bootstrap identity."""

    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text()

    def test_uses_exact_memory_identity_before_any_mutation(self) -> None:
        expected = "system:serviceaccount:solidstats-memory:memory-ci-deployer"
        self.assertIn("secrets.K8S_MEMORY_TOKEN", self.workflow)
        self.assertIn("K8S_USER_NAME: memory-ci-deployer", self.workflow)
        self.assertIn("K8S_CONTEXT_NAME: memory-k3s-staging", self.workflow)
        self.assertIn("kubectl --context memory-k3s-staging auth whoami", self.workflow)
        self.assertIn(expected, self.workflow)
        identity = self.workflow.index("auth whoami")
        boundary = self.workflow.index("Prove exact memory identity and RBAC boundary")
        self.assertLess(identity, boundary + 1000)
        for marker in ("--dry-run=server", "apply --server-side"):
            start = 0
            while True:
                start = self.workflow.find(marker, start)
                if start == -1:
                    break
                self.assertLess(boundary, start, marker)
                self.assertLess(identity, start, marker)
                start += len(marker)

    def test_reuses_an_exclusive_workload_manifest_list(self) -> None:
        self.assertIn("! -name '00-namespace.yaml'", self.workflow)
        self.assertIn("! -name '01-ci-rbac.yaml'", self.workflow)
        self.assertEqual(self.workflow.count("mapfile -t MEMORY_WORKLOAD_FILES"), 2)
        self.assertEqual(self.workflow.count("MEMORY_WORKLOAD_FILES[@]/#/-f"), 2)
        self.assertIn("memory-workload-files", self.workflow)
        self.assertIn("rendered-memory/secrets.yaml", self.workflow)

    def test_fails_closed_on_permission_boundary(self) -> None:
        self.assertIn("for resource in secrets configmaps services deployments.apps", self.workflow)
        self.assertIn("networkpolicies.networking.k8s.io serviceaccounts", self.workflow)
        for command in (
            "auth can-i create namespaces",
            "auth can-i create roles.rbac.authorization.k8s.io",
            "auth can-i create rolebindings.rbac.authorization.k8s.io",
            "create deployments.apps -n solid-stats-staging",
            "create deployments.apps -n monitoring",
        ):
            self.assertIn(command, self.workflow)

    def test_cleans_temporary_credentials_with_managed_tunnel(self) -> None:
        self.assertIn("if: always()", self.workflow)
        self.assertIn("--stop-managed", self.workflow)
        self.assertIn("SSH_TUNNEL_PID_FILE", self.workflow)
        self.assertNotIn("exit 1", self.workflow)
        for forbidden in ("secrets.K8S_TOKEN", "K8S_OBS_TOKEN", "ci-k3s-staging", "obs-k3s-staging"):
            self.assertNotIn(forbidden, self.workflow)

    def test_uses_direct_s3_secrets_without_memory_variables_or_aliases(self) -> None:
        self.assertNotRegex(self.workflow, r"vars\.MEMORY_")
        self.assertNotRegex(self.workflow, r"secrets\.MEMORY_BACKUP_S3_")
        for name in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"):
            self.assertIn(f"secrets.{name}", self.workflow)
        secret_names = set(re.findall(r"secrets\.([A-Z0-9_]+)", self.workflow))
        established = {"DEPLOY_SSH_PRIVATE_KEY", "DEPLOY_SSH_KNOWN_HOSTS", "DEPLOY_SSH_HOST", "DEPLOY_SSH_USER", "K8S_CA_CERT"}
        self.assertEqual(
            secret_names
            - established
            - {"S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"},
            {
                "K8S_MEMORY_TOKEN",
                "MEMORY_QDRANT_API_KEY",
                "MEMORY_QDRANT_COLLECTION",
                "MEMORY_QDRANT_LOGICAL_ALIAS",
                "MEMORY_MCP_HTTP_TOKEN",
            },
        )


class MemoryValidatorContractTests(unittest.TestCase):
    """Validation must reject configuration drift before a cluster mutation."""

    def copied_manifests(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        target = Path(directory.name) / "memory"
        shutil.copytree(ROOT / "k8s" / "memory", target)
        return directory, target

    def validate(self, manifest_dir: Path, placeholders: bool = False) -> subprocess.CompletedProcess[str]:
        command = ["python3", str(VALIDATOR), "--manifest-dir", str(manifest_dir)]
        if placeholders:
            command.append("--allow-operator-placeholders")
        return subprocess.run(command, env=synthetic_environment(), text=True, capture_output=True, check=False, timeout=10)

    def test_source_mode_requires_exact_marker_locations(self) -> None:
        temporary, manifest_dir = self.copied_manifests()
        self.addCleanup(temporary.cleanup)
        backup = manifest_dir / "40-backup.yaml"
        backup.write_text(backup.read_text().replace("MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME", "missing-operator-marker", 1))
        result = self.validate(manifest_dir, placeholders=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("operator placeholders", result.stderr)

    def test_source_mode_rejects_secret_backed_endpoint_or_prefix(self) -> None:
        temporary, manifest_dir = self.copied_manifests()
        self.addCleanup(temporary.cleanup)
        backup = manifest_dir / "40-backup.yaml"
        backup.write_text(
            backup.read_text().replace(
                "name: S3_ENDPOINT\n                  value: https://s3.twcstorage.ru",
                "name: S3_ENDPOINT\n                  valueFrom:\n                    secretKeyRef:\n                      name: memory-backup-runtime\n                      key: S3_ENDPOINT",
            )
        )
        result = self.validate(manifest_dir, placeholders=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("endpoint", result.stderr)

    def test_validator_rejects_broad_or_drifting_mempalace_egress(self) -> None:
        mutations = (
            (
                "source selector",
                "  podSelector:\n    matchLabels:\n      app.kubernetes.io/name: mempalace",
                "  podSelector: {}",
            ),
            (
                "namespace selector",
                "        - podSelector:\n            matchLabels:\n              app.kubernetes.io/name: qdrant",
                "        - namespaceSelector: {}",
            ),
            (
                "CIDR destination",
                "        - podSelector:\n            matchLabels:\n              app.kubernetes.io/name: qdrant",
                "        - ipBlock:\n            cidr: 10.0.0.0/8",
            ),
            (
                "wrong destination label",
                "              app.kubernetes.io/name: qdrant",
                "              app.kubernetes.io/name: other",
            ),
            (
                "extra port",
                "        - protocol: TCP\n          port: 6333",
                "        - protocol: TCP\n          port: 6333\n        - protocol: TCP\n          port: 9999",
            ),
            (
                "wrong direction",
                "  policyTypes: [Egress]",
                "  policyTypes: [Ingress]",
            ),
            (
                "extra destination",
                "      ports:\n        - protocol: TCP",
                "        - podSelector:\n            matchLabels:\n              app: extra\n      ports:\n        - protocol: TCP",
            ),
        )
        for name, original, replacement in mutations:
            with self.subTest(name=name):
                temporary, manifest_dir = self.copied_manifests()
                self.addCleanup(temporary.cleanup)
                policy_path = manifest_dir / "30-network-policy.yaml"
                documents = policy_path.read_text().split("\n---\n")
                index = next(
                    index
                    for index, document in enumerate(documents)
                    if "name: allow-mempalace-qdrant-egress" in document
                )
                self.assertIn(original, documents[index])
                documents[index] = documents[index].replace(original, replacement, 1)
                policy_path.write_text("\n---\n".join(documents))
                result = self.validate(manifest_dir, placeholders=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("MemPalace egress", result.stderr)

    def test_strict_mode_rejects_markers_and_malformed_resolved_values(self) -> None:
        source_result = self.validate(ROOT / "k8s" / "memory")
        self.assertNotEqual(source_result.returncode, 0)
        self.assertIn("unresolved operator", source_result.stderr)

        temporary, manifest_dir = self.copied_manifests()
        self.addCleanup(temporary.cleanup)
        replacements = {
            "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": "example.invalid/mempalace:mutable",
            "MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST": "example.invalid/observer:mutable",
            "MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST": "example.invalid/backup:mutable",
            "MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE": "0Gi",
            "MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE": "not-a-size",
            "MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR": "not-a-cidr",
            "MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR": "also-not-a-cidr",
            "MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME": "Invalid_Collection",
        }
        for path in manifest_dir.glob("*.yaml"):
            text = path.read_text()
            for marker, value in replacements.items():
                text = text.replace(marker, value)
            path.write_text(text)
        result = self.validate(manifest_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr, r"immutable|storage|CIDR|collection")

    def test_strict_mode_accepts_only_well_formed_resolved_values(self) -> None:
        temporary, manifest_dir = self.copied_manifests()
        self.addCleanup(temporary.cleanup)
        replacements = {
            "MEMORY_OPERATOR_SUPPLIED_MEMPALACE_IMAGE_DIGEST": "example.invalid/mempalace@sha256:" + "a" * 64,
            "MEMORY_OPERATOR_SUPPLIED_OBSERVER_IMAGE_DIGEST": "example.invalid/observer@sha256:" + "b" * 64,
            "MEMORY_OPERATOR_SUPPLIED_BACKUP_UPLOADER_IMAGE_DIGEST": "example.invalid/backup@sha256:" + "c" * 64,
            "MEMORY_OPERATOR_MEASURED_QDRANT_PVC_SIZE": "1Gi",
            "MEMORY_OPERATOR_MEASURED_MEMPALACE_PVC_SIZE": "2Gi",
            "MEMORY_OPERATOR_MEASURED_HOST_NGINX_SOURCE_CIDR": "203.0.113.0/24",
            "MEMORY_OPERATOR_APPROVED_BACKUP_S3_CIDR": "198.51.100.0/24",
            "MEMORY_OPERATOR_CONFIRMED_QDRANT_COLLECTION_NAME": "solidstats_memory",
        }
        for path in manifest_dir.glob("*.yaml"):
            text = path.read_text()
            for marker, value in replacements.items():
                text = text.replace(marker, value)
            path.write_text(text)
        result = self.validate(manifest_dir)
        self.assertEqual(result.returncode, 0, result.stderr)


class SshTunnelLifecycleContractTests(unittest.TestCase):
    """Managed tunnel lifecycle must only signal its validated SSH process."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.pid_file = self.work / "tunnel.pid"
        fake_ssh = self.bin_dir / "ssh"
        fake_ssh.write_text(
            "#!/usr/bin/env bash\n"
            "case \" $* \" in *' -fN '*) exit 0 ;; esac\n"
            "exec >/dev/null 2>&1\n"
            "while true; do sleep 1; done\n"
        )
        fake_ssh.chmod(0o755)
        self.env = os.environ | {
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "SSH_TUNNEL_PID_FILE": str(self.pid_file),
            "DEPLOY_SSH_PRIVATE_KEY": "synthetic-key",
            "DEPLOY_SSH_KNOWN_HOSTS": "synthetic-host ssh-ed25519 synthetic",
            "DEPLOY_SSH_HOST": "memory.test",
            "DEPLOY_SSH_USER": "memory-ci",
            "REACHABILITY_TIMEOUT_SECS": "0",
            "SSH_TUNNEL_SKIP_REACHABILITY_CHECK": "1",
        }

    def tearDown(self) -> None:
        if self.pid_file.exists() and self.pid_file.is_file():
            try:
                os.kill(int(self.pid_file.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def run_tunnel(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(TUNNEL), mode], env=self.env, text=True,
            capture_output=True, check=False, timeout=10,
        )

    def stop_process(self, process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)

    def test_start_and_stop_manage_only_the_recorded_process(self) -> None:
        started = self.run_tunnel("--start-managed")
        self.assertEqual(started.returncode, 0, started.stderr)
        pid = int(self.pid_file.read_text().strip())
        os.kill(pid, 0)
        self.assertEqual(self.pid_file.stat().st_mode & 0o777, 0o600)
        stopped = self.run_tunnel("--stop-managed")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertFalse(self.pid_file.exists())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_stop_refuses_mismatched_or_stale_processes(self) -> None:
        unrelated = subprocess.Popen(["sleep", "30"])
        self.addCleanup(self.stop_process, unrelated)
        self.pid_file.write_text(str(unrelated.pid))
        self.pid_file.chmod(0o600)
        rejected = self.run_tunnel("--stop-managed")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIsNone(unrelated.poll())
        unrelated.kill()
        unrelated.wait()
        rejected = self.run_tunnel("--stop-managed")
        self.assertNotEqual(rejected.returncode, 0)

    def test_startup_failure_cleans_the_validated_pidfile(self) -> None:
        failed_env = self.env | {
            "SSH_TUNNEL_SKIP_REACHABILITY_CHECK": "",
            "LOCAL_PORT": "28999",
        }
        failed = subprocess.run(
            ["bash", str(TUNNEL), "--start-managed"], env=failed_env,
            text=True, capture_output=True, check=False, timeout=10,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.pid_file.exists())

    def test_stop_refuses_live_ssh_with_wrong_forward(self) -> None:
        wrong = subprocess.Popen(
            [str(self.bin_dir / "ssh"), "-N", "-L", "127.0.0.1:19999:127.0.0.1:6443", "memory-ci@memory.test"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.stop_process, wrong)
        self.pid_file.write_text(str(wrong.pid))
        self.pid_file.chmod(0o600)
        rejected = self.run_tunnel("--stop-managed")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIsNone(wrong.poll())


class MemoryObserverContractTests(unittest.TestCase):
    @staticmethod
    def memory_network_policies() -> dict[str, dict[str, object]]:
        documents = yaml.safe_load_all((ROOT / "k8s/memory/30-network-policy.yaml").read_text())
        return {
            document["metadata"]["name"]: document
            for document in documents
            if document and document["kind"] == "NetworkPolicy"
        }

    @staticmethod
    def assert_observer_mempalace_ingress(policy: dict[str, object]) -> None:
        expected_spec = {
            "podSelector": {
                "matchLabels": {"app.kubernetes.io/name": "mempalace"},
            },
            "policyTypes": ["Ingress"],
            "ingress": [{
                "from": [{
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "solidstats-memory-observer",
                        },
                    },
                }],
                "ports": [{"protocol": "TCP", "port": 8765}],
            }],
        }
        assert policy["spec"] == expected_spec

    @staticmethod
    def assert_mempalace_qdrant_egress(policy: dict[str, object]) -> None:
        expected_spec = {
            "podSelector": {
                "matchLabels": {"app.kubernetes.io/name": "mempalace"},
            },
            "policyTypes": ["Egress"],
            "egress": [{
                "to": [{
                    "podSelector": {
                        "matchLabels": {"app.kubernetes.io/name": "qdrant"},
                    },
                }],
                "ports": [{"protocol": "TCP", "port": 6333}],
            }],
        }
        assert policy["spec"] == expected_spec

    def test_mempalace_qdrant_policy_is_exact_and_reciprocal(self) -> None:
        policies = self.memory_network_policies()
        egress = policies.get("allow-mempalace-qdrant-egress")
        if egress is None:
            self.fail("MemPalace-to-Qdrant egress policy is absent")
        self.assert_mempalace_qdrant_egress(egress)

        qdrant_ingress = policies["allow-mempalace-to-qdrant"]["spec"]["ingress"]
        self.assertEqual(
            [{"protocol": "TCP", "port": 6333}],
            qdrant_ingress[0]["ports"],
        )
        expected_source = {
            "podSelector": {
                "matchLabels": {"app.kubernetes.io/name": "mempalace"},
            },
        }
        self.assertIn(expected_source, qdrant_ingress[0]["from"])

    def test_mempalace_qdrant_policy_rejects_broad_or_drifting_shapes(self) -> None:
        policy = {
            "spec": {
                "podSelector": {
                    "matchLabels": {"app.kubernetes.io/name": "mempalace"},
                },
                "policyTypes": ["Egress"],
                "egress": [{
                    "to": [{
                        "podSelector": {
                            "matchLabels": {"app.kubernetes.io/name": "qdrant"},
                        },
                    }],
                    "ports": [{"protocol": "TCP", "port": 6333}],
                }],
            },
        }
        mutations = (
            lambda candidate: candidate["spec"].update({"podSelector": {}}),
            lambda candidate: candidate["spec"]["egress"][0]["to"][0].update(
                {"namespaceSelector": {}}
            ),
            lambda candidate: candidate["spec"]["egress"][0]["to"][0].update(
                {"ipBlock": {"cidr": "10.0.0.0/8"}}
            ),
            lambda candidate: candidate["spec"]["egress"][0]["to"][0][
                "podSelector"
            ]["matchLabels"].update({"app.kubernetes.io/name": "other"}),
            lambda candidate: candidate["spec"]["egress"][0]["ports"].append(
                {"protocol": "TCP", "port": 9999}
            ),
            lambda candidate: candidate["spec"].update({"policyTypes": ["Ingress"]}),
            lambda candidate: candidate["spec"]["egress"][0]["to"].append(
                {"podSelector": {"matchLabels": {"app": "extra"}}}
            ),
        )
        for mutate in mutations:
            candidate = deepcopy(policy)
            mutate(candidate)
            with self.subTest(mutate=mutate):
                with self.assertRaises(AssertionError):
                    self.assert_mempalace_qdrant_egress(candidate)

    def test_observer_mempalace_policy_is_exact_and_reciprocal(self) -> None:
        policies = self.memory_network_policies()
        ingress = policies["allow-memory-observer-to-mempalace"]
        self.assert_observer_mempalace_ingress(ingress)

        egress = policies["allow-memory-observer-egress"]["spec"]
        expected_tuple = {
            "to": [{
                "podSelector": {
                    "matchLabels": {"app.kubernetes.io/name": "mempalace"},
                },
            }],
            "ports": [{"protocol": "TCP", "port": 8765}],
        }
        self.assertIn(expected_tuple, egress["egress"])

    def test_observer_mempalace_policy_rejects_broad_or_drifting_shapes(self) -> None:
        policies = self.memory_network_policies()
        ingress = policies.get("allow-memory-observer-to-mempalace")
        if ingress is None:
            self.fail("observer-to-MemPalace ingress policy is absent")

        mutations = (
            lambda policy: policy["spec"].update({"podSelector": {}}),
            lambda policy: policy["spec"]["ingress"][0]["from"][0].update({"namespaceSelector": {}}),
            lambda policy: policy["spec"]["ingress"][0]["from"][0].update({"ipBlock": {"cidr": "10.0.0.0/8"}}),
            lambda policy: policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"].update({"app.kubernetes.io/name": "other"}),
            lambda policy: policy["spec"]["ingress"][0]["ports"].append({"protocol": "TCP", "port": 9999}),
            lambda policy: policy["spec"].update({"policyTypes": ["Egress"]}),
            lambda policy: policy["spec"]["ingress"][0]["from"].append({"podSelector": {"matchLabels": {"app": "extra"}}}),
        )
        for mutate in mutations:
            candidate = yaml.safe_load(yaml.safe_dump(ingress))
            mutate(candidate)
            with self.subTest(mutate=mutate):
                with self.assertRaises(AssertionError):
                    self.assert_observer_mempalace_ingress(candidate)

    def load_observer(self) -> dict[str, object]:
        documents = list(yaml.safe_load_all((ROOT / "k8s/memory/50-monitoring.yaml").read_text()))
        config = next(doc for doc in documents if doc["kind"] == "ConfigMap")
        namespace = {"__name__": "memory_observer_test"}
        exec(config["data"]["exporter.py"], namespace)
        return namespace

    def fake_urlopen(self, responses, requests):
        def open_request(request, timeout):
            requests.append((request.full_url, dict(request.header_items()), timeout))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            status, body = response
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self, _): return body
            result = Response()
            result.status = status
            return result
        return open_request

    def test_healthy_fixture_exports_only_stable_metrics(self) -> None:
        observer = self.load_observer()
        requests = []
        responses = [
            (200, b"{}"), (200, b"{}"),
            (200, b'{"status":"ok","result":{"status":"green","optimizer_status":"ok"}}'),
            (200, b'{"result":[{"creation_time":"2024-01-01T00:00:00Z"}]}'),
        ]
        with patch.dict(os.environ, {"QDRANT_COLLECTION": "private/name", "QDRANT_API_KEY": "secret-value"}):
            observer["urlopen"] = self.fake_urlopen(responses, requests)
            monotonic = iter((1.0, 1.2, 2.0, 2.1, 3.0, 3.1, 4.0, 4.1))
            with patch.object(observer["time"], "monotonic", monotonic.__next__):
                metrics = observer["collect_metrics"]()
        for name in (
            "solidstats_memory_mcp_ready 1", "solidstats_memory_qdrant_ready 1",
            "solidstats_memory_qdrant_collection_healthy 1",
            "solidstats_memory_qdrant_latest_snapshot_timestamp_seconds 1704067200.0",
        ):
            self.assertIn(name, metrics)
        self.assertNotIn("secret-value", metrics)
        self.assertNotIn("private/name", metrics)
        self.assertNotIn("optimizer_status", metrics)
        self.assertEqual(requests[0][1], {})
        self.assertEqual(requests[1][1], {})
        self.assertEqual(requests[2][1]["Api-key"], "secret-value")
        self.assertIn("private%2Fname", requests[2][0])

    def test_unhealthy_malformed_empty_and_timeout_paths_increment_counters(self) -> None:
        observer = self.load_observer()
        requests = []
        responses = [
            observer["URLError"]("timeout"), (500, b"{}"), (200, b"not-json"), (200, b'{"result":[]}'),
        ]
        with patch.dict(os.environ, {"QDRANT_COLLECTION": "collection", "QDRANT_API_KEY": "secret-value"}):
            observer["urlopen"] = self.fake_urlopen(responses, requests)
            monotonic = iter(range(20))
            with patch.object(observer["time"], "monotonic", monotonic.__next__):
                metrics = observer["collect_metrics"]()
        for name in (
            "solidstats_memory_mcp_ready 0", "solidstats_memory_mcp_probe_errors_total 1",
            "solidstats_memory_qdrant_ready 0", "solidstats_memory_qdrant_collection_healthy 0",
            "solidstats_memory_qdrant_probe_errors_total 1", "solidstats_memory_qdrant_latest_snapshot_timestamp_seconds 0",
        ):
            self.assertIn(name, metrics)
        self.assertFalse(observer["parse_collection_health"](b"not-json"))
        self.assertIsNone(observer["latest_snapshot_timestamp"](b"not-json"))
        self.assertEqual(observer["latest_snapshot_timestamp"](b'{"result":[]}'), 0)


class PrometheusMemoryContractTests(unittest.TestCase):
    recording_names = {
        "solidstats_memory:mcp_ready:max",
        "solidstats_memory:mcp_probe_duration_seconds:max",
        "solidstats_memory:mcp_probe_errors:rate5m",
        "solidstats_memory:qdrant_ready:max",
        "solidstats_memory:qdrant_collection_healthy:max",
        "solidstats_memory:qdrant_snapshot_age_seconds:max",
        "solidstats_memory:pvc_capacity_ratio:max",
    }
    alert_names = {
        "SolidStatsMemoryMCPNotReady",
        "SolidStatsMemoryMCPLatencyHigh",
        "SolidStatsMemoryMCPProbeErrors",
        "SolidStatsMemoryQdrantUnhealthy",
        "SolidStatsMemoryQdrantCollectionUnavailable",
        "SolidStatsMemorySnapshotMissingOrStale",
        "SolidStatsMemoryPVCCapacityHigh",
        "SolidStatsMemoryPVCMetricsMissing",
    }

    @staticmethod
    def backup_cronjob_name(documents: list[dict[str, object]]) -> str:
        cronjobs = [
            document
            for document in documents
            if document
            and document.get("kind") == "CronJob"
            and document.get("metadata", {}).get("namespace") == "solidstats-memory"
        ]
        if len(cronjobs) != 1:
            raise AssertionError("expected exactly one SolidStats memory backup CronJob")
        return cronjobs[0]["metadata"]["name"]

    @staticmethod
    def prometheus_server_data(text: str) -> dict[str, str]:
        document = next(
            document
            for document in yaml.safe_load_all(text)
            if document and document.get("kind") == "ConfigMap" and document["metadata"]["name"] == "prometheus-server"
        )
        return document["data"]

    @classmethod
    def rule_names(cls, block: str, declaration: str) -> list[str]:
        rules = yaml.safe_load(block)
        return [
            rule[declaration]
            for group in rules["groups"]
            for rule in group["rules"]
            if declaration in rule
        ]

    @classmethod
    def assert_memory_rule_files(cls, data: dict[str, str], values: dict[str, object]) -> None:
        source_files = values["serverFiles"]
        for key in ("alerting_rules.yml", "recording_rules.yml"):
            if key not in data:
                raise AssertionError(f"missing chart-owned {key}")
            if yaml.safe_load(data[key]) != source_files[key]:
                raise AssertionError(f"{key} differs from authoritative values")
        if set(cls.rule_names(data["alerting_rules.yml"], "alert")) != cls.alert_names:
            raise AssertionError("memory alert names are incomplete or duplicated")
        if set(cls.rule_names(data["recording_rules.yml"], "record")) != cls.recording_names:
            raise AssertionError("memory recording names are incomplete or duplicated")
        for key, block in data.items():
            if key in ("alerting_rules.yml", "recording_rules.yml"):
                continue
            for name in cls.rule_names(block, "alert") if "groups:" in block else []:
                if name in cls.alert_names:
                    raise AssertionError(f"memory alert found in wrong key: {key}")
            for name in cls.rule_names(block, "record") if "groups:" in block else []:
                if name in cls.recording_names:
                    raise AssertionError(f"memory recording found in wrong key: {key}")

    @classmethod
    def snapshot_alert_expression(cls, data: dict[str, str]) -> str:
        rules = yaml.safe_load(data["alerting_rules.yml"])
        alert = next(
            rule
            for group in rules["groups"]
            for rule in group["rules"]
            if rule.get("alert") == "SolidStatsMemorySnapshotMissingOrStale"
        )
        return alert["expr"]

    @staticmethod
    def snapshot_alert_expression_from_values(text: str) -> str:
        values = yaml.safe_load(text)
        rules = values["serverFiles"]["alerting_rules.yml"]
        alert = next(
            rule
            for group in rules["groups"]
            for rule in group["rules"]
            if rule.get("alert") == "SolidStatsMemorySnapshotMissingOrStale"
        )
        return alert["expr"]

    def test_snapshot_gate_tracks_backup_cronjob_manifest(self) -> None:
        backup_documents = list(yaml.safe_load_all((ROOT / "k8s/memory/40-backup.yaml").read_text()))
        cronjob_name = self.backup_cronjob_name(backup_documents)
        expected = (
            'kube_cronjob_spec_suspend{namespace="solidstats-memory",'
            f'cronjob="{cronjob_name}"}} == 0 and '
            "solidstats_memory:qdrant_snapshot_age_seconds:max > 93600"
        )
        values = (ROOT / "k8s/observability/values/prometheus-values.yaml").read_text()
        rendered = self.prometheus_server_data((ROOT / "k8s/observability/10-prometheus.yaml").read_text())
        self.assertEqual(self.snapshot_alert_expression_from_values(values), expected)
        self.assertEqual(self.snapshot_alert_expression(rendered), expected)

    def test_snapshot_gate_rejects_missing_duplicate_and_drifting_cronjobs(self) -> None:
        backup_documents = list(yaml.safe_load_all((ROOT / "k8s/memory/40-backup.yaml").read_text()))
        with self.assertRaises(AssertionError):
            self.backup_cronjob_name([])
        with self.assertRaises(AssertionError):
            self.backup_cronjob_name(backup_documents + backup_documents)

        cronjob_name = self.backup_cronjob_name(backup_documents)
        expected_selector = f'cronjob="{cronjob_name}"'
        values = (ROOT / "k8s/observability/values/prometheus-values.yaml").read_text()
        rendered = self.prometheus_server_data((ROOT / "k8s/observability/10-prometheus.yaml").read_text())
        self.assertIn(expected_selector, self.snapshot_alert_expression_from_values(values))
        self.assertIn(expected_selector, self.snapshot_alert_expression(rendered))
        self.assertNotEqual(
            self.snapshot_alert_expression_from_values(values),
            self.snapshot_alert_expression(rendered).replace(expected_selector, 'cronjob="drift"'),
        )

    def test_values_and_rendered_config_consume_all_memory_signals(self) -> None:
        values = (ROOT / "k8s/observability/values/prometheus-values.yaml").read_text()
        rendered = (ROOT / "k8s/observability/10-prometheus.yaml").read_text()
        values_mapping = yaml.safe_load(values)
        rendered_data = self.prometheus_server_data(rendered)
        self.assert_memory_rule_files(rendered_data, values_mapping)
        recording_rules = (
            "solidstats_memory:mcp_ready:max", "solidstats_memory:mcp_probe_duration_seconds:max",
            "solidstats_memory:mcp_probe_errors:rate5m", "solidstats_memory:qdrant_ready:max",
            "solidstats_memory:qdrant_collection_healthy:max", "solidstats_memory:qdrant_snapshot_age_seconds:max",
            "solidstats_memory:pvc_capacity_ratio:max",
        )
        alerts = (
            "SolidStatsMemoryMCPNotReady", "SolidStatsMemoryMCPLatencyHigh", "SolidStatsMemoryMCPProbeErrors",
            "SolidStatsMemoryQdrantUnhealthy", "SolidStatsMemoryQdrantCollectionUnavailable",
            "SolidStatsMemorySnapshotMissingOrStale", "SolidStatsMemoryPVCCapacityHigh", "SolidStatsMemoryPVCMetricsMissing",
        )
        for text in (values, rendered):
            self.assertIn("solidstats-memory-observer", text)
            self.assertIn("kubernetes-nodes-volume-stats", text)
            self.assertIn("/api/v1/nodes/$1/proxy/metrics", text)
            self.assertIn("bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token", text)
            self.assertIn('namespace="solidstats-memory"', text)
            self.assertIn('persistentvolumeclaim=~"mempalace-data|qdrant-data-qdrant-0"', text)
            for name in recording_rules + alerts:
                self.assertIn(name, text)
        workflow = WORKFLOW.read_text()
        role = (ROOT / "k8s/memory/01-ci-rbac.yaml").read_text()
        for forbidden in ("K8S_OBS_TOKEN", "K8S_OBS_ET_TOKEN", "obs-k3s-staging", "namespace: monitoring"):
            self.assertNotIn(forbidden, workflow)
        self.assertNotIn("monitoring", role)
        self.assertNotIn("ClusterRole", role)

    def test_memory_rule_files_reject_wrong_keys_and_duplicates(self) -> None:
        values = yaml.safe_load((ROOT / "k8s/observability/values/prometheus-values.yaml").read_text())
        data = self.prometheus_server_data((ROOT / "k8s/observability/10-prometheus.yaml").read_text())
        for correct_key, wrong_keys in (
            ("alerting_rules.yml", ("rules", "alerts", "recording_rules.yml", "synthetic.yml")),
            ("recording_rules.yml", ("rules", "alerts", "alerting_rules.yml", "synthetic.yml")),
        ):
            for wrong_key in wrong_keys:
                with self.subTest(correct_key=correct_key, wrong_key=wrong_key):
                    moved = deepcopy(data)
                    moved[wrong_key] = moved.pop(correct_key)
                    with self.assertRaises(AssertionError):
                        self.assert_memory_rule_files(moved, values)
                    duplicated = deepcopy(data)
                    duplicated[wrong_key] = duplicated[correct_key]
                    with self.assertRaises(AssertionError):
                        self.assert_memory_rule_files(duplicated, values)

        missing = deepcopy(data)
        alert_rules = yaml.safe_load(missing["alerting_rules.yml"])
        alert_rules["groups"][0]["rules"].pop()
        missing["alerting_rules.yml"] = yaml.safe_dump(alert_rules, sort_keys=False)
        with self.assertRaises(AssertionError):
            self.assert_memory_rule_files(missing, values)

        duplicate = deepcopy(data)
        recording_rules = yaml.safe_load(duplicate["recording_rules.yml"])
        recording_rules["groups"][0]["rules"].append(
            deepcopy(recording_rules["groups"][0]["rules"][0])
        )
        duplicate["recording_rules.yml"] = yaml.safe_dump(recording_rules, sort_keys=False)
        with self.assertRaises(AssertionError):
            self.assert_memory_rule_files(duplicate, values)

        drifted = deepcopy(data)
        snapshot_rules = yaml.safe_load(drifted["alerting_rules.yml"])
        snapshot = next(
            rule
            for rule in snapshot_rules["groups"][0]["rules"]
            if rule.get("alert") == "SolidStatsMemorySnapshotMissingOrStale"
        )
        snapshot["expr"] = snapshot["expr"].replace(
            'cronjob="solidstats-memory-backup"', 'cronjob="drift"'
        )
        drifted["alerting_rules.yml"] = yaml.safe_dump(snapshot_rules, sort_keys=False)
        with self.assertRaises(AssertionError):
            self.assert_memory_rule_files(drifted, values)

        reordered = deepcopy(data)
        reordered["alerting_rules.yml"] = yaml.safe_dump(
            yaml.safe_load(reordered["alerting_rules.yml"]), sort_keys=True
        )
        self.assert_memory_rule_files(reordered, values)


if __name__ == "__main__":
    unittest.main()
