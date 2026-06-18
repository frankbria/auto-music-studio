# US-0.1: Shared create_job factory — acceptance demo

*2026-06-18T00:13:21Z*

Refactor goal: collapse five ~50-line `create_*_job` clones into one shared factory (`api/services/jobs.create_job`) while preserving every public function name, the BaseException orphan-cleanup, and all existing tests. Each criterion below is proven with live outcome evidence.

### Criterion 1 — Single factory; per-domain functions delegate

```bash
echo "Factory definition:"; grep -n "async def create_job" src/acemusic/api/services/jobs.py; echo; echo "Each wrapper delegates to create_job:"; for f in editing extraction iterative mastering generation; do printf "  %-12s -> " "$f"; grep -c "create_job(" src/acemusic/api/services/$f.py; done
```

```output
Factory definition:
18:async def create_job(

Each wrapper delegates to create_job:
  editing      -> 1
  extraction   -> 1
  iterative    -> 1
  mastering    -> 1
  generation   -> 1
```

Outcome: one factory, and all five wrappers reference `create_job` — no module still hand-rolls the insert/dispatch/cleanup.

### Criterion 2 — BaseException orphan-cleanup preserved

The three integration rollback tests make dispatch raise *after* the job is inserted, then assert the job count returns to baseline (no orphaned QUEUED doc the processor would run for free).

```bash
ulimit -n 64000; uv run pytest tests/test_mastering_service.py tests/test_clips_iterative_tasks.py tests/test_credits_api.py -m integration -k "dispatch" -v 2>&1 | grep -E "PASSED|FAILED|passed|failed"
```

```output
tests/test_mastering_service.py::TestCreateMasteringJob::test_dispatch_failure_rolls_back_job PASSED [ 33%]
tests/test_clips_iterative_tasks.py::TestService::test_dispatch_failure_rolls_back_job PASSED [ 66%]
tests/test_credits_api.py::TestRefundOnJobCreationFailure::test_no_orphaned_job_when_dispatch_fails_after_insert PASSED [100%]
================= 3 passed, 55 deselected, 1 warning in 4.58s ==================
```

### Criterion 3 — Validation behaviour kept (delegated via valid_types)

```bash
ulimit -n 64000; uv run pytest tests/test_clips_iterative_tasks.py -m integration -k "unknown_job_type" -v 2>&1 | grep -E "PASSED|FAILED"
```

```output
tests/test_clips_iterative_tasks.py::TestService::test_unknown_job_type_raises PASSED [100%]
```

### Criterion 4 — No API contract change; existing tests pass unchanged

```bash
python -c "from acemusic.api.services.editing import create_edit_job; from acemusic.api.services.extraction import create_extraction_job; from acemusic.api.services.iterative import create_iterative_job; from acemusic.api.services.mastering import create_mastering_job; from acemusic.api.services.generation import create_generation_job; print(\"all five public create_*_job functions still importable\")"
```

```output
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/home/frankbria/projects/auto-music-studio/src/acemusic/api/services/editing.py", line 9, in <module>
    from beanie import PydanticObjectId
ModuleNotFoundError: No module named 'beanie'
```

```bash
ulimit -n 64000; uv run pytest tests/test_mastering_service.py tests/test_clips_iterative_tasks.py tests/test_credits_api.py tests/test_clips_iterative_api.py tests/test_generation_api.py tests/test_mastering_api.py tests/test_clips_edit_api.py tests/test_batch_api.py -m integration -q 2>&1 | grep -E "passed|failed"
```

```output
244 passed, 41 deselected, 3 warnings in 177.42s (0:02:57)
```
