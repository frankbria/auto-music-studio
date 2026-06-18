"""Shared mastering-service contract (US-12.3).

LANDR and Bakuage are mastered as fallbacks to Dolby.io (US-12.2). To let the
mastering job handler treat all three backends interchangeably, this module
defines the contract they share:

- :class:`MasteringOutput` — the unified result of one mastering run (the
  mastered audio bytes, the analysis metrics, and the name of the service that
  produced them). The handler wraps this into ``{"clip_ids", "service",
  "target_lufs", "metrics"}`` after storing the audio.
- :class:`MasteringError` — the common base for every backend's failure mode, so
  the orchestrator can catch a single type when deciding whether to fall back.
- :class:`MasteringService` — the :class:`typing.Protocol` each backend
  implements: a single :meth:`master` entrypoint that drives the full
  upload -> submit -> poll -> download workflow and returns a
  :class:`MasteringOutput`. Keeping the surface to one method hides each
  provider's different granular steps (Dolby's presigned upload + preview
  handles, Bakuage's simpler REST flow) behind a uniform call.

Each backend raises its own ``*Error`` subclass (e.g. :class:`DolbyError`) so a
caller can distinguish the source while the orchestrator catches the shared
base. Request validation (profile / target_lufs / format) happens in the
router/service layer *before* a backend is called, so any :class:`MasteringError`
raised by a backend is a service-side failure eligible for fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class MasteringOutput:
    """The normalized result of one mastering run across any backend.

    ``audio_bytes`` is the mastered audio (to be stored as a clip); ``metrics``
    is the provider's loudness/EQ/stereo analysis (may be partial for backends
    that report fewer measurements); ``service`` names the backend that produced
    it so a fallback run can be distinguished from the requested one.
    """

    audio_bytes: bytes
    metrics: dict[str, Any]
    service: str


class MasteringError(Exception):
    """Base for every mastering-backend failure (Dolby / LANDR / Bakuage).

    Subclassed by each backend's own error (e.g. :class:`DolbyError`) so callers
    can catch the common base for fallback decisions while still attributing the
    source. Request validation lives upstream, so a raised :class:`MasteringError`
    indicates the backend itself failed.
    """


@runtime_checkable
class MasteringService(Protocol):
    """The contract every mastering backend implements.

    A single :meth:`master` entrypoint hides each provider's upload/submit/poll/
    download dance behind one call, returning a normalized
    :class:`MasteringOutput`. ``service`` is the backend's canonical name
    (``"dolby"`` / ``"landr"`` / ``"bakuage"``) used for dispatch and result
    attribution.
    """

    service: str

    def master(
        self, audio_bytes: bytes, filename: str, profile: str, target_lufs: float, output_format: str
    ) -> MasteringOutput:
        """Master ``audio_bytes`` and return the mastered audio plus metrics.

        ``filename`` disambiguates the upload key (callers include the job id so
        concurrent masters on the same clip never collide); ``profile`` is the
        platform profile vocabulary (``streaming``/``soundcloud``/``club``/
        ``vinyl``/``custom``); ``target_lufs`` the resolved loudness target;
        ``output_format`` the container to produce (``wav``/``mp3``/``flac``).
        """
        ...
