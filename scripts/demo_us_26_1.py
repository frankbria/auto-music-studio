"""US-26.1 demo driver: what each action costs, and what happens when one fails.

Runs the real FastAPI app against the local MongoDB — real auth tokens, real balances,
real ledger rows. The only stand-in is ACE-Step itself (no GPU here), and it is only
used to make a job fail on purpose so the refund can be watched.
"""

import asyncio
import os
import sys

import httpx
from beanie import PydanticObjectId

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from acemusic.api.auth.tokens import create_access_token  # noqa: E402
from acemusic.api.database import close_db, init_db  # noqa: E402
from acemusic.api.main import API_V1_PREFIX, create_app  # noqa: E402
from acemusic.api.models import Clip, CreditTransaction, Job, JobStatus, User  # noqa: E402
from acemusic.api.services import (  # noqa: E402
    credits as credits_service,
    routing,
    users as user_service,
)
from acemusic.api.settings import ApiSettings  # noqa: E402

SETTINGS = ApiSettings(
    mongodb_url="mongodb://127.0.0.1:27017",
    mongodb_db_name="acemusic_demo_us261",
    jwt_secret_key="demo-secret-key-at-least-32-bytes-long-x",
    job_processor_enabled=False,
)


def auth(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=SETTINGS,
    )
    return {"Authorization": f"Bearer {token}"}


async def make_user(label: str, credits: float) -> User:
    # A fresh principal per run, so the demo repeats without deleting anything.
    email = f"{label}-{PydanticObjectId()}@example.com"
    user = await user_service.get_or_create_user(email=email, provider="demo", oauth_id=email, name="Demo")
    user.credits_balance = credits
    await user.save()
    return user


async def make_clip(user: User, fmt: str = "wav") -> Clip:
    workspace_id = PydanticObjectId()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=f"{user.id}/{workspace_id}/clips/source.{fmt}",
        format=fmt,
        duration=30.0,
    )
    await clip.insert()
    return clip


async def balance(user: User) -> float:
    return (await User.get(user.id)).credits_balance


async def ledger(job_id: str) -> list[CreditTransaction]:
    rows = await CreditTransaction.find(CreditTransaction.job_id == job_id).to_list()
    return sorted(rows, key=lambda r: r.created_at)


async def _available(*_args, **_kwargs) -> bool:
    return True


async def main() -> None:
    # There is no ACE-Step on this machine, so routing would 503 the generate call and
    # the row would read "free" for the wrong reason. Credits are what this demo is
    # about, so make the backend reachable and let the pricing speak for itself.
    routing.check_local_availability = _available
    routing.check_remote_availability = _available

    await init_db(SETTINGS)
    app = create_app(SETTINGS)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as client:
        print("\n== AC1: every action's cost, deducted at enqueue ==")
        user = await make_user("costs", 20.0)
        clip = await make_clip(user)

        actions = [
            ("song  (POST /generate)", f"{API_V1_PREFIX}/generate", {"prompt": "a warm ballad"}),
            ("mashup", f"{API_V1_PREFIX}/mashup", None),  # filled in below
            ("stems   [was free]", f"{API_V1_PREFIX}/clips/{clip.id}/stems", None),
            ("midi    [was free]", f"{API_V1_PREFIX}/clips/{clip.id}/midi", None),
            (
                "remaster [was free]",
                f"{API_V1_PREFIX}/clips/{clip.id}/remaster",
                {"target_lufs": -14.0},
            ),
            ("crop    (still free)", f"{API_V1_PREFIX}/clips/{clip.id}/crop", {"start": "0s", "end": "10s"}),
            ("speed   (still free)", f"{API_V1_PREFIX}/clips/{clip.id}/speed", {"multiplier": 1.5}),
        ]

        second = await make_clip(user)
        for label, url, body in actions:
            if label == "mashup":
                body = {"clip_ids": [str(clip.id), str(second.id)]}
            before = await balance(user)
            resp = await client.post(url, json=body, headers=auth(user))
            after = await balance(user)
            charged = before - after
            note = "" if charged else "   (free)"
            print(f"  {label:24} -> {resp.status_code}  charged {charged:>4.1f}{note}")

        print("\n== AC1: the charge is explained in the history ==")
        user2 = await make_user("ledger", 10.0)
        clip2 = await make_clip(user2)
        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip2.id}/stems", headers=auth(user2))
        for row in await ledger(resp.json()["job_id"]):
            print(f"  {row.action_type:12} {row.amount:>6.1f}   balance after {row.balance_after}")
        print("  (a balance that drops with no row to explain it is the complaint this avoids)")

        print("\n== What keeps pricing a previously-free action fair ==")
        user3 = await make_user("fair", 10.0)
        clip3 = await make_clip(user3)
        await client.post(f"{API_V1_PREFIX}/clips/{clip3.id}/midi", headers=auth(user3))
        # Cache it, the way the worker would.
        fresh = await Clip.get(clip3.id)
        fresh.midi_paths = {"melody": "demo/melody.mid"}
        await fresh.save()
        before = await balance(user3)
        again = await client.post(f"{API_V1_PREFIX}/clips/{clip3.id}/midi", headers=auth(user3))
        print(f"  re-requesting cached MIDI -> {again.status_code}, charged {before - await balance(user3):.1f}")

        mp3 = await make_clip(user3, fmt="mp3")
        before = await balance(user3)
        bad = await client.post(f"{API_V1_PREFIX}/clips/{mp3.id}/stems", headers=auth(user3))
        print(f"  stems on a non-wav clip   -> {bad.status_code}, charged {before - await balance(user3):.1f}")

        print("\n== AC3: an empty balance says what to do about it ==")
        broke = await make_user("broke", 0.0)
        clip4 = await make_clip(broke)
        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip4.id}/stems", headers=auth(broke))
        detail = resp.json()["detail"]
        print(f"  -> {resp.status_code}")
        for key in ("error", "required", "balance", "message", "upgrade_url"):
            print(f"     {key:12} {detail[key]}")
        print(f"  jobs queued without payment: {await Job.find(Job.user_id == broke.id).count()}")

        print("\n== AC5: the balance the sidebar reads ==")
        resp = await client.get(f"{API_V1_PREFIX}/credits/balance", headers=auth(user))
        print(f"  GET /credits/balance -> {resp.status_code}  {resp.json()}")

    print("\n== AC4: a failed job gives the credit back ==")
    await demo_refunds()
    await close_db()


