#!/usr/bin/env python3
"""Offline contract tests for the isolated SolidStats memory runtime."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-memory.yml"
TUNNEL = ROOT / "scripts" / "ssh-tunnel-up.sh"


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
        self.assertLess(identity, self.workflow.index("--dry-run=server"))
        self.assertLess(identity, self.workflow.index("-n solidstats-memory apply"))

    def test_reuses_an_exclusive_workload_manifest_list(self) -> None:
        self.assertIn("! -name '00-namespace.yaml'", self.workflow)
        self.assertIn("! -name '01-ci-rbac.yaml'", self.workflow)
        self.assertIn("MEMORY_WORKLOAD_FILES", self.workflow)
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
        self.addCleanup(unrelated.kill)
        self.pid_file.write_text(str(unrelated.pid))
        self.pid_file.chmod(0o600)
        rejected = self.run_tunnel("--stop-managed")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIsNone(unrelated.poll())
        unrelated.kill()
        unrelated.wait()
        rejected = self.run_tunnel("--stop-managed")
        self.assertNotEqual(rejected.returncode, 0)


if __name__ == "__main__":
    unittest.main()
