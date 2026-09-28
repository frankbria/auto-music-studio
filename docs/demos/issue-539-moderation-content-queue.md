# Issue #539: flagged videos, artwork and voice models in the moderation queue (PR #570)

*2026-09-28T20:09:12Z by Showboat 0.6.1*
<!-- showboat-id: 603a56d6-5c42-4df7-9a77-b56fa8f1ed5a -->

Live stack: FastAPI on :8539 against a throwaway local Mongo database `demo_539_content` (random JWT secret, local storage), and a production `next start` build of `web/` on :3539 proxying to it. The seed uses Beanie + storage: Ada Admin (`is_admin=True`) and Cleo Creator (Pro). Cleo has:
- a clip, **Fight Night**, flagged `violence`
- a **published video** for *War Anthem*, rendered from a job whose prompt "soldiers marching through fire" screened as `violent extremism`
- a generated **artwork option** for *Ash City* (prompt "a city burning at night", `violent extremism`), selected as that song's cover
- a **voice model** "Rape survivor" (`sexual violence`)
- an unflagged voice model **Warm Tenor**, whose stored description ("for my genocide concept album") was never screened

Commands run from the scratch dir. The `tok_*.env` files export `$ACCESS`/`$REFRESH`, so no JWT is inlined here.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; source tok_admin.env; curl -s localhost:8539/api/v1/admin/moderation/queue -H "Authorization: Bearer $ACCESS" | jq -r '.items[] | [.target_type, .title, (.description // "-"), (.moderation_flags|join(",")), (.sources|join(",")), .severity, (if .published == null then "-" else (.published|tostring) end), .creator_name] | @tsv'
```

```output
voice_model	Rape survivor	spoken word	sexual violence	automated	3	-	Cleo Creator
artwork	Ash City	a city burning at night	violent extremism	automated	3	-	Cleo Creator
video	War Anthem	soldiers marching through fire	violent extremism	automated	3	true	Cleo Creator
clip	Fight Night	-	violence	automated	3	-	Cleo Creator
```

**Queue (API):** all four kinds share one queue. Each row carries its `target_type`, the text screening flagged (the job prompt, or the voice description), its flags, and, for the video, whether it is published.

## AC2: the dashboard shows each item's type, with the actions that fit it

Ada Admin signs in with a freshly minted refresh cookie and opens `/admin/moderation`. The session really is authenticated: the page fetched `/api/credits/balance` and the admin queue. `rows.js` prints each rendered row as `title | Type column | text under the title | source | preview | row buttons`.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'performance.getEntriesByType("resource").map(e=>e.name).filter(n=>n.includes("/api/")).join(" ")'; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval "$(cat rows.js)" | jq -r .
```

```output
"http://localhost:3539/api/auth/refresh http://localhost:3539/api/users/me http://localhost:3539/api/users/me/notifications?offset=0 http://localhost:3539/api/credits/balance http://localhost:3539/api/admin/moderation/queue http://localhost:3539/api/admin/moderation/log?limit=100"
Rape survivor | Voice model | spoken word | Automated sexual violence | no preview | Approve,Warn creator,Ban creator
Ash City | Artwork | a city burning at night | Automated violent extremism | no preview | Approve,Drop,Warn creator,Ban creator
War Anthem | Video | soldiers marching through fire / published | Automated violent extremism | video /api/videos/6abac9432ce210a3611b0be4/stream | Approve,Unpublish,Warn creator,Ban creator
Fight Night | Clip | public | Automated violence | audio /api/clips/6abac9432ce210a3611b0be0/stream | Approve,Remove,Flag,Warn creator,Ban creator
```

The video row plays its MP4 inline through the web proxy (a range request answers `206 video/mp4`). The clip keeps its audio player, and artwork and voice models have no preview. Actions are per type: **Unpublish** only on the video, **Drop** only on the artwork, **Remove/Flag** only on the clip, and Approve alone on the voice model (plus the creator actions every row has).

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'fetch(document.querySelector("video").src, {headers: {range: "bytes=0-99"}}).then(r => r.status + " " + r.headers.get("content-type"))'
```

```output
"206 video/mp4"
```

```bash {image}
![Queue with a Type column: voice model, artwork, video (inline player) and clip, each with its own actions](docs/demos/issue539-queue-types.png)
```

![Queue with a Type column: voice model, artwork, video (inline player) and clip, each with its own actions](64c2cda8-2026-09-28.png)

## AC2: unpublish a video from the dashboard

Clicking **Unpublish** on the War Anthem row opens the reason dialog, which says what the action does. The admin enters a reason.

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'document.querySelector("[role=dialog]").innerText + " | reason=" + document.querySelector("#moderation-reason").value'
```

