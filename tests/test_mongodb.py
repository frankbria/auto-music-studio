"""Integration tests for the MongoDB data layer (US-8.2).

These run against a real local MongoDB (no mocking). They are marked
``integration`` so the default unit run deselects them; CI runs them with a
mongo service container. Each test uses an isolated throwaway database.
"""

import pytest

pytestmark = pytest.mark.integration


class TestConnection:
    async def test_init_db_connects_and_pings(self, mongo_db):
        """init_db returns a live client that responds to ping."""
        client = mongo_db.get_client()
        result = await client.admin.command("ping")
        assert result.get("ok") == 1.0

    async def test_init_db_fails_fast_on_unreachable(self):
        """An unreachable MongoDB raises ConnectionError quickly (no silent hang)."""
        from acemusic.api import database
        from acemusic.api.settings import ApiSettings

        settings = ApiSettings(
            _env_file=None,
            mongodb_url="mongodb://127.0.0.1:1",  # nothing listens here
            mongodb_db_name="acemusic_test_unreachable",
            mongodb_server_selection_timeout_ms=1000,
        )
        with pytest.raises(ConnectionError) as exc:
            await database.init_db(settings)
        assert "mongo" in str(exc.value).lower()


class TestIndexes:
    async def test_required_indexes_created(self, mongo_db):
        """Collections are created with the indexes required by the AC."""
        db = mongo_db.get_database()

        user_idx = await db["users"].index_information()
        # email must be uniquely indexed
        assert any(
            keys[0][0] == "email" and meta.get("unique")
            for meta in [user_idx[name] for name in user_idx]
            for keys in [meta["key"]]
        )

        clip_idx = await db["clips"].index_information()
        indexed_fields = {meta["key"][0][0] for meta in clip_idx.values()}
        assert {"workspace_id", "user_id", "created_at"} <= indexed_fields


class TestUserCrud:
    async def test_create_query_update_delete(self, mongo_db):
        from acemusic.api.models import User

        user = await User(email="a@example.com", name="Ada").insert()
        assert user.id is not None

        found = await User.find_one(User.email == "a@example.com")
        assert found is not None and found.name == "Ada"

        found.name = "Ada L."
        await found.save()
        assert (await User.find_one(User.email == "a@example.com")).name == "Ada L."

        await found.delete()
        assert await User.find_one(User.email == "a@example.com") is None

    async def test_duplicate_email_rejected(self, mongo_db):
        """The unique email index prevents duplicate users."""
        from pymongo.errors import DuplicateKeyError

        from acemusic.api.models import User

        await User(email="dup@example.com", name="One").insert()
        with pytest.raises(DuplicateKeyError):
            await User(email="dup@example.com", name="Two").insert()


class TestWorkspaceCrud:
    async def test_create_and_query_by_user(self, mongo_db):
        from beanie import PydanticObjectId

        from acemusic.api.models import Workspace

        user_id = PydanticObjectId()
        ws = await Workspace(name="My Album", user_id=user_id, is_default=True).insert()
        assert ws.id is not None

        results = await Workspace.find(Workspace.user_id == user_id).to_list()
        assert len(results) == 1 and results[0].is_default is True


class TestClipCrud:
    async def test_create_and_created_at_ordering(self, mongo_db):
        from datetime import datetime, timezone

        from beanie import PydanticObjectId

        from acemusic.api.models import Clip

        ws = PydanticObjectId()
        older = await Clip(
            title="older",
            workspace_id=ws,
            user_id=PydanticObjectId(),
            file_path="/x/older.wav",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ).insert()
        newer = await Clip(
            title="newer",
            workspace_id=ws,
            user_id=PydanticObjectId(),
            file_path="/x/newer.wav",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ).insert()

        by_ws = await Clip.find(Clip.workspace_id == ws).sort("-created_at").to_list()
        assert [c.title for c in by_ws] == ["newer", "older"]
        assert {older.id, newer.id} == {c.id for c in by_ws}


class TestJobCrud:
    async def test_status_transitions(self, mongo_db):
        from beanie import PydanticObjectId

        from acemusic.api.models import Job, JobStatus

        job = await Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="generate",
            input_params={"prompt": "lofi"},
        ).insert()
        assert job.status == JobStatus.QUEUED

        job.status = JobStatus.PROCESSING
        await job.save()
        job.status = JobStatus.COMPLETED
        job.result = {"clip_ids": ["1", "2"]}
        await job.save()

        reloaded = await Job.get(job.id)
        assert reloaded.status == JobStatus.COMPLETED
        assert reloaded.result == {"clip_ids": ["1", "2"]}
