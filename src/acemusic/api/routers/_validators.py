"""Validator helpers shared by the generation, iterative and preset schemas.

Both ``GenerationRequest`` and ``_PresetParams`` validate the same enum-like
fields against :mod:`acemusic.constants`; delegating to these functions keeps
the two schemas from drifting. ``None`` passes through so the same helper
serves required fields (generation's ``format``) and nullable preset fields.

:func:`require_voice_model` is the odd one out — it does a database lookup and
raises ``HTTPException`` rather than ``ValueError``, because a voice can only be
checked once the caller is resolved. It lives here so the generation and
iterative routers apply exactly the same rule (US-25.4).
"""

from fastapi import HTTPException, status

from acemusic.constants import VALID_FORMATS, VALID_MODELS, VALID_TIME_SIGNATURES

from ..services import voice_models as voice_service


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


async def require_voice_model(voice_model_id: str | None, user_id: str) -> None:
    """Reject a generation naming a voice the caller cannot sing with (US-25.4).

    Runs *before* credits are deducted, so an unusable voice never costs anything.
    404 covers both "no such id" and "someone else's voice"; a voice that exists but
    is still training is a 409, which is a different thing to tell the musician.
    """
    if voice_model_id is None:
        return

    try:
        await voice_service.weights_for(voice_model_id, user_id)
    except voice_service.VoiceModelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voice_service.VoiceModelNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
