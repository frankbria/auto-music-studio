# #607: three functions split below the CRAP ceiling, behaviour unchanged

*2026-11-03T01:07:25Z by Showboat 0.6.1*
<!-- showboat-id: 3cd098ef-4843-4a74-a74d-477287d1913b -->

Issue #607 tracked three functions over the CRAP ceiling of 6. CRAP can't fall below a function's own complexity, so each was split into helpers of cyclomatic complexity 5 or less. The demo shows the complexity before and after, then runs each refactored path against a live API stack (scripts/demo_api_stack.py: throwaway Mongo database, seeded Pro musician, admin, and a local SoundCloud stand-in). The output shows the paths still work the same way. To replay it, set `SCRATCH` to a scratch directory outside the repo and start the stack there with `--dir $SCRATCH/demo-607 --db acemusic_demo_607 --clips 3 --port 8607`. `$SCRATCH/demo_flow.sh` defines `upload`, `report` and `queue` as thin wrappers over the stack's `api` and `admin_api`.

## AC1: every split body is at complexity 5 or less (lizard, main vs branch)

```bash
for f in src/acemusic/api/routers/distribution.py src/acemusic/api/services/appeals.py src/acemusic/api/services/moderation.py; do git show main:$f > $SCRATCH/main_$(basename $f); done
echo "main:"; lizard -l python $SCRATCH/main_*.py | grep -E " (soundcloud_upload|decide|get_queue)@" | sort -u | awk "{print \$2, \$6}" | sed "s/@.*//"
echo "branch:"; lizard -l python src/acemusic/api/routers/distribution.py src/acemusic/api/services/appeals.py src/acemusic/api/services/moderation.py | grep -E " (soundcloud_upload|_owned_release_for|_linked_connection|_download_audio|_upload_track|_record_track|decide|_get_appeal|_claim|_notify_creator|_log_decision|get_queue|_open_reports|_clips_for|_creators_for|_clip_items|_content_items|_jobs_for|_job_prompt|_matches|_queue_page)@" | awk "{print \$2, \$6}" | sed "s/@.*//"
```

```output
main:
11 decide
31 get_queue
17 soundcloud_upload
branch:
3 soundcloud_upload
3 _owned_release_for
4 _linked_connection
3 _download_audio
5 _upload_track
4 _record_track
3 decide
3 _get_appeal
3 _claim
3 _notify_creator
3 _log_decision
4 get_queue
2 _open_reports
5 _clips_for
3 _creators_for
3 _clip_items
4 _content_items
3 _jobs_for
5 _job_prompt
4 _matches
5 _queue_page
```

## AC2a: SoundCloud upload (soundcloud_upload) creates the track and records it on the clip

```bash
. $SCRATCH/demo-607/env.sh; . $SCRATCH/demo_flow.sh; upload $CLIP_1; M "db.clips.findOne({_id: ObjectId(\"$CLIP_1\")}, {_id: 0, soundcloud_track_ids: 1})"; echo "stand-in log:"; cat $DEMO_DIR/soundcloud.log
```

```output
HTTP 200
{"track_id":"4242","permalink_url":"https://soundcloud.example/demo"}
{ soundcloud_track_ids: [ '4242' ] }
stand-in log:
POST /tracks
```

## AC2b: the upload error paths keep their status and message

```bash
. $SCRATCH/demo-607/env.sh; . $SCRATCH/demo_flow.sh; api POST /distribution/soundcloud/upload "{\"clip_id\": \"$CLIP_2\", \"release_id\": \"000000000000000000000000\"}"; M "db.clips.updateOne({_id: ObjectId(\"$CLIP_2\")}, {\$set: {file_path: \"missing.wav\"}}).modifiedCount" >/dev/null; upload $CLIP_2; M "db.clips.updateOne({_id: ObjectId(\"$CLIP_2\")}, {\$set: {file_path: \"$(M "db.clips.findOne({_id: ObjectId(\"$CLIP_1\")}).file_path" | tail -1 | sed "s/$CLIP_1/$CLIP_2/")\"}}).modifiedCount" >/dev/null
```

```output
HTTP 404
{"detail":"Release not found.","code":"not_found"}
HTTP 404
{"detail":"Audio file not found.","code":"not_found"}
```

## AC2c: the moderation queue (get_queue) ranks, filters and pages. Setup: tag and publish clips 2 and 3, then the admin reports them

