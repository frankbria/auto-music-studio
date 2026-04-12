# AGENTS.md — Auto Music Studio

## Project Overview

AI-powered music generation platform built on **ACE-Step-1.5** (fork: `github.com/frankbria/ACE-Step-1.5`). The platform follows a 4-layer architecture, building outward from a runnable CLI core:

1. **Layer 1 — CLI Foundation** (Stages 1–7): `acemusic` CLI for generation, workspace management, audio processing, and DAW export
2. **Layer 2 — Platform API** (Stages 8–14): FastAPI backend with auth, async jobs, remote compute, mastering, and distribution
3. **Layer 3 — Web UI** (Stages 15–21): Next.js frontend
4. **Layer 4 — Advanced Integrations** (Stages 22–28): VST3 plugin, music video, voice models, credits, moderation

**Current progress:** Stages 1–4 complete. CLI entry point, health check, basic generation, musical parameters, quality/speed tradeoffs, model selection, sound modes, and workspace management all implemented.

## Commands

```bash
# Setup
uv venv
uv sync --extra dev

# Run tests (unit only, excludes integration)
uv run pytest

# Run integration tests (requires live ACE-Step server)
uv run pytest -m integration

# Run all tests
uv run pytest --run-integration

# Lint
uv run ruff check .

# Format check
uv run black --check .

# Format fix
uv run black .

# Smoke test
uv run python -c "import acemusic"

# CLI usage
uv run acemusic --help
uv run acemusic health
uv run acemusic generate "upbeat pop" --output ./output --name demo
uv run acemusic generate "dark electro" --bpm 128 --key "C minor" --time-signature "4/4" --seed 42 --duration 60
uv run acemusic generate "ambient pad" --backend elevenlabs --instrumental

# Workspace management (US-4.1)
uv run acemusic workspace list                        # list all workspaces (auto-creates Default)
uv run acemusic workspace create "My Album"           # create a new workspace
uv run acemusic workspace switch "My Album"           # set active workspace
uv run acemusic workspace rename "My Album" "Debut"   # rename a workspace
uv run acemusic workspace delete "Debut"              # delete (prompts if clips exist)
uv run acemusic workspace delete "Debut" --force      # delete without confirmation
```

## Architecture

### Source Layout

```
src/acemusic/
  __init__.py       # Package metadata (__version__)
  cli.py            # Typer CLI app (health, generate, models, workspace commands)
  client.py         # AceStepClient — HTTP client for ACE-Step REST API
  config.py         # Config loading: env > .env > ~/.acemusic/config.yaml
  db.py             # SQLite connection and schema init (~/.acemusic/metadata.db)
  utils.py          # Filename helpers (make_slug, make_filename, get_duration)
  workspace.py      # Workspace CRUD — create, list, switch, rename, delete

tests/
  conftest.py       # Fixtures: ace_server (session-scoped lifecycle), integration_url
  test_cli.py       # CLI entry point tests
  test_client.py    # AceStepClient unit tests (mocked HTTP)
  test_generate.py  # Generate command tests (unit + integration)
  test_health.py    # Health command tests
  test_utils.py     # Utility function tests
  test_package.py   # Package import/version tests
  test_smoke.py     # Test runner smoke test
  test_workspace.py # Workspace command tests
  features/         # pytest-bdd feature files (not yet populated)

web/                # Next.js frontend (placeholder, Layer 3)
plugin/             # JUCE VST3 plugin (placeholder, Layer 4)
docs/               # Additional documentation (placeholder)
```

### Key Modules

- **`client.py`** — The core integration with ACE-Step-1.5. Understands the API envelope (`{"data": ..., "code": 200}`), integer status codes (0=pending, 1=completed, 2=failed), and the `/release_task` → `/query_result` → `/v1/audio` workflow.
- **`cli.py`** — Typer-based CLI. Commands: `health`, `generate`, `models`, and the `workspace` subcommand group (`create`, `list`, `switch`, `rename`, `delete`). Uses `AceStepClient` for generation and `workspace.py` for workspace ops.
- **`config.py`** — Returns `AceConfig(api_url, api_key, output_dir)`. Priority: env vars > `.env` > `~/.acemusic/config.yaml`.
- **`db.py`** — Opens (and schema-inits on first use) the SQLite metadata database at `~/.acemusic/metadata.db`. All workspace state is persisted here.
- **`workspace.py`** — CRUD operations on workspaces. Audio clips are stored under `~/.acemusic/workspaces/{id}/clips/`. A "Default" workspace is auto-created on first access. `generate` falls back to the active workspace's clips directory when `--output` and `config.output_dir` are both unset.

