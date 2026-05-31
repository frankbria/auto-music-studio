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

## Environment

Copy `.env.example` to `.env` and fill in the required values before running.
