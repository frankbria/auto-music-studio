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

