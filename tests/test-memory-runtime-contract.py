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
from unittest.mock import patch

import yaml


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
            observer["time"].monotonic = iter((1.0, 1.2, 2.0, 2.1, 3.0, 3.1, 4.0, 4.1)).__next__
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
            observer["time"].monotonic = iter(range(20)).__next__
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
    def snapshot_alert_expression(text: str) -> str:
        document = next(
            document
            for document in yaml.safe_load_all(text)
            if document and document.get("kind") == "ConfigMap" and document["metadata"]["name"] == "prometheus-server"
        )
        rules = yaml.safe_load(document["data"]["rules"])
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
        rendered = (ROOT / "k8s/observability/10-prometheus.yaml").read_text()
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
        rendered = (ROOT / "k8s/observability/10-prometheus.yaml").read_text()
        self.assertIn(expected_selector, self.snapshot_alert_expression_from_values(values))
        self.assertIn(expected_selector, self.snapshot_alert_expression(rendered))
        self.assertNotEqual(
            self.snapshot_alert_expression_from_values(values),
            self.snapshot_alert_expression(rendered).replace(expected_selector, 'cronjob="drift"'),
        )

    def test_values_and_rendered_config_consume_all_memory_signals(self) -> None:
        values = (ROOT / "k8s/observability/values/prometheus-values.yaml").read_text()
        rendered = (ROOT / "k8s/observability/10-prometheus.yaml").read_text()
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
            self.assertIn('kube_cronjob_spec_suspend{namespace="solidstats-memory",cronjob="solidstats-memory-backup"} == 0', text)
            for name in recording_rules + alerts:
                self.assertIn(name, text)
        workflow = WORKFLOW.read_text()
        role = (ROOT / "k8s/memory/01-ci-rbac.yaml").read_text()
        for forbidden in ("K8S_OBS_TOKEN", "K8S_OBS_ET_TOKEN", "obs-k3s-staging", "namespace: monitoring"):
            self.assertNotIn(forbidden, workflow)
        self.assertNotIn("monitoring", role)
        self.assertNotIn("ClusterRole", role)


if __name__ == "__main__":
    unittest.main()
