# Issue #525 — Refresh-token reuse detection

*2026-09-21T16:08:12Z*

A refresh token is single-use. Rotating it **in place** (#515) keeps one MongoDB document per token lineage, so a DAW plugin credential holds one id across refreshes — but it also erased the hash the rotation spent, leaving a replayed token indistinguishable from a random string. This demo drives the real API (uvicorn on :8010, real MongoDB) and reads the database back after each step.

Every criterion below is checked against what the database and the server log actually say, not against the HTTP status alone: on the wire a replay and a typo are both a 401, and that is deliberate.

## Setup — one musician, one browser session

The session is seeded through the service layer the OAuth callback uses, then every step after this one goes over HTTP.

```bash
DEMO_MONGO_URL=mongodb://localhost:27017 DEMO_DB=acemusic_demo_525 uv run python $DEMO_TMP/demo_setup.py | tee $DEMO_TMP/seed.txt
```

```output
user_id=6ab1567693fafcff6552740e
lineage_id=6ab1567693fafcff6552740f
refresh_token=nJZJLxhrXSxlnykJ3c3bU0fU0ZgfCFhbqo_ilWbeY3KcrQxnFxlwSFl2SsfdPvKR
```

## The session refreshes twice

A browser refreshes whenever its access token expires, so by the time a stolen token is used the lineage has usually moved on more than one hop. `t0` is the token that was issued at sign-in; `t1` and `t2` are what the two refreshes hand back.

```bash
source $DEMO_TMP/tok.sh
echo "refresh #1 -> HTTP $(refresh "$T0")"
T1=$(jq -r .refresh_token $J/resp.json)
echo "refresh #2 -> HTTP $(refresh "$T1")"
T2=$(jq -r .refresh_token $J/resp.json)
echo "$T1" > $J/t1.txt; echo "$T2" > $J/t2.txt
echo
echo "t0, t1 and t2 are three different tokens:"
printf "  t0 %s...\n  t1 %s...\n  t2 %s...\n" "${T0:0:12}" "${T1:0:12}" "${T2:0:12}"
```

```output
refresh #1 -> HTTP 200
refresh #2 -> HTTP 200

t0, t1 and t2 are three different tokens:
  t0 nJZJLxhrXSxl...
  t1 p_E91ke-dit5...
  t2 xRA2O8o6avOA...
```

## AC3 — two refreshes later, it is still one document

The `_id` below is the one printed at sign-in. That is what #515 needs: a plugin credential the musician can see in Settings and revoke, under an id that does not change every time the plugin refreshes. Alongside it, the spent hashes of t0 and t1 — the substrate this issue is about.

```bash
source $DEMO_TMP/tok.sh
echo "lineage id printed at sign-in: $LINEAGE"
mongosh --quiet acemusic_demo_525 --eval "
  const docs = db.refresh_tokens.find({}, {token_hash:1, previous_token_hashes:1, revoked:1, rotated_at:1}).toArray();
  print(\"documents in the collection: \" + docs.length);
  docs.forEach(d => {
    print(\"  _id                   \" + d._id);
    print(\"  token_hash            \" + d.token_hash.slice(0,16) + \"...  (this is t2)\");
    print(\"  previous_token_hashes \" + d.previous_token_hashes.length + \" spent: \" + d.previous_token_hashes.map(h => h.slice(0,16)+\"...\").join(\", \"));
    print(\"  revoked               \" + d.revoked);
  });
"
```

```output
lineage id printed at sign-in: 6ab1567693fafcff6552740f
documents in the collection: 1
  _id                   6ab1567693fafcff6552740f
  token_hash            bb32fe311d0ada52...  (this is t2)
  previous_token_hashes 2 spent: eaf5f3d83bb217e5..., 0b586e6ff8323f37...
  revoked               false
```

## AC1 — a replay and a typo are the same 401 on the wire, and nothing alike in the server

The thief has been holding `t0` since sign-in. Ageing `rotated_at` past the three-second leeway is what separates a theft from the client's own racing retry (AC4 below) — here it stands in for the minutes or hours a real attacker waits.

```bash
source $DEMO_TMP/tok.sh
mongosh --quiet acemusic_demo_525 --eval "db.refresh_tokens.updateOne({}, {\$set: {rotated_at: new Date(Date.now() - 60000)}})" > /dev/null
LOGMARK=$(wc -l < $J/api.log)
echo "unknown token  -> HTTP $(refresh "never-issued-by-anyone")   body: $(cat $J/resp.json)"
echo "replay of t0   -> HTTP $(refresh "$T0")   body: $(cat $J/resp.json)"
echo
echo "what the server made of each, from its own log:"
tail -n +$((LOGMARK+1)) $J/api.log | grep -E "WARNING|reuse" || echo "  (no warning)"
```

```output
unknown token  -> HTTP 401   body: {"detail":"Invalid or expired refresh token."}
replay of t0   -> HTTP 401   body: {"detail":"Invalid or expired refresh token."}

what the server made of each, from its own log:
WARNING:     acemusic.api.auth.services - Refresh-token reuse detected for user 6ab1567693fafcff6552740e; revoked token lineage 6ab1567693fafcff6552740f
```

Note which token was replayed: **t0**, two rotations back. Remembering only the last spent hash would have let this one through as garbage — the ordinary case, since a browser refreshes on every access-token expiry.

## AC2 — the replay kills the credential the real client is still holding

`t2` was valid a moment ago and nobody used it. It dies because the replay says someone else has a copy of this lineage.

```bash
source $DEMO_TMP/tok.sh
T2=$(cat $J/t2.txt)
echo "the client refreshes with its live t2 -> HTTP $(refresh "$T2")   body: $(cat $J/resp.json)"
echo
mongosh --quiet acemusic_demo_525 --eval "
  const d = db.refresh_tokens.findOne({});
  print(\"lineage \" + d._id + \"  revoked: \" + d.revoked);
  print(\"documents still live for this user: \" + db.refresh_tokens.countDocuments({revoked: false}));
"
```

```output
the client refreshes with its live t2 -> HTTP 401   body: {"detail":"Invalid or expired refresh token."}

lineage 6ab1567693fafcff6552740f  revoked: true
documents still live for this user: 0
```

## AC4 — a client racing itself is not a thief

Two refreshes fired at once present exactly what an attacker presents: the same spent token. Only elapsed time tells them apart, so a spend inside the three-second leeway is refused without the lineage being killed — otherwise every double-click would sign the musician out. A fresh session, five concurrent refreshes:

```bash
J=$DEMO_TMP
DEMO_MONGO_URL=mongodb://localhost:27017 DEMO_DB=acemusic_demo_525 uv run python $J/demo_setup.py > $J/seed2.txt
RACER=$(grep refresh_token $J/seed2.txt | cut -d= -f2)
RACE_LINEAGE=$(grep lineage_id $J/seed2.txt | cut -d= -f2)
uv run python $J/demo_race.py "$RACER"
mongosh --quiet acemusic_demo_525 --eval "
  const d = db.refresh_tokens.findOne({_id: ObjectId(\"$RACE_LINEAGE\")});
  print(\"lineage revoked by the four losers? \" + d.revoked);
"
```

```output
five simultaneous refreshes of the same token -> [401, 200, 401, 401, 401]
tokens handed back: 1
the winner still refreshes afterwards -> HTTP 200
lineage revoked by the four losers? false
```

## Blast radius — a replayed browser session does not unplug the DAW

The kill is the lineage, which under in-place rotation is the whole token family. A musician whose browser session is replayed keeps the plugin credential they pasted into their DAW; it was never part of the theft.

```bash
J=$DEMO_TMP
source $J/tok.sh
# One musician, two lineages: the browser session and a DAW plugin token.
DEMO_MONGO_URL=mongodb://localhost:27017 DEMO_DB=acemusic_demo_525 uv run python $J/demo_setup.py > $J/seed3.txt
WEB=$(grep refresh_token $J/seed3.txt | cut -d= -f2)
USER=$(grep user_id $J/seed3.txt | cut -d= -f2)
PLUGIN=$(uv run python - "$USER" <<PY
import asyncio, sys
sys.path.insert(0, "src")
from datetime import datetime, timedelta, timezone
from beanie import init_beanie, PydanticObjectId
from pymongo import AsyncMongoClient
from acemusic.api.database import ALL_MODELS
from acemusic.api.auth.services import store_refresh_token
from acemusic.api.auth.tokens import create_refresh_token
async def main():
    c = AsyncMongoClient("mongodb://localhost:27017")
    await init_beanie(database=c["acemusic_demo_525"], document_models=ALL_MODELS)
    raw = create_refresh_token()
    await store_refresh_token(PydanticObjectId(sys.argv[1]), raw, datetime.now(timezone.utc)+timedelta(days=7), kind="plugin")
    print(raw)
asyncio.run(main())
PY
)
# The browser session refreshes once, then the stolen original is replayed after the leeway.
refresh "$WEB" > /dev/null
mongosh --quiet acemusic_demo_525 --eval "db.refresh_tokens.updateMany({kind:\"web\"}, {\$set:{rotated_at: new Date(Date.now()-60000)}})" > /dev/null
echo "replay of the stolen browser token -> HTTP $(refresh "$WEB")"
echo "the DAW plugin refreshes           -> HTTP $(refresh "$PLUGIN")"
```

```output
replay of the stolen browser token -> HTTP 401
the DAW plugin refreshes           -> HTTP 200
```

## Evidence

| Criterion | Action | Outcome evidence | Status |
|---|---|---|---|
| AC1 — a replay is distinguishable from an unknown token, server-side | `POST /auth/refresh` with an unknown string, then with the spent `t0` | Identical 401 and body on the wire; the server logged `Refresh-token reuse detected for user … revoked token lineage …` for the replay and nothing for the unknown token | VERIFIED |
| AC2 — a detected replay kills the live credential in that lineage | Refresh with `t2`, which nobody had used, after the replay | HTTP 401, and the lineage document reads `revoked: true` with 0 live documents left for the user | VERIFIED |
| AC3 — rotation still keeps one document per lineage | Two refreshes, then read the collection | 1 document, `_id` identical to the one printed at sign-in, carrying 2 spent hashes | VERIFIED |
| AC4 — normal rotation is unaffected under concurrency | Five simultaneous `POST /auth/refresh` of one token | One 200 and four 401s, one token handed back, the winner still refreshes afterwards, and the lineage is `revoked: false` — the losers did not kill it | VERIFIED |
| Blast radius (design note, not an AC) | Replay a stolen browser token for a user who also has a DAW plugin token | Browser replay 401; the plugin's own refresh still returns 200 | VERIFIED |

Re-run this document with `showboat verify docs/demos/issue-525-reuse-detection.md` against a local API on :8010 and MongoDB on :27017. Token values and ids differ per run; the outcomes do not.
