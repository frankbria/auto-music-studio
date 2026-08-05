"""Credit balance endpoint (US-26.1), mounted under ``/api/v1/credits``.

``GET /api/v1/credits/balance`` — what the musician has left.

Deliberately separate from ``GET /users/me/credits``, which returns balance, tier
*and* recent history. The UI shows the balance in the sidebar on every page, so it
polls something small; sending the last fifty ledger rows along with it would be
waste on every navigation. Both read the same user document, so they cannot drift.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth.dependencies import CurrentUser, get_current_user
from ..services import credits as credits_service, users as user_service

router = APIRouter(prefix="/credits", tags=["credits"], dependencies=[Depends(get_current_user)])


class BalanceResponse(BaseModel):
    """Just enough for the header/sidebar display."""

    balance: float
    tier: str
    #: Where to send someone who has run out. Served rather than hardcoded in the
    #: client so the destination can move without a frontend release.
    upgrade_url: str


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(current: CurrentUser = Depends(get_current_user)) -> BalanceResponse:
    """The authenticated user's current credit balance.

    Read from the user document rather than the token claims, so it reflects every
    deduction and refund since the token was issued — which is the whole point of a
    balance the UI keeps on screen.
    """
    user = await user_service.get_user_by_id(current.user_id)

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return BalanceResponse(
        balance=user.credits_balance,
        tier=user.subscription_tier,
        upgrade_url=credits_service.UPGRADE_URL,
    )
