#!/usr/bin/env python3
# scripts/split-obs-secrets.py
# Splits a multi-document YAML produced by render-obs-secrets.py into two
# per-namespace files so each CI token only applies to its own namespace.
#
# Usage:
#   python3 scripts/split-obs-secrets.py <all.yaml> <monitoring.yaml> <error-tracking.yaml>
#
# Each document that contains "namespace: error-tracking" goes to the third file;
# documents with "namespace: monitoring" (or no explicit namespace) go to the second file.
# This allows the monitoring-scoped and error-tracking-scoped CI tokens to each apply
# only their own secrets without cross-namespace access (T-16-11 mitigation).

import sys

if len(sys.argv) != 4:
    print(f"Usage: {sys.argv[0]} <all.yaml> <monitoring.yaml> <error-tracking.yaml>", file=sys.stderr)
    sys.exit(1)

in_file, mon_file, et_file = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(in_file).read()

# Split on document boundaries (--- separator)
raw_docs = []
current: list[str] = []
for line in text.splitlines():
    if line.strip() == "---":
        if current:
            raw_docs.append("\n".join(current))
        current = []
    else:
        current.append(line)
if current:
    raw_docs.append("\n".join(current))

mon_docs: list[str] = []
et_docs: list[str] = []
for doc in raw_docs:
    if not doc.strip():
        continue
    if "namespace: error-tracking" in doc:
        et_docs.append(doc)
    elif "namespace: monitoring" in doc:
        mon_docs.append(doc)
    else:
        # Fallback: apply to monitoring if no namespace declared
        mon_docs.append(doc)

with open(mon_file, "w") as f:
    f.write("\n---\n".join(mon_docs) + "\n")
with open(et_file, "w") as f:
    f.write("\n---\n".join(et_docs) + "\n")

print(f"split: {len(mon_docs)} monitoring doc(s) -> {mon_file}")
print(f"split: {len(et_docs)} error-tracking doc(s) -> {et_file}")
