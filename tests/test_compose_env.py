"""compose.yaml hands every setting in .env.docker to the API container (#702)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker compose CLI")


def _api_environment(deploy_dir: Path) -> dict[str, str]:
    shutil.copy(REPO / "compose.yaml", deploy_dir / "compose.yaml")
    rendered = subprocess.run(
        ["docker", "compose", "--project-directory", str(deploy_dir), "--env-file", str(deploy_dir / ".env.docker")]
        + ["config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(rendered.stdout)["services"]["api"]["environment"]


def test_a_setting_compose_does_not_list_reaches_the_api(tmp_path: Path) -> None:
    (tmp_path / ".env.docker").write_text(
        "ACEMUSIC_API_JWT_SECRET_KEY=k\nACEMUSIC_API_STRIPE_PRICE_ID_ENTERPRISE_ANNUAL=price_enterprise_annual\n"
    )

    environment = _api_environment(tmp_path)

    assert environment["ACEMUSIC_API_STRIPE_PRICE_ID_ENTERPRISE_ANNUAL"] == "price_enterprise_annual"


def test_the_pinned_database_url_wins_over_the_env_file(tmp_path: Path) -> None:
    (tmp_path / ".env.docker").write_text(
        "ACEMUSIC_API_JWT_SECRET_KEY=k\nACEMUSIC_API_MONGODB_URL=mongodb+srv://somewhere-else\n"
    )

    assert _api_environment(tmp_path)["ACEMUSIC_API_MONGODB_URL"] == "mongodb://mongo:27017"
