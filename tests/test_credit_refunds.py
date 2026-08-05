"""US-26.1: refunds are ledgered, and a failed job is refunded exactly once.

Two properties are load-bearing here, and both are about money:

* **A refund must be visible.** Before this story ``refund_credits`` only moved the
  balance, so a user's history showed the charge and never the compensating credit.
* **A failed job must be refunded once.** Several handlers already refund their own
  partial work (full-song sections, mastering pre-flight, voice training), so a blanket
  "refund on failure" that ignored them would pay twice.
"""

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import CreditTransaction, Job, JobStatus, User
from acemusic.api.services import credits as credits_service, users as user_service

pytestmark = pytest.mark.integration


async def _user(email: str, credits: float = 100.0) -> User:
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    user.credits_balance = credits
    await user.save()
    return user


async def _job(user: User, job_type: str = "generate", status: JobStatus = JobStatus.QUEUED) -> Job:
    job = Job(
        user_id=user.id,
        workspace_id=PydanticObjectId(),
        job_type=job_type,
        input_params={"prompt": "x"},
        status=status,
    )
    await job.insert()
    return job


async def _balance(user: User) -> float:
    fresh = await User.get(user.id)
    return fresh.credits_balance


async def _rows(job: Job) -> list[CreditTransaction]:
    return await CreditTransaction.find(CreditTransaction.job_id == str(job.id)).to_list()


async def _charge(user: User, job: Job, amount: float, action_type: str = "song") -> None:
    """Charge exactly the way a router does, so these tests exercise the real shape."""
    balance_after = await credits_service.deduct_credits(user.id, amount)
    assert balance_after is not None
    await credits_service.record_transaction(
        user_id=user.id,
        amount=-amount,
        action_type=action_type,
        job_id=str(job.id),
        balance_after=balance_after,
    )


class TestRefundsAreLedgered:
    async def test_a_refund_appears_in_the_history(self, mongo_db) -> None:
        # The whole point: a user who was charged and then refunded can see both.
        user = await _user("ledger@example.com", credits=10.0)
        job = await _job(user)
        await _charge(user, job, 1.0)

        await credits_service.refund_credits(user.id, 1.0, action_type="song_refund", job_id=str(job.id))

        rows = sorted(await _rows(job), key=lambda r: r.created_at)
        assert [r.amount for r in rows] == [-1.0, 1.0]
        assert rows[1].action_type == "song_refund"

    async def test_the_refund_row_records_the_balance_after_it(self, mongo_db) -> None:
        # Denormalised so history rows are self-describing; a stale read here would
        # show the user a balance they never had.
        user = await _user("ledger-balance@example.com", credits=10.0)
        job = await _job(user)
        await _charge(user, job, 1.0)

        await credits_service.refund_credits(user.id, 1.0, action_type="song_refund", job_id=str(job.id))

        rows = sorted(await _rows(job), key=lambda r: r.created_at)
        assert rows[1].balance_after == 10.0
        assert await _balance(user) == 10.0

    async def test_a_refund_with_no_job_is_still_ledgered(self, mongo_db) -> None:
        # The request paths refund when job creation itself failed, so there is no id.
        user = await _user("ledger-nojob@example.com", credits=10.0)

        await credits_service.refund_credits(user.id, 1.0, action_type="song_refund", job_id="")

        rows = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert [r.amount for r in rows] == [1.0]

    async def test_a_non_positive_refund_is_refused(self, mongo_db) -> None:
        # Symmetric with deduct_credits: a negative "refund" would silently charge.
        user = await _user("ledger-negative@example.com")
        with pytest.raises(ValueError):
            await credits_service.refund_credits(user.id, 0.0, action_type="x", job_id="")
        with pytest.raises(ValueError):
            await credits_service.refund_credits(user.id, -5.0, action_type="x", job_id="")


class TestUnrecordedChargeReversal:
    """The request paths ledger the charge *last*, so their compensating reversal
    must leave no trace — otherwise the history shows a credit from nowhere."""

    async def test_reversing_an_unrecorded_charge_writes_no_row(self, mongo_db) -> None:
        user = await _user("reverse@example.com", credits=10.0)
        await credits_service.deduct_credits(user.id, 1.0)

        await credits_service.reverse_unrecorded_charge(user.id, 1.0)

        assert await _balance(user) == 10.0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0

    async def test_a_non_positive_reversal_is_refused(self, mongo_db) -> None:
        # Same guard as the others: a negative "reversal" would charge the user.
        user = await _user("reverse-negative@example.com")
        with pytest.raises(ValueError):
            await credits_service.reverse_unrecorded_charge(user.id, -1.0)


