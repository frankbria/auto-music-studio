"""Backend selection and capability routing (#95).

Central, dependency-free helpers shared by all backend-capable commands so
routing and validation stay consistent. The CLI translates a ``BackendError``
into a friendly message + exit code.

Backends:
- ``auto``       — pick a capable engine; ACE-Step first, fall back to ElevenLabs
                   on a transport failure (the historical default behavior).
- ``ace-step``   — ACE-Step only; never silently switches engines.
- ``elevenlabs`` — ElevenLabs only.
"""

from __future__ import annotations

VALID_BACKENDS: tuple[str, ...] = ("auto", "ace-step", "elevenlabs")
DEFAULT_BACKEND = "auto"

# Which concrete engines support each operation. ElevenLabs entries expand as
# the sibling issues land (#96 generate/plans, #97 stems, #98 inpainting,
# #99 mashup); for now ElevenLabs only does text-to-music generation.
_CAPABILITIES: dict[str, set[str]] = {
    "generate": {"ace-step", "elevenlabs"},
    "sample": {"ace-step", "elevenlabs"},
    "stems": {"ace-step"},
    "midi": {"ace-step"},
    "remaster": {"ace-step"},
    "extend": {"ace-step"},
    "cover": {"ace-step"},
    "repaint": {"ace-step"},
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