### ACE-Step API Contract

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/stats` | GET | Server stats (models, jobs, avg time) |
| `/release_task` | POST | Submit generation job → returns `task_id` |
| `/query_result` | POST | Poll status (body: `{"task_id_list": [id]}`) |
| `/v1/audio?path=...` | GET | Download generated audio |

Response envelope: `{"data": {...}, "code": 200, "error": null}`
Status integers: `0` = queued/running, `1` = succeeded, `2` = failed
Result field: JSON string `[{"file": "/v1/audio?path=..."}]`

## Configuration

Environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `ACEMUSIC_BASE_URL` | ACE-Step API URL (required for CLI) |
| `ACEMUSIC_API_KEY` | API key for platform auth |
| `ACESTEP_LOCAL_URL` | Local ACE-Step server (default `http://localhost:8001`) |
| `ACESTEP_API_KEY` | Key securing the ACE-Step server process |
| `RUNPOD_API_KEY` | RunPod management API key (remote GPU) |
| `RUNPOD_ENDPOINT_ID` | RunPod serverless endpoint ID |
| `SECRET_KEY` | App secret for sessions/CSRF |
| `DATABASE_URL` | DB connection (SQLite for dev, PostgreSQL for prod) |
| `ACEMUSIC_POLL_TIMEOUT` | Generation poll timeout in seconds (default 600) |

## Code Style

- **Python 3.11+**, line length 120
- **black** owns all formatting; **ruff** handles lint only (`E7`, `E9`, `F`, `I`)
- No comments unless requested
- Imports sorted with `isort` (ruff rule `I`), first-party: `acemusic`

## Testing

- **pytest** with `pytest-bdd` and `pytest-cov`
- Tests in `tests/`, features in `tests/features/`
- Coverage target: >85%
- Integration tests marked `@pytest.mark.integration` (excluded by default)
- Integration tests require a live ACE-Step server (auto-started via `ACESTEP_API_CMD` env var, or skipped)
- Test config: `testpaths = ["tests"]`, `bdd_features_base_dir = "tests/features"`

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml`:
1. `trailing-whitespace` + `end-of-file-fixer`
2. `black` (owns formatting)
3. `ruff` with `--no-fix` (lint only, runs after black)

## CI

GitHub Actions (`.github/workflows/ci.yml`):
- Triggers on push (all branches) and PR to `main`
- Matrix: Python 3.11, 3.12
- Steps: `uv sync --extra dev` → `black --check` → `ruff check` → `pytest --cov`

## Key References

- `ai-music-spec.md` — Full platform specification (49 sections across 8 parts)
- `model-deployment.md` — ACE-Step deployment guide (local + RunPod)
- `user-stories/00-overview.md` — Story index and development methodology
- `user-stories/01-layer-1-cli-foundation.md` — CLI user stories (Stages 1–7)
- `user-stories/02-layer-2-platform-api.md` — API user stories (Stages 8–14)
- `user-stories/03-layer-3-web-ui.md` — Web UI user stories (Stages 15–21)
- `user-stories/04-layer-4-advanced-integrations.md` — Advanced stories (Stages 22–28)

## Dependencies

Runtime: `typer`, `httpx`, `python-dotenv`, `PyYAML`, `mutagen`
Dev: `pytest`, `pytest-bdd`, `pytest-cov`, `ruff`, `black`
Package manager: `uv` with `hatchling` build backend

## Agent Notes

- The `web/`, `plugin/`, and `docs/` directories are placeholders — don't expect working code there yet
- User stories are numbered `US-{stage}.{sequence}` (e.g., US-2.1 = Stage 2, first story)
- Integration tests are gated behind `@pytest.mark.integration` and skip gracefully without a server
- The `.beads/` directory is local-only (gitignored) for issue tracking across sessions
- Story references in code comments map to user stories (e.g., `US-2.1`, `US-2.3`)
