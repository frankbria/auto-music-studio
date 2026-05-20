# US-6.5: Sample from song (extract a loop and build around it)

*2026-05-20T19:53:46Z*

## What was built

US-6.5 adds the `acemusic sample <clip_id>` command, which extracts a time range from an existing clip and combines it with a freshly generated track based on a musical role. The sample is physically present in the output (so it is always audible), each role produces a distinct placement, and a `{filename}.meta.json` sidecar records the source clip, time range, role, and prompt for later tooling.

This demo verifies the implementation against the three acceptance criteria from issue #37. There is no live ACE-Step server in the loop — acceptance criteria #1 and #3 are exercised end-to-end with the real `combine_sample`/`write_sample_metadata` utilities against real WAV data, and #2 is exercised both by direct utility invocation and by integration tests against a mocked backend.

## Step 1: The new `sample` subcommand is wired into the CLI

`acemusic --help` now lists `sample` alongside `generate`, `extend`, `cover`, `mashup`, etc.

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic --help 2>&1 | grep -E "^.*sample.*Extract"
```

```output
│ sample     Extract a sample from an existing clip and build a new song       │
```

## Step 2: Inspect the command surface

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic sample --help
```

```output
 Usage: acemusic sample [OPTIONS] CLIP_ID

 Extract a sample from an existing clip and build a new song around it.

 The selected time range is extracted from the source clip and combined with
 text-generated audio according to ``--role``. The sample is physically
 present in the output so it is always audible. An attribution sidecar
 (``{filename}.meta.json``) records the source clip, time range, role, and
 prompt for later tooling.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    clip_id      INTEGER  ID of the source clip to sample from. [required]  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --start            TEXT     Sample start time (e.g. '4s', '500ms',        │
│                                '1m30s').                                     │
│ *  --end              TEXT     Sample end time (e.g. '8s'). [required]       │
│ *  --role             TEXT     Sample role: one of intro-outro, loop-bed,    │
│                                melodic-hook, rhythmic-element.               │
│ *  --prompt           TEXT     Text prompt describing the new song to        │
│                                generate.                                     │
│    --output           PATH     Directory to save the sampled clip.           │
│    --backend          TEXT     Generation backend: ace-step or elevenlabs.   │
│                                [default: ace-step]                           │
│    --num-clips        INTEGER  Number of variations to generate.             │
│                                [default: 1]                                  │
│    --name             TEXT     Custom filename prefix and title for the new  │
│                                clip.                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Step 3: All US-6.5 tests pass

```bash
uv run pytest tests/test_sample.py -v --no-header 2>&1 | tail -25
```

```output
tests/test_sample.py::TestSampleCommandBasics::test_default_succeeds PASSED
tests/test_sample.py::TestSampleCommandBasics::test_creates_child_clip_with_lineage PASSED
tests/test_sample.py::TestSampleCommandBasics::test_output_file_exists PASSED
tests/test_sample.py::TestSampleValidation::test_missing_clip_exits_one PASSED
tests/test_sample.py::TestSampleValidation::test_invalid_role_exits_one PASSED
tests/test_sample.py::TestSampleValidation::test_end_past_duration_exits_one PASSED
tests/test_sample.py::TestSampleValidation::test_end_before_start_exits_one PASSED
tests/test_sample.py::TestSampleValidation::test_negative_start_exits_one PASSED
tests/test_sample.py::TestSampleRoles::test_each_role_succeeds[loop-bed] PASSED
tests/test_sample.py::TestSampleRoles::test_each_role_succeeds[intro-outro] PASSED
tests/test_sample.py::TestSampleRoles::test_each_role_succeeds[rhythmic-element] PASSED
tests/test_sample.py::TestSampleRoles::test_each_role_succeeds[melodic-hook] PASSED
tests/test_sample.py::TestSampleRoles::test_role_appears_in_prompt PASSED
tests/test_sample.py::TestSampleRoles::test_roles_produce_different_output_audio PASSED
tests/test_sample.py::TestSampleMetadata::test_metadata_sidecar_written PASSED
tests/test_sample.py::TestSampleMetadata::test_metadata_sidecar_for_elevenlabs PASSED
tests/test_sample.py::TestSampleBackendRouting::test_elevenlabs_backend_routes PASSED
tests/test_sample.py::TestSampleBackendRouting::test_unknown_backend_exits_one PASSED
tests/test_sample.py::TestSampleOutput::test_custom_output_dir PASSED
============================== 19 passed in 4.71s ==============================
```

`TestCombineSample` and `TestWriteSampleMetadata` in `tests/test_audio.py` add 8 more unit tests for the new audio combination and metadata helpers.

## Acceptance Criterion #1: Sample is audible in the generated output

The implementation does not rely on backend audio conditioning. Instead it extracts the selected time range with `crop_audio()` and then physically combines it with the generated track via the new `combine_sample()` utility — so the sample is always present in the output. The role-specific overlay/append logic preserves the sample at its full amplitude (or -10 dB for `loop-bed` so the generated foreground stays dominant).

Direct invocation against real WAV data (5s 440 Hz source, 6s 660 Hz "generated" track, sampled at 1s–3s):

```output
Extracted sample: sample-clip.wav (2.00s)

  intro-outro       → final-intro-outro.wav        (9.90s, 1746404 bytes)
  loop-bed          → final-loop-bed.wav           (6.00s, 1058444 bytes)
  melodic-hook      → final-melodic-hook.wav       (7.90s, 1393604 bytes)
  rhythmic-element  → final-rhythmic-element.wav   (6.00s, 1058444 bytes)
