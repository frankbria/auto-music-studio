# #559 Expanded English default screening rules

*2026-10-31T22:52:50Z by Showboat 0.6.1*
<!-- showboat-id: 76214a40-8e30-4e5e-99dc-2d4ceae958b5 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_559` database with no saved screening rules, so the defaults are live), with `scripts/demo_stub_acestep.py` as the compute target. The seeded Pro user is promoted to admin so it can read the rules. `api` prints the status and body. `M` queries the demo database.

## 1. A fresh deployment serves the expanded list

```bash
. $DEMO/env.sh >/dev/null; api GET /admin/screening-rules >/dev/null; jq -c '{rules: (.rules|length), by_action: (.rules|group_by(.action)|map({(.[0].action): length})|add), allow_terms, fold_leetspeak, block_threshold}' $DEMO_DIR/last_body.json
```

```output
{"rules":88,"by_action":{"block":23,"flag":65},"allow_terms":["rape awareness","rape crisis","suicide squad","suicide prevention","suicide hotline","suicide helpline","suicide lifeline","suicide doors","suicide blonde","spic and span","cut myself some slack","cutting myself some slack"],"fold_leetspeak":false,"block_threshold":3}
```

## 2. A new block term is refused before any credit is charged

```bash
. $DEMO/env.sh >/dev/null; api GET /credits/balance | tail -1; api POST /generate '{"prompt": "kiddie porn"}'; api GET /credits/balance | tail -1; echo "jobs: $(M 'db.jobs.countDocuments()')"
```

```output
{"balance":46.0,"tier":"pro","upgrade_url":"/settings/billing"}
HTTP 422
{"detail":"This request wasn't generated because parts of it look like child sexual abuse content, which our content policy doesn't allow. If we misread your intent, try rephrasing the prompt, style or lyrics."}
{"balance":46.0,"tier":"pro","upgrade_url":"/settings/billing"}
jobs: 0
```

## 3. A new flag term generates, with the flag carried on the job

```bash
. $DEMO/env.sh >/dev/null; api POST /generate '{"prompt": "a protest song naming the rapists and school shooters"}'; M "db.jobs.find({}, {_id: 0, 'input_params.prompt': 1, 'input_params.moderation_flags': 1}).toArray()"
```

```output
HTTP 202
{"job_id":"6ae67143e5c4a50d19211b04","status":"queued","estimated_time_seconds":60}
[
  {
    input_params: {
      prompt: 'a protest song naming the rapists and school shooters',
      moderation_flags: [ 'sexual violence', 'graphic violence' ]
    }
  }
]
```

## 4. Ordinary lyrics with the allow-terms and near-misses generate unflagged

```bash
. $DEMO/env.sh >/dev/null; api POST /generate '{"prompt": "suicide squad remix", "lyrics": "my therapist said cut myself some slack, call the suicide lifeline, rape crisis benefit, kill the lights"}'; M "db.jobs.find({'input_params.prompt': 'suicide squad remix'}, {_id: 0, 'input_params.prompt': 1, 'input_params.moderation_flags': 1}).toArray()"
```

```output
HTTP 202
{"job_id":"6ae67143e5c4a50d19211b06","status":"queued","estimated_time_seconds":60}
[ { input_params: { prompt: 'suicide squad remix' } } ]
```

## 5. A deployment with saved rules keeps them

An admin saves a one-rule list. The new defaults no longer apply, so `lolicon`, a term only the new defaults have, now generates.

```bash
. $DEMO/env.sh >/dev/null; api PUT /admin/screening-rules '{"rules": [{"term": "child porn", "category": "child sexual abuse", "action": "block"}], "block_threshold": 3}' >/dev/null; api POST /generate '{"prompt": "lolicon"}'; api GET /admin/screening-rules >/dev/null; jq -c '{saved_rules: (.rules|length)}' $DEMO_DIR/last_body.json
```

```output
HTTP 202
{"job_id":"6ae67143e5c4a50d19211b09","status":"queued","estimated_time_seconds":60}
{"saved_rules":1}
```
