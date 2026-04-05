# User Stories by Development Stage

**Project:** Auto Music Studio — AI Music Platform
**Version:** 1.0 Draft (April 2026)
**Methodology:** TDD, GitHub Issues per story, Agile/iterative delivery
**Reference:** [Platform Specification](ai-music-spec.md) · [Model Deployment Guide](model-deployment.md)

---

## Overview

This document defines user stories for the AI Music Platform organized into **28 development stages** across **4 layers**. The guiding principle is **build outward from a runnable core**:

1. **Layer 1 — CLI Foundation** (Stages 1–7): Every feature starts as a testable CLI command. The application runs locally, generates music, manages workspaces, processes audio, and exports for DAWs — all from the terminal.
2. **Layer 2 — Platform API** (Stages 8–14): CLI logic is wrapped in a FastAPI service with authentication, async job processing, remote compute, mastering, and distribution APIs.
3. **Layer 3 — Web UI** (Stages 15–21): A Next.js frontend consumes the API, providing the full creative and social experience.
4. **Layer 4 — Advanced Integrations** (Stages 22–28): VST3 plugin, music video, custom voice models, subscription/credits, moderation, and production polish.

**At every stage, the application runs.** A musician can use it — first via CLI, then via API calls, then through the browser, and finally from inside their DAW.

### How to Read This Document

