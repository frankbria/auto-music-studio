"""Supply-chain guard for .github/workflows (#425).

Every action must be pinned to an immutable commit SHA with a trailing version
comment, and every job must run with an explicit least-privilege GITHUB_TOKEN.
"""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"uses:\s*\S+@[0-9a-f]{40}\s+#\s*\S+")


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_sha_pinned(workflow: Path) -> None:
    offenders = [
        f"{workflow.name}:{n}: {line.strip()}"
        for n, line in enumerate(workflow.read_text().splitlines(), 1)
        if "uses:" in line and not PINNED.search(line)
    ]
    assert not offenders, "mutable action pins:\n" + "\n".join(offenders)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_declares_permissions(workflow: Path) -> None:
    doc = yaml.safe_load(workflow.read_text())
    missing = [name for name, job in doc["jobs"].items() if "permissions" not in job]
    assert "permissions" in doc or not missing, f"jobs without permissions: {missing}"
