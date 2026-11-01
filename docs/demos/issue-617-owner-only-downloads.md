# #617: clip downloads are owner-only


Owner decision (2026-10-08): visitors may **stream** a public clip but not **download** it. The web already offered visitors no Download. The API now matches it:

- `GET /clips/{id}/audio` and the DAW-export `GET /clips/{id}/export/daw` resolve the clip through `get_owned_clip`, so a non-owner gets `404 Clip not found.` whatever the clip's visibility, the same as every other owner-only route
- `get_clip_for_audio_access` is unchanged, so reporting, similar clips and artwork keep working on public clips. Streaming (`/stream`, public links, videos) stays public
- No visitor surface (song page, feed, explore, player) fetches `/audio`. Only the owner's editor, studio and mastering previews do

## Evidence

Non-owner downloads as a free and a Pro user, across public, unlisted and private clips, plus the owner's own download:

```bash
uv run pytest -m integration tests/test_clips_visibility_api.py tests/test_daw_export_api.py tests/test_clips_api.py -q --no-cov -k "owner_only or other_users" 2>&1 | tail -1
```

```output
13 passed, 123 deselected, 2 warnings in 3.54s
```

```bash
uv run pytest -m integration tests/test_artwork_api.py tests/test_clip_reports_api.py tests/test_similar_clips.py tests/test_discover_api.py -q --no-cov 2>&1 | tail -1
```

```output
70 passed, 18 deselected, 2 warnings in 10.84s
```
