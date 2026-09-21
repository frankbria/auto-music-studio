# US-27.1 — Automated content screening (#334)

*2026-09-21T17:06:36Z*

Helper scripts live in `$DEMO` (a scratch dir). Live API (uvicorn on :8765) against a real local MongoDB (db `acemusic_demo_334`), job processor off so queued jobs stay inspectable. Local compute is "available" via a static `/v1/stats` file. `api METHOD PATH ROLE [JSON]` is a curl wrapper that prints the HTTP status and body; `balance USER` reads the user's credits and job count straight from Mongo. Both users start at 50 credits.

## AC1 + AC4 — clearly prohibited content is blocked with an explanation, and costs nothing

```bash
$DEMO/api POST /generate musician '{"prompt":"stadium rock anthem, crowd chanting sieg heil"}'; $DEMO/balance musician
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 50; jobs = 0
```

```bash
$DEMO/api POST /generate musician '{"prompt":"gentle folk","lyrics":"[Verse]\nwe trade child-porn"}'; $DEMO/balance musician
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like child sexual abuse content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 50; jobs = 0
```

## AC2 — a normal creative prompt passes (dark-sounding words like *killer* are not on any list)

```bash
$DEMO/api POST /generate musician '{"prompt":"a killer synthwave groove for a midnight drive"}'; $DEMO/balance musician; mongosh --quiet acemusic_demo_334 --eval 'printjson(db.jobs.find({},{_id:0,status:1,"input_params.prompt":1,"input_params.moderation_flags":1}).sort({created_at:-1}).limit(1).toArray())'
```

```output
HTTP 202
{"job_id":"6ab1641dabc8f9e9ba1f6309","status":"queued","estimated_time_seconds":60}
musician credits_balance = 49; jobs = 1
[
  {
    status: 'queued',
    input_params: {
      prompt: 'a killer synthwave groove for a midnight drive'
    }
  }
]
```

## AC3 — borderline content is flagged but still generates; the flag lands on the clip

```bash
$DEMO/api POST /generate musician '{"prompt":"a quiet song about grief after a suicide"}'; $DEMO/balance musician; mongosh --quiet acemusic_demo_334 --eval 'printjson(db.jobs.find({},{_id:0,status:1,"input_params.moderation_flags":1}).sort({created_at:-1}).limit(1).toArray())'
```

```output
HTTP 202
{"job_id":"6ab1641eabc8f9e9ba1f630b","status":"queued","estimated_time_seconds":60}
musician credits_balance = 48; jobs = 2
[
  {
    status: 'queued',
    input_params: {
      moderation_flags: [
        'self-harm'
      ]
    }
  }
]
```

The worker turns that job into a clip through `JobProcessor._build_clip` (the real completion path, minus the ACE-Step download). Build the clip from the stored job and insert it:

```bash
cd /home/frankbria/projects/auto-music-studio && . $DEMO/demo_env.sh && uv run python -c '
import asyncio
from beanie import PydanticObjectId
from acemusic.api import database
from acemusic.api.models import Job, Clip
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.processor import JobProcessor
async def main():
    await database.init_db(ApiSettings())
    job = await Job.find_all().sort(-Job.created_at).first_or_none()
    clip = JobProcessor._build_clip(job, job.input_params, PydanticObjectId(), "demo.wav", "wav")
    await clip.insert()
    stored = await Clip.get(clip.id)
    print("clip", stored.id, "moderation_flags =", stored.moderation_flags)
asyncio.run(main())
'
```

```output
clip 6ab1641fc09590498c18bb4b moderation_flags = ['self-harm']
```

## AC5 — an admin changes the rules at runtime, no deploy or restart

```bash
$DEMO/api GET /admin/screening-rules musician
```

```output
HTTP 403
{"detail":"Admin access required."}
```

```bash
$DEMO/api POST /generate musician '{"prompt":"a lullaby about a bonfire"}'
```

```output
HTTP 202
{"job_id":"6ab16427abc8f9e9ba1f630d","status":"queued","estimated_time_seconds":60}
```

```bash
$DEMO/api GET /admin/screening-rules admin | head -1; jq '.rules += [{"term":"bonfire","category":"demo test category","action":"block"}] | .allow_terms += ["suicide squad"]' $DEMO/body.json > $DEMO/new_rules.json; $DEMO/api PUT /admin/screening-rules admin "$(cat $DEMO/new_rules.json)" | head -1
```

```output
HTTP 200
HTTP 200
```

```bash
$DEMO/api POST /generate musician '{"prompt":"a lullaby about a bonfire"}'
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like demo test category content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
```

```bash
$DEMO/api POST /generate musician '{"prompt":"a suicide squad style heist theme"}'; mongosh --quiet acemusic_demo_334 --eval 'printjson(db.jobs.find({},{_id:0,"input_params.prompt":1,"input_params.moderation_flags":1}).sort({created_at:-1}).limit(1).toArray())'
```

```output
HTTP 202
{"job_id":"6ab16427abc8f9e9ba1f630f","status":"queued","estimated_time_seconds":60}
[
  {
    input_params: {
      prompt: 'a suicide squad style heist theme'
    }
  }
]
```

The API process was never restarted between the two identical bonfire requests; the allow-list entry likewise stopped *suicide squad* from being flagged.

```bash
$DEMO/balance musician
```

```output
musician credits_balance = 46; jobs = 4
```

## AC1 across entry points — iterative modes also screen the source clip (fixed after post-PR review)
`extend` carries no text of its own; the worker prompts ACE-Step with the clip's title/tags, which the owner can edit. (Fresh demo DB for this section; the musician again starts at 50 credits.)

```bash
$DEMO/api POST /clips/6ab167ed36972cd59e9559c6/extend musician '{"duration":"10s"}'; $DEMO/balance musician
```

```output
HTTP 202
{"job_id":"6ab167ff5527d23373ccbb19","status":"queued","estimated_time_seconds":45}
musician credits_balance = 49; jobs = 1
```

```bash
$DEMO/api PATCH /clips/6ab167ed36972cd59e9559c6 musician '{"title":"Sieg-Heil march"}' | head -1; $DEMO/api POST /clips/6ab167ed36972cd59e9559c6/extend musician '{"duration":"10s"}'; $DEMO/balance musician
```

```output
HTTP 200
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 48; jobs = 2
```

Renaming the clip is allowed (renaming alone generates nothing), but the next generative operation that would prompt with that title is refused before the charge: balance and job count are unchanged. (They read 48/2 rather than 49/1 because a discarded attempt, a PATCH that sent a non-editable `style_tags` field and was rejected with 422, ran one more clean extend first.)
