# #582 Reversing a removal restores its release and SoundCloud sharing

*2026-11-01T01:56:37Z by Showboat 0.6.1*
<!-- showboat-id: 2baa1c75-6375-4b61-b717-7d78186b81a8 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_582` database) and its local SoundCloud stand-in, which logs one line per request to `soundcloud.log`. The seeded musician is also an admin, so one token removes their clip, appeals, and decides the appeal. Moderation has no self-check, and the release logic doesn't care who acts. The clip is public, with a release created through the API.

## 1. The release is uploaded to SoundCloud and made public

```bash
. $DEMO/env.sh >/dev/null; R=$(cat $DEMO_DIR/release); api POST /distribution/soundcloud/upload "{\"clip_id\": \"$CLIP_1\", \"release_id\": \"$R\"}" >/dev/null; api PATCH /releases/$R/visibility '{"state": "public"}' >/dev/null; M "db.releases.findOne({_id: ObjectId('$R')}, {_id: 0, visibility: 1, soundcloud_track_id: 1})"; echo "queued un-shares: $(M 'db.soundcloud_unshares.countDocuments()')"; cat $DEMO_DIR/soundcloud.log
```

```output
{ visibility: 'public', soundcloud_track_id: '4242' }
queued un-shares: 0
POST /tracks
PUT /tracks/4242
```

## 2. Moderation removes the clip: the release goes private and its track is queued for un-share, with the release's visibility recorded

```bash
. $DEMO/env.sh >/dev/null; R=$(cat $DEMO_DIR/release); api POST /admin/moderation/clips "{\"action\": \"remove\", \"clip_ids\": [\"$CLIP_1\"], \"reason\": \"Uncleared sample\"}" >/dev/null; M "db.releases.findOne({_id: ObjectId('$R')}, {_id: 0, visibility: 1, soundcloud_track_id: 1})"; echo "queued un-shares: $(M 'db.soundcloud_unshares.countDocuments()')"; M "db.moderation_log.findOne({action: 'remove'}, {_id: 0, 'details.previous_visibility': 1, 'details.previous_release_visibility': 1})"
```

```output
{ visibility: 'private', soundcloud_track_id: '4242' }
queued un-shares: 1
{
  details: {
    previous_visibility: 'public',
    previous_release_visibility: { '6ae69c4818b9074b168c3149': 'public' }
  }
}
```

## 3. The owner appeals, and the admin reverses it

```bash
. $DEMO/env.sh >/dev/null; R=$(cat $DEMO_DIR/release); : > $DEMO_DIR/soundcloud.log; api POST /clips/$CLIP_1/appeal '{"reason": "The sample is licensed"}' >/dev/null; A=$(jq -r .id $DEMO_DIR/last_body.json); api POST /admin/moderation/appeals/$A '{"decision": "reverse", "note": "Licence checked"}' | head -c 120; echo
```

```output
HTTP 200
{"id":"6ae69c5718b9074b168c314c","clip_id":"6ae69c4518b9074b168c3146","action":"remove","reason":"The sample is
```

## 4. The release is public again, the queued un-share is gone, and the track was re-shared

```bash
. $DEMO/env.sh >/dev/null; R=$(cat $DEMO_DIR/release); M "db.releases.findOne({_id: ObjectId('$R')}, {_id: 0, visibility: 1, soundcloud_track_id: 1})"; echo "queued un-shares: $(M 'db.soundcloud_unshares.countDocuments()')"; echo "SoundCloud calls during the reversal:"; cat $DEMO_DIR/soundcloud.log; M "db.moderation_log.findOne({action: 'appeal_reversed'}, {_id: 0, details: 1})"
```

```output
{ visibility: 'public', soundcloud_track_id: '4242' }
queued un-shares: 0
SoundCloud calls during the reversal:
PUT /tracks/4242
{
  details: {
    appeal_id: '6ae69c5718b9074b168c314c',
    appealed_action: 'remove',
    releases_restored: 1
  }
}
```
