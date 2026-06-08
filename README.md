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

## Environment

Copy `.env.example` to `.env` and fill in the required values before running.
