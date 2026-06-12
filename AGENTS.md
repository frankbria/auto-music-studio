# AGENTS.md — Auto Music Studio

## Project Overview

AI-powered music generation platform built on **ACE-Step-1.5** (fork: `github.com/frankbria/ACE-Step-1.5`). The platform follows a 4-layer architecture, building outward from a runnable CLI core:

1. **Layer 1 — CLI Foundation** (Stages 1–7): `acemusic` CLI for generation, workspace management, audio processing, and DAW export
2. **Layer 2 — Platform API** (Stages 8–14): FastAPI backend with auth, async jobs, remote compute, mastering, and distribution
3. **Layer 3 — Web UI** (Stages 15–21): Next.js frontend
4. **Layer 4 — Advanced Integrations** (Stages 22–28): VST3 plugin, music video, voice models, credits, moderation

**Current progress:** Stages 1–9 complete on `main`; Stage 10 in progress (US-10.1 audio editing endpoints implemented). CLI foundation (Stages 1–7): generation, workspace management, audio processing, DAW export. Platform API (Stages 8–9): FastAPI with OAuth2 auth, async job queue, clip audio streaming, workspace/clip/preset CRUD, credit deduction. Audio editing API (US-10.1): crop, speed-adjust, and remaster endpoints enqueue async jobs that create derived clips with lineage tracking.

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

# Composition plans (#96) — structured multi-section generation via ElevenLabs
uv run acemusic compose "uplifting indie-pop song" --duration 120 --seed 42   # plan (intro/verse/chorus/…) → one-shot MP3
uv run acemusic compose "cinematic theme" --instrumental --name main-theme

# Short samples via ElevenLabs (#96) — sounds also accepts --backend
uv run acemusic sounds "deep kick drum" --type one-shot --backend elevenlabs

# Iterative generation (US-6.1) — extend an existing clip with AI-generated continuation
uv run acemusic extend 42 --duration 60s                          # extend clip 42 by 60s from its end
uv run acemusic extend 42 --duration 30s --from 45s               # extend from a mid-clip timestamp
uv run acemusic extend 42 --duration 30s --style "add a bridge feel" --lyrics "[Bridge]\nWe cross the river"

# Cover mode (US-6.2) — restyle an existing clip in a different genre
uv run acemusic cover 42 --style "jazz piano trio"                # cover clip 42 in a new style
uv run acemusic cover 42 --style "lo-fi hip hop" --lyrics "[Verse]\nNew words"   # cover with lyric override

# Repaint (US-6.3) — regenerate a section of a clip with crossfade-blended boundaries
uv run acemusic repaint 42 --start 10s --end 20s --prompt "add a guitar solo"   # regenerate 10s–20s
uv run acemusic repaint 42 --start 30s --end 45s --prompt "soft strings" --style "ambient" --crossfade-ms 100

# Mashup (US-6.4) — combine elements from two clips with BPM alignment
uv run acemusic mashup 42 43                                                    # layered blend (default), BPM aligned
uv run acemusic mashup 42 43 --blend sequential                                 # section-by-section blend
uv run acemusic mashup 42 43 --blend ai-guided --style "lo-fi hip hop"          # model chooses; unifying style applied

# Add vocal (US-6.6) — layer vocals onto an instrumental clip
uv run acemusic add-vocal 42 --lyrics "[Verse]\nSing this line"                                    # default voice
uv run acemusic add-vocal 42 --lyrics "[Chorus]\nLouder now" --voice soulful --style "breathy"     # styled vocal

# Replace section (US-6.6) — regenerate a specific time range with new instructions
uv run acemusic replace 42 --start 30s --end 45s --prompt "make this section more energetic"      # locks context (default)
uv run acemusic replace 42 --start 1m --end 1m30s --prompt "soft strings" --no-lock-context        # use model output as-is

# Full song auto-extend (US-6.7) — grow a short seed clip into a complete song
uv run acemusic full-song 42 --auto                                       # build a ~3.5min song from clip 42 without prompts
uv run acemusic full-song 42                                              # interactive: confirm after each of 7 sections
uv run acemusic full-song 42 --target-duration 180 --style "indie folk"   # custom length + base style override

# Workspace management (US-4.1)
uv run acemusic workspace list                        # list all workspaces (auto-creates Default)
uv run acemusic workspace create "My Album"           # create a new workspace
uv run acemusic workspace switch "My Album"           # set active workspace
uv run acemusic workspace rename "My Album" "Debut"   # rename a workspace
uv run acemusic workspace delete "Debut"              # delete (prompts if clips exist)
uv run acemusic workspace delete "Debut" --force      # delete without confirmation

# Export (US-7.1) — export a clip to disk in the chosen audio format
uv run acemusic export 42                                              # default: WAV 48kHz/24-bit → ./<slug>.wav
uv run acemusic export 42 --format wav32                               # 48kHz / 32-bit float WAV
uv run acemusic export 42 --format flac                                # lossless FLAC
uv run acemusic export 42 --format mp3                                 # 320 kbps MP3
uv run acemusic export 42 --format flac --output /path/to/out.flac     # explicit destination path
```

## Architecture

### Source Layout

```
src/acemusic/
  __init__.py       # Package metadata (__version__)
  api/              # FastAPI platform API (Layer 2)
    main.py         # create_app() factory + ASGI app (uvicorn target); DB lifespan
    settings.py     # ApiSettings (pydantic-settings, ACEMUSIC_API_ prefix)
    database.py     # MongoDB connect/close (Beanie + pymongo async), fail-fast ping
    models/         # Beanie ODM documents: User, Workspace, Clip, Job, Preset, CreditTransaction
    routers/        # Versioned routers mounted under /api/v1 (health, auth, users, generation, jobs, clips, editing, workspaces, presets)
  backends.py       # Backend selector: resolve_backend (auto|ace-step|elevenlabs) + capability map
  cli.py            # Typer CLI app (health, generate, compose, sounds, models, workspace commands)
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
- **`cli.py`** — Typer-based CLI. Commands: `health`, `generate`, `models`, `extend`, `cover`, `repaint`, `mashup`, `sample`, `add-vocal`, `replace`, `full-song`, and the `workspace` subcommand group (`create`, `list`, `switch`, `rename`, `delete`). Uses `AceStepClient` for generation and `workspace.py` for workspace ops.
- **`song_structure.py`** — Pure planning module for the `full-song` command (US-6.7). Defines the canonical `SONG_STRUCTURE` (intro → outro), per-section weights and style hints, and `plan_sections(seed_duration, target_duration)` which distributes the remaining time across seven sections without ever overshooting the target.
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