- Each **stage** has an overview, a set of user stories, and stage completion criteria.
- Each **user story** contains: a user statement, a description, functional requirements (bullet points), and acceptance criteria (checkboxes).
- Stories are numbered `US-{stage}.{sequence}` (e.g., US-2.1 is the first story in Stage 2).
- **Stories are not exhaustive implementation specs.** They capture *what* and *why* — detailed technical design happens during implementation planning for each GH issue.
- Stages are sequential within a layer but some stages across layers can be parallelized (see [Dependency Graph](#dependency-graph)).

### User Personas

| Persona | Description |
|---------|-------------|
| **Musician** | Primary user — creates, edits, produces, and distributes music. May range from hobbyist to professional producer. |
| **Listener** | Discovers, plays, and engages with music on the platform's social features. |
| **Admin** | Platform operator — moderates content, manages users, monitors system health. |
| **Developer** | Builds and maintains the platform — needs reliable tooling, CI/CD, and observability. |

### Development Methodology

- **TDD:** Tests are written before implementation. Acceptance criteria map directly to test assertions.
- **GitHub Issues:** Each user story becomes one or more GH issues when its stage is active. Issues are not pre-created for future stages.
- **Feature branches:** Each story/issue is developed on a feature branch and merged via PR to `main`.
- **Agile flexibility:** Stages define *intent*, not contracts. Stories may be added, modified, split, or deferred as learning happens during development.

---

## Stage Map

```
LAYER 1: CLI FOUNDATION
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 1  │→│ Stage 2  │→│ Stage 3  │→│ Stage 4  │→│ Stage 5  │→│ Stage 6  │→│ Stage 7  │
│ Bootstrap│  │Model CLI │  │Gen Params│  │Workspace │  │Audio Proc│  │Iterative │  │DAW Export│
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘

LAYER 2: PLATFORM API
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 8  │→│ Stage 9  │→│ Stage 10 │→│ Stage 11 │→│ Stage 12 │→│ Stage 13 │→│ Stage 14 │
│API Found.│  │Gen API   │  │Edit API  │  │Compute   │  │Mastering │  │Distrib.  │  │Export API│
└─────────┘  └─────────┘  └─────────┘  │Routing   │  │API       │  │API       │  └─────────┘
                                         └─────────┘  └─────────┘  └─────────┘

LAYER 3: WEB UI
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 15 │→│ Stage 16 │→│ Stage 17 │→│ Stage 18 │→│ Stage 19 │→│ Stage 20 │→│ Stage 21 │
│App Shell │  │Create UI │  │Edit UI   │  │Waveform  │  │Studio UI │  │Social UI │  │Master UI │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘

LAYER 4: ADVANCED INTEGRATIONS
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 22 │  │ Stage 23 │→│ Stage 24 │  │ Stage 25 │  │ Stage 26 │→│ Stage 27 │→│ Stage 28 │
│Video Gen │  │VST3 Core │  │VST3 Adv. │  │Voice Mod.│  │Credits   │  │Moderat.  │  │Polish    │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘
```

---

## Layer 1: CLI Foundation

*Goal: Build a fully functional music generation and processing tool that runs entirely from the command line, backed by a locally-running ACE-Step-1.5 server.*

---

### Stage 1: Project Bootstrap

**Overview:** Establish the monorepo structure, development tooling, CI/CD pipeline, and testing framework. This stage produces no user-facing features but creates the foundation every subsequent stage builds on.

---

#### US-1.1: Repository and Development Environment

**As a** developer, **I want** a properly configured monorepo with Python tooling, **so that** I can begin building features with consistent code quality from day one.

**Description:**
Set up the project root with `uv` as the Python package manager, a `pyproject.toml` with development dependencies, and organized directory structure for the CLI, API, and future web/plugin code.

**Functional Requirements:**
- Monorepo root with `pyproject.toml` defining the `acemusic` package
- Directory structure: `src/acemusic/` (CLI + core logic), `tests/`, `docs/`
- Placeholder directories: `web/` (Next.js, future), `plugin/` (JUCE, future)
- `uv` environment with `uv venv` and `uv sync` working
- `.env.example` documenting all required environment variables
- `.gitignore` updated to cover Python, Node.js, JUCE build artifacts, audio files, and secrets

**Acceptance Criteria:**
- [ ] `uv sync` installs all dependencies without error
- [ ] `uv run python -c "import acemusic"` succeeds
- [ ] `.env.example` exists with documented variable descriptions
- [ ] Directory structure matches the monorepo layout

---

#### US-1.2: Test Framework and Linting

**As a** developer, **I want** pytest, pytest-BDD, and linting tools configured, **so that** I can write tests before code and maintain consistent style.

**Description:**
Configure pytest with pytest-BDD for behavioral tests, ruff for linting, and black for formatting. Include a trivial passing test to validate the setup.

**Functional Requirements:**
- pytest + pytest-BDD as test dependencies
- ruff configuration in `pyproject.toml` (line length, target Python version, selected rules)
- black configuration in `pyproject.toml`
- A trivial test (`tests/test_smoke.py`) that passes
- Test coverage reporting via `pytest-cov`

**Acceptance Criteria:**
- [ ] `uv run pytest` passes with at least 1 test
- [ ] `uv run ruff check .` passes with no errors
- [ ] `uv run black --check .` passes
- [ ] Coverage report is generated

---

#### US-1.3: CI Pipeline and Pre-Commit Hooks

**As a** developer, **I want** GitHub Actions CI and local pre-commit hooks, **so that** code quality is enforced automatically on every commit and PR.

**Description:**
Set up a GitHub Actions workflow that runs lint, type-check, and tests on every push/PR. Install pre-commit hooks locally using the project's hook templates.

**Functional Requirements:**
- GitHub Actions workflow (`.github/workflows/ci.yml`): lint → test → type-check
- Pre-commit hooks from templates (`/home/frankbria/projects/templates`)
- Hooks run: ruff, black, trailing whitespace, end-of-file-fixer
- Branch protection on `main`: require CI pass before merge

**Acceptance Criteria:**
- [ ] Push to any branch triggers CI; CI passes on clean repo
- [ ] `git commit` with a linting violation is blocked by pre-commit hook
- [ ] PR to `main` requires CI green

---

#### US-1.4: Issue Tracking Setup

**As a** developer, **I want** beads issue tracking initialized, **so that** I can track development work across stages and sessions.

**Description:**
Initialize the `.beads` directory for issue tracking so that `bd` commands are available throughout the project lifecycle.

**Functional Requirements:**
- Run `bd onboard` to initialize `.beads`
- Configure project label prefix (e.g., `ams-###`)
- Verify `bd quickstart` works

**Acceptance Criteria:**
- [ ] `.beads` directory exists in the repo
- [ ] `bd quickstart` runs without error
- [ ] Issues can be created with `bd` commands

---

**Stage 1 Completion Criteria:**
- CI pipeline is green
- Pre-commit hooks fire on commit
- `uv run pytest` passes
- Linting passes
- Issue tracking is initialized
- The repo is a clean foundation for Stage 2

---

### Stage 2: Local Model Client CLI

**Overview:** Create the `acemusic` CLI entry point and establish the connection to the ACE-Step-1.5 REST API. By the end of this stage, a musician can type a prompt and receive a playable audio file. This is the first "I made music" milestone.

---

#### US-2.1: CLI Entry Point

**As a** musician, **I want** a single command (`acemusic`) to interact with the AI music engine, **so that** I can generate music from my terminal without writing API calls.

**Description:**
Create the CLI application using a framework like `click` or `typer`. The command should be installable via `uv` and respond to `--help` and `--version` flags.

**Functional Requirements:**
- CLI entry point: `uv run acemusic` (or `acemusic` if installed)
- `--help` displays available subcommands
- `--version` displays current version
- Configuration loaded from `.env` or `~/.acemusic/config.yaml` (API URL, API key)
- Graceful error messages for missing configuration

**Acceptance Criteria:**
- [ ] `uv run acemusic --help` shows subcommand list
- [ ] `uv run acemusic --version` prints the version string
- [ ] Missing API URL produces a helpful error message, not a stack trace

---

#### US-2.2: Health Check

**As a** musician, **I want** to verify that the AI engine is running before I try to generate music, **so that** I get a clear error instead of a confusing timeout.

**Description:**
The `acemusic health` command checks the ACE-Step-1.5 API server at the configured URL and reports whether it's reachable, what models are loaded, and basic server stats.

**Functional Requirements:**
- `acemusic health` calls `GET /v1/stats` on the configured ACE-Step URL
- Displays: server status (up/down), loaded models, average job time, active jobs
- Color-coded output (green = healthy, red = unreachable)
- Timeout after 5 seconds with clear error message

**Acceptance Criteria:**
- [ ] With ACE-Step running: `acemusic health` shows "Server: healthy" and model info
- [ ] With ACE-Step stopped: `acemusic health` shows "Server: unreachable" within 5 seconds
- [ ] Output includes at least: status, loaded models, server URL

---

#### US-2.3: Basic Text-to-Music Generation

**As a** musician, **I want** to generate a song from a text prompt, **so that** I can hear an AI-composed track from just a description.

**Description:**
The `acemusic generate` command sends a text prompt to the ACE-Step-1.5 `/release_task` endpoint, polls for completion, downloads the audio, and saves it to the current directory. This is the core generation loop that everything else builds on.

**Functional Requirements:**
- `acemusic generate "a mellow folk song about rain"` submits to the API
- Polls `/query_result` until the job completes
- Downloads the generated audio file (WAV format by default)
- Saves to current directory with auto-generated filename (e.g., `mellow-folk-song-{timestamp}.wav`)
- Progress indicator while waiting (spinner or progress bar)
- Generates 2 clips per request (matching spec default)
- On success: prints file path(s) and duration
- On failure: prints error message from API

**Acceptance Criteria:**
- [ ] With ACE-Step running: `acemusic generate "upbeat pop"` produces 2 playable WAV files
- [ ] Files are saved to the current directory with descriptive names
- [ ] Output shows file paths and durations
- [ ] Generation failure shows a meaningful error message
- [ ] Progress is visible during the wait

---

#### US-2.4: Output Directory and Naming

**As a** musician, **I want** to control where generated files are saved, **so that** I can organize my output.

**Description:**
Support `--output` flag to specify a target directory, and `--name` to set a custom filename prefix.

**Functional Requirements:**
- `--output /path/to/dir` saves files to the specified directory (created if needed)
- `--name "my-song"` uses the given prefix instead of auto-generated name
- Default output directory configurable in config file

**Acceptance Criteria:**
- [ ] `acemusic generate "test" --output ./songs --name "demo"` saves to `./songs/demo-1.wav` and `./songs/demo-2.wav`
- [ ] Non-existent output directory is created automatically
- [ ] Default output from config is respected when flags are omitted

---

**Stage 2 Completion Criteria:**
- `acemusic health` reports server status
- `acemusic generate "any prompt"` produces playable audio files
- Error handling covers server-down, timeout, and API errors
- Configuration is externalized (env vars or config file)
- All features covered by tests (unit + integration with real ACE-Step server)

---

### Stage 3: Core Generation Parameters CLI

**Overview:** Expose the full parameter surface of ACE-Step-1.5 through the CLI — BPM, key, duration, seed, style tags, lyrics, vocal language, instrumental mode, model selection, and sounds mode. After this stage, the musician has precise creative control.

---

#### US-3.1: Style and Lyrics Parameters

**As a** musician, **I want** to specify style tags and lyrics separately from the prompt, **so that** I have precise control over the song's genre and words.

**Description:**
Add `--style` and `--lyrics` flags. Style accepts comma-separated descriptors. Lyrics can be inline or loaded from a file. Supports structure tags like `[Verse]`, `[Chorus]`.

**Functional Requirements:**
- `--style "dark electro, punchy drums, dreamy"` sets style descriptors
- `--lyrics "..."` provides inline lyrics
- `--lyrics-file song.txt` loads lyrics from a file
- `--vocal-language en` sets the vocal language (ISO 639-1 code, default "auto")
- `--instrumental` flag suppresses vocals entirely
- Style and lyrics are sent as separate API parameters (not merged into prompt)

**Acceptance Criteria:**
- [ ] `acemusic generate "pop song" --style "upbeat, synth-pop" --lyrics "[Verse]\nHello world"` uses all three inputs
- [ ] `--lyrics-file` reads from disk and sends content to API
- [ ] `--instrumental` produces a track without vocals
- [ ] `--vocal-language ja` generates with Japanese vocals

---

#### US-3.2: Musical Parameters

**As a** musician, **I want** to set BPM, key, time signature, and duration, **so that** the generated music fits my project's requirements.

**Description:**
Expose the core musical parameters that ACE-Step-1.5 accepts. These allow the musician to constrain the generation to specific musical properties.

**Functional Requirements:**
- `--bpm 120` sets tempo (range: 60–180, or "auto")
- `--key "C major"` sets the tonal center (or "any" for auto)
- `--time-signature "4/4"` sets meter (4/4, 3/4, 6/8, 5/4, 7/8)
- `--duration 90` sets target length in seconds (30–240)
- `--seed 42` sets a fixed seed for reproducibility (`-1` or omit for random)
- Invalid parameter values produce clear validation errors

**Acceptance Criteria:**
- [ ] `--bpm 128` generates a track at approximately 128 BPM
- [ ] `--seed 42` produces identical output on repeated runs with same parameters
- [ ] `--duration 60` produces a clip approximately 60 seconds long
- [ ] `--bpm 999` produces a validation error, not an API crash

---

#### US-3.3: Generation Quality Controls

**As a** musician, **I want** to control the quality/speed tradeoff and creative parameters, **so that** I can do quick previews or high-quality final renders.

**Description:**
Expose inference steps, weirdness, and style influence sliders, plus output format selection.

**Functional Requirements:**
- `--inference-steps 8` sets the number of diffusion steps (Turbo: 8, Standard: 32–64)
- `--weirdness 75` sets deviation from conventional structures (0–100, default 50)
- `--style-influence 80` sets adherence to style descriptors (0–100, default 50)
- `--format wav|flac|mp3|aac|opus` sets the output audio format
- `--thinking` enables Chain-of-Thought mode for richer control

**Acceptance Criteria:**
- [ ] `--inference-steps 8` generates significantly faster than `--inference-steps 64`
- [ ] `--format mp3` produces an MP3 file (not WAV)
- [ ] `--weirdness 100` produces noticeably more experimental output than `--weirdness 0`

---

#### US-3.4: Model Selection

**As a** musician, **I want** to choose which AI model variant to use, **so that** I can pick the right quality/speed tradeoff for my task.

**Description:**
List available models and allow selection per-generation. Maps to ACE-Step-1.5's multi-model support.

**Functional Requirements:**
- `acemusic models` lists available model variants with descriptions (Turbo, Base, SFT, XL-Base, XL-SFT, XL-Turbo)
- `--model turbo` selects a specific variant for generation
- Display VRAM requirements and recommended inference steps per model
- Default model configurable in config file

**Acceptance Criteria:**
- [ ] `acemusic models` lists at least one model with name, description, and VRAM info
- [ ] `--model turbo` uses the turbo variant (verified via API response or faster generation)
- [ ] Invalid model name produces a clear error listing valid options

---

#### US-3.5: Sounds Mode

**As a** musician, **I want** to generate short audio samples (loops, one-shots, sound effects), **so that** I can create building blocks for my productions.

**Description:**
Sounds mode generates short audio clips rather than full songs. Supports one-shot and loop types with BPM and key constraints for DAW compatibility.

**Functional Requirements:**
- `acemusic sounds "deep punchy kick drum" --type one-shot` generates a one-shot sample
- `acemusic sounds "ambient pad" --type loop --bpm 120 --key "A minor"` generates a seamless loop
- `--type` is required: `one-shot` or `loop`
- Duration is short (seconds, not minutes)
- Loop clips include tempo metadata

**Acceptance Criteria:**
- [ ] `acemusic sounds "hi-hat pattern" --type loop --bpm 140` produces a loopable audio file
- [ ] One-shot and loop types produce audibly different results
- [ ] BPM and key constraints are applied to loops

---

**Stage 3 Completion Criteria:**
- All generation parameters are exposed and functional
- Model selection works
- Sounds mode works
- Output format selection works
- All parameters validated with clear error messages
- Tests cover parameter combinations and edge cases

---

### Stage 4: Workspace Management CLI

**Overview:** Introduce local workspace and clip management — the organizational backbone. Musicians can create projects, track their generated clips with metadata, and save reusable presets. Metadata is stored in a local SQLite database.

---

#### US-4.1: Workspace CRUD

**As a** musician, **I want** to organize my clips into workspaces (projects), **so that** I can keep different songs or albums separate.

**Description:**
Workspaces are named containers for clips. A default workspace is created automatically. The active workspace determines where new generations are saved.

**Functional Requirements:**
- `acemusic workspace create "My Album"` creates a new workspace
- `acemusic workspace list` shows all workspaces with clip counts
- `acemusic workspace switch "My Album"` sets the active workspace
- `acemusic workspace rename "My Album" "Debut LP"` renames a workspace
- `acemusic workspace delete "Debut LP"` removes a workspace (with confirmation if non-empty)
- Audio files stored in `~/.acemusic/workspaces/{workspace_id}/clips/`

**Acceptance Criteria:**
- [ ] Creating, listing, switching, renaming, and deleting workspaces all work
- [ ] New generations are saved to the active workspace
- [ ] Deleting a non-empty workspace requires confirmation
- [ ] Default workspace exists on first run

---

#### US-4.2: Clip Metadata Storage

**As a** musician, **I want** my clips' metadata (title, BPM, key, style, seed, lineage) stored persistently, **so that** I can search and recall my work across sessions.

**Description:**
A local SQLite database stores clip metadata alongside the audio files. Every generation automatically records its parameters and output details.

**Functional Requirements:**
- SQLite database at `~/.acemusic/metadata.db`
- Clip record fields: id, title, workspace_id, file_path, format, duration, bpm, key, style_tags, lyrics, vocal_language, model, seed, inference_steps, parent_clip_id, generation_mode, created_at
- `acemusic clips list` shows clips in the active workspace (title, duration, BPM, model, date)
- `acemusic clips info <clip_id>` shows full metadata for a clip
- `acemusic clips rename <clip_id> "New Title"` renames a clip
- `acemusic clips delete <clip_id>` removes clip and its audio file
- `acemusic clips search --style "rock" --bpm-range 100-140` filters clips

**Acceptance Criteria:**
- [ ] After generation, clip metadata is queryable via `acemusic clips list`
- [ ] `acemusic clips info` shows all recorded parameters including seed
- [ ] Search filters work (style, BPM range, key, model, date range)
- [ ] Metadata persists across CLI sessions

---

#### US-4.3: Style and Lyrics Presets

**As a** musician, **I want** to save and reuse combinations of style tags, lyrics, and parameters, **so that** I can quickly regenerate with consistent settings.

**Description:**
Presets capture a snapshot of generation parameters (style, lyrics, BPM, key, model, etc.) that can be recalled by name.

**Functional Requirements:**
- `acemusic preset save "Dark Electro" --from-last` saves the parameters from the last generation
- `acemusic preset save "Chill Vibes" --style "lo-fi, chill" --bpm 85 --key "D minor"` saves explicit parameters
- `acemusic preset list` shows all saved presets
- `acemusic preset load "Dark Electro"` displays the preset's parameters
- `acemusic generate "new song" --preset "Dark Electro"` applies the preset (individual flags override preset values)
- `acemusic preset delete "Dark Electro"` removes a preset

**Acceptance Criteria:**
- [ ] Saving and loading presets works end-to-end
- [ ] `--preset` applies all saved parameters to generation
- [ ] Explicit flags (e.g., `--bpm 140`) override preset values
- [ ] Presets persist across sessions

---

#### US-4.4: Clip Import and Upload

**As a** musician, **I want** to import existing audio files into my workspace, **so that** I can use them as references for covers, remixes, and mashups.

**Description:**
Import audio files from the local filesystem into the workspace, registering them in the metadata database for use in later stages (cover, remix, mashup).

**Functional Requirements:**
- `acemusic import /path/to/song.wav` copies the file into the active workspace and creates a metadata record
- Accepted formats: WAV, FLAC, MP3, OGG, AAC, AIFF
- Auto-detect BPM and key if possible (using audio analysis library)
- `--title "My Reference"` sets the clip title
- Imported clips are tagged with `source: upload` in metadata

**Acceptance Criteria:**
- [ ] Importing a WAV file copies it to the workspace and creates a metadata record
- [ ] `acemusic clips list` shows the imported clip with `upload` badge
- [ ] BPM detection produces a reasonable estimate for a rhythmic track

---

**Stage 4 Completion Criteria:**
- Workspaces and clips are fully manageable from CLI
- SQLite metadata persists across sessions
- Presets are saveable, loadable, and applicable to generation
- Audio import works for all major formats
- All features covered by tests

---

### Stage 5: Audio Processing CLI

**Overview:** Add non-generative audio processing — crop, speed adjustment, stem separation, MIDI extraction, and basic remastering. These operations transform existing clips without calling the AI generation model (except stems/remaster which may use AI-based processing).

---

#### US-5.1: Crop and Trim

**As a** musician, **I want** to trim a clip to a specific time range, **so that** I can isolate the best section of a generation.

**Description:**
Crop creates a new clip from a selected time range of an existing clip. The original is preserved. Supports optional fade-in/fade-out.

**Functional Requirements:**
- `acemusic crop <clip_id> --start 10s --end 45s` creates a new clip
- `--fade-in 0.5s --fade-out 1s` applies fades
- `--snap-to-beat` rounds start/end to nearest beat boundary (uses BPM from metadata)
- New clip is registered in metadata with `generation_mode: crop` and `parent_clip_id`
- Original clip is unchanged

**Acceptance Criteria:**
- [ ] Cropped clip has the correct duration (end - start)
- [ ] Fade-in/fade-out are audible in the output
- [ ] Original clip still exists unchanged
- [ ] Metadata records the parent-child relationship

---

#### US-5.2: Speed Adjustment

**As a** musician, **I want** to change a clip's tempo without affecting pitch, **so that** I can make it fit a different BPM.

**Description:**
Time-stretch a clip by a multiplier or to a target BPM. Pitch is preserved by default but can optionally be shifted.

**Functional Requirements:**
- `acemusic speed <clip_id> --multiplier 1.5` speeds up by 50%
- `acemusic speed <clip_id> --target-bpm 140` calculates multiplier from clip's stored BPM
- `--preserve-pitch` (default: on) maintains original pitch
- `--preserve-pitch off` allows pitch to shift with speed
- Range: 0.5x–2.0x
- Creates a new clip; original preserved

**Acceptance Criteria:**
- [ ] `--multiplier 2.0` produces a clip half the original duration
- [ ] `--target-bpm` correctly calculates the multiplier from stored BPM
- [ ] Pitch is preserved by default
- [ ] Values outside 0.5–2.0 produce a validation error

---

#### US-5.3: Stem Separation

**As a** musician, **I want** to separate a clip into individual stems (vocals, drums, bass, other), **so that** I can remix individual parts or export them to my DAW.

**Description:**
Uses AI-based source separation to isolate four stems from a full mix. This is a prerequisite for MIDI extraction (which works best on isolated stems) and DAW export.

**Functional Requirements:**
- `acemusic stems <clip_id>` produces 4 WAV files: vocals, drums, bass, other
- Output saved to workspace in a `stems/` subdirectory
- Each stem registered as a child clip in metadata with appropriate labels
- `--output-format wav|flac` controls stem output format (default: WAV 48kHz/24-bit)
- Progress indicator (separation can take 30–120 seconds)
- Library: likely `demucs` or ACE-Step's Extract mode

**Acceptance Criteria:**
- [ ] Four stem files are produced and playable
- [ ] Stems re-summed approximate the original mix (within acceptable tolerance)
- [ ] Each stem is registered in metadata with correct labels
- [ ] Processing completes within 2 minutes for a 3-minute clip

---

#### US-5.4: MIDI Extraction

**As a** musician, **I want** to extract MIDI data from a clip, **so that** I can import melodies, chords, and rhythms into my DAW as editable MIDI.

**Description:**
Analyzes audio and transcribes detected melodic, harmonic, and rhythmic content to standard MIDI files. Works best on isolated stems rather than full mixes.

**Functional Requirements:**
- `acemusic midi <clip_id>` produces MIDI files: melody.mid, chords.mid, drums.mid, bass.mid
- `--from-stems` uses previously separated stems for better accuracy
- Output: Standard MIDI Type 1, channels: 1=Melody, 2=Chords, 10=Drums, 3=Bass
- Tempo map and time signature embedded in MIDI header
- MIDI CC data (expression, modulation, sustain) included where detected
- Library: `basic-pitch`, `omnizart`, or similar

**Acceptance Criteria:**
- [ ] MIDI files are produced and importable into a DAW
- [ ] `--from-stems` produces more accurate MIDI than full-mix extraction
- [ ] Tempo map in MIDI matches the clip's BPM metadata
- [ ] At least melody extraction produces musically recognizable output

---

#### US-5.5: Basic Remaster

**As a** musician, **I want** a one-command audio enhancement, **so that** my clips sound more polished without leaving the terminal.

**Description:**
Applies AI-based or DSP-based audio enhancement: dynamic range optimization, EQ balancing, stereo enhancement, and loudness normalization. This is distinct from the external mastering pipeline (Stage 12) — it's a quick, local operation.

**Functional Requirements:**
- `acemusic remaster <clip_id>` produces an enhanced version
- Processing: loudness normalization (target -14 LUFS), basic EQ, stereo widening, dynamic range compression
- Creates a new clip with `generation_mode: remaster` and `parent_clip_id`
- Original preserved
- `--target-lufs -12` allows custom loudness target

**Acceptance Criteria:**
- [ ] Remastered clip is louder and more balanced than the original
- [ ] Loudness measures approximately at the target LUFS
- [ ] Original clip is unchanged
- [ ] Processing completes in under 30 seconds for a 3-minute clip

---

**Stage 5 Completion Criteria:**
- All five audio processing commands work and produce correct output
- Each operation creates new clips (non-destructive)
- Parent-child lineage is tracked in metadata
- Stems and MIDI are usable in external DAWs
- Tests verify audio properties (duration, format, channel count)

---

### Stage 6: Iterative Generation CLI

**Overview:** Add AI-powered generation modes that build on existing clips — extend, cover, remix/repaint, mashup, sample, add vocal, replace section, and auto-assembled full songs. These are the creative iteration loops that make the platform powerful.

---

#### US-6.1: Extend a Clip

**As a** musician, **I want** to extend a clip by generating additional audio that continues the song, **so that** I can build a full song from a short seed.

**Description:**
Generates new audio that picks up where the clip ends, maintaining tempo, key, and timbre continuity. Can be chained repeatedly.

**Functional Requirements:**
- `acemusic extend <clip_id> --duration 60s` generates 60 seconds of continuation
- `--from end` (default) or `--from 45s` to extend from a specific timestamp
- `--style "add a bridge feel"` optional style override for the extension
- `--lyrics "[Bridge]\nWe cross the river..."` optional lyrics for the extended section
- Result is a new clip containing original + extension
- Lineage tracked in metadata

**Acceptance Criteria:**
- [ ] Extended clip is longer than the original by approximately the requested duration
- [ ] Musical continuity is audible (tempo, key, timbre match)
- [ ] Chaining two extends produces a valid, longer clip
- [ ] Style overrides audibly affect the extension

---

#### US-6.2: Cover Mode

**As a** musician, **I want** to create a cover version of a clip in a different style, **so that** I can explore how a song sounds in another genre.

**Description:**
Preserves the melodic structure of the source while restyling instrumentation, arrangement, and optionally the vocal performance.

**Functional Requirements:**
- `acemusic cover <clip_id> --style "jazz piano trio"`
- `--voice <voice_id>` optional custom voice (if available in later stages)
- `--lyrics "new lyrics"` optional lyrics override (melody preserved, words changed)
- Source clip's melody contour is retained in the output
- New clip created with `generation_mode: cover`

**Acceptance Criteria:**
- [ ] Cover output is recognizably derived from the source melody
- [ ] Style is audibly different from the original
- [ ] Lyrics override changes the words while keeping the melodic feel

---

#### US-6.3: Remix and Repaint

**As a** musician, **I want** to remix a full clip or repaint a specific section, **so that** I can iterate on parts of a song without regenerating the whole thing.

**Description:**
Remix restyles the entire clip. Repaint regenerates only a selected time range while preserving surrounding audio.

**Functional Requirements:**
- `acemusic remix <clip_id> --style "lo-fi bedroom pop"` restyles the entire clip
- `acemusic repaint <clip_id> --start 10s --end 20s --prompt "add a guitar solo here"` regenerates a section
- Repaint blends seamlessly with surrounding audio (crossfade at boundaries)
- Both create new clips with lineage tracking

**Acceptance Criteria:**
- [ ] Remix produces a full-length clip with the new style applied
- [ ] Repaint changes only the specified time range; surrounding audio is intact
- [ ] Transitions at repaint boundaries are smooth (no audible clicks/jumps)

---

#### US-6.4: Mashup

**As a** musician, **I want** to combine elements from multiple clips into one, **so that** I can create hybrid compositions.

**Description:**
Takes 2+ source clips and generates a new clip that blends their elements. Supports multiple blend strategies.

**Functional Requirements:**
- `acemusic mashup <clip_id_1> <clip_id_2> --blend layered` blends concurrently
- `--blend sequential` arranges sources section-by-section
- `--blend ai-guided` lets the model decide how to combine
- `--style "unifying style"` optional style for cohesion
- Auto-aligns BPM and key where possible

**Acceptance Criteria:**
- [ ] Mashup of two clips produces a single new clip
- [ ] The three blend modes produce audibly different results
- [ ] BPM/key alignment is attempted (clips at different tempos are harmonized)

---

#### US-6.5: Sample from Song

**As a** musician, **I want** to extract a sample from a clip and build a new song around it, **so that** I can use short hooks or loops as creative seeds.

**Description:**
Selects a time range from a source clip, extracts it as a sample, and uses it as a constraint in a new generation.

**Functional Requirements:**
- `acemusic sample <clip_id> --start 4s --end 8s --role loop-bed --prompt "build a chill track around this"`
- `--role` options: `loop-bed`, `intro-outro`, `rhythmic-element`, `melodic-hook`
- New song incorporates the sample organically
- Attribution metadata links back to the source clip

**Acceptance Criteria:**
- [ ] Sample is audible in the generated output
- [ ] Different roles produce different placements of the sample
- [ ] Metadata includes attribution to the source clip and time range

---

#### US-6.6: Add Vocal and Replace Section

**As a** musician, **I want** to add vocals to an instrumental clip or replace a section of a song, **so that** I can refine specific parts of my composition.

**Description:**
Add Vocal layers a vocal performance onto an instrumental. Replace Section regenerates a specific time range with new instructions.

**Functional Requirements:**
- `acemusic add-vocal <clip_id> --lyrics "..." --voice default --style "breathy, soulful"`
- `acemusic replace <clip_id> --start 30s --end 45s --prompt "make this section more energetic"`
- `--lock-context` ensures replacement blends with surrounding audio (default: on)
- Both create new clips with lineage

**Acceptance Criteria:**
- [ ] Add-vocal produces a clip with vocals layered on the instrumental
- [ ] Replace section changes only the target time range
- [ ] Surrounding audio is preserved with smooth transitions

---

#### US-6.7: Get Full Song (Auto-Extend)

**As a** musician, **I want** to automatically build a full-length song from a short seed clip, **so that** I don't have to manually chain extends.

**Description:**
Automatically extends a short clip (~30-60s) into a complete song (~3-4 minutes) by planning a song structure and executing sequential extends.

**Functional Requirements:**
- `acemusic full-song <clip_id>` triggers the auto-extend pipeline
- Plans a structure: intro → verse → chorus → verse → chorus → bridge → outro
- Executes sequential extends with appropriate style/lyrics per section
- `--target-duration 240` sets the target length (default: ~3-4 minutes)
- Each section is reviewable after generation (confirmation prompt before continuing)
- `--auto` skips confirmation prompts and builds the entire song
- Final output is a single assembled clip

**Acceptance Criteria:**
- [ ] Produces a clip of approximately the target duration
- [ ] Song has audible structural variety (not just repetition)
- [ ] Interactive mode pauses for confirmation between sections
- [ ] `--auto` mode completes without user intervention

---

**Stage 6 Completion Criteria:**
- All seven iterative generation modes work via CLI
- Each mode creates properly tracked clips with lineage
- Musical continuity is maintained across extends and sections
- Tests cover each mode with at least one integration test against real ACE-Step
- Clips from Stage 4 (imported) can be used as sources

---

### Stage 7: DAW Export CLI

**Overview:** Package clips, stems, and MIDI into DAW-ready export bundles. After this stage, a musician can generate music in the CLI and drop the results directly into Cubase, Ableton, or any other DAW.

---

#### US-7.1: Single Clip Export

**As a** musician, **I want** to export a clip in my preferred audio format, **so that** I can use it in external tools.

**Description:**
Export a single clip as WAV, FLAC, or MP3 with optional format conversion.

**Functional Requirements:**
- `acemusic export <clip_id> --format wav` exports as WAV (48kHz, 24-bit)
- `--format wav32` exports as 32-bit float WAV
- `--format flac` exports as lossless FLAC
- `--format mp3` exports as MP3 (320kbps)
- `--output /path/to/file.wav` specifies output path
- Default output: current directory with clip title as filename

**Acceptance Criteria:**
- [ ] Each format produces a valid, playable file
- [ ] WAV output is 48kHz/24-bit
- [ ] File is named after the clip title by default

---

#### US-7.2: DAW Bundle Export

**As a** musician, **I want** to export a clip as a complete DAW-ready bundle (stems + MIDI + metadata), **so that** I can import everything into Cubase and continue production.

**Description:**
Creates a ZIP archive containing audio stems, MIDI files, project metadata JSON, and artwork. The bundle is structured for easy import into any professional DAW.

**Functional Requirements:**
- `acemusic export <clip_id> --format daw` produces a ZIP archive
- ZIP structure:
  ```
  SongTitle_Export/
  ├── audio/
  │   ├── full_mix.wav
  │   ├── vocals.wav
  │   ├── drums.wav
  │   ├── bass.wav
  │   └── other.wav
  ├── midi/
  │   ├── melody.mid
  │   ├── chords.mid
  │   ├── drums.mid
  │   └── bass.mid
  ├── project.json
  └── artwork.jpg (placeholder if no cover art)
  ```
- project.json includes: BPM, key, time signature, duration, stem references, MIDI channel assignments, markers, lyrics, style tags, model, seed
- Stems are auto-generated if not already separated (triggers stem separation)
- MIDI is auto-extracted if not already done

**Acceptance Criteria:**
- [ ] ZIP contains all expected files in the correct directory structure
- [ ] project.json is valid JSON with all metadata fields populated
- [ ] MIDI files are Type 1 with correct channel assignments
- [ ] Stems are time-aligned and equal length
- [ ] Full mix is included alongside stems

---

#### US-7.3: Batch Export

**As a** musician, **I want** to export all clips in a workspace at once, **so that** I can quickly package an entire project.

**Description:**
Export multiple clips in one command, with consistent naming and optional format selection.

**Functional Requirements:**
- `acemusic export --workspace "My Album" --format wav` exports all clips as WAVs
- `acemusic export --workspace "My Album" --format daw` exports all clips as DAW bundles
- `--output /path/to/dir` specifies output directory
- Each clip gets its own file/ZIP named by title
- Summary output: number of clips exported, total size, output location

**Acceptance Criteria:**
- [ ] All clips in the workspace are exported
- [ ] Each clip has a distinct, descriptively-named file
- [ ] Summary shows count and total size

---

#### US-7.4: Stems-Only and MIDI-Only Export

**As a** musician, **I want** to export just the stems or just the MIDI for a clip, **so that** I can get exactly what I need without the full bundle.

**Description:**
Targeted export options for when you only need audio stems or MIDI data.

**Functional Requirements:**
- `acemusic export <clip_id> --format stems` exports only the 4 stem WAV files
- `acemusic export <clip_id> --format midi` exports only the 4 MIDI files
- Stems are auto-separated if needed; MIDI is auto-extracted if needed

**Acceptance Criteria:**
- [ ] `--format stems` produces 4 WAV files (no MIDI, no ZIP)
- [ ] `--format midi` produces 4 MIDI files (no audio)
- [ ] Auto-separation/extraction is triggered when needed

---

**Stage 7 Completion Criteria:**
- All export formats work (wav, flac, mp3, wav32, daw, stems, midi)
- DAW bundle ZIP matches the specified structure
- Batch export handles entire workspaces
- Project metadata JSON is comprehensive and valid
- Tests verify file formats, ZIP structure, and metadata correctness
- **End-to-end CLI workflow validated:** generate → edit → stems → MIDI → DAW export

---

## Layer 2: Platform API

*Goal: Wrap the CLI foundation in a FastAPI service with authentication, async job processing, compute routing, mastering, distribution, and export APIs. After this layer, the platform is fully operational via HTTP — any client (web, mobile, plugin) can consume it.*

---

### Stage 8: API Foundation

**Overview:** Stand up the FastAPI project with versioned routes, MongoDB persistence, OAuth2 authentication, user management, and file storage. This stage replaces the CLI's local SQLite with a shared database and adds multi-user support. Every subsequent API stage builds on these primitives.

---

#### US-8.1: FastAPI Project and Versioned Routes

**As a** developer, **I want** a properly structured FastAPI application with versioned routes and auto-generated docs, **so that** I have a stable API surface that clients can depend on from day one.

**Description:**
Bootstrap the `api/` directory inside the monorepo with a FastAPI app, versioned under `/api/v1/`. Include health check, CORS configuration for local and future web clients, and OpenAPI/Swagger docs at `/docs`.

**Functional Requirements:**
- FastAPI app with `/api/v1/` route prefix
- `GET /api/v1/health` returns server status, version, and uptime
- CORS middleware configured with allowed origins (localhost initially, configurable via env)
- OpenAPI docs available at `/docs` and `/redoc`
- Environment-based configuration using pydantic-settings (`.env` file)
- Uvicorn runner with reload for development

**Acceptance Criteria:**
- [ ] `uv run uvicorn acemusic.api.main:app --reload` starts without error
- [ ] `GET /api/v1/health` returns 200 with `{"status": "ok", "version": "..."}`
- [ ] `/docs` renders the Swagger UI with all registered endpoints
- [ ] CORS headers are present in responses for configured origins
- [ ] Requests to `/api/v2/` return 404 (no version leak)

---

#### US-8.2: MongoDB Connection and Core Collections

**As a** developer, **I want** MongoDB connected with schemas for songs, users, and workspaces, **so that** the API has a persistent, scalable data layer from the start.

**Description:**
Establish the MongoDB connection using Motor (async driver) with Beanie or raw Motor documents. Define the core collections that the platform needs: users, workspaces, clips, and jobs. Seed a default workspace on user creation.

**Functional Requirements:**
- Async MongoDB connection via Motor with connection pooling
- Collections: `users`, `workspaces`, `clips`, `jobs`
- Beanie ODM models (or Pydantic + Motor) for each collection with validation
- Database name and connection string configurable via environment variables
- Startup event verifies connectivity; fails fast if MongoDB is unreachable
- Indexes on: `clips.workspace_id`, `clips.user_id`, `clips.created_at`, `users.email`

**Acceptance Criteria:**
- [ ] Application connects to MongoDB on startup and logs success
- [ ] If MongoDB is down, the app exits with a clear error (not a silent hang)
- [ ] Collections are created with defined indexes on first run
- [ ] CRUD operations on each collection work from test fixtures

---

#### US-8.3: OAuth2 Authentication and JWT Tokens

**As a** musician, **I want to** sign in with my Google or Discord account, **so that** I can access my workspaces and clips securely without creating yet another password.

**Description:**
Implement OAuth2 login via Google and Discord identity providers. On successful auth, issue a JWT access token (short-lived) and refresh token (long-lived). All subsequent API requests require a valid Bearer token.

**Functional Requirements:**
- OAuth2 authorization code flow for Google and Discord
- JWT access token (15-minute expiry) and refresh token (7-day expiry)
- `POST /api/v1/auth/login/{provider}` initiates OAuth flow
- `POST /api/v1/auth/callback/{provider}` handles the redirect
- `POST /api/v1/auth/refresh` exchanges a refresh token for a new access token
- `POST /api/v1/auth/logout` revokes the refresh token
- Token payload includes: user_id, email, subscription_tier
- Protected routes return 401 for missing/invalid tokens

**Acceptance Criteria:**
- [ ] Google OAuth login returns a valid JWT on success
- [ ] Discord OAuth login returns a valid JWT on success
- [ ] Expired access tokens return 401; refresh token exchange returns a new access token
- [ ] Invalid or revoked refresh tokens return 401
- [ ] All `/api/v1/` routes (except health, auth) return 401 without a Bearer token

---

#### US-8.4: User Registration and Profile CRUD

**As a** musician, **I want to** create and manage my profile (display name, handle, avatar, bio, style tags), **so that** my identity is established on the platform.

**Description:**
On first OAuth login, a user record is created automatically with sensible defaults. The user can then update their profile. Handles must be unique. Profile data is stored in the `users` collection.

**Functional Requirements:**
- Auto-create user on first login (email, provider, default display name from OAuth)
- `GET /api/v1/users/me` returns the authenticated user's profile
- `PATCH /api/v1/users/me` updates display name, handle, bio, style tags
- `PUT /api/v1/users/me/avatar` uploads a profile image
- Handle uniqueness enforced at the database level
- Handle format validation: alphanumeric + hyphens, 3-30 characters

**Acceptance Criteria:**
- [ ] First login creates a user record with data from the OAuth provider
- [ ] `GET /api/v1/users/me` returns the full profile for the authenticated user
- [ ] `PATCH /api/v1/users/me` updates fields and returns the updated profile
- [ ] Duplicate handle returns 409 Conflict
- [ ] Invalid handle format returns 422 with a descriptive error

---

#### US-8.5: File Storage Abstraction

**As a** developer, **I want** a file storage layer that works with local filesystem now and S3-compatible storage later, **so that** audio files are managed through a single interface regardless of deployment.

**Description:**
Create a storage abstraction with a common interface (upload, download, delete, get_url) and two implementations: LocalStorage (for development) and S3Storage (for production). All audio file operations go through this layer.

**Functional Requirements:**
- `StorageBackend` abstract class with methods: `upload(path, data)`, `download(path)`, `delete(path)`, `get_url(path)`
- `LocalStorage` implementation storing files under a configurable directory
- `S3Storage` implementation using `boto3` with S3-compatible endpoints (AWS, MinIO, Backblaze B2)
- Backend selection via `STORAGE_BACKEND=local|s3` environment variable
- Files organized as: `{user_id}/{workspace_id}/clips/{clip_id}.{format}`
- Signed URLs for S3 downloads (configurable expiry)

**Acceptance Criteria:**
- [ ] `LocalStorage` uploads and downloads files correctly
- [ ] `S3Storage` uploads and downloads files correctly (tested with MinIO or localstack)
- [ ] Switching `STORAGE_BACKEND` between `local` and `s3` requires no code changes in callers
- [ ] `get_url` returns a local file path for LocalStorage and a signed URL for S3Storage
- [ ] Deleting a file removes it from storage and returns no error on missing files

---

**Stage 8 Completion Criteria:**
- FastAPI app starts and serves versioned routes at `/api/v1/`
- MongoDB is connected with indexed collections for users, workspaces, clips, and jobs
- OAuth2 login works for Google and Discord, issuing JWT tokens
- User profile CRUD is fully functional
- File storage abstraction works with local filesystem
- Health endpoint, CORS, and OpenAPI docs are operational
- All endpoints are covered by integration tests against a real MongoDB instance

---

### Stage 9: Generation API

**Overview:** Expose the core music generation pipeline over HTTP. This stage wraps the CLI's generate, workspace, clip, and preset logic in REST endpoints with async job processing and credit deduction. After this stage, any HTTP client can submit prompts, poll for results, and manage clips.

---

#### US-9.1: Generation Endpoint

**As a** musician, **I want to** submit a generation request via the API with all creative parameters, **so that** I can generate music from any client — not just the CLI.

**Description:**
The generation endpoint accepts the full parameter set (prompt, style, lyrics, BPM, key, duration, model, seed, inference steps, etc.) and returns a job ID for async tracking. Supports all three creation modes: text-to-music, sounds (one-shot/loop), and advanced mode with separate style/lyrics fields.

**Functional Requirements:**
- `POST /api/v1/generate` accepts a JSON body with all generation parameters
- Parameters: prompt, style, lyrics, vocal_language, instrumental, bpm, key, time_signature, duration, seed, inference_steps, model, weirdness, style_influence, format, thinking, mode (song|sound), sound_type (one-shot|loop)
- Validates all parameters (ranges, enums) and returns 422 on invalid input
- Creates a job record in the `jobs` collection with status `queued`
- Returns `{"job_id": "...", "status": "queued", "estimated_time_seconds": N}`
- Job is dispatched to the async task queue for processing

**Acceptance Criteria:**
- [ ] `POST /api/v1/generate` with a valid body returns 202 with a job_id
- [ ] Invalid parameters (e.g., BPM of 999) return 422 with field-level errors
- [ ] Job record is created in MongoDB with status `queued`
- [ ] Unauthenticated requests return 401
- [ ] All three modes (song, sound one-shot, sound loop) are accepted

---

#### US-9.2: Async Job Queue and Processing

**As a** developer, **I want** generation requests processed asynchronously with status tracking, **so that** clients are not blocked during the 5-60 second generation time.

**Description:**
Implement an async job processor that picks up queued jobs, forwards them to the ACE-Step-1.5 API, polls for completion, stores the resulting audio, and updates the job status. Initially uses asyncio tasks; designed for later migration to Redis/Celery.

**Functional Requirements:**
- Job processor runs as background tasks within the FastAPI process
- Job lifecycle: `queued` -> `processing` -> `completed` | `failed`
- On completion: audio files stored via the storage abstraction, clip records created in MongoDB
- On failure: error message stored in the job record, status set to `failed`
- Concurrency limit configurable (default: 2 concurrent jobs)
- `GET /api/v1/jobs/{id}/status` returns current status, progress, and result (clip IDs when complete)

**Acceptance Criteria:**
- [ ] A queued job transitions to `processing` and then `completed` when ACE-Step is running
- [ ] `GET /api/v1/jobs/{id}/status` returns the current state at each lifecycle phase
- [ ] Completed jobs include clip IDs and audio URLs in the response
- [ ] Failed jobs include an error message
- [ ] Two concurrent jobs process without deadlock or corruption

---

#### US-9.3: Clip Audio Retrieval

**As a** musician, **I want to** stream or download my generated audio clips via the API, **so that** I can listen to results from any client.

**Description:**
Serve audio files with proper content-type headers, supporting both full download and streaming via HTTP range requests.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/audio` returns the audio file
- Content-Type set correctly based on format (audio/wav, audio/flac, audio/mpeg, etc.)
- Support HTTP Range headers for streaming/seeking
- `?format=mp3` query param for on-the-fly format conversion (optional, WAV by default)
- 404 if clip does not exist or does not belong to the authenticated user
- 403 if clip belongs to another user and is private

**Acceptance Criteria:**
- [ ] `GET /api/v1/clips/{id}/audio` returns a playable audio file with correct Content-Type
- [ ] Range request returns 206 Partial Content with the requested byte range
- [ ] Requesting another user's private clip returns 403
- [ ] Requesting a non-existent clip returns 404

---

#### US-9.4: Workspace and Clip CRUD

**As a** musician, **I want to** create, list, update, and delete workspaces and clips via the API, **so that** I can organize my music library from any client.

**Description:**
Expose the workspace and clip management operations as REST endpoints. Clips support search, filtering, and sorting. A default workspace is created when a new user is registered.

**Functional Requirements:**
- Workspace endpoints: `POST /api/v1/workspaces`, `GET /api/v1/workspaces`, `GET /api/v1/workspaces/{id}`, `PATCH /api/v1/workspaces/{id}`, `DELETE /api/v1/workspaces/{id}`
- Clip endpoints: `GET /api/v1/clips` (list with pagination), `GET /api/v1/clips/{id}`, `PATCH /api/v1/clips/{id}`, `DELETE /api/v1/clips/{id}`
- Clip list supports: `?workspace_id=`, `?search=`, `?style=`, `?bpm_min=`, `?bpm_max=`, `?key=`, `?model=`, `?sort=newest|oldest`, `?page=`, `?per_page=`
- Deleting a workspace with clips requires `?force=true` or returns 409
- All endpoints scoped to the authenticated user

**Acceptance Criteria:**
- [ ] Full CRUD lifecycle works for workspaces (create, list, get, update, delete)
- [ ] Full CRUD lifecycle works for clips (list, get, update, delete)
- [ ] Clip search filters by style, BPM range, key, and model
- [ ] Pagination returns correct page counts and respects per_page limits
- [ ] Deleting a non-empty workspace without `?force=true` returns 409

---

#### US-9.5: Preset CRUD

**As a** musician, **I want to** save and load generation presets via the API, **so that** I can reuse my favorite parameter combinations across sessions and devices.

**Description:**
Presets store a named snapshot of generation parameters. They can be applied when submitting a generation request by including a preset_id, with individual parameters overriding preset values.

**Functional Requirements:**
- `POST /api/v1/presets` creates a preset with name and parameter snapshot
- `GET /api/v1/presets` lists all presets for the authenticated user
- `GET /api/v1/presets/{id}` returns a single preset
- `PATCH /api/v1/presets/{id}` updates a preset
- `DELETE /api/v1/presets/{id}` deletes a preset
- `POST /api/v1/generate` accepts an optional `preset_id`; explicit parameters override preset values

**Acceptance Criteria:**
- [ ] Creating and retrieving a preset returns all saved parameters
- [ ] Generating with a preset_id applies the preset's parameters
- [ ] Explicit parameters in the generate request override preset values
- [ ] Presets are scoped to the authenticated user (no cross-user access)

---

#### US-9.6: Credit Deduction

**As a** musician, **I want** credits deducted when I generate music, **so that** the platform can enforce usage limits based on my subscription tier.

**Description:**
Each generation consumes credits from the user's balance. The generation endpoint checks the user's credit balance before processing and rejects requests when credits are insufficient. Credit costs vary by action type.

**Functional Requirements:**
- User record includes `credits_balance` and `subscription_tier` fields
- `POST /api/v1/generate` checks credit balance before queuing the job
- Credit cost: 1 credit per song generation (2 clips), 0.5 credits per sound generation
- Insufficient credits return 402 Payment Required with remaining balance
- `GET /api/v1/users/me/credits` returns current balance and usage history
- Credits are deducted atomically when the job is queued (not on completion)

**Acceptance Criteria:**
- [ ] Generation with sufficient credits succeeds and reduces the balance
- [ ] Generation with insufficient credits returns 402
- [ ] Credit balance is visible via `GET /api/v1/users/me/credits`
- [ ] Concurrent generation requests do not cause double-deduction (atomic update)

---

**Stage 9 Completion Criteria:**
- Generation endpoint accepts all parameter modes and returns async job IDs
- Job queue processes requests and tracks status through completion or failure
- Clip audio is retrievable via streaming-capable endpoints
- Workspace and clip CRUD with search/filter/sort is fully functional
- Presets are saveable and applicable to generation
- Credit deduction enforces usage limits
- All endpoints covered by integration tests against real MongoDB and ACE-Step

---

### Stage 10: Audio Processing & Iterative Generation API

**Overview:** Expose all audio editing and iterative generation modes as API endpoints. This stage wraps the CLI's crop, speed, stems, MIDI, remaster, extend, cover, remix, repaint, mashup, sample, add-vocal, and full-song operations behind REST endpoints with background task processing and lineage tracking.

---

#### US-10.1: Audio Editing Endpoints

**As a** musician, **I want to** crop, adjust speed, and remaster clips via the API, **so that** I can refine my music from any client without using the CLI.

**Description:**
Expose the non-generative audio processing operations as POST endpoints. Each operation creates a new clip (non-destructive) with lineage tracking. Operations run as background tasks since they may take seconds to minutes.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/crop` with `{start, end, fade_in, fade_out, snap_to_beat}`
- `POST /api/v1/clips/{id}/speed` with `{multiplier, target_bpm, preserve_pitch}`
- `POST /api/v1/clips/{id}/remaster` with `{target_lufs}` (optional, default -14)
- All three return a job_id for async tracking (reuses the job queue from Stage 9)
- Resulting clips include `parent_clip_ids` and `generation_mode` in metadata
- Original clips are never modified

**Acceptance Criteria:**
- [ ] Crop creates a new clip with the correct duration (end - start)
- [ ] Speed adjustment with `multiplier: 2.0` produces a clip half the original duration
- [ ] Remaster produces a clip with loudness approximately at the target LUFS
- [ ] All operations return job IDs and track status via `GET /api/v1/jobs/{id}/status`
- [ ] Original clips are unchanged after any operation

---

#### US-10.2: Stems and MIDI Extraction Endpoints

**As a** musician, **I want to** extract stems and MIDI from clips via the API, **so that** I can get individual parts for remixing or DAW import.

**Description:**
Stem separation and MIDI extraction are computationally intensive and run as background tasks. Results are stored as child clips (stems) or downloadable files (MIDI).

**Functional Requirements:**
- `POST /api/v1/clips/{id}/stems` triggers stem separation (vocals, drums, bass, other)
- `POST /api/v1/clips/{id}/midi` triggers MIDI extraction (melody, chords, drums, bass)
- Both return a job_id for async tracking
- Stem results: 4 new clip records linked to the parent with appropriate labels
- MIDI results: downloadable MIDI files stored in the storage layer
- `GET /api/v1/clips/{id}/stems` returns the stem clip IDs if separation has been done
- `GET /api/v1/clips/{id}/midi` returns download URLs for extracted MIDI files

**Acceptance Criteria:**
- [ ] Stem separation produces 4 playable audio clips linked to the parent
- [ ] MIDI extraction produces downloadable .mid files
- [ ] Re-requesting stems/MIDI for a clip that already has them returns cached results
- [ ] Job status is trackable through completion
- [ ] Stems are time-aligned and equal length

---

#### US-10.3: Iterative Generation Endpoints

**As a** musician, **I want to** extend, cover, remix, repaint, mashup, sample from, and add vocals to clips via the API, **so that** I can iteratively build and refine songs from any client.

**Description:**
Expose all AI-powered iterative generation modes as POST endpoints. Each takes a source clip (or multiple clips for mashup) plus mode-specific parameters and produces a new clip with lineage tracking.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/extend` with `{duration, from_point, style_override, lyrics}`
- `POST /api/v1/clips/{id}/cover` with `{style, voice_id, lyrics_override}`
- `POST /api/v1/clips/{id}/remix` with `{style}`
- `POST /api/v1/clips/{id}/repaint` with `{start, end, prompt, style}`
- `POST /api/v1/mashup` with `{clip_ids[], blend_mode, style}`
- `POST /api/v1/clips/{id}/sample` with `{start, end, role, prompt}`
- `POST /api/v1/clips/{id}/add-vocal` with `{lyrics, voice_id, vocal_style}`
- All return job_ids and deduct appropriate credits
- All produce new clips with `parent_clip_ids` and `generation_mode` set

**Acceptance Criteria:**
- [ ] Each endpoint returns a job_id and the resulting clip is accessible on completion
- [ ] Extend produces a clip longer than the source by approximately the requested duration
- [ ] Cover preserves melodic structure while changing style
- [ ] Repaint modifies only the specified time range
- [ ] Mashup accepts 2+ clip IDs and produces a single blended clip
- [ ] All new clips have correct lineage metadata linking to their source(s)

---

#### US-10.4: Full Song Assembly Endpoint

**As a** musician, **I want to** generate a full-length song from a short clip via the API, **so that** I can turn a 30-second idea into a complete 3-4 minute track.

**Description:**
Wraps the auto-extend pipeline from Stage 6 as an API endpoint. Plans a song structure and executes sequential extends. Returns a single assembled clip.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/full-song` with `{target_duration, structure_plan}`
- Default target duration: 210 seconds (~3.5 minutes)
- Optional structure_plan override (e.g., `["intro", "verse", "chorus", "verse", "chorus", "bridge", "outro"]`)
- Creates a single long-running job that chains multiple extend operations
- Returns progress updates per section via the job status endpoint
- Final result is one assembled clip with all sections concatenated

**Acceptance Criteria:**
- [ ] Full-song produces a clip of approximately the target duration
- [ ] Job status shows progress per section (e.g., "Processing section 3 of 7")
- [ ] The output clip has audible structural variety (not pure repetition)
- [ ] Source clip shorter than 60 seconds is required; longer clips return 422
- [ ] Credits are deducted based on the number of extend operations performed

---

#### US-10.5: Batch Operations

**As a** musician, **I want to** run stems extraction or export on multiple clips at once, **so that** I can process an entire workspace efficiently.

**Description:**
Batch endpoints accept an array of clip IDs and queue individual operations for each. A batch job tracks overall progress across all sub-jobs.

**Functional Requirements:**
- `POST /api/v1/batch/stems` with `{clip_ids[]}`
- `POST /api/v1/batch/export` with `{clip_ids[], format}`
- Both return a batch_job_id with individual sub-job IDs
- `GET /api/v1/batch/{batch_id}/status` returns overall progress and per-clip status
- Batch size limit: 50 clips per request

**Acceptance Criteria:**
- [ ] Batch stems processes all provided clips and tracks individual status
- [ ] Batch export produces files for all clips in the requested format
- [ ] Requesting more than 50 clips returns 422
- [ ] Individual failures do not halt the entire batch (partial success reported)

---

#### US-10.6: Lineage Tracking

**As a** musician, **I want to** see the full creation history of any clip, **so that** I can trace how a song evolved through extends, covers, and remixes.

**Description:**
Every clip stores its lineage: the parent clip(s) it was derived from, the operation that created it, and the parameters used. The API exposes this as a queryable graph.

**Functional Requirements:**
- Every clip document includes: `parent_clip_ids` (array), `generation_mode`, `generation_params`
- `GET /api/v1/clips/{id}/lineage` returns the full ancestry tree (parents, grandparents, etc.)
- `GET /api/v1/clips/{id}/children` returns clips derived from this clip
- Lineage response includes clip IDs, titles, generation modes, and creation timestamps
- Maximum lineage depth: 50 levels

**Acceptance Criteria:**
- [ ] A clip created via extend shows its parent in the lineage response
- [ ] A clip with multiple parents (mashup) shows all sources
- [ ] Lineage traversal returns the full tree up to the original generation
- [ ] Children endpoint returns all clips derived from a given clip
- [ ] Lineage queries complete within 500ms for chains up to 20 levels deep

---

**Stage 10 Completion Criteria:**
- All audio editing endpoints (crop, speed, remaster) work and produce correct results
- Stems and MIDI extraction endpoints run as background tasks and cache results
- All iterative generation modes (extend, cover, remix, repaint, mashup, sample, add-vocal) are functional
- Full-song assembly chains extends and reports per-section progress
- Batch operations process multiple clips with partial failure handling
- Lineage tracking records and exposes the full clip derivation graph
- All operations are non-destructive and track parent-child relationships

---

### Stage 11: Compute Routing

**Overview:** Implement hybrid compute routing so generation requests can run on the local GPU, a remote RunPod serverless endpoint, or automatically fall back between them. This stage adds the infrastructure that makes the platform usable from anywhere — not just the machine running the local GPU.

---

#### US-11.1: Compute Routing Engine

**As a** musician, **I want** the platform to automatically choose the best compute target for my generation, **so that** I get results whether I am at my workstation or on my laptop.

**Description:**
Implement a routing engine that evaluates the configured preference (local_first, remote_first, remote_only, local_only) and the current availability of each target to decide where to send a generation request. The compute_target parameter can also be set explicitly per request.

**Functional Requirements:**
- Routing modes: `local_first`, `remote_first`, `remote_only`, `local_only`
- Default mode configurable via `COMPUTE_PREFERENCE` environment variable
- `POST /api/v1/generate` accepts optional `compute_target` parameter (`auto`, `local`, `remote`)
- `auto` uses the configured preference with fallback logic
- Local availability check: ping `http://localhost:8001/v1/stats` with 2-second timeout
- Remote availability check: verify RunPod endpoint status via RunPod API
- Fallback: if preferred target is unavailable, try the other (unless mode is `*_only`)

**Acceptance Criteria:**
- [ ] `local_first` routes to local GPU when available and falls back to remote when not
- [ ] `remote_first` routes to RunPod when available and falls back to local when not
- [ ] `local_only` returns 503 when local GPU is unavailable (no fallback)
- [ ] `remote_only` returns 503 when RunPod is unavailable (no fallback)
- [ ] Per-request `compute_target: "local"` overrides the default preference
- [ ] The chosen target is recorded in the job record and visible in status responses

---

#### US-11.2: RunPod Serverless Integration

**As a** developer, **I want** the platform to submit, poll, and retrieve results from RunPod serverless endpoints, **so that** remote GPU generation is fully automated.

**Description:**
Integrate with RunPod's serverless API to submit generation jobs, poll for status, and retrieve audio results. Handle cold starts, timeouts, and error responses gracefully.

**Functional Requirements:**
- Submit jobs to `https://api.runpod.ai/v2/{endpoint_id}/run` with RunPod API key
- Poll status at `https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}`
- Retrieve results including generated audio data
- Handle RunPod-specific states: `IN_QUEUE`, `IN_PROGRESS`, `COMPLETED`, `FAILED`
- Timeout: configurable per request (default: 300 seconds)
- Retry on transient errors (5xx responses) with exponential backoff (max 3 retries)
- `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` from environment variables

**Acceptance Criteria:**
- [ ] A generation request routed to RunPod returns a completed clip
- [ ] Cold start latency is tolerated without premature timeout
- [ ] RunPod errors are surfaced as meaningful messages in the job status
- [ ] Transient failures are retried before marking the job as failed
- [ ] Missing RunPod configuration disables remote routing (does not crash the app)

---

#### US-11.3: Docker Image for ACE-Step

**As a** developer, **I want** a Docker image for ACE-Step-1.5 that works as both a RunPod serverless handler and a standalone API server, **so that** remote deployment is reproducible and versioned.

**Description:**
Build and publish a Docker image based on the PyTorch CUDA runtime with ACE-Step-1.5 installed. The image supports two modes: standalone API server (for pods) and RunPod serverless handler. Model weights are loaded from a Network Volume, not baked into the image.

**Functional Requirements:**
- Dockerfile based on `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime`
- Installs ACE-Step-1.5 from the fork repository with all dependencies
- Default CMD starts the API server (`uv run acestep-api`)
- Serverless mode: `python /app/handler.py` as alternate CMD
- Handler implements RunPod's `runpod.serverless.start()` pattern
- Model weights loaded from `/workspace/models` (Network Volume mount point)
- Image published to Docker Hub as `frankbria/ace-step:latest`
- Image size target: under 10GB

**Acceptance Criteria:**
- [ ] `docker build` completes without error
- [ ] Container starts in API server mode and responds to `/v1/stats`
- [ ] Container starts in serverless mode and processes a RunPod handler event
- [ ] Model weights are loaded from the mounted volume (not from inside the image)
- [ ] Image is pushable to Docker Hub

---

#### US-11.4: Compute Status Endpoint

**As a** musician, **I want to** check the status of available compute targets, **so that** I know whether my local GPU is busy and whether remote is available before generating.

**Description:**
A status endpoint that aggregates health information from both local and remote compute targets into a single response.

**Functional Requirements:**
- `GET /api/v1/compute/status` returns combined status of local and remote targets
- Local status: available (bool), GPU name, VRAM total/used, active jobs, loaded models
- Remote status: available (bool), provider, endpoint_id, active workers, max workers, scaling status
- Current routing preference included in response
- Timeout: 3 seconds per target check (non-blocking, parallel)

**Acceptance Criteria:**
- [ ] With local GPU running: local status shows available with GPU details
- [ ] With local GPU stopped: local status shows unavailable
- [ ] With RunPod configured: remote status shows endpoint details
- [ ] With RunPod not configured: remote status shows unavailable (not an error)
- [ ] Response returns within 5 seconds even if one target is unreachable

---

#### US-11.5: RunPod Network Volume Setup Documentation

**As a** developer, **I want** a scripted setup process for the RunPod Network Volume with model weights, **so that** remote deployment can be reproduced or recovered quickly.

**Description:**
Provide a setup script and management commands for initializing the RunPod Network Volume with ACE-Step-1.5 model weights. The volume persists model weights so they only need to be downloaded once.

**Functional Requirements:**
- Setup script: `scripts/runpod-setup.py` that creates a Network Volume, spins up a temporary pod, downloads model weights, and stops the pod
- `GET /api/v1/compute/remote/volume` returns volume info (size, used, region)
- Script configurable for region and volume size
- Documentation of the one-time setup process in code comments
- Cost estimate displayed before creating resources

**Acceptance Criteria:**
- [ ] Setup script creates a Network Volume and downloads model weights
- [ ] Volume persists after the temporary pod is stopped
- [ ] Future serverless workers or pods can mount the volume and access weights
- [ ] Script is idempotent (re-running does not create duplicate volumes)

---

**Stage 11 Completion Criteria:**
- Compute routing engine correctly selects local or remote based on preference and availability
- RunPod serverless integration submits, polls, and retrieves generation results
- Docker image builds and runs in both API and serverless modes
- Compute status endpoint reports health of all targets
- Fallback logic gracefully handles target unavailability
- Network Volume setup is scripted and documented
- Tests cover all routing modes and fallback scenarios

---

### Stage 12: Mastering Pipeline API

**Overview:** Integrate external mastering services (Dolby.io, LANDR, Bakuage) to transform final mixes into distribution-ready masters. Musicians can submit clips for professional-grade mastering, choose loudness profiles, preview multiple results, and A/B compare against the original.

---

#### US-12.1: Mastering Job Submission

**As a** musician, **I want to** submit a clip for automated mastering with a target profile, **so that** my music sounds professional and meets platform loudness standards.

**Description:**
The mastering endpoint accepts a clip ID, a mastering profile, and an optional service preference. It uploads the audio to the selected mastering API and creates a job for tracking.

**Functional Requirements:**
- `POST /api/v1/mastering/jobs` with `{clip_id, profile, service, format}`
- Profiles: `streaming` (-14 LUFS), `soundcloud` (-12 LUFS), `club` (maximum loudness), `vinyl` (wide dynamic range), `custom` (user-specified LUFS target)
- Service: `dolby` (default), `landr`, `bakuage`
- Format: output audio format (wav, mp3, flac)
- Returns a mastering_job_id with status `queued`
- Credits deducted based on service (2-5 credits)

**Acceptance Criteria:**
- [ ] Submitting a mastering job returns a job_id with status `queued`
- [ ] Each profile maps to the correct LUFS target
- [ ] Invalid profile or service returns 422
- [ ] Insufficient credits returns 402
- [ ] Job record is created in MongoDB with all parameters

---

#### US-12.2: Dolby.io Integration

**As a** developer, **I want** full integration with Dolby.io's Music Mastering API, **so that** the primary mastering service works end-to-end.

**Description:**
Implement the Dolby.io mastering flow: authenticate with JWT, upload audio to Dolby's input storage, submit a mastering job, poll for completion, retrieve metrics, and download the mastered audio.

**Functional Requirements:**
- Authenticate with Dolby.io using API key to obtain a JWT
- Upload source audio to Dolby.io input URL
- Submit mastering job with profile-specific parameters
- Poll job status until completion
- Retrieve mastering metrics: loudness (LUFS), EQ across 16 bands, stereo image analysis
- Download mastered audio and store via the storage abstraction
- Support generating up to 5 preview variants per job
- `DOLBY_API_KEY` and `DOLBY_API_SECRET` from environment variables

**Acceptance Criteria:**
- [ ] End-to-end mastering via Dolby.io produces a mastered audio file
- [ ] Mastering metrics are stored in the job record and retrievable via API
- [ ] Up to 5 previews can be generated and individually auditioned
- [ ] Missing Dolby.io credentials disable the service (not crash the app)
- [ ] Audio quality is measurably improved (LUFS closer to target)

---

#### US-12.3: LANDR and Bakuage Fallback Integrations

**As a** developer, **I want** LANDR and Bakuage mastering integrations as alternatives, **so that** the platform has fallback options and service flexibility.

**Description:**
Implement secondary mastering service integrations. LANDR provides B2B API access with genre-aware processing. Bakuage provides an open REST API as a cost-effective fallback.

**Functional Requirements:**
- LANDR integration: submit audio, select loudness and style, poll, retrieve mastered audio
- Bakuage integration: create mastering via REST API, poll status, download result
- Both services implement the same `MasteringService` interface as Dolby.io
- Service selection via the `service` parameter on the mastering endpoint
- Automatic fallback: if the primary service fails, retry with the next available service

**Acceptance Criteria:**
- [ ] LANDR mastering produces a mastered audio file (when API access is configured)
- [ ] Bakuage mastering produces a mastered audio file
- [ ] Fallback from Dolby.io to Bakuage works when Dolby.io returns an error
- [ ] Each service returns its results in the same response format

---

#### US-12.4: Mastering Preview and A/B Comparison

**As a** musician, **I want to** preview multiple mastering results and compare them against the original, **so that** I can choose the best master for my release.

**Description:**
After mastering completes, the musician can audition up to 5 preview variants and A/B compare any preview against the unmastered original. Approving a preview promotes it to the final master.

**Functional Requirements:**
- `GET /api/v1/mastering/jobs/{id}` returns job status, previews, and metrics
- `GET /api/v1/mastering/jobs/{id}/previews` returns audio URLs for each preview variant
- `POST /api/v1/mastering/jobs/{id}/approve` with `{preview_id}` promotes a preview to the final master
- Approved master is saved as a new clip with `generation_mode: mastered` and linked to the source
- A/B comparison data: original clip URL + mastered clip URL + metrics diff

**Acceptance Criteria:**
- [ ] Multiple previews are accessible after mastering completes
- [ ] Approving a preview creates a new clip with mastered metadata
- [ ] The mastered clip is linked to the original via parent_clip_ids
- [ ] Metrics (LUFS, EQ) are available for both original and mastered versions
- [ ] Rejecting all previews allows resubmission with different parameters

---

#### US-12.5: Batch Mastering

**As a** musician, **I want to** master multiple clips with the same profile at once, **so that** I can prepare an entire album with consistent sound.

**Description:**
Batch mastering applies the same mastering profile and service to multiple clips. Each clip is processed as an individual mastering job, tracked under a single batch ID.

**Functional Requirements:**
- `POST /api/v1/mastering/batch` with `{clip_ids[], profile, service}`
- Returns a batch_id with individual mastering_job_ids
- `GET /api/v1/mastering/batch/{batch_id}/status` shows overall progress
- Batch size limit: 20 clips
- Credits deducted for each clip individually

**Acceptance Criteria:**
- [ ] Batch mastering processes all provided clips
- [ ] Each clip gets its own mastering job with independent status
- [ ] Overall batch progress is trackable via the batch status endpoint
- [ ] Individual failures do not halt the batch
- [ ] Exceeding the batch limit returns 422

---

**Stage 12 Completion Criteria:**
- Mastering jobs can be submitted with any supported profile and service
- Dolby.io integration works end-to-end (auth, upload, master, metrics, download)
- LANDR and Bakuage integrations work as alternatives
- Previews are generated, auditioned, and approved
- A/B comparison data is available for original vs. mastered
- Batch mastering processes multiple clips consistently
- All mastering endpoints are covered by integration tests

---

### Stage 13: Distribution Pipeline API

**Overview:** Build the distribution pipeline — from cover art generation through SoundCloud upload to guided distribution prep for LANDR and DistroKid. This stage takes a mastered clip and packages it with metadata, artwork, and identifiers into a release-ready package.

---

#### US-13.1: Cover Art Generation

**As a** musician, **I want to** generate AI cover art based on my song's style and mood, **so that** I have professional artwork for distribution without hiring a designer.

**Description:**
Integrates with an AI image generation API to produce cover art options based on the song's title, style tags, lyrics, and mood. The musician selects their preferred art, which is attached to the clip metadata.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/artwork/generate` with optional `{style_prompt}` override
- Generates 4 cover art options (1024x1024 minimum, upscaled to 3000x3000 for distribution)
- Returns URLs for all 4 options
- `POST /api/v1/clips/{id}/artwork` with `{artwork_id}` selects the preferred art
- `PUT /api/v1/clips/{id}/artwork/upload` accepts a custom image upload (JPG/PNG, 3000x3000 minimum)
- Image validation: minimum resolution, acceptable formats, no corrupt files

**Acceptance Criteria:**
- [ ] Generating artwork produces 4 image options tied to the clip
- [ ] Selecting an artwork option attaches it to the clip metadata
- [ ] Uploading custom artwork validates resolution and format
- [ ] Images below 3000x3000 are rejected with a descriptive error
- [ ] Generated artwork visually reflects the song's style tags (manual verification)

---

#### US-13.2: SoundCloud OAuth and Upload

**As a** musician, **I want to** connect my SoundCloud account and upload mastered tracks directly from the platform, **so that** I can publish music without leaving my workflow.

**Description:**
Implement the full SoundCloud OAuth 2.1 flow for account linking and the track upload endpoint. The platform handles authentication, metadata mapping, and multipart file upload.

**Functional Requirements:**
- `POST /api/v1/distribution/soundcloud/connect` initiates SoundCloud OAuth 2.1 flow
- `POST /api/v1/distribution/soundcloud/callback` handles the OAuth redirect and stores tokens
- `GET /api/v1/distribution/soundcloud/status` returns connection status
- `POST /api/v1/distribution/soundcloud/upload` with `{clip_id, metadata_overrides}` uploads a track
- Metadata mapped: title, genre, description, bpm, key_signature, isrc, sharing (public/private), artwork
- Audio format: WAV or FLAC preferred, MP3 acceptable
- Upload size limit: 500MB (SoundCloud limit)
- Token refresh handled automatically when tokens expire

**Acceptance Criteria:**
- [ ] SoundCloud OAuth flow completes and stores access/refresh tokens
- [ ] Uploading a mastered clip to SoundCloud creates a track on the user's profile
- [ ] Metadata (title, genre, BPM) is correctly set on the SoundCloud track
- [ ] Cover art is uploaded alongside the audio
- [ ] Token refresh works transparently when the access token expires

---

#### US-13.3: Release Package Assembly

**As a** musician, **I want** the platform to assemble all required assets into a release package, **so that** I have everything needed for distribution in one place.

**Description:**
A release package bundles the mastered audio, cover art, metadata, lyrics, and credits into a validated, distribution-ready bundle. This package is the input for all distribution channels.

**Functional Requirements:**
- `POST /api/v1/releases` with `{clip_id, metadata}` creates a release package
- Required metadata: title, artist, genre, release_date
- Optional metadata: album_name, description, isrc, upc, copyright, is_explicit, language, credits
- Validates: mastered audio exists, cover art meets resolution requirements, required metadata is complete
- `GET /api/v1/releases/{id}` returns the package status and contents
- `PATCH /api/v1/releases/{id}` updates metadata before submission
- Package states: `draft`, `ready`, `submitted`, `live`, `rejected`

**Acceptance Criteria:**
- [ ] Creating a release with complete metadata and mastered audio returns status `ready`
- [ ] Missing required fields return 422 with specific field errors
- [ ] Submitting a release for an unmastered clip warns the user (soft block, not hard block)
- [ ] Release metadata is editable while in `draft` or `ready` state
- [ ] Package includes audio file, artwork, and metadata JSON

---

#### US-13.4: ISRC and UPC Generation

**As a** musician, **I want** the platform to generate ISRC and UPC codes for my releases, **so that** my music is properly identified across all streaming platforms.

**Description:**
ISRC (International Standard Recording Code) identifies individual recordings. UPC/EAN identifies a release (single/album). The platform auto-generates these codes or allows the musician to enter existing ones.

**Functional Requirements:**
- Auto-generate ISRC codes for each track in a release (format: CC-XXX-YY-NNNNN)
- Auto-generate UPC/EAN-13 codes for each release
- `PATCH /api/v1/releases/{id}` allows manual ISRC/UPC entry (overrides auto-generated)
- ISRC codes are unique and never reused
- UPC codes include a valid check digit
- Codes are stored in the release package and the clip metadata

**Acceptance Criteria:**
- [ ] Auto-generated ISRC follows the standard format and is unique
- [ ] Auto-generated UPC is a valid EAN-13 with correct check digit
- [ ] Manually entered codes override auto-generated ones
- [ ] Duplicate ISRC codes are rejected
- [ ] Codes persist in both the release package and the clip record

---

#### US-13.5: Guided Distribution Prep

**As a** musician, **I want** the platform to prepare my release package for LANDR and DistroKid, **so that** I can submit to major streaming platforms with minimal friction.

**Description:**
Since LANDR, DistroKid, and TuneCore do not offer public APIs, the platform prepares the release package to each service's requirements and provides a guided flow to complete the submission.

**Functional Requirements:**
- `POST /api/v1/releases/{id}/prepare/{target}` where target is `landr`, `distrokid`, `tunecore`
- Validates the package against the target's requirements (format, resolution, metadata completeness)
- Returns a preparation checklist with pass/fail items
- Provides a downloadable bundle formatted to the target's specifications
- Generates instructions for completing the submission on the target platform
- Updates release status to `submitted` when the user confirms manual submission

**Acceptance Criteria:**
- [ ] Preparing for LANDR validates and formats the package to LANDR requirements
- [ ] A downloadable bundle is available for each target
- [ ] The preparation checklist identifies missing or non-compliant items
- [ ] Instructions are specific to each distribution target
- [ ] Release status updates to `submitted` after user confirmation

---

#### US-13.6: Distribution Status Tracking

**As a** musician, **I want to** track the status of my releases across all distribution channels, **so that** I know when my music is live and can respond to issues.

**Description:**
A unified dashboard endpoint showing the distribution status of each release across all channels. For SoundCloud (direct integration), status is polled automatically. For guided channels, the user manually updates status.

**Functional Requirements:**
- `GET /api/v1/releases` lists all releases with their distribution status per channel
- `GET /api/v1/releases/{id}/status` returns per-channel status: `draft`, `ready`, `submitted`, `in_review`, `live`, `rejected`
- SoundCloud status is updated automatically via API polling
- Guided channels: `PATCH /api/v1/releases/{id}/channels/{channel}/status` allows manual status update
- Visibility controls: `PATCH /api/v1/releases/{id}/visibility` with `{state}` (private, unlisted, public)
- Notifications triggered on status changes (live, rejected)

**Acceptance Criteria:**
- [ ] Release listing shows per-channel distribution status
- [ ] SoundCloud status reflects actual track state (checking via API)
- [ ] Manual status updates for guided channels are stored and visible
- [ ] Visibility changes update the clip's sharing state
- [ ] Status transitions follow the valid sequence (no skipping from draft to live)

---

**Stage 13 Completion Criteria:**
- Cover art generation produces options and attaches selected art to clips
- SoundCloud OAuth flow and track upload work end-to-end
- Release packages are assembled with validated metadata and assets
- ISRC and UPC codes are auto-generated with proper formatting
- Guided distribution prep produces compliant packages for LANDR and DistroKid
- Distribution status is tracked per channel and per release
- All endpoints covered by integration tests

---

### Stage 14: DAW Export & Playback API

**Overview:** Expose the DAW export bundle, audio streaming with range requests (for the global player), playback queue management, and similar-songs queries as API endpoints. This stage completes Layer 2 by providing the backend for the web player and DAW integration workflows.

---

#### US-14.1: DAW Export Endpoint

**As a** musician, **I want to** download a DAW-ready export bundle via the API, **so that** I can import stems, MIDI, and metadata into Cubase or any other DAW.

**Description:**
Wraps the CLI's DAW export logic in an API endpoint. Triggers stem separation and MIDI extraction if not already done, packages everything into a ZIP archive, and serves it for download.

**Functional Requirements:**
- `POST /api/v1/clips/{id}/export/daw` triggers DAW bundle creation (async job if stems/MIDI need extraction)
- `GET /api/v1/clips/{id}/export/daw` downloads the ZIP once ready
- ZIP structure: `SongTitle_Export/audio/{full_mix,vocals,drums,bass,other}.wav`, `midi/{melody,chords,drums,bass}.mid`, `project.json`, `artwork.jpg`
- project.json includes: BPM, key, time_signature, duration, stem references, MIDI channel assignments, markers, lyrics, style_tags, model, seed
- If stems/MIDI already exist, reuses cached results (no re-extraction)
- Credits: 1 credit for stems + 1 credit for MIDI (0 if already extracted)

**Acceptance Criteria:**
- [ ] DAW export produces a ZIP with the correct directory structure
- [ ] project.json contains all metadata fields with correct values
- [ ] MIDI files are importable into a DAW with correct tempo and channels
- [ ] Stems are time-aligned and equal length
- [ ] Cached stems/MIDI are reused without re-extraction or additional credit charge

---

#### US-14.2: Audio Streaming with Range Requests

**As a** listener, **I want to** stream audio with seeking support, **so that** the web player can play clips immediately without downloading the entire file.

**Description:**
Enhance the clip audio endpoint to fully support HTTP range requests for efficient streaming. This is the backend for the global player in the web UI.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/stream` serves audio optimized for streaming
- Full HTTP Range header support (single and multi-range)
- Returns 206 Partial Content for range requests, 200 for full requests
- Content-Type, Content-Length, Content-Range, and Accept-Ranges headers set correctly
- Supports MP3 format for streaming (smaller file size) and WAV for lossless
- Connection keep-alive for continuous playback
- Rate limiting: prevent abuse of streaming endpoints

**Acceptance Criteria:**
- [ ] A web audio player can seek to any position without buffering the full file
- [ ] Range requests return 206 with correct Content-Range header
- [ ] Full request (no Range header) returns 200 with the complete file
- [ ] Streaming a 3-minute MP3 begins playback within 1 second
- [ ] Public clips are streamable without authentication; private clips require auth

---

#### US-14.3: Playback Queue Management

**As a** musician, **I want to** manage a playback queue via the API, **so that** the web player can queue up songs, support next/previous, and maintain state across page navigations.

**Description:**
Server-side playback queue that persists the user's current listening session. Supports adding, removing, reordering, and advancing through the queue.

**Functional Requirements:**
- `POST /api/v1/queue` with `{clip_ids[], position}` adds clips to the queue
- `GET /api/v1/queue` returns the current queue with playback position
- `DELETE /api/v1/queue/{clip_id}` removes a clip from the queue
- `POST /api/v1/queue/next` advances to the next clip
- `POST /api/v1/queue/previous` goes back to the previous clip
- `PUT /api/v1/queue/reorder` with `{clip_id, new_position}` reorders the queue
- `DELETE /api/v1/queue` clears the entire queue
- Repeat mode: `none`, `one`, `all`
- Shuffle mode: on/off (shuffles remaining queue, preserves play history)

**Acceptance Criteria:**
- [ ] Adding clips to the queue persists across API requests
- [ ] Next/previous navigation works correctly with repeat and shuffle modes
- [ ] Reordering updates positions without losing clips
- [ ] Queue is scoped to the authenticated user
- [ ] Queue state persists across page reloads (client can restore state from GET)

---

#### US-14.4: Similar Songs Query

**As a** musician, **I want to** find songs similar to a given clip, **so that** I can discover related music and populate a radio-style listening queue.

**Description:**
Query for clips similar to a seed clip based on style tags, genre, BPM, key, and mood. Results are drawn from the user's library and optionally from public clips.

**Functional Requirements:**
- `GET /api/v1/clips/{id}/similar` returns up to 20 similar clips
- Similarity based on: matching style tags, BPM proximity (within 10%), same key or relative key, same model/generation mode
- `?scope=mine` limits to user's own clips; `?scope=public` includes public clips; `?scope=all` (default) includes both
- `?limit=N` controls result count (default 20, max 50)
- Results ordered by similarity score (descending)
- Can be used to auto-populate a radio queue

**Acceptance Criteria:**
- [ ] Similar clips share at least one style tag or are within 10% BPM of the seed
- [ ] Scope parameter correctly filters results to own/public/all
- [ ] Results are ordered by relevance (most similar first)
- [ ] Empty result set returns 200 with an empty array (not 404)
- [ ] Query completes within 1 second for a library of 1000+ clips

---

**Stage 14 Completion Criteria:**
- DAW export produces valid ZIP bundles with stems, MIDI, metadata, and artwork
- Audio streaming with range requests enables efficient web player playback
- Playback queue supports full lifecycle (add, remove, reorder, next, previous, repeat, shuffle)
- Similar songs query returns relevant results based on musical properties
- All endpoints covered by integration tests
- **End-to-end API workflow validated:** authenticate -> generate -> edit -> master -> distribute -> export -> stream

---

## Layer 3: Web UI

*Goal: Build a Next.js frontend that consumes the Platform API, providing the full creative, social, and distribution experience through the browser. The UI follows the Nova template design system with gray color scheme, Hugeicons, and Nunito Sans typography.*

---

### Stage 15: App Shell & Auth UI

**Overview:** Stand up the Next.js application with the core layout chrome — sidebar navigation, main content area, contextual right panel, and persistent bottom playbar. Add OAuth authentication, profile settings, and the global audio player. After this stage, a musician can log in, configure their profile, and play audio across any page.

---

#### US-15.1: Next.js Project Scaffold

**As a** developer, **I want** a Next.js project initialized with the Nova template (gray scheme, Hugeicons, Nunito Sans), **so that** I have a consistent, accessible design system from the first page.

**Description:**
Bootstrap the `web/` directory using the Nova template with Shadcn/UI and Tailwind CSS. Configure the gray color palette, Hugeicons icon library, and Nunito Sans font. Ensure the dev server runs and renders a placeholder page.

**Functional Requirements:**
- Next.js project created via Nova template setup command with gray base color, Hugeicons, and Nunito Sans
- Tailwind CSS configured with the gray palette and Nova design tokens
- `@hugeicons/react` installed and verified with a sample icon render
- Nunito Sans loaded from Google Fonts with CSS variables
- Dev server starts without errors (`npm run dev`)
- Placeholder index page renders with correct font, color scheme, and a sample icon

**Acceptance Criteria:**
- [ ] `npm run dev` starts the dev server without errors
- [ ] Index page renders with Nunito Sans font applied
- [ ] Gray color palette is active (not zinc or slate)
- [ ] A Hugeicons icon renders correctly on the placeholder page
- [ ] Shadcn/UI components use Nova styling (data-slot attributes, ring-[3px] focus states)

---

#### US-15.2: Application Shell Layout

**As a** musician, **I want** a consistent layout with sidebar navigation, main content, a contextual right panel, and a bottom playbar, **so that** I can navigate the platform without losing context or audio playback.

**Description:**
Build the two-panel layout described in spec section 1.1. The left sidebar is a collapsed icon bar by default, the main content area is route-driven, the right panel shows contextual information, and the bottom playbar persists across all routes.

**Functional Requirements:**
- Left sidebar renders as a collapsed icon bar (icons only, no labels by default)
- Main content area fills remaining horizontal space and is route-driven
- Right panel renders conditionally based on route context (placeholder for now)
- Bottom playbar is fixed at the bottom, visible on all pages
- Layout is responsive: sidebar collapses to icons on smaller screens, right panel hides below a breakpoint
- All panels maintain proper z-index layering

**Acceptance Criteria:**
- [ ] Layout renders with sidebar, main content, and bottom playbar on all routes
- [ ] Right panel is visible on routes that provide contextual content
- [ ] Sidebar does not overlap main content
- [ ] Bottom playbar remains visible during scroll
- [ ] Layout is usable at 1024px, 1440px, and 1920px viewport widths

---

#### US-15.3: Sidebar Navigation

**As a** musician, **I want** icon-based navigation in the sidebar with all major destinations, **so that** I can reach any area of the platform in one click.

**Description:**
Implement the sidebar navigation icons from spec section 1.2 — Home, Explore, Create, Studio, Library, Search, Feed, Notifications, Mastering/Distribution, Labs, and Account. Include the expand/collapse toggle (spec section 1.3) and profile avatar menu (spec section 1.4).

**Functional Requirements:**
- Sidebar icons for all destinations: Home (`/`), Explore (`/explore`), Create (`/create`), Studio (`/studio`), Library (`/me`), Search (`/search`), Feed (`/feed`), Notifications (`/notifications`), Mastering & Distribution (`/release`), Labs (`/labs`), Account (dialog)
- Active route icon is visually highlighted
- Expand/collapse toggle at the top switches between icon-only and full-label mode
- Expanded mode shows icon + text label for each destination
- Profile avatar button at the top opens a dropdown: profile link, account settings, subscription, logout
- Labs and Account icons pinned to the bottom of the sidebar
- All icons sourced from `@hugeicons/react`

**Acceptance Criteria:**
- [ ] All navigation icons render and link to correct routes
- [ ] Active route icon is visually distinct
- [ ] Expand toggle switches sidebar between icon-only and icon+label modes
- [ ] Sidebar state persists across navigation (does not reset on route change)
- [ ] Profile dropdown shows profile, account settings, subscription, and logout options

---

#### US-15.4: OAuth Login and Signup

**As a** musician, **I want** to log in with Google or Discord, **so that** I can start creating music without managing another password.

**Description:**
Implement OAuth/SSO authentication with Google and Discord identity providers. Login redirects to the Create page on success. Unauthenticated users are redirected to the login page when accessing protected routes.

**Functional Requirements:**
- Login page with Google and Discord OAuth buttons
- Optional email/password signup as a fallback
- Successful login redirects to `/create`
- Auth state stored securely (JWT or session cookie)
- Protected routes redirect unauthenticated users to login
- Logout clears session and redirects to login page
- Loading state while OAuth flow is in progress

**Acceptance Criteria:**
- [ ] Google OAuth login completes and redirects to `/create`
- [ ] Discord OAuth login completes and redirects to `/create`
- [ ] Unauthenticated access to `/create` redirects to login
- [ ] Logout clears session and returns to login page
- [ ] Auth tokens are stored securely (httpOnly cookie or equivalent)

---

#### US-15.5: Profile Settings Page

**As a** musician, **I want** to set my display name, handle, avatar, bio, and style tags, **so that** my public profile reflects who I am as a creator.

**Description:**
Build the profile settings page where users configure their identity. This data is displayed on the public profile page (`/@username`) and used by the personalization engine for style recommendations.

**Functional Requirements:**
- Display name text input
- Username handle input (`@username`) with availability check
- Avatar image upload (drag-and-drop or file picker, crop to square)
- Bio/description textarea (character limit displayed)
- Style tags as pill badges (add/remove, typeahead suggestions, e.g., "cello," "orchestral," "lo-fi")
- Save button with loading state and success/error feedback
- Form validation: handle must be unique, avatar must be an image, style tags have a reasonable max count

**Acceptance Criteria:**
- [ ] All fields save successfully and persist on page reload
- [ ] Username handle shows real-time availability feedback
- [ ] Avatar upload previews the image before saving
- [ ] Style tags render as removable pill badges
- [ ] Validation errors display inline next to the offending field

---

#### US-15.6: Global Audio Player

**As a** musician, **I want** a persistent player at the bottom of every page with full playback controls, **so that** I can listen to any clip while navigating the platform.

**Description:**
Implement the global playbar described in spec section 46. The player supports play/pause, previous/next, progress scrubbing, volume control, waveform visualization, song info display, queue management, repeat/shuffle modes, and a like button. Audio playback continues uninterrupted across route transitions.

**Functional Requirements:**
- Play/pause toggle
- Previous/next track buttons
- Progress scrubber (click or drag to seek)
- Current time and total duration display
- Volume slider with mute toggle
- Waveform visualization (miniature waveform in the playbar)
- Song info display: thumbnail, title, artist
- Queue button (opens queue panel showing upcoming tracks)
- Repeat mode toggle (off / repeat-all / repeat-one)
- Shuffle toggle
- Like button (heart icon, toggles liked state)
- Audio continues playing across route changes (no interruption on navigation)
- Keyboard shortcuts: space (play/pause), left/right arrows (seek), up/down arrows (volume)

**Acceptance Criteria:**
- [ ] Play/pause, prev/next, and scrubber work correctly
- [ ] Audio continues playing when navigating between routes
- [ ] Volume slider and mute toggle control audio level
- [ ] Queue panel displays upcoming tracks and allows reordering
- [ ] Repeat and shuffle modes function correctly
- [ ] Song info (thumbnail, title, artist) updates when track changes
- [ ] Keyboard shortcuts work when player is active

---

**Stage 15 Completion Criteria:**
- Next.js project runs with Nova template styling (gray palette, Hugeicons, Nunito Sans)
- App shell layout renders correctly at multiple viewport widths
- All sidebar navigation links route to the correct pages
- OAuth login with Google and Discord works end-to-end
- Profile settings save and persist
- Global player plays audio across all routes without interruption
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 16: Creation Pages

**Overview:** Build the song creation UI — the heart of the platform. Implement Simple, Advanced, and Sounds creation modes, the model/version selector, the workspace clip panel, clip cards with full actions, and audio input modals. After this stage, a musician can compose songs through the browser with the same power as the CLI.

---

#### US-16.1: Simple Creation Mode

**As a** musician, **I want** a minimal creation form where I describe a song in plain language, **so that** I can generate music quickly without configuring parameters.

**Description:**
Build the Simple tab on the `/create` page with the song description textarea, instrumental toggle, +Audio button, +Lyrics button, and AI-suggested inspiration tags with a shuffle button. This is the low-barrier entry point for music creation.

**Functional Requirements:**
- Song description textarea with placeholder text (e.g., "Describe the song you want to create...")
- Instrumental toggle (boolean switch to suppress vocals)
- "+Audio" button opens the audio input modal (US-16.7)
- "+Lyrics" button opens an inline lyrics entry field
- Inspiration tags: AI-suggested style tag pills rendered below the description
- Each tag is clickable to add it to the generation context
- Shuffle button randomizes/refreshes the tag suggestions
- Create button at the bottom (disabled until at least one field is populated)

**Acceptance Criteria:**
- [ ] Description textarea accepts free-form text input
- [ ] Instrumental toggle visibly changes state and is sent with generation request
- [ ] Inspiration tags render as clickable pills; clicking adds the tag to the form context
- [ ] Shuffle button replaces current tag suggestions with new ones
- [ ] Create button is disabled when all fields are empty
- [ ] Create button is enabled when description or lyrics are provided

---

#### US-16.2: Advanced Creation Mode

**As a** musician, **I want** separate controls for lyrics, styles, and generation parameters, **so that** I have precise creative control over every aspect of the song.

**Description:**
Build the Advanced tab with the lyrics panel (textarea, enhance, undo, save, clear, manual/auto toggle), styles panel (textarea, magic wand, tag pills, shuffle, undo, save, clear), and the expandable "More Options" section containing all parameters from spec section 4.4.

**Functional Requirements:**
- Lyrics panel: textarea with structure tag support (`[Verse]`, `[Chorus]`, etc.), vocal language dropdown, enhance input field, undo, save preset, clear, and manual/auto toggle
- Styles panel: comma-separated styles textarea, personalized magic wand button, clickable style tag pills, shuffle, undo, save preset, clear
- More Options (collapsed by default): exclude styles, vocal gender toggle, lyrics mode, BPM (60-180 or Auto), key selector, time signature selector, duration input, weirdness slider (0-100), style influence slider (0-100), song title, save to workspace selector, seed input
- All controls send their values to the generation API
- Undo buttons revert to previous state for their respective fields

**Acceptance Criteria:**
- [ ] Lyrics panel supports structured sections and vocal language selection
- [ ] Enhance lyrics input triggers AI rewrite of the lyrics field
- [ ] Styles textarea and tag pills both contribute to the style string
- [ ] More Options section expands/collapses and exposes all generation parameters
- [ ] BPM, key, duration, weirdness, and style influence values are validated before submission
- [ ] Undo buttons revert their respective fields to the previous state

---

#### US-16.3: Sounds Creation Mode

**As a** musician, **I want** to generate short audio samples like loops and one-shots, **so that** I can create building blocks for my productions.

**Description:**
Build the Sounds tab with a description textarea, type selector (one-shot or loop), BPM input, and key selector. Outputs are short clips stored in the workspace alongside songs.

**Functional Requirements:**
- Sound description textarea
- Type selector: One-Shot or Loop (required)
- BPM numeric input (or "Auto") for loops
- Key selector ("Any" or specific musical key)
- Create button behavior matches Simple/Advanced mode (disabled until valid, 2 clips generated)
- Generated clips tagged as sounds in the workspace

**Acceptance Criteria:**
- [ ] Type selector is required before Create is enabled
- [ ] BPM and key fields are available and sent with the request
- [ ] Generated sound clips appear in the workspace panel with correct metadata
- [ ] Loop clips include tempo metadata

---

#### US-16.4: Model and Version Selector

**As a** musician, **I want** to choose which AI model generates my music, **so that** I can trade off between speed and quality.

**Description:**
Add a model/version selector dropdown accessible from all creation modes. Shows available model variants with descriptions, VRAM info, and subscription requirements.

**Functional Requirements:**
- Version badge button visible on all creation tabs
- Dropdown lists: Create Custom Model (Beta), Latest Model (XL), Standard Model, Turbo Model, Legacy Models
- Each option shows name, brief description, and Pro badge if subscription required
- Selected model persists across tab switches within the same session
- Default model configurable in user settings

**Acceptance Criteria:**
- [ ] Model selector is accessible from Simple, Advanced, and Sounds tabs
- [ ] Selecting a model updates the generation request payload
- [ ] Pro-only models show a badge or lock indicator for free-tier users
- [ ] Selected model persists when switching between creation tabs

---

#### US-16.5: Workspace and Clip Library Panel

**As a** musician, **I want** a workspace panel showing all my clips with search, filters, and sorting, **so that** I can manage my generated content alongside creation.

**Description:**
Build the right-side workspace panel on the Create page with clip cards in list view, workspace breadcrumb, search, filter controls, sort dropdown, and pagination. This panel is the musician's clip library during the creation workflow.

**Functional Requirements:**
- Workspace breadcrumb showing current workspace path (clickable to navigate)
- Search input filtering clips by title or metadata
- Filters button with active filter count badge; filter panel includes: liked, public, uploads
- Sort dropdown: Newest, Oldest
- Pagination controls (previous/next + page number)
- Clip cards rendered in list view (see US-16.6)
- Panel scrolls independently of main content

**Acceptance Criteria:**
- [ ] Workspace breadcrumb displays current workspace and navigates on click
- [ ] Search filters clips in real time by title or metadata
- [ ] Filter toggles (Liked, Public, Uploads) narrow the clip list
- [ ] Sort dropdown reorders clips
- [ ] Pagination loads additional pages of clips
- [ ] Panel scrolls independently from the creation form

---

#### US-16.6: Clip Card Component

**As a** musician, **I want** each clip card to show its metadata, playback controls, and quick actions, **so that** I can preview, edit, and manage clips without leaving the creation page.

**Description:**
Build the clip card component for the workspace list view. Each card displays thumbnail, title (inline editable), version badge, metadata badge, style description, and action buttons. This component is reused across the workspace panel, library, and search results.

**Functional Requirements:**
- Thumbnail with duration overlay and play button (plays clip in global player)
- Title with inline edit (pencil icon, click to rename)
- Version badge (model that generated the clip)
- Metadata badge (Cover, Upload, Studio, Extend 1, Mastered, etc.)
- Style description (truncated with tooltip for full text)
- Like / Dislike / Share action buttons
- Publish button (toggles public visibility)
- "Get Full Song" button (visible on short clips under ~60 seconds)
- Remix/Edit button (primary CTA with dropdown arrow for sub-options)
- More options menu (three-dot icon) with full action list from spec section 9.2

**Acceptance Criteria:**
- [ ] Clip card renders all metadata fields correctly
- [ ] Play button sends the clip to the global player
- [ ] Inline title edit saves on blur or Enter key
- [ ] Like/dislike/share/publish buttons trigger appropriate API calls
- [ ] More options menu renders all actions from spec section 9.2
- [ ] "Get Full Song" button is only visible on clips shorter than ~60 seconds

---

#### US-16.7: Create Button Behavior and Generation Flow

**As a** musician, **I want** the Create button to show progress and deliver clips to my workspace, **so that** I have clear feedback during generation and immediate access to results.

**Description:**
Wire the Create button across all modes to submit the form to the generation API. Show a progress indicator during generation, display generation time estimates based on the selected model, and render 2 new clip cards in the workspace panel when complete.

**Functional Requirements:**
- Create button disabled until minimum inputs are satisfied
- On click: button shows a progress indicator (spinner or progress bar)
- Generation time estimate displayed based on selected model (Turbo: ~2-5s, Standard: ~10-30s, XL: ~30-60s)
- On success: 2 new clip cards appear at the top of the workspace panel
- On failure: error state with message and retry option
- Each generation consumes credits (credit count updates in UI)
- "Clear all" button resets all form inputs to defaults

**Acceptance Criteria:**
- [ ] Create button is disabled when form is empty and enabled when valid
- [ ] Progress indicator is visible during generation
- [ ] Generation time estimate reflects the selected model
- [ ] 2 new clip cards appear in the workspace panel on success
- [ ] Error state shows a meaningful message with retry option
- [ ] "Clear all" resets all fields across the active tab

---

#### US-16.8: Audio Input Modals

**As a** musician, **I want** to attach audio references, custom voices, and playlist inspiration to my generation, **so that** the AI has richer context to work with.

**Description:**
Build the three audio input modals: Add Audio (remix from workspace/upload from disk/record from mic), Add Voice (select a custom voice model), and Add Inspiration (reference a playlist). These are accessible from both Simple and Advanced creation modes.

**Functional Requirements:**
- Add Audio modal with three sub-tabs:
  - Remix: search and select a clip from workspace or public songs
  - Upload: drag-and-drop or file picker for local audio (WAV, FLAC, MP3, OGG, AAC, AIFF)
  - Record: browser microphone recording with start/stop/preview controls
- Add Voice modal: list of user's custom voice models with preview playback, select one
- Add Inspiration modal: list of user's playlists, select one as inspirational context
- Selected inputs display as removable chips/badges on the creation form
- Each input is sent as part of the generation API request

**Acceptance Criteria:**
- [ ] Add Audio modal opens with Remix, Upload, and Record tabs
- [ ] Uploading a file shows a preview and attaches it to the form
- [ ] Recording audio works via browser microphone API
- [ ] Add Voice modal lists available voice models
- [ ] Add Inspiration modal lists user's playlists
- [ ] Selected inputs appear as removable badges on the creation form

---

**Stage 16 Completion Criteria:**
- All three creation modes (Simple, Advanced, Sounds) are functional
- Model selector is accessible and affects generation requests
- Workspace panel displays clips with full search, filter, sort, and pagination
- Clip cards render all metadata and actions correctly
- Create button submits to the API and delivers results to the workspace
- Audio input modals (Add Audio, Add Voice, Add Inspiration) work end-to-end
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 17: Song Detail & Editing UI

**Overview:** Build the song detail page and the editing workflow modals that let musicians refine their compositions. This includes the full waveform player, metadata display, action menus, editing operations (extend, cover, remix, mashup, sample, replace, crop, speed, add vocal, remaster), the "Get Full Song" assembly flow, clip context menus, and generation lineage visualization. After this stage, the browser experience matches the full editing power of the CLI.

---

#### US-17.1: Song Detail Page

**As a** musician, **I want** a dedicated page for each song showing its waveform player, metadata, lyrics, lineage, and comments, **so that** I can review and share my work in full detail.

**Description:**
Build the song detail page at `/song/:id` with all content described in spec section 23: full waveform player with scrubber, song metadata (model, BPM, key, duration, created date, mastering status, distribution status), lyrics display, generation lineage, comments section, related songs panel, and full action menu.

**Functional Requirements:**
- Full waveform player with click-to-seek scrubber
- Metadata display: model version, BPM, key, duration, created timestamp, mastering status, distribution status
- Song title, artist name, and style tags prominently displayed
- Lyrics section (scrollable, synchronized if available)
- Like / Dislike / Share / Publish inline controls
- Comments section (visible for public songs)
- Related/similar songs panel (right side or below)
- Full action menu accessible from a primary button

**Acceptance Criteria:**
- [ ] Song detail page loads at `/song/:id` with correct song data
- [ ] Waveform player renders and supports click-to-seek
- [ ] All metadata fields display correctly
- [ ] Lyrics section renders with structure tags formatted
- [ ] Like/dislike/share/publish actions work inline
- [ ] Related songs panel shows relevant suggestions

---

#### US-17.2: Full Action Menu

**As a** musician, **I want** access to all edit, remix, and export operations from the song detail page, **so that** I can perform any action on a song without navigating elsewhere.

**Description:**
Implement the full action menu combining clip card actions and song-level operations. This is the central hub for all operations a musician can perform on a song.

**Functional Requirements:**
- Menu accessible from a primary action button on the song detail page
- Actions grouped by category:
  - Edit: Remix, Edit (Repaint), Open in Editor, Open in Studio
  - Create: Cover, Extend, Mashup, Sample from Song, Use as Inspiration
  - Audio: Add Vocal, Remaster, Replace Section, Crop, Adjust Speed
  - Export: Send to Mastering, Export to DAW, Create Music Video, Download (MP3/WAV/FLAC/Stems)
  - Manage: Publish/Unpublish, Delete
- Each action opens the appropriate modal, panel, or navigates to the relevant page
- Pro-only actions show a badge for free-tier users

**Acceptance Criteria:**
- [ ] Action menu renders all operations grouped by category
- [ ] Each action triggers the correct workflow (modal, navigation, or inline)
- [ ] Pro-only actions are visually distinguished for free-tier users
- [ ] Menu is keyboard navigable and accessible

---

#### US-17.3: Editing Workflow Modals

**As a** musician, **I want** modal-based editing workflows for extend, cover, remix, mashup, sample, replace section, crop, speed adjust, add vocal, and remaster, **so that** I can refine my songs through the browser.

**Description:**
Build modal or panel-based UIs for each editing workflow from spec sections 10-19. Each modal presents the relevant controls, submits to the API, and delivers results to the workspace.

**Functional Requirements:**
- Extend modal: extension point selector (end or timestamp), duration, style override, lyrics continuation
- Cover modal: target style input, voice model selector, lyrics override
- Remix modal: new style descriptors, parameter overrides
- Mashup modal: multi-clip selector (2+), blend mode (layered/sequential/AI-guided), style override
- Sample from Song modal: waveform range selector, sample role picker, generation prompt
- Replace Section modal: waveform range selector, replacement instructions, lock-context toggle
- Crop modal: waveform range selector, snap-to-beat toggle, fade-in/fade-out controls
- Adjust Speed modal: speed multiplier slider (0.5x-2.0x), preserve pitch toggle, target BPM input
- Add Vocal modal: lyrics input, voice model selector, vocal style descriptors
- Remaster: one-click action (no modal, shows progress indicator)
- All modals show a progress state during processing and deliver results to the workspace

**Acceptance Criteria:**
- [ ] Each editing modal opens with the correct controls for its workflow
- [ ] Form validation prevents invalid submissions (e.g., empty required fields)
- [ ] Submitting a modal triggers the correct API endpoint
- [ ] Results appear as new clips in the workspace upon completion
- [ ] Remaster triggers immediately without a modal and shows progress

---

#### US-17.4: Get Full Song Flow

**As a** musician, **I want** to automatically extend a short clip into a full-length song with section-by-section review, **so that** I can build a complete composition from a seed idea.

**Description:**
Implement the "Get Full Song" flow from spec section 21. The system plans a song structure, executes sequential extends, and presents each section for review before continuing.

**Functional Requirements:**
- Triggered from clip cards (clips under ~60 seconds) or song detail page
- Displays planned song structure (intro, verse, chorus, verse, chorus, bridge, outro)
- Generates sections sequentially with progress indication
- After each section: preview playback, accept or reject
- Rejected sections can be regenerated with modified instructions
- Final assembly produces a single clip containing all accepted sections
- Target duration: ~3-4 minutes (configurable)

**Acceptance Criteria:**
- [ ] Flow is available on clips shorter than ~60 seconds
- [ ] Planned structure is displayed before generation begins
- [ ] Each section can be previewed, accepted, or rejected
- [ ] Rejected sections can be regenerated with new instructions
- [ ] Final assembled clip appears in the workspace

---

#### US-17.5: Clip Context Menu

**As a** musician, **I want** a context menu on every clip with all available actions including mastering, DAW export, video, and download options, **so that** I can perform any operation from wherever a clip appears.

**Description:**
Build the three-dot (more options) context menu for clip cards with the full action list from spec section 9.2. This menu is reused across the workspace panel, library, search results, and any other location where clip cards appear.

**Functional Requirements:**
- Three-dot icon button opens a dropdown menu
- Menu items: Remix/Edit, Open in Studio, Open in Editor (Pro), Cover, Extend, Mashup, Sample from Song (Beta), Use as Inspiration, Send to Mastering, Export to DAW, Create Music Video, Download submenu (MP3/WAV/FLAC/Stems), Delete
- Download submenu expands on hover/click
- Delete requires confirmation dialog
- Menu items trigger appropriate modals, navigation, or API calls
- Context-sensitive: some items hidden based on clip state (e.g., no "Get Full Song" on long clips)

**Acceptance Criteria:**
- [ ] Context menu renders all action items from spec section 9.2
- [ ] Download submenu expands to show format options
- [ ] Delete shows a confirmation dialog before proceeding
- [ ] Menu items correctly trigger their respective workflows
- [ ] Context menu renders consistently across all clip card locations

---

#### US-17.6: Like, Dislike, Share, and Publish Actions

**As a** musician, **I want** inline like, dislike, share, and publish controls on clips and song detail pages, **so that** I can engage with content and control visibility without extra steps.

**Description:**
Implement inline action buttons that appear on clip cards and song detail pages. These are the primary engagement and visibility controls.

**Functional Requirements:**
- Like button (heart icon): toggles liked state, updates count, persists to API
- Dislike button: toggles dislike state, affects recommendations
- Share button: opens share modal with copy-link, and social sharing options
- Publish button: toggles between private/unlisted/public visibility states
- Publishing requires a title and at least one style tag; prompt if missing
- Optimistic UI updates with rollback on API failure

**Acceptance Criteria:**
- [ ] Like/dislike toggle states correctly and persist after page reload
- [ ] Share modal provides a copyable link
- [ ] Publish toggle changes visibility state with API confirmation
- [ ] Publishing without a title or style tag shows a prompt to add them
- [ ] UI updates optimistically and rolls back on error

---

#### US-17.7: Generation Lineage Visualization

**As a** musician, **I want** to see the generation history of a clip showing its parent clips, **so that** I can trace how a song evolved through remixes, extends, and covers.

**Description:**
Display the generation lineage on the song detail page. Show parent clips (the clips this song was derived from) as a visual chain or tree, with clickable links to each ancestor.

**Functional Requirements:**
- Lineage section on the song detail page
- Shows parent clip(s) with thumbnails, titles, and relationship labels (e.g., "Remixed from," "Extended from," "Cover of")
- Each parent is clickable, navigating to its song detail page
- For multi-parent operations (mashup): show all source clips
- Visual representation as a horizontal chain or simple tree

**Acceptance Criteria:**
- [ ] Lineage section displays parent clips with correct relationship labels
- [ ] Clicking a parent navigates to that clip's song detail page
- [ ] Mashup clips show multiple parents
- [ ] Clips with no parents (original generations) show "Original" or omit the section

---

**Stage 17 Completion Criteria:**
- Song detail page renders all metadata, lyrics, waveform player, and actions
- All editing workflow modals are functional and submit to the API
- "Get Full Song" flow supports section-by-section review
- Clip context menus provide access to all spec section 9.2 actions
- Like/dislike/share/publish inline actions work across all clip locations
- Generation lineage is displayed and navigable
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 18: Waveform Editor UI

**Overview:** Build the in-browser waveform-level audio editor for precise clip manipulation. This is the "Open in Editor" Pro feature from spec section 22. The editor provides zoom, region selection, cut/copy/paste, fades, gain tools, undo/redo, and repaint mode integration. All edits are non-destructive — they create new clip versions.

---

#### US-18.1: Waveform Display with Zoom and Scroll

**As a** musician, **I want** a full waveform display with zoom and scroll controls, **so that** I can see and navigate the audio at any level of detail.

**Description:**
Render the clip's audio waveform in a scrollable, zoomable canvas. The waveform is the foundation of all editor interactions — region selection, editing operations, and repaint mode all depend on accurate waveform rendering.

**Functional Requirements:**
- Full waveform rendered from the clip's audio data
- Horizontal zoom: zoom in/out via scroll wheel, pinch gesture, or +/- buttons
- Zoom range from full-clip overview to sample-level detail
- Horizontal scroll when zoomed in (scroll bar and drag)
- Playhead indicator showing current playback position
- Time ruler above the waveform (mm:ss or bars+beats)
- Click on waveform sets the playhead position
- Responsive: fills available width of the editor panel

**Acceptance Criteria:**
- [ ] Waveform renders accurately for the loaded clip
- [ ] Zoom in/out works smoothly with visible detail change
- [ ] Scrolling navigates through a zoomed-in waveform
- [ ] Playhead moves during playback and can be repositioned by clicking
- [ ] Time ruler labels update correctly at different zoom levels

---

#### US-18.2: Region Selection and Clipboard Operations

**As a** musician, **I want** to select a time range and perform cut, copy, paste, and delete operations, **so that** I can rearrange and restructure audio precisely.

**Description:**
Click-and-drag on the waveform to select a time range. Selected regions can be cut, copied, pasted at the playhead, or deleted. These are the fundamental editing primitives.

**Functional Requirements:**
- Click-and-drag on the waveform creates a highlighted region selection
- Selection handles at start/end for fine adjustment
- Keyboard shortcuts: Ctrl+X (cut), Ctrl+C (copy), Ctrl+V (paste at playhead), Delete (delete region)
- Cut: removes selected audio, shifts remaining audio left
- Copy: copies selected audio to clipboard (in-app, not system clipboard)
- Paste: inserts clipboard audio at the current playhead position
- Delete: removes selected audio, shifts remaining audio left (same as cut without copy)
- Selection info display: start time, end time, duration

**Acceptance Criteria:**
- [ ] Click-and-drag creates a visible selection region
- [ ] Selection handles allow fine-tuning start and end points
- [ ] Cut removes audio and shortens the clip
- [ ] Copy + paste duplicates audio at the playhead position
- [ ] Delete removes selected audio
- [ ] Keyboard shortcuts work correctly

---

#### US-18.3: Fades and Gain Tools

**As a** musician, **I want** to apply fade-in, fade-out, crossfade, normalize, silence, and gain adjustments, **so that** I can polish transitions and levels within a clip.

**Description:**
Provide toolbar tools for common audio processing operations on selected regions or the entire clip. These are non-destructive and preview in real time.

**Functional Requirements:**
- Fade-in: applies a linear or logarithmic fade to the start of a selection
- Fade-out: applies a fade to the end of a selection
- Crossfade: blends two adjacent regions with configurable overlap duration
- Normalize: scales audio to peak at 0 dB (or a specified level)
- Silence: replaces selected region with silence
- Gain adjustment: slider or numeric input to raise/lower volume of selection (in dB)
- Real-time preview of gain changes before applying
- All tools accessible from a toolbar above the waveform

**Acceptance Criteria:**
- [ ] Fade-in and fade-out are audible in the affected region
- [ ] Crossfade creates a smooth transition between adjacent regions
- [ ] Normalize adjusts peak level to the target
- [ ] Silence replaces the selection with zero audio
- [ ] Gain adjustment changes volume by the specified dB amount
- [ ] All tools are accessible from the editor toolbar

---

#### US-18.4: Undo/Redo and Non-Destructive Editing

**As a** musician, **I want** unlimited undo/redo and non-destructive editing, **so that** I can experiment freely without fear of losing my work.

**Description:**
Maintain an undo/redo stack for all editor operations. Every edit creates a new version — the original clip is never modified. The musician can revert any number of steps or save the current state as a new clip version.

**Functional Requirements:**
- Unlimited undo/redo stack (persists for the editing session)
- Keyboard shortcuts: Ctrl+Z (undo), Ctrl+Shift+Z (redo)
- Undo/redo buttons in the toolbar with disabled state when at stack boundary
- "Save as new version" button creates a new clip in the workspace
- Original clip is preserved unchanged
- History panel (optional) showing the list of operations performed

**Acceptance Criteria:**
- [ ] Undo reverts the last operation and redo re-applies it
- [ ] Multiple undos walk back through the full operation history
- [ ] "Save as new version" creates a new clip in the workspace with correct lineage
- [ ] Original clip remains unchanged after any number of edits
- [ ] Undo/redo buttons are disabled when at the start/end of the stack

---

#### US-18.5: Repaint Mode Integration

**As a** musician, **I want** to select a range in the editor and regenerate that section with a new prompt, **so that** I can use AI to fix or reimagine specific parts of a clip.

**Description:**
Integrate the Repaint/Edit workflow (spec section 10.2) into the waveform editor. The musician selects a time range, provides new instructions (prompt, style, lyrics), and the AI regenerates only that section while blending seamlessly with surrounding audio.

**Functional Requirements:**
- Select a region in the waveform editor to activate Repaint mode
- Repaint panel appears with: prompt/instructions textarea, style override field, lyrics override field
- "Regenerate" button submits the selected range and instructions to the API
- Progress indicator during regeneration
- Result replaces the selected region in the editor view
- Surrounding audio is unchanged; crossfade applied at boundaries
- Result can be undone (returns to pre-repaint state)
- Save as new version to persist the change

**Acceptance Criteria:**
- [ ] Selecting a region enables the Repaint mode panel
- [ ] Providing instructions and clicking Regenerate submits to the API
- [ ] Regenerated section replaces only the selected range in the waveform
- [ ] Surrounding audio remains intact with smooth transitions
- [ ] Repaint result is undoable
- [ ] Saving creates a new clip version in the workspace

---

**Stage 18 Completion Criteria:**
- Waveform editor renders and supports zoom, scroll, and playback
- Region selection and clipboard operations (cut, copy, paste, delete) work correctly
- Fade, gain, normalize, and silence tools function as specified
- Undo/redo stack supports unlimited operations
- All edits are non-destructive (original clip preserved, new versions created)
- Repaint mode integrates AI regeneration into the editor workflow
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 19: Multi-Track Studio UI

**Overview:** Build the in-browser multi-track DAW at `/studio` — a horizontal timeline with vertically stacked track lanes, per-track controls, a master bus with EQ/compressor/limiter, and export capabilities. After this stage, a musician can arrange, layer, and mix multiple clips into a complete production entirely in the browser.

---

#### US-19.1: Studio Timeline and Track Lanes

**As a** musician, **I want** a horizontal timeline with a time ruler and vertically stacked track lanes, **so that** I can arrange multiple clips visually on a timeline.

**Description:**
Build the core Studio layout at `/studio`: a horizontal timeline with a time ruler (switchable between bars+beats and mm:ss), vertically stacked track lanes, and the ability to drag clips onto tracks. This is the spatial arrangement canvas for multi-track production.

**Functional Requirements:**
- Horizontal time ruler with bars+beats and mm:ss display modes (toggle)
- Vertically stacked track lanes; new tracks can be added
- Clips rendered as colored blocks on track lanes showing title and waveform thumbnail
- Drag-and-drop clips from workspace panel onto track lanes
- Clips can be repositioned by dragging along the timeline
- Horizontal zoom and scroll for the timeline
- Playhead with transport controls (play, pause, stop, return to start)
- Playback renders all tracks mixed together through the global player

**Acceptance Criteria:**
- [ ] Time ruler renders with correct time markings in both display modes
- [ ] Track lanes stack vertically and accept dropped clips
- [ ] Clips render as blocks with title and waveform preview
- [ ] Dragging a clip repositions it on the timeline
- [ ] Playback plays all tracks simultaneously through the global player
- [ ] Zoom and scroll work on the timeline

---

#### US-19.2: Track Types and Clip Import

**As a** musician, **I want** to create different track types (AI-generated, uploaded audio, sounds/loops, vocal stems), **so that** I can organize my arrangement by source material.

**Description:**
Support four track types from spec section 24.2. Each type has a visual indicator and accepts clips of its category. Clips can be imported from the workspace or dragged from the clip library panel.

**Functional Requirements:**
- Track type selector when adding a new track: AI-Generated, Audio, Sound/Loop, Vocal
- Track type indicated by color label and icon
- Clips from the workspace panel can be dragged onto matching track types
- Sounds/loops placed on loop tracks inherit the project tempo
- Multiple clips on the same track arranged sequentially
- Clips on different tracks play simultaneously (layered)

**Acceptance Criteria:**
- [ ] All four track types can be created
- [ ] Each type is visually distinguished by color and icon
- [ ] Clips from the workspace can be dragged onto tracks
- [ ] Multiple clips on one track play sequentially
- [ ] Clips on different tracks play simultaneously

---

#### US-19.3: Snap-to-Grid, Loop Regions, and Markers

**As a** musician, **I want** snap-to-grid, loop regions, and named markers, **so that** my arrangement stays rhythmically precise and organized.

**Description:**
Add timeline interaction features: snap-to-grid quantizes clip placement to beat divisions, loop regions define playback loops, and named markers label song sections.

**Functional Requirements:**
- Snap-to-grid toggle with configurable grid resolution (1 bar, 1 beat, 1/2 beat, 1/4 beat)
- Clip edges snap to the nearest grid line when snapping is enabled
- Loop region: draggable start/end markers on the time ruler defining a loop range
- When loop is active, playback repeats within the loop region
- Named markers: click on ruler to add a marker with a label (e.g., "Verse 1," "Chorus")
- Markers are visually displayed as flags on the time ruler
- Markers can be renamed, moved, or deleted

**Acceptance Criteria:**
- [ ] Snap-to-grid quantizes clip placement to the selected grid resolution
- [ ] Loop region causes playback to repeat within the defined range
- [ ] Named markers render on the time ruler with labels
- [ ] Markers can be added, renamed, moved, and deleted

---

#### US-19.4: Per-Track Controls

**As a** musician, **I want** volume, pan, mute, solo, color, and AI regenerate controls on each track, **so that** I can mix and refine individual elements of my arrangement.

**Description:**
Each track lane has a control strip on the left side with volume fader, pan knob, mute/solo buttons, track color selector, and an AI Regenerate button that re-generates the track's content with modified parameters.

**Functional Requirements:**
- Volume fader (vertical or horizontal slider, range: -inf to +6 dB)
- Pan knob (left-center-right, -100 to +100)
- Mute button: silences the track (visual indicator on muted track)
- Solo button: solos the track (mutes all others; multiple solos allowed)
- Track color selector: choose a color label for visual organization
- AI Regenerate button: opens a prompt dialog to regenerate the track's clip(s) with new parameters
- Track name (editable inline)

**Acceptance Criteria:**
- [ ] Volume fader changes the track's playback level
- [ ] Pan knob shifts the track's stereo position
- [ ] Mute silences the track; solo mutes all non-soloed tracks
- [ ] Track color is selectable and visually applied
- [ ] AI Regenerate opens a prompt and generates a new clip for the track
- [ ] Track name is editable inline

---

#### US-19.5: Master Bus Controls

**As a** musician, **I want** a master bus with volume, EQ, compressor, and limiter, **so that** I can shape the overall mix before exporting.

**Description:**
Build the master bus section with master volume, 3-band EQ (low/mid/high shelf), compressor (threshold, ratio, attack, release), and limiter. These controls affect the summed output of all tracks.

**Functional Requirements:**
- Master volume fader
- 3-band EQ: low shelf, mid peak, high shelf with frequency and gain controls
- Compressor: threshold, ratio, attack, release knobs
- Limiter: ceiling knob
- All controls update the audio output in real time
- Visual metering (peak and RMS levels for left/right channels)

**Acceptance Criteria:**
- [ ] Master volume controls the overall output level
- [ ] EQ bands audibly affect the frequency spectrum
- [ ] Compressor and limiter respond to dynamics as expected
- [ ] Visual metering shows peak and RMS levels in real time

---

#### US-19.6: Studio Export and Handoff

**As a** musician, **I want** to export a mixdown, send to mastering, and export for DAW from the studio, **so that** I can finalize and distribute my multi-track production.

**Description:**
Add export capabilities to the Studio: "Export Mixdown" bounces all tracks to a single file, "Send to Mastering" exports the mixdown and opens the mastering pipeline, and "Export for DAW" exports individual track stems with project metadata.

**Functional Requirements:**
- Export Mixdown: bounces all tracks to a single WAV file (48kHz, 24-bit), saves to workspace
- Send to Mastering button on the master bus: triggers mixdown export, then navigates to `/release` mastering tab with the mixdown pre-selected
- Export for DAW button: exports individual track stems as WAV files + project metadata JSON (tempo, markers, track names), packaged as a ZIP
- Format selection for mixdown: WAV, FLAC, MP3
- Progress indicator during export
- Exported files registered in workspace with "Studio" metadata badge

**Acceptance Criteria:**
- [ ] Export Mixdown produces a single playable audio file
- [ ] Send to Mastering navigates to the mastering page with the mixdown pre-loaded
- [ ] Export for DAW produces a ZIP with stems and metadata JSON
- [ ] Export progress is visible to the user
- [ ] Exported clips appear in the workspace with correct metadata

---

**Stage 19 Completion Criteria:**
- Studio page renders a functional multi-track timeline with drag-and-drop clips
- All four track types are supported
- Snap-to-grid, loop regions, and markers work correctly
- Per-track controls (volume, pan, mute, solo, color, AI regenerate) function as specified
- Master bus provides volume, EQ, compressor, and limiter
- Export mixdown, send to mastering, and DAW export all work
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 20: Discovery & Social UI

**Overview:** Build the discovery, search, playlist, feed, profile, and notification pages that transform the platform from a creation tool into a social music community. After this stage, musicians can explore trending content, find music by genre or attribute, curate playlists, scroll a short-form feed, follow other creators, and receive notifications.

---

#### US-20.1: Explore Page

**As a** listener, **I want** an Explore page showing trending songs, genre channels, staff picks, new releases, and charts, **so that** I can discover new music across the platform.

**Description:**
Build the Explore page at `/explore` with content sections from spec section 28: Trending (24h and 7d filters), Genre Channels, Staff Picks, New Releases, and Charts. Each section is a horizontally scrollable row of clip cards or a grid.

**Functional Requirements:**
- Trending section with 24h/7d time range toggle
- Genre Channels: horizontal row of genre tiles (Rock, Electronic, Hip Hop, Classical, etc.) linking to genre-filtered views
- Staff Picks: editorially curated highlights
- New Releases: chronological feed of recently published songs
- Charts: Top clips by plays, likes, or shares with ranking numbers
- Each song is a clickable clip card linking to the song detail page
- Sections are lazy-loaded for performance

**Acceptance Criteria:**
- [ ] Explore page renders all five content sections
- [ ] Trending section filters by 24h and 7d correctly
- [ ] Genre tiles navigate to genre-filtered views
- [ ] Charts display ranking numbers alongside clip cards
- [ ] Clicking any clip navigates to its song detail page

---

#### US-20.2: Search Page

**As a** listener, **I want** to search for songs by text, filter by genre, BPM, key, duration, and model, and sort results, **so that** I can find exactly the music I am looking for.

**Description:**
Build the Search page at `/search` with full-text search, attribute filters, and sort options from spec section 29.

**Functional Requirements:**
- Search input with real-time results (debounced)
- Search targets: song titles, lyrics, style tags, artist/username, playlists
- Filter panel: genre, BPM range, key, duration range, model version, creation date
- Sort options: relevance, newest, most popular
- Results rendered as clip cards in a grid or list view
- Empty state with helpful suggestions
- URL query parameters for shareable search links

**Acceptance Criteria:**
- [ ] Search returns results matching the query across titles, lyrics, tags, and artists
- [ ] Filters narrow results correctly (e.g., BPM 120-140 returns only clips in that range)
- [ ] Sort changes the ordering of results
- [ ] Search state is reflected in the URL for sharing
- [ ] Empty queries show an empty state with suggestions

---

#### US-20.3: Playlists

**As a** musician, **I want** to create, manage, and share playlists with custom cover art, **so that** I can curate collections of music and use them as inspiration for new generations.

**Description:**
Build playlist CRUD, song management, visibility controls, cover art, and the "Use as Inspiration" feature from spec section 30.

**Functional Requirements:**
- Create playlist: name input, optional description
- Rename and delete playlists (delete with confirmation)
- Add/remove songs from a playlist
- Drag-to-reorder songs within a playlist
- Public/private visibility toggle
- Cover art: auto-generated mosaic from first 4 song thumbnails, or custom upload
- Share link for public playlists
- "Use as Inspiration" button: feeds the playlist into a new generation as context (links to Add Inspiration modal)
- Playlist detail page showing all songs with playback controls

**Acceptance Criteria:**
- [ ] Playlists can be created, renamed, and deleted
- [ ] Songs can be added, removed, and reordered
- [ ] Public/private toggle changes playlist visibility
- [ ] Cover art shows auto-mosaic by default and supports custom upload
- [ ] "Use as Inspiration" opens the creation page with the playlist as context
- [ ] Share link works for public playlists

---

#### US-20.4: Short-Form Feed

**As a** listener, **I want** a vertical-scroll feed of short audio clips that auto-play as I scroll, **so that** I can discover music in a fast, engaging format.

**Description:**
Build the short-form feed at `/feed` from spec section 26. Each item is a full-screen or large-card audio player that auto-plays when scrolled into view, with title/artist/tag overlays and action buttons.

**Functional Requirements:**
- Vertical scroll layout with one item per viewport height (or large card)
- Auto-play audio when item scrolls into view; pause when it scrolls out
- Song title, artist name, and style tags as overlays on the card
- Action buttons: like, share, remix, use as inspiration
- Swipe or scroll to advance to the next item
- Feed algorithm: mix of trending clips, genre-matched recommendations, and followed-artist content
- Loading indicator for next items (infinite scroll)

**Acceptance Criteria:**
- [ ] Feed renders items in a vertical scroll layout
- [ ] Audio auto-plays when an item enters the viewport and pauses when it leaves
- [ ] Overlays display song title, artist, and style tags
- [ ] Like, share, remix, and use-as-inspiration buttons are functional
- [ ] Infinite scroll loads more items as the user reaches the bottom

---

#### US-20.5: Profile Page

**As a** listener, **I want** to view a musician's public profile showing their avatar, bio, published songs, playlists, and follower counts, **so that** I can explore their work and follow them.

**Description:**
Build the public profile page at `/@username` from spec section 32. Displays the creator's identity, published content, and social connections.

**Functional Requirements:**
- Avatar, display name, and bio prominently displayed
- Style tags rendered as pill badges
- Published songs grid (paginated)
- Playlists section
- Follower and following counts
- Follow/unfollow button (for authenticated users viewing others' profiles)
- Tab navigation between songs, playlists, and about sections
- Profile URL matches the user's handle (`/@username`)

**Acceptance Criteria:**
- [ ] Profile page loads at `/@username` with correct user data
- [ ] Published songs render in a grid with clip cards
- [ ] Follow button toggles follow state and updates follower count
- [ ] Style tags render as pill badges
- [ ] Playlists section shows the user's public playlists

---

#### US-20.6: Notifications Page

**As a** musician, **I want** a notifications page showing likes, remixes, followers, generation completions, mastering status, and distribution updates, **so that** I stay informed about activity related to my music.

**Description:**
Build the notifications page at `/notifications` from spec section 31. Each notification type has a distinct icon and links to the relevant content.

**Functional Requirements:**
- Notification types: liked/shared your song, remixed your song, new follower, generation complete, mastering job complete, distribution status update, system announcements
- Each notification shows: icon, message, timestamp, and link to relevant content
- Unread indicator (dot or badge) on unread notifications
- Mark as read (individual and mark all as read)
- Bell icon in sidebar shows unread count badge
- Real-time updates (WebSocket or polling) for new notifications
- Notification list is paginated or infinite-scroll

**Acceptance Criteria:**
- [ ] Notifications page lists all notification types with correct icons and messages
- [ ] Clicking a notification navigates to the relevant content (song, profile, release)
- [ ] Unread notifications show a visual indicator
- [ ] "Mark all as read" clears unread indicators
- [ ] Bell icon in sidebar shows unread count

---

#### US-20.7: Publish and Visibility Controls

**As a** musician, **I want** to set my clips as private, unlisted, or public from any clip location, **so that** I control who can see my work.

**Description:**
Implement the three-state visibility toggle (private, unlisted, public) from spec section 33. Publishing requires a title and at least one style tag.

**Functional Requirements:**
- Visibility toggle accessible from clip card, song detail page, and workspace
- Three states: Private (default), Unlisted (link-only access), Public (visible in feeds/search/explore)
- Publishing to Public requires: title is set and at least one style tag exists
- If requirements are not met, show an inline prompt to add the missing fields
- State change persists immediately via API
- Visual badge on clip cards indicating current visibility state

**Acceptance Criteria:**
- [ ] Visibility toggle switches between private, unlisted, and public
- [ ] Publishing without a title or style tag shows a prompt
- [ ] Visibility change persists after page reload
- [ ] Clip cards show a badge indicating current visibility state
- [ ] Unlisted clips are accessible via direct link but not in search/explore

---

**Stage 20 Completion Criteria:**
- Explore page displays trending, genres, staff picks, new releases, and charts
- Search returns results with filtering and sorting
- Playlists support full CRUD, reordering, cover art, and "Use as Inspiration"
- Short-form feed auto-plays audio on scroll
- Profile pages display public content and support follow/unfollow
- Notifications render all types with real-time updates
- Publish/visibility controls enforce title and style tag requirements
- All features covered by tests (unit + E2E with Playwright)

---

### Stage 21: Mastering & Distribution UI

**Overview:** Build the release management pages where musicians master their songs through external services and distribute them to streaming platforms. This includes the mastering workflow (profile selection, service selection, multi-preview, A/B compare), distribution metadata forms, cover art, ISRC/UPC codes, SoundCloud OAuth, and a status dashboard. After this stage, the full prompt-to-distribution pipeline is operable through the browser.

---

#### US-21.1: Release Page Layout

**As a** musician, **I want** a dedicated release page with Mastering and Distribute tabs, **so that** I have a single destination for preparing and shipping my music.

**Description:**
Build the release page at `/release` with two primary tabs: Mastering and Distribute. The page accepts a song selection (from workspace, studio mixdown, or direct navigation) and guides the musician through mastering and distribution in sequence.

**Functional Requirements:**
- Route: `/release` with Mastering and Distribute tab navigation
- Song selector: choose a song from workspace or arrive with a pre-selected song (e.g., from "Send to Mastering" in Studio)
- Selected song summary: thumbnail, title, duration, current mastering/distribution status
- Tab state persisted in URL (e.g., `/release?tab=mastering`)
- Mastering tab is the default landing

**Acceptance Criteria:**
- [ ] Release page loads at `/release` with Mastering and Distribute tabs
- [ ] Song selector allows choosing from workspace clips
- [ ] Pre-selected song from Studio or clip context menu is loaded automatically
- [ ] Selected song summary displays correctly
- [ ] Tab navigation updates the URL and persists on refresh

---

#### US-21.2: Mastering Workflow

**As a** musician, **I want** to choose a mastering profile and service, preview up to 5 masters, and A/B compare with the original, **so that** I can get a professional-quality master tuned to my target platform.

**Description:**
Build the mastering tab workflow from spec section 41.3: profile selection, service selection, preview generation, audition, A/B comparison, and approval.

**Functional Requirements:**
- Mastering profile selector: Streaming (-14 LUFS), SoundCloud (-12 LUFS), Club/DJ, Vinyl, Custom (user-specified LUFS target)
- Service selector: Dolby.io (default), LANDR, Bakuage
- "Start Mastering" button submits the job
- Preview section: up to 5 mastered versions with playback controls
- A/B compare toggle: switch between original mix and mastered version during playback
- Approve button: selects the preferred master, saves to workspace with "Mastered" badge
- Mastering metrics display (when available): loudness (LUFS), EQ bands, stereo image
- Error state with retry option if mastering fails

**Acceptance Criteria:**
- [ ] All five mastering profiles are selectable
- [ ] All three mastering services are selectable
- [ ] Mastering job submits and shows progress
- [ ] Previews are playable when ready
- [ ] A/B toggle switches between original and mastered audio during playback
- [ ] Approving a master saves it to the workspace with the correct badge

---

#### US-21.3: Mastering Status Tracking

**As a** musician, **I want** to see the real-time status of my mastering jobs, **so that** I know when my masters are ready for review.

**Description:**
Display mastering job status as it progresses through the pipeline: Queued, Processing, Preview Ready, Approved, or Failed. Status updates in real time without requiring page refresh.

**Functional Requirements:**
- Status indicators: Queued, Processing, Preview Ready, Approved, Failed
- Real-time status updates (polling or WebSocket)
- Progress visualization (spinner, progress bar, or step indicator)
- Failed state shows error message and retry button
- Status visible on the mastering tab and in the notifications page
- History of past mastering jobs with their status and approved results

**Acceptance Criteria:**
- [ ] Status updates display in real time as the job progresses
- [ ] Each status state is visually distinct
- [ ] Failed jobs show an error message with a retry option
- [ ] Approved masters are accessible from the mastering history
- [ ] Mastering completion triggers a notification

---

#### US-21.4: Distribution Metadata Form

**As a** musician, **I want** a pre-populated metadata form for my release, **so that** I can review and edit song details before distributing.

**Description:**
Build the distribution tab metadata form from spec section 42.3-42.4. Fields are pre-populated from the song's existing metadata. The form includes cover art selection/generation and ISRC/UPC codes.

**Functional Requirements:**
- Pre-populated fields: title, artist, album name, genre, description, BPM, key, language, explicit content flag
- Editable fields: all pre-populated fields plus release date, copyright notice, credits (producer, songwriter, performer)
- Cover art section: select existing art, upload new art (3000x3000 minimum, JPG/PNG), or generate via AI (links to cover art generation)
- ISRC field: enter existing code or generate a new one
- UPC/EAN field: enter existing code or generate a new one
- Lyrics field: pre-populated, editable (synced or unsynced)
- Form validation: required fields highlighted, resolution check on cover art
- Save as draft functionality

**Acceptance Criteria:**
- [ ] Metadata form pre-populates from the selected song's data
- [ ] All fields are editable
- [ ] Cover art upload enforces 3000x3000 minimum resolution
- [ ] ISRC and UPC codes can be entered or auto-generated
- [ ] Form validation highlights missing required fields
- [ ] Draft can be saved and resumed later

---

#### US-21.5: Distribution Target Selection and SoundCloud OAuth

**As a** musician, **I want** to select distribution targets and connect my SoundCloud account, **so that** my music reaches listeners on their preferred platforms.

**Description:**
Build the distribution target selection UI and SoundCloud OAuth connection flow. SoundCloud is fully automated; LANDR and DistroKid are guided workflows with package preparation.

**Functional Requirements:**
- Target selection: SoundCloud (auto), LANDR (guided), DistroKid (guided)
- SoundCloud OAuth connect button: initiates OAuth 2.1 flow, stores token
- Connected SoundCloud account displays username and avatar
- Disconnect option for SoundCloud
- LANDR/DistroKid guided flow: prepares distribution package, provides instructions, opens external service in new tab
- Target-specific requirements displayed (e.g., SoundCloud metadata fields, LANDR format requirements)

**Acceptance Criteria:**
- [ ] SoundCloud OAuth connect flow completes and stores credentials
- [ ] Connected SoundCloud account shows username and avatar
- [ ] SoundCloud can be disconnected
- [ ] LANDR guided flow prepares package and opens LANDR in a new tab
- [ ] Target-specific requirements are displayed for each distribution channel

---

#### US-21.6: Distribution Status Dashboard and Review Screen

**As a** musician, **I want** to see the status of my distributions and review all assets before submission, **so that** I can track my releases and catch issues before they go live.

**Description:**
Build the distribution status dashboard from spec section 42.5 and the review/summary screen from spec section 42.4 step 7. The dashboard tracks releases through their lifecycle; the review screen provides a final check before submission.

**Functional Requirements:**
- Review/summary screen: displays all metadata, cover art, audio file details, selected targets, and ISRC/UPC before submission
- "Submit" button on review screen: triggers SoundCloud upload (auto) or opens guided flow
- Distribution status dashboard: shows all releases with status badges
- Status states: Draft, Ready, Submitted, In Review, Live, Rejected
- Rejected status shows the reason from the platform
- Status updates via real-time polling or notifications
- Direct links to live releases on external platforms

**Acceptance Criteria:**
- [ ] Review screen displays complete release package for final verification
- [ ] Submission triggers the correct workflow for each target
- [ ] Status dashboard shows all releases with correct status badges
- [ ] Status updates reflect changes from external platforms
- [ ] Rejected releases display the rejection reason
- [ ] Live releases link to their external platform pages

---

**Stage 21 Completion Criteria:**
- Release page provides mastering and distribution workflows in a single destination
- Mastering supports profile/service selection, multi-preview, A/B compare, and approval
- Mastering status tracks jobs in real time through all pipeline stages
- Distribution metadata form pre-populates and validates all required fields
- SoundCloud OAuth connect flow works end-to-end
- Distribution status dashboard tracks releases from draft to live
- Review screen provides a final verification before submission
- All features covered by tests (unit + E2E with Playwright)

---

## Layer 4: Advanced Integrations

*Goal: Extend the platform with music video generation, DAW-native creation via VST3 plugin, custom voice models, monetization, content safety, and production hardening.*

---

### Stage 22: Music Video Generator

**Overview:** Enable musicians to create AI-generated music videos from their songs. This stage integrates a backend video generation API, provides a dedicated video creation page, and includes basic editing tools — turning audio-only tracks into shareable visual content without leaving the platform.

**Spec Reference:** §40

---

#### US-22.1: Video Generation Backend Integration

**As a** developer, **I want** a backend service that communicates with an AI video generation API, **so that** the platform can render music videos from audio and visual prompts.

**Description:**
Integrate with an external AI video generation provider (e.g., Runway, Pika, or similar). The backend accepts a source audio file, a visual style prompt, optional reference images, and generation options, then submits a rendering job and tracks it to completion. This is the foundational plumbing for the entire video feature.

**Functional Requirements:**
- POST `/api/v1/videos/generate` accepts: songId, visual style prompt, reference image URLs, lyrics sync toggle, style preset, aspect ratio, resolution, frame rate, scene transitions
- Backend queues a rendering job to the video generation provider
- Job status endpoint: GET `/api/v1/videos/{jobId}/status` returns progress percentage, estimated time remaining, and current state (queued/rendering/encoding/complete/failed)
- On completion, the rendered MP4 is stored and associated with the source song
- Retry logic for transient provider failures
- Credit deduction (5–10 credits depending on resolution and duration) validated before submission

**Acceptance Criteria:**
- [ ] POST endpoint accepts valid parameters and returns a job ID
- [ ] Job status endpoint reports progress through all states to completion
- [ ] Completed video is a valid MP4 file with audio muxed in
- [ ] Insufficient credits returns a 402 error with explanation
- [ ] Provider failure triggers retry (up to 3 attempts) before marking as failed

---

#### US-22.2: Video Creation Page

**As a** musician, **I want** a dedicated video creation page where I can configure and generate a music video for my song, **so that** I have full control over the visual output.

**Description:**
The video page (`/video/:songId`) presents the source song, visual configuration options, and a generation trigger. The musician selects style, aspect ratio, resolution, and other options, then submits to generate.

**Functional Requirements:**
- Route: `/video/:songId` — loads the song's metadata, waveform, and cover art
- Source song card with playback controls, title, duration, and style tags
- Visual style prompt textarea for free-form description of desired video aesthetic
- Reference images upload (up to 5 images) to guide visual style
- Lyrics sync toggle — if enabled, lyrics appear as animated text overlays synced to the audio
- Style presets selector: Abstract, Cinematic, Animated, Lyric Video, Live Performance, Nature
- Aspect ratio picker: 16:9 (landscape), 9:16 (vertical/social), 1:1 (square)
- Resolution selector: 720p (Free), 1080p (Pro), 4K (Pro) — Pro options gated by subscription
- Frame rate: 24fps, 30fps, 60fps
- Scene transitions: Auto (AI-driven), Cut, Fade, Dissolve
- "Generate Video" button — disabled until source song is selected and at least a style prompt or preset is chosen
- Credit cost estimate displayed before submission

**Acceptance Criteria:**
- [ ] Page loads with song metadata and all configuration controls visible
- [ ] Style presets populate the style prompt with preset-specific text
- [ ] Pro-gated options (1080p, 4K) show a Pro badge and upgrade prompt for Free users
- [ ] Generate button submits to the backend and transitions to a progress view
- [ ] All aspect ratio and resolution combinations are selectable

---

#### US-22.3: Video Rendering Progress and Delivery

**As a** musician, **I want** to see real-time progress while my video renders and receive it when complete, **so that** I know the status and can plan accordingly.

**Description:**
Video rendering is a long-running job (minutes to tens of minutes depending on duration and resolution). The progress view keeps the musician informed and delivers the final video with download and publish options.

**Functional Requirements:**
- Progress view replaces the generation form after submission
- Progress bar with percentage, estimated time remaining, and current phase (analyzing audio, generating scenes, encoding)
- In-browser notification when rendering completes (even if the user navigated away)
- Video player with the rendered result, full playback controls
- Download button: MP4 (H.264 by default, H.265 for 4K)
- "Publish to Platform" button — makes the video publicly visible on the song detail page
- "Export for Social" — provides optimized versions for YouTube (16:9), TikTok/Reels (9:16), and Instagram (1:1)

**Acceptance Criteria:**
- [ ] Progress bar updates at least every 5 seconds during rendering
- [ ] Notification fires on completion if user navigated away
- [ ] Completed video is playable in-browser
- [ ] Download produces a valid MP4 with correct resolution and audio
- [ ] Publish makes the video visible on the song detail page

---

#### US-22.4: Basic Video Editing

**As a** musician, **I want** to make basic edits to my generated video, **so that** I can fix imperfect scenes without regenerating the entire video.

**Description:**
After a video is rendered, the musician can trim it, replace individual scenes (regenerate a time range), add or remove lyrics overlays, and adjust scene transition timing. These are non-destructive edits that produce a new version.

**Functional Requirements:**
- Trim controls: adjust start and end points of the video
- Scene replacement: select a time range, provide a new visual prompt, and regenerate only that section
- Lyrics overlay toggle: add or remove lyrics overlay post-generation
- Transition timing: drag scene transition markers to adjust cut points
- Each edit produces a new video version (original preserved)
- Edit history is maintained per video

**Acceptance Criteria:**
- [ ] Trimming produces a shorter video with clean cut points
- [ ] Scene replacement regenerates only the selected time range; surrounding video is preserved
- [ ] Adding lyrics overlay post-generation syncs text to audio
- [ ] Original video version is accessible after edits
- [ ] Edit history shows all versions with timestamps

---

### Stage 23: VST3 Plugin — Core

**Overview:** Build the foundational VST3 plugin using JUCE (C++) that connects to the locally-running ACE-Step-1.5 server. The plugin provides text-to-music generation inside any VST3-compatible DAW, with connection management, a generation panel, and a results panel for previewing and inserting clips. This brings the AI music engine directly into the musician's existing production workflow.

**Spec Reference:** §44.1–44.3, §44.6, §44.7

---

#### US-23.1: JUCE Project Setup and Cross-Platform Build

**As a** developer, **I want** a JUCE-based VST3 plugin project that builds on Windows, macOS, and Linux, **so that** we have a solid foundation for the DAW integration features.

**Description:**
Set up the JUCE project in the `plugin/` directory of the monorepo. Configure CMake for cross-platform builds producing VST3 as the primary format and AU as a secondary format for macOS. The plugin should load in a DAW and display a minimal UI.

**Functional Requirements:**
- JUCE project in `plugin/` with CMakeLists.txt
- Build targets: VST3 (all platforms), AU (macOS only)
- CI build verification for Windows (MSVC), macOS (Xcode/clang), Linux (GCC)
- Plugin loads in a DAW host without crashing (validated with pluginval or equivalent)
- Minimal placeholder UI renders (plugin name, version, empty panels)
- Installed binary size target: ~20MB
- Non-audio thread infrastructure for HTTP communication (no network calls on audio thread)

**Acceptance Criteria:**
- [ ] VST3 builds successfully on all three platforms
- [ ] AU builds on macOS
- [ ] Plugin passes pluginval validation
- [ ] Plugin loads in at least one DAW (Reaper recommended for testing) and shows UI
- [ ] Binary size is under 25MB

---

#### US-23.2: Connection Status Panel

**As a** musician, **I want** to configure and verify the connection to my local ACE-Step server from within the plugin, **so that** I know the AI engine is ready before I try to generate.

**Description:**
The connection panel is the first thing a musician sees when opening the plugin. It shows the server URL, API key field, model selector, connection test button, and a clear status indicator. The plugin requires a running ACE-Step-1.5 server at `localhost:8001` (configurable).

**Functional Requirements:**
- Server URL text field (default: `http://localhost:8001`)
- API key text field (optional, for secured setups)
- "Test Connection" button — calls the server's health endpoint
- Status indicator: Green (connected, model loaded), Yellow (connecting/testing), Red (offline/error)
- Model selector dropdown — populated from the server's available models on successful connection
- Connection settings persist between DAW sessions (saved to local config file)
- Auto-connect on plugin load (non-blocking, updates indicator when complete)

**Acceptance Criteria:**
- [ ] With ACE-Step running: Test Connection shows green indicator and populates model list
- [ ] With ACE-Step stopped: Test Connection shows red indicator with "Server unreachable" message
- [ ] Custom server URL is saved and restored across DAW sessions
- [ ] Model dropdown lists all available models from the server
- [ ] Auto-connect attempt occurs on plugin load without blocking the DAW

---

#### US-23.3: Generation Panel

**As a** musician, **I want** to enter a prompt, configure generation parameters, and trigger music generation from inside my DAW, **so that** I can create AI music without leaving my production environment.

**Description:**
The generation panel mirrors the core creation controls from the web app — prompt, lyrics, vocal language, instrumental toggle, BPM, key, duration, seed, and quality preset. The musician fills in the fields and clicks Generate. The request is sent via HTTP REST on a non-audio thread.

**Functional Requirements:**
- Prompt textarea for style/caption text
- Lyrics textarea (collapsible) with support for structure tags ([Verse], [Chorus], etc.)
- Vocal language dropdown (50+ languages)
- Instrumental toggle
- BPM field (numeric input, or "Auto")
- Key selector ("Any" or specific musical key)
- Duration field (seconds, numeric input)
- Seed field (numeric or "Random")
- Quality preset selector: Turbo / Standard / High (maps to inference steps)
- Generate button — submits to the ACE-Step REST API via non-audio HTTP thread
- Progress bar during generation (polls job status)
- Generation disabled when connection status is Red
- Text-to-Music and Cover modes selectable via a mode toggle

**Acceptance Criteria:**
- [ ] Filling in a prompt and clicking Generate produces 2 audio clips
- [ ] Progress bar updates during generation and completes when clips are ready
- [ ] All parameter fields are sent correctly to the API (verified via request logging)
- [ ] Generation does not cause audio dropouts or DAW UI freezing
- [ ] Cover mode accepts a source audio reference

---

#### US-23.4: Results Panel and Clip Insertion

**As a** musician, **I want** to preview generated clips and insert them into my DAW timeline, **so that** I can use AI-generated audio alongside my existing tracks.

**Description:**
After generation completes, the results panel shows waveform previews of the 2 generated clips. The musician can play/stop each clip, then insert it at the DAW playhead position or send it to a new track.

**Functional Requirements:**
- Waveform visualization for each of the 2 generated clips
- Play/Stop buttons per clip (audio routed through the DAW's audio engine)
- "Insert to Track" button — places the selected clip at the DAW playhead position on the plugin's track
- "Send to New Track" button — creates a new audio track in the DAW containing the clip
- Generation history: scrollable list of all generations in this session, with the ability to re-insert any past result
- Generated clips cached locally at `~/ACEStepPlugin/cache/` (configurable)
- Cache is browsable from the history panel

**Acceptance Criteria:**
- [ ] Both generated clips display waveform previews
- [ ] Play/Stop works for each clip within the DAW
- [ ] "Insert to Track" places audio at the correct playhead position
- [ ] History panel shows all generations from the current session
- [ ] Clips are persisted in the local cache directory and survive plugin close/reopen

---

#### US-23.5: Local Cache and File Management

**As a** musician, **I want** my generated clips stored locally and managed efficiently, **so that** I can access past generations without regenerating.

**Description:**
The plugin maintains a local file cache for all generated clips. The cache is organized, browsable, and configurable. This keeps the plugin lightweight (~20MB binary) while audio data lives on disk.

**Functional Requirements:**
- Default cache directory: `~/ACEStepPlugin/cache/`
- Configurable cache path via plugin settings
- Cache organized by date and generation ID
- Cache browser in the plugin UI showing past generations with metadata (prompt, date, duration)
- Delete individual cached clips or clear entire cache
- Total cache size displayed in settings
- Cache is independent of the web platform — no account required for local-only usage

**Acceptance Criteria:**
- [ ] Generated clips appear in the cache directory after generation
- [ ] Cache browser lists clips with correct metadata
- [ ] Deleting a cached clip removes it from disk and the browser
- [ ] Custom cache path is respected after configuration change
- [ ] Cache size is reported accurately in settings

---

### Stage 24: VST3 Plugin — Advanced

**Overview:** Enhance the VST3 plugin with deep DAW integration features — tempo/key sync, selection-aware generation, MIDI input, sidechain audio input, Lego mode, and bidirectional sync with the web platform. These features make the plugin feel native to the DAW workflow rather than a bolted-on tool.

**Spec Reference:** §44.4–44.5

---

#### US-24.1: DAW Tempo and Key Sync

**As a** musician, **I want** the plugin to automatically detect my DAW's BPM and key, **so that** generated music matches my project without manual configuration.

**Description:**
The plugin reads the host DAW's tempo and key signature and auto-populates the generation fields. Generated audio is time-stretched or pitch-shifted if needed to match the DAW project exactly. This removes friction and ensures every generation is immediately usable in context.

**Functional Requirements:**
- Read host BPM via JUCE's `getPlayHead()->getPosition()` API
- Read host key signature if available
- Auto-populate BPM and Key fields in the generation panel (overridable by the musician)
- "Sync" indicator shows when fields are auto-populated vs. manually set
- If DAW tempo changes during a session, the fields update accordingly
- Generated audio is time-stretched to match host BPM if the generation result differs slightly

**Acceptance Criteria:**
- [ ] Opening the plugin in a 120 BPM project auto-fills the BPM field with 120
- [ ] Changing the DAW tempo updates the plugin's BPM field
- [ ] Generated clip at 118 BPM is time-stretched to 120 BPM on insertion
- [ ] Manual BPM override disables auto-sync with a visual indicator

---

#### US-24.2: Selection-Aware Generation

**As a** musician, **I want** the plugin to use my DAW's time selection to set generation duration and insertion point, **so that** I can generate audio that fits exactly where I need it.

**Description:**
When the musician has a time selection in the DAW (e.g., bars 5–13), the plugin reads it, auto-sets the duration to match the selection length, and offers a "Generate & Insert" button that places the result precisely at the selection start.

**Functional Requirements:**
- Detect DAW time selection (start and end position) via host transport API
- Auto-set duration field to match selection length in seconds
- "Generate & Insert" button: generates and places result at the selection start on the plugin's track
- Selection info displayed in the generation panel (e.g., "Selection: bars 5–13, 16.0s")
- Works with no selection — falls back to manual duration and playhead insertion
- Duration field shows both the auto-detected value and allows manual override

**Acceptance Criteria:**
- [ ] Selecting bars 5–13 in the DAW auto-sets duration to the correct number of seconds
- [ ] "Generate & Insert" places audio starting at bar 5
- [ ] With no selection, the plugin behaves as in Stage 23 (manual duration, playhead insertion)
- [ ] Selection info is displayed correctly in the generation panel

---

#### US-24.3: MIDI Input and Sidechain Audio

**As a** musician, **I want** to feed MIDI or audio from my DAW into the plugin as creative input, **so that** I can use my own performances and existing tracks as seeds for AI generation.

**Description:**
The plugin accepts MIDI input from the DAW for "Complete" generation mode (turning a MIDI sketch into full audio) and sidechain audio input for Cover/Repaint modes (restyling an existing DAW track). These inputs deeply integrate AI generation into the production workflow.

**Functional Requirements:**
- MIDI input mode: plugin receives MIDI from the DAW (played or recorded)
- Captured MIDI is used as melodic input for the "Complete" generation mode
- "Record MIDI" toggle captures incoming MIDI to a buffer for submission
- Sidechain audio input: receive audio from a sidechain bus/send
- "Capture Sidechain" records sidechain audio for use as reference in Cover or Repaint modes
- Mode selector includes: Text to Music, Cover (sidechain), Complete (MIDI), Repaint (sidechain + time range)
- Clear indicators showing when MIDI or sidechain audio has been captured and is ready for generation

**Acceptance Criteria:**
- [ ] Playing MIDI into the plugin captures it and enables "Complete" mode generation
- [ ] Sidechain audio from another track is captured and usable as Cover reference
- [ ] Generated audio from MIDI input reflects the melodic content of the MIDI performance
- [ ] Cover mode with sidechain input produces a restyled version of the reference audio
- [ ] Mode selector correctly shows available modes based on captured inputs

---

#### US-24.4: Lego Mode and Layer-by-Layer Generation

**As a** musician, **I want** to build up a song layer by layer, generating one instrument or part at a time, **so that** I have fine-grained control over the arrangement.

**Description:**
Lego mode enables iterative layer-by-layer generation. The musician generates a drum track, then a bass line that fits the drums, then a melody on top, each on a separate DAW track. Each layer is generated with awareness of what exists already.

**Functional Requirements:**
- "Lego Mode" toggle in the generation panel
- In Lego mode, existing audio on the plugin track (or sidechain) is sent as context for the next generation
- Each generated layer is placed on a separate new track
- Layer order is tracked: the musician can regenerate any layer while keeping others
- Prompt for each layer specifies the instrument or part (e.g., "add a funky bass line")
- Context audio is mixed down and sent as reference to the API

**Acceptance Criteria:**
- [ ] Generating a drum layer, then a bass layer, produces two tracks where the bass fits the drums
- [ ] Each layer is placed on its own track in the DAW
- [ ] Regenerating one layer does not affect other layers
- [ ] Context audio is audibly reflected in the generated layer (musical coherence)

---

#### US-24.5: Platform Integration and Clip Sync

**As a** musician, **I want** to browse my web platform workspace from the plugin and push DAW clips back to the platform, **so that** my work flows seamlessly between the DAW and the web app.

**Description:**
The plugin connects to the web platform API (when authenticated) to import clips from the musician's workspace into the DAW and push locally generated clips back to the web app. This creates a bidirectional bridge between desktop production and the cloud platform.

**Functional Requirements:**
- "Import from Platform" panel: browse workspaces and clips from the web app
- Search and filter clips by title, style, date
- Download selected clip and insert into DAW track
- "Push to Platform" button on any cached clip: uploads to the musician's web app workspace
- Authentication via API key or OAuth token stored in plugin settings
- Platform sync is optional — plugin works fully offline with local ACE-Step server

**Acceptance Criteria:**
- [ ] Authenticated plugin displays the musician's web app workspaces and clips
- [ ] Importing a platform clip downloads and inserts it into the DAW
- [ ] Pushing a local clip uploads it to the web app workspace with metadata
- [ ] Plugin works without platform authentication (local-only mode)
- [ ] Connection errors to the platform do not affect local generation

---

### Stage 25: Custom Voice Models

**Overview:** Allow musicians to train personalized voice models from a small set of reference recordings. Trained models are usable across all creation modes — Simple, Advanced, Cover, Add Vocal, and Extend. Voice models are private by default and stored in a per-user library.

**Spec Reference:** §25, §39

---

#### US-25.1: Voice Model Training Backend

**As a** musician, **I want** to upload reference audio files and train a custom voice model, **so that** generated songs can use my unique vocal style.

**Description:**
The backend accepts 2–10 reference audio files, validates their quality and consistency, and queues a LoRA fine-tuning job. The resulting voice model weights are stored in the user's private voice library. Training consumes premium credits (10 credits).

**Functional Requirements:**
- POST `/api/v1/voice-models/train` accepts: 2–10 audio files (WAV, FLAC, MP3 at 16kHz+ sample rate), model name, optional description
- Validation: minimum 2 files, maximum 10, audio quality check (sample rate, duration, noise level), consistency check (similar vocal characteristics across files)
- Training job queued with estimated time (typically minutes on GPU)
- Credit validation: 10 credits deducted before training begins; insufficient credits returns 402
- On completion, LoRA weights file stored and associated with the user's account
- On failure, credits are refunded and error details are returned

**Acceptance Criteria:**
- [ ] Uploading 3 valid audio files and triggering training returns a job ID
- [ ] Validation rejects files below 16kHz sample rate with a clear error message
- [ ] Training job completes and produces a usable voice model
- [ ] 10 credits are deducted on submission; refunded on failure
- [ ] Uploading 1 file or 11 files returns a validation error

---

#### US-25.2: Training Progress and Notifications

**As a** musician, **I want** to track my voice model training progress and be notified when it completes, **so that** I know when my voice is ready to use.

**Description:**
Voice model training takes minutes to complete. The platform provides progress tracking and notifications so the musician can continue other work while training runs.

**Functional Requirements:**
- GET `/api/v1/voice-models/train/{jobId}/status` returns: progress percentage, estimated time remaining, current phase (uploading, preprocessing, training, finalizing)
- In-app notification on completion (success or failure)
- Email notification (optional, based on user notification preferences)
- Training progress visible in the voice library page
- If the user navigates away and returns, progress is restored

**Acceptance Criteria:**
- [ ] Status endpoint returns progress updates during training
- [ ] In-app notification fires on training completion
- [ ] Progress is visible in the voice library UI
- [ ] Returning to the page after navigation restores the current progress state

---

#### US-25.3: Voice Model Library

**As a** musician, **I want** a library to manage my trained voice models, **so that** I can organize, rename, and delete my custom voices.

**Description:**
Each user has a private voice model library accessible from the Library section of the platform. Models can be listed, renamed, deleted, and previewed.

**Functional Requirements:**
- GET `/api/v1/voice-models` returns all voice models for the authenticated user
- DELETE `/api/v1/voice-models/{id}` removes a voice model and its stored weights
- PATCH `/api/v1/voice-models/{id}` allows renaming and updating description
- Voice library page in the Library section (`/me` → Voices tab)
- Each voice card shows: name, description, creation date, number of reference files, training status
- Preview: generate a short sample clip using the voice model
- Voice models are private by default (not visible to other users)

**Acceptance Criteria:**
- [ ] Voice library page lists all trained voice models
- [ ] Renaming a voice model updates it everywhere it appears
- [ ] Deleting a voice model removes it from the library and frees storage
- [ ] Preview generates a short audio clip using the selected voice
- [ ] Other users cannot see or access another user's voice models

---

#### US-25.4: Voice Selection in Creation Modes

**As a** musician, **I want** to select a custom voice model when creating songs in any mode, **so that** all my music can feature my unique vocal style.

**Description:**
Custom voice models appear as an option in all creation forms — Simple, Advanced, Cover, Add Vocal, and Extend. An "Add Voice" modal lets the musician browse their voice library and attach a voice to the generation.

**Functional Requirements:**
- "Add Voice" button in the creation form opens a voice selection modal
- Modal lists all trained voice models with name, preview button, and select button
- Selected voice is shown as a pill/badge in the creation form
- Voice selection is available in: Simple mode, Advanced mode, Cover workflow, Add Vocal workflow, Extend workflow
- Voice parameter sent to the generation API alongside other parameters
- "Remove Voice" option to clear the selection and use the default model voice
- Voice selector also available in the VST3 plugin (if authenticated with the platform)

**Acceptance Criteria:**
- [ ] Voice selection modal appears and lists all trained voices
- [ ] Selecting a voice and generating produces audio with the custom vocal timbre
- [ ] Voice selection works in all five creation modes
- [ ] Removing voice selection reverts to the default model voice
- [ ] Generation without a custom voice works as before (no regressions)

---

### Stage 26: Credits & Subscription System

**Overview:** Implement the credit-based usage tracking and subscription tier system. Every generative action consumes credits. Free users get a limited monthly allocation; Pro users get more credits and unlock advanced features. This stage adds payment integration, feature gating, and a usage dashboard.

**Spec Reference:** §45

---

#### US-26.1: Credit Tracking and Deduction

**As a** musician, **I want** my credits tracked accurately per action, **so that** I know what each generation costs and how many credits I have left.

**Description:**
Every generative action has a defined credit cost. The system deducts credits atomically before processing begins and displays the remaining balance. If the musician has insufficient credits, the action is denied with a clear explanation.

**Functional Requirements:**
- Credit costs per action: generation (1), extend (1), cover (1), mashup (2), stems (1), MIDI (1), remaster (0.5), mastering (2–5), LoRA training (10), video (5–10)
- Credits are deducted atomically before the job begins (no double-deduction on retry)
- GET `/api/v1/credits/balance` returns current credit balance
- Credit balance displayed in the app header/sidebar at all times
- Insufficient credits returns 402 with: required credits, current balance, and upgrade prompt
- Credit refund on job failure (automatic)

**Acceptance Criteria:**
- [ ] Generating a song deducts exactly 1 credit
- [ ] Mashup deducts exactly 2 credits
- [ ] Attempting an action with insufficient credits returns a 402 with clear messaging
- [ ] Failed jobs result in automatic credit refund
- [ ] Credit balance is visible at all times and updates in real time after each action

---

#### US-26.2: Subscription Tiers and Feature Gating

**As a** musician, **I want** to understand what my subscription tier includes and see clear prompts to upgrade when I hit a limit, **so that** I can make informed decisions about my plan.

**Description:**
Two tiers exist: Free (50 credits/month, limited features) and Pro (500 credits/month, all features). Pro-only features show a Pro badge and an upgrade prompt for Free users. Feature gating is enforced both on the frontend (UI indicators) and backend (API authorization).

**Functional Requirements:**
- Free tier: 50 credits/month, MP3 download only, Studio view-only, no stems/MIDI export, no mastering, no distribution, VST3 preview-only, 720p watermarked video, no custom voice models
- Pro tier: 500 credits/month, all formats, full Studio editing, stems/MIDI, mastering, distribution, full VST3, 1080p/4K video, custom voice models, priority queue
- Pro badge displayed on locked features in the UI
- Clicking a locked feature shows an upgrade modal explaining the benefit
- Backend enforces tier restrictions — Free users hitting Pro endpoints receive 403 with upgrade guidance
- Credits reset monthly on the subscription anniversary date

**Acceptance Criteria:**
- [ ] Free user sees Pro badges on restricted features
- [ ] Free user clicking a Pro feature sees an upgrade modal (not an error)
- [ ] Pro user can access all features without restriction
- [ ] API returns 403 for Free users attempting Pro-only actions
- [ ] Credits reset to tier allocation on monthly anniversary

---

#### US-26.3: Payment Integration

**As a** musician, **I want** to subscribe, cancel, and manage my payment method, **so that** I can upgrade to Pro and manage my billing.

**Description:**
Integrate with a payment provider (Stripe or similar) for subscription management. The musician can subscribe to Pro, update their payment method, cancel their subscription, and switch between tiers.

**Functional Requirements:**
- Subscribe to Pro: redirects to payment provider's checkout flow
- Payment methods: credit/debit card, with potential for additional methods
- Cancel subscription: takes effect at end of current billing period (no immediate feature loss)
- Upgrade from Free to Pro: immediate access to Pro features, prorated first month
- Downgrade from Pro to Free: takes effect at end of billing period
- Billing history accessible from account settings
- Webhook handler for payment events (successful charge, failed charge, subscription canceled)

**Acceptance Criteria:**
- [ ] Subscribing to Pro via checkout flow activates Pro features immediately
- [ ] Canceling retains Pro access until the end of the billing period
- [ ] Failed payment triggers a grace period with retry before downgrade
- [ ] Billing history shows all past charges with dates and amounts
- [ ] Webhook correctly processes payment events and updates user tier

---

#### US-26.4: Credit Top-Up Purchase

**As a** musician, **I want** to buy additional credits when I run out, **so that** I can keep creating without waiting for my monthly reset.

**Description:**
Both Free and Pro users can purchase credit top-up packs. Purchased credits do not expire and are used after the monthly allocation is exhausted.

**Functional Requirements:**
- Credit packs available: 50 credits, 100 credits, 250 credits (pricing TBD)
- Purchase flow via payment provider (one-time charge, not recurring)
- Purchased credits are additive and do not expire
- Monthly credits are consumed first; purchased credits are consumed after monthly allocation is depleted
- Purchase history visible in the usage dashboard
- Credit pack purchase available from the upgrade modal and the usage dashboard

**Acceptance Criteria:**
- [ ] Purchasing a credit pack increases the credit balance by the correct amount
- [ ] Monthly credits are consumed before purchased credits
- [ ] Purchased credits persist across monthly resets (do not expire)
- [ ] Purchase history is visible in the usage dashboard

---

#### US-26.5: Usage Dashboard

**As a** musician, **I want** to see my credit usage history and breakdown by category, **so that** I can understand my usage patterns and plan accordingly.

**Description:**
A usage dashboard shows remaining credits, usage history over time, and breakdown by action category (generation, editing, mastering, video, etc.).

**Functional Requirements:**
- Usage dashboard accessible from account settings or sidebar
- Display: credits remaining (monthly + purchased), days until reset, current tier
- Usage chart: daily or weekly credit consumption over the past 30 days
- Category breakdown: pie/bar chart showing credits spent per action type
- Usage history table: date, action type, clip title, credits consumed
- Export usage data as CSV

**Acceptance Criteria:**
- [ ] Dashboard shows accurate credit balance and reset date
- [ ] Usage chart reflects actual credit consumption over time
- [ ] Category breakdown correctly attributes credits to action types
- [ ] Usage history lists all credit-consuming actions
- [ ] CSV export contains complete usage data

---

### Stage 27: Content Moderation

**Overview:** Implement automated content screening, user reporting, admin moderation tools, and an appeals workflow. This stage ensures the platform is safe and trustworthy for all users — filtering harmful content at generation time, providing reporting mechanisms, and giving admins the tools to manage issues.

**Spec Reference:** §47

---

#### US-27.1: Automated Content Screening

**As an** admin, **I want** AI-based content screening on all generation requests, **so that** harmful or prohibited content is filtered before it reaches the platform.

**Description:**
All generation requests pass through an automated screening layer that checks prompts, style descriptors, and lyrics for policy violations. Flagged content is blocked with an explanation; borderline content may be flagged for review.

**Functional Requirements:**
- Prompt filtering: scan style prompts for restricted terms and prohibited content categories
- Lyrics scanning: check lyrics for policy violations (hate speech, explicit violence, prohibited content)
- Screening runs before credits are deducted and before the generation job is submitted
- Blocked requests return a clear, non-accusatory message explaining why the content was not generated
- Borderline content is flagged for admin review but allowed to generate (with a flag on the clip)
- Screening rules are configurable by admin (allow-lists, block-lists, sensitivity thresholds)
- False positive rate should be minimized — creative expression is prioritized

**Acceptance Criteria:**
- [ ] A prompt containing clearly prohibited content is blocked with an explanation
- [ ] A normal creative prompt passes screening without delay
- [ ] Borderline content is flagged but still generates
- [ ] Blocked requests do not consume credits
- [ ] Admin can adjust screening rules without a code deploy

---

#### US-27.2: User Reporting

**As a** listener, **I want** to report public clips that violate community guidelines, **so that** I can help keep the platform safe.

**Description:**
Any public clip can be reported by any authenticated user. The report includes a category and optional details, and enters a moderation review queue.

**Functional Requirements:**
- "Report" button on every public clip (song detail page, feed, explore, search results)
- Report modal with categories: Inappropriate content, Copyright concern, Spam, Other
- Optional free-text field for additional details
- Submission confirmation message ("Report received. Our team will review it.")
- Duplicate reports from the same user on the same clip are prevented
- Reports create entries in the admin moderation queue

**Acceptance Criteria:**
- [ ] Clicking "Report" opens the report modal with category options
- [ ] Submitting a report shows a confirmation message
- [ ] The report appears in the admin moderation queue
- [ ] Submitting a duplicate report shows "You have already reported this clip"
- [ ] Reports are available for all public clip surface areas (detail page, feed, explore)

---

#### US-27.3: Admin Moderation Dashboard

**As an** admin, **I want** a dashboard to review reported content and take action, **so that** I can maintain community safety efficiently.

**Description:**
The admin moderation dashboard shows a queue of reported and flagged content, with tools to review, approve, remove, or escalate. Admins can also ban users who repeatedly violate guidelines.

**Functional Requirements:**
- Admin route: `/admin/moderation` (accessible only to admin role)
- Review queue: list of reported clips sorted by report count and severity
- Each queue item shows: clip details (title, creator, style, audio player), report count, report categories, flagging source (user report vs. automated)
- Actions per item: Approve (dismiss reports), Remove (take down the clip, notify creator), Flag (add a warning label visible to listeners)
- User actions: Warn user (send a notification), Ban user (disable account, remove all public content)
- Bulk actions: select multiple items and apply the same action
- Moderation activity log for audit trail

**Acceptance Criteria:**
- [ ] Admin sees all reported clips in a sortable, filterable queue
- [ ] Approving a report clears it from the queue
- [ ] Removing a clip makes it inaccessible publicly and notifies the creator
- [ ] Banning a user disables their account and removes public content
- [ ] Moderation log records all admin actions with timestamps

---

#### US-27.4: Appeals Workflow

**As a** musician, **I want** to appeal a moderation decision on my content, **so that** I can have unfair takedowns reviewed.

**Description:**
When a musician's content is removed or their account is restricted, they can submit an appeal through their account settings. Appeals enter a separate review queue for admin evaluation.

**Functional Requirements:**
- Appeal option on any removed or flagged clip in the musician's Library (visible only to the clip owner)
- Appeal form: reason for appeal (free text), optional supporting context
- Appeal submission creates an entry in the admin appeals queue
- Admin can: Uphold decision (deny appeal), Reverse decision (restore content, notify musician), Request more information
- Musician receives notification of the appeal outcome
- One appeal per moderation action (no repeat appeals for the same decision)

**Acceptance Criteria:**
- [ ] Musician sees "Appeal" option on removed clips in their Library
- [ ] Submitting an appeal shows confirmation and creates an admin queue entry
- [ ] Admin can uphold or reverse the decision from the appeals queue
- [ ] Musician receives notification of the outcome
- [ ] Repeat appeal on the same decision is blocked

---

### Stage 28: Polish & Production Readiness

**Overview:** Harden the platform for production use — performance optimization, error handling audit, accessibility, mobile responsiveness, API rate limiting, monitoring, experimental features page, and documentation. This is the final stage before launch, ensuring the platform is fast, reliable, accessible, and well-documented.

**Spec Reference:** §48

---

#### US-28.1: Performance Optimization

**As a** musician, **I want** the platform to load quickly and respond instantly, **so that** I can focus on creating music without waiting for the interface.

**Description:**
Audit and optimize all critical performance paths — lazy loading for heavy components, CDN caching for images and audio, API response time targets, and efficient data fetching patterns.

**Functional Requirements:**
- Lazy loading for: waveform components, studio editor, video player, heavy library views
- Image and audio assets served via CDN with appropriate cache headers
- API response time target: <200ms for reads, <500ms for writes (excluding generation jobs)
- Bundle size audit: code-split routes, tree-shake unused dependencies
- Database query optimization: add indexes for common query patterns
- Audio streaming: progressive loading for long clips (not full download before playback)

**Acceptance Criteria:**
- [ ] Initial page load (Time to Interactive) under 3 seconds on broadband
- [ ] API read endpoints respond in under 200ms (p95)
- [ ] Navigating between pages does not trigger full-page reloads
- [ ] Audio playback begins within 1 second of clicking play (not after full download)
- [ ] Lighthouse performance score above 80 for key pages

---

#### US-28.2: Error Handling and User Experience Audit

**As a** musician, **I want** every error to show a helpful, human-readable message, **so that** I never see a raw stack trace or cryptic error code.

**Description:**
Audit all error paths across the frontend and API. Replace raw error messages, stack traces, and generic "Something went wrong" messages with specific, actionable guidance.

**Functional Requirements:**
- Frontend error boundary catches all unhandled exceptions and shows a recovery UI
- API errors return consistent format: `{ error: string, code: string, details?: string, action?: string }`
- No raw stack traces exposed to users in any environment (including 500 errors)
- Network errors show "Connection lost — retrying" with automatic retry
- Generation failures show specific guidance (e.g., "Server busy — try again in 30 seconds")
- Form validation errors appear inline next to the relevant field
- 404 pages have navigation back to home and search

**Acceptance Criteria:**
- [ ] No endpoint returns raw stack traces in production (verified by fuzzing)
- [ ] Network disconnection shows a non-blocking retry banner
- [ ] All form validation errors appear inline
- [ ] 500 errors show a user-friendly message with a support link
- [ ] 404 page includes navigation to home and search

---

#### US-28.3: Accessibility

**As a** musician, **I want** the platform to be fully accessible via keyboard and screen reader, **so that** I can use it regardless of my abilities.

**Description:**
Implement WCAG 2.1 AA compliance across all pages — keyboard navigation, screen reader support, ARIA labels, sufficient color contrast, and focus management.

**Functional Requirements:**
- All interactive elements reachable and operable via keyboard (Tab, Enter, Escape, Arrow keys)
- ARIA labels on all non-text interactive elements (buttons, sliders, toggles, icons)
- Focus management: focus moves logically through modals, drawers, and dynamic content
- Color contrast: minimum 4.5:1 for normal text, 3:1 for large text (WCAG AA)
- Audio player controls fully accessible (play, pause, seek, volume)
- Screen reader announces: page transitions, loading states, error messages, generation progress
- Skip-to-content link on every page

**Acceptance Criteria:**
- [ ] All pages pass axe-core automated accessibility audit with zero critical violations
- [ ] A screen reader user can navigate from login through song creation and playback
- [ ] Tab order is logical on all pages (no focus traps except modals)
- [ ] Color contrast meets WCAG AA on all text elements
- [ ] Audio player is fully operable via keyboard

---

#### US-28.4: Mobile Responsiveness and API Rate Limiting

**As a** musician, **I want** the platform to work on my phone and be protected from abuse, **so that** I can create on mobile and trust the platform is stable.

**Description:**
Ensure all pages are usable on mobile viewports (360px–768px) and implement per-user, per-endpoint API rate limiting to prevent abuse and ensure fair resource distribution.

**Functional Requirements:**
- All pages responsive at 360px, 414px, and 768px viewports
- Touch targets minimum 44x44px
- Mobile-optimized navigation: bottom nav bar or hamburger menu
- Audio player adapts to mobile layout (compact mode)
- API rate limiting: per-user, per-endpoint limits (e.g., 60 requests/min for reads, 10/min for generation)
- Rate limit exceeded returns 429 with `Retry-After` header
- Rate limits are tiered by subscription (Pro gets higher limits)
- Rate limit dashboard for admins

**Acceptance Criteria:**
- [ ] All pages render correctly at 360px viewport width
- [ ] Touch targets meet minimum 44x44px size
- [ ] API returns 429 with Retry-After header when rate limit is exceeded
- [ ] Pro users have higher rate limits than Free users
- [ ] Audio player is functional on mobile (play, pause, seek)

---

#### US-28.5: Monitoring, Experimental Features, and Documentation

**As a** developer, **I want** production observability, a feature flag system for experiments, and comprehensive documentation, **so that** we can monitor the platform, test new features safely, and onboard new contributors.

**Description:**
Set up structured logging, error tracking, uptime monitoring, a `/labs` page for experimental features behind feature flags, and auto-generated API documentation. This is the capstone of production readiness.

**Functional Requirements:**
- Structured logging: JSON-formatted logs with request IDs, user IDs, timestamps, and severity levels
- Error tracking: Sentry (or similar) integration for frontend and backend exceptions
- Uptime monitoring: health check endpoint polled every 60 seconds with alerting on downtime
- Experimental features page (`/labs`) with feature flags for: Real-time generation (Alpha), Collaborative workspaces (Alpha), AI Arrangement (Beta), Style Transfer (Beta)
- Feature flags controlled via admin panel (per-user or global rollout)
- API documentation: auto-generated Swagger/OpenAPI docs at `/docs`
- User guide: in-app help pages covering core workflows
- Deployment guide: documented deployment process for VPS

**Acceptance Criteria:**
- [ ] Logs are structured JSON and include request IDs for tracing
- [ ] Sentry captures frontend and backend errors with source maps
- [ ] Uptime monitor alerts when the health endpoint is unreachable for >2 minutes
- [ ] `/labs` page shows experimental features with Alpha/Beta badges and toggle switches
- [ ] Feature flags can be enabled/disabled per user from the admin panel
- [ ] `/docs` serves auto-generated OpenAPI documentation
- [ ] Deployment guide enables a new developer to deploy the platform from scratch

---

**Stage 28 Completion Criteria:**
- Lighthouse performance score above 80 on key pages
- Zero critical accessibility violations
- All pages responsive on mobile viewports
- API rate limiting is active and tested
- Structured logging and error tracking are operational
- `/labs` page is live with feature flags
- API docs are auto-generated and current
- No raw stack traces or cryptic errors exposed to users

---

## Dependency Graph

```
LAYER 1: CLI FOUNDATION (sequential)
S1 → S2 → S3 → S4 → S5 → S6 → S7

LAYER 2: PLATFORM API (sequential, depends on Layer 1)
S7 → S8 → S9 → S10 → S11 → S12 → S13 → S14

LAYER 3: WEB UI (sequential, depends on Layer 2)
S14 → S15 → S16 → S17 → S18 → S19 → S20 → S21

LAYER 4: ADVANCED INTEGRATIONS (partially parallel, depends on Layer 3)
S21 → S22 (Video Gen)          ─────────────────────────────────┐
S21 → S23 → S24 (VST3 Core → Advanced)                         │
S21 → S25 (Custom Voice Models)                                 ├→ S28 (Polish)
S21 → S26 → S27 (Credits → Moderation) ────────────────────────┘

CRITICAL PATH:
S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10 → S11 → S12 → S13 → S14
→ S15 → S16 → S17 → S18 → S19 → S20 → S21 → S26 → S27 → S28

PARALLEL OPPORTUNITIES (Layer 4):
┌──────────────────────────────────────────────────────────────────────┐
│  After Stage 21, the following can run in parallel:                  │
│                                                                      │
│  Track A: S22 (Video Gen)              ┐                             │
│  Track B: S23 → S24 (VST3)            ├─ All independent            │
│  Track C: S25 (Voice Models)           │                             │
│  Track D: S26 → S27 (Credits → Mod.)  ┘                             │
│                                                                      │
│  Stage 28 (Polish) depends on ALL of the above completing.           │
│                                                                      │
│  CROSS-LAYER parallelism:                                            │
│  - S23 (VST3 Core) can start during Layer 3 if S14 (Export API)     │
│    is complete (plugin talks to API, not web UI).                    │
│  - S25 (Voice Models) backend can start during Layer 2 if S9        │
│    (Generation API) is complete.                                     │
│  - S22 (Video Gen) backend can start during Layer 2 if S9 is        │
│    complete (needs generation API for song access).                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Appendix: Spec Section Cross-Reference

This table maps every spec section to the development stage(s) and user stories that implement it. Use this to verify complete specification coverage.

| Spec Section | Title | Stage(s) | Story IDs |
|---|---|---|---|
| §1 | Application Shell & Navigation | 15 | US-15.1, US-15.2, US-15.3 |
| §2 | Authentication & Account | 8, 15 | US-8.1, US-8.2, US-15.1 |
| §3 | Song Creation — Simple Mode | 2, 3, 9, 16 | US-2.3, US-3.1, US-9.1, US-16.1 |
| §4 | Song Creation — Advanced Mode | 3, 9, 16 | US-3.1, US-3.2, US-3.3, US-9.1, US-16.2 |
| §5 | Song Creation — Sounds Mode | 3, 9, 16 | US-3.5, US-9.1, US-16.3 |
| §6 | Audio Input Sources at Creation Time | 4, 10, 16 | US-4.4, US-10.1, US-16.4 |
| §7 | Generation Controls & Parameters | 3, 9, 16 | US-3.2, US-3.3, US-9.1, US-16.1 |
| §8 | Workspace & Clip Library Panel | 4, 9, 16 | US-4.1, US-4.2, US-9.2, US-16.5 |
| §9 | Clip Card — Actions & States | 4, 16 | US-4.2, US-16.5 |
| §10 | Remix & Edit Workflows | 6, 10, 17 | US-6.3, US-10.1, US-17.1 |
| §11 | Extend Workflow | 6, 10, 17 | US-6.1, US-10.2, US-17.2 |
| §12 | Cover Workflow | 6, 10, 17 | US-6.2, US-10.3, US-17.3 |
| §13 | Mashup Workflow | 6, 10, 17 | US-6.4, US-10.4, US-17.4 |
| §14 | Sample from Song (Beta) | 6, 10, 17 | US-6.5, US-10.5, US-17.5 |
| §15 | Replace Section | 6, 10, 17 | US-6.6, US-10.6, US-17.6 |
| §16 | Crop | 5, 10, 17 | US-5.1, US-10.7, US-17.7 |
| §17 | Adjust Speed | 5, 10, 17 | US-5.2, US-10.8, US-17.8 |
| §18 | Add Vocal | 6, 10, 17 | US-6.6, US-10.9, US-17.9 |
| §19 | Remaster | 5, 10, 17 | US-5.5, US-10.10, US-17.10 |
| §20 | Similar Songs Radio | 20 | US-20.3 |
| §21 | Get Full Song | 6, 10, 17 | US-6.7, US-10.11, US-17.11 |
| §22 | Open in Editor (Pro) | 19 | US-19.1 |
| §23 | Song Detail Page | 20 | US-20.1 |
| §24 | Studio — Multi-Track DAW | 19 | US-19.1, US-19.2, US-19.3, US-19.4 |
| §25 | Custom Voice Models | 25 | US-25.1, US-25.2, US-25.3, US-25.4 |
| §26 | Short-Form Audio/Video Feed | 20 | US-20.2 |
| §27 | Library (/me) | 20 | US-20.4 |
| §28 | Explore / Discovery | 20 | US-20.5 |
| §29 | Search | 20 | US-20.6 |
| §30 | Playlists | 20 | US-20.7 |
| §31 | Notifications | 20 | US-20.8 |
| §32 | Profile Page | 20 | US-20.9 |
| §33 | Publish & Visibility Controls | 20 | US-20.10 |
| §34 | Download & Export | 7, 14, 21 | US-7.1, US-7.2, US-14.1, US-21.1 |
| §35 | Cover Art Generation | 21 | US-21.2 |
| §36 | Stems & MIDI Extraction | 5, 14, 18 | US-5.3, US-5.4, US-14.2, US-18.1 |
| §37 | AI Engine — ACE-Step-1.5 | 2, 8, 11 | US-2.2, US-2.3, US-8.3, US-11.1 |
| §38 | Model Configuration & Selection | 3, 9 | US-3.4, US-9.3 |
| §39 | LoRA Training & Personalization | 25 | US-25.1, US-25.2 |
| §40 | Music Video Generator | 22 | US-22.1, US-22.2, US-22.3, US-22.4 |
| §41 | Automated Mastering Pipeline | 12, 21 | US-12.1, US-12.2, US-21.3 |
| §42 | Distribution & Release Management | 13, 21 | US-13.1, US-13.2, US-21.4 |
| §43 | DAW Export — Audio & MIDI | 7, 14 | US-7.2, US-7.3, US-7.4, US-14.1, US-14.2 |
| §44.1–44.3 | VST3 Plugin — Core (Overview, Stack, UI) | 23 | US-23.1, US-23.2, US-23.3, US-23.4, US-23.5 |
| §44.4–44.5 | VST3 Plugin — Advanced (DAW Integration, Modes) | 24 | US-24.1, US-24.2, US-24.3, US-24.4, US-24.5 |
| §44.6 | VST3 Plugin — File Management | 23 | US-23.5 |
| §44.7 | VST3 Plugin — System Requirements | 23 | US-23.1 |
| §45 | Credits & Subscription System | 26 | US-26.1, US-26.2, US-26.3, US-26.4, US-26.5 |
| §46 | Playback System (Global Player) | 15, 18 | US-15.4, US-18.2 |
| §47 | Content Moderation & Reporting | 27 | US-27.1, US-27.2, US-27.3, US-27.4 |
| §48 | Experimental Features | 28 | US-28.5 |
| §49 | Full UX Lifecycle Summary | — | Cross-cutting; validated by end-to-end acceptance tests across all stages |

**Coverage Notes:**
- All 49 spec sections are mapped to at least one development stage.
- §49 (Full UX Lifecycle Summary) is a cross-cutting description of the platform workflow rather than a discrete feature. It is validated implicitly by the integration of all stages.
- Story IDs for Layers 2–3 (Stages 8–21) reference the planned story numbering convention. Exact IDs will be confirmed when those layers are written.
- Some spec sections span multiple layers (e.g., §34 Download & Export appears in CLI, API, and UI layers) reflecting the "build outward from a runnable core" philosophy.
