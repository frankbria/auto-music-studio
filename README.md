# Auto Music Studio

AI-powered music generation platform built on ACE-Step-1.5.

## Bootstrap

```bash
uv venv
uv sync --extra dev
uv run python -c "import acemusic"  # smoke test
```

## Running tests

```bash
uv run pytest
```

## Running the API (Layer 2)

The platform API is a FastAPI app served under `/api/v1`:

```bash
uv run uvicorn acemusic.api.main:app --reload
```

Then visit `http://127.0.0.1:8000/docs` for the interactive Swagger UI, or
`GET /api/v1/health` for a liveness check. Allowed CORS origins are configured
via `ACEMUSIC_API_CORS_ALLOW_ORIGINS` (comma-separated).

The API requires **MongoDB** and fails fast on startup if it is unreachable.
Set `ACEMUSIC_API_MONGODB_URL` (defaults to `mongodb://localhost:27017`); use an
Atlas `mongodb+srv://…` string for staging/production. Local integration tests
run only against a local MongoDB (`uv run pytest -m integration`).

### Authentication

Sign-in uses **OAuth2** (Google and Discord) and issues a short-lived JWT access
token plus a rotating, single-use refresh token. All `/api/v1` routes except
`/health` and `/auth/*` require an `Authorization: Bearer <access_token>` header.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/auth/login/{provider}` | Returns the provider authorization URL and sets the CSRF state cookie |
| `POST /api/v1/auth/callback/{provider}` | Validates state against the cookie, exchanges the code, upserts the user, mints tokens |
| `POST /api/v1/auth/refresh` | Rotates the refresh token for a new access token |
| `POST /api/v1/auth/logout` | Revokes a refresh token (idempotent) |

### User profile

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/users/me` | Returns the authenticated user's full profile |
| `PATCH /api/v1/users/me` | Partially updates the profile (`display_name`, `handle`, `bio`, `style_tags`); unset fields are left unchanged |
| `GET /api/v1/users/me/credits` | Returns the authenticated user's current credit balance, subscription tier, and recent usage history (newest first, up to 50 entries) |

Profile fields: `display_name` (user-editable name, 1–100 chars), `handle` (unique public identifier — alphanumeric + hyphens, 3–30 chars, must start and end with a letter or number; currently case-sensitive), `bio` (up to 500 chars), `style_tags` (up to 20 tags, 30 chars each). A duplicate handle returns `409 Conflict`; an invalid handle or unknown PATCH key returns `422`.

The OAuth `state` is bound to the initiating client to prevent login CSRF /
session fixation: `/login` sets a per-flow, HttpOnly+SameSite cookie holding a
nonce, and `/callback` requires that cookie to match the signed `state`. **The
client must therefore preserve cookies between `/login` and `/callback`.** Use a
same-origin frontend/API in dev (the default `SameSite=Lax` works); a split-origin
SPA must serve over HTTPS with `ACEMUSIC_API_OAUTH_COOKIE_SAMESITE=none` and make
credentialed requests (a cross-origin **plain-HTTP** pair cannot carry the cookie —
a browser constraint, not a code limitation).

Configure provider credentials and the JWT signing secret via the
`ACEMUSIC_API_GOOGLE_*`, `ACEMUSIC_API_DISCORD_*`, and `ACEMUSIC_API_JWT_SECRET_KEY`
environment variables (see `.env.example`); cookie behavior is tuned via
`ACEMUSIC_API_OAUTH_COOKIE_SECURE` / `ACEMUSIC_API_OAUTH_COOKIE_SAMESITE`.
`jwt_algorithm` is restricted to the HMAC family (`HS256`/`HS384`/`HS512`).

