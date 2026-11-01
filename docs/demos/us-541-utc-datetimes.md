# #541 Every API datetime carries its UTC offset

*2026-11-01T05:48:29Z by Showboat 0.6.1*
<!-- showboat-id: a77b0405-93ae-4537-b889-a69d1384be9d -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_541` database). Before #541, Mongo's round trip dropped tzinfo, so responses said `2026-09-21T23:32:56.360000` and a browser read that as local time. Now every timestamp ends in an offset.

```bash
. $DEMO/env.sh >/dev/null; api GET /clips/$CLIP_1 >/dev/null; jq -c '{created_at}' $DEMO_DIR/last_body.json; api GET /users/me >/dev/null; jq -c '{created_at, updated_at}' $DEMO_DIR/last_body.json; api GET /credits/usage >/dev/null; jq -c '[.. | strings | select(test("^20[0-9]{2}-[0-9]{2}-[0-9]{2}T"))] | .[:3]' $DEMO_DIR/last_body.json
```

```output
{"created_at":"2026-11-01T05:48:29.274000Z"}
{"created_at":"2026-11-01T05:48:29.270000Z","updated_at":null}
["2026-12-01T05:48:29.270000Z"]
```

A JavaScript client now parses them as UTC with plain `new Date`, which is why the web's `parseApiTime` workaround is deleted:

```bash
. $DEMO/env.sh >/dev/null; api GET /clips/$CLIP_1 >/dev/null; node -e "const t=require('$DEMO_DIR/last_body.json').created_at; process.env.TZ='America/New_York'; console.log(t, '->', new Date(t).toISOString())"
```

```output
2026-11-01T05:48:29.274000Z -> 2026-11-01T05:48:29.274Z
```
