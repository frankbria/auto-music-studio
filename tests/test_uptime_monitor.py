"""scripts/uptime-monitor.sh: alert once after three failed health checks, and once on recovery (#342).

``curl`` is stubbed on PATH: health checks succeed or fail by a flag file, and webhook posts are recorded.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

MONITOR = Path(__file__).resolve().parents[1] / "scripts" / "uptime-monitor.sh"


@pytest.fixture
def rig(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    posts = tmp_path / "posts.log"
    bodies = tmp_path / "bodies.log"
    down = tmp_path / "down"
    (bin_dir / "curl").write_text(f"""#!/bin/sh
case "$*" in
  *"-X POST"*) echo "$*" >> {posts}
    while [ $# -gt 0 ]; do [ "$1" = --data ] && printf '%s\\n' "$2" >> {bodies}; shift; done
    exit 0 ;;
esac
[ -f {down} ] && exit 7
exit 0
""")
    (bin_dir / "curl").chmod(0o755)

    def run(**env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(MONITOR)],
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HEALTH_URL": "https://example.com/api/v1/health",
                "ALERT_WEBHOOK_URL": "https://hooks.example/alert",
                "STATE_FILE": str(tmp_path / "state" / "uptime"),
                **env,
            },
            capture_output=True,
            text=True,
        )

    def alerts() -> list[str]:
        return posts.read_text().splitlines() if posts.exists() else []

    run.bodies = bodies
    run.state = tmp_path / "state" / "uptime"
    return run, alerts, down


def test_two_failures_are_tolerated_and_the_third_alerts_once(rig) -> None:
    run, alerts, down = rig
    down.touch()

    for _ in range(2):
        assert run().returncode == 0
    assert alerts() == []

    run()
    run()

    [alert] = alerts()
    assert "Down: https://example.com/api/v1/health has failed 3 checks in a row." in alert
    assert '{"text": ' in alert


def test_recovery_is_announced_once_and_resets_the_count(rig) -> None:
    run, alerts, down = rig
    down.touch()
    for _ in range(3):
        run()
    down.unlink()

    run()
    run()

    assert len(alerts()) == 2
    assert "Recovered" in alerts()[1]


def test_a_blip_that_recovers_never_alerts(rig) -> None:
    run, alerts, down = rig
    down.touch()
    run()
    down.unlink()
    run()
    down.touch()
    run()
    run()

    assert alerts() == []


@pytest.mark.parametrize(("fmt", "shape"), [("discord", '{"content": '), ("ntfy", "Content-Type: text/plain")])
def test_other_webhook_formats(rig, fmt: str, shape: str) -> None:
    run, alerts, down = rig
    down.touch()
    for _ in range(3):
        run(ALERT_FORMAT=fmt)

    [alert] = alerts()
    assert shape in alert


def test_it_refuses_to_run_unconfigured(rig) -> None:
    run, _, _ = rig

    result = run(ALERT_WEBHOOK_URL="")

    assert result.returncode != 0
    assert "ALERT_WEBHOOK_URL" in result.stderr


def test_the_alert_is_valid_json_whatever_the_url_holds(rig) -> None:
    run, _, down = rig
    down.touch()
    url = 'https://example.com/a"b\\c'
    for _ in range(3):
        run(HEALTH_URL=url)

    [body] = run.bodies.read_text().splitlines()
    assert json.loads(body)["text"] == f"Down: {url} has failed 3 checks in a row."


def test_a_damaged_state_file_starts_the_count_again(rig) -> None:
    run, alerts, down = rig
    run.state.parent.mkdir()
    run.state.write_text("garbage here\n")
    down.touch()

    assert run().returncode == 0
    assert run.state.read_text() == "1 0\n"
    assert alerts() == []
