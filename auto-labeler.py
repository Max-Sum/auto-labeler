#!/usr/bin/env python3
import argparse
import os
import sys
import json
import subprocess

parser = argparse.ArgumentParser(description="Pod hook for Shell-Operator")
parser.add_argument("--config", action="store_true")

args = parser.parse_args()
CONFIG_FILE = os.getenv("CONFIG_FILE", "/etc/auto-labeler/config.yaml")
CONTEXT_FILE = os.getenv("BINDING_CONTEXT_PATH")
COPY_LABELS = os.getenv("COPY_LABELS", "node-dc,node-rack,node-name")

if args.config:
    with open(CONFIG_FILE) as cfg:
        print("".join(cfg.readlines()))
    sys.exit(0)

context = None
print("Processing context file: ", CONTEXT_FILE)
with open(CONTEXT_FILE) as context_hdl:
    context = json.load(context_hdl)

if context[0]["type"] == "Synchronization":
    print("Garbage fired.")
    sys.exit(0)

failed = 0
for item in context:
    obj = item["object"]

    # jqFilter stripped the object: obj is bare node name string instead of pod JSON
    if isinstance(obj, str):
        node_name = obj
        # Cannot determine pod name from filtered context; skip
        print("SKIP: jqFilter stripped pod info, only have node={}".format(node_name))
        continue

    node_name = obj["spec"]["nodeName"]
    namespace = obj["metadata"]["namespace"]
    pod_name = obj["metadata"]["name"]
    print("Processing {}...".format(pod_name))

    try:
        node_info = json.loads(
            subprocess.check_output(
                ["kubectl", "get", "node", node_name, "-o", "json"]))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print("ERROR: Failed to get node info for {}: {}".format(node_name, e))
        failed += 1
        continue

    node_labels = node_info["metadata"]["labels"]
    copy_keys = COPY_LABELS.split(",")

    final_labels = ["auto-labeler.maxsum.io/labeled="]
    for key in [key for key in node_labels.keys() if key in copy_keys]:
        final_labels.append("{}={}".format(key, node_labels[key]))
    cmd = ["kubectl", "label", "pods", pod_name, "-n", namespace, "--overwrite"] + final_labels
    print(cmd)
    try:
        print(subprocess.check_output(cmd))
    except subprocess.CalledProcessError as e:
        print("ERROR: Failed to label pod {}: {}".format(pod_name, e))
        failed += 1
        continue

if failed > 0:
    print("{} pod(s) failed, exiting non-zero to trigger shell-operator retry".format(failed))
    sys.exit(1)
sys.exit(0)
