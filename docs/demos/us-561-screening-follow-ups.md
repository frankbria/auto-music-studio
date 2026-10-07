# #561 Screening follow-ups: confusables, short leet terms, invisible rule terms, rules PATCH

*2026-10-07T15:28:40Z by Showboat 0.6.1*
<!-- showboat-id: 25bc39ed-2b7b-4965-bfca-f81957f16604 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_561` database, a seeded Pro user promoted to admin). `api` prints the HTTP status and body; `M` queries the demo database. Every step drives the real API.

## 1. Confusables from more scripts are folded

Small capitals `ꜱɪ` plus an Armenian `հ` spell "sieg heil". A Greek lunate sigma `Ϲ` spells "child porn". Both are blocked before any credit is charged.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api POST /generate '{"prompt": "a chant of ꜱɪeg հeil"}'
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
```

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api POST /generate '{"prompt": "Ϲhild porn"}'
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like child sexual abuse content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
```

There is no ACE-Step server here, so allowed text is shown on clip title PATCH, which screens what it stores and records flags on the clip. The demo clears the flags before each step. An ordinary Armenian and Icelandic title is saved (200) with no flags. `þ` is an Icelandic letter, so it is deliberately not folded to `p`.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; M 'db.clips.updateOne({}, {$set: {moderation_flags: []}})' >/dev/null; api PATCH /clips/$CLIP_1 '{"title": "Իմ սիրելի մայր, Þú ert sólin mín"}' | head -1; M 'db.clips.findOne({}, {_id: 0, title: 1, moderation_flags: 1})'
```

```output
HTTP 200
{ title: 'Իմ սիրելի մայր, Þú ert sólin mín', moderation_flags: [] }
```

## 2. Rules PATCH changes only the fields sent

Before: the live rules have 12 rules and `block_threshold` 3. A PATCH that only turns leet folding on leaves both alone. A whole-document PUT used to reset them.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api GET /admin/screening-rules >/dev/null; jq -c "{rules: (.rules|length), block_threshold, fold_leetspeak}" "$DEMO_DIR/last_body.json"
```

```output
{"rules":12,"block_threshold":3,"fold_leetspeak":false}
```

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api PATCH /admin/screening-rules '{"fold_leetspeak": true}' | head -1; jq -c "{rules: (.rules|length), block_threshold, fold_leetspeak}" "$DEMO_DIR/last_body.json"
```

```output
HTTP 200
{"rules":12,"block_threshold":3,"fold_leetspeak":true}
```

The change is in the moderation log like any rules save:

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; M 'const e = db.moderation_log.find({action: "update_screening_rules"}).sort({_id:-1}).limit(1).toArray()[0]; printjson({before: e.details.before.fold_leetspeak, after: e.details.after.fold_leetspeak})'
```

```output
{
  before: false,
  after: true
}
```

A misspelt field is refused, not silently ignored, and nothing changes:

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api PATCH /admin/screening-rules '{"fold_leetspeek": false}'; api GET /admin/screening-rules >/dev/null; jq -c "{fold_leetspeak}" "$DEMO_DIR/last_body.json"
```

```output
HTTP 422
{"detail":"Unknown screening-rules fields: fold_leetspeek."}
{"fold_leetspeak":true}
```

## 3. Under leet folding, a short term no longer matches a number

An admin adds the flag term `to` (PATCH with `rules` only, so leet folding stays on). `70` is a number, not `to`: no flag. `7o` still has a letter, so it is still flagged (`demo`).

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api GET /admin/screening-rules >/dev/null; RULES=$(jq -c ".rules + [{term: \"to\", category: \"demo\", action: \"flag\"}]" "$DEMO_DIR/last_body.json"); api PATCH /admin/screening-rules "{\"rules\": $RULES}" | head -1; jq -c "{rules: (.rules|length), fold_leetspeak}" "$DEMO_DIR/last_body.json"
```

```output
HTTP 200
{"rules":13,"fold_leetspeak":true}
```

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; M 'db.clips.updateOne({}, {$set: {moderation_flags: []}})' >/dev/null; api PATCH /clips/$CLIP_1 '{"title": "we drove 70 miles"}' | head -1; M 'db.clips.findOne({}, {_id: 0, title: 1, moderation_flags: 1})'
```

```output
HTTP 200
{ title: 'we drove 70 miles', moderation_flags: [] }
```

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; M 'db.clips.updateOne({}, {$set: {moderation_flags: []}})' >/dev/null; api PATCH /clips/$CLIP_1 '{"title": "down 7o the river"}' | head -1; M 'db.clips.findOne({}, {_id: 0, title: 1, moderation_flags: 1})'
```

```output
HTTP 200
{ title: 'down 7o the river', moderation_flags: [ 'demo' ] }
```

## 4. A rule term hiding an invisible character is refused

`sieg<U+200B>heil` would have compiled as the single word `siegheil` and never matched. PUT and PATCH both return 422 and name the term. The stored rules are untouched.

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api PUT /admin/screening-rules "$(printf '{"rules": [{"term": "sieg\\u200bheil", "category": "hate speech", "action": "block"}]}')"
```

```output
HTTP 422
{"detail":"The term 'sieg\\u200bheil' contains an invisible character, which would join the words around it."}
```

```bash
. /tmp/claude-1002/-home-frankbria-projects-auto-music-studio/117e6780-3b63-4f7b-a894-bb826c5db304/scratchpad/demo-561/env.sh >/dev/null; api PATCH /admin/screening-rules "$(printf '{"allow_terms": ["rape\\u2060awareness"]}')"; api GET /admin/screening-rules >/dev/null; jq -c "{rules: (.rules|length), allow_terms}" "$DEMO_DIR/last_body.json"
```

```output
HTTP 422
{"detail":"The term 'rape\\u2060awareness' contains an invisible character, which would join the words around it."}
{"rules":13,"allow_terms":[]}
```
