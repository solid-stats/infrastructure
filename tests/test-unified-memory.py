#!/usr/bin/env python3
"""Behavioral synthetic package and manifest contracts, without live services."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import unified_memory_recovery as recovery


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


renderer = load("renderer", "render-unified-memory.py")
bootstrap = load("bootstrap", "bootstrap-unified-memory.py")
IMAGE = "ghcr.io/mempalace/mempalace@sha256:" + "a" * 64


class FakeQdrant:
    def __init__(self, rows):
        self.collections = {row["physical"]: {"size": row["dimension"], "distance": row["distance"]} for row in rows}
        self.aliases = [{"alias_name": row["alias"], "collection_name": row["physical"]} for row in rows]
        self.recovered = []
        self.deleted = []

    def call(self, method, path, body=None, output=None):
        if method == "DELETE":
            self.deleted.append(path)
            return True
        if path == "/collections":
            return {"collections": [{"name": name} for name in sorted(self.collections)]}
        if path == "/aliases":
            return {"aliases": copy.deepcopy(self.aliases)}
        name = path.split("/")[2]
        if output is not None:
            Path(output).write_text(json.dumps(self.collections[name]))
            return
        if path.endswith("/snapshots"):
            return {"name": "snapshot.file"}
        return {"config": {"params": {"vectors": self.collections[name]}}}

    def fingerprint(self, name):
        return {"count": 2, "sha256": "a" * 64}

    def recover(self, name, snapshot):
        self.collections[name] = json.loads(Path(snapshot).read_text())
        self.recovered.append(name)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "source"
        self.state.mkdir()
        (self.state / "tunnels.json").write_text('{"preserved":true}')
        palace = self.state / "palace"
        palace.mkdir()
        db = sqlite3.connect(palace / "knowledge.db")
        db.execute("CREATE TABLE facts (value TEXT)")
        db.execute("INSERT INTO facts VALUES ('synthetic')")
        db.commit()
        db.close()
        self.config = json.loads((ROOT / "k8s/unified-memory/inputs.example.json").read_text())
        self.client = FakeQdrant(self.config["collections"])
        self.package = self.root / "package"
        recovery.backup(self.client, self.config, self.state, self.package)

    def tearDown(self):
        self.temporary.cleanup()

    def test_all_collections_and_sibling_state_survive_isolated_restore(self):
        before = copy.deepcopy(self.client.aliases)
        targets = {row["physical"]: "restored-" + str(i) for i, row in enumerate(self.config["collections"])}
        result = recovery.restore(self.client, self.package, targets, {"solidstats-protected"}, self.root / "restored")
        self.assertEqual(2, result["restored"])
        self.assertEqual(before, self.client.aliases)
        self.assertEqual(recovery.tree_digest(self.state), recovery.tree_digest(self.root / "restored/palace"))
        self.assertEqual(recovery.sqlite_checks(self.state), recovery.sqlite_checks(self.root / "restored/palace"))

    def test_corrupt_snapshot_fails_before_any_restore_mutation(self):
        (self.package / "collection-0.snapshot").write_text("corrupt")
        with self.assertRaises(ValueError):
            recovery.restore(self.client, self.package, {"one": "two"}, {"solidstats-protected"}, self.root / "restored")
        self.assertEqual([], self.client.recovered)

    def test_incomplete_inventory_and_missing_completion_rejected(self):
        (self.package / "COMPLETE.json").unlink()
        with self.assertRaises(FileNotFoundError):
            recovery.validate_package(self.package, require_complete=True)
        (self.package / "collection-1.snapshot").unlink()
        with self.assertRaises(ValueError):
            recovery.validate_package(self.package)

    def test_every_existing_collection_and_alias_is_protected(self):
        targets = {row["physical"]: "absent-" + str(i) for i, row in enumerate(self.config["collections"])}
        for forbidden in (self.config["collections"][0]["physical"], self.config["collections"][0]["alias"], "solidstats-reserved"):
            altered = dict(targets)
            altered[next(iter(altered))] = forbidden
            with self.subTest(target=forbidden), self.assertRaises(ValueError):
                recovery.restore(self.client, self.package, altered, {"solidstats-reserved"}, self.root / "restored")
        self.assertEqual([], self.client.recovered)

    def test_partial_collection_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            recovery.restore(self.client, self.package, {self.config["collections"][0]["physical"]: "one"}, {"protected"}, self.root / "restored")

    def test_traversal_and_link_archives_rejected(self):
        archive = self.root / "unsafe.tar"
        with tarfile.open(archive, "w") as stream:
            member = tarfile.TarInfo("palace/../../escape")
            member.size = 0
            stream.addfile(member)
        with self.assertRaises(ValueError):
            recovery.extract_state(archive, self.root / "unsafe-output")

    def test_publication_marker_is_uploaded_only_after_verified_members(self):
        events = []
        source = self.package
        class ObjectStore(recovery.S3):
            def __init__(self):
                pass
            def transfer(self, method, name, path):
                events.append((method, name))
                if method == "GET":
                    Path(path).write_bytes((source / name).read_bytes())
        ObjectStore().publish(self.package)
        self.assertEqual(("PUT", "COMPLETE.json"), events[-2])
        self.assertEqual(("GET", "COMPLETE.json"), events[-1])
        for index, event in enumerate(events[:-2]):
            self.assertNotEqual("COMPLETE.json", event[1])
        class Corrupt(ObjectStore):
            def transfer(self, method, name, path):
                super().transfer(method, name, path)
                if method == "GET":
                    Path(path).write_bytes(b"corrupt")
        events.clear()
        with self.assertRaises(ValueError):
            Corrupt().publish(self.package)
        self.assertNotIn(("PUT", "COMPLETE.json"), events)


    def test_drawers_only_backup_cannot_claim_complete_recovery(self):
        incomplete = copy.deepcopy(self.config)
        incomplete["collections"] = incomplete["collections"][:1]
        with self.assertRaises(ValueError):
            recovery.backup(self.client, incomplete, self.state, self.root / "incomplete")
        self.assertFalse((self.root / "incomplete" / "COMPLETE.json").exists())

    def test_transient_snapshots_are_cleaned_on_success_and_failed_download(self):
        self.assertEqual(2, len(self.client.deleted))
        original = self.client.call
        def failing(method, path, body=None, output=None):
            if output is not None:
                raise ValueError("synthetic failed download")
            return original(method, path, body, output)
        self.client.call = failing
        with self.assertRaises(ValueError):
            recovery.backup(self.client, self.config, self.state, self.root / "failed-download")
        self.assertEqual(3, len(self.client.deleted))
        self.assertFalse((self.root / "failed-download" / "COMPLETE.json").exists())

    def test_expanded_archive_capacity_checked_before_extract_and_compression_rejected(self):
        plain = self.package / "local-state.tar"
        with mock.patch.object(recovery.shutil, "disk_usage", return_value=mock.Mock(free=0)) as capacity:
            with self.assertRaises(ValueError):
                recovery.extract_state(plain, self.root / "no-capacity")
            capacity.assert_called_once_with(self.root)
        self.assertFalse((self.root / "no-capacity").exists())
        compressed = self.root / "compressed.tar.gz"
        with tarfile.open(compressed, "w:gz") as archive:
            archive.add(self.state, arcname="palace")
        with self.assertRaises(tarfile.ReadError):
            recovery.extract_state(compressed, self.root / "compressed-output")

    def test_actual_backup_cli_rejects_low_scratch_before_snapshot_creation(self):
        config_path = self.root / "bindings.json"
        config_path.write_text(json.dumps(self.config))
        argv = ["recovery", "backup", "--bindings", str(config_path), "--palace", str(self.state),
                "--package", str(self.root / "scratch-failure"), "--qdrant-url", "http://127.0.0.1:1"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.dict(os.environ, {"UNIFIED_WRITERS_QUIESCED": "1", "QDRANT_API_KEY": "synthetic"}), \
             mock.patch.object(recovery.shutil, "disk_usage", return_value=mock.Mock(free=0)), \
             mock.patch.object(recovery, "backup") as create:
            with self.assertRaises(ValueError):
                recovery.main()
        create.assert_not_called()

    def test_retention_keeps_all_recent_days_and_deletes_only_verified_old_complete_points(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        source = {path.name: path.read_bytes() for path in self.package.iterdir()}
        class Store(recovery.S3):
            def __init__(self):
                self.prefix = "backups/unified-memory/"
                self.data, self.times, self.deletes = {}, {}, []
                for index, age in enumerate([0] * 35 + [29, 31, 32]):
                    for name, content in source.items():
                        key = self.prefix + "point-" + str(index) + "/" + name
                        self.data[key], self.times[key] = content, now - timedelta(days=age)
                self.data[self.prefix + "incomplete-old/manifest.json"] = b"incomplete"
                self.times[self.prefix + "incomplete-old/manifest.json"] = now - timedelta(days=60)
            def require_unversioned(self):
                pass
            def objects(self):
                return [{"key": key, "size": len(value), "modified": self.times[key]} for key, value in self.data.items()]
            def transfer(self, method, name, path, **kwargs):
                key = self.prefix + name
                if method == "GET":
                    Path(path).write_bytes(self.data[key])
                elif method == "DELETE":
                    self.deletes.append(key)
                    del self.data[key]
                else:
                    raise AssertionError(method)
        store = Store()
        store.prune(now)
        self.assertTrue(store.deletes)
        self.assertTrue(all("/point-36/" in key or "/point-37/" in key for key in store.deletes))
        self.assertTrue(any("/point-35/" in key for key in store.data))
        self.assertTrue(any("/incomplete-old/" in key for key in store.data))
        self.assertTrue(store.deletes[0].endswith("/COMPLETE.json"))
        broken = Store()
        broken.data[broken.prefix + "point-36/COMPLETE.json"] = b"{}"
        with self.assertRaises(ValueError):
            broken.prune(now)
        self.assertEqual([], broken.deletes)
        foreign = Store()
        foreign.data["backups/solidstats-memory/foreign/COMPLETE.json"] = b"protected"
        foreign.times["backups/solidstats-memory/foreign/COMPLETE.json"] = now - timedelta(days=60)
        with self.assertRaises(ValueError):
            foreign.prune(now)
        self.assertEqual([], foreign.deletes)

    def test_versioned_or_unknown_object_store_state_fails_closed(self):
        from xml.etree import ElementTree
        store = recovery.S3("https://example.invalid", "bucket", "backups/unified-memory/")
        for status in ("Enabled", "Suspended", "Unknown"):
            store.metadata = lambda query, status=status: ElementTree.fromstring("<VersioningConfiguration><Status>" + status + "</Status></VersioningConfiguration>")
            with self.subTest(status=status), self.assertRaises(ValueError):
                store.require_unversioned()
        store.metadata = lambda query: ElementTree.fromstring("<VersioningConfiguration/>")
        store.require_unversioned()

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "k8s/unified-memory/inputs.example.json").read_text())
        self.config["probeWing"] = "technical-operations"

    def test_complete_isolated_runtime_and_suspended_template(self):
        resources = renderer.generated(self.config, IMAGE)["items"]
        deployment = next(row for row in resources if row["kind"] == "Deployment")
        self.assertEqual("Recreate", deployment["spec"]["strategy"]["type"])
        self.assertFalse(deployment["spec"]["template"]["spec"]["automountServiceAccountToken"])
        cron = next(row for row in resources if row["kind"] == "CronJob")
        self.assertTrue(cron["spec"]["suspend"])
        self.assertEqual("Forbid", cron["spec"]["concurrencyPolicy"])
        policies = [row for row in resources if row["kind"] == "NetworkPolicy"]
        shared = next(row for row in policies if row["metadata"]["namespace"] == "solidstats-memory")
        for source in shared["spec"]["ingress"][0]["from"]:
            self.assertEqual("unified-memory", source["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"])
            self.assertIn(source["podSelector"]["matchLabels"]["app.kubernetes.io/name"], {"unified-mempalace", "unified-memory-backup"})

    def test_unsafe_image_namespace_or_wide_network_is_rejected(self):
        for field, value in (("namespace", "solidstats-memory"), ("hostNginxSourceCidr", "0.0.0.0/0"), ("qdrantUrl", "http://public:6333")):
            altered = copy.deepcopy(self.config)
            altered[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                renderer.generated(altered, IMAGE)
        with self.assertRaises(ValueError):
            renderer.generated(self.config, "image:latest")

    def test_startup_rejects_compatible_but_wrong_physical_alias_binding(self):
        observer = mock.Mock()
        observer.call.return_value = {"aliases": [
            {"alias_name": row["alias"], "collection_name": row["physical"]}
            for row in self.config["collections"]]}
        bootstrap.validate_alias_bindings(self.config, observer)
        observer.call.return_value["aliases"][0]["collection_name"] = "compatible-wrong-corpus"
        with self.assertRaises(ValueError):
            bootstrap.validate_alias_bindings(self.config, observer)

    def test_role_tokens_exclude_master_and_foreign_collections(self):
        import base64
        output = renderer.secrets(self.config, "synthetic-admin", "synthetic-http", {"S3_BUCKET": "bucket", "AWS_ACCESS_KEY_ID": "key", "AWS_SECRET_ACCESS_KEY": "secret"})
        expected = [{"collection": row["alias"], "access": "rw"} for row in self.config["collections"]]
        token = output["items"][0]["stringData"]["MEMPALACE_QDRANT_API_KEY"]
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
        self.assertEqual(expected, payload["access"])
        self.assertNotIn("synthetic-admin", json.dumps(output))
        self.assertNotIn("solidstats", json.dumps(payload).lower())




@unittest.skipUnless(os.environ.get("UNIFIED_QDRANT_BINARY"), "set UNIFIED_QDRANT_BINARY for pinned native server proof")
class NativeAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket
        import time
        executable = os.environ["UNIFIED_QDRANT_BINARY"]
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10)
        if version.returncode or version.stdout.strip() != "qdrant 1.19.0":
            raise RuntimeError("pinned Qdrant 1.19.0 required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="uq-")
        cls.root = Path(cls.temporary.name)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            grpc = listener.getsockname()[1]
        config = {"storage": {"storage_path": str(cls.root / "q"), "snapshots_path": str(cls.root / "snap")},
                  "service": {"host": "127.0.0.1", "http_port": port, "grpc_port": grpc,
                              "api_key": "synthetic-admin", "jwt_rbac": True}, "telemetry_disabled": True}
        config_path = cls.root / "qdrant.yaml"
        config_path.write_text(json.dumps(config))
        cls.log = (cls.root / "server.log").open("w")
        cls.process = subprocess.Popen([executable, "--config-path", str(config_path), "--disable-telemetry"],
            stdout=cls.log, stderr=subprocess.STDOUT, cwd=cls.root,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cls.client = recovery.Qdrant("http://127.0.0.1:" + str(port), "synthetic-admin")
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    raise RuntimeError("native server exited")
                try:
                    cls.client.call("GET", "/collections")
                    break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError("native server readiness failed")
            cls.config = json.loads((ROOT / "k8s/unified-memory/inputs.example.json").read_text())
            for row in cls.config["collections"]:
                cls.client.call("PUT", "/collections/" + row["physical"], {"vectors": {"size": 384, "distance": "Cosine"}})
                cls.client.call("POST", "/collections/aliases", {"actions": [{"create_alias": {"collection_name": row["physical"], "alias_name": row["alias"]}}]})
            cls.client.call("PUT", "/collections/foreign-solidstats", {"vectors": {"size": 384, "distance": "Cosine"}})
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.log.close()
        cls.temporary.cleanup()

    def test_real_alias_credentials_reject_foreign_and_administrative_access(self):
        from urllib.error import HTTPError
        rows = self.config["collections"]
        runtime = recovery.Qdrant(self.client.url, renderer.jwt("synthetic-admin", "unified-runtime", [row["alias"] for row in rows], "rw"))
        backup = recovery.Qdrant(self.client.url, renderer.jwt("synthetic-admin", "unified-backup", [row["physical"] for row in rows], "rw"))
        observer = recovery.Qdrant(self.client.url, renderer.jwt("synthetic-admin", "unified-observer", [name for row in rows for name in (row["physical"], row["alias"])], "r"))
        bootstrap.validate_alias_bindings(self.config, observer)
        for row in rows:
            runtime.call("GET", "/collections/" + row["alias"])
            self.assertEqual([{ "alias_name": row["alias"], "collection_name": row["physical"] }],
                             observer.call("GET", "/collections/" + row["physical"] + "/aliases")["aliases"])
            snapshot = backup.call("POST", "/collections/" + row["physical"] + "/snapshots")
            backup.call("DELETE", "/collections/" + row["physical"] + "/snapshots/" + snapshot["name"])
            observer.call("GET", "/collections/" + row["physical"])
        for client, method, path, body in (
            (runtime, "GET", "/collections/foreign-solidstats", None),
            (runtime, "GET", "/collections/" + rows[0]["physical"], None),
            (backup, "GET", "/collections/foreign-solidstats", None),
            (observer, "GET", "/collections/foreign-solidstats", None),
            (observer, "POST", "/collections/" + rows[0]["physical"] + "/snapshots", None),
            (runtime, "PUT", "/collections/unauthorized-create", {"vectors": {"size": 384, "distance": "Cosine"}}),
            (runtime, "POST", "/collections/aliases", {"actions": []}),
        ):
            with self.subTest(method=method, path=path), self.assertRaises(HTTPError) as captured:
                client.call(method, path, body)
            self.assertEqual(403, captured.exception.code)

    def test_native_two_collection_snapshot_and_isolated_restore(self):
        state = self.root / "state"
        state.mkdir()
        (state / "tunnels.json").write_text('{"synthetic":true}')
        for row in self.config["collections"]:
            self.client.call("PUT", "/collections/" + row["physical"] + "/points?wait=true",
                             {"points": [{"id": 1, "vector": [1.0] + [0.0] * 383, "payload": {"document": "synthetic"}}]})
        package = self.root / "package"
        backup_role = recovery.Qdrant(self.client.url, renderer.jwt("synthetic-admin", "unified-backup",
                                              [row["physical"] for row in self.config["collections"]], "rw"))
        recovery.backup(backup_role, self.config, state, package)
        targets = {row["physical"]: "isolated-" + str(index) for index, row in enumerate(self.config["collections"])}
        result = recovery.restore(self.client, package, targets, {"foreign-solidstats"}, self.root / "restored")
        self.assertEqual(2, result["restored"])
        self.assertFalse(result["aliasesChanged"])


if __name__ == "__main__":
    unittest.main()
