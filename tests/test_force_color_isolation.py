"""Guard for #520: the suite must pass regardless of the caller's FORCE_COLOR.

A plain `assert os.environ.get("FORCE_COLOR") is None` would pass in CI even with
the conftest fixture deleted, because CI never sets the variable. So this runs a
real subprocess pytest with FORCE_COLOR set, against a test that asserts on Rich
output.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET = "tests/test_generate.py::TestGenerateCommand::test_generate_prints_duration"


def test_cli_output_assertions_survive_forced_color():
    # Only FORCE_COLOR is asserted: CLICOLOR_FORCE alone does not make this
    # Rich version emit escapes, so a case for it would pass either way.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "-p", "no:cacheprovider", "--no-cov", "-q"],
        cwd=REPO_ROOT,
        env={**os.environ, "FORCE_COLOR": "3"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
