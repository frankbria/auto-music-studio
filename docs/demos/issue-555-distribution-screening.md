# #555 — Screening release and distribution metadata

*2026-10-01T18:40:04Z by Showboat 0.6.1*
<!-- showboat-id: 917fc2cf-827e-470d-84b5-90cb940f5fe1 -->

Live API (uvicorn on :8755, this branch) against a throwaway local MongoDB (db `acemusic_demo_555`), job processor off, local file storage. One seeded Pro musician, ten clips with real WAV audio in storage, and a `SoundCloudConnection` with an unexpired token. SoundCloud has no credentials here, so the API is launched with `SOUNDCLOUD_UPLOAD_URL` pointed at a local stub (`:8756`) that answers `POST /tracks` and appends one line per request to a log; `sclog` prints how many uploads it received. Nothing is mocked inside the API: real HTTP in, real Mongo rows out. Text that leaves the platform is screened by the default rules: "gas the jews" **blocks** (hate speech), "a song about self harm" **flags** (self-harm). Helpers in `$DEMO`: `api METHOD PATH [JSON]` curls with the musician bearer token (`$TOKEN`, from `ids.sh`) and prints `HTTP <code>` plus the body fields that matter (ids and timestamps dropped so the doc is re-runnable); `clip ID` / `release ID` / `relcount ID` print the stored Mongo rows (the ISRC shows as `claimed` or `null`); `reset ID` quietly restores a clip and deletes its releases so every block can be re-run by `showboat verify`.

## AC1 — creating a release screens its metadata

A blocked description is refused with 422, no release row exists for the clip, and the clip has no ISRC (it was refused before the ISRC was claimed):

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $A_BLOCKCREATE; api POST /releases "{\"clip_id\":\"$A_BLOCKCREATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"description\":\"anthem, gas the jews\"}"; relcount $A_BLOCKCREATE; clip $A_BLOCKCREATE
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
releases for clip: 0
clip: {"isrc":null,"lyrics":null,"moderation_flags":[],"moderation_reviewed_at":null}
```

A borderline description is saved (201) and the source clip is flagged and re-queued for moderators (`moderation_reviewed_at` null):

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $B_FLAGCREATE; api POST /releases "{\"clip_id\":\"$B_FLAGCREATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"description\":\"a song about self harm\"}"; relcount $B_FLAGCREATE; clip $B_FLAGCREATE
```

```output
HTTP 201
{"status": "ready", "submitted_channels": [], "title": "Tune", "album_name": null, "description": "a song about self harm", "credits": null}
releases for clip: 1
clip: {"isrc":"claimed","lyrics":null,"moderation_flags":["self-harm"],"moderation_reviewed_at":null}
```

Ordinary text creates the release and leaves the clip unflagged:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $C_CLEANCREATE; api POST /releases "{\"clip_id\":\"$C_CLEANCREATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"description\":\"A late-night cruise.\"}"; relcount $C_CLEANCREATE; clip $C_CLEANCREATE
```

```output
HTTP 201
{"status": "ready", "submitted_channels": [], "title": "Tune", "album_name": null, "description": "A late-night cruise.", "credits": null}
releases for clip: 1
clip: {"isrc":"claimed","lyrics":null,"moderation_flags":[],"moderation_reviewed_at":null}
```

The release language is free text too, and it goes into the DSP bundle `metadata.json`, so it is screened like the rest:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $A_BLOCKCREATE; api POST /releases "{\"clip_id\":\"$A_BLOCKCREATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"language\":\"gas the jews\"}"; relcount $A_BLOCKCREATE; clip $A_BLOCKCREATE
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
releases for clip: 0
clip: {"isrc":null,"lyrics":null,"moderation_flags":[],"moderation_reviewed_at":null}
```

## AC1 — updating a release screens the changed fields

A release is created cleanly with credits "Produced by DJ". A PATCH with blocked credits is refused and the stored credits are unchanged:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $D_UPDATE; api POST /releases "{\"clip_id\":\"$D_UPDATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"credits\":\"Produced by DJ\"}" >/dev/null; R=$(cat $DEMO/last_id); api PATCH /releases/$R "{\"credits\":\"gas the jews\"}"; release $R; clip $D_UPDATE
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
release: {"status":"ready","submitted_channels":[],"album_name":null,"credits":"Produced by DJ"}
clip: {"isrc":"claimed","lyrics":null,"moderation_flags":[],"moderation_reviewed_at":null}
```

A borderline album name is saved (200) and flags the source clip:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $D_UPDATE; api POST /releases "{\"clip_id\":\"$D_UPDATE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\",\"credits\":\"Produced by DJ\"}" >/dev/null; R=$(cat $DEMO/last_id); api PATCH /releases/$R "{\"album_name\":\"a song about self harm\"}"; release $R; clip $D_UPDATE
```

