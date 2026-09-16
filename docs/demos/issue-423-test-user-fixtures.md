# #423 — shared free_user / pro_user test fixtures

*2026-09-16T21:22:35Z*

Acceptance criterion 2: per-file _make_user helpers that only differ in tier handling are removed. Left: main (scratch worktree). Right: this branch. The helpers that remain compute a unique email or a timestamp and delegate to make_user.

```bash
MAIN=/tmp/claude-1000/-home-frankbria-projects-auto-music-studio/51caba09-9d27-43fe-a436-89327fc4d6a4/scratchpad/main-wt
echo "main:   $(grep -lE "^\s*async def _(make_)?user\(" $MAIN/tests/test_*.py | wc -l) files define a user-creating helper"
echo "branch: $(grep -lE "^\s*async def _(make_)?user\(" tests/test_*.py | wc -l) files still do:"
grep -nE "^\s*async def _(make_)?user\(" tests/test_*.py
echo; echo "each of them delegates to make_user:"
grep -nE "return await make_user\(" tests/test_tier_enforcement_api.py tests/test_credit_reset.py tests/test_usage_api.py
echo; echo "API test files calling get_or_create_user directly: $(grep -l "get_or_create_user(" tests/test_*_api.py | wc -l)"
```

```output
main:   40 files define a user-creating helper
branch: 6 files still do:
tests/test_clips_full_song_api.py:94:async def _make_user(email: str, *, balance: float | None = None):
tests/test_clips_iterative_api.py:115:async def _make_user(email: str, *, balance: float | None = None):
tests/test_credit_reset.py:50:    async def _user(self, label: str, *, tier: str, balance: float, created: datetime, last_reset=None) -> User:
tests/test_tier_enforcement_api.py:51:async def _user(label: str, tier: str = "free", credits: float = 500.0) -> User:
tests/test_usage_api.py:53:async def _make_user(email: str, *, monthly: float = 0.0, purchased: float = 0.0):
tests/test_usage_service.py:25:async def _user(email: str, *, monthly: float = 0.0, purchased: float = 0.0) -> User:

each of them delegates to make_user:
tests/test_tier_enforcement_api.py:53:    return await make_user(email, tier=tier, credits_balance=credits)
tests/test_credit_reset.py:52:        return await make_user(
tests/test_credit_reset.py:153:        return await make_user(
tests/test_usage_api.py:54:    return await make_user(

API test files calling get_or_create_user directly: 0
```

Acceptance criterion 1: shared free_user / pro_user fixtures exist and are used. Below: the fixture definitions, the files that take them, and a live round-trip against a throwaway MongoDB showing the tier each fixture-created user is stored with.

```bash
grep -nE "^async def (free_user|pro_user)" tests/conftest.py
echo; echo "test files taking the fixtures as parameters:"
grep -lE "\b(free_user|pro_user)\b" tests/test_*.py
echo; echo "tests taking pro_user in test_distribution_prep_api.py: $(grep -c "pro_user)" tests/test_distribution_prep_api.py)"
```

```output
309:async def free_user(mongo_db):
317:async def pro_user(mongo_db):

test files taking the fixtures as parameters:
tests/test_distribution_prep_api.py
tests/test_user_fixtures.py

tests taking pro_user in test_distribution_prep_api.py: 17
```

```bash
uv run python - <<'PY'
import asyncio, os, uuid
from acemusic.api import database
from acemusic.api.models import User
from acemusic.api.services.tiers import PRO
from acemusic.api.settings import ApiSettings
from tests.users import make_user

async def main():
    settings = ApiSettings(_env_file=None, mongodb_url=os.environ["ACEMUSIC_TEST_MONGODB_URL"], mongodb_db_name=f"demo_{uuid.uuid4().hex[:6]}")
    client = await database.init_db(settings)
    try:
        free = await make_user("free@example.com")                 # what free_user does
        pro = await make_user("pro@example.com", tier=PRO)          # what pro_user does
        rich = await make_user("rich@example.com", credits_balance=250.0, purchased_credits=40.0)
        for u in (free, pro, rich):
            stored = await User.get(u.id)
            print(f"{stored.email:18} tier={stored.subscription_tier:5} credits={stored.credits_balance:6.1f} purchased={stored.purchased_credits}")
    finally:
        await client.drop_database(settings.mongodb_db_name)
        await database.close_db(client)
asyncio.run(main())
PY
```

```output
free@example.com   tier=free  credits=  10.0 purchased=0.0
pro@example.com    tier=pro   credits=  10.0 purchased=0.0
rich@example.com   tier=free  credits= 250.0 purchased=40.0
```

Acceptance criterion 3: tests for ungated operations still run as a free user. The default tier is free and Pro is opted into per call site, never per file. Crop and speed are free operations; the parametrized editing tests derive the tier from the operation and pass as a free musician.

```bash
echo "make_user() calls across tests: $(grep -ho "make_user(" tests/test_*.py | wc -l) total, $(grep -h "make_user(" tests/test_*.py | grep -c "tier=PRO") say tier=PRO, $(grep -h "make_user(" tests/test_*.py | grep -c "tier=") state any tier"
echo "file-level Pro defaults left: $(grep -lE "subscription_tier = PRO|tier: str = \"pro\"" tests/test_*.py | wc -l)"
echo; grep -n -A1 "def _tier_for" tests/test_clips_edit_api.py | head -2; grep -n "return \"pro\" if" tests/test_clips_edit_api.py
```

