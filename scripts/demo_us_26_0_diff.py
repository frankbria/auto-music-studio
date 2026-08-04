"""Show exactly which packages this branch moves, and why each one moved."""

import json
import subprocess

main = json.loads(subprocess.run(["git", "show", "main:web/package-lock.json"], capture_output=True, text=True).stdout)[
    "packages"
]
cur = json.load(open("web/package-lock.json"))["packages"]

changed = sorted(
    (k, main[k].get("version"), cur[k].get("version"))
    for k in cur
    if k in main and main[k].get("version") != cur[k].get("version")
)
added = [k for k in cur if k not in main]
removed = [k for k in main if k not in cur]

# The per-platform sharp/next binaries move as a block with their parent; listing all
# 33 would bury the 15 packages that actually carry an advisory.
platform = [c for c in changed if "@img/" in c[0] or "@next/" in c[0]]
notable = [c for c in changed if c not in platform]

for key, before, after in notable:
    print(f"  {key.replace('node_modules/', ''):46} {before:>9} -> {after}")
print(f"  ... plus {len(platform)} per-platform sharp/next binaries moving with them")
print()
print(f"  {len(changed)} version changes, {len(added)} added, {len(removed)} removed")
