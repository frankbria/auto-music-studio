"""Subscription billing endpoints (US-26.3), mounted under ``/api/v1/billing``.

``POST /checkout``      — start a Pro subscription, returns a Stripe Checkout URL
``POST /portal``        — Stripe Billing Portal: change card, cancel, read invoices
``GET  /subscription``  — what this musician's subscription currently is
``GET  /history``       — past charges (AC4)
``POST /webhook``       — Stripe's event feed (AC5)

Auth is per-endpoint rather than router-wide, because ``/webhook`` must be reachable
*without* a bearer token — Stripe has no session. It is not unprotected: every delivery
is authenticated by signature instead (see :func:`services.billing.verify_webhook`),
which is the stronger check here since it also proves the body was not altered.
"""

import logging

from beanie.operators import Eq
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from pymongo import DESCENDING

from ..auth.dependencies import CurrentUser, get_current_user, get_settings
from ..models import BillingEvent
from ..services import billing as billing_service, users as user_service
from ..settings import ApiSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

#: How many charges the history endpoint returns. The billing page shows a list, not an
#: archive; anyone needing more has the Stripe portal, which owns the full record.
HISTORY_LIMIT = 50


class CheckoutResponse(BaseModel):
    """Where to send the musician to pay."""

    url: str


class CreditPack(BaseModel):
    """One purchasable top-up pack."""

    id: str
    credits: float
    #: Major units, divided once here at the edge like every other amount.
    price: float
    currency: str = "usd"


class CreditPacksResponse(BaseModel):
    packs: list[CreditPack]
    billing_enabled: bool


class TopUpRequest(BaseModel):
    pack_id: str


class SubscriptionResponse(BaseModel):
    """The subscription as this platform currently understands it."""

    tier: str
    status: str | None
    #: ISO-8601. While a cancellation is pending, the date Pro access actually stops.
    current_period_end: str | None
    cancel_at_period_end: bool
    #: Whether billing is configured at all — lets the UI hide the upgrade button on a
    #: deployment with no Stripe rather than offering a link that 503s.
    billing_enabled: bool


class BillingHistoryEntry(BaseModel):
    """One charge, as shown in account settings."""

    id: str
    event_type: str
    #: Major units (e.g. dollars). Stored as integer cents; divided once, here at the
    #: edge, so no arithmetic downstream ever runs on a float.
    amount: float | None
    currency: str | None
    status: str | None
    description: str | None
    invoice_url: str | None
    created_at: str


class BillingHistoryResponse(BaseModel):
    entries: list[BillingHistoryEntry]


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


async def _current_user_doc(current: CurrentUser):
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


