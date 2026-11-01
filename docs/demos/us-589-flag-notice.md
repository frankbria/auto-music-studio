# #589 Flagging a clip notifies its owner

*2026-11-01T01:21:39Z by Showboat 0.6.1*
<!-- showboat-id: 8fb91b18-8cc1-4573-9493-e523d59f1ef9 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_589` database). The seeded musician is also made an admin, so the same token can flag their own clip and read their own inbox. Flag actions have no self-check, and the notice goes to the clip's owner either way.

## 1. Before: the inbox is empty

```bash
. $DEMO/env.sh >/dev/null; M "db.users.updateOne({_id: ObjectId('$USER_ID')}, {\$set: {is_admin: true}}).modifiedCount" >/dev/null; api GET /users/me/notifications
```

```output
HTTP 200
{"notifications":[],"unread_count":0,"has_more":false}
```

## 2. An admin flags the clip with a reason

```bash
. $DEMO/env.sh >/dev/null; api POST /admin/moderation/clips "{\"action\": \"flag\", \"clip_ids\": [\"$CLIP_1\"], \"reason\": \"Graphic lyrics\"}"; M "db.clips.findOne({_id: ObjectId('$CLIP_1')}, {_id: 0, content_warning: 1})"
```

```output
HTTP 200
{"results":[{"ok":true,"detail":null,"clip_id":"6ae69415d48a6a2e7b18219f"}]}
{ content_warning: true }
```

## 3. The owner's inbox has the flag notice, with the reason

```bash
. $DEMO/env.sh >/dev/null; api GET /users/me/notifications >/dev/null; jq -c '{unread_count, items: [.notifications[]? // .items[]? | {event_type, clip_id, payload}]}' $DEMO_DIR/last_body.json
```

```output
{"unread_count":1,"items":[{"event_type":"moderation_clip_flagged","clip_id":"6ae69415d48a6a2e7b18219f","payload":{"clip_id":"6ae69415d48a6a2e7b18219f","title":"Demo clip 1","reason":"Graphic lyrics"}}]}
```

## 4. Approve still notifies no one

```bash
. $DEMO/env.sh >/dev/null; api POST /admin/moderation/clips "{\"action\": \"approve\", \"clip_ids\": [\"$CLIP_1\"]}" >/dev/null; api GET /users/me/notifications >/dev/null; jq -c '.unread_count' $DEMO_DIR/last_body.json
```

```output
1
```

## 5. Web: the notice renders as a moderation row, and a moderation notice refetches the clip list

```bash
cd web && npx vitest run lib/notifications.test.ts hooks/use-clips.test.tsx -t '589' --reporter=verbose 2>&1 | grep -E '✓|×|Tests ' | sed 's/ [0-9]*ms$//'
```

```output
✓ lib/notifications.test.ts > toAppNotification (#537) > tells the owner a clip got a content warning, linking to the song (#589)
 ✓ hooks/use-clips.test.tsx > useClips > refetches when a moderation notice arrives, not on other notices (#589)
      Tests  2 passed | 25 skipped (27)
```