```output
"Unpublish 1 video?\n\nUnpublished videos come off their song pages and cannot be published again.\n\nReason (optional)\nCancel\nUnpublish\nClose | reason=Glorifies violent extremism"
```

```bash {image}
![Unpublish dialog with a reason entered](docs/demos/issue539-unpublish-dialog.png)
```

![Unpublish dialog with a reason entered](34bd05fd-2026-09-28.png)

Confirming sends the action. The dashboard reports it, refetches, and the video's row is gone from the queue.

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("[role=dialog] button")].find(b => b.textContent === "Unpublish").click()' >/dev/null; sleep 2; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'document.querySelector("[role=status]")?.textContent'; cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval "$(cat rows.js)" | jq -r .
```

```output
"Unpublished 1 video."
Rape survivor | Voice model | spoken word | Automated sexual violence | no preview | Approve,Warn creator,Ban creator
Ash City | Artwork | a city burning at night | Automated violent extremism | no preview | Approve,Drop,Warn creator,Ban creator
Fight Night | Clip | public | Automated violence | audio /api/clips/6abac9432ce210a3611b0be0/stream | Approve,Remove,Flag,Warn creator,Ban creator
```

**Outcome.** The stored video is unpublished and stamped removed and reviewed. The public song page no longer serves it. Cleo's own attempt to publish it again is refused with 403.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; V=$(jq -r .video ids.json); C=$(jq -r .war_anthem ids.json); mongosh --quiet demo_539_content --eval "const v = db.videos.findOne({_id: ObjectId('$V')}); print(JSON.stringify({published: v.published, removed_at: !!v.removed_at, moderation_reviewed_at: !!v.moderation_reviewed_at, moderation_flags: v.moderation_flags}))"; echo "song page: $(curl -s -o /dev/null -w '%{http_code}' localhost:8539/api/v1/videos/for-clip/$C)"; source tok_creator.env; curl -s -w ' HTTP %{http_code}\n' -X POST localhost:8539/api/v1/videos/$V/publish -H "Authorization: Bearer $ACCESS"
```

```output
{"published":false,"removed_at":true,"moderation_reviewed_at":true,"moderation_flags":["violent extremism"]}
song page: 404
{"detail":"This video was removed by moderation."} HTTP 403
```

## AC2: drop a generated artwork option

First, the before state: Ash City's cover is the flagged option, and its image is in storage.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; A=$(jq -r .ash_city ids.json); mongosh --quiet demo_539_content --eval "print(db.clips.findOne({_id: ObjectId('$A')}).artwork_path)" | tee /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo/artpath; ls storage/$(cat artpath) >/dev/null && echo 'image object: present'
```

```output
6abac9432ce210a3611b0bde/6abac9432ce210a3611b0bdf/artwork/6abac9432ce210a3611b0be2/6abac9432ce210a3611b0be5/0.png
image object: present
```

Clicking **Drop** on the Ash City row, then confirming the dialog:

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("tbody tr")].find(r => r.innerText.includes("Ash City")).querySelectorAll("button").forEach(b => b.textContent === "Drop" && b.click())' >/dev/null; sleep 1; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'document.querySelector("[role=dialog]").innerText.split("\n")[0] + " | " + document.querySelector("[role=dialog] p")?.textContent'; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("[role=dialog] button")].find(b => b.textContent === "Drop").click()' >/dev/null; sleep 2; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'document.querySelector("[role=status]")?.textContent'; cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval "$(cat rows.js)" | jq -r .
```

```output
"Drop 1 artwork image? | Dropped artwork is deleted, and taken off its song if it was the selected cover."
"Dropped 1 artwork image."
Rape survivor | Voice model | spoken word | Automated sexual violence | no preview | Approve,Warn creator,Ban creator
Fight Night | Clip | public | Automated violence | audio /api/clips/6abac9432ce210a3611b0be0/stream | Approve,Remove,Flag,Warn creator,Ban creator
```

