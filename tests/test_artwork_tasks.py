"""Tests for the cover-art job handler (US-13.1, issue #132).

Exercise ``process_artwork_job`` directly with a fake image client and a local
storage backend: it generates options, upscales each to the distribution size,
stores them and records one ``ArtworkOption`` per option, rolling back on a
mid-batch failure. The ``get_image_client`` factory tests run in CI (no DB); the
handler tests need a local MongoDB (Beanie) and are ``integration``.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from acemusic.api.models import ArtworkOption, Clip, Job, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.artwork import ARTWORK_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks import artwork as tasks
from acemusic.api.tasks.common import JobProcessingError
from acemusic.constants import ARTWORK_FINAL_SIZE, ARTWORK_OPTIONS_COUNT
from acemusic.image_processing import validate_image
from acemusic.storage import LocalStorage, StorageBackend


def _png_1024() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), "purple").save(buf, format="PNG")
    return buf.getvalue()


class FakeImageClient:
    """Returns ``count`` canned 1024x1024 PNGs and records the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_images(self, prompt: str, count: int = 4) -> list[bytes]:
        self.prompts.append(prompt)
        return [_png_1024() for _ in range(count)]


class FailingStorage(StorageBackend):
    """Delegates to LocalStorage but raises on the Nth upload (to test rollback)."""

    def __init__(self, inner: LocalStorage, fail_on_call: int) -> None:
        self._inner = inner
        self._fail_on_call = fail_on_call
        self._uploads = 0

    def upload(self, path: str, data: bytes) -> None:
        self._uploads += 1
        if self._uploads == self._fail_on_call:
            raise OSError("disk full")
        self._inner.upload(path, data)

    def download(self, path: str) -> bytes:
        return self._inner.download(path)

    def delete(self, path: str) -> None:
        self._inner.delete(path)

    def get_url(self, path: str) -> str:
        return self._inner.get_url(path)


# ---------------------------------------------------------------------------
# get_image_client factory — CI (no DB)
# ---------------------------------------------------------------------------


class TestGetImageClient:
    def test_none_without_key(self) -> None:
        assert tasks.get_image_client(ApiSettings(_env_file=None)) is None

    def test_none_when_kill_switched(self) -> None:
        settings = ApiSettings(_env_file=None, openai_api_key="sk", artwork_generation_enabled=False)
        assert tasks.get_image_client(settings) is None

    def test_client_when_configured(self) -> None:
        settings = ApiSettings(_env_file=None, openai_api_key="sk-test")
        client = tasks.get_image_client(settings)
        assert client is not None and client.api_key == "sk-test"


# ---------------------------------------------------------------------------
# Handler — integration (local MongoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _make_job_and_clip(*, prompt: str | None = "album cover") -> tuple[Job, Clip]:
    user = await user_service.get_or_create_user(email="t@e.com", provider="google", oauth_id="g-t", name="T")
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = Clip(user_id=user.id, workspace_id=workspace.id, file_path="x.wav", title="Song", style_tags=["lofi"])
    await clip.insert()
    params: dict = {"clip_id": str(clip.id)}
    if prompt is not None:
        params["prompt"] = prompt
    job = Job(user_id=user.id, workspace_id=workspace.id, job_type=ARTWORK_JOB_TYPE, input_params=params)
    await job.insert()
    return job, clip


@pytest.mark.integration
class TestProcessArtworkJob:
    async def test_generates_and_stores_options(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        client = FakeImageClient()
        result = await tasks.process_artwork_job(job, storage=storage, client=client)

        ids = result["artwork_option_ids"]
        assert len(ids) == ARTWORK_OPTIONS_COUNT
        assert client.prompts == ["album cover"]

        options = await ArtworkOption.find(ArtworkOption.clip_id == clip.id).to_list()
        assert len(options) == ARTWORK_OPTIONS_COUNT
        # Each stored object is a valid PNG upscaled to the distribution size.
        for option in options:
            _fmt, width, height = validate_image(storage.download(option.storage_path))
            assert (width, height) == (ARTWORK_FINAL_SIZE, ARTWORK_FINAL_SIZE)

    async def test_missing_prompt_fails(self, storage) -> None:
        job, _clip = await _make_job_and_clip(prompt=None)
        with pytest.raises(JobProcessingError):
            await tasks.process_artwork_job(job, storage=storage, client=FakeImageClient())

    async def test_rollback_on_partial_failure(self, storage, tmp_path) -> None:
        job, clip = await _make_job_and_clip()
        # Fail on the 3rd upload: the first two options are stored, then unwound.
        failing = FailingStorage(storage, fail_on_call=3)
        with pytest.raises(OSError):
            await tasks.process_artwork_job(job, storage=failing, client=FakeImageClient())

        # No ArtworkOption docs and no leftover objects survive the rollback.
        assert await ArtworkOption.find(ArtworkOption.clip_id == clip.id).to_list() == []
        for idx in range(ARTWORK_OPTIONS_COUNT):
            with pytest.raises(FileNotFoundError):
                storage.download(f"{job.user_id}/{job.workspace_id}/artwork/{clip.id}/{idx}.png")
