"""Audio format → MIME type mapping (US-9.3)."""

_AUDIO_CONTENT_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "opus": "audio/opus",
}

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def get_audio_content_type(format: str | None) -> str:
    """Return the MIME type for an audio ``format`` name (case-insensitive).

    Unknown, blank, or missing formats fall back to ``application/octet-stream``
    so the endpoint can always serve bytes even for formats added to storage
    before this map.
    """
    if not format:
        return DEFAULT_CONTENT_TYPE
    return _AUDIO_CONTENT_TYPES.get(format.strip().lower(), DEFAULT_CONTENT_TYPE)
