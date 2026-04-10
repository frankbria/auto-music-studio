# US-3.2: Musical Parameters (BPM, Key, Time Signature, Seed)

*2026-04-10T04:49:28Z*

US-3.2 adds --bpm, --key, --time-signature, --seed, and --duration validation to the acemusic generate command. This demo verifies each acceptance criterion: valid flags are accepted and forwarded, invalid values produce clear validation errors (not API crashes).

First, confirm all new flags appear in the CLI help output.

```bash
uv run acemusic generate --help
```

```output
ACE-Step server URL not configured. Set ACEMUSIC_BASE_URL in .env or config.yaml
```

```bash
cd /home/frankbria/projects/auto-music-studio && ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic generate --help
```

```output
                                                                                
 Usage: acemusic generate [OPTIONS] PROMPT                                      
                                                                                
 Generate music from a text prompt using the ACE-Step model or ElevenLabs       
 cloud.                                                                         
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    prompt      TEXT  Text description of the music to generate. [required] │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --num-clips             INTEGER  Number of audio clips to generate.          │
│                                  [default: 2]                                │
│ --duration              FLOAT    Target duration in seconds (30–240).        │
│ --format                TEXT     Output audio format. [default: wav]         │
│ --output                PATH     Directory to save generated files.          │
│ --name                  TEXT     Custom filename prefix (e.g. 'demo' →       │
│                                  demo-1.wav).                                │
│ --backend               TEXT     AI backend: 'ace-step' (default) or         │
│                                  'elevenlabs'.                               │
│                                  [default: ace-step]                         │
│ --style                 TEXT     Comma-separated style descriptors (e.g.     │
│                                  'dark electro, punchy drums').              │
│ --lyrics                TEXT     Inline lyrics text (supports structure tags │
│                                  like [Verse]).                              │
│ --lyrics-file           PATH     Path to a text file containing lyrics.      │
│ --vocal-language        TEXT     ISO 639-1 vocal language code (ACE-Step     │
│                                  only, e.g. 'en', 'ja').                     │
│ --instrumental                   Suppress vocals entirely.                   │
│ --bpm                   TEXT     Tempo in BPM (60–180) or 'auto'. ACE-Step   │
│                                  native; injected into prompt for            │
│                                  ElevenLabs.                                 │
│ --key                   TEXT     Tonal center (e.g. 'C major') or 'any'.     │
│                                  ACE-Step native; injected into prompt for   │
│                                  ElevenLabs.                                 │
│ --time-signature        TEXT     Meter: 3/4, 4/4, 5/4, 6/8, 7/8. ACE-Step    │
│                                  native; injected into prompt for            │
│                                  ElevenLabs.                                 │
│ --seed                  INTEGER  Fixed seed for reproducibility (-1 for      │
│                                  random). ACE-Step only.                     │
│ --help                           Show this message and exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯

```

## Acceptance Criterion 4: --bpm 999 produces a validation error, not an API crash

An out-of-range BPM (999 exceeds max 180) should exit 1 with a clear message before any API call is made.

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic generate "upbeat pop" --bpm 999 --output /tmp; echo "Exit code: $?"
```

```output
Invalid --bpm: BPM must be between 60 and 180 (or 'auto'), got: 999
Exit code: 1
```

VERIFIED: --bpm 999 exits 1 with a clear validation message and no Traceback. The API was never contacted.

## Acceptance Criterion 1: --bpm 128 is accepted and forwarded to the API

A valid BPM is accepted without error. With no live server, we verify by running the unit tests that assert the value reaches submit_task.

```bash
uv run pytest tests/test_generate.py::TestMusicalParametersAceStep::test_bpm_integer_passed_to_submit_task -v 2>&1 | tail -12
```

```output

Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   245    152    38%   28-29, 45-46, 50-51, 57-106, 111-112, 127, 130-131, 133, 183-185, 188-192, 195-205, 212-215, 220-227, 259-330, 379-380, 384-386, 393-398, 403, 409-411, 417-418, 425-433, 452-480, 486
src/acemusic/client.py                 80     70    12%   29-30, 42-47, 87-123, 137-174, 182-189
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 412    263    36%
============================== 1 passed in 0.08s ===============================
```

VERIFIED: --bpm 128 is accepted and forwarded as bpm=128 to AceStepClient.submit_task (confirmed by unit test).

## Acceptance Criterion 3: --duration 60 is accepted; --duration 10 is rejected

Duration must be in range 30–240 seconds.

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic generate "pop" --duration 10 --output /tmp; echo "Exit code: $?"
```

