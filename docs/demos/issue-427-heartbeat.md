# Issue #427: a sibling worker never re-claims a live video render

*2026-09-18T04:59:55Z*

Before this change the startup stale sweep re-queued any `processing` job whose `started_at` was older than `poll_timeout + 300s`. A video render legitimately outlives that (600s provider poll plus up to 1800s of watermarking), so a second API process starting mid-render would re-claim a live job: the provider billed twice, two `Video` documents, one storage object overwritten. Now the worker heartbeats each job it is running and the sweep re-queues only jobs whose heartbeat has stopped; the `videos` collection also rejects a second document for one job, and each run writes its own storage object. Everything below runs against real MongoDB, the real `JobProcessor` and the real video handler; only the external video provider is stood in for (no credentials here). Timings are scaled: heartbeat every 1s, stale window 5s.

## Criterion 1 — a job actively being processed cannot be re-claimed by a sibling worker. Worker A claims a video job and sits in a render that never finishes. Well past the stale window, worker B starts: its sweep must leave the job alone. Then A is killed mid-render, its heartbeat stops, and worker C starts: now the sweep must re-queue it.

```bash
uv run python /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/cd7085fc-3be9-4c56-a060-5b7a0713bb29/scratchpad/demo427_sibling.py 2>&1 | grep -v 'Connected to MongoDB'
```

```output
video job 6aacc54e8691208166a339df enqueued; stale window = 5s, heartbeat every 1s

--- worker A claims the job and starts the (never-ending) render
LOG acemusic.api.tasks.processor: Job processor started (concurrency=1)
A claimed:                                   status=processing started_at=0.1s ago   heartbeat_at=0.1s ago
7s later (past the 5s stale window):         status=processing started_at=7.1s ago   heartbeat_at=0.0s ago

--- worker B starts mid-render: its startup sweep runs against this job
LOG acemusic.api.tasks.processor: Job processor started (concurrency=1)
after B.start():                             status=processing started_at=9.4s ago   heartbeat_at=0.0s ago
2s later, A still renders:                   status=processing started_at=11.4s ago  heartbeat_at=0.0s ago
heartbeat advanced while B ran: True
LOG acemusic.api.tasks.processor: Job processor stopped
(B claimed nothing: the only job is A's, and it never went back to `queued`)

--- A dies mid-render (graceful cancel leaves the job `processing`, heartbeat stops)
LOG acemusic.api.tasks.processor: Job processor stopped
A stopped:                                   status=processing started_at=11.4s ago  heartbeat_at=0.0s ago
6s later, no heartbeat:                      status=processing started_at=17.4s ago  heartbeat_at=6.0s ago

--- worker C starts: the dead job IS re-queued (log line) and C claims it afresh
LOG acemusic.api.tasks.processor: Re-queued 1 stale processing job(s)
LOG acemusic.api.tasks.processor: Job processor started (concurrency=1)
after C.start():                             status=processing started_at=1.0s ago   heartbeat_at=1.0s ago
LOG acemusic.api.tasks.processor: Job processor stopped
```

After B started, the job is still `processing` with `started_at` far older than the 5s window and a heartbeat under a second old — the sweep keyed on the heartbeat, not the start time — and the heartbeat kept advancing while B ran. Once A was gone and 6s passed without a beat, C's startup logged `Re-queued 1 stale processing job(s)` and claimed it afresh (`started_at` reset to now).

## Criterion 2 — two workers cannot both produce a `Video` document for the same job. The real handler runs twice for one job, the way a stale-requeue race would. The second run must answer with the first run's record, leave one `Video`, and leave the stored object untouched.

```bash
uv run python /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/cd7085fc-3be9-4c56-a060-5b7a0713bb29/scratchpad/demo427_duplicate.py 2>&1 | grep -v 'Connected to MongoDB'
```

```output
Video for job 6aacc5623a00a2e2ef102764 was already recorded by another worker; reusing it
videos indexes: {'_id_': False, 'clip_id_1_user_id_1': False, 'job_id_1': True}
worker A result: {'video_ids': ['6aacc5623a00a2e2ef102765'], 'storage_path': '6aacc5623a00a2e2ef102761/6aacc5623a00a2e2ef102762/videos/6aacc5623a00a2e2ef102763/6aacc5623a00a2e2ef102764-a8a02eff.mp4'}
worker B result: {'video_ids': ['6aacc5623a00a2e2ef102765'], 'storage_path': '6aacc5623a00a2e2ef102761/6aacc5623a00a2e2ef102762/videos/6aacc5623a00a2e2ef102763/6aacc5623a00a2e2ef102764-a8a02eff.mp4'}
same result: True
Video documents for job 6aacc5623a00a2e2ef102764: 1
stored object intact: True
```

The `videos` collection carries a unique index on `job_id` (`job_id_1: True`). The second worker's result is identical to the first's, there is exactly one `Video` for the job, and the stored bytes are still the first render's.

## Criterion 3 — a test covers the requeue path for `video` jobs. The new tests run against the same real MongoDB: a `video` job with a live heartbeat survives the sweep however old its `started_at`, a `video` job with a dead heartbeat is re-queued, the heartbeat advances while a handler runs, a second run for one job reuses the first `Video`, a loser that already uploaded keeps only the winner's object, and a voice-training run's progress writes leave the heartbeat alone.

```bash
uv run pytest tests/test_job_processor.py::TestHeartbeat tests/test_video_tasks.py::TestSiblingWorkerCannotDuplicate 'tests/test_voice_models_api.py::TestTrainingWorker::test_progress_writes_do_not_clobber_the_heartbeat' -m integration -v --no-cov -p no:cacheprovider 2>&1 | grep -E 'PASSED|FAILED|ERROR|passed|failed'
```

```output
tests/test_job_processor.py::TestHeartbeat::test_video_job_with_live_heartbeat_is_not_requeued PASSED [ 16%]
tests/test_job_processor.py::TestHeartbeat::test_video_job_with_dead_heartbeat_is_requeued PASSED [ 33%]
tests/test_job_processor.py::TestHeartbeat::test_heartbeat_advances_while_handler_runs PASSED [ 50%]
tests/test_video_tasks.py::TestSiblingWorkerCannotDuplicate::test_second_run_for_the_same_job_reuses_the_first_video PASSED [ 66%]
tests/test_video_tasks.py::TestSiblingWorkerCannotDuplicate::test_a_loser_that_already_uploaded_keeps_only_the_winners_object PASSED [ 83%]
tests/test_voice_models_api.py::TestTrainingWorker::test_progress_writes_do_not_clobber_the_heartbeat PASSED [100%]
========================= 6 passed, 1 warning in 8.35s =========================
```
