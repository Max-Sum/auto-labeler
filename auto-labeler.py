#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys


DEFAULT_CONFIG_FILE = "/etc/auto-labeler/config.yaml"
DEFAULT_COPY_LABELS = "node-dc,node-rack,node-name"
LABELED_MARKER = "auto-labeler.maxsum.io/labeled="


def log(message):
    print(message, flush=True)


def kubectl_timeout():
    raw_value = os.getenv("KUBECTL_TIMEOUT_SECONDS", "10")
    try:
        value = float(raw_value)
    except ValueError:
        log("WARN: invalid KUBECTL_TIMEOUT_SECONDS={!r}; using 10".format(raw_value))
        return 10.0
    if value <= 0:
        log("WARN: KUBECTL_TIMEOUT_SECONDS must be positive; using 10")
        return 10.0
    return value


def run_kubectl(arguments, timeout=None):
    timeout = kubectl_timeout() if timeout is None else timeout
    request_timeout = max(1, min(int(timeout), 30))
    command = ["kubectl", "--request-timeout={}s".format(request_timeout)] + arguments
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log(
            "ERROR: kubectl timed out after {}s: {}".format(
                timeout, " ".join(arguments[:4])
            )
        )
        return None
    except OSError as error:
        log("ERROR: cannot execute kubectl: {}".format(error))
        return None


def command_error(result):
    return " ".join(result.stderr.strip().splitlines())[:1000]


def binding_objects(context):
    for item in context:
        if not isinstance(item, dict):
            log("WARN: skipping non-object binding context entry")
            continue

        if item.get("type") == "Synchronization":
            entries = item.get("objects", [])
        else:
            entries = [item]

        for entry in entries:
            if not isinstance(entry, dict):
                log("WARN: skipping malformed binding object")
                continue
            obj = entry.get("object", entry)
            if isinstance(obj, dict):
                yield obj
            else:
                log("WARN: skipping binding object without a full Kubernetes object")


def get_node_labels(node_name, node_cache, timeout=None):
    if node_name in node_cache:
        return node_cache[node_name]

    result = run_kubectl(["get", "node", node_name, "-o", "json"], timeout=timeout)
    if result is None:
        return None
    if result.returncode != 0:
        log("ERROR: cannot read node {}: {}".format(node_name, command_error(result)))
        return None

    try:
        metadata = json.loads(result.stdout)["metadata"]
        labels = metadata.get("labels", {})
    except (AttributeError, json.JSONDecodeError, KeyError, TypeError) as error:
        log("ERROR: invalid node response for {}: {}".format(node_name, error))
        return None

    node_cache[node_name] = labels
    return labels


def label_pod(obj, copy_keys, node_cache, timeout=None):
    metadata = obj.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    spec = obj.get("spec", {})
    namespace = metadata.get("namespace")
    pod_name = metadata.get("name")
    node_name = spec.get("nodeName") if isinstance(spec, dict) else None

    if not namespace or not pod_name:
        log("WARN: skipping Pod event without namespace/name")
        return "skipped"
    if not node_name:
        # Pod creation and scheduling are separate API updates. A later Modified
        # event (or periodic resynchronization) will contain spec.nodeName.
        log("SKIP: {}/{} is not scheduled yet".format(namespace, pod_name))
        return "skipped"

    node_labels = get_node_labels(node_name, node_cache, timeout=timeout)
    if node_labels is None:
        return "failed"

    labels = [LABELED_MARKER]
    labels.extend(
        "{}={}".format(key, node_labels[key])
        for key in copy_keys
        if key in node_labels
    )
    result = run_kubectl(
        ["label", "pod", pod_name, "-n", namespace, "--overwrite"] + labels,
        timeout=timeout,
    )
    if result is None:
        return "failed"
    if result.returncode != 0:
        error = command_error(result)
        if "NotFound" in error or "not found" in error.lower():
            # Deletion racing with a queued Modified event is expected.
            log(
                "SKIP: {}/{} was deleted before it could be labeled".format(
                    namespace, pod_name
                )
            )
            return "skipped"
        log("ERROR: cannot label {}/{}: {}".format(namespace, pod_name, error))
        return "failed"

    log("Labeled {}/{} from node {}".format(namespace, pod_name, node_name))
    return "labeled"


def process_context(context, copy_labels=None, timeout=None):
    copy_labels = copy_labels or os.getenv("COPY_LABELS", DEFAULT_COPY_LABELS)
    copy_keys = tuple(key.strip() for key in copy_labels.split(",") if key.strip())
    counts = {"labeled": 0, "skipped": 0, "failed": 0}
    node_cache = {}

    for obj in binding_objects(context):
        result = label_pod(obj, copy_keys, node_cache, timeout=timeout)
        counts[result] += 1

    log(
        "Finished: labeled={labeled}, skipped={skipped}, failed={failed}".format(
            **counts
        )
    )
    # Never poison Shell-Operator's serial queue because of one stale or
    # temporarily failing object. resynchronizationPeriod retries missed Pods.
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pod hook for Shell-Operator")
    parser.add_argument("--config", action="store_true")
    args = parser.parse_args(argv)

    if args.config:
        config_file = os.getenv("CONFIG_FILE", DEFAULT_CONFIG_FILE)
        with open(config_file) as config_handle:
            sys.stdout.write(config_handle.read())
        return 0

    context_file = os.getenv("BINDING_CONTEXT_PATH")
    if not context_file:
        log("ERROR: BINDING_CONTEXT_PATH is not set")
        return 0

    try:
        with open(context_file) as context_handle:
            context = json.load(context_handle)
    except (OSError, json.JSONDecodeError) as error:
        # allowFailure in the hook configuration is the final safety net, but
        # exiting successfully here also prevents an unreadable task looping.
        log("ERROR: cannot read binding context: {}".format(error))
        return 0

    if not isinstance(context, list):
        log("ERROR: binding context is not a JSON array")
        return 0

    process_context(context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
