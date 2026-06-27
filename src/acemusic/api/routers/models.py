"""Public models-list router (US-16.4), mounted under ``/api/v1/models``.

Exposes the ACE-Step model registry (:data:`acemusic.constants.MODELS`) with
display-friendly metadata so the web creation UI can render a model selector
without hard-coding model details on the frontend. Keeping display name,
category, and the Pro-tier flag server-side means new models or re-grouping
ship without a frontend change.

The endpoint is **public** (no auth): model info is not sensitive, and the
selector renders before a user is necessarily authenticated. The ``pro_only``
flag is a display hint only — generation requests are not yet tier-enforced.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from acemusic.constants import MODELS

router = APIRouter(prefix="/models", tags=["models"])

# Display metadata layered over the raw MODELS registry. Keyed by model key.
# ``category`` drives the UI grouping; ``pro_only`` marks the premium XL tier.
# Source-of-truth model data (description, vram, steps, dit_size) still comes
# from constants.MODELS so the two can't drift on the technical facts.
_DISPLAY: dict[str, dict[str, object]] = {
    "turbo": {"display_name": "Turbo Model", "category": "Turbo", "pro_only": False},
    "base": {"display_name": "Standard Model", "category": "Standard", "pro_only": False},
    "sft": {"display_name": "Standard Model (Fine-tuned)", "category": "Standard", "pro_only": False},
    "xl-base": {"display_name": "Latest Model (XL)", "category": "XL", "pro_only": True},
    "xl-sft": {"display_name": "Latest Model (XL, Fine-tuned)", "category": "XL", "pro_only": True},
    "xl-turbo": {"display_name": "Turbo XL", "category": "XL", "pro_only": True},
}


class ModelInfo(BaseModel):
    """One selectable model variant with display + technical metadata."""

    key: str
    display_name: str
    category: str
    description: str
    pro_only: bool
    vram: str
    steps: str
    dit_size: str


class ModelsListResponse(BaseModel):
    """All available models for the creation-mode selector."""

    models: list[ModelInfo]


def _build_models() -> list[ModelInfo]:
    out: list[ModelInfo] = []
    for key, meta in MODELS.items():
        display = _DISPLAY.get(
            key,
            # Fallback so a model added to MODELS without display metadata still
            # renders (un-grouped, non-Pro) rather than vanishing from the list.
            {"display_name": key, "category": "Other", "pro_only": False},
        )
        out.append(
            ModelInfo(
                key=key,
                display_name=str(display["display_name"]),
                category=str(display["category"]),
                description=meta["description"],
                pro_only=bool(display["pro_only"]),
                vram=meta["vram"],
                steps=meta["steps"],
                dit_size=meta["dit_size"],
            )
        )
    return out


# MODELS and _DISPLAY are immutable module constants, so the response is built
# once at import time rather than per request.
_MODELS_LIST: list[ModelInfo] = _build_models()


@router.get("", response_model=ModelsListResponse)
def list_models() -> ModelsListResponse:
    """Return all model variants with display metadata for the UI selector."""
    return ModelsListResponse(models=_MODELS_LIST)
