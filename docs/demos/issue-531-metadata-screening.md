# #531 — Screening clip display metadata

*2026-09-27T06:18:22Z by Showboat 0.6.1*
<!-- showboat-id: 415bfab3-abef-4406-9b16-00869e01418f -->

Live API (uvicorn on :8766, this branch) against a throwaway local MongoDB (db `acemusic_demo_531`), job processor off. One seeded Pro musician with 50 credits. `$DEMO` holds scratch helpers: `api METHOD PATH [JSON]` curls the API with the musician's token (`$TOKEN`, sourced from `ids.sh`) and prints status + body; `upload TITLE TAGS` is the plugin's multipart `POST /clips/upload`; `train NAME [DESC]` posts three reference takes to `/voice-models/train`; `clip ID` and `state` read the stored rows straight from Mongo. Four clips were seeded **directly into Mongo**, the way rows written before this change look: `$LEGACY` (lyrics "heil hitler"), `$REVIEWED` (lyrics about suicide, already flagged `self-harm` and reviewed by an admin), `$PLAIN`, and `$RELSRC` (lyrics "white power", used for a release).

## AC1 — upload screens the title and tags it stores

```bash
. $DEMO/ids.sh; $DEMO/upload "Sieg Heil march" "folk"; mongosh --quiet acemusic_demo_531 --eval "print(\"clips titled Sieg Heil march: \" + db.clips.countDocuments({title: \"Sieg Heil march\"}))"
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
clips titled Sieg Heil march: 0
```

Tags are screened as the joined string workers prompt with, so a phrase split across two tags is still caught:

```bash
. $DEMO/ids.sh; $DEMO/upload "March" "sieg, heil"
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
```

A borderline tag is stored, with the flag on the clip (so it enters the moderation queue); a clean upload carries no flag:

```bash
. $DEMO/ids.sh; ID=$($DEMO/upload "Grief" "suicide ballad" | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)[\"id\"])"); echo "stored: $($DEMO/clip $ID)"; ID=$($DEMO/upload "Night drive" "synthwave" | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)[\"id\"])"); echo "stored: $($DEMO/clip $ID)"
```

```output
stored: {"title":"Grief","moderation_flags":["self-harm"],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
stored: {"title":"Night drive","moderation_flags":[],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
```

## AC1 — a title edit screens the new title

```bash
. $DEMO/ids.sh; $DEMO/api PATCH /clips/$PLAIN "{\"title\":\"white power anthem\"}"; echo "stored: $($DEMO/clip $PLAIN)"
```

```output
HTTP 422
{"detail":"This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}

stored: {"title":"Night drive","moderation_flags":[],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
```

A borderline rename is saved and flagged:

```bash
. $DEMO/ids.sh; $DEMO/api PATCH /clips/$PLAIN "{\"title\":\"Terrorist in my head\"}" | head -1; echo "stored: $($DEMO/clip $PLAIN)"
```

```output
HTTP 200
stored: {"title":"Terrorist in my head","moderation_flags":["violent extremism"],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
```

## AC2 — going public or unlisted re-screens everything the clip displays

**Decision:** screening runs on every write (above) **and** when a clip goes public/unlisted. Unlisted counts because `/clips/{id}/public` serves it to anyone holding the link. The visibility check catches text stored before screening existed (the seeded rows) and text that only matches a rule an admin added after the write. It screens title, joined tags and lyrics, even though this PATCH carries none of them.

```bash
. $DEMO/ids.sh; $DEMO/api PATCH /clips/$LEGACY "{\"visibility\":\"unlisted\"}"; echo "stored: $($DEMO/clip $LEGACY)"
```

```output
HTTP 422
{"detail":"This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}

stored: {"title":"Rally","moderation_flags":[],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
```

A clip whose flag an admin already reviewed publishes without being sent back to the queue. Only a *new* category re-queues, so `moderation_reviewed_at` stays set:

```bash
. $DEMO/ids.sh; echo "before: $($DEMO/clip $REVIEWED)"; $DEMO/api PATCH /clips/$REVIEWED "{\"visibility\":\"public\"}" | head -1; echo "after:  $($DEMO/clip $REVIEWED)"
```

```output
before: {"title":"Grief","moderation_flags":["self-harm"],"moderation_reviewed_at":"2026-09-27T06:17:43.974Z","visibility":"private","is_public":false}
HTTP 200
after:  {"title":"Grief","moderation_flags":["self-harm"],"moderation_reviewed_at":"2026-09-27T06:17:43.974Z","visibility":"public","is_public":true}
```

