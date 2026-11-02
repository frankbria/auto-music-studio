"""Every error answers ``{"detail", "code"}``, and nothing internal reaches the caller (#339)."""

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from acemusic.api.main import create_app
from acemusic.api.services.credits import InsufficientCreditsError
from acemusic.api.services.routing import ComputePreference, ComputeTarget, ComputeUnavailableError
from acemusic.api.services.screening import ContentBlockedError
from acemusic.api.tasks.common import JobProcessingError, UserFacingJobError, failure_message


class _Body(BaseModel):
    count: int


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    async def crash() -> None:
        raise RuntimeError("mongodb://admin:hunter2@db.internal:27017 refused the connection")

    async def limited() -> None:
        raise HTTPException(status_code=429, detail="Slow down.", headers={"Retry-After": "7"})

    async def needs_body(body: _Body) -> dict:
        return {"count": body.count}

    async def broke() -> None:
        raise InsufficientCreditsError(balance=1, required=3)

    async def blocked() -> None:
        raise ContentBlockedError("That lyric can't be used.")

    app.add_api_route("/test/crash", crash)
    app.add_api_route("/test/limited", limited)
    app.add_api_route("/test/body", needs_body, methods=["POST"])
    app.add_api_route("/test/broke", broke)
    app.add_api_route("/test/blocked", blocked)
    return TestClient(app, raise_server_exceptions=False)


def test_an_unhandled_error_is_a_generic_500_with_a_reference(client: TestClient) -> None:
    resp = client.get("/test/crash")

    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "internal_error"
    assert "contact support and quote reference" in body["detail"]
    assert "hunter2" not in resp.text and "Traceback" not in resp.text and "RuntimeError" not in resp.text


def test_an_http_error_keeps_its_detail_and_headers_and_gains_a_code(client: TestClient) -> None:
    resp = client.get("/test/limited")

    assert resp.status_code == 429
    assert resp.json() == {"detail": "Slow down.", "code": "rate_limited"}
    assert resp.headers["retry-after"] == "7"


def test_an_unknown_route_is_a_coded_404(client: TestClient) -> None:
    resp = client.get("/no/such/route")

    assert resp.json() == {"detail": "Not Found", "code": "not_found"}


def test_a_validation_error_keeps_its_field_list_and_gains_a_code(client: TestClient) -> None:
    resp = client.post("/test/body", json={"count": "many"})

    body = resp.json()
    assert resp.status_code == 422
    assert body["code"] == "invalid_request"
    assert body["detail"][0]["loc"] == ["body", "count"]


def test_domain_errors_name_their_own_codes(client: TestClient) -> None:
    broke = client.get("/test/broke")
    blocked = client.get("/test/blocked")

    assert (broke.status_code, broke.json()["code"]) == (402, "insufficient_credits")
    assert broke.json()["detail"]["upgrade_url"]
    assert (blocked.status_code, blocked.json()["code"]) == (422, "content_blocked")


class TestFailureMessage:
    def test_a_message_written_for_the_musician_is_shown_as_it_is(self) -> None:
        assert failure_message("generation", UserFacingJobError("Voice model 'Ana' is not ready to use yet.")) == (
            "Voice model 'Ana' is not ready to use yet."
        )

    def test_an_internal_message_is_replaced_by_what_was_being_made(self) -> None:
        message = failure_message("video", JobProcessingError("Source clip 6ae8 audio object 'u/w/c.wav' is missing"))

        assert message.startswith("The video didn't finish. Any credits it used were refunded.")
        assert "6ae8" not in message and ".wav" not in message
        assert message.endswith("If it keeps happening, contact support.")

    @pytest.mark.parametrize(
        "cause",
        [
            ComputeUnavailableError(ComputeTarget.LOCAL, ComputePreference.LOCAL_FIRST),
            httpx.ConnectError("connection refused"),
            httpx.ReadTimeout("read timed out"),
            TimeoutError(),
        ],
    )
    def test_a_busy_or_unreachable_server_says_when_to_try_again(self, cause: Exception) -> None:
        try:
            raise JobProcessingError("Submit failed") from cause
        except JobProcessingError as exc:
            message = failure_message("generation", exc)

        assert message.startswith("The music server is busy right now. Try again in 30 seconds.")

    def test_an_unknown_family_still_gets_guidance(self) -> None:
        assert failure_message("", ValueError("boom")).startswith("This didn't finish.")