**Outcome.** The option document is deleted, Ash City's cover is cleared (it pointed at that option), and the image object is gone from storage.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; A=$(jq -r .ash_city ids.json); O=$(jq -r .artwork ids.json); mongosh --quiet demo_539_content --eval "print('option doc: ' + db.artwork_options.countDocuments({_id: ObjectId('$O')}) + ' | Ash City artwork_path: ' + db.clips.findOne({_id: ObjectId('$A')}).artwork_path)"; ls storage/$(cat artpath) 2>/dev/null || echo 'image object: deleted'
```

```output
option doc: 0 | Ash City artwork_path: null
image object: deleted
```

## AC4: voice models join the queue; approve one

**Approve** on the voice-model row takes one click. The model is stamped reviewed and leaves the queue.

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("tbody tr")].find(r => r.innerText.includes("Rape survivor")).querySelector("button").click()' >/dev/null; sleep 2; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval 'document.querySelector("[role=status]")?.textContent'; cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval "$(cat rows.js)" | jq -r .; V=$(jq -r .voice ids.json); mongosh --quiet demo_539_content --eval "print('reviewed: ' + !!db.voice_models.findOne({_id: ObjectId('$V')}).moderation_reviewed_at)"
```

```output
"Approved 1 voice model."
Fight Night | Clip | public | Automated violence | audio /api/clips/6abac9432ce210a3611b0be0/stream | Approve,Remove,Flag,Warn creator,Ban creator
reviewed: true
```

## AC4: a rename re-screens the full name + description

Warm Tenor's description ("for my genocide concept album") was stored unscreened. Cleo renames only the **name**. The rename screens the whole name + description, so the old description's `violent extremism` flag is caught, and the model enters the queue.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; source tok_creator.env; W=$(jq -r .warm_tenor ids.json); curl -s -X PATCH localhost:8539/api/v1/voice-models/$W -H "Authorization: Bearer $ACCESS" -H 'content-type: application/json' -d '{"name": "Warm Baritone"}' | jq -c '{name, description}'; source tok_admin.env; curl -s localhost:8539/api/v1/admin/moderation/queue -H "Authorization: Bearer $ACCESS" | jq -r '.items[] | [.target_type, .title, .description, (.moderation_flags|join(","))] | @tsv'
```

```output
{"name":"Warm Baritone","description":"for my genocide concept album"}
voice_model	Warm Baritone	for my genocide concept album	violent extremism
clip	Fight Night		violence
```

## Activity log: every action, labelled by what it targeted

```bash
/home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("[role=tab]")].find(t => t.textContent === "Activity log").dispatchEvent(new MouseEvent("mousedown", {bubbles: true}))' >/dev/null; sleep 1; /home/frankbria/.nvm/versions/node/v24.12.0/bin/agent-browser --session d539 eval '[...document.querySelectorAll("[role=tabpanel] tbody tr")].map(r => [...r.querySelectorAll("td")].slice(1).map(c => c.innerText).join(" | ")).join("\n")' | jq -r .
```

```output
Approved voice model | voice_model 6abac9432ce210a3611b0be7 | 6abac9432ce210a3611b0bdd | -
Dropped artwork | artwork 6abac9432ce210a3611b0be6 | 6abac9432ce210a3611b0bdd | -
Unpublished video | video 6abac9432ce210a3611b0be4 | 6abac9432ce210a3611b0bdd | Glorifies violent extremism
```

```bash {image}
![Activity log: Approved voice model, Dropped artwork, Unpublished video with its reason](docs/demos/issue539-activity-log.png)
```

![Activity log: Approved voice model, Dropped artwork, Unpublished video with its reason](568a0eea-2026-09-28.png)

## AC1: flags are persisted on the output, end to end

Cleo asks for cover art for Fight Night with a borderline style prompt. The API's real screening lets it through with a `violent extremism` flag on the job. The real artwork task then renders the job; the external image API isn't available here, so `run_artwork_job.py` passes a local image stand-in. Every `ArtworkOption` it stores carries the job's flag and no review stamp, so all four enter the queue. (The video task copies flags the same way; `tests/test_video_tasks.py` covers that, including an edit inheriting a takedown.)

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; source tok_creator.env; A=$(jq -r .fight_night ids.json); JOB=$(curl -s -X POST localhost:8539/api/v1/clips/$A/artwork/generate -H "Authorization: Bearer $ACCESS" -H 'content-type: application/json' -d '{"style_prompt": "album art for my genocide concept album"}' | jq -r .job_id); source env.sh; (cd /home/frankbria/projects/auto-music-studio && uv run python /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo/run_artwork_job.py $JOB 2>/dev/null); source tok_admin.env; curl -s localhost:8539/api/v1/admin/moderation/queue -H "Authorization: Bearer $ACCESS" | jq -r '.items[] | [.target_type, .title, .description, (.moderation_flags|join(","))] | @tsv'
```