### Generation

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/generate` | Submits a generation request and returns a `job_id` for async tracking (HTTP 202) |
| `GET /api/v1/jobs/{id}/status` | Returns a job's current status; owner-scoped (404 for missing or other users' jobs) |

The request body accepts the full creative parameter set: `prompt` (required), `style`, `lyrics`, `vocal_language`, `instrumental`, `bpm` (60–180 or `"auto"`), `key`, `time_signature`, `duration`, `seed`, `inference_steps`, `model`, `weirdness` (0–100), `style_influence` (0–100), `format` (`wav`/`flac`/`mp3`/`aac`/`opus`), `thinking`, `mode` (`song`|`sound`), `sound_type` (`one-shot`|`loop`, required when `mode` is `sound`), and the optional `preset_id`. When `preset_id` is supplied the saved preset's parameters serve as defaults; any field explicitly included in the request overrides the preset value. The job is created with status `queued` and picked up by the async processor (US-9.2).

Invalid parameters return 422 with field-level errors. If the user has insufficient credits for the requested mode (song costs 1.0 credit, sound costs 0.5), the request is rejected with `402 Payment Required` and a JSON body of `{"detail": {"error": "insufficient_credits", "balance": <current>, "required": <cost>}}`. New accounts start with 10.0 credits. The create response includes `job_id`, `status: "queued"`, and `estimated_time_seconds`.

The status endpoint returns `job_id`, `status` (`queued`|`processing`|`completed`|`failed`), `created_at`, and `estimated_time_seconds`. Completed jobs additionally include `clip_ids` and `audio_urls`; failed jobs include an `error` message.

#### Async job processor (US-9.2, US-10.1, US-10.3)

A background processor runs inside the API process, polling MongoDB for `queued`
jobs and dispatching them to the handler registered for their `job_type`. Generation
jobs (`generate`) forward to ACE-Step, store the audio, and create clip records.
Editing jobs (`crop`, `speed`, `remaster`) run local CPU operations via the audio
processing library. Iterative generation jobs (`extend`, `cover`, `remix`, `repaint`,
`sample`, `add_vocal`, `mashup`) run ACE-Step operations and create lineage-tagged child
clips. All handlers mark the job `completed` (or `failed` with an
error). Tunables (all prefixed `ACEMUSIC_API_`): `JOB_CONCURRENCY` (default 2),
`JOB_POLL_INTERVAL` seconds (default 1.0), `JOB_POLL_TIMEOUT` seconds (default
600), and `JOB_PROCESSOR_ENABLED` (default `true`; set `false` to run the API
without the worker — recommended to run a single processor instance).

### Workspaces

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/workspaces` | Create a workspace (201; 409 on duplicate name) |
| `GET /api/v1/workspaces` | List all workspaces for the authenticated user with per-workspace clip counts |
| `GET /api/v1/workspaces/{id}` | Get a single workspace (404 if missing or not owned) |
| `PATCH /api/v1/workspaces/{id}` | Rename a workspace (409 on duplicate name; empty body is a no-op) |
| `DELETE /api/v1/workspaces/{id}` | Delete a workspace (409 if non-empty without `?force=true`; 400 if it is the last workspace) |

A default workspace is created automatically when a new user registers (OAuth callback). The get-or-create call is idempotent, so subsequent logins are a cheap lookup and accounts created before this feature are backfilled on their next login.

### Clips

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/clips` | Paginated clip list with search, filter, and sort |
| `GET /api/v1/clips/{id}` | Get clip metadata (404 if missing or not owned) |
| `PATCH /api/v1/clips/{id}` | Rename a clip (`title` is the only writable field; empty body is a no-op) |
| `DELETE /api/v1/clips/{id}` | Delete the clip record and its stored audio |
| `GET /api/v1/clips/{id}/audio` | Streams or downloads a clip's audio with the correct `Content-Type` |

`GET /api/v1/clips` supports these query parameters: `workspace_id`, `search` (case-insensitive substring over title or style tags), `style`, `bpm_min`, `bpm_max`, `key`, `model`, `sort` (`newest` or `oldest`, default `newest`), `page` (default 1), `per_page` (default 20, max 100). An inverted BPM range (`bpm_min > bpm_max`) returns 422. The response includes `total`, `page`, `per_page`, and `total_pages`.

All CRUD endpoints are owner-scoped. `GET /api/v1/clips/{id}/audio` additionally supports single HTTP byte ranges (`Range: bytes=…` → `206 Partial Content`, unsatisfiable ranges → `416`) for seeking, and on-the-fly conversion via `?format=wav|flac|mp3` (mp3/flac conversion requires ffmpeg on the host; byte ranges are ignored for converted output). For the audio endpoint an unknown or malformed id returns `404`, another user's private clip returns `403`, and clips marked `is_public` are retrievable by any authenticated user; the CRUD endpoints return `404` for any clip the caller does not own.

### Audio Editing (US-10.1)

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/clips/{id}/crop` | Trim a clip to `[start, end]` with optional fades and beat-snap; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/speed` | Time-stretch a clip by a `multiplier` (0.5–2.0) or to a `target_bpm`; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/remaster` | Loudness-normalise a clip to a `target_lufs` (default −14 LUFS); returns 202 + `job_id` |

