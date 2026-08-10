# #429 — Containerize the platform and ship it via CD

Everything below ran against a real Docker daemon on this machine: real images, a real
local registry, a real rollout, a real rollback.

The one thing that could **not** run is the SSH hop to a production VPS — no host, user or
key exists, and I cannot create them. So the rollout is demonstrated by running
`scripts/deploy.sh` exactly as the workflow runs it, against a registry the stack really
pulls from. What is unproven is the transport, not the logic. See *Not verified here* at
the end.

---

## Images and local stack

### `docker compose up` brings up API + web + MongoDB

```
$ docker compose up -d
 Container acemusic-mongo-1  Healthy
 Container acemusic-api-1    Started
 Container acemusic-web-1    Started

$ docker compose ps
api     Up (healthy)
mongo   Up (healthy)
web     Up (healthy)

$ curl localhost:8000/api/v1/health
{"status":"ok","version":"0.1.0","uptime_seconds":19.368,"build_sha":"local"}

api-1 | Connected to MongoDB database 'acemusic' at mongodb://mongo:27017
```

Port 3000 was already taken on this machine by a dev server — the shared-host conflict the
issue calls out. It was resolved with `WEB_PORT=3080 API_PORT=8080` in `.env`, no file
edit, which is the point of every setting being an environment variable.

### A generation completes against the containerised API

The ACE-Step inference server is deliberately **not** in this stack — it is a separate CUDA
image on a GPU host. The repo's own stub (`scripts/demo_stub_acestep.py`) stands in for it,
which is what the existing demos do.

```
POST /api/v1/generate  →  {"job_id":"6a79ff0e…","status":"queued"}
poll 1: queued
poll 2: completed
  clip_ids   ["6a79ff11…d","6a79ff11…e"]
  audio_urls ["/data/storage/…/clips/6a79ff11…d.wav", …]

$ docker compose exec api find /data/storage -name '*.wav'
/data/storage/6a79fe14…/6a79fe14…/clips/6a79ff11…d.wav
/data/storage/6a79fe14…/6a79fe14…/clips/6a79ff11…e.wav
```

Two clips, written to the mounted volume, by the in-process worker inside the API
container. And through the web container's BFF, which is how the browser reaches it:

```
GET localhost:3080/api/credits/balance  (Bearer)  → 200
{"balance":9,"tier":"free","upgrade_url":"/settings/billing"}
```

**Two real bugs surfaced here**, both now fixed in `compose.yaml`:

1. The stack passed no compute-target URL at all, so every generation 503'd on the
   availability probe with the stack otherwise perfectly healthy.
2. Setting only `ACEMUSIC_API_LOCAL_URL` was not enough. The router's probe reads that
   (`ApiSettings`, `ACEMUSIC_API_` prefix) while the job processor's client reads
   `ACEMUSIC_BASE_URL` (the CLI config, no `_API_`). With one set and not the other, every
   generation is **accepted and then fails**: `ACE-Step base URL is not configured`. Both
   are now passed through, the second defaulting to the first.

Neither is a new bug — they are the per-host tribal knowledge the issue is about, made
visible by writing the manifest down.

### ffmpeg is in the image, verified by the #401 watermark path

Not "the binary is present" — the actual free-tier watermarking code, on a real 720p
render, inside the container:

```
$ docker compose exec api python -c "…apply_watermark(…)"
watermark asset present: True /app/.venv/…/acemusic/assets/watermark.png
input bytes : 50391
marked bytes: 57790
changed     : True
marked video stream: h264,1280,720
```

```
$ docker run --rm acemusic-api ffmpeg -version
ffmpeg version 7.1.5-0+deb13u1
$ docker run --rm acemusic-api id
uid=10001(acemusic) gid=10001(acemusic)
```

### No component reads a CWD-relative path

Same container, three working directories:

```
cwd=/      storage=/data/storage  voice=/data/voice-training
cwd=/tmp   storage=/data/storage  voice=/data/voice-training
cwd=/app   storage=/data/storage  voice=/data/voice-training
```

The code defaults are `./acemusic-voice-training` and `Path.cwd()/"storage"`. They are
overridden by environment in the image rather than changed in code: `voice_training_root`
is deliberately relative so the API and ACE-Step share a filesystem, and the value is sent
verbatim to ACE-Step.

### Data survives a container recreation