```output
HTTP 200
{"status": "ready", "submitted_channels": [], "title": "Tune", "album_name": "a song about self harm", "description": null, "credits": "Produced by DJ"}
release: {"status":"ready","submitted_channels":[],"album_name":"a song about self harm","credits":"Produced by DJ"}
clip: {"isrc":"claimed","lyrics":null,"moderation_flags":["self-harm"],"moderation_reviewed_at":null}
```

## AC2 — preparing and submitting to LANDR re-screens at send-out

The clip `$E_LEGACY` gets a clean release, then its lyrics are written **straight into Mongo** to the blocked phrase, simulating text stored before a rule existed. Both prepare and submit are refused with 422 and the release stays `ready` with no submitted channels:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $E_LEGACY; api POST /releases "{\"clip_id\":\"$E_LEGACY\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\"}" >/dev/null; R=$(cat $DEMO/last_id); M "db.clips.updateOne({_id:ObjectId(\"$E_LEGACY\")},{\$set:{lyrics:\"gas the jews\"}})" >/dev/null; api POST /releases/$R/prepare/landr; api POST /releases/$R/submit/landr; release $R
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
release: {"status":"ready","submitted_channels":[],"album_name":null,"credits":null}
```

A second release over a clip whose stored lyrics are only borderline goes out (200, status `submitted`) and the clip is flagged:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $F_BORDERLINE; api POST /releases "{\"clip_id\":\"$F_BORDERLINE\",\"title\":\"Tune\",\"artist\":\"DJ\",\"genre\":\"house\",\"release_date\":\"2026-07-01T00:00:00Z\"}" >/dev/null; R=$(cat $DEMO/last_id); M "db.clips.updateOne({_id:ObjectId(\"$F_BORDERLINE\")},{\$set:{lyrics:\"a song about self harm\"}})" >/dev/null; api POST /releases/$R/submit/landr; release $R; clip $F_BORDERLINE
```

```output
HTTP 200
{"status": "submitted", "submitted_channels": ["landr"], "title": "Tune", "album_name": null, "description": null, "credits": null}
release: {"status":"submitted","submitted_channels":["landr"],"album_name":null,"credits":null}
clip: {"isrc":"claimed","lyrics":"a song about self harm","moderation_flags":["self-harm"],"moderation_reviewed_at":null}
```

## AC2 — SoundCloud upload screens the clip and every metadata field

A blocked `key_signature` override (one of the fields SoundCloud would receive) is refused and the stub received nothing:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $G_SCKEY; api POST /distribution/soundcloud/upload "{\"clip_id\":\"$G_SCKEY\",\"metadata_overrides\":{\"key_signature\":\"gas the jews\"}}"; sclog
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
uploads received by SoundCloud stub: 0
```

A clip whose stored lyrics are blocked (written directly to Mongo) is refused too, with no upload:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $H_SCLYRICS; M "db.clips.updateOne({_id:ObjectId(\"$H_SCLYRICS\")},{\$set:{lyrics:\"gas the jews\"}})" >/dev/null; api POST /distribution/soundcloud/upload "{\"clip_id\":\"$H_SCLYRICS\"}"; sclog
```

```output
HTTP 422
{"detail": "This wasn't saved because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing it."}
uploads received by SoundCloud stub: 0
```

A borderline description is uploaded (200, exactly one upload received by the stub) and the clip is flagged:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $I_SCFLAG; api POST /distribution/soundcloud/upload "{\"clip_id\":\"$I_SCFLAG\",\"metadata_overrides\":{\"description\":\"a song about self harm\"}}"; sclog; clip $I_SCFLAG
```

```output
HTTP 200
{"track_id": "4242", "permalink_url": "https://snd.sc/t"}
uploads received by SoundCloud stub: 1
clip: {"isrc":null,"lyrics":null,"moderation_flags":["self-harm"],"moderation_reviewed_at":null}
```

Clean metadata uploads and leaves no flag:

```bash
. $DEMO/ids.sh; . $DEMO/helpers.sh; reset $J_SCCLEAN; api POST /distribution/soundcloud/upload "{\"clip_id\":\"$J_SCCLEAN\",\"metadata_overrides\":{\"genre\":\"house\"}}"; sclog; clip $J_SCCLEAN
```

```output
HTTP 200
{"track_id": "4242", "permalink_url": "https://snd.sc/t"}
uploads received by SoundCloud stub: 1
clip: {"isrc":null,"lyrics":null,"moderation_flags":[],"moderation_reviewed_at":null}
```