class TestAmountOwed:
    async def test_a_charged_job_owes_what_it_was_charged(self, mongo_db) -> None:
        user = await _user("owed-charged@example.com")
        job = await _job(user)
        await _charge(user, job, 2.0)

        assert await credits_service.amount_owed_for_job(str(job.id)) == 2.0

    async def test_a_fully_refunded_job_owes_nothing(self, mongo_db) -> None:
        user = await _user("owed-refunded@example.com")
        job = await _job(user)
        await _charge(user, job, 2.0)
        await credits_service.refund_credits(user.id, 2.0, action_type="r", job_id=str(job.id))

        assert await credits_service.amount_owed_for_job(str(job.id)) == 0.0

    async def test_a_partly_refunded_job_owes_the_remainder(self, mongo_db) -> None:
        # The full-song case: some sections ran, the rest were refunded mid-flight.
        user = await _user("owed-partial@example.com")
        job = await _job(user, job_type="full_song")
        await _charge(user, job, 5.0)
        await credits_service.refund_credits(user.id, 3.0, action_type="r", job_id=str(job.id))

        assert await credits_service.amount_owed_for_job(str(job.id)) == 2.0

    async def test_an_over_refunded_job_owes_nothing_rather_than_a_negative(self, mongo_db) -> None:
        # Clamped: a negative "owed" fed back into refund_credits would charge the user.
        user = await _user("owed-over@example.com")
        job = await _job(user)
        await _charge(user, job, 1.0)
        await credits_service.refund_credits(user.id, 3.0, action_type="r", job_id=str(job.id))

        assert await credits_service.amount_owed_for_job(str(job.id)) == 0.0

    async def test_an_uncharged_job_owes_nothing(self, mongo_db) -> None:
        # Edits/exports are free; a failure there must not mint credits.
        user = await _user("owed-free@example.com")
        job = await _job(user, job_type="crop")

        assert await credits_service.amount_owed_for_job(str(job.id)) == 0.0


class TestRefundFailedJob:
    async def test_a_failed_job_gets_its_credit_back(self, mongo_db) -> None:
        user = await _user("failed@example.com", credits=10.0)
        job = await _job(user, status=JobStatus.FAILED)
        await _charge(user, job, 1.0)
        assert await _balance(user) == 9.0

        await credits_service.refund_failed_job(job)

        assert await _balance(user) == 10.0

    async def test_refunding_twice_pays_once(self, mongo_db) -> None:
        # A handler that already refunded, followed by the processor's generic path.
        user = await _user("failed-twice@example.com", credits=10.0)
        job = await _job(user, status=JobStatus.FAILED)
        await _charge(user, job, 1.0)

        await credits_service.refund_failed_job(job)
        await credits_service.refund_failed_job(job)

        assert await _balance(user) == 10.0

    async def test_a_handler_partial_refund_is_not_paid_again(self, mongo_db) -> None:
        # Exactly the full-song shape: the handler refunds unperformed sections, then
        # the job fails and the generic path runs.
        user = await _user("failed-partial@example.com", credits=10.0)
        job = await _job(user, job_type="full_song", status=JobStatus.FAILED)
        await _charge(user, job, 5.0)
        await credits_service.refund_credits(user.id, 3.0, action_type="full_song_refund", job_id=str(job.id))
        assert await _balance(user) == 8.0

        await credits_service.refund_failed_job(job)

        # 5 charged, 3 already returned, 2 owed -> back to the starting balance, once.
        assert await _balance(user) == 10.0

    async def test_a_free_job_failing_does_not_mint_credits(self, mongo_db) -> None:
        user = await _user("failed-free@example.com", credits=10.0)
        job = await _job(user, job_type="crop", status=JobStatus.FAILED)

        await credits_service.refund_failed_job(job)

        assert await _balance(user) == 10.0
        assert await _rows(job) == []

    async def test_the_refund_is_attributed_to_the_job_type(self, mongo_db) -> None:
        user = await _user("failed-attr@example.com", credits=10.0)
        job = await _job(user, job_type="mashup", status=JobStatus.FAILED)
        await _charge(user, job, 2.0, action_type="mashup")

        await credits_service.refund_failed_job(job)

        rows = sorted(await _rows(job), key=lambda r: r.created_at)
        assert rows[-1].action_type == "mashup_refund"

    async def test_a_completed_job_is_never_refunded(self, mongo_db) -> None:
        # Guards against a caller wiring this to the wrong lifecycle transition.
        user = await _user("completed@example.com", credits=10.0)
        job = await _job(user)
        await _charge(user, job, 1.0)
        job.status = JobStatus.COMPLETED
        await job.save()

        with pytest.raises(ValueError):
            await credits_service.refund_failed_job(job)

        assert await _balance(user) == 9.0


