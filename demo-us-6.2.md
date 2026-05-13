# Demo: US-6.2 — Cover Mode

**Story**: As a musician, I want to create a cover version of a clip in a different style.

**Command**: `acemusic cover <clip_id> --style "jazz piano trio" [--lyrics "..."] [--voice <id>]`

## CLI Surface

```text
$ acemusic cover --help
 Usage: acemusic cover [OPTIONS] CLIP_ID

 Create a cover of an existing clip in a different style.

 Submits a `task_type=cover` request to ACE-Step with the source clip as
 src_audio. The result is saved as a new clip with `parent_clip_id` set to
 the source and `generation_mode='cover'`.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    clip_id      INTEGER  ID of the source clip to cover. [required]        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --style         TEXT  Target style/genre for the cover. [required]        │
│    --lyrics        TEXT  Optional lyrics override (melody preserved).        │
│    --voice         TEXT  Optional custom voice id (Stage 25 feature).        │
│    --output        PATH  Directory to save the cover file.                   │
│    --name          TEXT  Custom filename prefix for the cover.               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Acceptance criteria verification

| Criterion | Status | Evidence |
|---|---|---|
| Cover output is recognizably derived from the source melody | VERIFIED (functional) / requires GPU server for audible verification | `submit_task` is called with `task_type="cover"` and `src_audio_path=<absolute path to source clip>` — verified by `test_submits_cover_task_with_correct_params`. Melody preservation is performed by the ACE-Step server-side `cover` task type, which uses the source audio as the melodic reference. |
| Style is audibly different from the original | VERIFIED (functional) / requires GPU server for audible verification | The `--style` flag is required and is forwarded as both the `prompt` and the `style` field to ACE-Step (`test_submits_cover_task_with_correct_params`). |
| Lyrics override changes the words while keeping the melodic feel | VERIFIED (functional) | `--lyrics` is forwarded to ACE-Step (`test_lyrics_override_passed_to_api`). Server preserves the melody contour via `src_audio_path` while substituting the new lyrics — same mechanism used by `extend`. |

## Functional verification (no live server needed)

### 1. Lineage and metadata

`test_creates_child_clip_with_lineage` asserts the cover output is registered as a new clip with:
- `parent_clip_id` = source clip id
- `generation_mode = "cover"`
- `style_tags` set to the new style
- Inherited `bpm`, `key`, `seed`, `vocal_language`, `model` from the source
- Title becomes `"<source title> (cover)"` (e.g. `"Morning Theme (cover)"` — `test_cover_inherits_title`)

### 2. API contract

`test_submits_cover_task_with_correct_params` asserts:
- `task_type="cover"` (the ACE-Step task type that preserves melody and restyles)
- `src_audio_path` = absolute path to the source WAV file
- `style` = the user-provided style string
- `bpm`, `key`, `seed` inherited from source clip
- `audio_duration` = source duration (output matches source length)

### 3. Voice flag placeholder

`test_voice_flag_shows_placeholder_message` asserts that `--voice <id>` prints `"Voice selection available in Stage 25"` and otherwise no-ops, satisfying the spec's "Stage 25 prerequisite — implement as no-op or placeholder for now".

### 4. Validation and error handling

- Nonexistent clip id → exit 1 with `"not found"` (`test_nonexistent_clip_returns_error`)
- Missing source file → exit 1 (`test_missing_source_file_returns_error`)
- Missing `--style` → typer rejects with exit 2 (`test_missing_style_returns_error`)
- ACE-Step returns FAILED → exit 1 with error message (`test_api_failure_returns_error`)
- Connection failure → exit 1 with friendly message, no traceback (`test_connection_error_returns_error`)

### 5. Polling

`test_polls_until_complete` asserts the command polls `query_result` until status flips from `pending` → `completed`, matching the existing `extend` pattern.

## Audible verification

The three audible acceptance criteria (melody preservation, style change, lyric swap with preserved melody) are performed server-side by ACE-Step's `cover` task type. They require a live GPU-backed ACE-Step server to render audio and listen.

The integration test `TestCoverIntegration.test_cover_live_server` (gated by `@pytest.mark.integration`) exercises the end-to-end flow against a real server when one is available — it generates a 30-second cover of a 30s source tone and asserts the output is a valid WAV file registered as a child clip. This test is skipped in CI (no GPU) but can be run locally with `uv run pytest -m integration` when an ACE-Step server is healthy at `ACESTEP_LOCAL_URL`.

## Test summary

```bash
$ uv run pytest tests/test_cover.py
collected 14 items / 1 deselected / 13 selected

tests/test_cover.py .............    [100%]
13 passed, 1 deselected
```

Full suite: **463 passed, 1 skipped**.