All three editing endpoints are non-destructive: the original clip is never modified. Each operation creates a new clip with `parent_clip_ids` and `generation_mode` set for lineage tracking, and tracks progress via `GET /api/v1/jobs/{id}/status`. Only `wav` source clips are accepted (422 otherwise). No credits are deducted — editing is local CPU work. Time parameters use human-readable strings (`"10s"`, `"1m30s"`, `"5"`). The `speed` endpoint accepts either `multiplier` (direct rate) or `target_bpm` (requires BPM metadata on the source clip); exactly one must be provided.

### Stems & MIDI Extraction (US-10.2)

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/clips/{id}/stems` | Separate a clip into `vocals`/`drums`/`bass`/`other`; returns 202 + `job_id` (or 200 with the existing stems on a cache hit) |
| `GET /api/v1/clips/{id}/stems` | The 4 stem clip ids and labels once separated (404 until the full set exists) |
| `POST /api/v1/clips/{id}/midi` | Extract `melody`/`chords`/`bass`/`drums` MIDI; returns 202 + `job_id` (or 200 with the existing files on a cache hit) |
| `GET /api/v1/clips/{id}/midi` | Download URLs for the extracted `.mid` files (404 until extracted) |

Both operations run as background jobs and are tracked via `GET /api/v1/jobs/{id}/status` — completed stems jobs surface `clip_ids`/`audio_urls`, completed MIDI jobs surface `midi_download_urls`. Stems become **four child clips** linked to the parent (`generation_mode="stems"`, same duration as the source); MIDI files are stored as objects (not clip records) and referenced from the parent clip's `midi_paths`. Requests are cache-first and idempotent per clip: re-requesting returns the existing results, and a second request while a job is in flight rides the existing job rather than enqueuing a duplicate. Only `wav` source clips are accepted (422 otherwise); no credits are deducted.

### Iterative Generation (US-10.3)

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/clips/{id}/extend` | Grow a clip by `duration` from `from_point` (default the end); returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/cover` | Restyle a clip in a new `style`; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/remix` | Style transfer to a new `style`; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/repaint` | Regenerate the `[start, end]` range from a `prompt`; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/sample` | Extract the `[start, end]` range and build `num_clips` tracks around it; returns 202 + `job_id` |
| `POST /api/v1/clips/{id}/add-vocal` | Layer vocals onto a clip from `lyrics`; returns 202 + `job_id` |
| `POST /api/v1/mashup` | Blend 2–8 owned clips into one; returns 202 + `job_id` |

All iterative endpoints are credit-bearing generative operations (unlike editing/extraction). Credits are deducted at queue time; insufficient balance returns `402 Payment Required` with `{"error": "insufficient_credits", "balance": <current>, "required": <cost>}`. Credit costs: extend/cover/remix/repaint/add-vocal = 1 credit each; sample = 1 credit × `num_clips` (default 1, max 4); mashup = 2 credits.

All endpoints are non-destructive: the original clip(s) are never modified. Each produces a new clip with `parent_clip_ids` and `generation_params` set for lineage tracking. Jobs are tracked via `GET /api/v1/jobs/{id}/status`. Only `wav` source clips are accepted (422 otherwise); clips without duration metadata are also rejected (422). Time parameters use human-readable strings (`"10s"`, `"1m30s"`, `"5"`) matching the CLI commands.

### Batch Processing (US-10.5)

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/batch/stems` | Queue stem separation for many clips at once (`{clip_ids[]}`); returns 202 + `batch_job_id` and one `sub_job_id` per queued clip |
| `POST /api/v1/batch/export` | Queue audio export of many clips to `format` (`{clip_ids[], format}`); returns 202 + `batch_job_id` and `sub_job_ids` |
| `GET /api/v1/batch/{batch_id}/status` | Overall progress (`completed`/`processing`/`failed`/`partial_success`) with a per-clip breakdown (404 if missing or not owned) |

Each request fans out into one sub-job per clip, tracked under a `BatchJob`. The 50-clip cap, an empty list, and duplicate ids each return 422. A clip that is unknown, not owned, or (for stems) non-`wav` is recorded as a **failed sub-job** rather than rejecting the whole request, so individual failures never halt the batch — the status reports `partial_success`. Stems sub-jobs reuse the single-clip stems job (wav only); export sub-jobs transcode any generated source (`wav`/`flac`/`mp3`/`aac`/`opus`) to a `wav`/`wav32`/`flac`/`mp3` target via ffmpeg and surface a `download_url` when complete. Like the single-clip extraction endpoints, these are non-generative local work, so **no credits are deducted**.

### Presets

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/presets` | Create a preset (201; 409 on duplicate name) |
| `GET /api/v1/presets` | List all presets for the authenticated user |
| `GET /api/v1/presets/{id}` | Get a single preset (404 if missing or not owned) |
| `PATCH /api/v1/presets/{id}` | Partially update a preset; sending `null` for a parameter clears it (409 on duplicate name; empty body is a no-op) |
| `DELETE /api/v1/presets/{id}` | Delete a preset (204) |

