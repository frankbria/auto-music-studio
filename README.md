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

## Environment

Copy `.env.example` to `.env` and fill in the required values before running.
