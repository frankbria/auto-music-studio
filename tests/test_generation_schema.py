"""Unit tests for the generation request/response schemas (US-9.1).

Pure Pydantic validation — no app, no database — so these run in the default
(non-integration) CI suite and cover every field-level validation rule plus the
duration/mode estimate heuristic. Endpoint-level behaviour (202, 401, MongoDB
persistence) is covered by ``tests/test_generation_api.py``.
"""

import pytest
from pydantic import ValidationError

from acemusic.api.routers.generation import (
    GenerationRequest,
    GenerationResponse,
    estimate_seconds,
)
from acemusic.constants import (
    VALID_MODES,
    VALID_SOUND_TYPES,
)


class TestValidRequests:
    def test_minimal_prompt_only_defaults_to_song(self):
        req = GenerationRequest(prompt="a calm piano ballad")
        assert req.prompt == "a calm piano ballad"
        assert req.mode == "song"
        assert req.sound_type is None
        assert req.instrumental is False
        assert req.weirdness == 50
        assert req.style_influence == 50
        assert req.format == "wav"

    def test_full_song_parameter_set(self):
        req = GenerationRequest(
            prompt="epic orchestral",
            style="cinematic",
            lyrics="la la la",
            vocal_language="en",
            instrumental=False,
            bpm=120,
            key="C minor",
            time_signature="4/4",
            duration=90.0,
            seed=42,
            inference_steps=64,
            model="xl-base",
            weirdness=70,
            style_influence=30,
            format="flac",
            thinking=True,
            mode="song",
        )
        assert req.bpm == 120
        assert req.model == "xl-base"
        assert req.time_signature == "4/4"

    def test_bpm_accepts_literal_auto(self):
        req = GenerationRequest(prompt="x", bpm="auto")
        assert req.bpm == "auto"

    def test_sound_one_shot_without_bpm_or_key(self):
        req = GenerationRequest(prompt="kick drum", mode="sound", sound_type="one-shot")
        assert req.mode == "sound"
        assert req.sound_type == "one-shot"

    def test_sound_loop_with_bpm_and_key(self):
        req = GenerationRequest(
            prompt="house loop",
            mode="sound",
            sound_type="loop",
            bpm=124,
            key="A minor",
        )
        assert req.sound_type == "loop"
        assert req.bpm == 124


class TestNumericRangeValidation:
    @pytest.mark.parametrize("bad_bpm", [59, 181, 999, 0])
    def test_bpm_out_of_range_rejected(self, bad_bpm):
        with pytest.raises(ValidationError) as exc:
            GenerationRequest(prompt="x", bpm=bad_bpm)
        assert any(e["loc"][-1] == "bpm" or e["loc"][0] == "bpm" for e in exc.value.errors())

    @pytest.mark.parametrize("bad_duration", [29.9, 240.1, 0.0, -5.0])
    def test_duration_out_of_range_rejected(self, bad_duration):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", duration=bad_duration)

    @pytest.mark.parametrize("bad", [-1, 101, 200])
    def test_weirdness_out_of_range_rejected(self, bad):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", weirdness=bad)

    @pytest.mark.parametrize("bad", [-1, 101])
    def test_style_influence_out_of_range_rejected(self, bad):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", style_influence=bad)

    @pytest.mark.parametrize("bad_steps", [0, -1])
    def test_inference_steps_must_be_positive(self, bad_steps):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", inference_steps=bad_steps)


class TestEnumValidation:
    def test_invalid_format_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", format="mp4")

    def test_invalid_model_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", model="gpt-music")

    def test_invalid_time_signature_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", time_signature="9/16")

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", mode="podcast")

    def test_invalid_sound_type_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", mode="sound", sound_type="riser")

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", tempo=120)

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="")


class TestModeConstraints:
    def test_sound_mode_requires_sound_type(self):
        with pytest.raises(ValidationError) as exc:
            GenerationRequest(prompt="x", mode="sound")
        assert "sound_type" in str(exc.value)

    def test_song_mode_forbids_sound_type(self):
        with pytest.raises(ValidationError) as exc:
            GenerationRequest(prompt="x", mode="song", sound_type="loop")
        assert "sound_type" in str(exc.value)

    def test_one_shot_forbids_bpm(self):
        with pytest.raises(ValidationError) as exc:
            GenerationRequest(prompt="x", mode="sound", sound_type="one-shot", bpm=120)
        assert "one-shot" in str(exc.value).lower()

    def test_one_shot_forbids_key(self):
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x", mode="sound", sound_type="one-shot", key="C major")


class TestEstimateHeuristic:
    def test_song_with_duration(self):
        req = GenerationRequest(prompt="x", duration=90.0)
        assert estimate_seconds(req) == 120

    def test_song_without_duration_uses_minimum(self):
        req = GenerationRequest(prompt="x")
        assert estimate_seconds(req) == 60  # 30 + DURATION_MIN(30)

    def test_sound_is_flat_base(self):
        req = GenerationRequest(prompt="x", mode="sound", sound_type="one-shot")
        assert estimate_seconds(req) == 15


class TestResponseSchema:
    def test_response_round_trip(self):
        resp = GenerationResponse(job_id="abc123", estimated_time_seconds=90)
        assert resp.status == "queued"
        body = resp.model_dump()
        assert body == {"job_id": "abc123", "status": "queued", "estimated_time_seconds": 90}


class TestConstantsStayInSync:
    """Guard against the schema's literals drifting from the shared constants."""

    def test_modes_match_constants(self):
        modes = set(GenerationRequest.model_fields["mode"].annotation.__args__)
        assert modes == set(VALID_MODES)

    def test_sound_types_match_constants(self):
        # sound_type annotation is ``Literal[...] | None``; pull the literal members.
        members: set[str] = set()
        for arg in GenerationRequest.model_fields["sound_type"].annotation.__args__:
            args = getattr(arg, "__args__", None)
            if args:
                members.update(a for a in args if isinstance(a, str))
        assert members == set(VALID_SOUND_TYPES)
