# Issue #532 — screening folds homoglyphs, invisible chars, optional leetspeak

*2026-09-27T21:40:26Z by Showboat 0.6.1*
<!-- showboat-id: 9b9992d9-9dbb-4ccd-b75d-a71380bbcb0e -->

Live FastAPI app (uvicorn on :8766) against a real local MongoDB (db `acemusic_demo_532`), job processor off so accepted requests stay inspectable as queued jobs. Local compute reads as available via a static `/v1/stats` stub. Helper scripts in the scratch dir: `api METHOD PATH ROLE [JSON|@file]` is a curl wrapper printing HTTP status + body; `balance ROLE` reads credits and job count straight from Mongo. Musician and admin users both start at 50 credits.

## Criterion 1 — homoglyph and invisible-char evasion is blocked

A Cyrillic "е" (U+0435) standing in for Latin "e" inside "heil" used to slip past the old plain-string match. `match()` now folds it back before matching, and the request is blocked before any credit is charged.

```bash
$DEMO/api POST /generate musician "@$DEMO/homoglyph.json"; $DEMO/balance musician
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 50; jobs = 0
```

Same result for a zero-width space (U+200B) spliced into the middle of "sieg" — invisible format characters are dropped rather than treated as word separators, so they cannot split a blocked phrase in two.

```bash
$DEMO/api POST /generate musician "@$DEMO/zerowidth.json"; $DEMO/balance musician
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 50; jobs = 0
```

## Criterion 2 — no false positive on ordinary content

Real Russian lyrics use genuine Cyrillic letters (not Latin look-alikes), and an English prompt with digits and a dollar sign is everyday text, not leetspeak. Neither should trip the folding.

```bash
$DEMO/api POST /generate musician "@$DEMO/russian.json"; $DEMO/balance musician
```

```output
HTTP 202
{"job_id":"6ab98d61aaa4d0f5193476bf","status":"queued","estimated_time_seconds":60}
musician credits_balance = 49; jobs = 1
```

Accepted (202), charged one credit, and the stored job has no `moderation_flags` key at all — confirming the request cleared screening cleanly rather than merely landing under the flag threshold.

```bash
mongosh --quiet acemusic_demo_532 --eval "printjson(db.jobs.find({},{_id:0,status:1,\"input_params.prompt\":1,\"input_params.moderation_flags\":1}).sort({created_at:-1}).limit(1).toArray())"
```

```output
[
  {
    status: 'queued',
    input_params: {
      prompt: 'Top 40 hits of 1999, $5 in the tank'
    }
  }
]
```

## Criterion 3 — leetspeak folding is off by default

`ScreeningRules.fold_leetspeak` defaults to `False` (a deliberate trade against false positives). The admin rules endpoint confirms it, and a leetspeak-obfuscated prompt passes through untouched.

```bash
$DEMO/api GET /admin/screening-rules admin
```

```output
HTTP 200
{"rules":[{"term":"child porn","category":"child sexual abuse","action":"block"},{"term":"child pornography","category":"child sexual abuse","action":"block"},{"term":"sieg heil","category":"hate speech","action":"block"},{"term":"heil hitler","category":"hate speech","action":"block"},{"term":"white power","category":"hate speech","action":"block"},{"term":"gas the jews","category":"hate speech","action":"block"},{"term":"suicide","category":"self-harm","action":"flag"},{"term":"self harm","category":"self-harm","action":"flag"},{"term":"rape","category":"sexual violence","action":"flag"},{"term":"terrorist","category":"violent extremism","action":"flag"},{"term":"genocide","category":"violent extremism","action":"flag"},{"term":"mass shooting","category":"graphic violence","action":"flag"}],"allow_terms":[],"block_threshold":3,"fold_leetspeak":false}
```

```bash
$DEMO/api POST /generate musician '{"prompt":"a chant of s13g h31l"}'; $DEMO/balance musician
```

```output
HTTP 202
{"job_id":"6ab98d70aaa4d0f5193476c1","status":"queued","estimated_time_seconds":60}
musician credits_balance = 48; jobs = 2
```

## Criterion 4 — admin turns leetspeak folding on at runtime

No deploy, no restart: the admin reads the live rules, flips the one flag, and PUTs the full document back.

```bash
$DEMO/api GET /admin/screening-rules admin > /dev/null; jq '.fold_leetspeak = true' $DEMO/body.json > $DEMO/rules_leet_on.json; $DEMO/api PUT /admin/screening-rules admin "@$DEMO/rules_leet_on.json"
```

