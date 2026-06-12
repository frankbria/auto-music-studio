"""User profile router (US-8.4), mounted under ``/api/v1/users``.

Endpoints (all require a valid Bearer access token):

* ``GET  /users/me``  → the authenticated user's full profile
* ``PATCH /users/me`` → partial profile update (display_name, handle, bio, style_tags)

Avatar upload (``PUT /users/me/avatar``) is intentionally deferred to US-8.5
(file storage) and is not part of this surface yet.

Request/response schemas live here (same convention as the auth router). The
handle validator is reused from the service layer so the rules have one home.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import CreditTransaction, User
from ..services import credits as credits_service, users as user_service

# Free-text profile fields are stored verbatim and re-served on every
# GET /users/me, so cap them: one PATCH must not be able to bloat the document
# (and thus every later read). Handle has its own format rules (see service).
DISPLAY_NAME_MAX_LENGTH = 100
BIO_MAX_LENGTH = 500
STYLE_TAG_MAX_LENGTH = 30
STYLE_TAGS_MAX_ITEMS = 20

# Router-level dependency gates every route; endpoints additionally take
# ``current`` to read the identity. FastAPI caches the dependency, so
# ``get_current_user`` still runs once per request.
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


class UserProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    display_name: str | None
    handle: str | None
    bio: str | None
    style_tags: list[str]
    avatar_url: str | None
    subscription_tier: str
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def from_user(cls, user: User) -> "UserProfileResponse":
        return cls(
            id=str(user.id),
            email=user.email,
            name=user.name,
            display_name=user.display_name,
            handle=user.handle,
            bio=user.bio,
            style_tags=user.style_tags,
            avatar_url=user.avatar_url,
            subscription_tier=user.subscription_tier,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserProfileUpdate(BaseModel):
    """Partial profile update; unset fields are left unchanged.

    ``extra="forbid"`` rejects unknown keys with 422 rather than silently dropping
    them, so a client typo surfaces instead of appearing to succeed.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH)] | None = None
    handle: str | None = None
    bio: Annotated[str, Field(max_length=BIO_MAX_LENGTH)] | None = None
    style_tags: (
        Annotated[
            list[Annotated[str, Field(max_length=STYLE_TAG_MAX_LENGTH)]],
            Field(max_length=STYLE_TAGS_MAX_ITEMS),
        ]
        | None
    ) = None

    @field_validator("handle")
    @classmethod
    def _check_handle(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            return user_service.validate_handle(value)
        except user_service.HandleValidationError as exc:
            # Surface the precise rule violation as a 422 via Pydantic.
            raise ValueError(str(exc)) from exc

    @field_validator("style_tags")
    @classmethod
    def _clean_style_tags(cls, value: list[str] | None) -> list[str]:
        # The validator only runs when the field is *present*. An explicit null
        # means "clear my tags": coerce to [] (style_tags is a non-nullable list
        # on the model, so storing None would 500 on read-back). An omitted field
        # never reaches here and is left unchanged by exclude_unset.
        if value is None:
            return []
        cleaned = [tag.strip() for tag in value]
        if any(not tag for tag in cleaned):
            raise ValueError("Style tags must not be empty or whitespace-only.")
        return cleaned


class CreditTransactionEntry(BaseModel):
    """One usage-history row (US-9.6)."""

    amount: float
    action_type: str
    job_id: str
    balance_after: float
    created_at: datetime

    @classmethod
    def from_transaction(cls, txn: CreditTransaction) -> "CreditTransactionEntry":
        return cls(
            amount=txn.amount,
            action_type=txn.action_type,
            job_id=txn.job_id,
            balance_after=txn.balance_after,
            created_at=txn.created_at,
        )


class CreditsResponse(BaseModel):
    """Current balance plus recent usage history, newest first (US-9.6)."""

    balance: float
    tier: str
    history: list[CreditTransactionEntry]


def _not_found() -> HTTPException:
    # An authenticated token whose user no longer exists (e.g. deleted account).
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


@router.get("/me", response_model=UserProfileResponse)
async def get_me(current: CurrentUser = Depends(get_current_user)) -> UserProfileResponse:
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise _not_found()
    return UserProfileResponse.from_user(user)


@router.get("/me/credits", response_model=CreditsResponse)
async def get_my_credits(current: CurrentUser = Depends(get_current_user)) -> CreditsResponse:
    """The authenticated user's credit balance and recent usage history.

    Balance and tier come from the user document (not the token claims), so the
    response reflects deductions made since the token was issued.
    """
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise _not_found()
    transactions = await credits_service.get_recent_transactions(user.id)
    return CreditsResponse(
        balance=user.credits_balance,
        tier=user.subscription_tier,
        history=[CreditTransactionEntry.from_transaction(txn) for txn in transactions],
    )


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    body: UserProfileUpdate,
    current: CurrentUser = Depends(get_current_user),
) -> UserProfileResponse:
    """Update the authenticated user's profile and return the new state.

    Invalid handle format → 422 (Pydantic). Duplicate handle → 409 (mapped from
    ``HandleConflictError`` in ``main.py``).
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        user = await user_service.get_user_by_id(current.user_id)
    else:
        user = await user_service.update_user_profile(current.user_id, updates)
    if user is None:
        raise _not_found()
    return UserProfileResponse.from_user(user)
