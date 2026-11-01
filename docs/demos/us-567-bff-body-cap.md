# #567 The web BFF refuses oversized request bodies

*2026-11-01T02:20:12Z by Showboat 0.6.1*
<!-- showboat-id: 15b7233c-7535-4b7b-87d9-6456d0a55900 -->

Live run: `next dev` on :3014 with its BFF pointed (`API_BASE_URL`) at `scripts/demo_api_stack.py` (throwaway `acemusic_demo_567` database). Requests go through the same-origin BFF routes, as the browser's do, with the seeded musician's token.

## 1. A normal body is relayed to the API

```bash
. $DEMO/env.sh >/dev/null; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X PATCH http://localhost:3014/api/users/me -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"bio": "Synthwave at 2am"}'; curl -s http://localhost:3014/api/users/me -H "authorization: Bearer $TOKEN" | jq -c '{bio}'
```

```output
HTTP 200
{"bio":"Synthwave at 2am"}
```

## 2. A 2 MiB JSON body is refused with 413 at the BFF

If it had reached the API, the API would have read all 2 MiB and then rejected the bio's length with a 422. The 413 comes from the BFF, and the stored bio is unchanged.

```bash
. $DEMO/env.sh >/dev/null; python3 -c 'import json; print(json.dumps({"bio": "x" * 2097152}))' > $DEMO_DIR/big.json; curl -s -w '\nHTTP %{http_code}\n' -X PATCH http://localhost:3014/api/users/me -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' --data-binary @$DEMO_DIR/big.json; curl -s http://localhost:3014/api/users/me -H "authorization: Bearer $TOKEN" | jq -c '{bio}'
```

```output
{"detail":"Request body is too large."}
HTTP 413
{"bio":"Synthwave at 2am"}
```

## 3. The same for a chunked body with no Content-Length, which only the byte count catches

```bash
. $DEMO/env.sh >/dev/null; curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:3014/api/generate -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -H 'Transfer-Encoding: chunked' --data-binary @$DEMO_DIR/big.json
```

```output
{"detail":"Request body is too large."}
HTTP 413
```
