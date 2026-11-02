"""compose.yaml hands every setting in .env.docker to the API container (#702)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker compose CLI")


def _api_environment(deploy_dir: Path, *env_file_args: str, env_file: str = "") -> dict[str, str]:
    shutil.copy(REPO / "compose.yaml", deploy_dir / "compose.yaml")
    rendered = subprocess.run(
        ["docker", "compose", "--project-directory", str(deploy_dir), *env_file_args, "config", "--format", "json"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "ACEMUSIC_API_JWT_SECRET_KEY": "k"}
        | ({"ENV_FILE": env_file} if env_file else {}),
    )
    assert rendered.returncode == 0, rendered.stderr
    return json.loads(rendered.stdout)["services"]["api"]["environment"]


def test_a_setting_compose_does_not_list_reaches_the_api(tmp_path: Path) -> None:
    (tmp_path / ".env.docker").write_text(
        "ACEMUSIC_API_JWT_SECRET_KEY=k\nACEMUSIC_API_STRIPE_PRICE_ID_ENTERPRISE_ANNUAL=price_enterprise_annual\n"
    )

    environment = _api_environment(tmp_path, "--env-file", str(tmp_path / ".env.docker"))

    assert environment["ACEMUSIC_API_STRIPE_PRICE_ID_ENTERPRISE_ANNUAL"] == "price_enterprise_annual"


def test_the_pinned_database_url_wins_over_the_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env.docker").write_text(
        "ACEMUSIC_API_JWT_SECRET_KEY=k\nACEMUSIC_API_MONGODB_URL=mongodb+srv://somewhere-else\n"
    )

    environment = _api_environment(tmp_path, "--env-file", str(tmp_path / ".env.docker"))

    assert environment["ACEMUSIC_API_MONGODB_URL"] == "mongodb://mongo:27017"


def test_the_stack_still_renders_without_an_env_file(tmp_path: Path) -> None:
    assert _api_environment(tmp_path)["ACEMUSIC_API_MONGODB_URL"] == "mongodb://mongo:27017"


def test_deploy_scripts_env_file_override_is_the_file_loaded(tmp_path: Path) -> None:
    custom = tmp_path / "staging.env"
    custom.write_text("ACEMUSIC_API_STRIPE_PRICE_ID_PRO_MONTHLY=price_from_custom\n")

    environment = _api_environment(tmp_path, "--env-file", str(custom), env_file=str(custom))

    assert environment["ACEMUSIC_API_STRIPE_PRICE_ID_PRO_MONTHLY"] == "price_from_custom"
