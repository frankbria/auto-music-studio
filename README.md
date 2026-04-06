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

## Environment

Copy `.env.example` to `.env` and fill in the required values before running.
