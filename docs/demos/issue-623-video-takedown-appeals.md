# #623: appeals for video takedowns


An owner whose video moderation unpublished can now contest it in the app, one appeal per decision, and admins decide it in the same Appeals queue as clip appeals.

- **API.** `POST /videos/{id}/appeal` files a `ClipAppeal` with `video_id` and `action="unpublish"` against the unpublish in force: the video's latest unpublish while it is still down and its owner isn't banned (`moderation.unpublishes_in_force`, the rule #624's Restore uses). `PATCH` answers an info request. Reversing runs the admin restore, so a takedown's edit copies are lifted too. The appeal lands in the existing claim-and-rollback decide flow (#587), and the restore is now conditional on `moderation_reviewed_at` as well, so an unpublish landing mid-decision is never lifted.
- **Web.** The takedown notice opens `/video/{song}?appeal={video}`, which shows `VideoAppealPanel` (status plus an Appeal form). A Publish refused for a takedown shows the same panel. The admin Appeals queue labels these "Video for {song}" and "Video unpublished". Video appeals no longer show on their song's Library card.

## Evidence

Appeal, reverse and republish, plus edit copies, one-per-decision, ownership, superseding, the mid-decision race, info requests and the queue:

```bash
uv run pytest -m integration tests/test_moderation_content_api.py -k VideoAppeals -q --no-cov 2>&1 | tail -1
```

```output
8 passed, 59 deselected, 1 warning in 3.77s
```

```bash
cd web && npx vitest run components/moderation/VideoAppealPanel.test.tsx components/video/VideoDelivery.test.tsx components/moderation/AppealsPanel.test.tsx lib/appeals.test.ts lib/notifications.test.ts 2>&1 | grep -E "Tests "
```

```output
      Tests  59 passed (59)
```