```bash
. $SCRATCH/demo-607/env.sh; . $SCRATCH/demo_flow.sh; M "db.clips.updateMany({}, {\$set: {style_tags: [\"lofi\"]}}).modifiedCount" >/dev/null; for c in $CLIP_2 $CLIP_3; do api PATCH /clips/$c "{\"visibility\": \"public\"}" | head -1; done; report $CLIP_2 spam | head -1; report $CLIP_3 inappropriate | head -1
echo "page 1 (limit=1, sort=reports: severity breaks the 1-1 tie, inappropriate=3 beats spam=1):"; P1=$(queue "limit=1" | tail -1); echo "$P1" | python3 -c "import json,sys; d=json.load(sys.stdin); print([(i[\"title\"], i[\"categories\"], i[\"severity\"]) for i in d[\"items\"]], \"next_cursor set:\", bool(d[\"next_cursor\"]))"
CUR=$(echo "$P1" | python3 -c "import json,sys; print(json.load(sys.stdin)[\"next_cursor\"])")
echo "page 2 (cursor from page 1):"; queue "limit=1&cursor=$CUR" | tail -1 | python3 -c "import json,sys; d=json.load(sys.stdin); print([(i[\"title\"], i[\"categories\"], i[\"severity\"]) for i in d[\"items\"]], \"next_cursor:\", d[\"next_cursor\"])"
echo "filter category=spam:"; queue "category=spam" | tail -1 | python3 -c "import json,sys; print([i[\"title\"] for i in json.load(sys.stdin)[\"items\"]])"
echo "filter source=automated (no flags yet):"; queue "source=automated" | tail -1
echo "bad cursor:"; queue "cursor=garbage" 
```

```output
HTTP 200
HTTP 200
HTTP 201
HTTP 201
page 1 (limit=1, sort=reports: severity breaks the 1-1 tie, inappropriate=3 beats spam=1):
[('Demo clip 3', {'inappropriate': 1}, 3)] next_cursor set: True
page 2 (cursor from page 1):
[('Demo clip 2', {'spam': 1}, 1)] next_cursor: None
filter category=spam:
['Demo clip 2']
filter source=automated (no flags yet):
{"items":[],"next_cursor":null}
bad cursor:
HTTP 422
{"detail":"Invalid cursor.","code":"invalid_request"}
```

## AC2d: appeal decisions (decide). The admin removes clip 3, the owner appeals, and the admin reverses it

```bash
. $SCRATCH/demo-607/env.sh; . $SCRATCH/demo_flow.sh; admin_api POST /admin/moderation/clips "{\"action\": \"remove\", \"clip_ids\": [\"$CLIP_3\"], \"reason\": \"demo removal\"}" | head -1; M "db.clips.findOne({_id: ObjectId(\"$CLIP_3\")}).visibility"
api POST /clips/$CLIP_3/appeal "{\"reason\": \"It is a lullaby, not inappropriate.\"}" | head -1; AID=$(M "db.clip_appeals.findOne()._id.toString()" | tail -1)
echo "reverse:"; admin_api POST /admin/moderation/appeals/$AID "{\"decision\": \"reverse\", \"note\": \"Fine on review\"}" | tail -1 | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[\"status\"], d[\"admin_note\"], bool(d[\"decided_at\"]))"
echo "clip visibility after reversal:"; M "db.clips.findOne({_id: ObjectId(\"$CLIP_3\")}).visibility"
echo "owner notification:"; M "db.notification_events.find({event_type: /appeal/}, {_id: 0, event_type: 1, \"payload.note\": 1, \"payload.title\": 1, \"payload.video_id\": 1}).toArray()"
echo "moderation log:"; M "db.moderation_log.find({action: /appeal/}, {_id: 0, action: 1, target_type: 1, \"details.appealed_action\": 1}).toArray()"
echo "deciding again:"; admin_api POST /admin/moderation/appeals/$AID "{\"decision\": \"uphold\"}"
echo "unknown appeal:"; admin_api POST /admin/moderation/appeals/000000000000000000000000 "{\"decision\": \"uphold\"}"
```

```output
HTTP 200
private
HTTP 201
reverse:
reversed Fine on review True
clip visibility after reversal:
public
owner notification:
[
  {
    event_type: 'moderation_appeal_reversed',
    payload: { video_id: null, title: 'Demo clip 3', note: 'Fine on review' }
  }
]
moderation log:
[
  {
    action: 'appeal_reversed',
    target_type: 'clip',
    details: { appealed_action: 'remove' }
  }
]
deciding again:
HTTP 409
{"detail":"This appeal has already been decided.","code":"conflict"}
unknown appeal:
HTTP 404
{"detail":"Appeal not found.","code":"not_found"}
```