```output
make_user() calls across tests: 640 total, 177 say tier=PRO, 183 state any tier
file-level Pro defaults left: 1

93:def _tier_for(operation: str) -> str:
94-    """Which tier may perform ``operation`` (#403).
101:    return "pro" if operation == "remaster" else "free"
```

```bash
uv run pytest "tests/test_clips_edit_api.py::TestCropEnqueue" "tests/test_clips_edit_api.py::TestSpeedEnqueue" "tests/test_tier_enforcement_api.py" -k "Enqueue or free_account" -m "integration or not integration" --no-cov -p no:cacheprovider -v 2>&1 | grep -E "PASSED|FAILED|passed|failed" | sed -E "s/^tests\///; s/ *\[ *[0-9]+%\]$//"
```

```output
test_clips_edit_api.py::TestCropEnqueue::test_returns_202_and_persists_resolved_params PASSED
test_clips_edit_api.py::TestCropEnqueue::test_snap_to_beat_resolves_snapped_bounds PASSED
test_clips_edit_api.py::TestSpeedEnqueue::test_multiplier_returns_202_and_persists_params PASSED
test_clips_edit_api.py::TestSpeedEnqueue::test_target_bpm_resolves_final_multiplier PASSED
test_clips_edit_api.py::TestSpeedEnqueue::test_preserve_pitch_false_logs_warning PASSED
test_tier_enforcement_api.py::TestReadsStayOpen::test_a_free_account_can_still_read_its_voice_models PASSED
test_tier_enforcement_api.py::TestReadsStayOpen::test_a_free_account_can_still_read_its_credits PASSED
test_tier_enforcement_api.py::TestResolutionAndFormatGates::test_a_free_account_may_render_720p PASSED
test_tier_enforcement_api.py::TestResolutionAndFormatGates::test_a_free_account_is_refused_above_720p[1080p] PASSED
test_tier_enforcement_api.py::TestResolutionAndFormatGates::test_a_free_account_is_refused_above_720p[4k] PASSED
test_tier_enforcement_api.py::TestLosslessExportGate::test_a_free_account_may_download_mp3 PASSED
test_tier_enforcement_api.py::TestLosslessExportGate::test_a_free_account_is_refused_a_lossless_conversion[wav] PASSED
test_tier_enforcement_api.py::TestLosslessExportGate::test_a_free_account_is_refused_a_lossless_conversion[flac] PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_is_refused_batch_stems PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_is_refused_a_lossless_batch_export[wav] PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_is_refused_a_lossless_batch_export[wav32] PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_is_refused_a_lossless_batch_export[flac] PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_may_batch_export_mp3 PASSED
test_tier_enforcement_api.py::TestBatchIsNotTheCheapWayIn::test_a_free_account_is_refused_a_per_clip_daw_export PASSED
test_tier_enforcement_api.py::TestReleaseBundlingIsPro::test_a_free_account_cannot_prepare_a_bundle PASSED
test_tier_enforcement_api.py::TestReleaseBundlingIsPro::test_a_free_account_cannot_mark_a_release_submitted PASSED
================ 21 passed, 35 deselected, 1 warning in 39.01s =================
```

Acceptance criterion 4: the test conventions say which fixture to reach for and why free is the default.

```bash
sed -n "/Test users (#423)/,/test_tier_enforcement_api.py\`\./p" AGENTS.md
```

```output
- **Test users (#423)**: create them with the `free_user` / `pro_user` fixtures (`tests/conftest.py`), or
  `tests.users.make_user(email, tier=..., **fields)` when a test needs several accounts. Never write a
  per-file `_make_user`; `tests/test_user_fixtures.py` fails if an API test file calls
  `get_or_create_user` directly.
  - **Free is the default** because it is what a real signup gets. A Pro-by-default helper keeps passing
    when an ungated endpoint is accidentally gated, so it proves nothing about the gate.
  - Say `tier=PRO` at the call site that needs it, never as a file-level default. Tests parametrized by
    capability derive it from the parameter (`_tier_for(operation)` in `tests/test_clips_edit_api.py`).
  - Use `pro_user` only for behaviour *behind* a gate; the gate itself is tested as free in
    `tests/test_tier_enforcement_api.py`.
```

The guard behind criterion 2, exercised: plant a direct get_or_create_user call in an API test file and the convention test names the file. The tree is restored afterwards.

```bash
echo "# user_service.get_or_create_user(email=x)" >> tests/test_jobs_api.py
uv run pytest tests/test_user_fixtures.py::test_api_tests_do_not_create_users_directly --no-cov -p no:cacheprovider -q 2>&1 | grep -E "AssertionError|passed|failed" | head -2
git checkout -q tests/test_jobs_api.py && echo "restored: $(git status --short tests/test_jobs_api.py | wc -l) modified files"
```

```output
E       AssertionError: create users via tests.users.make_user, not directly: ['test_jobs_api.py']
tests/test_user_fixtures.py:27: AssertionError
restored: 0 modified files
```
