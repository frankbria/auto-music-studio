# #619: re-sharing a track whose cover moderation dropped

*2026-11-02T03:55:37Z by Showboat 0.6.1*
<!-- showboat-id: 03c8b3bf-db9c-401b-943c-b805db996e54 -->

Moderation dropped a song's cover after it went to SoundCloud. Sharing that track again is refused (409) until the owner picks a new cover; with one, the platform PUTs the new artwork to the track first, then shares it. If the artwork PUT fails, the track stays private and the next share retries.

```bash
uv run pytest -q -m integration --no-cov tests/test_distribution_status_api.py -k ReshareAfterDroppedCover -v 2>&1 | grep -E "PASSED|FAILED|passed|failed"
```

```output
================= 4 passed, 17 deselected, 2 warnings in 4.06s =================
```