```output
HTTP 200
{"rules":[{"term":"child porn","category":"child sexual abuse","action":"block"},{"term":"child pornography","category":"child sexual abuse","action":"block"},{"term":"sieg heil","category":"hate speech","action":"block"},{"term":"heil hitler","category":"hate speech","action":"block"},{"term":"white power","category":"hate speech","action":"block"},{"term":"gas the jews","category":"hate speech","action":"block"},{"term":"suicide","category":"self-harm","action":"flag"},{"term":"self harm","category":"self-harm","action":"flag"},{"term":"rape","category":"sexual violence","action":"flag"},{"term":"terrorist","category":"violent extremism","action":"flag"},{"term":"genocide","category":"violent extremism","action":"flag"},{"term":"mass shooting","category":"graphic violence","action":"flag"}],"allow_terms":[],"block_threshold":3,"fold_leetspeak":true}
```

```bash
$DEMO/api GET /admin/screening-rules admin
```

```output
HTTP 200
{"rules":[{"term":"child porn","category":"child sexual abuse","action":"block"},{"term":"child pornography","category":"child sexual abuse","action":"block"},{"term":"sieg heil","category":"hate speech","action":"block"},{"term":"heil hitler","category":"hate speech","action":"block"},{"term":"white power","category":"hate speech","action":"block"},{"term":"gas the jews","category":"hate speech","action":"block"},{"term":"suicide","category":"self-harm","action":"flag"},{"term":"self harm","category":"self-harm","action":"flag"},{"term":"rape","category":"sexual violence","action":"flag"},{"term":"terrorist","category":"violent extremism","action":"flag"},{"term":"genocide","category":"violent extremism","action":"flag"},{"term":"mass shooting","category":"graphic violence","action":"flag"}],"allow_terms":[],"block_threshold":3,"fold_leetspeak":true}
```

The same leetspeak prompt that generated a moment ago is now blocked — with no restart in between — and no credit is spent on the refusal.

```bash
$DEMO/api POST /generate musician '{"prompt":"a chant of s13g h31l"}'; $DEMO/balance musician
```

```output
HTTP 422
{"detail":"This request wasn't generated because parts of it look like hate speech content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
musician credits_balance = 48; jobs = 2
```

The moderation log recorded the rule change with a before/after diff.

```bash
mongosh --quiet acemusic_demo_532 --eval "printjson(db.moderation_log.find({action:\"update_screening_rules\"},{_id:0,action:1,\"details.before.fold_leetspeak\":1,\"details.after.fold_leetspeak\":1}).sort({created_at:-1}).limit(1).toArray())"
```

```output
[
  {
    action: 'update_screening_rules',
    details: {
      before: {
        fold_leetspeak: false
      },
      after: {
        fold_leetspeak: true
      }
    }
  }
]
```

## Criterion 5 — a legacy rules document (no `fold_leetspeak` key) still loads

Replace the "global" rules document directly in Mongo with the shape the OLD code wrote — no `fold_leetspeak` field at all — the way a document written before this change would actually look.

```bash
mongosh --quiet acemusic_demo_532 --eval "db.screening_rules.replaceOne({key:\"global\"},{key:\"global\",rules:[{term:\"sieg heil\",category:\"hate speech\",action:\"block\"}],allow_terms:[],block_threshold:3}); printjson(db.screening_rules.findOne({key:\"global\"}))"
```

```output
{
  _id: ObjectId('6ab98d76f4a1ffdba3d99d44'),
  key: 'global',
  rules: [
    {
      term: 'sieg heil',
      category: 'hate speech',
      action: 'block'
    }
  ],
  allow_terms: [],
  block_threshold: 3
}
```

The admin GET reads that document straight through `ScreeningRules.model_validate` — the missing key defaults to `False` rather than raising or crashing.

```bash
$DEMO/api GET /admin/screening-rules admin
```

```output
HTTP 200
{"rules":[{"term":"sieg heil","category":"hate speech","action":"block"}],"allow_terms":[],"block_threshold":3,"fold_leetspeak":false}
```

All five criteria verified against the live API and a real local MongoDB. Server stopped and the `acemusic_demo_532` database dropped after this run.

## Note

Recorded at commit 70d9747. The later commits change only how invisible characters and leet symbols are matched: they now stay in the text, and a rule may find them inside a word or between two. That covers `sieg<ZWSP>heil`, `sieg$heil`, mixed cases like `si<ZWSP>eg<ZWSP>heil`, and an `n@zi` allow-term. All of it is tested in `TestMatch` in `tests/test_screening_api.py`.
