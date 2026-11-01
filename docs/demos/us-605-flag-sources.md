# #605 The moderation queue names the outgoing text that raised a flag

*2026-11-01T03:08:15Z by Showboat 0.6.1*
<!-- showboat-id: a8ccd6d6-781e-4dfa-8329-d4f92caf1d90 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_605` database). The seeded musician (made an admin to read the queue) creates a release whose **credits** carry borderline text. The flag lands on the clip, but a moderator's clip view never shows release credits.

```bash
. $DEMO/env.sh >/dev/null; M "db.users.updateOne({_id: ObjectId('$USER_ID')}, {\$set: {is_admin: true}}).modifiedCount" >/dev/null; api POST /releases "{\"clip_id\": \"$CLIP_1\", \"title\": \"Tune\", \"artist\": \"DJ\", \"genre\": \"house\", \"release_date\": \"2026-11-01T00:00:00Z\", \"credits\": \"thanks to everyone who helped me through self harm\"}" | head -1; api GET /admin/moderation/queue >/dev/null; jq -c '.items[] | {title, sources, moderation_flags, flag_sources}' $DEMO_DIR/last_body.json
```

```output
HTTP 201
{"title":"Demo clip 1","sources":["automated"],"moderation_flags":["self-harm"],"flag_sources":["self-harm (release credits)"]}
```

Approving the clip clears the sources along with the review:

```bash
. $DEMO/env.sh >/dev/null; api POST /admin/moderation/clips "{\"action\": \"approve\", \"clip_ids\": [\"$CLIP_1\"]}" >/dev/null; M "db.clips.findOne({_id: ObjectId('$CLIP_1')}, {_id: 0, moderation_flags: 1, moderation_flag_sources: 1})"
```

```output
{ moderation_flags: [ 'self-harm' ], moderation_flag_sources: [] }
```
