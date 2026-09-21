# Issue #520 — Test suite fails under `FORCE_COLOR`

**Done when:** `FORCE_COLOR=3 uv run pytest` is green.

## Before the fix — 9 CLI tests fail (RED)

Run on `origin/main` (commit `6010f25`), with `FORCE_COLOR=3` exported:

```
$ FORCE_COLOR=3 uv run pytest tests/test_add_vocal.py tests/test_batch_export.py \
    tests/test_cover.py tests/test_export_cli.py tests/test_generate.py \
    tests/test_mashup.py tests/test_sounds.py -q
```

```
FAILED tests/test_add_vocal.py::TestAddVocalCommand::test_non_default_voice_emits_stage_25_warning
  - AssertionError: assert 'Stage 25' in '\x1b[33mVoice selection available in ...
FAILED tests/test_batch_export.py::TestSummaryAndFailures::test_summary_shows_count_and_size
  - AssertionError: assert '3 clips' in '  \x1b[32m✓\x1b[0m Third Song → third-...
FAILED tests/test_batch_export.py::TestSummaryAndFailures::test_partial_failure_continues_and_reports
FAILED tests/test_batch_export.py::TestSummaryAndFailures::test_empty_workspace_reports_zero
FAILED tests/test_cover.py::TestCoverCommand::test_voice_flag_shows_placeholder_message
FAILED tests/test_export_cli.py::TestExportCommand::test_success_message_includes_path
FAILED tests/test_generate.py::TestGenerateCommand::test_generate_prints_duration
FAILED tests/test_mashup.py::TestMashupElevenLabsBackend::test_too_short_source_fails_before_upload_naming_the_clip
FAILED tests/test_sounds.py::TestSoundsCommand::test_sounds_prints_duration

9 failed, 239 passed, 4 deselected, 13 warnings in 25.08s
```

Exactly the nine the issue names. The ANSI escapes (`\x1b[33m`, `\x1b[32m`) are visible in
every assertion message — Rich is emitting color into `CliRunner`'s non-tty buffer.

## The fix

`tests/conftest.py` pops the color-forcing variables **at import time**:

```python
for _color_var in ("FORCE_COLOR", "CLICOLOR_FORCE"):
    os.environ.pop(_color_var, None)
```

The first attempt was the autouse `monkeypatch.delenv` fixture the issue suggested, and it
did **not** work — the same 9 tests still failed. `src/acemusic/cli.py:114` builds
`console = Console()` at module import, and Rich latches `force_terminal` from the
environment in `Console.__init__`. By the time a function-scoped fixture runs, the Console
already exists. Popping in the conftest body runs before any test module imports
`acemusic.cli`.

## After the fix — green (GREEN)

Same command, same shell, same `FORCE_COLOR=3`:

```
250 passed, 4 deselected, 10 warnings in 21.49s
```

Full default suite under `FORCE_COLOR=3`:

```
$ FORCE_COLOR=3 uv run pytest -q
...
1901 passed, 1 skipped, 1272 deselected, 30 warnings in 141.62s (0:02:21)
```

**Acceptance criterion met:** `FORCE_COLOR=3 uv run pytest` is green.

## The guard is real — mutation check

`tests/test_force_color_isolation.py` re-runs an affected test in a subprocess with
`FORCE_COLOR=3`. An in-process `assert os.environ.get("FORCE_COLOR") is None` would pass in
CI with the fix deleted, because CI never sets the variable — so it would guard nothing.

Deleting the fix (replacing the `os.environ.pop` line with `pass`) and running the guard
**in CI's own conditions**, with no `FORCE_COLOR` in the calling shell:

```
$ env -u FORCE_COLOR -u CLICOLOR_FORCE uv run pytest tests/test_force_color_isolation.py -q --no-cov
FAILED tests/test_force_color_isolation.py::test_cli_output_assertions_survive_forced_color
1 failed
```

Restored, same command:

```
1 passed in 0.77s
```

Red without the fix, green with it — from a clean environment.

## Known limitations

- The guard originally parametrized over `CLICOLOR_FORCE` too. That case passed **with and
  without** the fix — this Rich version does not emit escapes for `CLICOLOR_FORCE` alone — so
  it was dropped rather than kept as a test that proves nothing. The conftest still pops the
  variable defensively.
- `PY_COLORS` and `GITHUB_ACTIONS` are read by `typer/rich_utils.py:80`, but that governs
  Typer's own help/error console, not `acemusic.cli`'s. Probed with `PY_COLORS=1`: the
  affected test passes unchanged, so neither is popped.
