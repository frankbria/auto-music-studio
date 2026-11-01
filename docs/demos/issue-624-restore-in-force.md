# #624: Restore only on the takedown in force; one notice per takedown


## Restore follows the takedown in force

The activity log offered Restore on every video-unpublish row, including ones a newer unpublish or a restore had already replaced. An old row's Restore failed ("This video is not taken down") or lifted the newer takedown. Log items now carry `restorable`: true only for a video's latest unpublish while the video is still down. The page computes this with one aggregation, and the dashboard shows Restore only there.

## One notice per takedown

Two concurrent unpublishes each read the video as up and each notified the owner. Unpublish now takes the video down with a write conditional on `removed_at: None` and notifies only when that write matched. A video already down keeps its stamp, as before.

Two concurrent drops each logged and notified. Drop now deletes with `delete_one` and logs and notifies only when it deleted the option. The losing drop reports "Artwork option not found."

## Evidence

```bash
uv run pytest -m integration tests/test_moderation_content_api.py -k OneOutcome -q --no-cov 2>&1 | tail -1
```

```output
3 passed, 54 deselected, 1 warning in 3.16s
```

```bash
cd web && npx vitest run components/moderation/ModerationDashboard.test.tsx -t "restores an unpublished" 2>&1 | grep -E "Tests "
```

```output
      Tests  1 passed | 36 skipped (37)
```
