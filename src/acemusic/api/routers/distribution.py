"""Distribution endpoints — SoundCloud account-linking and upload (US-13.2).

Mounted under ``/api/v1/distribution`` and gated behind a valid Bearer token:

* ``POST   /soundcloud/connect``   → start the OAuth link, return the authorize URL
* ``POST   /soundcloud/callback``  → finish the link, persist the connection
* ``GET    /soundcloud/status``    → report whether the user is linked
* ``POST   /soundcloud/upload``    → upload an owned clip as a SoundCloud track
* ``DELETE /soundcloud/connect``   → unlink the SoundCloud account (idempotent)

The OAuth/PKCE/token mechanics live in :mod:`acemusic.api.services.soundcloud`;
this router is the HTTP surface (cookies, status codes, request/response shapes).
"""

import asyncio
import logging
from datetime import datetime

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError

from acemusic.storage import StorageBackend, get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import Clip, SoundCloudConnection
from ..models.common import utcnow
from ..services import clips as clip_service, soundcloud as sc
from ..settings import ApiSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/distribution", tags=["distribution"], dependencies=[Depends(get_current_user)])


# --- request / response models ----------------------------------------------
class ConnectResponse(BaseModel):
    authorization_url: str


class CallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    state: str


class StatusResponse(BaseModel):
    connected: bool
    soundcloud_username: str | None = None
    connected_at: datetime | None = None
    token_valid: bool | None = None


class MetadataOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    genre: str | None = None
    description: str | None = None
    bpm: int | None = None
    key_signature: str | None = None
    isrc: str | None = None
    sharing: str | None = Field(default=None, pattern="^(public|private)$")


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str
    metadata_overrides: MetadataOverrides = Field(default_factory=MetadataOverrides)


class UploadResponse(BaseModel):
    track_id: str
    permalink_url: str | None = None


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def _cookie_path(request: Request) -> str:
    """Scope the link cookies to the distribution prefix (e.g. ``/api/v1/distribution``).

    Both ``/soundcloud/connect`` and ``/soundcloud/callback`` resolve to the same
    path, so a cookie set at connect is sent to (and cleared by) the callback.
    """
    path = request.url.path
    marker = "/soundcloud/"
    if marker in path:
        return path.rsplit(marker, 1)[0] or "/"
    return "/"


def _set_link_cookie(response: Response, request: Request, settings: ApiSettings, name: str, value: str) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=sc.LINK_STATE_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.oauth_cookie_secure,
        samesite=settings.oauth_cookie_samesite,
        path=_cookie_path(request),
    )


@router.post("/soundcloud/connect", response_model=ConnectResponse)
async def soundcloud_connect(
    request: Request,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
) -> ConnectResponse:
    """Begin the SoundCloud OAuth link; return the URL the client redirects to."""
    settings = _settings(request)
    try:
        link = sc.build_connect_request(current.user_id, settings)
    except sc.SoundCloudError as exc:
        # SoundCloudNotConfiguredError is a subclass, so this covers both.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    _set_link_cookie(response, request, settings, link.nonce_cookie_name, link.state_nonce)
    _set_link_cookie(response, request, settings, link.verifier_cookie_name, link.code_verifier)
    return ConnectResponse(authorization_url=link.url)


@router.post("/soundcloud/callback", response_model=StatusResponse)
async def soundcloud_callback(
    body: CallbackRequest,
    request: Request,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
) -> StatusResponse:
    """Complete the link: validate state, exchange the code, persist the tokens."""
    settings = _settings(request)
    try:
        validated = sc.validate_link_state(body.state, current.user_id, settings, request.cookies)
    except sc.SoundCloudError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid SoundCloud state.") from exc

    # Single-use: clear the per-flow cookies now that they've served their purpose.
    response.delete_cookie(validated.nonce_cookie_name, path=_cookie_path(request))
    response.delete_cookie(validated.verifier_cookie_name, path=_cookie_path(request))

    try:
        tokens = await sc.exchange_code(body.code, validated.code_verifier, settings)
        profile = await sc.get_soundcloud_user(tokens["access_token"])
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="SoundCloud returned no access token."
        ) from exc
    except sc.SoundCloudError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    connection = await _upsert_connection(current.user_id, tokens, profile)
    return StatusResponse(
        connected=True,
        soundcloud_username=connection.soundcloud_username,
        connected_at=connection.created_at,
        token_valid=sc.token_valid(connection.token_expires_at),
    )


