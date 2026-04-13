# US-3.1: Style Tags and Lyrics CLI Parameters

*2026-04-09T18:21:24Z*

US-3.1 adds five new flags to `acemusic generate`: --style, --lyrics, --lyrics-file, --vocal-language, and --instrumental. Style and lyrics are sent as separate API parameters — not merged into the prompt. This demo verifies all four acceptance criteria.

First, confirm all five flags appear in --help.

```bash
uv run acemusic generate --help
```

```output
ACE-Step server URL not configured. Set ACEMUSIC_BASE_URL in .env or config.yaml
```

```bash
ACEMUSIC_BASE_URL=http://localhost:8001 uv run acemusic generate --help
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
│ --duration              FLOAT    Desired audio duration in seconds.          │
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
│ --help                           Show this message and exit.                 │
╰──────────────────────────────────────────────────────────────────────────────╯

```

All five new flags are present: --style, --lyrics, --lyrics-file, --vocal-language, and --instrumental. Now verify Acceptance Criterion 1: all three inputs (prompt + style + lyrics) are forwarded as separate parameters.

```bash
uv run pytest tests/test_generate.py::TestStyleLyricsFlags::test_all_three_inputs_ace_step -v 2>&1 | tail -15
```

```output

================================ tests coverage ================================
_______________ coverage: platform linux, python 3.13.3-final-0 ________________

Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   199    123    38%   28-29, 45-46, 50-51, 57-106, 111-112, 144-147, 152-159, 187-232, 273-274, 278-280, 287-292, 297, 303-305, 311-312, 319-327, 346-374, 380
src/acemusic/client.py                 72     62    14%   29-30, 42-47, 79-107, 121-158, 166-173
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 358    226    37%
============================== 1 passed in 0.08s ===============================
```

AC1 passes: prompt="pop song", style="upbeat, synth-pop", and lyrics="[Verse]\nHello world" are all forwarded as separate kwargs to submit_task. Next: AC2 — --lyrics-file reads from disk.

```bash
uv run pytest tests/test_generate.py::TestStyleLyricsFlags::test_lyrics_file_flag_reads_file_and_passes_content tests/test_generate.py::TestStyleLyricsFlags::test_lyrics_file_missing_exits_one -v 2>&1 | tail -10
```

```output
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   199    118    41%   28-29, 45-46, 50-51, 57-106, 111-112, 144-147, 157-159, 187-232, 273-274, 278-280, 287-292, 297, 303-305, 311-312, 319-327, 346-374, 380
src/acemusic/client.py                 72     62    14%   29-30, 42-47, 79-107, 121-158, 166-173
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 358    221    38%
============================== 2 passed in 0.08s ===============================
```

AC2 passes: --lyrics-file reads the file and sends its content; missing file exits 1 with "not found" in output. Next: AC3 — --instrumental suppresses vocals.

```bash
uv run pytest tests/test_generate.py::TestStyleLyricsFlags::test_instrumental_flag_passed_to_submit_task tests/test_generate.py::TestStyleLyricsElevenLabs::test_instrumental_forwarded_to_elevenlabs -v 2>&1 | tail -10
```

```output
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   199    101    49%   28-29, 45-46, 50-51, 57-106, 111-112, 144-147, 152-159, 187-199, 203-206, 208, 231-232, 273-274, 278-280, 287-292, 297, 303-305, 311-312, 321-327, 358-360, 363, 371-372, 380
src/acemusic/client.py                 72     62    14%   29-30, 42-47, 79-107, 121-158, 166-173
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 358    204    43%
============================== 2 passed in 0.08s ===============================
```

AC3 passes: --instrumental forwards instrumental=True to both ACE-Step (sets instrumental in payload) and ElevenLabs (sets force_instrumental=True). Next: AC4 — --vocal-language ja on ACE-Step and warning on ElevenLabs.

```bash
uv run pytest tests/test_generate.py::TestStyleLyricsFlags::test_vocal_language_passed_to_submit_task tests/test_generate.py::TestStyleLyricsElevenLabs::test_vocal_language_elevenlabs_prints_warning -v 2>&1 | tail -10
```

```output
-----------------------------------------------------------------
src/acemusic/__init__.py                5      2    60%   5-6
src/acemusic/cli.py                   199    100    50%   28-29, 45-46, 50-51, 57-106, 111-112, 144-147, 152-159, 187-199, 203-206, 231-232, 273-274, 278-280, 287-292, 297, 303-305, 311-312, 321-327, 358-360, 363, 371-372, 380
src/acemusic/client.py                 72     62    14%   29-30, 42-47, 79-107, 121-158, 166-173
src/acemusic/config.py                 33     10    70%   40-50
src/acemusic/elevenlabs_client.py      34     26    24%   19-21, 43-66, 70-79
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 358    203    43%
============================== 2 passed in 0.08s ===============================
```

AC4 passes: --vocal-language ja is forwarded to ACE-Step as vocal_language="ja"; when used with --backend elevenlabs, a warning is printed and the flag is ignored. Also verified: when --vocal-language is omitted, ACE-Step receives vocal_language="auto" (the spec default).

Final: run the full test suite to confirm no regressions.

```bash
uv run pytest tests/ -q --ignore=tests/features -m "not integration" 2>&1 | tail -5
```

```output
src/acemusic/elevenlabs_client.py      34      2    94%   49, 51
src/acemusic/utils.py                  15      3    80%   29-32
-----------------------------------------------------------------
TOTAL                                 358     50    86%
97 passed, 6 deselected in 0.42s
```

All 97 unit tests pass with 86% coverage. All four acceptance criteria verified. US-3.1 is complete.
