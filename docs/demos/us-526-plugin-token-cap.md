# #526 Live plugin tokens are capped at 10 per account

*2026-11-01T02:06:39Z by Showboat 0.6.1*
<!-- showboat-id: 6e352701-d430-4c21-85d2-ebddd81a241e -->

Live run against `scripts/demo_api_stack.py` (throwaway `acemusic_demo_526` database), as the seeded musician.

## 1. Ten plugin tokens mint; the eleventh is refused with what to do

```bash
. $DEMO/env.sh >/dev/null; for i in $(seq 10); do api POST /auth/plugin-token | head -1; done | sort | uniq -c; api POST /auth/plugin-token; api GET /auth/plugin-tokens >/dev/null; echo "listed: $(jq length $DEMO_DIR/last_body.json)"
```

```output
     10 HTTP 200
HTTP 409
{"detail":"You already have 10 plugin tokens. Revoke one below to create another."}
listed: 10
```

## 2. Revoking one frees a slot

```bash
. $DEMO/env.sh >/dev/null; api GET /auth/plugin-tokens >/dev/null; OLDEST=$(jq -r '.[-1].id' $DEMO_DIR/last_body.json); api DELETE /auth/plugin-tokens/$OLDEST | head -1; api POST /auth/plugin-token | head -1
```

```output
HTTP 204
HTTP 200
```
