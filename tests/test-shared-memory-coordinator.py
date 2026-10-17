#!/usr/bin/env python3
"""Fencing, identity and writer restoration tests for the shared coordinator."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/operate-shared-memory.py"
spec = importlib.util.spec_from_file_location("coordinator", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeApi:
    def __init__(self):
        self.replicas = 1
        self.available = 1
        self.jobs = {}
        self.scales = []
        self.probed = False
        self.orphan_after_create = False
        self.uid_drift = False
        self.probe_failure = False
        self.template = {"spec": {"template": {"spec": {"containers": [{"name": "backup"}]}}}}

    def get(self, namespace, kind, name=None):
        if kind == "jobs":
            return {"items": [job for ns, job in self.jobs.values() if ns == namespace]}
        if kind == "cronjob":
            return {"metadata": {"uid": "cron-uid"}, "spec": {"suspend": True, "concurrencyPolicy": "Forbid", "jobTemplate": copy.deepcopy(self.template)}}
        if kind == "deployment":
            return {"spec": {"replicas": self.replicas}, "status": {"availableReplicas": self.available}}
        if kind == "job":
            result = copy.deepcopy(self.jobs[name][1])
            if self.uid_drift:
                result["metadata"]["uid"] = "foreign-uid"
            return result
        raise AssertionError(kind)

    def pods(self, scope):
        return []

    def scale(self, scope, replicas):
        self.replicas = self.available = replicas
        self.scales.append(replicas)

    def create(self, value):
        job = copy.deepcopy(value)
        job["metadata"]["uid"] = "created-uid"
        job["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
        self.jobs[job["metadata"]["name"]] = (job["metadata"]["namespace"], job)
        if self.orphan_after_create:
            job["status"] = {}
            raise RuntimeError("connection lost after Job creation")
        return job

    def probe(self, scope):
        if self.probe_failure:
            raise RuntimeError("probe failed")
        self.probed = True

    def command(self, *args):
        if "solidstats-memory" in args:
            return b"PASS: writer-restored=pass\nPASS: behavior-oracle=pass\n"
        return b"PASS: unified recovery operation\n"


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        self.api = FakeApi()
        checksum = hashlib.sha256(module.encoded(self.api.template)).hexdigest()
        self.config = {"timeout": 1, "scopes": {
            "solidstats": {"namespace": "solidstats-memory", "cronjob": "solidstats-memory-backup", "templateSha256": checksum},
            "unified": {"namespace": "unified-memory", "cronjob": "unified-memory-backup", "writer": "mempalace", "pvc": "unified-memory-data", "templateSha256": checksum}}}
        self.subject = module.Coordinator(self.config, self.api, self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_unified_backup_preserves_owner_uid_and_restores_writer(self):
        self.subject.backup("unified")
        record = json.loads(self.subject.journal.read_text())
        self.assertEqual("complete", record["status"])
        self.assertEqual([0, 1], self.api.scales)
        self.assertTrue(self.api.probed)
        job = next(iter(self.api.jobs.values()))[1]
        self.assertEqual("cron-uid", job["metadata"]["ownerReferences"][0]["uid"])
        self.assertEqual("created-uid", record["jobUid"])

    def test_solidstats_keeps_its_own_quiescence_and_original_oracles(self):
        self.subject.backup("solidstats")
        self.assertEqual([], self.api.scales)
        self.assertEqual("complete", json.loads(self.subject.journal.read_text())["status"])
        self.assertTrue(next(iter(self.api.jobs)).startswith("solidstats-memory-backup-"))

    def test_lost_create_ack_leaves_writer_frozen_and_blocks_every_scope(self):
        self.api.orphan_after_create = True
        with self.assertRaises(RuntimeError):
            self.subject.backup("unified")
        self.assertEqual(0, self.api.replicas)
        for scope in ("solidstats", "unified"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.subject.backup(scope)
        record = json.loads(self.subject.journal.read_text())
        with self.assertRaises(ValueError):
            self.subject.reconcile(record["runId"])
        for namespace, job in self.api.jobs.values():
            job["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        self.subject.reconcile(record["runId"])
        self.assertEqual(1, self.api.replicas)
        self.assertEqual("reconciled", json.loads(self.subject.journal.read_text())["status"])

    def test_unregistered_orphan_blocks_even_without_journal(self):
        self.api.jobs["unknown"] = ("solidstats-memory", {"metadata": {"name": "unknown"}, "status": {}})
        with self.assertRaises(ValueError):
            self.subject.backup("unified")
        self.assertEqual([], self.api.scales)

    def test_changed_template_fails_before_writer_mutation(self):
        self.config["scopes"]["unified"]["templateSha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.subject.backup("unified")
        self.assertEqual([], self.api.scales)

    def test_changed_uid_and_failed_resume_probe_remain_fenced(self):
        self.api.uid_drift = True
        with self.assertRaises(ValueError):
            self.subject.backup("unified")
        self.assertEqual("incomplete", json.loads(self.subject.journal.read_text())["status"])
        self.api.uid_drift = False
        self.api.probe_failure = True
        record = json.loads(self.subject.journal.read_text())
        # Force the required resume path so the failing probe is exercised.
        record["writerRestoreRequired"] = True
        module.durable(self.subject.journal, record)
        with self.assertRaises(RuntimeError):
            self.subject.reconcile(record["runId"])
        self.assertEqual("incomplete", json.loads(self.subject.journal.read_text())["status"])

    def test_orphan_pvc_pod_fences_reconciliation_and_every_operation(self):
        self.api.orphan_after_create = True
        with self.assertRaises(RuntimeError):
            self.subject.backup("unified")
        self.api.jobs.clear()
        orphan = {"metadata": {}, "status": {"phase": "Running"},
                  "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "unified-memory-data"}}]}}
        self.api.pods = lambda scope: [orphan] if scope["namespace"] == "unified-memory" else []
        record = json.loads(self.subject.journal.read_text())
        with self.assertRaises(ValueError):
            self.subject.reconcile(record["runId"])
        self.assertEqual(0, self.api.replicas)
        for scope in ("solidstats", "unified"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.subject.backup(scope)
        self.assertEqual("incomplete", json.loads(self.subject.journal.read_text())["status"])

    def test_cli_dispatches_the_whole_registered_solidstats_recovery(self):
        config = {**self.config, "schema": "shared-memory-coordinator/v1", "stateRoot": str(self.path),
                  "kubectl": "/registered/kubectl", "kubeconfig": "/registered/kubeconfig",
                  "solidstatsRecovery": {"python": "/registered/python3", "module": "/registered/restore.py"}}
        request = {"schema": "shared-solidstats-recovery-request/v1", "runId": "recovery-test-01",
                   "handoff": "/registered/handoff.json", "evidenceDir": "/registered/evidence",
                   "environment": {"SOLIDSTATS_MEMORY_OPERATOR": "/registered/operator.py",
                                   "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT": "/registered/private"}}
        config_path, request_path = self.path / "config.json", self.path / "request.json"
        config_path.write_text(json.dumps(config))
        request_path.write_text(json.dumps(request))
        with mock.patch.object(module.os, "geteuid", return_value=0, create=True), \
             mock.patch.object(module, "trusted", side_effect=lambda path, **kwargs: Path(path)), \
             mock.patch.object(module.stat, "S_IMODE", return_value=0o700), \
             mock.patch.object(module, "Coordinator") as coordinator, \
             mock.patch.object(sys, "argv", [str(SCRIPT), "--config", str(config_path), "solidstats-recovery", "--request", str(request_path)]):
            module.main()
        coordinator.return_value.solidstats_recovery.assert_called_once_with(request)
        coordinator.return_value.preflight.assert_not_called()

    def test_registered_recovery_runs_all_existing_stages_under_one_operation(self):
        self.config["solidstatsRecovery"] = {"python": "/registered/python3", "module": "/registered/restore.py"}
        request = {"runId": "recovery-test-01", "environment": {}, "handoff": "/registered/handoff.json", "evidenceDir": "/registered/evidence"}
        def complete(command, **kwargs):
            stage = command[2]
            self.assertEqual("incomplete", json.loads(self.subject.journal.read_text())["status"])
            return subprocess.CompletedProcess(command, 0, ("PASS: " + stage + " completed\n").encode(), b"")
        with mock.patch.object(module.subprocess, "run", side_effect=complete) as execute:
            self.subject.solidstats_recovery(request)
        self.assertEqual(["preflight", "backup", "isolated-restore", "verify-restore"], [call.args[0][2] for call in execute.call_args_list])
        self.assertEqual("complete", json.loads(self.subject.journal.read_text())["status"])

    def test_second_process_cannot_enter_while_first_holds_shared_lock(self):
        command = ("import importlib.util,pathlib; "
                   "s=importlib.util.spec_from_file_location('coordinator', " + repr(str(SCRIPT)) + "); "
                   "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                   "c=m.exclusive(pathlib.Path(" + repr(str(self.path / "operation.lock")) + ")); "
                   "c.__enter__()")
        with module.exclusive(self.path / "operation.lock"):
            result = subprocess.run([sys.executable, "-B", "-c", command], capture_output=True, timeout=10)
        self.assertNotEqual(0, result.returncode)
        with module.exclusive(self.path / "operation.lock"):
            pass


if __name__ == "__main__":
    unittest.main()
