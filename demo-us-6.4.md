# US-6.4: Mashup (combine elements from two clips)

*2026-05-19T20:07:09Z*

## What was built

US-6.4 adds the `acemusic mashup <clip_id_1> <clip_id_2>` command, which combines elements from two existing clips into a single new hybrid clip. The command supports three blend strategies — layered, sequential, and ai-guided — and attempts BPM alignment by time-stretching the secondary clip to match the primary clip's tempo before submitting the job to ACE-Step.

This demo verifies the implementation against the three acceptance criteria from issue #36, with no live ACE-Step server in the loop (the acceptance criteria are exercised end-to-end against a mocked client in the test suite; this script confirms the CLI surface, the wiring through to `submit_task`, and that all locked-in tests are green).

## Step 1: The new `mashup` subcommand is wired into the CLI

`acemusic --help` should now list `mashup` alongside `generate`, `cover`, `repaint`, etc.

```bash
uv run acemusic --help 2>&1 | grep -E "mashup|Combine"
```

```output
│ mashup     Combine elements from two clips into a single hybrid clip.        │
```

## Step 2: Inspect the command surface

The command takes two required clip-ID arguments and exposes the blend strategy, optional unifying style, output directory, and filename prefix.

```bash
uv run acemusic mashup --help 2>&1
```

```output
                                                                                
 Usage: acemusic mashup [OPTIONS] CLIP_ID_1 CLIP_ID_2                           
                                                                                
 Combine elements from two clips into a single hybrid clip.                     
                                                                                
 Submits a ``task_type=mashup`` request to ACE-Step with both source clips and  
 a blend strategy. When the two clips have known but differing BPMs, the        
 secondary clip is time-stretched to match the primary clip's tempo before      
 submission (US-5.2 alignment). The result is saved as a new clip with          
 ``parent_clip_id`` pointing to the primary source and                          
 ``generation_mode='mashup'``.                                                  
                                                                                
 Note: Requires ACE-Step to run on the same host (or with shared filesystem     
 access), since source audio is passed via absolute server-side paths.          
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    clip_id_1      INTEGER  ID of the primary source clip. [required]       │
│ *    clip_id_2      INTEGER  ID of the secondary source clip to blend with.  │
│                              [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --blend         TEXT  Blend strategy: 'layered' (concurrent), 'sequential'   │
│                       (section-by-section), or 'ai-guided'.                  │
│                       [default: layered]                                     │
│ --style         TEXT  Optional unifying style descriptor (e.g. 'lo-fi hip    │
│                       hop').                                                 │
│ --output        PATH  Directory to save the mashup file.                     │
│ --name          TEXT  Custom filename prefix and title for the mashup.       │
│ --help                Show this message and exit.                            │
╰──────────────────────────────────────────────────────────────────────────────╯

```

## Step 3: Acceptance criterion 1 — mashup produces a single new clip

`tests/test_mashup.py::TestMashupCommand::test_creates_single_new_clip_with_lineage` invokes `mashup` against two source clips with a mocked ACE-Step client and asserts that exactly one new row appears in the clips DB with `generation_mode='mashup'` and `parent_clip_id` pointing at the primary source.

```bash
uv run pytest tests/test_mashup.py::TestMashupCommand::test_creates_single_new_clip_with_lineage --no-cov -v 2>&1 | tail -10
```

```output
tests/test_mashup.py::TestMashupCommand::test_creates_single_new_clip_with_lineage
  /home/frankbria/projects/auto-music-studio/.venv/lib/python3.13/site-packages/audioread/rawread.py:16: DeprecationWarning: aifc was removed in Python 3.13. Please be aware that you are currently NOT using standard 'aifc', but instead a separately installed 'standard-aifc'.
    import aifc

tests/test_mashup.py::TestMashupCommand::test_creates_single_new_clip_with_lineage
  /home/frankbria/projects/auto-music-studio/.venv/lib/python3.13/site-packages/audioread/rawread.py:19: DeprecationWarning: sunau was removed in Python 3.13. Please be aware that you are currently NOT using standard 'sunau', but instead a separately installed 'standard-sunau'.
    import sunau

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 1 passed, 2 warnings in 2.11s =========================
```

## Step 4: Acceptance criterion 2 — the three blend modes produce different requests

`blend_mode` is threaded straight through to the ACE-Step API. Three locked-in tests assert that each `--blend` value reaches `submit_task` unchanged, plus a guard rejects unknown blend strings before any DB lookup happens.

```bash
uv run pytest tests/test_mashup.py::TestMashupCommand::test_blend_layered tests/test_mashup.py::TestMashupCommand::test_blend_sequential tests/test_mashup.py::TestMashupCommand::test_blend_ai_guided tests/test_mashup.py::TestMashupCommand::test_invalid_blend_mode_exits_one --no-cov -v 2>&1 | tail -8
```

```output
    import aifc

tests/test_mashup.py::TestMashupCommand::test_blend_layered
  /home/frankbria/projects/auto-music-studio/.venv/lib/python3.13/site-packages/audioread/rawread.py:19: DeprecationWarning: sunau was removed in Python 3.13. Please be aware that you are currently NOT using standard 'sunau', but instead a separately installed 'standard-sunau'.
    import sunau

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 4 passed, 2 warnings in 2.44s =========================
```

## Step 5: Acceptance criterion 3 — BPM alignment is attempted

When both source clips have known but different BPMs, the secondary clip is time-stretched to the primary's tempo via the US-5.2 `time_stretch_audio` helper. The test below patches `time_stretch_audio` and asserts it is invoked with the expected rate (120/100 = 1.2x).

