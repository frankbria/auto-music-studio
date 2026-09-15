"""Demo driver for #422: refunds return credit to the bucket that paid for it.

Run one step per invocation against a local throwaway MongoDB so a Showboat
document can capture each step's output separately. Steps share state through the
demo database.

    uv run python docs/demos/issue-422-refund-buckets.py <step>
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId

from acemusic.api import database
from acemusic.api.models import CreditTransaction, Job, JobStatus, User
from acemusic.api.services import credits as cs, users as us
from acemusic.api.settings import ApiSettings

URL = os.environ.get("ACEMUSIC_TEST_MONGODB_URL", "mongodb://localhost:27018")
DB = "acemusic_demo_422"
EMAIL = "musician@example.com"


async def _init():
    return await database.init_db(ApiSettings(_env_file=None, mongodb_url=URL, mongodb_db_name=DB))


async def _user() -> User:
    return await us.get_or_create_user(email=EMAIL, provider="google", oauth_id="g-demo", name="Demo")


async def _show(label: str) -> None:
    user = await _user()
    print(f"{label:<28} monthly={user.credits_balance:g}  purchased={user.purchased_credits:g}  spendable={cs.spendable(user):g}")


async def _ledger(job_id: str) -> None:
    rows = await CreditTransaction.find(CreditTransaction.job_id == job_id).sort("+created_at").to_list()
    print("ledger rows for this job (amount / purchased_amount):")
    for r in rows:
        print(f"  {r.action_type:<14} amount={r.amount:+g}  purchased_amount={r.purchased_amount:+g}  balance_after={r.balance_after:g}")


async def _job(job_type: str = "song") -> Job:
    job = Job(user_id=(await _user()).id, workspace_id=PydanticObjectId(), job_type=job_type, input_params={"prompt": "demo"})
    await job.insert()
    return job


async def _set(monthly: float, purchased: float) -> None:
    user = await _user()
    user.credits_balance, user.purchased_credits = monthly, purchased
    await user.save()


async def _fail(job: Job) -> None:
    job.status = JobStatus.FAILED
    await job.save()


async def _last_job() -> Job:
    return await Job.find(Job.user_id == (await _user()).id).sort("-created_at").first_or_none()


async def step(name: str) -> None:
    client = await _init()
    try:
        if name == "reset":
            await client.drop_database(DB)
            user = await _user()
            user.subscription_tier = "free"
            user.credits_balance = 50.0  # free tier: 50 a month
            await user.save()
            await cs.grant_purchased_credits(user.id, 100.0)  # bought the 100-pack
            await _show("start")

        elif name == "charge-120":
            user = await _user()
            job = await cs.charge_and_create(user_id=user.id, cost=120.0, action_type="song", create=_job)
            await _show("after 120-credit charge")
            await _ledger(str(job.id))

        elif name == "fail-and-refund":
            job = await _last_job()
            await _fail(job)
            await cs.refund_failed_job(job)
            await _show("after refund")
            await _ledger(str(job.id))

        elif name == "anniversary":
            user = await _user()
            await cs.deduct_credits(user.id, 10.0)  # a normal month's use, from the monthly bucket
            await _show("spent 10 this month")
            user = await _user()
            user.created_at = datetime.now(timezone.utc) - timedelta(days=400)
            user.credits_reset_at = datetime.now(timezone.utc) - timedelta(days=40)
            await user.save()
            user = await cs.apply_monthly_reset(await _user())
            await _show("after monthly reset")
            row = await CreditTransaction.find(CreditTransaction.action_type == "monthly_reset").first_or_none()
            print(f"monthly_reset granted: {row.amount:g}" if row else "monthly_reset granted: 0 (no row written)")

        elif name == "monthly-only":
            await _set(50.0, 100.0)
            user = await _user()
            job = await cs.charge_and_create(user_id=user.id, cost=20.0, action_type="song", create=_job)
            await _show("after 20-credit charge")
            await _fail(job)
            await cs.refund_failed_job(job)
            await _show("after refund")
            await _ledger(str(job.id))

        elif name == "partial":
            await _set(1.0, 10.0)
            user = await _user()
            job = await cs.charge_and_create(user_id=user.id, cost=3.0, action_type="full_song", create=lambda: _job("full_song"))
            await _show("after 3-credit charge")
            await cs.refund_credits(user.id, 1.5, action_type="full_song_refund", job_id=str(job.id))
            await _show("after refunding half")
            await _ledger(str(job.id))

        elif name == "no-double-refund":
            await _set(1.0, 10.0)
            user = await _user()
            job = await cs.charge_and_create(user_id=user.id, cost=4.0, action_type="full_song", create=lambda: _job("full_song"))
            await _show("after 4-credit charge")
            await cs.refund_credits(user.id, 2.0, action_type="full_song_refund", job_id=str(job.id))
            await _show("handler refunded 2")
            await _fail(job)
            await cs.refund_failed_job(job)
            await _show("processor refund #1")
            await cs.refund_failed_job(job)
            await _show("processor refund #2")
            await _ledger(str(job.id))
        else:
            raise SystemExit(f"unknown step {name}")
    finally:
        await database.close_db(client)


asyncio.run(step(sys.argv[1]))
