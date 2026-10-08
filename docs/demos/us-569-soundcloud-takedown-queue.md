# #569 SoundCloud takedowns: queued off-request, retried by the poller, bare uploads recorded, bulk targets isolated

*2026-10-08T05:49:50Z by Showboat 0.6.1*
<!-- showboat-id: 1e062194-6608-40ca-a4a3-acfb0d991846 -->

Live run against `scripts/demo_api_stack.py`: a throwaway `acemusic_demo_569` database, a seeded Pro musician (promoted to admin for this demo) with a linked SoundCloud account, and the local SoundCloud stand-in, which logs one line per request to `soundcloud.log`. The stack runs with `ACEMUSIC_API_SOUNDCLOUD_POLL_INTERVAL=5`, so the poller cycles every 5s. `api` prints the status and body. `M` queries the demo database.

## 1. An upload without a release is recorded on the clip

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-569/env.sh >/dev/null; api POST /distribution/soundcloud/upload "{\"clip_id\": \"$CLIP_1\"}"; M "db.clips.findOne({_id: ObjectId(\"$CLIP_1\")}, {_id: 0, soundcloud_track_ids: 1})"
```

```output
HTTP 200
{"track_id":"4242","permalink_url":"https://soundcloud.example/demo"}
{ soundcloud_track_ids: [ '4242' ] }
```

## 2. A bulk remove returns without touching SoundCloud, and one broken target fails alone

Clip 2's document is corrupted on purpose (an invalid `visibility`), so loading it raises. Before #569 that aborted the whole batch with a 500. The stand-in log is checked straight after the response, before the poller's next cycle.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-569/env.sh >/dev/null; M "db.clips.updateOne({_id: ObjectId(\"$CLIP_2\")}, {\$set: {visibility: \"bogus\"}}).modifiedCount" >/dev/null; : > "$DEMO_DIR/soundcloud.log"; api POST /admin/moderation/clips "{\"action\": \"remove\", \"clip_ids\": [\"$CLIP_1\", \"$CLIP_2\"]}"; echo "PUTs to SoundCloud during the request: $(grep -c "^PUT" "$DEMO_DIR/soundcloud.log")"; M "db.soundcloud_unshares.find({}, {_id: 0, track_id: 1, attempts: 1}).toArray()"
```

```output
HTTP 200
{"results":[{"ok":true,"detail":null,"clip_id":"6ac72efd101be0753566c9d4"},{"ok":false,"detail":"This action hit an unexpected error. Try it again.","clip_id":"6ac72efd101be0753566c9d5"}]}
PUTs to SoundCloud during the request: 0
[ { track_id: '4242', attempts: 0 } ]
```

## 3. The poller drains the queue on its next cycle and logs the outcome

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-569/env.sh >/dev/null; sleep 7; cat "$DEMO_DIR/soundcloud.log"; echo "queued rows left: $(M "db.soundcloud_unshares.countDocuments()")"; M "db.moderation_log.find({action: \"soundcloud_unshared\"}, {_id: 0, actor_id: 1, action: 1, target_id: 1, details: 1}).toArray()"
```

```output
PUT /tracks/4242
queued rows left: 0
[
  {
    actor_id: null,
    action: 'soundcloud_unshared',
    target_id: '6ac72efd101be0753566c9d4',
    details: { track_id: '4242', attempts: 1 }
  }
]
```

## 4. Dropping a distributed cover queues the song's tracks

Clip 3 is uploaded, then a generated artwork option is set as its cover and dropped by moderation. The test seeds the artwork option directly, since generating one needs the image worker.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-569/env.sh >/dev/null; api POST /distribution/soundcloud/upload "{\"clip_id\": \"$CLIP_3\"}" | head -1; ART=$(M "db.artwork_options.insertOne({clip_id: ObjectId(\"$CLIP_3\"), user_id: ObjectId(\"$USER_ID\"), job_id: new ObjectId(), storage_path: \"covers/c3.png\", option_index: 0, moderation_flags: [\"violent extremism\"], created_at: new Date()}).insertedId.toString()"); M "db.clips.updateOne({_id: ObjectId(\"$CLIP_3\")}, {\$set: {artwork_path: \"covers/c3.png\"}}).modifiedCount" >/dev/null; : > "$DEMO_DIR/soundcloud.log"; api POST /admin/moderation/content "{\"target_type\": \"artwork\", \"action\": \"drop\", \"ids\": [\"$ART\"]}"; M "db.moderation_log.findOne({target_type: \"artwork\"}, {_id: 0, details: 1})"; sleep 7; cat "$DEMO_DIR/soundcloud.log"
```

```output
HTTP 200
HTTP 200
{"results":[{"ok":true,"detail":null,"id":"6ac72f0ad1e7c5fba58c48c4"}]}
{
  details: {
    clip_id: '6ac72efd101be0753566c9d6',
    was_cover: true,
    soundcloud_unshare_queued: [ '4243' ]
  }
}
PUT /tracks/4243
```

## 5. A lost grant ends the retries, and that is logged too

The owner unlinks SoundCloud, then clip 3 is removed. Nobody can reach its tracks any more, so the poller abandons them and says so.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-569/env.sh >/dev/null; api DELETE /distribution/soundcloud/connect | head -1; : > "$DEMO_DIR/soundcloud.log"; api POST /admin/moderation/clips "{\"action\": \"remove\", \"clip_ids\": [\"$CLIP_3\"]}" | head -1; sleep 7; echo "PUTs to SoundCloud: $(grep -c "^PUT" "$DEMO_DIR/soundcloud.log")"; echo "queued rows left: $(M "db.soundcloud_unshares.countDocuments()")"; M "db.moderation_log.find({action: \"soundcloud_unshare_abandoned\"}, {_id: 0, actor_id: 1, details: 1}).toArray()"
```

```output
HTTP 204
HTTP 200
PUTs to SoundCloud: 0
queued rows left: 0
[
  {
    actor_id: null,
    details: { track_id: '4243', error: 'No SoundCloud account is linked.' }
  }
]
```

## Not shown live: backoff on a transient failure

The stand-in answers every `PUT` with 200, so a transient SoundCloud error (5xx, timeout, a token refresh that fails in transit) can't be triggered here. `tests/test_soundcloud_unshare_queue.py` covers it against real MongoDB with an injected failing call: the row's `attempts` goes 1→2, `next_attempt_at` moves out by 60s then 120s (capped at 1h even after 60 failures), `soundcloud_unshare_failed` is logged once, and a takedown re-queued mid-attempt still runs.