```
$ …upload('u1/w1/clips/c1.wav', …); write /data/voice-training/model-1/voice.safetensors
$ docker compose up -d --force-recreate api
clip survived      : True
voice data survived: True
```

`--force-recreate`, not `restart` — that is the motion a deploy performs.

---

## Delivery

`scripts/deploy.sh` was run exactly as the workflow runs it, against a local
`registry:2` holding two tags: `goodsha` (the working image) and `badsha` (identical but
the API process exits immediately on start).

### First rollout, and the deployed commit is verifiable

```
$ ./deploy.sh goodsha
[deploy] deploying goodsha (currently: none)
[deploy] goodsha is live

$ curl …/api/v1/health
{"status":"ok","version":"0.1.0","uptime_seconds":4.147,"build_sha":"goodsha"}
```

`build_sha` is new (`GET /api/v1/health`). Before it, the only version the API reported was
the static `0.1.0` from `pyproject.toml` that nobody bumps — so "did the deploy land?" could
only be answered by trusting the workflow that said it had.

### Re-running the same deploy is a no-op

```
$ ./deploy.sh goodsha
[deploy] goodsha is already deployed and serving — nothing to do
container recreated? NO
```

Gated on what is actually serving, not on the recorded tag alone — a stack that has since
fallen over is still brought back (`test_it_redeploys_when_the_tag_matches_but_the_stack_is_down`).

### A broken deploy rolls back automatically and reports failure

```
$ ./deploy.sh badsha
[deploy] deploying badsha (currently: goodsha)
 Container acemusic-api-1 Recreated
[deploy] timed out after 45s waiting for build_sha=badsha (last seen: 'no response')
[deploy] rollback: restoring goodsha
 Container acemusic-api-1 Recreated
[deploy] badsha failed its health gate; rolled back to goodsha
exit=1

$ cat .deployed-tag → goodsha
$ curl …/health   → {"status":"ok",…,"build_sha":"goodsha"}
api  …/acemusic-api:goodsha  Up (healthy)
web  …/acemusic-web:goodsha  Up (healthy)
```

Exit 1, so the workflow step fails. A deploy that leaves the site down while reporting
green is the outcome this exists to prevent.

The gate is **not** "does something answer 200": a crash-looping new image leaves the
previous container answering happily. It waits for the API to report *the SHA just
deployed*.

### Two deploys cannot run concurrently

```
$ flock .deploy.lock sleep 8 &        # a rollout in flight
$ ./deploy.sh goodsha
[deploy] another deploy is already running (…/.deploy.lock)
exit=3
```

`concurrency: production` in the workflow only serialises workflow runs; the host-side lock
also covers an operator running the rollout by hand, which is exactly when someone would.

### Unconfigured is skipped, not green

The complaint in the issue is that `docker-publish.yml` reports **success** having skipped
checkout, build and push. Both publish paths are now gated at *job* level on a repository
variable, so an unconfigured repo renders them as **Skipped**. Enabled-but-not-credentialed
fails loudly instead.

---

## Tests

`tests/test_deploy_script.py` — 8 cases covering the rollout, the SHA gate, idempotence,
the concurrency lock, rollback, and the first-ever-deploy case where there is nothing to
roll back to. `docker` and `curl` are stubbed on PATH, so they run in CI with no daemon.

A rollback that has never run is not a rollback.

`tests/test_api_health.py` — `build_sha` reported from the environment, `unknown` outside a
built image.

`ci.yml` gains a `build images` job: both images are built (not pushed) on every PR, so a
Dockerfile that does not build fails the PR rather than the deploy. The web image build runs
`npm run typecheck` and `next build`, which is the first time either has run in automation.

---

## Not verified here

- **The SSH rollout to a production VPS.** No host, user or key exists. `deploy.sh` — the
  health gate, rollback, idempotence and locking — is exercised against a real stack above;
  the workflow step that carries it over SSH is not.
- **A live GHCR publish.** It needs no new secrets (`GITHUB_TOKEN` authenticates), so it
  will run for real on the first merge to `main`; it cannot run from a branch beforehand.
- **`PRODUCTION_HEALTH_URL` post-deploy confirmation**, for the same reason.

To turn the rollout on: set `DEPLOY_ENABLED=true` plus `DEPLOY_HOST` / `DEPLOY_USER` /
`DEPLOY_SSH_KEY` on the `production` environment. Full list in `docs/deployment.md`.
