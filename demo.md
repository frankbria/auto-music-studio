# US-2.4: Output Directory and Naming

*2026-04-07T16:11:36Z*

US-2.4 adds two capabilities to `acemusic generate`: a `--name` flag for custom filename prefixes, and a config-driven output directory fallback. This demo verifies all four acceptance criteria using the installed CLI and the test suite.

Acceptance Criterion 1: The --name and --output flags appear in the generate help.

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
                                                                                
 Generate music from a text prompt using the ACE-Step model.                    
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    prompt      TEXT  Text description of the music to generate. [required] │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --num-clips        INTEGER  Number of audio clips to generate. [default: 2]  │
│ --duration         FLOAT    Desired audio duration in seconds.               │
│ --format           TEXT     Output audio format. [default: wav]              │
│ --output           PATH     Directory to save generated files.               │
│ --name             TEXT     Custom filename prefix (e.g. 'demo' →            │
│                             demo-1.wav).                                     │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯

```

Both --output and --name flags are present. Now verifying all four acceptance criteria via the unit test suite (no live server required).

AC1 & AC2: --name "demo" produces demo-1.wav and demo-2.wav; non-existent output directory is created automatically.

```bash
uv run pytest tests/test_generate.py::TestGenerateOutputNaming::test_name_flag_produces_prefixed_filenames tests/test_generate.py::TestGenerateOutputNaming::test_output_dir_created_when_missing -v --no-header --no-cov 2>&1 | grep -E "PASSED|FAILED|ERROR"
```

```output
tests/test_generate.py::TestGenerateOutputNaming::test_name_flag_produces_prefixed_filenames PASSED [ 50%]
tests/test_generate.py::TestGenerateOutputNaming::test_output_dir_created_when_missing PASSED [100%]
```

AC3: When --output is omitted, the configured output_dir from config.yaml is used.

```bash
uv run pytest tests/test_generate.py::TestGenerateOutputNaming::test_output_falls_back_to_config_output_dir -v --no-header --no-cov 2>&1 | grep -E "PASSED|FAILED|ERROR"
```

```output
tests/test_generate.py::TestGenerateOutputNaming::test_output_falls_back_to_config_output_dir PASSED [100%]
```

AC4: When --output is omitted and no config default, files are saved to the current working directory.

```bash
uv run pytest tests/test_generate.py::TestGenerateOutputNaming::test_output_falls_back_to_cwd_when_no_config -v --no-header --no-cov 2>&1 | grep -E "PASSED|FAILED|ERROR"
```

```output
tests/test_generate.py::TestGenerateOutputNaming::test_output_falls_back_to_cwd_when_no_config PASSED [100%]
```

All 4 acceptance criteria pass. Final check: full test suite with coverage.

```bash
uv run pytest --no-header 2>&1 | tail -12
```

```output
_______________ coverage: platform linux, python 3.13.3-final-0 ________________

Name                       Stmts   Miss  Cover   Missing
--------------------------------------------------------
src/acemusic/__init__.py       5      2    60%   5-6
src/acemusic/cli.py          119     11    91%   44-45, 140-142, 166-168, 174-175, 183
src/acemusic/client.py        45      0   100%
src/acemusic/config.py        30     10    67%   38-48
src/acemusic/utils.py         15      3    80%   29-32
--------------------------------------------------------
TOTAL                        214     26    88%
======================= 50 passed, 2 deselected in 0.30s =======================
```

50 tests pass, 88% coverage. US-2.4 is complete: --name and --output directory fallback are fully implemented and verified.