Publishing through a release mirrors visibility onto the source clip, so it is screened the same way, before any SoundCloud sharing sync. Both the release and the clip stay private:

```bash
. $DEMO/ids.sh; REL=$($DEMO/api POST /releases "{\"clip_id\":\"$RELSRC\",\"title\":\"Hymn\",\"artist\":\"Demo\",\"genre\":\"Folk\",\"release_date\":\"2026-10-01T00:00:00Z\"}" | sed -n 2p | python3 -c "import json,sys; print(json.load(sys.stdin)[\"id\"])"); $DEMO/api PATCH /releases/$REL/visibility "{\"state\":\"public\"}"; echo "clip:    $($DEMO/clip $RELSRC)"; mongosh --quiet acemusic_demo_531 --eval "print(\"release: \" + db.releases.findOne({_id: ObjectId(\"$REL\")}).visibility)"
```

```output
HTTP 422
{"detail":"This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}

clip:    {"title":"Hymn","moderation_flags":[],"moderation_reviewed_at":null,"visibility":"private","is_public":false}
release: private
```

The flagged rows are what the admin moderation queue selects (`moderation_flags` set, `moderation_reviewed_at` null — the filter in `services/moderation.py`). The uploaded *Grief* (private) and the renamed clip are queued; the seeded, already-reviewed *Grief* that was just published is not:

```bash
mongosh --quiet acemusic_demo_531 --eval "db.clips.find({moderation_flags: {\$type: \"string\"}, moderation_reviewed_at: null}, {_id: 0, title: 1, visibility: 1, moderation_flags: 1}).forEach(c => print(JSON.stringify(c)))"
```

```output
{"title":"Grief","moderation_flags":["self-harm"],"visibility":"private"}
{"title":"Terrorist in my head","moderation_flags":["violent extremism"],"visibility":"private"}
```

## AC3 — voice-model name and description get the same treatment

Training costs 10 credits. A blocked name is refused **before** anything is charged:

```bash
. $DEMO/ids.sh; $DEMO/state | head -1; $DEMO/train "Heil Hitler voice"; $DEMO/state
```

```output
credits_balance = 50
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
credits_balance = 50
voice models: []
```

A borderline description trains, with the flag stored on the voice model:

```bash
. $DEMO/ids.sh; $DEMO/train "Mine" "for my genocide concept album"; $DEMO/state
```

```output
HTTP 202
{"voice_model_id": "6ab8b566a645e3c9a845d1de", "credits_charged": 10.0}
credits_balance = 40
voice models: [{"name":"Mine","description":"for my genocide concept album","moderation_flags":["violent extremism"]}]
```

Renaming a voice model is screened too. A blocked description is refused and the model is unchanged; a clean rename passes:

```bash
. $DEMO/ids.sh; VM=$(mongosh --quiet acemusic_demo_531 --eval "print(db.voice_models.findOne()._id.toString())"); $DEMO/api PATCH /voice-models/$VM "{\"description\":\"sieg heil\"}"; $DEMO/api PATCH /voice-models/$VM "{\"name\":\"Tenor\"}" | head -1; $DEMO/state | tail -1
```

```output
HTTP 422
{"detail":"This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}

HTTP 200
voice models: [{"name":"Tenor","description":"for my genocide concept album","moderation_flags":["violent extremism"]}]
```

## Evidence summary

| Criterion | Action | Outcome evidence | Status |
|---|---|---|---|
| Upload screens persisted text | `POST /clips/upload` with blocked title / split blocked tags / borderline tag / clean | 422 "wasn't saved… hate speech", 0 rows stored; flagged row carries `["self-harm"]`; clean row `[]` | VERIFIED |
| Title edits screen persisted text | `PATCH /clips/{id}` title blocked / borderline | 422 and title unchanged in Mongo; borderline saved with `["violent extremism"]`, queued | VERIFIED |
| Publish-gating decision documented | `PATCH` visibility unlisted/public; release visibility public | Legacy blocked lyrics → 422, stays private; reviewed flag publishes without re-queue; release + clip stay private on blocked source text. Decision above and in AGENTS.md | VERIFIED |
| Voice-model name/description | `POST /voice-models/train`, `PATCH /voice-models/{id}` | Blocked name → 422, balance stays 50, no model; flagged description stored on the model; blocked rename refused, clean rename saved | VERIFIED |
| Integration tests (real Mongo) block/flag/pass per surface | `tests/test_screening_api.py` (`TestClipMetadataScreening`, `TestReleaseVisibilityScreening`, `TestVoiceModelScreening`) | All passing; each guard mutation-checked (removing it turns its tests red) | VERIFIED |
