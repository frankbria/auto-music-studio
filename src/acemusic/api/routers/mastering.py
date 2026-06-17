"""Mastering job submission endpoint (US-12.1).

``POST /api/v1/mastering/jobs`` accepts a source clip, a mastering profile, and
an optional service/format, then enqueues a credit-bearing mastering job and
returns 202 with a trackable job id.

The credit-gate flow mirrors the generation/iterative endpoints (these are paid
operations): the source clip is validated for ownership first (404 before any
charge), the per-service cost is deducted atomically (the concurrency guard), a
job-creation failure refunds, and the ledger write is best-effort. The actual
mastering work is a future ticket — the processor only claims registered
``job_type``s, so submitted jobs queue safely until then.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator

from ..auth.dependencies import CurrentUser, get_current_user
from ..services import (
    clips as clip_service,
    credits as credits_service,
    mastering as mastering_service,
    users as user_service,
)

logger = logging.getLogger(__name__)

# Custom LUFS targets share the remaster bounds: anything above -5 or below -70
# is a client error, not a master (see editing.RemasterRequest).
_CUSTOM_LUFS_MIN = -70.0
_CUSTOM_LUFS_MAX = -5.0

router = APIRouter(prefix="/mastering", tags=["mastering"], dependencies=[Depends(get_current_user)])


class MasteringRequest(BaseModel):
    """A mastering submission: a source clip plus a target profile.

    ``extra="forbid"`` rejects unknown keys with 422 (a client typo surfaces
    instead of being silently dropped). ``target_lufs`` is required for the
    ``custom`` profile and forbidden for the standard profiles, which own their
    own loudness target.
    """

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    profile: Literal["streaming", "soundcloud", "club", "vinyl", "custom"]
    service: Literal["dolby", "landr", "bakuage"] = "dolby"
    format: Literal["wav", "mp3", "flac"] = "wav"
    target_lufs: float | None = None

    @model_validator(mode="after")
    def _check_target_lufs(self) -> "MasteringRequest":
        if self.profile == "custom":
            if self.target_lufs is None:
                raise ValueError("target_lufs is required when profile is 'custom'")
            if not (_CUSTOM_LUFS_MIN <= self.target_lufs <= _CUSTOM_LUFS_MAX):
                raise ValueError(f"target_lufs must be between {_CUSTOM_LUFS_MIN} and {_CUSTOM_LUFS_MAX} dB")
        elif self.target_lufs is not None:
            raise ValueError("target_lufs is only allowed when profile is 'custom'")
        return self


class MasteringJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


@router.post("/jobs", response_model=MasteringJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_mastering_job(
    request: MasteringRequest,
    # The router-level dependency already gates auth; declaring it here too gives
    # the handler the resolved CurrentUser. FastAPI dedupes by callable per
    # request, so get_current_user runs once (mirrors the iterative router).
    current: CurrentUser = Depends(get_current_user),
) -> MasteringJobResponse:
    """Validate the clip, charge credits, and enqueue a queued mastering job.

    Pydantic returns 422 for invalid bodies and the router dependency returns 401
    for missing/invalid tokens — both before this runs. Raises 404 (stale token
    or unknown/unowned clip) and 402 (insufficient credits).
    """
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Validate ownership before charging: an unknown/unowned clip yields a clean
    # 404 with no credit movement. The clip's workspace is where the master lands.
    clip = await clip_service.get_owned_clip(request.clip_id, current.user_id)

    cost = credits_service.get_mastering_cost(request.service)
    balance_after = await credits_service.deduct_credits(user.id, cost)
    if balance_after is None:
        # Re-read the balance for the error payload: the copy on ``user`` was
        # loaded before the deduction attempt and may be stale under concurrency.
        fresh = await user_service.get_user_by_id(user.id)
        balance = fresh.credits_balance if fresh is not None else 0.0
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "insufficient_credits", "balance": balance, "required": cost},
        )

    try:
        # Everything after the deduction lives inside the refund guard so the
        # "charged ⇒ either a job exists or the credit is returned" invariant
        # holds structurally, not just because resolve_target_lufs happens to be
        # unreachable today (the Literal profile is Pydantic-validated upstream).
        target_lufs = mastering_service.resolve_target_lufs(request.profile, request.target_lufs)
        params = {
            "clip_id": str(clip.id),
            "profile": request.profile,
            "service": request.service,
            "format": request.format,
            "target_lufs": target_lufs,
        }
        job = await mastering_service.create_mastering_job(
            user_id=user.id,
            workspace_id=clip.workspace_id,
            params=params,
        )
    except BaseException:
        # The deduction already landed but no job exists — give the credit back.
        # BaseException (not Exception): asyncio.CancelledError must also refund.
        await credits_service.refund_credits(user.id, cost)
        raise
    try:
        await credits_service.record_transaction(
            user_id=user.id,
            amount=-cost,
            action_type=mastering_service.MASTERING_JOB_TYPE,
            job_id=str(job.id),
            balance_after=balance_after,
        )
    except Exception:
        # The charge is taken and the job dispatched; failing here would invite a
        # retry that double-charges. The ledger row is best-effort history.
        logger.exception("Credit ledger write failed for job %s (user %s)", job.id, user.id)
    return MasteringJobResponse(job_id=str(job.id))
