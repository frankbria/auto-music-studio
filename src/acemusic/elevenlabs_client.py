"""ElevenLabs cloud music generation client (US-2.5)."""

from __future__ import annotations

import io
import zipfile
import zlib
from pathlib import Path

import httpx

_BASE_URL = "https://api.elevenlabs.io"

# ElevenLabs music API duration limits (music_length_ms: 3000–600000).
DURATION_MIN_S = 3.0
DURATION_MAX_S = 600.0

# Stem labels produced by the six_stems_v1 separation model (#97). Demucs
# produces four (vocals/drums/bass/other); ElevenLabs adds guitar and piano.
ELEVENLABS_STEM_LABELS: list[str] = ["vocals", "drums", "bass", "guitar", "piano", "other"]

# Generating a track can take well over two minutes for long durations (up to
# 10 min of audio), so music generation calls get a generous read timeout.
# Plan creation is a fast, credit-free endpoint and keeps a tighter budget.
# Stem separation is documented as high-latency and uploads the source file,
# so it gets a long read timeout plus extra write headroom for the upload.
_GENERATION_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)
_PLAN_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
_STEMS_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


class ElevenLabsError(Exception):
    """Raised when the ElevenLabs API returns an error or is unreachable."""


def _validate_duration(duration: float | None) -> None:
    """Raise ElevenLabsError if duration is outside the API limits (3s–600s)."""
    if duration is not None and not (DURATION_MIN_S <= duration <= DURATION_MAX_S):
        raise ElevenLabsError(
            f"Invalid duration {duration}s: ElevenLabs requires between "
            f"{int(DURATION_MIN_S)}s and {int(DURATION_MAX_S)}s (10 min)."
        )


