# #581 Contesting a ban, and an admin unban that restores the swept clips

*2026-10-31T23:30:01Z by Showboat 0.6.1*
<!-- showboat-id: 33594d93-1421-448f-8dee-69c2749dbad0 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_581` database), started with `ACEMUSIC_API_SUSPENSION_CONTACT=appeals@example.com`. The seeded musician (`api`, `TOKEN`) owns three clips. The seeded admin (`admin_api`, `ADMIN_TOKEN`) bans and unbans them. `M` queries the demo database.

## 1. Before: one public, one unlisted, one private clip

```bash
. $DEMO/env.sh >/dev/null; M "db.clips.updateOne({_id: ObjectId('$CLIP_1')}, {\$set: {visibility: 'public', is_public: true}}); db.clips.updateOne({_id: ObjectId('$CLIP_2')}, {\$set: {visibility: 'unlisted'}})" >/dev/null; M "db.clips.find({}, {_id: 0, title: 1, visibility: 1, is_public: 1, removed_at: 1, visibility_before_ban: 1}).sort({title: 1}).toArray()"
```

```output
[
  {
    title: 'Demo clip 1',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'public',
    is_public: true
  },
  {
    title: 'Demo clip 2',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'unlisted',
    is_public: false
  },
  {
    title: 'Demo clip 3',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'private',
    is_public: false
  }
]
```

## 2. The ban sweep records what each clip was taken down from, stamped with the ban's own time

```bash
. $DEMO/env.sh >/dev/null; admin_api POST /admin/moderation/users "{\"action\": \"ban\", \"user_ids\": [\"$USER_ID\"], \"reason\": \"Spam\"}"; M "db.users.findOne({_id: ObjectId('$USER_ID')}, {_id: 0, banned_at: 1})"; M "db.clips.find({}, {_id: 0, title: 1, visibility: 1, is_public: 1, removed_at: 1, visibility_before_ban: 1}).sort({title: 1}).toArray()"
```

```output
HTTP 200
{"results":[{"ok":true,"detail":null,"user_id":"6ae679e86136ee6ff07d89eb"}]}
{ banned_at: ISODate('2026-10-31T23:30:02.888Z') }
[
  {
    title: 'Demo clip 1',
    removed_at: ISODate('2026-10-31T23:30:02.888Z'),
    visibility_before_ban: 'public',
    visibility: 'private',
    is_public: false
  },
  {
    title: 'Demo clip 2',
    removed_at: ISODate('2026-10-31T23:30:02.888Z'),
    visibility_before_ban: 'unlisted',
    visibility: 'private',
    is_public: false
  },
  {
    title: 'Demo clip 3',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'private',
    is_public: false
  }
]
```

## 3. The banned musician is told how to contest the ban

```bash
. $DEMO/env.sh >/dev/null; api GET /clips
```

```output
HTTP 403
{"detail":"This account has been suspended. To contest it, contact appeals@example.com."}
```

## 4. The admin lifts the ban. The clips come back as they were, and the action is logged

```bash
. $DEMO/env.sh >/dev/null; admin_api POST /admin/moderation/users "{\"action\": \"unban\", \"user_ids\": [\"$USER_ID\"], \"reason\": \"Appeal upheld\"}"; M "db.clips.find({}, {_id: 0, title: 1, visibility: 1, is_public: 1, removed_at: 1, visibility_before_ban: 1}).sort({title: 1}).toArray()"; admin_api GET /admin/moderation/log >/dev/null; jq -c '.entries[] | {action, target_label, reason, details}' $DEMO_DIR/last_body.json
```

```output
HTTP 200
{"results":[{"ok":true,"detail":null,"user_id":"6ae679e86136ee6ff07d89eb"}]}
[
  {
    title: 'Demo clip 1',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'public',
    is_public: true
  },
  {
    title: 'Demo clip 2',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'unlisted',
    is_public: false
  },
  {
    title: 'Demo clip 3',
    removed_at: null,
    visibility_before_ban: null,
    visibility: 'private',
    is_public: false
  }
]
{"action":"unban","target_label":"Demo Musician","reason":"Appeal upheld","details":{"clips_restored":2,"videos_restored":0}}
{"action":"ban","target_label":"Demo Musician","reason":"Spam","details":{"clips_removed":2,"videos_unpublished":0,"releases_privatized":0,"soundcloud_unshare_queued":[]}}
```

## 5. The musician is back in, and the public clip is public again

```bash
. $DEMO/env.sh >/dev/null; api GET /clips >/dev/null; jq -c '[.clips[] | {title, visibility}]' $DEMO_DIR/last_body.json; curl -s -o /dev/null -w 'public page: HTTP %{http_code}\n' $DEMO_API/clips/$CLIP_1/public
```

```output
[{"title":"Demo clip 3","visibility":"private"},{"title":"Demo clip 2","visibility":"unlisted"},{"title":"Demo clip 1","visibility":"public"}]
public page: HTTP 200
```

## 6. Unbanning someone who isn't banned is refused, and nothing is logged

The count is the one unban from step 4.

```bash
. $DEMO/env.sh >/dev/null; admin_api POST /admin/moderation/users "{\"action\": \"unban\", \"user_ids\": [\"$USER_ID\"]}"; M 'db.moderation_log.countDocuments({action: "unban"})'
```

```output
HTTP 200
{"results":[{"ok":false,"detail":"This account is not banned.","user_id":"6ae679e86136ee6ff07d89eb"}]}
1
```
