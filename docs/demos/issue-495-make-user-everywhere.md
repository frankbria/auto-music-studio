# #495 — make_user everywhere, guard every test file

*2026-09-18T19:51:38Z*

AC1: the five task/service test files create users via make_user; video states the tier at every call. Left: main. Right: this branch.

```bash
FILES="test_artwork_service test_artwork_tasks test_mastering_tasks test_studio_tasks test_video_tasks"
for f in $FILES; do printf "%-22s main: %s direct calls  branch: %s direct, %s make_user\n" $f "$(git show main:tests/$f.py | grep -c "get_or_create_user(")" "$(grep -c "get_or_create_user(" tests/$f.py)" "$(grep -c "make_user(" tests/$f.py)"; done
echo; echo "video helper signatures on main vs branch:"
git show main:tests/test_video_tasks.py | grep -E "^async def _make_(job_and_clip|edit_job_and_source)"
grep -E "^async def _make_(job_and_clip|edit_job_and_source)" tests/test_video_tasks.py
echo; echo "video helper calls without an explicit tier: $(grep -cE "_make_(job_and_clip|edit_job_and_source)\((storage)?\)" tests/test_video_tasks.py)"
echo "calls stating tier: PRO=$(grep -cE "_make_(job_and_clip|edit_job_and_source)\(.*tier=PRO" tests/test_video_tasks.py) FREE=$(grep -cE "_make_(job_and_clip|edit_job_and_source)\(.*tier=FREE" tests/test_video_tasks.py)"
```

```output
test_artwork_service   main: 1 direct calls  branch: 0 direct, 1 make_user
test_artwork_tasks     main: 1 direct calls  branch: 0 direct, 1 make_user
test_mastering_tasks   main: 1 direct calls  branch: 0 direct, 1 make_user
test_studio_tasks      main: 1 direct calls  branch: 0 direct, 1 make_user
test_video_tasks       main: 2 direct calls  branch: 0 direct, 2 make_user

video helper signatures on main vs branch:
async def _make_job_and_clip(*, tier: str = "pro") -> tuple[Job, Clip]:
async def _make_edit_job_and_source(storage: LocalStorage, *, tier: str = "pro") -> tuple[Job, Video]:
async def _make_job_and_clip(*, tier: str) -> tuple[Job, Clip]:
async def _make_edit_job_and_source(storage: LocalStorage, *, tier: str) -> tuple[Job, Video]:

video helper calls without an explicit tier: 0
calls stating tier: PRO=20 FREE=4
```

AC1 outcome: the tier is load-bearing. Flipping one verbatim-bytes video test from PRO to FREE makes it fail (watermarked output), then it is restored.

```bash
B=$(mktemp); cp tests/test_video_tasks.py $B
sed -i "0,/_make_job_and_clip(tier=PRO)/s//_make_job_and_clip(tier=FREE)/" tests/test_video_tasks.py
echo "mutated (FREE): $(uv run pytest tests/test_video_tasks.py -m integration -q --no-cov -p no:cacheprovider -k test_success_stores_mp4_and_records_video 2>&1 | sed "s/\x1b\[[0-9;]*m//g" | grep -oE "(WatermarkError|[0-9]+ (passed|failed))" | sort -u | tr "\n" " ")"
cp $B tests/test_video_tasks.py; rm $B
echo "restored (PRO): $(uv run pytest tests/test_video_tasks.py -m integration -q --no-cov -p no:cacheprovider -k test_success_stores_mp4_and_records_video 2>&1 | sed "s/\x1b\[[0-9;]*m//g" | grep -oE "[0-9]+ (passed|failed)")"
```

```output
mutated (FREE): 1 failed WatermarkError 
restored (PRO): 1 passed
```

AC2: the guard scans every tests/test_*.py except the user-service allow-list. A planted non-API offender is caught; the allow-listed service tests are not flagged; the real tree passes.

```bash
printf "async def _u():\n    await user_service.get_or_create_user(email=\"x\")\n" > tests/test_zz_canary_tasks.py
uv run pytest tests/test_user_fixtures.py::test_tests_do_not_create_users_directly -q --no-cov -p no:cacheprovider 2>&1 | sed "s/\x1b\[[0-9;]*m//g" | grep -oE "directly: \[.*\]|[0-9]+ (passed|failed)"
rm tests/test_zz_canary_tasks.py
echo "allow-listed files still calling the service: $(grep -l "get_or_create_user(" tests/test_user_service.py tests/test_oauth_identities.py | xargs -n1 basename | tr "\n" " ")"
uv run pytest tests/test_user_fixtures.py::test_tests_do_not_create_users_directly -q --no-cov -p no:cacheprovider 2>&1 | sed "s/\x1b\[[0-9;]*m//g" | grep -oE "[0-9]+ (passed|failed)"
```

```output
directly: ['test_zz_canary_tasks.py']
1 failed
allow-listed files still calling the service: test_user_service.py test_oauth_identities.py 
1 passed
```

AC3: the AGENTS.md note no longer says API.

```bash
grep -A4 "Test users (#423)" AGENTS.md | grep "fails if"
```

```output
  per-file `_make_user`; `tests/test_user_fixtures.py` fails if any test file calls
```
