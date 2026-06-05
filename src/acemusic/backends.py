"""Backend selection and capability routing (#95).

Central, dependency-free helpers shared by all backend-capable commands so
routing and validation stay consistent. The CLI translates a ``BackendError``
into a friendly message + exit code.

Backends:
- ``auto``       — prefer ACE-Step. Commands that implement fallback (currently
                   ``generate``) drop to ElevenLabs on a transport failure; other
                   commands run on ACE-Step. ``auto`` never fails just because one
                   engine is unavailable when another can do the job.
- ``ace-step``   — ACE-Step only; never silently switches engines.
- ``elevenlabs`` — ElevenLabs only.
"""

from __future__ import annotations

VALID_BACKENDS: tuple[str, ...] = ("auto", "ace-step", "elevenlabs")
DEFAULT_BACKEND = "auto"

# Which concrete engines support each operation. ElevenLabs entries expand as
# the sibling issues land (#99 mashup). #96 added first-class generate/sounds
# and composition plans ("compose"); #97 added stem separation; #98 added
# inpainting (repaint/extend).
_CAPABILITIES: dict[str, set[str]] = {
    "generate": {"ace-step", "elevenlabs"},
    "sample": {"ace-step", "elevenlabs"},
    "sounds": {"ace-step", "elevenlabs"},
    "compose": {"elevenlabs"},
    "stems": {"ace-step", "elevenlabs"},
    "midi": {"ace-step"},
    "remaster": {"ace-step"},
    "extend": {"ace-step", "elevenlabs"},
    "cover": {"ace-step"},
    "repaint": {"ace-step", "elevenlabs"},
    "mashup": {"ace-step"},
    "export": {"ace-step"},
}


class BackendError(ValueError):
    """Raised for an invalid backend value or an unsupported operation."""


def resolve_backend(cli_value: str | None, config_backend: str | None = None) -> str:
    """Resolve the effective backend.

    Precedence: explicit CLI value > config default (``ACEMUSIC_BACKEND``) >
    :data:`DEFAULT_BACKEND`. Case-insensitive and whitespace-trimmed.

    Raises:
        BackendError: if the resolved value is not a known backend.
    """
    raw = cli_value if cli_value is not None else (config_backend or DEFAULT_BACKEND)
    backend = raw.strip().lower()
    if backend not in VALID_BACKENDS:
        raise BackendError(f"Invalid backend {raw!r}. Choose one of: {', '.join(VALID_BACKENDS)}.")
    return backend


def supports(backend: str, operation: str) -> bool:
    """Return True if ``backend`` can perform ``operation``.

    ``auto`` supports an operation if *any* concrete engine does (it will route
    to a capable one at runtime).
    """
    engines = _CAPABILITIES.get(operation, set())
    if backend == "auto":
        return bool(engines)
    return backend in engines


def ensure_supports(backend: str, operation: str) -> None:
    """Raise :class:`BackendError` if ``backend`` cannot perform ``operation``."""
    if not supports(backend, operation):
        capable = sorted(_CAPABILITIES.get(operation, set()))
        capable_str = ", ".join(capable) if capable else "no backend yet"
        raise BackendError(f"Backend {backend!r} does not support '{operation}'. Supported by: {capable_str}.")
