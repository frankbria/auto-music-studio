"""Shared ElevenLabs test helpers (#97 stems, #98 inpainting).

Imported by the command test modules (`test_stems.py`, `test_repaint.py`,
`test_extend.py`) so the mock client shape and config wiring stay in sync
as more ElevenLabs-backed commands land.
"""

from __future__ import annotations

from unittest.mock import MagicMock

FAKE_EL_MP3 = b"ID3" + b"\x00" * 200


def _el_config(monkeypatch, api_key="test-key", output_format="mp3_44100_128"):
    """Point load_config at an ElevenLabs-enabled config."""
    from acemusic.config import AceConfig

    monkeypatch.setattr(
        "acemusic.cli.load_config",
        lambda: AceConfig(
            api_url="http://localhost:8001",
            api_key=None,
            elevenlabs_api_key=api_key,
            elevenlabs_output_format=output_format,
        ),
    )


def _make_elevenlabs_client_mock(audio_bytes: bytes = FAKE_EL_MP3, song_id: str = "song-123"):
    """MagicMock ElevenLabsClient with a happy-path upload→plan→compose default."""
    el = MagicMock()
    el.upload_for_inpainting.return_value = song_id
    el.generate_from_plan.return_value = audio_bytes
    return el