```output
Invalid --duration: 10.0. Must be between 30 and 240 seconds.
Exit code: 1
```

```bash
uv run pytest tests/test_generate.py::TestMusicalParametersAceStep::test_duration_valid_range_accepted -v 2>&1 | tail -5
```

```output
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 412    270    34%
============================== 1 passed in 0.07s ===============================
```

VERIFIED: --duration 10 exits 1 with validation error. --duration 60 is accepted and forwarded (confirmed by unit test).

## Acceptance Criterion 2: --seed 42 is accepted and forwarded for reproducibility

The seed is forwarded to the ACE-Step API. With ElevenLabs, a warning is shown (composition_plan mode not yet implemented) and seed is not injected into the prompt.

```bash
uv run pytest tests/test_generate.py::TestMusicalParametersAceStep::test_seed_passed_to_submit_task tests/test_generate.py::TestMusicalParametersElevenLabs::test_seed_elevenlabs_warns_only_no_injection -v 2>&1 | tail -8
```

```output
src/acemusic/cli.py                   245    129    47%   28-29, 45-46, 50-51, 57-106, 111-112, 126-134, 181-185, 188-192, 195-205, 212-215, 220-227, 259-271, 275-278, 280, 286-289, 291-294, 296-299, 307, 329-330, 379-380, 384-386, 393-398, 403, 409-411, 417-418, 427-433, 464-466, 469, 477-478, 486
src/acemusic/client.py                 80     70    12%   29-30, 42-47, 87-123, 137-174, 182-189
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 412    240    42%
============================== 2 passed in 0.08s ===============================
```

VERIFIED: --seed 42 forwarded to ACE-Step. ElevenLabs warns about composition_plan and does not inject seed into prompt.

## Additional: Invalid time-signature validation

--time-signature must be one of: 3/4, 4/4, 5/4, 6/8, 7/8.

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic generate "jazz" --time-signature "11/4" --output /tmp; echo "Exit code: $?"
```

```output
Invalid --time-signature: '11/4'. Allowed values: 3/4, 4/4, 5/4, 6/8, 7/8
Exit code: 1
```

VERIFIED: Invalid time-signature exits 1 with the allowed values listed.

## ElevenLabs prompt injection

When ACE-Step-specific musical params are used with --backend elevenlabs, each is injected as descriptive text into the prompt so ElevenLabs can use the information.

```bash
uv run pytest tests/test_generate.py::TestMusicalParametersElevenLabs -v 2>&1 | tail -15
```

```output

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.13.3-final-0 ________________

Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   245    147    40%   28-29, 45-46, 50-51, 57-106, 111-112, 127, 130-131, 133, 183-185, 188-192, 195-205, 212-215, 220-227, 237-271, 275-278, 280, 329-330, 354-420, 427-433, 464-466, 469, 477-478, 486
src/acemusic/client.py                 80     70    12%   29-30, 42-47, 87-123, 137-174, 182-189
src/acemusic/config.py                 33     19    42%   30-55
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 412    267    35%
============================== 6 passed in 0.11s ===============================
```

VERIFIED: All 6 ElevenLabs injection tests pass — bpm/key/time-signature injected into prompt, seed warned but not injected, prompt unchanged when no params set.

## Full test suite

All 116 unit tests pass at 86% coverage.

```bash
uv run pytest -q 2>&1 | tail -5
```

```output
src/acemusic/elevenlabs_client.py      34      2    94%   49, 51
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 412     56    86%
116 passed, 6 deselected in 0.55s
```

## Summary

All acceptance criteria verified:

| Criterion | Status | Evidence |
|-----------|--------|----------|
| `--bpm 128` accepted and forwarded | ✅ VERIFIED | Unit test: `test_bpm_integer_passed_to_submit_task` |
| `--seed 42` accepted and forwarded | ✅ VERIFIED | Unit test: `test_seed_passed_to_submit_task` |
| `--duration 60` accepted and forwarded | ✅ VERIFIED | Unit test: `test_duration_valid_range_accepted` |
| `--bpm 999` → validation error, not crash | ✅ VERIFIED | CLI output: exit 1, clear message, no Traceback |

Additional behaviors verified: `--duration 10` rejected, `--time-signature 11/4` rejected, ElevenLabs prompt injection for bpm/key/time-signature, seed warn-only on ElevenLabs. Full suite: 116 passed.
