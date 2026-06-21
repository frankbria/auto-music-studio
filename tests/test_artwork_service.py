"""Tests for the cover-art service layer (US-13.1, issue #132).

``build_artwork_prompt`` is pure (CI). ``create_artwork_job`` / ``select_artwork``
/ ``upload_custom_artwork`` touch MongoDB and storage, so they are ``integration``.
"""

import io
from types import SimpleNamespace

import pytest
from beanie import PydanticObjectId
from PIL import Image

from acemusic.api.models import ArtworkOption, Clip, Workspace
from acemusic.api.services import artwork as artwork_service, users as user_service
from acemusic.api.services.artwork import ARTWORK_JOB_TYPE, ArtworkNotFoundError
from acemusic.constants import ARTWORK_PROMPT_MAX_LENGTH
from acemusic.storage import LocalStorage


def _png(size=(3000, 3000)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "teal").save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# build_artwork_prompt — CI (pure)
# ---------------------------------------------------------------------------


class TestBuildArtworkPrompt:
    """build_artwork_prompt only reads ``title``/``style_tags``; a stand-in avoids
    needing Beanie initialised for these pure-logic cases."""

    @staticmethod
    def _clip(title=None, style_tags=()):
        return SimpleNamespace(title=title, style_tags=list(style_tags))

    def test_uses_title_and_style_tags_when_no_override(self) -> None:
        prompt = artwork_service.build_artwork_prompt(self._clip("Midnight Drive", ["synthwave", "retro"]))
        assert "Midnight Drive" in prompt
        assert "synthwave" in prompt and "retro" in prompt

    def test_explicit_override_wins(self) -> None:
        assert artwork_service.build_artwork_prompt(self._clip("T"), "a neon city at night") == "a neon city at night"

    def test_blank_override_falls_back_to_derived(self) -> None:
        assert "jazz" in artwork_service.build_artwork_prompt(self._clip(style_tags=["jazz"]), "   ")

    def test_override_is_capped(self) -> None:
        prompt = artwork_service.build_artwork_prompt(self._clip(), "x" * (ARTWORK_PROMPT_MAX_LENGTH + 500))
        assert len(prompt) == ARTWORK_PROMPT_MAX_LENGTH


# ---------------------------------------------------------------------------
# Integration — real MongoDB + LocalStorage
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _make_clip(*, email: str = "art@example.com") -> Clip:
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/c.wav",
        title="Song",
        style_tags=["lofi"],
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestCreateArtworkJob:
    async def test_persists_queued_job_with_resolved_prompt(self, storage) -> None:
        clip = await _make_clip()
        job = await artwork_service.create_artwork_job(clip=clip, style_prompt="custom prompt")
        assert job.job_type == ARTWORK_JOB_TYPE
        assert job.input_params["clip_id"] == str(clip.id)
        assert job.input_params["prompt"] == "custom prompt"


@pytest.mark.integration
class TestSelectArtwork:
    async def test_attaches_option_path_to_clip(self, storage) -> None:
        clip = await _make_clip()
        option = ArtworkOption(
            clip_id=clip.id,
            user_id=clip.user_id,
            job_id=PydanticObjectId(),
            storage_path="some/path/0.png",
            option_index=0,
        )
        await option.insert()
        updated = await artwork_service.select_artwork(clip, str(option.id))
        assert updated.artwork_path == "some/path/0.png"

    async def test_unknown_option_raises(self, storage) -> None:
        clip = await _make_clip()
        with pytest.raises(ArtworkNotFoundError):
            await artwork_service.select_artwork(clip, str(PydanticObjectId()))

    async def test_option_for_another_clip_raises(self, storage) -> None:
        clip = await _make_clip()
        other = await _make_clip(email="other@example.com")
        option = ArtworkOption(
            clip_id=other.id,
            user_id=other.user_id,
            job_id=PydanticObjectId(),
            storage_path="p.png",
            option_index=0,
        )
        await option.insert()
        with pytest.raises(ArtworkNotFoundError):
            await artwork_service.select_artwork(clip, str(option.id))


@pytest.mark.integration
class TestUploadCustomArtwork:
    async def test_stores_valid_image_and_sets_path(self, storage, monkeypatch) -> None:
        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
        monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(storage.root_dir))
        clip = await _make_clip()
        updated = await artwork_service.upload_custom_artwork(clip, _png())
        assert updated.artwork_path is not None
        assert storage.download(updated.artwork_path)  # object exists

    async def test_below_min_resolution_raises(self, storage, monkeypatch) -> None:
        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
        monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(storage.root_dir))
        clip = await _make_clip()
        from acemusic.image_processing import ImageValidationError

        with pytest.raises(ImageValidationError):
            await artwork_service.upload_custom_artwork(clip, _png(size=(1024, 1024)))
