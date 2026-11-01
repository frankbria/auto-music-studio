# #591: the appeals queue reads one log row per clip and action

`_in_force_actions` decides whether each appeal on a queue page is superseded. It used to read every `remove` and `flag` log entry for the page's clips and keep the newest per clip in Python, so its cost grew with each clip's moderation history.

It is now one aggregation: `$match` on the page's clip ids and actions, `$sort` newest first, and `$group` by `(target_id, action)` taking the first `_id`. That returns at most two rows per clip, however long its history. The `(target_id, created_at)` index serves the match and sort.

## Evidence

The superseded and queue tests, including `test_a_flag_back_in_force_after_a_reversed_removal_is_not_superseded`, pass on the aggregation. Flipping its `$sort` to oldest-first turns one of them red, so they pin the "newest wins" rule.

```bash
uv run pytest -m integration tests/test_clip_appeals_api.py -k "superseded or queue" -q --no-cov 2>&1 | tail -1
```

```output
9 passed, 51 deselected, 1 warning in 16.44s
```
