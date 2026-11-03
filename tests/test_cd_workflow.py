"""Guards for .github/workflows/cd.yml: production is a promotion of what staging proved healthy (#700)."""

from pathlib import Path

import yaml

CD = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "cd.yml"
JOBS = yaml.safe_load(CD.read_text())["jobs"]
PRODUCTION = JOBS["deploy"]
STAGING = JOBS["deploy-staging"]


def _image_tag(job: dict) -> str:
    return next(step["env"]["IMAGE_TAG"] for step in job["steps"] if step.get("run") == "scripts/ci-deploy.sh")


def test_production_waits_for_a_green_staging_deploy() -> None:
    assert PRODUCTION["environment"] == "production"
    assert "deploy-staging" in PRODUCTION["needs"]
    # always(), failure() or !cancelled() in the condition would let production run after staging failed or skipped.
    assert not any(override in PRODUCTION["if"] for override in ("always()", "failure()", "cancelled()"))


def test_production_promotes_the_image_staging_ran_rather_than_building_one() -> None:
    assert _image_tag(PRODUCTION) == _image_tag(STAGING) == "${{ needs.publish.outputs.sha }}"
    assert not any("build-push-action" in step.get("uses", "") for step in PRODUCTION["steps"])


def test_production_reaches_its_host_over_the_tailnet_without_a_key() -> None:
    assert any(step.get("uses", "").startswith("tailscale/github-action@") for step in PRODUCTION["steps"])
    deploy_env = next(step["env"] for step in PRODUCTION["steps"] if step.get("run") == "scripts/ci-deploy.sh")
    assert deploy_env["DEPLOY_SSH_KEY_OPTIONAL"] == "true"
