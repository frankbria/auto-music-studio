# #655: bound discovery search cost


Feed, Explore and Search read `GET /api/v1/discover/clips` anonymously. Each cost the PR #652 reviewers raised is now bounded:

| Cost | Now |
|---|---|
| Unanchored regex over title, tags and lyrics on every request | `$text` on the weighted `clip_text_search` index (title 5, tags 2, lyrics 1) |
| Relevance score per match, sorted in memory, no disk | `textScore`, sorted over the text-matched rows only, `allowDiskUse` |
| `total` re-counted on every page | first page only; `null` after it, and the web keeps the first count |
| No query time limit | `maxTimeMS` 3000 on count, find and aggregate; 503 past it |
| Two `distinct` scans per Search load | cached per process for 45 s |
| Every banned id shipped in a `$nin` per request | `Clip.owner_banned_at`, set by ban and cleared by unban |

**Matching semantics changed** (decided: Mongo `$text`): whole words, stemmed in English ("love" finds "Loving You"), any word matching. A partial word finds nothing ("lov" no longer finds "love"), and symbols are plain text.

## Evidence

```bash
uv run pytest -m integration tests/test_discover_api.py -q --no-cov 2>&1 | tail -1
```

```output
29 passed, 3 deselected, 2 warnings in 7.10s
```

```bash
uv run pytest -m integration tests/test_moderation_dashboard_api.py -k stamps_every_owner_clip -q --no-cov 2>&1 | tail -1
```

```output
1 passed, 115 deselected, 1 warning in 3.30s
```

```bash
cd web && npx vitest run components/search/SearchView.test.tsx 2>&1 | grep -E "Tests "
```

```output
      Tests  16 passed (16)
```
