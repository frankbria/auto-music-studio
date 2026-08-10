"""scripts/deploy.sh — the rollout, its health gate and its rollback (#429).

The deploy logic lives in a script rather than in workflow YAML precisely so it can be
tested. A rollback that has never run is not a rollback, and "we'll find out during the
next bad deploy" is not a test strategy.

``docker`` and ``curl`` are stubbed on PATH, so these run anywhere — no daemon, no host,
no network — while still asserting the real command lines the script issues.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

DEPLOY_SH = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"


@dataclass
class Rig:
    run: Callable[..., subprocess.CompletedProcess]
    docker_log: Path
    health_file: Path
    state_file: Path

    def serve(self, sha: str) -> None:
        """Make the stubbed health endpoint report ``sha`` as the running build."""
        self.health_file.write_text(json.dumps({"status": "ok", "build_sha": sha}))

    def docker_calls(self) -> str:
        return self.docker_log.read_text() if self.docker_log.exists() else ""


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    """A deploy directory plus stubbed ``docker``/``curl`` that record what they were asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    (deploy_dir / "compose.yaml").write_text("services: {}\n")

    docker_log = tmp_path / "docker.log"
    health_file = tmp_path / "health.json"
    health_file.write_text(json.dumps({"status": "ok", "build_sha": "unknown"}))

    (bin_dir / "docker").write_text(f'#!/bin/sh\necho "IMAGE_TAG=${{IMAGE_TAG}} $*" >> {docker_log}\nexit 0\n')
    (bin_dir / "curl").write_text(f"#!/bin/sh\ncat {health_file}\n")
    for name in ("docker", "curl"):
        (bin_dir / name).chmod(0o755)

    def run(tag: str, **env_overrides) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DEPLOY_DIR": str(deploy_dir),
            "HEALTH_URL": "http://localhost:8000/api/v1/health",
            # Short, so the failure path does not make the suite wait out a real deadline.
            "HEALTH_TIMEOUT": "3",
            "HEALTH_INTERVAL": "1",
            **env_overrides,
        }
        return subprocess.run([str(DEPLOY_SH), tag], capture_output=True, text=True, env=env)

    return Rig(run=run, docker_log=docker_log, health_file=health_file, state_file=deploy_dir / ".deployed-tag")


class TestRollout:
    def test_a_healthy_deploy_pulls_starts_and_records_the_tag(self, rig: Rig) -> None:
        rig.serve("newsha")

        result = rig.run("newsha")

        assert result.returncode == 0, result.stderr
        log = rig.docker_calls()
        assert "IMAGE_TAG=newsha compose" in log
        assert "pull" in log
        assert "up -d" in log
        assert rig.state_file.read_text().strip() == "newsha"

    def test_it_waits_for_the_new_commit_not_merely_a_200(self, rig: Rig) -> None:
        # The whole point of the gate. A crash-looping new image leaves the old container
        # answering 200 the entire time, and a plain liveness check calls that a success.
        rig.serve("oldsha")
        rig.state_file.write_text("oldsha\n")

        result = rig.run("newsha")

        assert result.returncode == 1
        assert "newsha" in result.stdout + result.stderr

    def test_a_missing_tag_is_a_usage_error(self, rig: Rig) -> None:
        assert rig.run("").returncode == 2


class TestIdempotence:
    def test_redeploying_the_running_tag_changes_nothing(self, rig: Rig) -> None:
        rig.serve("samesha")
        rig.state_file.write_text("samesha\n")

        result = rig.run("samesha")

        assert result.returncode == 0
        # Re-running the same deploy must be a no-op, not a second mutation.
        assert "up -d" not in rig.docker_calls()

    def test_it_redeploys_when_the_tag_matches_but_the_stack_is_down(self, rig: Rig) -> None:
        # The recorded tag is a claim about the last deploy, not evidence the stack is
        # still up — so the shortcut has to be gated on what is actually answering.
        rig.serve("unknown")
        rig.state_file.write_text("samesha\n")

        rig.run("samesha")

        assert "up -d" in rig.docker_calls()


class TestConcurrency:
    def test_a_second_deploy_refuses_while_one_is_running(self, rig: Rig) -> None:
        """`concurrency: production` only serialises workflow runs.

        It does nothing about an operator running this by hand mid-rollout — which is
        exactly when someone would — and two interleaved rollouts can leave the stack on a
        mixed set of images.
        """
        rig.serve("newsha")
        lock = rig.state_file.parent / ".deploy.lock"

        # Hold the lock the way a rollout in flight would.
        holder = subprocess.Popen(["flock", str(lock), "sleep", "10"])
        try:
            time.sleep(0.5)
            result = rig.run("newsha")
        finally:
            holder.kill()
            holder.wait()

        assert result.returncode == 3
        assert "another deploy is already running" in result.stderr
        assert "up -d" not in rig.docker_calls()


class TestRollback:
    def test_an_unhealthy_deploy_restores_the_previous_tag_and_fails(self, rig: Rig) -> None:
        rig.serve("oldsha")  # the new image never comes up
        rig.state_file.write_text("oldsha\n")

        result = rig.run("badsha")

        assert result.returncode == 1
        log = rig.docker_calls()
        assert "IMAGE_TAG=badsha compose" in log
        assert "IMAGE_TAG=oldsha compose" in log
        # Rolled back *after* the bad attempt, not merely present from an earlier line.
        assert log.rindex("IMAGE_TAG=oldsha") > log.index("IMAGE_TAG=badsha")
        assert rig.state_file.read_text().strip() == "oldsha"
        assert "rollback" in (result.stdout + result.stderr).lower()

    def test_a_first_ever_deploy_has_nothing_to_roll_back_to(self, rig: Rig) -> None:
        # No state file. Failing is still correct; pretending to roll back is not.
        rig.serve("unknown")

        result = rig.run("firstsha")

        assert result.returncode == 1
        assert "no previous" in (result.stdout + result.stderr).lower()