async def demo_refunds() -> None:
    from acemusic.api.tasks.processor import JobProcessor
    from acemusic.storage import LocalStorage

    class FailingAce:
        """ACE-Step stand-in that reports a failed task. No GPU here to fail for real."""

        base_url = "http://ace-step.test"

        def submit_task(self, **kwargs) -> str:
            return "task-1"

        def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
            return {"status": "failed", "audio_urls": [], "error": "the model fell over"}

        def download_audio(self, url: str) -> bytes:  # pragma: no cover - never reached
            return b""

    import tempfile

    user = await make_user("refund", 10.0)
    job = Job(
        user_id=user.id,
        workspace_id=PydanticObjectId(),
        job_type="generate",
        input_params={"prompt": "a song that will not render"},
    )
    await job.insert()

    charged = await credits_service.deduct_credits(user.id, 1.0)
    await credits_service.record_transaction(
        user_id=user.id, amount=-1.0, action_type="song", job_id=str(job.id), balance_after=charged
    )
    print(f"  charged 1 credit, balance now {await balance(user)}")

    with tempfile.TemporaryDirectory() as tmp:
        processor = JobProcessor(
            concurrency=1,
            poll_interval=0.05,
            ace_poll_interval=0.01,
            client_factory=FailingAce,
            storage_factory=lambda: LocalStorage(root_dir=tmp),
        )
        await processor._process_job(job)

    refreshed = await Job.get(job.id)
    print(f"  job ran and {refreshed.status.value}: {refreshed.error}")
    print(f"  balance now {await balance(user)}")
    print("  history:")
    for row in await ledger(str(job.id)):
        print(f"    {row.action_type:16} {row.amount:>6.1f}   balance after {row.balance_after}")

    print("\n== AC4: refunded exactly once, even alongside a handler that already refunded ==")
    user2 = await make_user("partial", 10.0)
    job2 = Job(
        user_id=user2.id,
        workspace_id=PydanticObjectId(),
        job_type="full_song",
        input_params={},
        status=JobStatus.FAILED,
    )
    await job2.insert()
    charged = await credits_service.deduct_credits(user2.id, 5.0)
    await credits_service.record_transaction(
        user_id=user2.id, amount=-5.0, action_type="full_song", job_id=str(job2.id), balance_after=charged
    )
    # Exactly what the full-song handler does when sections go unperformed.
    await credits_service.refund_credits(user2.id, 3.0, action_type="full_song_refund", job_id=str(job2.id))
    print(f"  charged 5, handler already returned 3 -> balance {await balance(user2)}")

    await credits_service.refund_failed_job(job2)
    print(f"  after the generic refund            -> balance {await balance(user2)}")
    await credits_service.refund_failed_job(job2)
    await credits_service.refund_failed_job(job2)
    print(f"  after calling it twice more         -> balance {await balance(user2)}")
    print("  (idempotent by construction: its own refund is a ledger row, so there is")
    print("   nothing left owed to pay a second time)")


if __name__ == "__main__":
    asyncio.run(main())