async def _upsert_connection(user_id: str, tokens: dict, profile: dict) -> SoundCloudConnection:
    """Create or update the user's single SoundCloud connection (race-safe).

    The unique ``user_id`` index makes a find-then-insert racy: two concurrent
    first-time links both see no row and one insert would 500 on the duplicate
    key. So a fresh insert that loses the race re-resolves and updates instead
    (mirrors ``users.get_or_create_user``).
    """
    oid = PydanticObjectId(user_id)
    existing = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == oid)
    if existing is not None:
        return await _apply_tokens(existing, tokens, profile)

    new_connection = SoundCloudConnection(
        user_id=oid,
        soundcloud_user_id=str(profile.get("id", "")),
        soundcloud_username=profile.get("username") or profile.get("full_name"),
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token", ""),
        token_expires_at=sc.token_expiry(tokens.get("expires_in")),
    )
    try:
        await new_connection.insert()
        return new_connection
    except DuplicateKeyError:
        racer = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == oid)
        if racer is None:
            raise
        return await _apply_tokens(racer, tokens, profile)


async def _apply_tokens(connection: SoundCloudConnection, tokens: dict, profile: dict) -> SoundCloudConnection:
    """Overwrite ``connection`` with the latest tokens/profile and persist it."""
    connection.soundcloud_user_id = str(profile.get("id", ""))
    connection.soundcloud_username = profile.get("username") or profile.get("full_name")
    connection.access_token = tokens["access_token"]
    connection.refresh_token = tokens.get("refresh_token") or connection.refresh_token
    connection.token_expires_at = sc.token_expiry(tokens.get("expires_in"))
    connection.updated_at = utcnow()
    await connection.save()
    return connection


@router.get("/soundcloud/status", response_model=StatusResponse)
async def soundcloud_status(current: CurrentUser = Depends(get_current_user)) -> StatusResponse:
    """Report whether the user has a linked SoundCloud account."""
    connection = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == PydanticObjectId(current.user_id))
    if connection is None:
        return StatusResponse(connected=False)
    return StatusResponse(
        connected=True,
        soundcloud_username=connection.soundcloud_username,
        connected_at=connection.created_at,
        token_valid=sc.token_valid(connection.token_expires_at),
    )


@router.post("/soundcloud/upload", response_model=UploadResponse)
async def soundcloud_upload(
    body: UploadRequest,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
) -> UploadResponse:
    """Upload an owned clip to the user's linked SoundCloud account."""
    clip = await clip_service.get_owned_clip(body.clip_id, current.user_id)

    # Validate the SoundCloud link first so the common "not connected" / revoked
    # case fast-fails before paying for a (potentially large) storage download.
    try:
        connection = await sc.get_valid_connection(current.user_id, _settings(request))
    except sc.SoundCloudNotConnectedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except sc.SoundCloudAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except sc.SoundCloudError as exc:
        # Transient refresh failure — the connection is preserved; ask to retry.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    storage = get_storage_backend()
    try:
        audio = await asyncio.to_thread(storage.download, clip.file_path)
    except FileNotFoundError as exc:
        logger.warning("Clip %s audio object %r is missing", clip.id, clip.file_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found.") from exc

    if len(audio) > sc.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Audio exceeds SoundCloud's {sc.MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.",
        )

    metadata = _merge_metadata(clip, body.metadata_overrides)
    artwork = await _resolve_artwork(clip, storage)

    filename = f"{clip.title or clip.id}.{clip.format or 'wav'}"
    try:
        track = await sc.upload_track(connection.access_token, audio, filename, metadata, artwork)
    except sc.SoundCloudError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    track_id = track.get("id")
    if track_id is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="SoundCloud returned no track id.")
    return UploadResponse(track_id=str(track_id), permalink_url=track.get("permalink_url"))


def _merge_metadata(clip: Clip, overrides: MetadataOverrides) -> dict[str, object]:
    """Derive track metadata from the clip, letting overrides take precedence."""
    metadata: dict[str, object] = {
        # SoundCloud requires a title; an untitled clip falls back to its id so the
        # upload never fails upstream for a missing ``track[title]``.
        "title": clip.title or str(clip.id),
        "bpm": clip.bpm,
        "key_signature": clip.key,
        "genre": clip.style_tags[0] if clip.style_tags else None,
    }
    metadata.update({k: v for k, v in overrides.model_dump().items() if v is not None})
    return metadata


async def _resolve_artwork(clip: Clip, storage: StorageBackend) -> bytes | None:
    """Return the clip's own cover art (US-13.1 ``artwork_path``) to upload, or None.

    Only the clip's stored, already-validated artwork is uploaded — there is no
    arbitrary-URL fetch path (that would be an SSRF surface for no real gain). A
    missing stored object is non-fatal: the track uploads without art.
    """
    if not clip.artwork_path:
        return None
    try:
        return await asyncio.to_thread(storage.download, clip.artwork_path)
    except FileNotFoundError:
        logger.warning("Clip %s artwork object %r is missing; uploading without art", clip.id, clip.artwork_path)
        return None


@router.delete("/soundcloud/connect", status_code=status.HTTP_204_NO_CONTENT)
async def soundcloud_disconnect(current: CurrentUser = Depends(get_current_user)) -> Response:
    """Unlink the user's SoundCloud account; idempotent (204 even if not linked)."""
    connection = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == PydanticObjectId(current.user_id))
    if connection is not None:
        await connection.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
