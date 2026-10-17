#!/usr/bin/env python3
"""Root-owned serialization for shared-Qdrant backups and isolated restores."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

NAME = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def durable(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("unsafe operation record")
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def exclusive(path, wait_seconds=0):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("unsafe shared lock")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.write(descriptor, b"0")
                    os.lseek(descriptor, 0, 0)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(2, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(descriptor)


def trusted(path, private=False):
    path = Path(path)
    for parent in (path, *path.parents):
        details = parent.lstat()
        if stat.S_ISLNK(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
            raise ValueError("unsafe operator trust chain")
    if private and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("private root-owned configuration required")
    return path


class Kubernetes:
    def __init__(self, config):
        self.config = config

    def command(self, *args, body=None):
        command = [self.config["kubectl"], "--kubeconfig", self.config["kubeconfig"], "--context", self.config["context"], *args]
        result = subprocess.run(command, input=None if body is None else encoded(body), capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError("Kubernetes operation failed")
        return result.stdout

    def get(self, namespace, kind, name=None):
        args = ["-n", namespace, "get", kind]
        if name:
            args.append(name)
        return json.loads(self.command(*args, "-o", "json"))

    def scale(self, scope, replicas):
        self.command("-n", scope["namespace"], "scale", "deployment/" + scope["writer"], "--replicas=" + str(replicas))

    def create(self, job):
        return json.loads(self.command("create", "-f", "-", "-o", "json", body=job))

    def probe(self, scope):
        self.command("-n", scope["namespace"], "exec", "deployment/" + scope["writer"], "--",
                     "python3", "/opt/unified-memory/bootstrap-unified-memory.py", "probe",
                     "--bindings", "/opt/unified-memory/bindings.json")

    def pods(self, scope):
        return self.get(scope["namespace"], "pods")["items"]


def active_pod(pod):
    return pod.get("status", {}).get("phase") not in {"Failed", "Succeeded"}


class Coordinator:
    def __init__(self, config, api, state, *, sleeper=time.sleep):
        self.config, self.api, self.state = config, api, Path(state)
        self.sleeper = sleeper
        self.journal = self.state / "operation.json"
        self.record = None

    def save(self, **values):
        self.record.update(values)
        durable(self.journal, self.record)

    def no_active_jobs(self):
        for scope in self.config["scopes"].values():
            for job in self.api.get(scope["namespace"], "jobs")["items"]:
                conditions = {row["type"]: row["status"] for row in job.get("status", {}).get("conditions", [])}
                if conditions.get("Complete") != "True" and conditions.get("Failed") != "True":
                    raise ValueError("an operation Job may still be running")

            for pod in self.api.pods(scope):
                if not active_pod(pod):
                    continue
                metadata = pod.get("metadata", {})
                labels = metadata.get("labels", {})
                backup = labels.get("app.kubernetes.io/name") in {"solidstats-memory-backup", "unified-memory-backup"}
                job_owned = any(owner.get("kind") == "Job" for owner in metadata.get("ownerReferences", []))
                foreign_pvc = scope.get("pvc") and labels.get("app.kubernetes.io/name") != "unified-mempalace" and any(
                    volume.get("persistentVolumeClaim", {}).get("claimName") == scope["pvc"]
                    for volume in pod.get("spec", {}).get("volumes", []))
                if backup or job_owned or labels.get("shared-memory-operation") or foreign_pvc:
                    raise ValueError("an orphan operation or writable-state Pod may still be running")

    def preflight(self):
        if self.journal.exists():
            prior = json.loads(self.journal.read_text())
            if prior.get("status") not in {"complete", "reconciled"}:
                raise ValueError("prior operation requires explicit reconciliation")
        self.no_active_jobs()
        for scope in self.config["scopes"].values():
            cron = self.api.get(scope["namespace"], "cronjob", scope["cronjob"])
            if cron["spec"].get("suspend") is not True or cron["spec"].get("concurrencyPolicy") != "Forbid":
                raise ValueError("all backup templates must stay suspended with Forbid")

    def wait(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            self.sleeper(2)
        raise ValueError("bounded operation timed out")

    def freeze_unified(self, scope):
        deployment = self.api.get(scope["namespace"], "deployment", scope["writer"])
        replicas = deployment["spec"]["replicas"]
        if type(replicas) is not int or replicas != 1 or deployment.get("status", {}).get("availableReplicas") != 1:
            raise ValueError("one available unified writer required")
        self.save(originalReplicas=replicas, writerRestoreRequired=True, stage="freeze-intent")
        self.api.scale(scope, 0)
        self.wait(lambda: not any(active_pod(pod) and any(
            volume.get("persistentVolumeClaim", {}).get("claimName") == scope["pvc"]
            for volume in pod.get("spec", {}).get("volumes", []))
            for pod in self.api.pods(scope)), self.config["timeout"])
        self.save(stage="writer-frozen")

    def restore_writer(self, scope):
        if not self.record.get("writerRestoreRequired"):
            return
        self.no_active_jobs()
        self.api.scale(scope, self.record["originalReplicas"])
        self.wait(lambda: self.api.get(scope["namespace"], "deployment", scope["writer"]).get("status", {}).get("availableReplicas", 0)
                  == self.record["originalReplicas"], self.config["timeout"])
        self.api.probe(scope)
        self.save(writerRestoreRequired=False, stage="writer-restored")

    def backup(self, name):
        self.preflight()
        scope = self.config["scopes"][name]
        cron = self.api.get(scope["namespace"], "cronjob", scope["cronjob"])
        template = cron["spec"]["jobTemplate"]
        template_digest = hashlib.sha256(encoded(template)).hexdigest()
        if template_digest != scope["templateSha256"]:
            raise ValueError("reviewed Job template changed")
        run = scope["cronjob"] + "-" + uuid.uuid4().hex[:12]
        self.record = {"schema": "shared-memory-operation/v1", "runId": run, "scope": name, "operation": "backup",
                       "status": "incomplete", "stage": "intent", "jobName": run, "jobUid": None,
                       "templateSha256": template_digest, "writerRestoreRequired": False}
        durable(self.journal, self.record)
        try:
            if name == "unified":
                self.freeze_unified(scope)
            job = {"apiVersion": "batch/v1", "kind": "Job",
                   "metadata": {"name": run, "namespace": scope["namespace"],
                                "labels": {"shared-memory-operation": run},
                                "ownerReferences": [{"apiVersion": "batch/v1", "kind": "CronJob", "name": scope["cronjob"],
                                                     "uid": cron["metadata"]["uid"], "controller": True, "blockOwnerDeletion": False}]},
                   "spec": copy.deepcopy(template["spec"])}
            # Deadline/backoff remain reviewed template values.
            self.save(stage="job-create-intent")
            created = self.api.create(job)
            self.save(jobUid=created["metadata"]["uid"], stage="job-created")
            def finished():
                observed = self.api.get(scope["namespace"], "job", run)
                if observed["metadata"]["uid"] != self.record["jobUid"]:
                    raise ValueError("operation Job identity changed")
                conditions = {row["type"]: row["status"] for row in observed.get("status", {}).get("conditions", [])}
                if conditions.get("Failed") == "True":
                    raise ValueError("backup Job failed")
                return conditions.get("Complete") == "True"
            self.wait(finished, self.config["timeout"])
            logs = self.api.command("-n", scope["namespace"], "logs", "job/" + run, "--tail=30").decode()
            markers = ("PASS: writer-restored=pass", "PASS: behavior-oracle=pass") if name == "solidstats" else ("PASS: unified recovery operation",)
            if any(marker not in logs.splitlines() for marker in markers):
                raise ValueError("backup completion oracle is missing")
            self.save(stage="package-verified")
            self.restore_writer(scope)
            self.save(status="complete", stage="complete")
        except BaseException:
            # Never un-fence a possibly running Job. Its state must be reconciled first.
            self.save(status="incomplete", stage="failed")
            try:
                self.no_active_jobs()
                self.restore_writer(scope)
            except BaseException:
                pass
            raise

    def reconcile(self, run):
        self.record = json.loads(self.journal.read_text())
        if self.record["runId"] != run or self.record.get("status") != "incomplete":
            raise ValueError("exact incomplete run required")
        self.no_active_jobs()
        scope = self.config["scopes"][self.record["scope"]]
        if self.record.get("jobUid"):
            observed = self.api.get(scope["namespace"], "job", self.record["jobName"])
            if observed["metadata"]["uid"] != self.record["jobUid"]:
                raise ValueError("reconciliation Job identity changed")
        self.restore_writer(scope)
        self.save(status="reconciled", stage="reconciled")

    def solidstats_recovery(self, request):
        self.preflight()
        run = request["runId"]
        self.record = {"schema": "shared-memory-operation/v1", "runId": run, "scope": "solidstats",
                       "operation": "solidstats-recovery", "status": "incomplete", "stage": "intent",
                       "writerRestoreRequired": False}
        durable(self.journal, self.record)
        environment = {**os.environ, **request["environment"]}
        registered = self.config["solidstatsRecovery"]
        for stage in ("preflight", "backup", "isolated-restore", "verify-restore"):
            self.save(stage=stage + "-intent")
            result = subprocess.run([registered["python"], registered["module"], stage,
                                     "--handoff", request["handoff"], "--evidence-dir", request["evidenceDir"],
                                     "--run-id", run], env=environment, capture_output=True,
                                    timeout=self.config["timeout"])
            # The existing controller's diagnostics stay in the private root journal directory.
            transcript = self.state / (run + "-" + stage + ".log")
            descriptor = os.open(transcript, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(result.stdout + result.stderr)
                stream.flush()
                os.fsync(stream.fileno())
            if result.returncode or ("PASS: " + stage + " completed").encode() not in result.stdout.splitlines():
                raise ValueError("SolidStats recovery failed; operation remains fenced")
            self.no_active_jobs()
            self.save(stage=stage + "-complete")
        self.save(status="complete", stage="complete")

    def restore(self, package, targets, state_output):
        self.preflight()
        run = "restore-" + uuid.uuid4().hex[:24]
        self.record = {"schema": "shared-memory-operation/v1", "runId": run, "scope": "unified",
                       "operation": "restore", "status": "incomplete", "stage": "restore-intent",
                       "writerRestoreRequired": False}
        durable(self.journal, self.record)
        # Fixed, root-owned interpreter/module and key path; no configurable shell.
        restore = self.config["restore"]
        result = subprocess.run([restore["python"], restore["module"], "restore", "--package", str(package),
                                 "--targets", str(targets), "--protected", restore["protectedFile"],
                                 "--state-output", str(state_output), "--key-file", restore["keyFile"],
                                 "--qdrant-url", restore["qdrantUrl"]], capture_output=True, timeout=self.config["timeout"])
        if result.returncode or b"PASS: unified recovery operation" not in result.stdout.splitlines():
            raise ValueError("isolated restore failed; operation remains fenced")
        self.save(status="complete", stage="complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--lock-wait-seconds", type=int, default=0, choices=range(0, 7201), metavar="0..7200")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("preflight")
    digest_parser = sub.add_parser("template-digest")
    digest_parser.add_argument("--scope", choices=("solidstats", "unified"), required=True)
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--scope", choices=("solidstats", "unified"), required=True)
    solidstats = sub.add_parser("solidstats-recovery")
    solidstats.add_argument("--request", type=Path, required=True)
    recovery = sub.add_parser("restore")
    for name in ("package", "targets", "state-output"):
        recovery.add_argument("--" + name, type=Path, required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise ValueError("host root coordinator required")
    config = json.loads(trusted(args.config, private=True).read_text())
    if config.get("schema") != "shared-memory-coordinator/v1" or set(config["scopes"]) != {"solidstats", "unified"}:
        raise ValueError("exact two-palace registry required")
    for field in ("kubectl", "kubeconfig"):
        trusted(config[field], private=(field == "kubeconfig"))
    for scope in config["scopes"].values():
        for field in ("namespace", "cronjob"):
            if not NAME.fullmatch(scope[field]):
                raise ValueError("invalid fixed scope")
    if type(config["timeout"]) is not int or not 1 <= config["timeout"] <= 7200:
        raise ValueError("bounded coordinator timeout required")
    state = trusted(config["stateRoot"])
    if stat.S_IMODE(state.stat().st_mode) != 0o700:
        raise ValueError("private operation state required")
    if args.operation == "restore":
        for path in (args.package, args.targets):
            trusted(path)
        for field in ("python", "module", "protectedFile", "keyFile"):
            trusted(config["restore"][field], private=field in {"protectedFile", "keyFile"})
        endpoint = config["restore"]["qdrantUrl"]
        if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", endpoint):
            raise ValueError("operator loopback Qdrant forward required")
    request = None
    if args.operation == "solidstats-recovery":
        request = json.loads(trusted(args.request, private=True).read_text())
        if set(request) != {"schema", "runId", "handoff", "evidenceDir", "environment"} or request["schema"] != "shared-solidstats-recovery-request/v1":
            raise ValueError("fixed SolidStats recovery request required")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", request["runId"]):
            raise ValueError("exact recovery run identity required")
        if not isinstance(request["environment"], dict) or any(
                not re.fullmatch(r"SOLIDSTATS_MEMORY_[A-Z0-9_]+", key) or not isinstance(value, str)
                for key, value in request["environment"].items()):
            raise ValueError("only existing SolidStats controller environment inputs permitted")
        for field in ("python", "module"):
            trusted(config["solidstatsRecovery"][field])
        trusted(request["handoff"])
        trusted(request["evidenceDir"])
        for field in ("SOLIDSTATS_MEMORY_OPERATOR", "SOLIDSTATS_MEMORY_PRIVATE_RUN_ROOT"):
            if field not in request["environment"]:
                raise ValueError("existing recovery adapter inputs required")
            trusted(request["environment"][field])
    with exclusive(state / "operation.lock", args.lock_wait_seconds):
        coordinator = Coordinator(config, Kubernetes(config), state)
        if args.operation == "template-digest":
            coordinator.preflight()
            scope = config["scopes"][args.scope]
            cron = coordinator.api.get(scope["namespace"], "cronjob", scope["cronjob"])
            print(hashlib.sha256(encoded(cron["spec"]["jobTemplate"])).hexdigest())
        elif args.operation == "backup":
            coordinator.backup(args.scope)
        elif args.operation == "reconcile":
            coordinator.reconcile(args.run_id)
        elif args.operation == "solidstats-recovery":
            coordinator.solidstats_recovery(request)
        elif args.operation == "restore":
            coordinator.restore(args.package, args.targets, args.state_output)
        else:
            coordinator.preflight()
    print("PASS: shared memory operation")


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        print("FAIL: shared memory operation; inspect private operation state", file=sys.stderr)
        raise SystemExit(1)
