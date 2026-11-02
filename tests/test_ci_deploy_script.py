"""scripts/ci-deploy.sh: the CI half of a rollout, shared by the staging and production jobs (#699).

``ssh``, ``scp`` and ``ssh-keyscan`` are stubbed on PATH and record what they were asked, so this asserts the real
command lines without a host. deploy.sh itself is tested in test_deploy_script.py.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CI_DEPLOY = REPO / "scripts" / "ci-deploy.sh"

BASE_ENV = {
    "ENVIRONMENT": "staging",
    "DEPLOY_HOST": "staging.example",
    "DEPLOY_USER": "deployer",
    "DEPLOY_SSH_KEY": "-----BEGIN KEY-----",
    "DEPLOY_PATH": "/opt/stack",
    "IMAGE_TAG": "abc123",
    "API_IMAGE": "ghcr.io/o/r-api",
    "WEB_IMAGE": "ghcr.io/o/r-web",
    "GHCR_USER": "bot",
    "GHCR_TOKEN": "ghs_token",
}


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    (bin_dir / "ssh").write_text(
        f'#!/bin/sh\nstdin=$(cat)\necho "ssh $* <<$stdin" >> {log}\ncase "$*" in *deploy.sh*) exit "${{DEPLOY_EXIT:-0}}";; esac\n'
    )
    (bin_dir / "scp").write_text(f'#!/bin/sh\necho "scp $*" >> {log}\n')
    (bin_dir / "ssh-keyscan").write_text("#!/bin/sh\necho 'host key'\n")
    for name in ("ssh", "scp", "ssh-keyscan"):
        (bin_dir / name).chmod(0o755)
    return tmp_path


def _run(stubs: Path, **overrides: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    env = {
        "PATH": f"{stubs / 'bin'}:{os.environ['PATH']}",
        "HOME": str(stubs),
        **BASE_ENV,
        **overrides,
    }
    env = {key: value for key, value in env.items() if value is not None}
    result = subprocess.run(["bash", str(CI_DEPLOY)], cwd=REPO, env=env, capture_output=True, text=True)
    log = stubs / "calls.log"
    return result, log.read_text().splitlines() if log.exists() else []


def test_it_ships_the_stack_logs_the_host_in_and_hands_deploy_sh_the_sha(stubs: Path) -> None:
    result, calls = _run(stubs)

    assert result.returncode == 0, result.stderr
    assert (
        calls[0]
        == "scp -i " + f"{stubs}/.ssh/deploy_key compose.yaml scripts/deploy.sh deployer@staging.example:/opt/stack/"
    )
    assert "docker login ghcr.io -u 'bot' --password-stdin <<ghs_token" in calls[1]
    deploy = calls[2]
    assert "cd /opt/stack && chmod +x deploy.sh" in deploy
    assert "API_IMAGE='ghcr.io/o/r-api' WEB_IMAGE='ghcr.io/o/r-web' DEPLOY_DIR='/opt/stack'" in deploy
    assert deploy.endswith("./deploy.sh 'abc123' <<")
    assert "HEALTH_URL" not in deploy
    assert (stubs / ".ssh" / "deploy_key").read_text() == "-----BEGIN KEY-----\n"


def test_a_shared_host_points_the_health_gate_at_its_own_port(stubs: Path) -> None:
    _, calls = _run(stubs, DEPLOY_HEALTH_URL="http://127.0.0.1:8030/api/v1/health")

    assert "HEALTH_URL='http://127.0.0.1:8030/api/v1/health' ./deploy.sh 'abc123'" in calls[2]


def test_a_rolled_back_deploy_fails_the_job(stubs: Path) -> None:
    result, _ = _run(stubs, DEPLOY_EXIT="1")

    assert result.returncode == 1


@pytest.mark.parametrize("missing", ["DEPLOY_HOST", "DEPLOY_USER"])
def test_a_missing_secret_names_the_environment_and_touches_nothing(stubs: Path, missing: str) -> None:
    result, calls = _run(stubs, **{missing: ""})

    assert result.returncode == 1
    assert f"{missing} is not set on the staging environment" in result.stdout
    assert calls == []


def test_without_a_key_it_relies_on_the_network_to_authorize_ssh(stubs: Path) -> None:
    result, calls = _run(stubs, DEPLOY_SSH_KEY="")

    assert result.returncode == 0, result.stderr
    assert calls[0] == "scp compose.yaml scripts/deploy.sh deployer@staging.example:/opt/stack/"
    assert all(" -i " not in call for call in calls)
    assert not (stubs / ".ssh" / "deploy_key").exists()