Two companion tests confirm the no-op branches: alignment is skipped when BPMs match, when either BPM is unknown, and when either BPM is ≤ 0. A failure-path test confirms the command still succeeds (falling back to the original clip) if time-stretching itself raises.

```bash
uv run pytest tests/test_mashup.py -k "bpm_alignment or no_alignment or zero_or_negative_bpm" --no-cov -v 2>&1 | tail -10
```

```output
tests/test_mashup.py::TestMashupCommand::test_zero_or_negative_bpm_skips_alignment PASSED [ 75%]
tests/test_mashup.py::TestMashupCommand::test_bpm_alignment_failure_falls_back_to_original PASSED [100%]

=============================== warnings summary ===============================
tests/test_mashup.py::TestMashupCommand::test_bpm_alignment_failure_falls_back_to_original
  /home/frankbria/projects/auto-music-studio/src/acemusic/cli.py:2485: UserWarning: BPM alignment failed, using original clip: librosa exploded
    aligned_secondary = _align_clips_bpm(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 4 passed, 21 deselected, 1 warning in 1.04s ==================
```

## Step 6: End-to-end CLI invocation against a real DB

Using a real workspace + clip DB and a real (mocked-at-the-network-boundary) `AceStepClient`, run the command and verify that one new file lands in the workspace and one new DB row is created with the correct lineage. Because no live ACE-Step server is available in this environment, the test below mocks just the HTTP boundary and exercises everything else for real — DB, workspace resolution, BPM detection, time-stretch invocation, file I/O, and clip persistence.

```bash
uv run pytest tests/test_mashup.py::TestMashupCommand::test_default_succeeds tests/test_mashup.py::TestMashupCommand::test_default_blend_is_layered tests/test_mashup.py::TestMashupCommand::test_default_title_combines_sources tests/test_mashup.py::TestMashupCommand::test_output_directory_overrides_default --no-cov -v 2>&1 | tail -10
```

```output
tests/test_mashup.py::TestMashupCommand::test_default_succeeds
  /home/frankbria/projects/auto-music-studio/.venv/lib/python3.13/site-packages/audioread/rawread.py:16: DeprecationWarning: aifc was removed in Python 3.13. Please be aware that you are currently NOT using standard 'aifc', but instead a separately installed 'standard-aifc'.
    import aifc

tests/test_mashup.py::TestMashupCommand::test_default_succeeds
  /home/frankbria/projects/auto-music-studio/.venv/lib/python3.13/site-packages/audioread/rawread.py:19: DeprecationWarning: sunau was removed in Python 3.13. Please be aware that you are currently NOT using standard 'sunau', but instead a separately installed 'standard-sunau'.
    import sunau

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 4 passed, 2 warnings in 2.71s =========================
```

## Step 7: Full mashup test suite (acceptance + edge cases)

All 25 mashup tests, covering the three acceptance criteria, the three blend modes, every error path (missing clips, missing files, unsupported format, API failure, polling timeout), the deduplication logic, and CLI defaults.

```bash
uv run pytest tests/test_mashup.py --no-cov 2>&1 | tail -5
```

```output
  /home/frankbria/projects/auto-music-studio/src/acemusic/cli.py:2485: UserWarning: BPM alignment failed, using original clip: librosa exploded
    aligned_secondary = _align_clips_bpm(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 25 passed, 3 warnings in 7.35s ========================
```

## Step 8: Full project test suite — no regressions

Running the whole project suite to confirm the mashup changes don't break the other CLI commands, the client, or anything in the audio pipeline.

```bash
uv run pytest --no-cov 2>&1 | tail -3
```

```output

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
========== 509 passed, 1 skipped, 7 deselected, 3 warnings in 48.63s ===========
```

## Step 9: `AceStepClient.submit_task` accepts `mashup` cleanly

The client gained `ref_audio_path` and `blend_mode` parameters, plus `"mashup"` was added to the `TaskType` literal. Existing callers (`generate`, `cover`, `repaint`, `extend`) remain backward compatible.

```bash
uv run python -c "
from acemusic.client import AceStepClient, TaskType
import typing
print(\"TaskType:\", typing.get_args(TaskType))
import inspect
sig = inspect.signature(AceStepClient.submit_task)
new_params = [p for p in sig.parameters.values() if p.name in {\"ref_audio_path\", \"blend_mode\"}]
for p in new_params:
    print(f\"  {p.name}: default={p.default}\")
"
```

```output
TaskType: ('text2music', 'cover', 'repaint', 'extract', 'lego', 'complete', 'mashup')
  ref_audio_path: default=None
  blend_mode: default=None
```

## Verdict

| Acceptance criterion | Evidence |
|---|---|
| Mashup of two clips produces a single new clip | Step 3 — `test_creates_single_new_clip_with_lineage` |
| The three blend modes produce audibly different results | Step 4 — `test_blend_layered`, `test_blend_sequential`, `test_blend_ai_guided` thread `blend_mode` through to `submit_task`; the model produces audibly different output at runtime against a live ACE-Step server (smoke-test deferred to integration env) |
| BPM/key alignment is attempted | Step 5 — `test_bpm_alignment_invoked_when_bpms_differ` patches `time_stretch_audio` and asserts it's invoked at rate=1.2 (120 BPM target / 100 BPM source). Companion tests cover no-op + failure-fallback branches |

**Caveat:** the model-level claim that the three blend modes produce *audibly* different output cannot be verified without a live ACE-Step server (which depends on a GPU host that's out of scope for this environment). The CLI plumbing — the parameter that controls it — is verified to thread through to the API correctly, so the audible-difference test will be done once during the next on-host smoke test.

Total tests: **25** mashup-specific, **509** project-wide. All green. Ruff + black clean.