A preset is a named snapshot of generation parameters. Every creative field accepted by `POST /api/v1/generate` (except `prompt` and `preset_id`) can be saved in a preset; all fields are optional — a preset pins down only what the user chooses to fix. Preset names are unique per user. All endpoints are owner-scoped (404 for missing or another user's preset).

## Stem separation backends

`acemusic stems <clip_id>` separates a clip into stems. Two engines are available
via `--backend` (or the `ACEMUSIC_BACKEND` default):

- `auto` / `ace-step` — local demucs separation (default). Produces **four** stems:
  vocals, drums, bass, other, in `wav` or `flac` (`--output-format`).
- `elevenlabs` — cloud separation via the ElevenLabs API (requires
  `ELEVENLABS_API_KEY`; no local GPU needed). Produces **six** stems:
  vocals, drums, bass, **guitar**, **piano**, other, in the format configured
  by `ELEVENLABS_OUTPUT_FORMAT` (MP3 by default). `--output-format` is
  ignored — use `ELEVENLABS_OUTPUT_FORMAT` to control the stem format.

Either way, each stem is registered as a child clip of the source, so downstream
commands (DAW export, etc.) work the same.

## Repaint & extend backends

`acemusic repaint <clip_id>` regenerates a section of a clip and
`acemusic extend <clip_id>` lengthens one. Both accept `--backend`
(or the `ACEMUSIC_BACKEND` default):

- `auto` / `ace-step` — ACE-Step repaint task with local crossfade stitching
  (default; requires `ACEMUSIC_BASE_URL`).
- `elevenlabs` — cloud inpainting via ElevenLabs composition plans (requires
  `ELEVENLABS_API_KEY` and an account with the **enterprise inpainting
  feature**). The source clip — including ACE-Step-generated WAVs — is uploaded
  (priced like a generation), kept ranges are referenced server-side, and the
  result is saved in the `ELEVENLABS_OUTPUT_FORMAT` (MP3 by default).
  ElevenLabs limits: each plan section must be 3s–120s (so repaint boundaries
  must leave ≥3s of kept audio on each non-edge side) and the total track is
  capped at 600s. Range validation runs before the upload, so invalid requests
  never spend credits.

Either way, results are saved as child clips of the source
(`parent_clip_id` + `generation_mode`), so lineage-aware commands work the same.

## Mashup backends

`acemusic mashup <clip_id> <clip_id> [...]` combines source clips. The two
engines blend differently:

- `auto` / `ace-step` — audio-level blend of **exactly two** clips
  (`--blend layered|sequential|ai-guided`, BPM alignment, local stitching).
- `elevenlabs` — **two or more** clips are uploaded and recombined at the
  **section/composition level**: each source plays in sequence under an
  optional unifying `--style`, composed server-side (same enterprise gating,
  per-upload pricing, and 3s/120s/600s limits as repaint/extend; `--blend`
  does not apply). With `auto`, three or more clips route here automatically
  when `ELEVENLABS_API_KEY` is set, since only ElevenLabs can combine them.

Mashup results record **all** sources in `parent_clip_ids` (JSON list; existing
databases are migrated automatically) plus `parent_clip_id` for the primary.

## File storage

Audio files are managed through a single storage interface
(`acemusic.storage`) so callers are deployment-agnostic. Select a backend with
`ACEMUSIC_STORAGE_BACKEND`:

- `local` (default) — files on the local filesystem under
  `ACEMUSIC_STORAGE_LOCAL_ROOT` (defaults to `./storage`).
- `s3` — any S3-compatible bucket (AWS, MinIO, Backblaze B2) via the optional
  `s3` extra (`uv sync --extra s3`). Set `ACEMUSIC_S3_BUCKET` and, for non-AWS
  endpoints, `ACEMUSIC_S3_ENDPOINT_URL`. Credentials come from boto3's default
  chain (env vars / shared config / IAM roles) — never put them in app config.
  Downloads return presigned URLs whose lifetime is `ACEMUSIC_S3_URL_EXPIRY`
  seconds (default 3600).

Build the configured backend with `acemusic.storage.get_storage_backend()`;
keys follow `{user_id}/{workspace_id}/clips/{clip_id}.{format}`. See
`.env.example` for the full list of storage variables.

## Environment

Copy `.env.example` to `.env` and fill in the required values before running.
