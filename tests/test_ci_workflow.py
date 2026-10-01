"""Guards for .github/workflows/ci.yml that are not supply-chain rules (see test_workflow_pins.py)."""

import shlex
from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_mongo_keeps_its_data_in_memory() -> None:
    """Every integration test builds and drops ~21 collections and ~74 indexes. On a runner with a
    slow disk, mongod's file create/drop and journal fsyncs made that 3-5x slower and pushed the
    step past the job timeout (#590). A tmpfs data dir takes the disk out of it."""
    args = shlex.split(yaml.safe_load(CI.read_text())["jobs"]["ci"]["services"]["mongodb"]["options"])
    mounts = [args[i + 1].split(":")[0] for i, a in enumerate(args) if a == "--tmpfs"]
    assert "/data/db" in mounts
