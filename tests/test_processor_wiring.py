"""The lifespan must hand the JobProcessor every setting it is configured with (#429).

A setting that `ApiSettings` reads but nothing passes on is worse than a missing one: it
looks configured. `voice_training_root` was exactly that — the container image sets
`ACEMUSIC_API_VOICE_TRAINING_ROOT=/data/voice-training` and mounts a volume there, while
the worker kept writing to its own default relative to the process's working directory.
"""

import pytest
from fastapi.testclient import TestClient

from acemusic.api.main import create_app
from acemusic.api.settings import ApiSettings


@pytest.fixture
def captured_processor(monkeypatch):
    """Capture the kwargs the lifespan constructs the real JobProcessor with."""
    from acemusic.api import main as main_module

    captured: dict = {}

    class _Recorder:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(main_module, "JobProcessor", _Recorder)
    return captured


@pytest.fixture
def settings(mongo_db, mongo_settings):
    """The lifespan connects to Mongo before it starts the worker, so this needs a real one."""

    def build(**overrides) -> ApiSettings:
        return mongo_settings.model_copy(
            update={
                "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
                "job_processor_enabled": True,
                **overrides,
            }
        )

    return build


@pytest.mark.integration
class TestJobProcessorWiring:
    def test_the_configured_voice_training_root_reaches_the_worker(self, captured_processor, settings) -> None:
        app = create_app(settings(voice_training_root="/data/voice-training"))

        with TestClient(app):
            pass

        assert captured_processor.get("voice_training_root") == "/data/voice-training"

    def test_concurrency_settings_still_reach_the_worker(self, captured_processor, settings) -> None:
        # Guards the fix above from being applied by dropping the other kwargs.
        app = create_app(settings(job_concurrency=7))

        with TestClient(app):
            pass

        assert captured_processor.get("concurrency") == 7
