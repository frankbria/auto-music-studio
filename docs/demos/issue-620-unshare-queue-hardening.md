# #620: un-share queue hardening


## One drainer per row

`drain_unshares` read the due rows and acted on them without claiming them, so two API instances would both PUT the same track and log `soundcloud_unshared` twice. It now claims one row at a time with `find_one_and_update`, pushing `next_attempt_at` out by a 10-minute lease (`UNSHARE_LEASE`) before SoundCloud is called. A drainer that dies mid-attempt frees its row when the lease expires. The existing generation guard still lets a requeue landing mid-attempt run once more.

## A stuck track is reported again

A track that kept failing (say a permanent 403) retried hourly forever, logged only on its first failure. `soundcloud_unshare_failed` is now logged once more at `UNSHARE_STUCK_AFTER` (24) attempts, about a day at the 1-hour backoff cap, with `stuck_after_attempts` set, so an admin sees it in the activity log. Retries carry on.

## The share-vs-remove release race, proved

A share's clip update matches before a removal stamps the clip, the removal privatizes the releases, and then the share's `release.set(public)` lands. The new test lands a real removal exactly there. The route's trailing `unshare_if_source_removed` privatizes the release again and answers 403. With that call removed, the test goes red.

## Evidence

```bash
uv run pytest -m integration tests/test_soundcloud_unshare_queue.py -k "two_drainers or after_a_day" -q --no-cov 2>&1 | tail -1
```

```output
2 passed, 17 deselected, 2 warnings in 2.77s
```

```bash
uv run pytest -m integration tests/test_moderation_dashboard_api.py -k before_the_shares_release_write -q --no-cov 2>&1 | tail -1
```

```output
1 passed, 114 deselected, 1 warning in 2.71s
```