@router.post("/checkout", response_model=CheckoutResponse)
async def start_checkout(
    current: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> CheckoutResponse:
    """Begin a Pro subscription.

    Returns a URL rather than redirecting: the caller is a fetch from the SPA, and a
    302 to a third-party host from an XHR is awkward for the client and invisible to
    the user. The frontend does the navigation.
    """
    user = await _current_user_doc(current)
    try:
        url = await billing_service.create_checkout_session(user, settings)
    except billing_service.BillingNotConfigured as exc:
        raise _unavailable(exc) from exc
    except billing_service.AlreadySubscribed as exc:
        # 409, not 400: the request is well-formed, it conflicts with state the caller
        # may not have known about (a stale tab, a second window). The only endpoint in
        # the platform where getting this wrong charges someone twice.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return CheckoutResponse(url=url)


@router.post("/portal", response_model=CheckoutResponse)
async def open_portal(
    current: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> CheckoutResponse:
    """Stripe's own billing portal — payment method, cancellation, invoices."""
    user = await _current_user_doc(current)
    try:
        url = await billing_service.create_portal_session(user, settings)
    except billing_service.BillingNotConfigured as exc:
        raise _unavailable(exc) from exc
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CheckoutResponse(url=url)


@router.get("/packs", response_model=CreditPacksResponse)
async def get_packs(
    _: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> CreditPacksResponse:
    """The credit packs on offer.

    Served rather than hardcoded in the client so pricing moves without a frontend
    release, and so the amount shown is the amount charged — both come from one table.
    """
    return CreditPacksResponse(
        packs=[
            CreditPack(id=pack_id, credits=pack["credits"], price=pack["amount_cents"] / 100)
            for pack_id, pack in billing_service.CREDIT_PACKS.items()
        ],
        billing_enabled=settings.stripe_enabled,
    )


@router.post("/topup", response_model=CheckoutResponse)
async def start_topup(
    body: TopUpRequest,
    current: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> CheckoutResponse:
    """Buy a credit pack — a one-off charge, available on every tier."""
    user = await _current_user_doc(current)
    try:
        url = await billing_service.create_topup_session(user, body.pack_id, settings)
    except billing_service.BillingNotConfigured as exc:
        raise _unavailable(exc) from exc
    except billing_service.BillingError as exc:
        # An unknown pack id is the caller's mistake, not Stripe's.
        code = status.HTTP_400_BAD_REQUEST if "Unknown credit pack" in str(exc) else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return CheckoutResponse(url=url)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> SubscriptionResponse:
    """Read the local mirror, not Stripe.

    This is on the settings page and potentially polled after a checkout redirect;
    round-tripping to Stripe would make it slow and would fail the page whenever Stripe
    is having a bad day, for information already known.
    """
    user = await _current_user_doc(current)
    end = user.subscription_current_period_end
    return SubscriptionResponse(
        tier=user.subscription_tier,
        status=user.subscription_status,
        current_period_end=end.isoformat() if end else None,
        cancel_at_period_end=user.subscription_cancel_at_period_end,
        billing_enabled=settings.stripe_enabled,
    )


@router.get("/history", response_model=BillingHistoryResponse)
async def get_history(
    current: CurrentUser = Depends(get_current_user),
) -> BillingHistoryResponse:
    """Past **charges**, newest first (AC4).

    Filtered to rows that carry an amount. ``billing_events`` also stores subscription
    lifecycle events, because that collection doubles as the webhook idempotency guard
    and every handled event has to be written there — but a musician's billing history
    is a list of times they were charged, not an audit log of Stripe callbacks. Without
    this filter the table fills with ``customer.subscription.updated`` rows showing a
    dash for the amount, which is noise wearing the costume of a receipt.

    Failed attempts *are* included: they carry ``amount_due`` and a non-paid status, and
    "we tried to charge you and it did not work" is exactly what someone opens this page
    to find out.
    """
    user = await _current_user_doc(current)
    events = (
        await BillingEvent.find(
            Eq(BillingEvent.user_id, user.id),
            {"amount_cents": {"$ne": None}},
        )
        .sort([("created_at", DESCENDING)])
        .limit(HISTORY_LIMIT)
        .to_list()
    )
    return BillingHistoryResponse(
        entries=[
            BillingHistoryEntry(
                id=str(event.id),
                event_type=event.event_type,
                amount=None if event.amount_cents is None else event.amount_cents / 100,
                currency=event.currency,
                status=event.status,
                description=event.description,
                invoice_url=event.invoice_url,
                created_at=event.created_at.isoformat(),
            )
            for event in events
        ]
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    settings: ApiSettings = Depends(get_settings),
) -> dict[str, str]:
    """Stripe's event feed (AC5).

    Reads the *raw* body — the signature covers the exact bytes Stripe sent, so parsing
    to JSON and re-serialising would break verification.

    Returns 2xx for anything successfully processed **or deliberately ignored**. A
    non-2xx tells Stripe to redeliver, and redelivering an event we will never care
    about just fills the queue; a genuine failure is what the 4xx/5xx paths are for.
    """
    payload = await request.body()
    try:
        event = billing_service.verify_webhook(payload, stripe_signature, settings)
    except billing_service.BillingNotConfigured as exc:
        raise _unavailable(exc) from exc
    except billing_service.BillingError as exc:
        # 400, not 403: an unverifiable delivery is a bad request, and Stripe does not
        # retry 4xx — which is right, because retrying will not make the signature valid.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    outcome = await billing_service.handle_event(event)
    logger.info("billing: handled %s -> %s", event.get("type"), outcome)
    return {"status": outcome}