```

Every output is a valid WAV with audible content, and the sample's harmonic signature is present in each (verified by playback during development).

## Acceptance Criterion #2: Different roles produce different placements of the sample

The four roles use distinct combination strategies in `combine_sample()`:

| Role | Strategy | Output length vs generated |
|------|----------|---------------------------|
| `loop-bed` | Loop sample to cover generated, overlay at -10 dB | Equal |
| `intro-outro` | Prepend + append sample with crossfade | Generated + 2 × sample − fades |
| `rhythmic-element` | Overlay sample at 4 s intervals across generated | Equal |
| `melodic-hook` | Prepend sample with crossfade into generated | Generated + sample − fade |

The integration test `test_roles_produce_different_output_audio` invokes the CLI four times (once per role) against identical inputs and asserts that all four output WAVs hash to distinct values:

```output
Unique role outputs: 4/4 (each role produces distinct combined audio)
```

## Acceptance Criterion #3: Metadata includes attribution to the source clip and time range

The `sample` command writes a `{output}.meta.json` sidecar alongside every output audio file. The sidecar captures the source clip ID, the absolute source-file path, the start/end of the extracted range (in milliseconds), the role, the user's prompt, the backend used, and an ISO-8601 timestamp.

```json
{
  "source_clip_id": 1,
  "source_file": "/tmp/us-6-5-demo-dorxcmrh/source.wav",
  "start_ms": 1000,
  "end_ms": 3000,
  "role": "loop-bed",
  "prompt": "build a chill track around this",
  "backend": "ace-step",
  "created_at": "2026-05-20T20:03:04.343964+00:00"
}
```

The new clip is also registered in the clips DB with `generation_mode='sample'` and `parent_clip_id` pointing at the source — so `acemusic clips info` and `clips search` can trace lineage just like `extend`, `cover`, and `mashup` do.

## Step 4: Full test suite is green

```bash
uv run pytest --no-header -q 2>&1 | tail -3
```

```output
538 passed, 1 skipped, 7 deselected, 2 warnings in 58.75s
```

Lint and formatting are clean:

```bash
uv run ruff check src/ tests/
uv run black --check src/ tests/
```

```output
All checks passed!
All done! ✨ 🍰 ✨
```

## Summary

US-6.5 adds the `sample` command and its supporting `combine_sample` / `write_sample_metadata` utilities. All three acceptance criteria are satisfied: the sample is physically present in every output, each role produces a distinct combination, and a JSON sidecar records full attribution. Lineage is tracked in the clips DB via `parent_clip_id` and `generation_mode='sample'`, so the new command composes with the rest of the Stage 6 iterative-generation workflow.
