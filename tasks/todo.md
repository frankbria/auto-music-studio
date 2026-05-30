# US-7.4: Stems-only and MIDI-only export (issue #43)

## Reality check — plan adaptation

The issue's CodeRabbit plan was written **before** US-5.3, US-5.4, US-7.1, US-7.2, US-7.3
were merged. It assumed `stems.py`, `midi.py`, and the whole `export` command had to be
created from scratch. They already exist:

- `stems_client.py` (`StemsClient`, demucs) — US-5.3
- `midi_client.py` (`MidiClient`, basic-pitch + mido) — US-5.4
- `export` command with `--format wav/wav32/flac/mp3` + `daw` + `--workspace` batch — US-7.1/7.2/7.3
- `daw_export._resolve_stems` / `_resolve_midi` — **already do the auto-trigger + reuse-existing
  + child-clip registration** logic this issue asks for, writing to `{clip_dir}/stems` and `{clip_dir}/midi`.

So US-7.4 reduces to: **add `stems` and `midi` as two new `--format` values on the existing
`export` command**, reusing the existing resolve helpers. No new ML code, no new deps.

## Steps

1. **`src/acemusic/daw_export.py`** — add two public functions:
   - `export_stems(clip, output_dir, *, stems_client_factory=StemsClient, reuse_existing=True)`:
     resolve via `_resolve_stems`, assert all 4 canonical stems present (else `ValueError`),
     copy each to `output_dir/<label>.wav` (via `_copy_as_wav`, transcoding reused non-wav).
     Returns `{label: Path}`. No MIDI, no ZIP.
   - `export_midi(clip, output_dir, *, midi_client_factory=MidiClient, reuse_existing=True)`:
     resolve via `_resolve_midi`, assert all 4 MIDI files present (else `ValueError`),
     copy each to `output_dir/<label>.mid`. Returns `{label: Path}`. No audio.

2. **`src/acemusic/cli.py`** — extend `export_cmd` / `_export_one_clip`:
   - Add `stems`, `midi` to allowed formats; update `--format` help text.
   - Single-clip: for stems/midi `--output` is a **directory** (default `./<basename>-stems` / `-midi`).
   - `_export_one_clip` branches on stems/midi → call new functions, return total bytes.
   - Success message: `Exported 4 stems → <dir>` / `Exported 4 MIDI files → <dir>`.
   - Reject `--workspace` + stems/midi with a clear single-clip-only error (known limitation).

3. **`tests/test_export_cli.py`** — extend (reuse fake client factories from `test_daw_export.py`):
   - `--format stems` → exactly 4 `.wav`, no `.mid`/`.zip`.
   - `--format midi` → exactly 4 `.mid`, no audio.
   - Auto-trigger: `separate`/`extract` called when no child clips exist.
   - Reuse: regeneration skipped when child clips already exist.
   - `--output` directory respected; `--workspace` + stems rejected.

## Acceptance criteria → evidence
- [ ] `--format stems` produces 4 WAV (no MIDI, no ZIP) — dir-contents assertion
- [ ] `--format midi` produces 4 MIDI (no audio) — dir-contents assertion
- [ ] Auto-separation/extraction triggered when needed — mock-call assertion + reuse assertion

## Deviations from original plan
- Do NOT create `stems.py`/`midi.py` — already exist as `stems_client.py`/`midi_client.py`.
- Do NOT add demucs/torch/basic-pitch deps — already present (optional extras).
- Reuse `_resolve_stems`/`_resolve_midi` instead of re-implementing auto-trigger.
- `--workspace` batch for stems/midi is out of scope (per-clip subdirs); rejected explicitly.
