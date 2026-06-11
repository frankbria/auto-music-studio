"""Preset CRUD router (US-9.5), mounted under ``/api/v1/presets``.

Endpoints (all require a valid Bearer access token and operate only on the
authenticated user's presets):

* ``POST   /presets``      → create (201; 409 on duplicate name)
* ``GET    /presets``      → list the user's presets
* ``GET    /presets/{id}`` → single preset (404 if missing/not owned)
* ``PATCH  /presets/{id}`` → partial update; an explicit ``null`` clears a
  parameter (409 on duplicate name)
* ``DELETE /presets/{id}`` → delete (204)

Request/response schemas live here (same convention as the workspaces router);
persistence lives in :mod:`acemusic.api.services.presets`. Parameter fields and
bounds mirror :class:`~acemusic.api.routers.generation.GenerationRequest` — a
preset may only store values the generate endpoint would accept — except the
cross-field rules (mode/sound_type coupling, the song duration floor), which
are enforced when the preset is applied to a request, since they depend on the
final merged parameter set.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.constants import (
    BPM_MAX,
    BPM_MIN,
    DURATION_MAX,
    INFERENCE_STEPS_MAX,
    STYLE_INFLUENCE_MAX,
    STYLE_INFLUENCE_MIN,
    VALID_FORMATS,
    VALID_MODELS,
    VALID_TIME_SIGNATURES,
    WEIRDNESS_MAX,
    WEIRDNESS_MIN,
)

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import PRESET_PARAM_FIELDS, Preset
from ..services import presets as preset_service
from .generation import (
    _KEY_MAX_LENGTH,
    _LYRICS_MAX_LENGTH,
    _SEED_MAX,
    _SEED_MIN,
    _STYLE_MAX_LENGTH,
    _VOCAL_LANGUAGE_MAX_LENGTH,
)

PRESET_NAME_MAX_LENGTH = 100

# Router-level dependency gates every route; endpoints additionally take
# ``current`` to read the identity.
router = APIRouter(prefix="/presets", tags=["presets"], dependencies=[Depends(get_current_user)])


def _validate_name(value: str) -> str:
    """Strip surrounding whitespace and reject names that are blank after it."""
    value = value.strip()
    if not value:
        raise ValueError("Preset name must not be blank.")
    return value


class _PresetParams(BaseModel):
    """The optional generation parameter snapshot shared by create and update.

    Field shapes and bounds mirror ``GenerationRequest`` so a stored preset is
    always applicable; every field is nullable because a preset pins down only
    what the user chose to save.
    """

    model_config = ConfigDict(extra="forbid")

    style: Annotated[str, Field(max_length=_STYLE_MAX_LENGTH)] | None = None
    lyrics: Annotated[str, Field(max_length=_LYRICS_MAX_LENGTH)] | None = None
    vocal_language: Annotated[str, Field(max_length=_VOCAL_LANGUAGE_MAX_LENGTH)] | None = None
    instrumental: bool | None = None
    bpm: Annotated[int, Field(ge=BPM_MIN, le=BPM_MAX)] | Literal["auto"] | None = None
    key: Annotated[str, Field(max_length=_KEY_MAX_LENGTH)] | None = None
    time_signature: str | None = None
    duration: Annotated[float, Field(gt=0, le=DURATION_MAX)] | None = None
    seed: Annotated[int, Field(ge=_SEED_MIN, le=_SEED_MAX)] | None = None
    inference_steps: Annotated[int, Field(gt=0, le=INFERENCE_STEPS_MAX)] | None = None
    model: str | None = None
    weirdness: Annotated[int, Field(ge=WEIRDNESS_MIN, le=WEIRDNESS_MAX)] | None = None
    style_influence: Annotated[int, Field(ge=STYLE_INFLUENCE_MIN, le=STYLE_INFLUENCE_MAX)] | None = None
    format: str | None = None
    thinking: bool | None = None
    mode: Literal["song", "sound"] | None = None
    sound_type: Literal["one-shot", "loop"] | None = None

    @field_validator("format")
    @classmethod
    def _check_format(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(VALID_FORMATS)}")
        return value

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_MODELS:
            raise ValueError(f"model must be one of {sorted(VALID_MODELS)}")
        return value

    @field_validator("time_signature")
    @classmethod
    def _check_time_signature(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_TIME_SIGNATURES:
            raise ValueError(f"time_signature must be one of {sorted(VALID_TIME_SIGNATURES)}")
        return value


class PresetCreate(_PresetParams):
    name: Annotated[str, Field(min_length=1, max_length=PRESET_NAME_MAX_LENGTH)]

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name(value)


class PresetUpdate(_PresetParams):
    """Partial update. Only explicitly-sent fields are applied; sending
    ``null`` for a parameter clears it. The name cannot be cleared."""

    name: Annotated[str, Field(min_length=1, max_length=PRESET_NAME_MAX_LENGTH)] | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return value if value is None else _validate_name(value)

    @model_validator(mode="after")
    def _reject_null_name(self) -> "PresetUpdate":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Preset name cannot be cleared.")
        return self


class PresetResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime | None

    style: str | None
    lyrics: str | None
    vocal_language: str | None
    instrumental: bool | None
    bpm: int | Literal["auto"] | None
    key: str | None
    time_signature: str | None
    duration: float | None
    seed: int | None
    inference_steps: int | None
    model: str | None
    weirdness: int | None
    style_influence: int | None
    format: str | None
    thinking: bool | None
    mode: Literal["song", "sound"] | None
    sound_type: Literal["one-shot", "loop"] | None

    @classmethod
    def from_preset(cls, preset: Preset) -> "PresetResponse":
        return cls(
            id=str(preset.id),
            name=preset.name,
            created_at=preset.created_at,
            updated_at=preset.updated_at,
            **{field: getattr(preset, field) for field in PRESET_PARAM_FIELDS},
        )


class PresetListResponse(BaseModel):
    presets: list[PresetResponse]
    total: int


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    body: PresetCreate,
    current: CurrentUser = Depends(require_existing_user),
) -> PresetResponse:
    params = body.model_dump(exclude={"name"})
    preset = await preset_service.create_preset(current.user_id, body.name, params)
    return PresetResponse.from_preset(preset)


@router.get("", response_model=PresetListResponse)
async def list_presets(current: CurrentUser = Depends(require_existing_user)) -> PresetListResponse:
    presets = await preset_service.list_presets(current.user_id)
    return PresetListResponse(presets=[PresetResponse.from_preset(p) for p in presets], total=len(presets))


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> PresetResponse:
    preset = await preset_service.get_preset(preset_id, current.user_id)
    return PresetResponse.from_preset(preset)


@router.patch("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: str,
    body: PresetUpdate,
    current: CurrentUser = Depends(require_existing_user),
) -> PresetResponse:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        preset = await preset_service.get_preset(preset_id, current.user_id)
    else:
        preset = await preset_service.update_preset(preset_id, current.user_id, updates)
    return PresetResponse.from_preset(preset)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> Response:
    await preset_service.delete_preset(preset_id, current.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