def _parse_stem_zip(content: bytes) -> dict[str, bytes]:
    """Parse a stem-separation ZIP response into a label → audio-bytes mapping.

    Raises ElevenLabsError if the archive is malformed or contains no stems.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ElevenLabsError("ElevenLabs stem separation failed: response is not a valid ZIP archive") from exc

    stems: dict[str, bytes] = {}
    try:
        with archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).stem.lower()
                label = next((known for known in ELEVENLABS_STEM_LABELS if known in name), name)
                if label in stems:
                    # Two entries matched the same known label — keep both by
                    # falling back to the filename stem instead of overwriting.
                    label = name
                stems[label] = archive.read(info)
    except (zipfile.BadZipFile, zlib.error, OSError, ValueError) as exc:
        # Corruption can also surface mid-read (bad CRC, truncated entry) —
        # normalize to the documented ElevenLabsError contract.
        raise ElevenLabsError("ElevenLabs stem separation failed: ZIP archive entry is corrupted") from exc

    if not stems:
        raise ElevenLabsError("ElevenLabs stem separation failed: ZIP archive contains no stems")
    return stems


class ElevenLabsClient:
    """HTTP client for the ElevenLabs music generation API."""

    def __init__(self, api_key: str, output_format: str = "mp3_44100_128") -> None:
        """Initialise the client with an API key and default output format."""
        self.api_key = api_key
        self.output_format = output_format
        self._headers = {"xi-api-key": api_key}

    def generate(
        self,
        prompt: str,
        duration: float | None = None,
        instrumental: bool = False,
        style: str | None = None,
        lyrics: str | None = None,
    ) -> bytes:
        """Generate music via POST /v1/music and return the raw audio bytes.

        Args:
            prompt: Text description of the music.
            duration: Target duration in seconds (converted to music_length_ms).
            instrumental: If True, sets force_instrumental in the request body.
            style: Comma-separated style descriptors forwarded to the API.
            lyrics: Inline lyrics text forwarded to the API.

        Raises:
            ElevenLabsError: On out-of-range duration, HTTP error, or connection failure.
        """
        _validate_duration(duration)
        body: dict = {"prompt": prompt}
        if duration is not None:
            body["music_length_ms"] = int(duration * 1000)
        if instrumental:
            body["force_instrumental"] = True
        if style is not None:
            body["style"] = style
        if lyrics is not None:
            body["lyrics"] = lyrics

        try:
            response = httpx.post(
                f"{_BASE_URL}/v1/music",
                json=body,
                headers=self._headers,
                params={"output_format": self.output_format},
                timeout=_GENERATION_TIMEOUT,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise ElevenLabsError(f"ElevenLabs generate failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs generate failed: {exc}") from exc

    def create_plan(
        self,
        prompt: str,
        duration: float | None = None,
        model_id: str | None = None,
    ) -> dict:
        """Create a composition plan via POST /v1/music/plan and return the parsed JSON.

        Args:
            prompt: Text description to compose a plan from.
            duration: Target plan length in seconds (converted to music_length_ms).
            model_id: Optional model override (e.g. 'music_v1').

        Raises:
            ElevenLabsError: On out-of-range duration, HTTP error, or connection failure.
        """
        _validate_duration(duration)
        body: dict = {"prompt": prompt}
        if duration is not None:
            body["music_length_ms"] = int(duration * 1000)
        if model_id is not None:
            body["model_id"] = model_id

        try:
            response = httpx.post(
                f"{_BASE_URL}/v1/music/plan",
                json=body,
                headers=self._headers,
                timeout=_PLAN_TIMEOUT,
            )
            response.raise_for_status()
            plan = response.json()
        except httpx.HTTPStatusError as exc:
            raise ElevenLabsError(f"ElevenLabs plan creation failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs plan creation failed: {exc}") from exc
        except ValueError as exc:
            raise ElevenLabsError("ElevenLabs plan creation failed: invalid JSON response") from exc
        if not isinstance(plan, dict):
            raise ElevenLabsError("ElevenLabs plan creation failed: invalid plan payload type")
        return plan

    def generate_from_plan(
        self,
        composition_plan: dict,
        respect_durations: bool = True,
        seed: int | None = None,
    ) -> bytes:
        """Generate music from a composition plan via POST /v1/music and return audio bytes.

        The API forbids combining ``composition_plan`` with ``prompt`` or
        ``force_instrumental``, so only plan-mode fields are sent.

        Args:
            composition_plan: Plan dict as returned by :meth:`create_plan`.
            respect_durations: If True, sections strictly honor their duration_ms.
            seed: Optional random seed (only valid in plan mode).

        Raises:
            ElevenLabsError: On HTTP error or connection failure.
        """
        body: dict = {
            "composition_plan": composition_plan,
            "respect_sections_durations": respect_durations,
        }
        if seed is not None:
            body["seed"] = seed

        try:
            response = httpx.post(
                f"{_BASE_URL}/v1/music",
                json=body,
                headers=self._headers,
                params={"output_format": self.output_format},
                timeout=_GENERATION_TIMEOUT,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as exc:
            raise ElevenLabsError(f"ElevenLabs plan generation failed: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs plan generation failed: {exc}") from exc

    def separate_stems(
        self,
        audio_path: str | Path,
        stem_variation_id: str = "six_stems_v1",
    ) -> dict[str, bytes]:
        """Separate an audio file into stems via POST /v1/music/stem-separation.

        Uploads the file as multipart form data and parses the ZIP response
        into a mapping of stem label to audio bytes. ZIP entries are matched
        against :data:`ELEVENLABS_STEM_LABELS` by filename; unrecognised
        entries fall back to their filename stem as the label.

        Args:
            audio_path: Path to the audio file to separate.
            stem_variation_id: Separation model ('six_stems_v1' or 'two_stems_v1').

        Raises:
            ElevenLabsError: On unreadable input file, HTTP error, connection
                failure, or a malformed/empty ZIP response.
        """
        audio_path = Path(audio_path)
        try:
            with open(audio_path, "rb") as fh:
                response = httpx.post(
                    f"{_BASE_URL}/v1/music/stem-separation",
                    files={"file": (audio_path.name, fh)},
                    data={"stem_variation_id": stem_variation_id},
                    headers=self._headers,
                    params={"output_format": self.output_format},
                    timeout=_STEMS_TIMEOUT,
                )
            response.raise_for_status()
        except OSError as exc:
            raise ElevenLabsError(f"ElevenLabs stem separation failed: cannot read {audio_path}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            # Include the response body (truncated) — 422 carries the reason
            # (e.g. file too large), which the bare status code would hide.
            detail = (exc.response.text or "").strip()[:200]
            message = f"ElevenLabs stem separation failed: {exc.response.status_code}"
            if detail:
                message = f"{message} — {detail}"
            raise ElevenLabsError(message) from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs stem separation failed: {exc}") from exc
        return _parse_stem_zip(response.content)

    def validate_key(self, timeout: float = 5.0) -> bool:
        """Validate the API key via GET /v1/user. Returns True if valid, False otherwise."""
        try:
            response = httpx.get(
                f"{_BASE_URL}/v1/user",
                headers=self._headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False
