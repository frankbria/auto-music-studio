"""In-memory audio format conversion for API responses (US-9.3).

Buffer-based counterpart of :func:`acemusic.audio.export_audio` (US-7.1) with
the same codec settings, so a clip downloaded as ``?format=mp3`` matches what
the CLI's export command would produce. Conversion (other than wav decode)
requires ffmpeg on the host.
"""

import io

CONVERSION_FORMATS = ("wav", "flac", "mp3")


def convert_audio_format(audio_bytes: bytes, source_format: str, target_format: str) -> bytes:
    """Convert ``audio_bytes`` from ``source_format`` to ``target_format``.

    Codec settings mirror ``export_audio``: wav is 48 kHz 24-bit PCM, flac is
    lossless at the source rate, mp3 is 320 kbps CBR. Raises ``ValueError``
    for an unsupported target format.
    """
    if target_format not in CONVERSION_FORMATS:
        raise ValueError(f"Unsupported conversion format: {target_format!r}. Expected one of {CONVERSION_FORMATS}.")

    from pydub import AudioSegment

    # Always pass format= — detection would shell out to ffprobe, which is not
    # installed everywhere (e.g. CI), and the clip's stored format is known.
    segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=source_format)

    buffer = io.BytesIO()
    if target_format == "wav":
        segment.export(buffer, format="wav", parameters=["-acodec", "pcm_s24le", "-ar", "48000"])
    elif target_format == "flac":
        segment.export(buffer, format="flac")
    else:  # mp3
        segment.export(buffer, format="mp3", bitrate="320k")
    return buffer.getvalue()
