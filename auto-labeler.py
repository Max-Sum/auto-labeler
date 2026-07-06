#!/usr/bin/env python3
import argparse
import os
import sys
import json
import subprocess
import traceback

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

failed = 0

for item in context:
    event_type = item.get("type", "")

    if event_type == "Synchronization":
        items = item.get("objects", [])
    else:
        items = [item]

    for entry in items:
        obj = entry.get("object", entry) if isinstance(entry, dict) else entry

        if isinstance(obj, str):
            print("SKIP: jqFilter left only node={}".format(obj))
            continue

        try:
            node_name = obj["spec"]["nodeName"]
        except KeyError:
            # Dump the problematic object for debugging
            print("DEBUG: obj type={}, keys={}".format(type(obj).__name__, list(obj.keys()) if isinstance(obj, dict) else "N/A"))
            print("DEBUG: obj["metadata"]["name"]={}".format(obj.get("metadata", {}).get("name", "N/A")))
            print("DEBUG: full obj: {}".format(json.dumps(obj, indent=2, default=str)[:2000]))
            failed += 1
            continue

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
