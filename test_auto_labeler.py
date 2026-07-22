import importlib.util
import pathlib
import subprocess
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("auto-labeler.py")
SPEC = importlib.util.spec_from_file_location("auto_labeler", MODULE_PATH)
auto_labeler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auto_labeler)


def pod(name="pod-1", node="node-1"):
    spec = {"nodeName": node} if node else {}
    return {
        "metadata": {"name": name, "namespace": "default"},
        "spec": spec,
    }


class AutoLabelerTest(unittest.TestCase):
    def completed(self, args, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    @mock.patch.object(auto_labeler, "run_kubectl")
    def test_labels_pod_and_reuses_node_cache(self, run_kubectl):
        node_json = '{"metadata":{"labels":{"zone":"east","ignored":"x"}}}'
        run_kubectl.side_effect = [
            self.completed([], stdout=node_json),
            self.completed([], stdout="pod/pod-1 labeled"),
            self.completed([], stdout="pod/pod-2 labeled"),
        ]

        counts = auto_labeler.process_context(
            [
                {"type": "Event", "object": pod("pod-1")},
                {"type": "Event", "object": pod("pod-2")},
            ],
            copy_labels="zone",
            timeout=3,
        )

        self.assertEqual(counts, {"labeled": 2, "skipped": 0, "failed": 0})
        self.assertEqual(run_kubectl.call_count, 3)
        label_args = run_kubectl.call_args_list[1].args[0]
        self.assertIn("auto-labeler.maxsum.io/labeled=", label_args)
        self.assertIn("zone=east", label_args)

    @mock.patch.object(auto_labeler, "run_kubectl")
    def test_unscheduled_pod_is_not_a_failure(self, run_kubectl):
        counts = auto_labeler.process_context(
            [{"type": "Event", "object": pod(node=None)}],
            timeout=3,
        )
        self.assertEqual(counts, {"labeled": 0, "skipped": 1, "failed": 0})
        run_kubectl.assert_not_called()

    @mock.patch.object(auto_labeler, "run_kubectl")
    def test_deleted_pod_is_not_a_failure(self, run_kubectl):
        run_kubectl.side_effect = [
            self.completed([], stdout='{ "metadata": {"labels": {}} }'),
            self.completed([], returncode=1, stderr='pods "pod-1" not found'),
        ]
        counts = auto_labeler.process_context(
            [{"type": "Event", "object": pod()}],
            timeout=3,
        )
        self.assertEqual(counts, {"labeled": 0, "skipped": 1, "failed": 0})

    @mock.patch.object(auto_labeler.subprocess, "run")
    def test_kubectl_has_client_and_process_timeouts(self, subprocess_run):
        subprocess_run.side_effect = subprocess.TimeoutExpired("kubectl", 2)
        result = auto_labeler.run_kubectl(["get", "node", "node-1"], timeout=2)
        self.assertIsNone(result)
        command = subprocess_run.call_args.args[0]
        self.assertEqual(command[:2], ["kubectl", "--request-timeout=2s"])
        self.assertEqual(subprocess_run.call_args.kwargs["timeout"], 2)

    @mock.patch.object(auto_labeler, "run_kubectl")
    def test_api_failure_is_counted_without_raising(self, run_kubectl):
        run_kubectl.return_value = self.completed(
            [], returncode=1, stderr="connection refused"
        )
        counts = auto_labeler.process_context(
            [{"type": "Event", "object": pod()}],
            timeout=3,
        )
        self.assertEqual(counts, {"labeled": 0, "skipped": 0, "failed": 1})

    @mock.patch.object(auto_labeler.subprocess, "run")
    def test_missing_kubectl_is_contained(self, subprocess_run):
        subprocess_run.side_effect = OSError("not installed")
        self.assertIsNone(auto_labeler.run_kubectl(["version"], timeout=2))

    def test_reads_synchronization_objects(self):
        context = [
            {
                "type": "Synchronization",
                "objects": [{"object": pod("pod-1")}, {"object": pod("pod-2")}],
            }
        ]
        self.assertEqual(len(list(auto_labeler.binding_objects(context))), 2)


if __name__ == "__main__":
    unittest.main()
