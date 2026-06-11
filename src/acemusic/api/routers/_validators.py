"""Field-validator helpers shared by the generation and preset schemas.

Both ``GenerationRequest`` and ``_PresetParams`` validate the same enum-like
fields against :mod:`acemusic.constants`; delegating to these functions keeps
the two schemas from drifting. ``None`` passes through so the same helper
serves required fields (generation's ``format``) and nullable preset fields.
"""

from acemusic.constants import VALID_FORMATS, VALID_MODELS, VALID_TIME_SIGNATURES


def validate_format(value: str | None) -> str | None:
    if value is not None and value not in VALID_FORMATS:
        raise ValueError(f"format must be one of {sorted(VALID_FORMATS)}")
    return value


def validate_model(value: str | None) -> str | None:
    if value is not None and value not in VALID_MODELS:
        raise ValueError(f"model must be one of {sorted(VALID_MODELS)}")
    return value


def validate_time_signature(value: str | None) -> str | None:
    if value is not None and value not in VALID_TIME_SIGNATURES:
        raise ValueError(f"time_signature must be one of {sorted(VALID_TIME_SIGNATURES)}")
    return value
