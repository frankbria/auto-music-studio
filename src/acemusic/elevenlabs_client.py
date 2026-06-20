"""ElevenLabs cloud music generation client (US-2.5)."""

from __future__ import annotations

import io
import zipfile
import zlib
from pathlib import Path

import httpx

from acemusic import _http

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
# Uploading for inpainting (#98) is priced like a generation and the server
# inspects the audio (copyright check), so give it the same headroom as stems.
_UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


class ElevenLabsError(Exception):
    """Raised when the ElevenLabs API returns an error or is unreachable."""


# Composition plan sections must be 3s–120s each (SongSection.duration_ms),
# and the whole track is capped at 600s (music_length_ms limit).
SECTION_MIN_MS = 3_000
SECTION_MAX_MS = 120_000
TRACK_MAX_MS = int(DURATION_MAX_S * 1000)


def _split_keep_range(start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    """Split a keep range into contiguous chunks no longer than SECTION_MAX_MS.

    Uses the minimal number of equal-sized chunks so every chunk stays well
    above SECTION_MIN_MS (a range needing a split is >120s, so halves are >60s).
    """
    total = end_ms - start_ms
    chunks = -(-total // SECTION_MAX_MS)  # ceil division
    ranges: list[tuple[int, int]] = []
    chunk_start = start_ms
    for i in range(1, chunks + 1):
        chunk_end = start_ms + (total * i) // chunks
        ranges.append((chunk_start, chunk_end))
        chunk_start = chunk_end
    return ranges


def build_inpaint_plan(
    song_id: str,
    keep_ranges: list[tuple[int, int]],
    regenerate_range: tuple[int, int],
    prompt: str,
    style: str | None = None,
    lyrics: str | None = None,
) -> dict:
    """Build a composition plan that regenerates one section of a stored song.

    Keep ranges become sections referencing the uploaded song via
    ``source_from`` so their audio is preserved; the regenerate range becomes
    a plain section described by ``prompt``/``style``/``lyrics`` that the
    model fills in. Sections are emitted in chronological order.

    Args:
        song_id: ID returned by :meth:`ElevenLabsClient.upload_for_inpainting`.
        keep_ranges: ``(start_ms, end_ms)`` ranges of the source to keep.
            Empty ranges are skipped; ranges longer than 120s are split into
            multiple sections (the API caps sections at 120s).
        regenerate_range: The single ``(start_ms, end_ms)`` range to regenerate.
        prompt: Description of the regenerated section.
        style: Optional comma-separated style descriptors for the section.
        lyrics: Optional lyrics for the section (one line per text line).

    Raises:
        ElevenLabsError: If any non-empty range is shorter than 3s, the
            regenerate range is longer than 120s, or it is inverted/empty.
    """
    regen_start, regen_end = regenerate_range
    regen_duration = regen_end - regen_start
    if regen_duration <= 0:
        raise ElevenLabsError(f"Invalid regenerate range [{regen_start}ms, {regen_end}ms]: start must be before end.")
    if regen_duration < SECTION_MIN_MS:
        raise ElevenLabsError(
            f"Regenerate range is {regen_duration}ms but ElevenLabs sections must be at least "
            f"{SECTION_MIN_MS // 1000}s. Widen the region (e.g. adjust --start/--end or --duration)."
        )
    if regen_duration > SECTION_MAX_MS:
        raise ElevenLabsError(
            f"Regenerate range is {regen_duration}ms but ElevenLabs sections are capped at "
            f"{SECTION_MAX_MS // 1000}s (120s). Narrow the region or run multiple passes."
        )

    entries: list[tuple[int, int, bool]] = [(regen_start, regen_end, True)]
    for start_ms, end_ms in keep_ranges:
        duration = end_ms - start_ms
        if duration <= 0:
            continue
        if duration < SECTION_MIN_MS:
            raise ElevenLabsError(
                f"Kept range [{start_ms}ms, {end_ms}ms] is {duration}ms but ElevenLabs sections "
                f"must be at least {SECTION_MIN_MS // 1000}s. Move the repaint boundary so at "
                f"least 3s of audio is kept on that side, or extend the region to the clip edge."
            )
        for chunk_start, chunk_end in _split_keep_range(start_ms, end_ms):
            entries.append((chunk_start, chunk_end, False))
    entries.sort(key=lambda entry: entry[0])

    # The whole composed track is capped at 600s — fail here so callers can
    # validate before paying for an upload that could never compose.
    total_ms = sum(end_ms - start_ms for start_ms, end_ms, _ in entries)
    if total_ms > TRACK_MAX_MS:
        raise ElevenLabsError(
            f"Inpainting plan totals {total_ms}ms but ElevenLabs tracks are capped at "
            f"{TRACK_MAX_MS // 1000}s (10 min). Use a shorter source clip or a smaller extension."
        )

    positive_styles = [prompt]
    if style:
        positive_styles.extend(part.strip() for part in style.split(",") if part.strip())
    lines = [line.strip() for line in lyrics.splitlines() if line.strip()] if lyrics else []

    sections: list[dict] = []
    keep_index = 0
    for start_ms, end_ms, is_regen in entries:
        if is_regen:
            sections.append(
                {
                    "section_name": "Regenerated",
                    "positive_local_styles": positive_styles,
                    "negative_local_styles": [],
                    "duration_ms": end_ms - start_ms,
                    "lines": lines,
                }
            )
        else:
            keep_index += 1
            sections.append(
                {
                    "section_name": f"Keep {keep_index}",
                    "positive_local_styles": [],
                    "negative_local_styles": [],
                    "duration_ms": end_ms - start_ms,
                    "lines": [],
                    "source_from": {
                        "song_id": song_id,
                        "range": {"start_ms": start_ms, "end_ms": end_ms},
                    },
                }
            )

    return {
        "positive_global_styles": [],
        "negative_global_styles": [],
        "sections": sections,
    }


def build_mashup_plan(
    sources: list[tuple[str, int]],
    style: str | None = None,
) -> dict:
    """Build a composition plan that combines whole sections from stored songs.

    Each source becomes one (or more, when longer than 120s) ``source_from``
    sections covering its full [0, duration] range, emitted in the given
    order. Unlike ACE-Step's audio-level mashup, ElevenLabs recombines at the
    section/composition level — sources play in sequence with the optional
    ``style`` applied globally to unify the result.

    Args:
        sources: ``(song_id, duration_ms)`` pairs in playback order. The
            song_ids come from :meth:`ElevenLabsClient.upload_for_inpainting`.
        style: Optional comma-separated style descriptors applied globally.

    Raises:
        ElevenLabsError: With fewer than two sources, a source shorter than
            3s (named in the message), or a combined duration over 600s.
    """
    if len(sources) < 2:
        raise ElevenLabsError("Mashup needs at least two source clips.")

    total_ms = 0
    for song_id, duration_ms in sources:
        if duration_ms < SECTION_MIN_MS:
            raise ElevenLabsError(
                f"Source {song_id} is {duration_ms}ms but ElevenLabs sections must be at "
                f"least {SECTION_MIN_MS // 1000}s. Use a longer clip."
            )
        total_ms += duration_ms
    if total_ms > TRACK_MAX_MS:
        raise ElevenLabsError(
            f"Combined sources total {total_ms}ms but ElevenLabs tracks are capped at "
            f"{TRACK_MAX_MS // 1000}s (10 min). Use fewer or shorter clips."
        )

    sections: list[dict] = []
    for index, (song_id, duration_ms) in enumerate(sources, start=1):
        for chunk_index, (chunk_start, chunk_end) in enumerate(_split_keep_range(0, duration_ms), start=1):
            suffix = f".{chunk_index}" if chunk_end - chunk_start != duration_ms else ""
            sections.append(
                {
                    "section_name": f"Source {index}{suffix}",
                    "positive_local_styles": [],
                    "negative_local_styles": [],
                    "duration_ms": chunk_end - chunk_start,
                    "lines": [],
                    "source_from": {
                        "song_id": song_id,
                        "range": {"start_ms": chunk_start, "end_ms": chunk_end},
                    },
                }
            )

    global_styles = [part.strip() for part in style.split(",") if part.strip()] if style else []
    return {
        "positive_global_styles": global_styles,
        "negative_global_styles": [],
        "sections": sections,
    }


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
            response = _http.request(
                httpx.post,
                f"{_BASE_URL}/v1/music",
                headers=self._headers,
                json=body,
                params={"output_format": self.output_format},
                timeout=_GENERATION_TIMEOUT,
                retries=0,
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
            response = _http.request(
                httpx.post,
                f"{_BASE_URL}/v1/music/plan",
                headers=self._headers,
                json=body,
                timeout=_PLAN_TIMEOUT,
                retries=0,
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
            response = _http.request(
                httpx.post,
                f"{_BASE_URL}/v1/music",
                headers=self._headers,
                json=body,
                params={"output_format": self.output_format},
                timeout=_GENERATION_TIMEOUT,
                retries=0,
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
                response = _http.request(
                    httpx.post,
                    f"{_BASE_URL}/v1/music/stem-separation",
                    headers=self._headers,
                    files={"file": (audio_path.name, fh)},
                    data={"stem_variation_id": stem_variation_id},
                    params={"output_format": self.output_format},
                    timeout=_STEMS_TIMEOUT,
                    retries=0,
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

    def upload_for_inpainting(self, audio_path: str | Path) -> str:
        """Upload an audio file for inpainting via POST /v1/music/upload.

        The uploaded song can then be referenced by ``song_id`` from a
        composition plan section's ``source_from`` to keep ranges of the
        original audio while regenerating others. Only available to accounts
        with access to the ElevenLabs inpainting feature; uploading is priced
        the same as a generation.

        Args:
            audio_path: Path to the audio file to upload.

        Returns:
            The ``song_id`` assigned to the uploaded song.

        Raises:
            ElevenLabsError: On unreadable input file, HTTP error, connection
                failure, or a response without a ``song_id``.
        """
        audio_path = Path(audio_path)
        try:
            with open(audio_path, "rb") as fh:
                response = _http.request(
                    httpx.post,
                    f"{_BASE_URL}/v1/music/upload",
                    headers=self._headers,
                    # No explicit content-type: httpx infers it from the
                    # filename (e.g. audio/x-wav, audio/mpeg) — same pattern
                    # proven against the live API by separate_stems (#97).
                    files={"file": (audio_path.name, fh)},
                    timeout=_UPLOAD_TIMEOUT,
                    retries=0,
                )
            response.raise_for_status()
        except OSError as exc:
            raise ElevenLabsError(f"ElevenLabs upload failed: cannot read {audio_path}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            # Include the response body (truncated) — 403 carries the
            # enterprise-gating reason and 422 the validation detail.
            detail = (exc.response.text or "").strip()[:200]
            message = f"ElevenLabs upload failed: {exc.response.status_code}"
            if detail:
                message = f"{message} — {detail}"
            raise ElevenLabsError(message) from exc
        except httpx.RequestError as exc:
            raise ElevenLabsError(f"ElevenLabs upload failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ElevenLabsError("ElevenLabs upload failed: invalid JSON response") from exc
        song_id = payload.get("song_id") if isinstance(payload, dict) else None
        if not song_id:
            raise ElevenLabsError("ElevenLabs upload failed: response contains no song_id")
        return str(song_id)

    def validate_key(self, timeout: float = 5.0) -> bool:
        """Validate the API key via GET /v1/user. Returns True if valid, False otherwise."""
        try:
            response = _http.request(
                httpx.get,
                f"{_BASE_URL}/v1/user",
                headers=self._headers,
                timeout=timeout,
                retries=0,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False