```output
job.input_params.moderation_flags = ['violent extremism']
ArtworkOption 0: moderation_flags=['violent extremism'] reviewed=None
ArtworkOption 1: moderation_flags=['violent extremism'] reviewed=None
ArtworkOption 2: moderation_flags=['violent extremism'] reviewed=None
ArtworkOption 3: moderation_flags=['violent extremism'] reviewed=None
artwork	Fight Night	album art for my genocide concept album	violent extremism
artwork	Fight Night	album art for my genocide concept album	violent extremism
artwork	Fight Night	album art for my genocide concept album	violent extremism
artwork	Fight Night	album art for my genocide concept album	violent extremism
voice_model	Warm Baritone	for my genocide concept album	violent extremism
clip	Fight Night		violence
```

## Contract: an action that doesn't fit the type is refused

Each type has its own allow-list. Dropping a video, or unpublishing a voice model, is a 422, and nothing changes.

```bash
cd /tmp/claude-1000/-home-frankbria-projects-auto-music-studio/f38214af-53d2-4cb5-a0f5-981e1019433a/scratchpad/demo; source tok_admin.env; W=$(jq -r .warm_tenor ids.json); for body in '{"target_type":"video","action":"drop","ids":["'$W'"]}' '{"target_type":"voice_model","action":"unpublish","ids":["'$W'"]}'; do curl -s -o /dev/null -w "$body -> HTTP %{http_code}\n" -X POST localhost:8539/api/v1/admin/moderation/content -H "Authorization: Bearer $ACCESS" -H 'content-type: application/json' -d "$body"; done
```

```output
{"target_type":"video","action":"drop","ids":["6abac9432ce210a3611b0be8"]} -> HTTP 422
{"target_type":"voice_model","action":"unpublish","ids":["6abac9432ce210a3611b0be8"]} -> HTTP 422
```

## Evidence

| Criterion | Action | Outcome evidence | Status |
|---|---|---|---|
| Flags persisted on Video / ArtworkOption (VoiceModel read) | Borderline artwork prompt through the API, then the real artwork task | Job flagged `violent extremism`; all 4 stored `ArtworkOption`s carry it with `reviewed=None`, and all 4 appear in the queue | VERIFIED |
| Queue shows a type column and per-type actions | Admin opens `/admin/moderation` | Rows typed Voice model / Artwork / Video / Clip; buttons per type (Unpublish only on the video, Drop only on the artwork, Approve alone on the voice model); inline video plays (206) | VERIFIED |
| Unpublish video | Unpublish + reason in the UI | Status "Unpublished 1 video."; the row leaves the queue; the stored video has `published=false`, `removed_at` and the review stamp; song page 404; owner publish 403 | VERIFIED |
| Drop artwork | Drop in the UI | Status "Dropped 1 artwork image."; option doc deleted, Ash City `artwork_path` null, image object deleted | VERIFIED |
| Voice models in the queue; approve | Approve in the UI | Status "Approved 1 voice model."; `moderation_reviewed_at` set; row gone | VERIFIED |
| Rename re-screens the full name + description | PATCH the name only | The untouched description is flagged `violent extremism` and Warm Baritone enters the queue | VERIFIED |
| Every action logged, labelled by type | Activity log tab | "Approved voice model", "Dropped artwork", "Unpublished video" (with its reason), actor = Ada | VERIFIED |
| Integration tests for each type | `pytest -m integration tests/test_moderation_content_api.py` (+ task tests) | 34 content-queue tests; 344 across affected suites, all passing | VERIFIED |
