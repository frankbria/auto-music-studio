"""The Sentry auth token reaches the web build only as a BuildKit secret, never a layer (#342)."""

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "web" / "Dockerfile"


def test_the_sentry_auth_token_is_never_an_arg_or_env() -> None:
    lines = DOCKERFILE.read_text().splitlines()
    baked = [line for line in lines if re.match(r"\s*(ARG|ENV)\b", line) and "SENTRY_AUTH_TOKEN" in line]
    assert baked == []


def test_the_build_reads_the_token_from_a_secret_mount() -> None:
    assert "--mount=type=secret,id=sentry_auth_token,env=SENTRY_AUTH_TOKEN" in DOCKERFILE.read_text()