class TestProcessorRefundsOnFailure:
    """The wiring, not just the service: a job that fails in the worker is refunded."""

    async def test_a_failed_generation_is_refunded_end_to_end(self, mongo_db, tmp_path) -> None:
        from acemusic.api.tasks.processor import JobProcessor
        from acemusic.storage import LocalStorage

        user = await _user("proc-failed@example.com", credits=10.0)
        job = await _job(user)
        await _charge(user, job, 1.0)
        assert await _balance(user) == 9.0

        class _FailingAce:
            base_url = "http://ace-step.test"

            def submit_task(self, **kwargs) -> str:
                return "task-1"

            def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
                return {"status": "failed", "audio_urls": [], "error": "boom"}

            def download_audio(self, url: str) -> bytes:  # pragma: no cover - never reached
                return b""

        processor = JobProcessor(
            concurrency=1,
            poll_interval=0.05,
            ace_poll_interval=0.01,
            client_factory=_FailingAce,
            storage_factory=lambda: LocalStorage(root_dir=tmp_path),
        )
        await processor._process_job(job)

        refreshed = await Job.get(job.id)
        assert refreshed.status is JobStatus.FAILED
        assert await _balance(user) == 10.0, "a failed generation kept the credit"

    async def test_a_successful_generation_keeps_the_charge(self, mongo_db, tmp_path) -> None:
        # The other half of the guarantee: success must not refund.
        from acemusic.api.tasks.processor import JobProcessor
        from acemusic.storage import LocalStorage

        user = await _user("proc-ok@example.com", credits=10.0)
        job = await _job(user)
        await _charge(user, job, 1.0)

        class _WorkingAce:
            base_url = "http://ace-step.test"

            def submit_task(self, **kwargs) -> str:
                return "task-1"

            def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
                return {"status": "completed", "audio_urls": ["u0"], "error": None}

            def download_audio(self, url: str) -> bytes:
                return b"RIFF....WAVEfake"

        processor = JobProcessor(
            concurrency=1,
            poll_interval=0.05,
            ace_poll_interval=0.01,
            client_factory=_WorkingAce,
            storage_factory=lambda: LocalStorage(root_dir=tmp_path),
        )
        await processor._process_job(job)

        refreshed = await Job.get(job.id)
        assert refreshed.status is JobStatus.COMPLETED
        assert await _balance(user) == 9.0, "a successful generation was refunded"


class TestChargeAndCreate:
    """The invariant the helper exists for: charged => a job exists, or the credit is back.

    Added after a mutation check — deleting the compensating reversal killed no test,
    because the pre-existing coverage exercised the hand-rolled copies in the routers
    rather than this helper.
    """

    async def test_a_successful_charge_deducts_and_ledgers_once(self, mongo_db) -> None:
        user = await _user("cac-ok@example.com", credits=10.0)

        async def _create() -> Job:
            return await _job(user)

        job = await credits_service.charge_and_create(user_id=user.id, cost=1.0, action_type="song", create=_create)

        assert await _balance(user) == 9.0
        rows = await _rows(job)
        assert [(r.action_type, r.amount) for r in rows] == [("song", -1.0)]

    async def test_a_failure_to_create_gives_the_credit_back(self, mongo_db) -> None:
        user = await _user("cac-fail@example.com", credits=10.0)

        async def _boom() -> Job:
            raise RuntimeError("could not queue")

        with pytest.raises(RuntimeError):
            await credits_service.charge_and_create(user_id=user.id, cost=1.0, action_type="song", create=_boom)

        assert await _balance(user) == 10.0, "the charge was kept for a job that never existed"

    async def test_a_failure_to_create_leaves_no_ledger_trace(self, mongo_db) -> None:
        # Neither the charge nor its reversal was recorded, so the history must be
        # empty rather than showing a credit from nowhere.
        user = await _user("cac-fail-ledger@example.com", credits=10.0)

        async def _boom() -> Job:
            raise RuntimeError("could not queue")

        with pytest.raises(RuntimeError):
            await credits_service.charge_and_create(user_id=user.id, cost=1.0, action_type="song", create=_boom)

        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0

    async def test_a_cancelled_request_also_gives_the_credit_back(self, mongo_db) -> None:
        # BaseException, not Exception: a shutdown mid-request must not leave someone
        # charged for work that will never run.
        import asyncio

        user = await _user("cac-cancel@example.com", credits=10.0)

        async def _cancelled() -> Job:
            raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await credits_service.charge_and_create(user_id=user.id, cost=1.0, action_type="song", create=_cancelled)

        assert await _balance(user) == 10.0

    async def test_an_unaffordable_action_is_refused_before_the_job_exists(self, mongo_db) -> None:
        user = await _user("cac-broke@example.com", credits=0.0)
        created = False

        async def _create() -> Job:
            nonlocal created
            created = True
            return await _job(user)

        with pytest.raises(credits_service.InsufficientCreditsError) as exc:
            await credits_service.charge_and_create(user_id=user.id, cost=1.0, action_type="song", create=_create)

        assert not created, "the job was created despite an insufficient balance"
        assert exc.value.required == 1.0
        assert exc.value.balance == 0.0

    async def test_a_free_action_creates_without_touching_the_balance(self, mongo_db) -> None:
        user = await _user("cac-free@example.com", credits=10.0)

        job = await credits_service.charge_and_create(
            user_id=user.id, cost=0.0, action_type="crop", create=lambda: _job(user, job_type="crop")
        )

        assert await _balance(user) == 10.0
        assert await _rows(job) == []
