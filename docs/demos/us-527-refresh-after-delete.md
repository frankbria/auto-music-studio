# #527 A refresh that fails after rotation leaves no live token

*2026-11-01T01:43:10Z by Showboat 0.6.1*
<!-- showboat-id: 0248f9f8-5986-4b17-871b-08222c159527 -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_527` database). A second account gets a live refresh token, then the account is deleted, the case where a delete lands while a refresh is in flight. Before #527 the refresh rotated the token to a hash nobody received and then answered 401, leaving a live credential that nobody held.

```bash
. $DEMO/env.sh >/dev/null; read RAW OWNER < <(uv run python $DEMO/seed_refresh.py acemusic_demo_527 2>/dev/null); echo "$RAW" > $DEMO_DIR/raw; echo "$OWNER" > $DEMO_DIR/owner; echo "live tokens: $(M "db.refresh_tokens.countDocuments({user_id: ObjectId('$OWNER'), revoked: false})")"
```

```output
live tokens: 1
```

The account is deleted, then its refresh token is used:

```bash
. $DEMO/env.sh >/dev/null; OWNER=$(cat $DEMO_DIR/owner); echo "deleted: $(M "db.users.deleteOne({_id: ObjectId('$OWNER')}).deletedCount")"; curl -s -w '\nHTTP %{http_code}\n' -X POST $DEMO_API/auth/refresh -H 'Content-Type: application/json' -d "{\"refresh_token\": \"$(cat $DEMO_DIR/raw)\"}"
```

```output
deleted: 1
{"detail":"Invalid or expired refresh token."}
HTTP 401
```

No live refresh token is left for that account. The one row was rotated, then revoked:

```bash
. $DEMO/env.sh >/dev/null; OWNER=$(cat $DEMO_DIR/owner); echo "live tokens: $(M "db.refresh_tokens.countDocuments({user_id: ObjectId('$OWNER'), revoked: false})")"; M "db.refresh_tokens.find({user_id: ObjectId('$OWNER')}, {_id: 0, revoked: 1, rotated: {\$gt: ['\$rotated_at', null]}}).toArray()"
```

```output
live tokens: 0
[ { revoked: true, rotated: true } ]
```
