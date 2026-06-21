"""CLI entry point for acemusic (US-2.1, US-2.2, US-2.3, US-4.2, US-5.1, US-5.3, US-5.4, US-5.5, US-6.2, US-6.4, US-6.5, US-6.6)."""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import typer
from pydub import AudioSegment
from rich.console import Console
from rich.table import Table

from acemusic import __version__
from acemusic.audio import (
    EXPORT_FORMATS,
    SAMPLE_ROLES,
    SUPPORTED_FORMATS,
    calculate_speed_multiplier,
    combine_sample,
    crop_audio,
    crossfade_stitch,
    detect_bpm,
    detect_key,
    export_audio,
    remaster_audio,
    time_stretch_audio,
)
from acemusic.backends import BackendError, ensure_supports, resolve_backend
from acemusic.client import AceStepClient, AceStepError
from acemusic.config import AceConfig, load_config
from acemusic.constants import (
    BPM_MAX as _BPM_MAX,
    BPM_MIN as _BPM_MIN,
    DURATION_MAX as _DURATION_MAX,
    DURATION_MIN as _DURATION_MIN,
    MODELS,
    STYLE_INFLUENCE_MAX as _STYLE_INFLUENCE_MAX,
    STYLE_INFLUENCE_MIN as _STYLE_INFLUENCE_MIN,
    VALID_FORMATS as _VALID_FORMATS,
    VALID_MODELS,
    VALID_SOUND_TYPES as _VALID_SOUND_TYPES,
    VALID_TIME_SIGNATURES as _VALID_TIME_SIGNATURES,
    WEIRDNESS_MAX as _WEIRDNESS_MAX,
    WEIRDNESS_MIN as _WEIRDNESS_MIN,
)
from acemusic.daw_export import build_daw_bundle, export_midi, export_stems, project_slug
from acemusic.db import (
    create_clip,
    create_preset,
    delete_clip,
    delete_preset,
    get_clip,
    get_preset,
    list_clips,
    list_presets,
    search_clips,
    update_clip_title,
)
from acemusic.elevenlabs_client import (
    DURATION_MAX_S as EL_DURATION_MAX_S,
    DURATION_MIN_S as EL_DURATION_MIN_S,
    ElevenLabsClient,
    ElevenLabsError,
    build_inpaint_plan,
    build_mashup_plan,
)
from acemusic.midi_client import MidiClient, MidiError
from acemusic.models import Clip, Preset
from acemusic.song_structure import Section, plan_sections
from acemusic.stems_client import StemsClient, StemsError
from acemusic.utils import (
    generate_remaster_filename,
    get_duration,
    human_readable_size,
    make_filename,
    make_slug,
    parse_time_string,
    slice_audio,
    snap_to_beat,
    write_sample_metadata,
)
from acemusic.workspace import (
    Workspace,
    create_workspace,
    delete_workspace,
    ensure_default_workspace,
    get_active_workspace,
    get_clip_count,
    get_workspace_by_name,
    get_workspace_path,
    list_workspaces,
    rename_workspace,
    switch_workspace,
)

app = typer.Typer(help="acemusic — AI music generation CLI")
workspace_app = typer.Typer(help="Manage workspaces")
clips_app = typer.Typer(help="Manage audio clips")
app.add_typer(workspace_app, name="workspace")
app.add_typer(clips_app, name="clips")

presets_app = typer.Typer(help="Manage generation presets")
app.add_typer(presets_app, name="preset")
console = Console()

# Generation-parameter bounds, the ACE-Step model registry, and related enums
# now live in ``acemusic.constants`` (imported above) so the CLI and the
# platform API validate against one source of truth.

# Mashup blend strategies (US-6.4).
VALID_BLEND_MODES: frozenset[str] = frozenset({"layered", "sequential", "ai-guided"})


def _version_callback(value: bool) -> None:
    """Print version string and exit when --version flag is set."""
    if value:
        typer.echo(f"acemusic {__version__}")
        raise typer.Exit()


def _require_ace_step_url(config) -> None:
    """Exit with a friendly error if the ACE-Step server URL is not configured.

    Called by backend-capable commands on their ACE-Step path only, so explicit
    `--backend elevenlabs` invocations never require an ACE-Step server (#96).
    """
    if not config.api_url:
        message = "ACE-Step server URL not configured. Set ACEMUSIC_BASE_URL in .env or config.yaml"
        if config.elevenlabs_api_key:
            message += " (or use --backend elevenlabs)"
        typer.echo(message)
        raise typer.Exit(1)


def _get_active_ws() -> Workspace:
    """Ensure a default workspace exists and return the active one."""
    ensure_default_workspace()
    return get_active_workspace()


def _resolve_backend_or_exit(backend: str | None, capability: str | None = None) -> tuple[AceConfig, str]:
    """Load config and resolve the effective backend, exiting on ``BackendError``.

    Returns ``(config, effective_backend)``. When *capability* is given, also
    verifies the resolved backend supports it (used by ``mashup``).
    """
    config = load_config()
    try:
        effective_backend = resolve_backend(backend, config.backend)
        if capability is not None:
            ensure_supports(effective_backend, capability)
    except BackendError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)
    return config, effective_backend


def _require_elevenlabs_key(config: AceConfig) -> None:
    """Exit with the standard error if the ElevenLabs API key is not configured."""
    if not config.elevenlabs_api_key:
        console.print("[red]Error: --backend elevenlabs requires ELEVENLABS_API_KEY to be set.[/red]")
        raise typer.Exit(code=1)


def _build_elevenlabs_prompt(
    prompt: str,
    *,
    bpm: int | float | str | None,
    key: str | None,
    time_signature: str | None = None,
    vocal_language: str | None = None,
    term: str = "specific",
    warn_skip: bool = True,
    prefix: list[str] | None = None,
) -> str:
    """Augment *prompt* with ACE-Step-specific params for ElevenLabs, with warnings.

    ``term`` selects the wording ("specific" for ``generate``, "native" for
    ``sounds``). ``warn_skip`` toggles the "no equivalent; skipping" notices for
    ``--bpm auto`` / ``--key any``. ``prefix`` seeds the additions list (e.g. the
    ``"<type> sample"`` entry used by ``sounds``).

    Side effect: prints the injection/skip warnings to the module ``console``.
    """
    additions: list[str] = list(prefix) if prefix else []
    if bpm is not None and bpm != "auto":
        console.print(
            f"[yellow]Warning: --bpm is ACE-Step-{term}; injecting '{bpm} BPM' into prompt for ElevenLabs.[/yellow]"
        )
        additions.append(f"{bpm} BPM")
    elif bpm == "auto" and warn_skip:
        console.print("[yellow]Warning: --bpm auto has no ElevenLabs equivalent; skipping prompt injection.[/yellow]")
    if key is not None and key.lower() != "any":
        console.print(
            f"[yellow]Warning: --key is ACE-Step-{term}; injecting '{key}' into prompt for ElevenLabs.[/yellow]"
        )
        additions.append(key)
    elif key is not None and key.lower() == "any" and warn_skip:
        console.print("[yellow]Warning: --key any has no ElevenLabs equivalent; skipping prompt injection.[/yellow]")
    if time_signature is not None:
        console.print(
            f"[yellow]Warning: --time-signature is ACE-Step-{term}; injecting '{time_signature} time signature' into prompt for ElevenLabs.[/yellow]"
        )
        additions.append(f"{time_signature} time signature")
    if vocal_language is not None and vocal_language.lower() != "auto":
        language_name = _LANGUAGE_NAMES.get(vocal_language.lower(), vocal_language)
        console.print(
            f"[yellow]Note: ElevenLabs has no language field; injecting '{language_name} vocals' into prompt.[/yellow]"
        )
        additions.append(f"{language_name} vocals")
    if not additions:
        return prompt
    return f"{prompt}, {', '.join(additions)}"


def _render_table(
    *,
    columns: list[tuple[str, dict[str, Any]]],
    rows: list[tuple],
    title: str | None = None,
    **table_kwargs: Any,
) -> None:
    """Build and print a Rich table from *columns* (header, kwargs) and *rows*."""
    table = Table(title=title, **table_kwargs)
    for header, col_kwargs in columns:
        table.add_column(header, **col_kwargs)
    for row in rows:
        table.add_row(*row)
    console.print(table)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """acemusic — AI music generation CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
    elif ctx.invoked_subcommand not in (
        "models",
        "workspace",
        "clips",
        "preset",
        "import",
        "export",
        "crop",
        "speed",
        "stems",
        "midi",
        "remaster",
        # Backend-capable commands check the URL on their ACE-Step path via
        # _require_ace_step_url(), so `--backend elevenlabs` works without an
        # ACE-Step server; `compose` is ElevenLabs-only (#96).
        "compose",
        "generate",
        "sounds",
        "sample",
        "repaint",
        "extend",
        "mashup",
    ):
        config = load_config()
        if not config.api_url:
            typer.echo("ACE-Step server URL not configured. Set ACEMUSIC_BASE_URL in .env or config.yaml")
            raise typer.Exit(1)


@app.command()
def health() -> None:
    """Check connectivity and stats for the ACE-Step server and ElevenLabs key status."""
    config = load_config()

    ace_healthy = True
    client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
    try:
        stats = client.get_stats(timeout=5.0)
    except Exception as exc:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            console.print("[red]ACE-Step: unreachable — connection timed out[/red]")
        elif isinstance(exc, httpx.HTTPStatusError):
            console.print(f"[red]ACE-Step: error — {exc.response.status_code} {exc.response.text}[/red]")
        else:
            console.print(f"[red]ACE-Step: unreachable — {exc}[/red]")
        ace_healthy = False
        stats = {}

    if ace_healthy:
        console.print("[green]ACE-Step: healthy[/green]")

        models = stats.get("models", [])
        models_str = ", ".join(models) if models else "—"

        active_jobs = stats.get("active_jobs", "—")
        avg_job_time = stats.get("avg_job_time")
        avg_str = f"{avg_job_time:.1f}s" if isinstance(avg_job_time, (int, float)) else "—"

        _render_table(
            columns=[("Key", {"style": "bold"}), ("Value", {})],
            rows=[
                ("Server URL", config.api_url),
                ("Loaded models", models_str),
                ("Active jobs", str(active_jobs)),
                ("Avg job time", avg_str),
            ],
            show_header=False,
            box=None,
            padding=(0, 1),
        )

    # ElevenLabs key status — always shown regardless of ACE-Step health
    if config.elevenlabs_api_key:
        el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
        key_valid = el_client.validate_key()
        if key_valid:
            console.print("[green]ElevenLabs: configured (valid)[/green]")
        else:
            console.print("[red]ElevenLabs: configured (invalid — check ELEVENLABS_API_KEY)[/red]")
    else:
        console.print("[yellow]ElevenLabs: not configured (ELEVENLABS_API_KEY not set)[/yellow]")

    if not ace_healthy:
        raise typer.Exit(code=1)


@app.command()
def models() -> None:
    """List available ACE-Step model variants with VRAM and inference step requirements."""
    table = Table(title="ACE-Step Model Variants", show_header=True)
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("VRAM (DIT size)", style="yellow", no_wrap=True)
    table.add_column("Inference Steps", style="green", no_wrap=True)
    for key, info in MODELS.items():
        vram_dit = f"{info['vram']} ({info['dit_size']})"
        table.add_row(key, info["description"], vram_dit, info["steps"])
    console.print(table)


def _is_connection_error(exc: AceStepError) -> bool:
    """Return True if the AceStepError is a connection/timeout failure (not an API error)."""
    msg = str(exc).lower()
    return any(
        keyword in msg
        # "timed out" and "timeout" are distinct substrings: httpx renders read/
        # connect timeouts as "timed out", so both must be matched.
        for keyword in ("connection refused", "connect", "timeout", "timed out", "unreachable", "name or service")
    )


def _is_timeout_error(exc: AceStepError) -> bool:
    """Return True if the failure is a timeout (server slow-but-reachable)."""
    if exc.is_connection:
        return exc.is_timeout
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg


def _should_fall_back(exc: AceStepError) -> bool:
    """Whether an ACE-Step failure warrants switching to ElevenLabs.

    Only a **hard connection failure** (server unreachable) qualifies. Timeouts
    mean ACE-Step is slow-but-reachable (the job may still finish, and ACE-Step
    flags were requested), and API/HTTP errors mean the server responded — neither
    should switch backends.
    """
    if exc.is_connection:
        return not exc.is_timeout
    return _is_connection_error(exc) and not _is_timeout_error(exc)


_MAX_CONSECUTIVE_POLL_ERRORS = 5


def _poll_until_complete(
    ace_client: AceStepClient,
    task_id: str,
    status_bar,
    label: str,
    poll_timeout: float,
    poll_interval: float = 2.0,
    raise_on_transport_error: bool = False,
) -> dict:
    """Poll ``query_result`` until the task completes; return the result dict.

    Retry policy for transient poll failures:

    - **Timeouts** mean the server is reachable but slow (e.g. blocking while it
      loads models on a cold start). These are retried for the *full*
      ``poll_timeout`` budget — they must not abort a legitimately long warmup.
    - **Hard connection failures** (refused/unreachable) mean the server is
      likely down, so after ``_MAX_CONSECUTIVE_POLL_ERRORS`` consecutive ones we
      fail fast instead of waiting out the whole budget. A single successful poll
      (or a timeout) resets the counter.
    - A **genuine API error** aborts immediately.

    When ``raise_on_transport_error`` is True, a **persistent connection failure**
    (the consecutive-failure abort — ACE-Step is unreachable) re-raises the
    ``AceStepError`` (with ``is_connection=True``) so the caller can fall back to
    another backend (used by ``generate``). A **timeout** does NOT trigger
    fallback: it means ACE-Step is reachable but slow, the job may still finish,
    and ACE-Step flags were requested — so timeouts always ``typer.Exit``.
    Reported ``failed`` status and genuine API errors also always exit (never a
    transport problem).

    Raises:
        AceStepError: persistent connection failure (``is_connection=True``)
            when ``raise_on_transport_error`` is set.
        typer.Exit: otherwise on timeout/failure/abort.
    """
    start = time.monotonic()
    consecutive_conn_failures = 0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= poll_timeout:
            # A timeout means ACE-Step is reachable but slow (cold start / long job),
            # not down — do NOT fall back (the job may still finish, and ACE-Step
            # flags like --model/--thinking were requested). Always exit here.
            console.print(f"[red]Timed out after {poll_timeout:.0f} seconds.[/red]")
            raise typer.Exit(code=1)

        try:
            result = ace_client.query_result(task_id)
            consecutive_conn_failures = 0
        except AceStepError as exc:
            if not exc.is_connection:
                # Genuine API/HTTP error — surface it immediately (never a fallback case).
                console.print(f"[red]Error polling status: {exc}[/red]")
                raise typer.Exit(code=1)
            # Transport failure (classified by the is_connection flag, not message
            # text, so a 500 whose body mentions "connection" is never mistaken for one).
            if exc.is_timeout:
                # Server is reachable but slow — keep polling within the budget.
                consecutive_conn_failures = 0
            else:
                consecutive_conn_failures += 1
                if consecutive_conn_failures >= _MAX_CONSECUTIVE_POLL_ERRORS:
                    if raise_on_transport_error:
                        raise
                    console.print(
                        f"[red]Error polling status after {consecutive_conn_failures} consecutive "
                        f"connection failures: {exc}[/red]"
                    )
                    raise typer.Exit(code=1)
            status_bar.update(f"[bold green]{label}… ({elapsed:.0f}s) — waiting for server…[/bold green]")
            time.sleep(poll_interval)
            continue

        job_status = result.get("status", "unknown")
        status_bar.update(f"[bold green]{label}… ({elapsed:.0f}s) — {job_status}[/bold green]")

        if job_status == "completed":
            return result
        if job_status == "failed":
            error_msg = result.get("error", "unknown error")
            console.print(f"[red]Generation failed: {error_msg}[/red]")
            raise typer.Exit(code=1)

        time.sleep(poll_interval)


# ISO 639-1 codes → English names for ElevenLabs prompt injection (the API has
# no language field; vocal language is steered through the prompt text).
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "sv": "Swedish",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
}


def _parse_bpm(value: str) -> int | str:
    """Parse --bpm value: 'auto' is returned as-is; otherwise validate integer 60–180."""
    if value.lower() == "auto":
        return "auto"
    try:
        bpm_int = int(value)
    except ValueError:
        raise typer.BadParameter(f"BPM must be an integer ({_BPM_MIN}–{_BPM_MAX}) or 'auto', got: {value!r}")
    if not (_BPM_MIN <= bpm_int <= _BPM_MAX):
        raise typer.BadParameter(f"BPM must be between {_BPM_MIN} and {_BPM_MAX} (or 'auto'), got: {bpm_int}")
    return bpm_int


def _validate_key(value: str | None) -> str | None:
    """Validate --key: strip whitespace, reject empty/blank values."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise typer.BadParameter("--key cannot be empty or whitespace-only")
    return stripped


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Text description of the music to generate."),
    num_clips: int = typer.Option(2, "--num-clips", help="Number of audio clips to generate."),
    duration: Optional[float] = typer.Option(
        None, "--duration", help=f"Target duration in seconds ({int(_DURATION_MIN)}–{int(_DURATION_MAX)})."
    ),
    format: str = typer.Option("wav", "--format", help="Output audio format."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save generated files."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix (e.g. 'demo' → demo-1.wav)."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto' (default — ACE-Step, fall back to ElevenLabs), 'ace-step', or 'elevenlabs'. "
        "Defaults to ACEMUSIC_BACKEND, then 'auto'.",
    ),
    preset: Optional[str] = typer.Option(None, "--preset", help="Apply a saved preset (flags override preset values)."),
    style: Optional[str] = typer.Option(
        None, "--style", help="Comma-separated style descriptors (e.g. 'dark electro, punchy drums')."
    ),
    lyrics: Optional[str] = typer.Option(
        None, "--lyrics", help="Inline lyrics text (supports structure tags like [Verse])."
    ),
    lyrics_file: Optional[Path] = typer.Option(None, "--lyrics-file", help="Path to a text file containing lyrics."),
    vocal_language: Optional[str] = typer.Option(
        None,
        "--vocal-language",
        help="ISO 639-1 vocal language code (e.g. 'en', 'ja'). ACE-Step native; injected into prompt for ElevenLabs.",
    ),
    instrumental: bool = typer.Option(False, "--instrumental", help="Suppress vocals entirely."),
    bpm: Optional[str] = typer.Option(
        None,
        "--bpm",
        help=f"Tempo in BPM ({_BPM_MIN}–{_BPM_MAX}) or 'auto'. ACE-Step native; injected into prompt for ElevenLabs.",
    ),
    key: Optional[str] = typer.Option(
        None,
        "--key",
        help="Tonal center (e.g. 'C major') or 'any'. ACE-Step native; injected into prompt for ElevenLabs.",
    ),
    time_signature: Optional[str] = typer.Option(
        None,
        "--time-signature",
        help=f"Meter: {', '.join(sorted(_VALID_TIME_SIGNATURES))}. ACE-Step native; injected into prompt for ElevenLabs.",
    ),
    seed: Optional[int] = typer.Option(
        None, "--seed", help="Fixed seed for reproducibility (-1 for random). ACE-Step only."
    ),
    inference_steps: Optional[int] = typer.Option(
        None, "--inference-steps", help="Number of diffusion steps (Turbo: 8, Standard: 32-64). ACE-Step only."
    ),
    weirdness: int = typer.Option(
        50, "--weirdness", help="Deviation from conventional structures (0-100). ACE-Step only."
    ),
    style_influence: int = typer.Option(
        50, "--style-influence", help="Adherence to style descriptors (0-100). ACE-Step only."
    ),
    thinking: bool = typer.Option(False, "--thinking", help="Enable Chain-of-Thought mode. ACE-Step only."),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help=f"ACE-Step model variant ({', '.join(sorted(VALID_MODELS))}). ACE-Step only.",
    ),
) -> None:
    """Generate music from a text prompt using the ACE-Step model or ElevenLabs cloud."""
    if format not in _VALID_FORMATS:
        console.print(f"[red]Invalid --format: {format!r}. Allowed values: {', '.join(sorted(_VALID_FORMATS))}[/red]")
        raise typer.Exit(code=1)

    if inference_steps is not None and inference_steps <= 0:
        console.print(
            f"[red]Invalid --inference-steps: {inference_steps}. --inference-steps must be a positive integer.[/red]"
        )
        raise typer.Exit(code=1)

    if not (_WEIRDNESS_MIN <= weirdness <= _WEIRDNESS_MAX):
        console.print(
            f"[red]Invalid --weirdness: {weirdness}. Must be between {_WEIRDNESS_MIN} and {_WEIRDNESS_MAX}.[/red]"
        )
        raise typer.Exit(code=1)

    if not (_STYLE_INFLUENCE_MIN <= style_influence <= _STYLE_INFLUENCE_MAX):
        console.print(
            f"[red]Invalid --style-influence: {style_influence}. "
            f"Must be between {_STYLE_INFLUENCE_MIN} and {_STYLE_INFLUENCE_MAX}.[/red]"
        )
        raise typer.Exit(code=1)

    parsed_bpm: int | str | None = None
    if bpm is not None:
        try:
            parsed_bpm = _parse_bpm(bpm)
        except typer.BadParameter as exc:
            console.print(f"[red]Invalid --bpm: {exc}[/red]")
            raise typer.Exit(code=1)

    try:
        key = _validate_key(key)
    except typer.BadParameter as exc:
        console.print(f"[red]Invalid --key: {exc}[/red]")
        raise typer.Exit(code=1)

    if time_signature is not None and time_signature not in _VALID_TIME_SIGNATURES:
        console.print(
            f"[red]Invalid --time-signature: {time_signature!r}. "
            f"Allowed values: {', '.join(sorted(_VALID_TIME_SIGNATURES))}[/red]"
        )
        raise typer.Exit(code=1)

    # Resolve the backend early (CLI flag > config default > auto) so duration
    # limits can be backend-aware. May change to "elevenlabs" below only when
    # resolved to "auto" (auto-fallback).
    config, effective_backend = _resolve_backend_or_exit(backend)

    # Load and apply preset if provided
    if preset is not None:
        try:
            ws = _get_active_ws()
            preset_obj = get_preset(ws.id, preset)
            if preset_obj is None:
                console.print(f"[red]Error: Preset '{preset}' not found.[/red]")
                raise typer.Exit(code=1)

            # Apply preset values, but allow CLI flags to override
            style = style or preset_obj.style
            bpm = bpm or (str(preset_obj.bpm) if preset_obj.bpm else None)
            key = key or preset_obj.key
            duration = duration or preset_obj.duration
            model = model or preset_obj.model
            seed = seed or preset_obj.seed
            inference_steps = inference_steps or preset_obj.inference_steps
            vocal_language = vocal_language or preset_obj.vocal_language
            instrumental = instrumental or bool(preset_obj.instrumental)
            time_signature = time_signature or preset_obj.time_signature

        except sqlite3.Error as exc:
            console.print(f"[red]Error loading preset: {exc}[/red]")
            raise typer.Exit(code=1)

    # Validate duration AFTER preset application so preset-supplied values are
    # checked too, with backend-aware limits.
    if duration is not None:
        if effective_backend == "elevenlabs":
            # Explicit ElevenLabs backend: use the wider ElevenLabs API limits.
            if not (EL_DURATION_MIN_S <= duration <= EL_DURATION_MAX_S):
                console.print(
                    f"[red]Invalid --duration: {duration}. ElevenLabs supports "
                    f"{int(EL_DURATION_MIN_S)}–{int(EL_DURATION_MAX_S)} seconds (10 min max).[/red]"
                )
                raise typer.Exit(code=1)
        elif not (_DURATION_MIN <= duration <= _DURATION_MAX):
            # Legacy compatibility shim: older integrations defaulted to
            # --duration 15, so exactly 15.0 clamps (with a warning) instead of
            # erroring. Removable once those integrations are updated.
            if duration == 15.0:
                console.print(
                    f"[yellow]Warning: --duration 15 is below the minimum ({int(_DURATION_MIN)}s). "
                    f"Clamping to {int(_DURATION_MIN)}s. Update your integration to use --duration {int(_DURATION_MIN)} or higher.[/yellow]"
                )
                duration = _DURATION_MIN
            elif effective_backend == "auto" and EL_DURATION_MIN_S <= duration <= EL_DURATION_MAX_S:
                # 'auto' never fails just because one engine can't do the job:
                # ACE-Step can't serve this duration, but ElevenLabs can.
                if config.elevenlabs_api_key:
                    console.print(
                        f"[yellow]--duration {duration} is outside the ACE-Step range "
                        f"({int(_DURATION_MIN)}–{int(_DURATION_MAX)}s); routing to ElevenLabs.[/yellow]"
                    )
                    effective_backend = "elevenlabs"
                else:
                    console.print(
                        f"[red]Invalid --duration: {duration}. Must be between {int(_DURATION_MIN)} and "
                        f"{int(_DURATION_MAX)} seconds. Set ELEVENLABS_API_KEY to generate "
                        f"{int(EL_DURATION_MIN_S)}–{int(EL_DURATION_MAX_S)}s tracks via ElevenLabs.[/red]"
                    )
                    raise typer.Exit(code=1)
            else:
                console.print(
                    f"[red]Invalid --duration: {duration}. Must be between {int(_DURATION_MIN)} and "
                    f"{int(_DURATION_MAX)} seconds.[/red]"
                )
                raise typer.Exit(code=1)

    # Resolve model: --model flag > config.default_model > None (server default)
    resolved_model = model or config.default_model or None
    if resolved_model is not None and resolved_model not in VALID_MODELS:
        console.print(
            f"[red]Invalid --model: {resolved_model!r}. Valid options: {', '.join(sorted(VALID_MODELS))}[/red]"
        )
        raise typer.Exit(code=1)

    if output is not None:
        output_path = output
    elif config.output_dir:
        output_path = Path(config.output_dir).expanduser()
    else:
        active_ws = get_active_workspace()
        output_path = get_workspace_path(active_ws.id)
    output_path.mkdir(parents=True, exist_ok=True)

    resolved_lyrics = lyrics
    if lyrics_file is not None:
        if not lyrics_file.is_file():
            console.print(f"[red]Lyrics file not found: {lyrics_file}[/red]")
            raise typer.Exit(code=1)
        try:
            resolved_lyrics = lyrics_file.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]Cannot read lyrics file {lyrics_file}: {exc}[/red]")
            raise typer.Exit(code=1)

    slug = make_slug(prompt)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = make_slug(name) if name else None

    if effective_backend in ("auto", "ace-step"):
        _require_ace_step_url(config)
        ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
        try:
            _generate_via_ace_step(
                ace_client=ace_client,
                prompt=prompt,
                num_clips=num_clips,
                duration=duration,
                format=format,
                output_path=output_path,
                slug=slug,
                timestamp=timestamp,
                safe_name=safe_name,
                style=style,
                lyrics=resolved_lyrics,
                vocal_language=vocal_language if vocal_language is not None else "auto",
                instrumental=instrumental,
                bpm=parsed_bpm,
                key=key,
                time_signature=time_signature,
                seed=seed,
                inference_steps=inference_steps,
                weirdness=weirdness,
                style_influence=style_influence,
                thinking=thinking,
                model=resolved_model,
                # Let poll-time transport outages propagate (not exit) so they
                # reach the fallback logic below, like submit-time failures do.
                raise_on_transport_error=True,
            )
            return
        except AceStepError as exc:
            # Fall back only on a hard connection failure (server unreachable),
            # submit- or poll-time. Timeouts (slow-but-reachable) and API errors
            # exit without switching backends.
            if not _should_fall_back(exc):
                console.print(f"[red]Error: {exc}[/red]")
                raise typer.Exit(code=1)
            # Connection failure. Only 'auto' falls back; explicit 'ace-step' does not.
            if effective_backend == "ace-step":
                console.print(
                    f"[red]ACE-Step unavailable ({exc}). Use --backend auto to allow ElevenLabs fallback.[/red]"
                )
                raise typer.Exit(code=1)
            if not config.elevenlabs_api_key:
                console.print(
                    f"[red]ACE-Step unavailable ({exc}). Set ELEVENLABS_API_KEY to enable automatic fallback.[/red]"
                )
                raise typer.Exit(code=1)
            console.print("[yellow]ACE-Step unavailable — falling back to ElevenLabs[/yellow]")
            effective_backend = "elevenlabs"

    if effective_backend == "elevenlabs":
        if not config.elevenlabs_api_key:
            console.print(
                "[red]ELEVENLABS_API_KEY is not configured. Set it in .env to use the ElevenLabs backend.[/red]"
            )
            raise typer.Exit(code=1)
        if inference_steps is not None:
            console.print(
                "[yellow]Warning: --inference-steps is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]"
            )
        if weirdness != 50:
            console.print("[yellow]Warning: --weirdness is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]")
        if style_influence != 50:
            console.print(
                "[yellow]Warning: --style-influence is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]"
            )
        if thinking:
            console.print("[yellow]Warning: --thinking is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]")
        if resolved_model is not None:
            console.print("[yellow]Warning: --model is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]")

        augmented_prompt = _build_elevenlabs_prompt(
            prompt,
            bpm=parsed_bpm,
            key=key,
            time_signature=time_signature,
            vocal_language=vocal_language,
        )
        if seed is not None:
            console.print(
                "[yellow]Warning: ElevenLabs only honors --seed in composition-plan mode — "
                "use `acemusic compose --seed`. Seed is ignored for generate.[/yellow]"
            )

        el_client = ElevenLabsClient(
            api_key=config.elevenlabs_api_key,
            output_format=config.elevenlabs_output_format,
        )
        _generate_via_elevenlabs(
            el_client=el_client,
            prompt=augmented_prompt,
            num_clips=num_clips,
            duration=duration,
            output_path=output_path,
            slug=slug,
            timestamp=timestamp,
            safe_name=safe_name,
            output_format=config.elevenlabs_output_format,
            style=style,
            lyrics=resolved_lyrics,
            instrumental=instrumental,
        )
        return


def _generate_via_ace_step(
    *,
    ace_client: AceStepClient,
    prompt: str,
    num_clips: int,
    duration: Optional[float],
    format: str,
    output_path: Path,
    slug: str,
    timestamp: str,
    safe_name: Optional[str],
    style: Optional[str] = None,
    lyrics: Optional[str] = None,
    vocal_language: Optional[str] = None,
    instrumental: bool = False,
    bpm: "int | str | None" = None,
    key: Optional[str] = None,
    time_signature: Optional[str] = None,
    seed: Optional[int] = None,
    inference_steps: Optional[int] = None,
    weirdness: int = 50,
    style_influence: int = 50,
    thinking: bool = False,
    model: Optional[str] = None,
    raise_on_transport_error: bool = False,
) -> None:
    """Submit, poll, and download audio via the ACE-Step backend.

    When ``raise_on_transport_error`` is set, a poll-time transport outage
    re-raises the ``AceStepError`` (``is_connection=True``, rather than exiting)
    so ``generate`` can fall back to ElevenLabs just as it does for submit-time
    failures.
    """
    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0

    task_id = ace_client.submit_task(
        prompt=prompt,
        num_clips=num_clips,
        audio_duration=duration,
        format=format,
        style=style,
        lyrics=lyrics,
        vocal_language=vocal_language,
        instrumental=instrumental,
        bpm=bpm,
        key=key,
        time_signature=time_signature,
        seed=seed,
        inference_steps=inference_steps,
        weirdness=weirdness,
        style_influence=style_influence,
        thinking=thinking,
        model=model,
    )
    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    with console.status("[bold green]Generating…[/bold green]", spinner="dots") as status:
        result = _poll_until_complete(
            ace_client,
            task_id,
            status,
            "Generating",
            poll_timeout,
            poll_interval,
            raise_on_transport_error=raise_on_transport_error,
        )

    audio_urls: list[str] = result.get("audio_urls", [])
    for i, url in enumerate(audio_urls, start=1):
        if safe_name:
            filename = f"{safe_name}-{i}.{format}"
        else:
            filename = make_filename(slug, timestamp, i, ext=format)
        dest = output_path / filename
        try:
            data = ace_client.download_audio(url)
        except AceStepError as exc:
            console.print(f"[red]Download failed for clip {i}: {exc}[/red]")
            raise typer.Exit(code=1)

        dest.write_bytes(data)
        dur: Optional[float] = None
        try:
            dur = get_duration(dest)
            dur_str = f"{dur:.1f}s"
        except Exception:
            dur_str = "unknown"

        try:
            ws = get_active_workspace()
            bpm_int = int(bpm) if isinstance(bpm, (int, float)) else None
            clip = Clip(
                title=f"{slug}-{i}",
                workspace_id=ws.id,
                file_path=str(dest.resolve()),
                format=format,
                duration=dur,
                bpm=bpm_int,
                key=key,
                style_tags=style,
                lyrics=lyrics,
                vocal_language=vocal_language,
                model=model,
                seed=seed,
                inference_steps=inference_steps,
                generation_mode="generate",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            create_clip(clip)
        except Exception as exc:
            warnings.warn(f"clip metadata not saved: {exc}", stacklevel=2)

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


def _elevenlabs_ext(output_format: str) -> str:
    """Map an ElevenLabs output_format string to a file extension."""
    if output_format.startswith("mp3"):
        return "mp3"
    if output_format.startswith("pcm"):
        return "wav"
    if output_format.startswith("opus"):
        return "opus"
    if output_format.startswith("ulaw") or output_format.startswith("alaw"):
        return "wav"
    return "mp3"


def _generate_via_elevenlabs(
    *,
    el_client: ElevenLabsClient,
    prompt: str,
    num_clips: int,
    duration: Optional[float],
    output_path: Path,
    slug: str,
    timestamp: str,
    safe_name: Optional[str],
    output_format: str,
    style: Optional[str] = None,
    lyrics: Optional[str] = None,
    instrumental: bool = False,
) -> None:
    """Generate N clips sequentially via ElevenLabs and save them to disk."""
    ext = _elevenlabs_ext(output_format)
    console.print(f"[cyan]Generating via ElevenLabs ({output_format})…[/cyan]")
    for i in range(1, num_clips + 1):
        with console.status(f"[bold green]Clip {i}/{num_clips}…[/bold green]", spinner="dots"):
            try:
                data = el_client.generate(
                    prompt=prompt,
                    duration=duration,
                    instrumental=instrumental,
                    style=style,
                    lyrics=lyrics,
                )
            except ElevenLabsError as exc:
                console.print(f"[red]ElevenLabs error: {exc}[/red]")
                raise typer.Exit(code=1)

        if safe_name:
            filename = f"{safe_name}-{i}.{ext}"
        else:
            filename = make_filename(slug, timestamp, i, ext=ext)
        dest = output_path / filename
        dest.write_bytes(data)
        el_dur: Optional[float] = None
        try:
            el_dur = get_duration(dest)
            dur_str = f"{el_dur:.1f}s"
        except Exception:
            dur_str = "unknown"

        try:
            ws = get_active_workspace()
            clip = Clip(
                title=f"{slug}-{i}",
                workspace_id=ws.id,
                file_path=str(dest.resolve()),
                format=ext,
                duration=el_dur,
                style_tags=style,
                lyrics=lyrics,
                model="elevenlabs",
                generation_mode="generate",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            create_clip(clip)
        except Exception as exc:
            warnings.warn(f"clip metadata not saved: {exc}", stacklevel=2)

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


@app.command()
def sounds(
    prompt: str = typer.Argument(..., help="Text description of the sound to generate."),
    sound_type: str = typer.Option(..., "--type", help="Sound type: 'one-shot' or 'loop'."),
    num_clips: int = typer.Option(1, "--num-clips", help="Number of audio clips to generate."),
    duration: Optional[float] = typer.Option(None, "--duration", help="Target duration in seconds."),
    format: str = typer.Option("wav", "--format", help="Output audio format."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save generated files."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix (e.g. 'kick' → kick-1.wav)."),
    bpm: Optional[str] = typer.Option(
        None,
        "--bpm",
        help=f"Tempo in BPM ({_BPM_MIN}–{_BPM_MAX}) or 'auto'. Applies to loops.",
    ),
    key: Optional[str] = typer.Option(
        None,
        "--key",
        help="Tonal center (e.g. 'A minor'). Applies to loops.",
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto'/'ace-step' (ACE-Step) or 'elevenlabs'. Defaults to ACEMUSIC_BACKEND, then 'auto'. "
        "(Automatic ElevenLabs fallback currently applies to `generate`, not `sounds`.)",
    ),
) -> None:
    """Generate short audio samples (loops or one-shots) via ACE-Step or ElevenLabs."""
    if format not in _VALID_FORMATS:
        console.print(f"[red]Invalid --format: {format!r}. Allowed values: {', '.join(sorted(_VALID_FORMATS))}[/red]")
        raise typer.Exit(code=1)

    if sound_type not in _VALID_SOUND_TYPES:
        console.print(
            f"[red]Invalid --type: {sound_type!r}. Allowed values: {', '.join(sorted(_VALID_SOUND_TYPES))}[/red]"
        )
        raise typer.Exit(code=1)

    parsed_bpm: int | str | None = None
    if bpm is not None:
        try:
            parsed_bpm = _parse_bpm(bpm)
        except typer.BadParameter as exc:
            console.print(f"[red]Invalid --bpm: {exc}[/red]")
            raise typer.Exit(code=1)

    try:
        key = _validate_key(key)
    except typer.BadParameter as exc:
        console.print(f"[red]Invalid --key: {exc}[/red]")
        raise typer.Exit(code=1)

    if sound_type == "one-shot" and (parsed_bpm is not None or key is not None):
        console.print("[red]--bpm and --key are only valid with --type 'loop'.[/red]")
        raise typer.Exit(code=1)

    # Resolve the backend (CLI flag > config default > auto). No auto-fallback
    # for sounds (matches `sample`): 'auto' routes to ACE-Step.
    config, effective_backend = _resolve_backend_or_exit(backend)

    if effective_backend == "elevenlabs" and duration is not None:
        if not (EL_DURATION_MIN_S <= duration <= EL_DURATION_MAX_S):
            console.print(
                f"[red]Invalid --duration: {duration}. ElevenLabs supports "
                f"{int(EL_DURATION_MIN_S)}–{int(EL_DURATION_MAX_S)} seconds (10 min max). "
                f"Use --backend ace-step for shorter samples.[/red]"
            )
            raise typer.Exit(code=1)

    if output is not None:
        output_path = output
    elif config.output_dir:
        output_path = Path(config.output_dir).expanduser()
    else:
        output_path = Path.cwd()
    output_path.mkdir(parents=True, exist_ok=True)

    slug = make_slug(prompt)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = make_slug(name) if name else None

    if effective_backend == "elevenlabs":
        _require_elevenlabs_key(config)
        if format != "mp3":
            console.print(f"[yellow]Warning: ElevenLabs output is MP3-only; --format {format} is ignored.[/yellow]")

        # ElevenLabs has no sound mode or native bpm/key controls — steer them
        # through the prompt, mirroring the `generate` command's injections.
        augmented_prompt = _build_elevenlabs_prompt(
            prompt,
            bpm=parsed_bpm,
            key=key,
            term="native",
            warn_skip=False,
            prefix=[f"{sound_type} sample"],
        )

        el_client = ElevenLabsClient(
            api_key=config.elevenlabs_api_key,
            output_format=config.elevenlabs_output_format,
        )
        _sounds_via_elevenlabs(
            el_client=el_client,
            prompt=augmented_prompt,
            num_clips=num_clips,
            duration=duration,
            output_path=output_path,
            slug=slug,
            timestamp=timestamp,
            safe_name=safe_name,
            output_format=config.elevenlabs_output_format,
        )
        return

    _require_ace_step_url(config)
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
    try:
        _sounds_via_ace_step(
            ace_client=ace_client,
            prompt=prompt,
            sound_type=sound_type,
            num_clips=num_clips,
            duration=duration,
            format=format,
            output_path=output_path,
            slug=slug,
            timestamp=timestamp,
            safe_name=safe_name,
            bpm=parsed_bpm,
            key=key,
        )
    except AceStepError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


def _sounds_via_ace_step(
    *,
    ace_client: AceStepClient,
    prompt: str,
    sound_type: str,
    num_clips: int,
    duration: Optional[float],
    format: str,
    output_path: Path,
    slug: str,
    timestamp: str,
    safe_name: Optional[str],
    bpm: "int | str | None" = None,
    key: Optional[str] = None,
) -> None:
    """Submit, poll, and download a short audio sample via the ACE-Step backend."""
    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0

    task_id = ace_client.submit_task(
        prompt=prompt,
        num_clips=num_clips,
        audio_duration=duration,
        format=format,
        bpm=bpm,
        key=key,
        mode="sound",
        sound_type=sound_type,
    )
    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    with console.status("[bold green]Generating…[/bold green]", spinner="dots") as status:
        result = _poll_until_complete(ace_client, task_id, status, "Generating", poll_timeout, poll_interval)

    audio_urls: list[str] = result.get("audio_urls", [])
    for i, url in enumerate(audio_urls, start=1):
        if safe_name:
            filename = f"{safe_name}-{i}.{format}"
        else:
            filename = make_filename(slug, timestamp, i, ext=format)
        dest = output_path / filename
        try:
            data = ace_client.download_audio(url)
        except AceStepError as exc:
            console.print(f"[red]Download failed for clip {i}: {exc}[/red]")
            raise typer.Exit(code=1)

        dest.write_bytes(data)
        try:
            dur = get_duration(dest)
            dur_str = f"{dur:.1f}s"
        except Exception:
            dur_str = "unknown"

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


def _sounds_via_elevenlabs(
    *,
    el_client: ElevenLabsClient,
    prompt: str,
    num_clips: int,
    duration: Optional[float],
    output_path: Path,
    slug: str,
    timestamp: str,
    safe_name: Optional[str],
    output_format: str,
) -> None:
    """Generate N short samples sequentially via ElevenLabs and save them to disk.

    Mirrors the ACE-Step sounds path: files only, no Clip records.
    """
    ext = _elevenlabs_ext(output_format)
    console.print(f"[cyan]Generating via ElevenLabs ({output_format})…[/cyan]")
    for i in range(1, num_clips + 1):
        with console.status(f"[bold green]Clip {i}/{num_clips}…[/bold green]", spinner="dots"):
            try:
                data = el_client.generate(prompt=prompt, duration=duration)
            except ElevenLabsError as exc:
                console.print(f"[red]ElevenLabs error: {exc}[/red]")
                raise typer.Exit(code=1)

        if safe_name:
            filename = f"{safe_name}-{i}.{ext}"
        else:
            filename = make_filename(slug, timestamp, i, ext=ext)
        dest = output_path / filename
        dest.write_bytes(data)
        try:
            dur_str = f"{get_duration(dest):.1f}s"
        except Exception:
            dur_str = "unknown"

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


@app.command()
def compose(
    prompt: str = typer.Argument(..., help="Text description of the song to compose."),
    duration: Optional[float] = typer.Option(
        None,
        "--duration",
        help=f"Target total length in seconds ({int(EL_DURATION_MIN_S)}–{int(EL_DURATION_MAX_S)}).",
    ),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the composed track."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix and clip title."),
    instrumental: bool = typer.Option(False, "--instrumental", help="Compose without vocals."),
    seed: Optional[int] = typer.Option(
        None, "--seed", help="Random seed for more consistent results (plan mode only)."
    ),
) -> None:
    """Compose a structured multi-section track via an ElevenLabs composition plan.

    Creates a sectioned plan (intro/verse/chorus/…) from the prompt, displays it,
    then generates the full track in one shot. ElevenLabs only; output format
    follows ELEVENLABS_OUTPUT_FORMAT (default: MP3).
    """
    if duration is not None and not (EL_DURATION_MIN_S <= duration <= EL_DURATION_MAX_S):
        console.print(
            f"[red]Invalid --duration: {duration}. ElevenLabs supports "
            f"{int(EL_DURATION_MIN_S)}–{int(EL_DURATION_MAX_S)} seconds (10 min max).[/red]"
        )
        raise typer.Exit(code=1)

    config = load_config()
    if not config.elevenlabs_api_key:
        console.print("[red]ELEVENLABS_API_KEY is not configured. Set it in .env to use the compose command.[/red]")
        raise typer.Exit(code=1)

    if output is not None:
        output_path = output
    elif config.output_dir:
        output_path = Path(config.output_dir).expanduser()
    else:
        active_ws = get_active_workspace()
        output_path = get_workspace_path(active_ws.id)
    output_path.mkdir(parents=True, exist_ok=True)

    plan_prompt = prompt
    if instrumental:
        plan_prompt = f"{prompt}, instrumental, no vocals"

    el_client = ElevenLabsClient(
        api_key=config.elevenlabs_api_key,
        output_format=config.elevenlabs_output_format,
    )
    _compose_via_elevenlabs(
        el_client=el_client,
        prompt=prompt,
        plan_prompt=plan_prompt,
        duration=duration,
        output_path=output_path,
        name=name,
        seed=seed,
        output_format=config.elevenlabs_output_format,
    )


def _compose_via_elevenlabs(
    *,
    el_client: ElevenLabsClient,
    prompt: str,
    plan_prompt: str,
    duration: Optional[float],
    output_path: Path,
    name: Optional[str],
    seed: Optional[int],
    output_format: str,
) -> None:
    """Create a composition plan, display it, generate the track, and save it."""
    with console.status("[bold green]Creating composition plan…[/bold green]", spinner="dots"):
        try:
            plan = el_client.create_plan(prompt=plan_prompt, duration=duration)
        except ElevenLabsError as exc:
            console.print(f"[red]ElevenLabs error: {exc}[/red]")
            raise typer.Exit(code=1)

    sections = plan.get("sections", [])
    table = Table(title="Composition Plan")
    table.add_column("Section", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Styles")
    table.add_column("Lyric lines", justify="right")
    for section in sections:
        table.add_row(
            section.get("section_name", "-"),
            f"{section.get('duration_ms', 0) / 1000:.1f}s",
            ", ".join(section.get("positive_local_styles", [])),
            str(len(section.get("lines", []))),
        )
    console.print(table)

    total_s = sum(s.get("duration_ms", 0) for s in sections) / 1000
    console.print(f"[cyan]Generating {len(sections)} sections ({total_s:.0f}s total) via ElevenLabs…[/cyan]")

    with console.status("[bold green]Composing…[/bold green]", spinner="dots"):
        try:
            data = el_client.generate_from_plan(composition_plan=plan, seed=seed)
        except ElevenLabsError as exc:
            console.print(f"[red]ElevenLabs error: {exc}[/red]")
            raise typer.Exit(code=1)

    ext = _elevenlabs_ext(output_format)
    slug = make_slug(prompt)
    if name:
        filename = f"{make_slug(name)}.{ext}"
    else:
        filename = make_filename(slug, datetime.now().strftime("%Y%m%d%H%M%S"), 1, ext=ext)
    dest = output_path / filename
    dest.write_bytes(data)

    clip_duration: Optional[float] = None
    try:
        clip_duration = get_duration(dest)
        dur_str = f"{clip_duration:.1f}s"
    except Exception:
        dur_str = "unknown"

    try:
        ws = get_active_workspace()
        clip = Clip(
            title=make_slug(name) if name else slug,
            workspace_id=ws.id,
            file_path=str(dest.resolve()),
            format=ext,
            duration=clip_duration,
            seed=seed,
            model="elevenlabs",
            generation_mode="compose",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        create_clip(clip)
    except Exception as exc:
        warnings.warn(f"clip metadata not saved: {exc}", stacklevel=2)

    console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


@workspace_app.command("create")
def workspace_create(name: str = typer.Argument(..., help="Workspace name.")) -> None:
    """Create a new workspace."""
    try:
        ws = create_workspace(name)
        console.print(f"[green]Created workspace:[/green] {ws.name}")
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@workspace_app.command("list")
def workspace_list() -> None:
    """List all workspaces."""
    try:
        ensure_default_workspace()
        workspaces = list_workspaces()
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    table = Table(title="Workspaces", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Clips", justify="right")
    table.add_column("Active", justify="center")
    table.add_column("Created")
    for ws in workspaces:
        active_mark = "[green]\u2713[/green]" if ws.is_active else ""
        table.add_row(ws.name, str(get_clip_count(ws.id)), active_mark, ws.created_at[:10])
    console.print(table)


@workspace_app.command("switch")
def workspace_switch(name: str = typer.Argument(..., help="Workspace name to activate.")) -> None:
    """Switch the active workspace."""
    try:
        switch_workspace(name)
        console.print(f"[green]Switched to workspace:[/green] {name}")
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@workspace_app.command("rename")
def workspace_rename(
    old_name: str = typer.Argument(..., help="Current workspace name."),
    new_name: str = typer.Argument(..., help="New workspace name."),
) -> None:
    """Rename a workspace."""
    try:
        rename_workspace(old_name, new_name)
        console.print(f"[green]Renamed workspace:[/green] {old_name!r} → {new_name!r}")
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@workspace_app.command("delete")
def workspace_delete(
    name: str = typer.Argument(..., help="Workspace name to delete."),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt."),
) -> None:
    """Delete a workspace (prompts if non-empty, unless --force)."""
    try:
        clips = get_clip_count(get_workspace_by_name(name).id)
        if clips > 0 and not force:
            confirmed = typer.confirm(f"Workspace {name!r} contains {clips} clip(s). Delete anyway?")
            if not confirmed:
                console.print("Aborted.")
                return
        delete_workspace(name)
        console.print(f"[green]Deleted workspace:[/green] {name}")
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Check ACE-Step server and ElevenLabs key status (alias for `health`)."""
    health()


# ---------------------------------------------------------------------------
# clips sub-application (US-4.2)
# ---------------------------------------------------------------------------


def _fmt_duration(seconds: Optional[float]) -> str:
    """Format a duration in seconds as MM:SS, or '-' if None."""
    if seconds is None:
        return "-"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins:02d}:{secs:02d}"


@clips_app.command("list")
def clips_list() -> None:
    """List all clips in the active workspace."""
    try:
        ws = _get_active_ws()
        clips = list_clips(ws.id)
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    if not clips:
        console.print("No clips found.")
        return

    table = Table(title=f"Clips — {ws.name}", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Duration", justify="right")
    table.add_column("BPM", justify="right")
    table.add_column("Source")
    table.add_column("Model")
    table.add_column("Created")
    for clip in clips:
        source = clip.generation_mode or "-"
        table.add_row(
            str(clip.id),
            clip.title or "-",
            _fmt_duration(clip.duration),
            str(clip.bpm) if clip.bpm is not None else "-",
            source,
            clip.model or "-",
            (clip.created_at or "")[:10],
        )
    console.print(table)


@clips_app.command("info")
def clips_info(clip_id: int = typer.Argument(..., help="Clip ID.")) -> None:
    """Show full metadata for a clip."""
    clip = get_clip(clip_id)
    if clip is None:
        console.print(f"[red]Clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    fields = [
        ("ID", str(clip.id)),
        ("Title", clip.title or "-"),
        ("Workspace", clip.workspace_id),
        ("File", clip.file_path),
        ("Format", clip.format or "-"),
        ("Duration", _fmt_duration(clip.duration)),
        ("BPM", str(clip.bpm) if clip.bpm is not None else "-"),
        ("Key", clip.key or "-"),
        ("Style Tags", clip.style_tags or "-"),
        ("Lyrics", clip.lyrics or "-"),
        ("Vocal Language", clip.vocal_language or "-"),
        ("Model", clip.model or "-"),
        ("Seed", str(clip.seed) if clip.seed is not None else "-"),
        ("Inference Steps", str(clip.inference_steps) if clip.inference_steps is not None else "-"),
        ("Parent Clip ID", str(clip.parent_clip_id) if clip.parent_clip_id is not None else "-"),
        ("Generation Mode", clip.generation_mode or "-"),
        ("Created", clip.created_at),
    ]
    _render_table(
        columns=[("Field", {"style": "bold"}), ("Value", {})],
        rows=fields,
        show_header=False,
        box=None,
        padding=(0, 1),
    )


@clips_app.command("rename")
def clips_rename(
    clip_id: int = typer.Argument(..., help="Clip ID."),
    new_title: str = typer.Argument(..., help="New title for the clip."),
) -> None:
    """Rename a clip."""
    success = update_clip_title(clip_id, new_title)
    if not success:
        console.print(f"[red]Clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Renamed clip {clip_id}:[/green] {new_title!r}")


@clips_app.command("delete")
def clips_delete(
    clip_id: int = typer.Argument(..., help="Clip ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a clip and its audio file (permanent — also removes the audio from disk)."""
    clip = get_clip(clip_id)
    if clip is None:
        console.print(f"[red]Clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)
    if not yes:
        typer.confirm(f"Delete clip {clip_id} and file {clip.file_path}?", abort=True)
    delete_clip(clip_id)
    Path(clip.file_path).unlink(missing_ok=True)
    console.print(f"[green]Deleted clip {clip_id}[/green] and file {clip.file_path}")


@clips_app.command("search")
def clips_search(
    style: Optional[str] = typer.Option(None, "--style", help="Filter by style tag (substring match)."),
    bpm_range: Optional[str] = typer.Option(None, "--bpm-range", help="BPM range as MIN-MAX (e.g. 100-140)."),
    key: Optional[str] = typer.Option(None, "--key", help="Filter by key (exact match, e.g. 'C major')."),
    model: Optional[str] = typer.Option(None, "--model", help="Filter by model name."),
    date_from: Optional[str] = typer.Option(
        None, "--date-from", help="Include clips created on or after this date (YYYY-MM-DD)."
    ),
    date_to: Optional[str] = typer.Option(
        None, "--date-to", help="Include clips created on or before this date (YYYY-MM-DD)."
    ),
) -> None:
    """Search clips with optional filters."""
    bpm_min: Optional[int] = None
    bpm_max: Optional[int] = None
    if bpm_range is not None:
        parts = bpm_range.split("-")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            console.print(f"[red]Invalid --bpm-range: {bpm_range!r}. Expected format: MIN-MAX (e.g. 100-140).[/red]")
            raise typer.Exit(code=1)
        bpm_min, bpm_max = int(parts[0]), int(parts[1])
        if bpm_min > bpm_max:
            console.print(f"[red]Invalid --bpm-range: min ({bpm_min}) must be ≤ max ({bpm_max}).[/red]")
            raise typer.Exit(code=1)

    try:
        ws = _get_active_ws()
        clips = search_clips(
            workspace_id=ws.id,
            style=style,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            key=key,
            model=model,
            date_from=date_from,
            date_to=date_to,
        )
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    if not clips:
        console.print("No clips found matching the given filters.")
        return

    table = Table(title="Search Results", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Duration", justify="right")
    table.add_column("BPM", justify="right")
    table.add_column("Model")
    table.add_column("Created")
    for clip in clips:
        table.add_row(
            str(clip.id),
            clip.title or "-",
            _fmt_duration(clip.duration),
            str(clip.bpm) if clip.bpm is not None else "-",
            clip.model or "-",
            (clip.created_at or "")[:10],
        )
    console.print(table)


@app.command(name="import")
def import_clip(
    file_path: Path = typer.Argument(..., help="Path to the audio file to import."),
    title: Optional[str] = typer.Option(None, "--title", help="Title for the imported clip (defaults to filename)."),
) -> None:
    """Import an existing audio file into the active workspace."""
    if not file_path.exists():
        console.print(f"[red]Error: file not found: {file_path}[/red]")
        raise typer.Exit(code=1)

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        console.print(f"[red]Error: unsupported format '{ext}'. Supported: {supported}[/red]")
        raise typer.Exit(code=1)

    try:
        ws = _get_active_ws()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = clips_dir / dest_name
    try:
        shutil.copy2(file_path, dest_path)
    except OSError as exc:
        console.print(f"[red]Error copying file: {exc}[/red]")
        raise typer.Exit(code=1)

    clip_title = title if title is not None else file_path.stem
    duration = get_duration(dest_path)
    bpm_raw = detect_bpm(dest_path)
    key = detect_key(dest_path)
    bpm = int(round(bpm_raw)) if bpm_raw is not None else None

    clip = Clip(
        title=clip_title,
        workspace_id=ws.id,
        file_path=str(dest_path.resolve()),
        format=ext.lstrip("."),
        duration=duration,
        bpm=bpm,
        key=key,
        generation_mode="upload",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        create_clip(clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    bpm_display = str(bpm) if bpm is not None else "unknown"
    key_display = key if key is not None else "unknown"
    duration_display = _fmt_duration(duration) if duration is not None else "unknown"

    console.print(f"  [green]\u2713[/green] Imported: {clip_title}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {duration_display}")
    console.print(f"    BPM:      {bpm_display}")
    console.print(f"    Key:      {key_display}")


# ---------------------------------------------------------------------------
# Export command (US-7.1)
# ---------------------------------------------------------------------------


def _clip_default_basename(clip: Clip) -> str:
    """Filename-safe base name for a clip (slug of its title, else ``clip-<id>``)."""
    if clip.title:
        slug = make_slug(clip.title)
        if slug:
            return slug
    return f"clip-{clip.id}"


def _export_one_clip(clip: Clip, format: str, dest: Path) -> int:
    """Export a single clip to ``dest`` and return the number of bytes written.

    Handles audio formats (via ``export_audio``), the ``daw`` bundle (via
    ``build_daw_bundle``), and the ``stems``/``midi`` targeted exports (via
    ``export_stems``/``export_midi``, where ``dest`` is a directory of files).
    Raises on failure; callers decide whether a failure aborts (single export)
    or is tracked and skipped (batch export).
    """
    # For stems/midi, ``dest`` is a directory of files (not a single file), so the
    # byte count is summed across the written set rather than a single stat().
    if format == "stems":
        written = export_stems(clip, dest, stems_client_factory=StemsClient)
        return sum(p.stat().st_size for p in written.values())
    if format == "midi":
        written = export_midi(clip, dest, midi_client_factory=MidiClient)
        return sum(p.stat().st_size for p in written.values())

    dest.parent.mkdir(parents=True, exist_ok=True)
    if format == "daw":
        build_daw_bundle(
            clip,
            output_path=dest,
            stems_client_factory=StemsClient,
            midi_client_factory=MidiClient,
        )
    else:
        source = Path(clip.file_path)
        if not source.exists():
            raise FileNotFoundError(f"source file not found: {source}")
        export_audio(source, dest, format)
    return dest.stat().st_size


def _batch_dest_name(clip: Clip, format: str, used: set[str]) -> str:
    """Pick a distinct, descriptive output filename for ``clip`` within a batch.

    Names derive from the clip title (or ``clip-<id>``). When two clips would
    collide (shared/empty titles), the clip id is appended to keep names unique.
    """
    base = _clip_default_basename(clip)
    suffix = "_Export.zip" if format == "daw" else f".{'wav' if format in ('wav', 'wav32') else format}"
    name = f"{base}{suffix}"
    if name in used:
        # Disambiguate with the (unique) clip id, then with a counter if even
        # that base already collides with another clip's primary name.
        name = f"{base}-{clip.id}{suffix}"
        counter = 2
        while name in used:
            name = f"{base}-{clip.id}-{counter}{suffix}"
            counter += 1
    used.add(name)
    return name


@app.command(name="export")
def export_cmd(
    clip_id: Optional[int] = typer.Argument(None, help="ID of the clip to export (single-clip mode)."),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", help="Export every clip in the named workspace (batch mode)."
    ),
    format: str = typer.Option(
        "wav",
        "--format",
        help=f"Output format: {', '.join(EXPORT_FORMATS)}, daw, stems, midi.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Single mode: output file path for audio/daw (default ./<slug>.<ext>), "
        "or output directory for stems/midi (default ./<slug>-stems|-midi). "
        "Batch mode: output directory (default current directory).",
    ),
) -> None:
    """Export a clip (or a whole workspace) to audio files, a DAW bundle, or just its stems/MIDI."""
    allowed = (*EXPORT_FORMATS, "daw", "stems", "midi")
    if format not in allowed:
        console.print(f"[red]Error: invalid --format {format!r}. Allowed values: {', '.join(allowed)}[/red]")
        raise typer.Exit(code=1)

    if (clip_id is None) == (workspace is None):
        console.print("[red]Error: provide exactly one of CLIP_ID or --workspace.[/red]")
        raise typer.Exit(code=1)

    if workspace is not None and format in ("stems", "midi"):
        console.print(
            f"[red]Error: --format {format} is single-clip only; pass a CLIP_ID instead of --workspace.[/red]"
        )
        raise typer.Exit(code=1)

    if workspace is not None:
        _batch_export(workspace, format, output)
        return

    clip = get_clip(clip_id)
    if clip is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    source = Path(clip.file_path)
    # daw/stems/midi can reuse previously generated child assets without the
    # original source on disk, so only the direct audio formats require it here.
    if format not in ("daw", "stems", "midi") and not source.exists():
        console.print(f"[red]Error: source file not found: {source}[/red]")
        raise typer.Exit(code=1)

    if output is not None:
        dest = output
    elif format == "daw":
        dest = Path.cwd() / f"{project_slug(clip)}_Export.zip"
    elif format in ("stems", "midi"):
        dest = Path.cwd() / f"{_clip_default_basename(clip)}-{format}"
    else:
        ext = "wav" if format in ("wav", "wav32") else format
        dest = Path.cwd() / f"{_clip_default_basename(clip)}.{ext}"

    try:
        size = _export_one_clip(clip, format, dest)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    label = {"daw": "DAW bundle", "stems": "stems", "midi": "MIDI files"}.get(format, "clip")
    console.print(f"  [green]✓[/green] Exported {label}: {dest}  ({size} bytes)")


def _batch_export(workspace: str, format: str, output: Optional[Path]) -> None:
    """Export every clip in ``workspace`` to ``output`` (a directory) and print a summary."""
    try:
        ws = get_workspace_by_name(workspace)
    except (ValueError, sqlite3.Error) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    out_dir = (output if output is not None else Path.cwd()).resolve()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        console.print(f"[red]Error: cannot use output directory {out_dir}: {exc}[/red]")
        raise typer.Exit(code=1)

    clips = list_clips(ws.id)
    used_names: set[str] = set()
    total_bytes = 0
    succeeded = 0
    failed = 0

    for clip in clips:
        dest = out_dir / _batch_dest_name(clip, format, used_names)
        label = clip.title or f"clip-{clip.id}"
        try:
            size = _export_one_clip(clip, format, dest)
        except Exception as exc:
            failed += 1
            console.print(f"  [yellow]![/yellow] Failed: {label} — {exc}")
            continue
        succeeded += 1
        total_bytes += size
        console.print(f"  [green]✓[/green] {label} → {dest.name}")

    total_display = human_readable_size(total_bytes)
    if failed:
        console.print(
            f"Exported {succeeded} of {succeeded + failed} clips "
            f"({failed} failed) → {out_dir} (total: {total_display})"
        )
        # Surface partial failure to callers (CI/scripts) via a non-zero exit code.
        raise typer.Exit(code=1)
    console.print(f"Exported {succeeded} clips → {out_dir} (total: {total_display})")


# ---------------------------------------------------------------------------
# Crop command (US-5.1)
# ---------------------------------------------------------------------------


@app.command()
def crop(
    clip_id: int = typer.Argument(..., help="ID of the source clip to crop."),
    start: str = typer.Option(..., "--start", help="Start time (e.g. '10s', '1m30s')."),
    end: str = typer.Option(..., "--end", help="End time (e.g. '45s', '2m')."),
    fade_in: str = typer.Option("0s", "--fade-in", help="Fade-in duration (e.g. '0.5s')."),
    fade_out: str = typer.Option("0s", "--fade-out", help="Fade-out duration (e.g. '1s')."),
    snap_to_beat_flag: bool = typer.Option(False, "--snap-to-beat", help="Round start/end to nearest beat boundary."),
) -> None:
    """Crop an existing clip to a time range, creating a new clip. Original is preserved."""
    try:
        start_ms = parse_time_string(start)
        end_ms = parse_time_string(end)
        fade_in_ms = parse_time_string(fade_in)
        fade_out_ms = parse_time_string(fade_out)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    if snap_to_beat_flag:
        if source.bpm is None:
            console.print(f"[red]Error: --snap-to-beat requires BPM metadata on clip {clip_id}, but none is set.[/red]")
            raise typer.Exit(code=1)
        start_ms = snap_to_beat(start_ms, source.bpm)
        end_ms = snap_to_beat(end_ms, source.bpm)

    if start_ms >= end_ms:
        if snap_to_beat_flag:
            console.print(
                f"[red]Error: after beat-snapping, start ({start_ms / 1000:.3f}s) "
                f"is not less than end ({end_ms / 1000:.3f}s).[/red]"
            )
        else:
            console.print(f"[red]Error: --start ({start}) must be less than --end ({end}).[/red]")
        raise typer.Exit(code=1)

    if source.duration is not None:
        source_duration_ms = int(round(source.duration * 1000))
        if end_ms > source_duration_ms:
            console.print(f"[red]Error: --end ({end}) exceeds clip duration ({source.duration:.1f}s).[/red]")
            raise typer.Exit(code=1)
    else:
        console.print(
            f"[red]Error: clip {clip_id} has no duration metadata — cannot validate --end. "
            f"Re-import the clip to detect duration.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        clips_dir = get_workspace_path(source.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    src_ext = Path(source.file_path).suffix.lower() or ".wav"
    dest_name = f"{uuid.uuid4().hex}{src_ext}"
    dest_path = clips_dir / dest_name

    try:
        crop_audio(
            input_path=source.file_path,
            output_path=str(dest_path),
            start_ms=start_ms,
            end_ms=end_ms,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )
    except Exception as exc:
        console.print(f"[red]Error during crop: {exc}[/red]")
        raise typer.Exit(code=1)

    duration_s = (end_ms - start_ms) / 1000.0
    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        format=source.format,
        duration=duration_s,
        bpm=source.bpm,
        key=source.key,
        parent_clip_id=source.id,
        generation_mode="crop",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"  [green]\u2713[/green] Cropped clip {clip_id} → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {_fmt_duration(duration_s)}")


# ---------------------------------------------------------------------------


@app.command()
def speed(
    clip_id: int = typer.Argument(..., help="ID of the source clip to adjust speed for."),
    target_bpm: Optional[float] = typer.Option(
        None, "--target-bpm", help="Target BPM (e.g. 100, 120.5). Either this or --rate is required."
    ),
    rate: Optional[float] = typer.Option(
        None,
        "--rate",
        help="Speed multiplier (e.g. 0.9 for 90% speed, 1.1 for 110%). Either this or --target-bpm is required.",
    ),
) -> None:
    """Adjust playback speed of a clip without changing pitch (time-stretch). Original is preserved."""
    if target_bpm is not None and rate is not None:
        console.print("[red]Error: provide either --target-bpm or --rate, not both.[/red]")
        raise typer.Exit(code=1)

    if target_bpm is None and rate is None:
        console.print("[red]Error: must provide either --target-bpm or --rate.[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    if target_bpm is not None:
        if source.bpm is None:
            console.print(f"[red]Error: --target-bpm requires BPM metadata on clip {clip_id}, but none is set.[/red]")
            raise typer.Exit(code=1)
        try:
            final_rate = calculate_speed_multiplier(source.bpm, target_bpm)
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(code=1)
    else:
        final_rate = rate

    if final_rate <= 0:
        console.print(f"[red]Error: rate must be positive, got {final_rate}.[/red]")
        raise typer.Exit(code=1)

    if not (0.5 <= final_rate <= 2.0):
        if target_bpm is not None:
            console.print(
                f"[red]Error: target BPM of {target_bpm} would require a rate of {final_rate:.4g}x, "
                f"which is outside the allowed range 0.5–2.0.[/red]"
            )
        else:
            console.print(f"[red]Error: rate must be between 0.5 and 2.0, got {final_rate}.[/red]")
        raise typer.Exit(code=1)

    if source.duration is None:
        console.print(
            f"[red]Error: clip {clip_id} has no duration metadata — cannot calculate new duration. "
            f"Re-import the clip to detect duration.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        clips_dir = get_workspace_path(source.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    src_ext = Path(source.file_path).suffix.lower() or ".wav"
    dest_name = f"{uuid.uuid4().hex}{src_ext}"
    dest_path = clips_dir / dest_name

    try:
        time_stretch_audio(
            input_path=source.file_path,
            output_path=str(dest_path),
            rate=final_rate,
        )
    except Exception as exc:
        console.print(f"[red]Error during time-stretch: {exc}[/red]")
        raise typer.Exit(code=1)

    new_duration_s = source.duration / final_rate
    new_bpm = None
    if source.bpm is not None:
        new_bpm = source.bpm * final_rate

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        format=source.format,
        duration=new_duration_s,
        bpm=new_bpm,
        key=source.key,
        parent_clip_id=source.id,
        generation_mode="speed",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    rate_pct = final_rate * 100
    bpm_str = f" (→ {new_bpm:.1f} BPM)" if new_bpm is not None else ""
    console.print(f"  [green]✓[/green] Speed adjusted on clip {clip_id} → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {_fmt_duration(source.duration)} → {_fmt_duration(new_duration_s)}")
    console.print(f"    Speed:    {rate_pct:.1f}%{bpm_str}")


# ---------------------------------------------------------------------------


def _separate_stems_via_demucs(source: Clip, stems_dir: Path, base_name: str, output_format: str) -> dict[str, Path]:
    """Separate stems locally with demucs and return a label → path mapping."""
    client = StemsClient()
    try:
        with console.status("[bold green]Loading model and separating stems...") as status:

            def _progress(msg: str) -> None:
                status.update(f"[bold green]{msg}")

            stem_data = client.separate(source.file_path, progress_callback=_progress)
            status.update("[bold green]Saving stems...")
            return client.save_stems(
                stem_data,
                stems_dir,
                base_name,
                sample_rate=client.model_samplerate,
                output_format=output_format,
            )
    except StemsError as exc:
        console.print(f"[red]Error during separation: {exc}[/red]")
        raise typer.Exit(code=1)


def _separate_stems_via_elevenlabs(config, source: Clip, stems_dir: Path, base_name: str) -> dict[str, Path]:
    """Separate stems via the ElevenLabs cloud API and return a label → path mapping.

    Stem files take their extension from the configured ELEVENLABS_OUTPUT_FORMAT
    (mp3 by default), matching the other ElevenLabs code paths.
    """
    _require_elevenlabs_key(config)

    el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
    try:
        with console.status("[bold green]Uploading clip and separating stems via ElevenLabs..."):
            stem_bytes = el_client.separate_stems(source.file_path)
    except ElevenLabsError as exc:
        console.print(f"[red]Error during separation: {exc}[/red]")
        raise typer.Exit(code=1)

    ext = _elevenlabs_ext(config.elevenlabs_output_format)
    stem_path_map: dict[str, Path] = {}
    for label, data in stem_bytes.items():
        stem_path = stems_dir / f"{base_name}-{label}.{ext}"
        stem_path.write_bytes(data)
        stem_path_map[label] = stem_path
    return stem_path_map


@app.command()
def stems(
    clip_id: int = typer.Argument(..., help="ID of the source clip to separate into stems."),
    output_format: Optional[str] = typer.Option(
        None,
        "--output-format",
        help="Stem output format: wav or flac (default: wav). Demucs backend only — "
        "ElevenLabs stems use ELEVENLABS_OUTPUT_FORMAT (MP3 by default).",
    ),
    output: Optional[Path] = typer.Option(None, "--output", help="Output directory (default: stems/ next to source)."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto' (default — local demucs), 'ace-step' (local demucs, 4 stems), or "
        "'elevenlabs' (cloud, 6 stems: adds guitar and piano). Defaults to ACEMUSIC_BACKEND, then 'auto'.",
    ),
) -> None:
    """Separate a clip into individual stems using AI source separation.

    The local demucs backend (auto/ace-step) produces four stems: vocals,
    drums, bass, other. The elevenlabs backend uploads the clip to the
    ElevenLabs cloud API and produces six stems: vocals, drums, bass,
    guitar, piano, other (format from ELEVENLABS_OUTPUT_FORMAT, MP3 default).
    """
    config, effective_backend = _resolve_backend_or_exit(backend)

    if effective_backend == "elevenlabs":
        if output_format is not None:
            console.print(
                "[yellow]Warning: --output-format is ignored with the elevenlabs backend "
                "(stems use the configured ELEVENLABS_OUTPUT_FORMAT, MP3 by default).[/yellow]"
            )
    else:
        # Validate output format (demucs path; None means the wav default)
        if output_format is None:
            output_format = "wav"
        if output_format not in ("wav", "flac"):
            console.print(f"[red]Error: --output-format must be wav or flac, got {output_format!r}.[/red]")
            raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    if output is not None:
        stems_dir = output
    else:
        stems_dir = Path(source.file_path).parent / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(source.file_path).stem

    start_time = time.time()
    if effective_backend == "elevenlabs":
        stem_path_map = _separate_stems_via_elevenlabs(config, source, stems_dir, base_name)
        clip_format = _elevenlabs_ext(config.elevenlabs_output_format)
    else:
        stem_path_map = _separate_stems_via_demucs(source, stems_dir, base_name, output_format)
        clip_format = output_format

    elapsed = time.time() - start_time

    new_ids = []
    for label, stem_path in stem_path_map.items():
        dur = get_duration(stem_path)
        stem_clip = Clip(
            workspace_id=source.workspace_id,
            file_path=str(stem_path.resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
            format=clip_format,
            duration=dur,
            bpm=source.bpm,
            key=source.key,
            title=label,
            parent_clip_id=source.id,
            generation_mode="stems",
        )
        try:
            new_id = create_clip(stem_clip)
            new_ids.append((label, new_id, stem_path, dur))
        except Exception as exc:
            console.print(f"[red]Error saving {label} clip record: {exc}[/red]")
            raise typer.Exit(code=1)

    console.print(f"\n  [green]✓[/green] Separated clip {clip_id} into {len(new_ids)} stems ({elapsed:.1f}s)")
    for label, nid, spath, dur in new_ids:
        dur_str = _fmt_duration(dur)
        console.print(f"    {label:<8} → clip {nid}  {spath}  ({dur_str})")


# MIDI extraction (US-5.4)
# ---------------------------------------------------------------------------


@app.command("midi")
def midi(
    clip_id: int = typer.Argument(..., help="ID of the source clip to extract MIDI from."),
    from_stems: bool = typer.Option(False, "--from-stems", help="Use separated stems for better accuracy."),
    output: Optional[Path] = typer.Option(None, "--output", help="Output directory (default: midi/ next to source)."),
    bpm: Optional[float] = typer.Option(None, "--bpm", help="Override auto-detected BPM for the MIDI tempo map."),
) -> None:
    """Extract MIDI from a clip (melody, chords, drums, bass) using AI transcription."""
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    if bpm is not None and not (20.0 <= bpm <= 300.0):
        console.print("[red]Error: --bpm must be between 20 and 300.[/red]")
        raise typer.Exit(code=1)

    if output is not None:
        midi_dir = output
    else:
        midi_dir = Path(source.file_path).parent / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(source.file_path).stem

    stem_paths = None
    if from_stems:
        clips = list_clips(source.workspace_id)
        stem_clips = {c.title: c for c in clips if c.parent_clip_id == clip_id and c.generation_mode == "stems"}
        if stem_clips:
            stem_paths = {label: Path(c.file_path) for label, c in stem_clips.items()}
            console.print(f"[cyan]Using {len(stem_paths)} extracted stems for improved accuracy.[/cyan]")
        else:
            console.print("[yellow]Warning: --from-stems requested but no stems found. Using full mix.[/yellow]")

    # Resolve tempo: explicit --bpm > clip metadata > default 120
    tempo = bpm if bpm is not None else (float(source.bpm) if source.bpm else 120.0)

    client = MidiClient()
    start_time = time.time()
    try:
        with console.status("[bold green]Extracting MIDI...") as status:

            def _progress(msg: str) -> None:
                status.update(f"[bold green]{msg}")

            extracted = client.extract(
                source.file_path,
                from_stems=from_stems,
                stem_paths=stem_paths,
                progress_callback=_progress,
            )
            status.update("[bold green]Writing MIDI files...")
            midi_path_map = client.save_midi(extracted, midi_dir, base_name, bpm=tempo)
    except MidiError as exc:
        console.print(f"[red]Error during MIDI extraction: {exc}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]Unexpected error: {exc}[/red]")
        raise typer.Exit(code=1)

    elapsed = time.time() - start_time

    # Register each MIDI output as a child clip
    new_ids = []
    for label, midi_path in midi_path_map.items():
        # Use last note end time from extracted data, or fall back to source duration
        notes = extracted.get(label, [])
        dur = max((n[1] for n in notes), default=0.0) if notes else (source.duration or 0.0)
        midi_clip = Clip(
            workspace_id=source.workspace_id,
            file_path=str(midi_path.resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
            format="mid",
            duration=dur,
            bpm=int(round(tempo)),
            key=source.key,
            title=f"midi-{label}",
            parent_clip_id=source.id,
            generation_mode="midi",
        )
        try:
            new_id = create_clip(midi_clip)
            new_ids.append((label, new_id, midi_path))
        except Exception as exc:
            console.print(f"[red]Error saving MIDI clip record: {exc}[/red]")
            raise typer.Exit(code=1)

    console.print(f"\n  [green]✓[/green] Extracted MIDI from clip {clip_id} ({elapsed:.1f}s)")
    for label, nid, mpath in new_ids:
        console.print(f"    {label:<8} → clip {nid}  {mpath}")


# ---------------------------------------------------------------------------
# Remaster command (US-5.5)
# ---------------------------------------------------------------------------


@app.command()
def remaster(
    clip_id: int = typer.Argument(..., help="ID of the source clip to remaster."),
    target_lufs: float = typer.Option(-14.0, "--target-lufs", help="Target loudness in LUFS (default: -14)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Custom output file path."),
) -> None:
    """Apply audio enhancement: loudness normalization, EQ, compression, and stereo widening. Original is preserved."""
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    src_ext = src_path.suffix.lower()
    if src_ext not in {".wav"}:
        console.print(
            f"[red]Error: unsupported format '{src_ext}' for remastering. Currently only .wav is supported.[/red]"
        )
        raise typer.Exit(code=1)

    if output is not None:
        dest_path = output
    else:
        dest_path = generate_remaster_filename(src_path)

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with console.status("[bold green]Remastering..."):
            result = remaster_audio(src_path, dest_path, target_lufs=target_lufs)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error during remastering: {exc}[/red]")
        raise typer.Exit(code=1)

    # Register new clip in DB
    dur = get_duration(dest_path)
    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        format=source.format,
        duration=dur,
        bpm=source.bpm,
        key=source.key,
        parent_clip_id=source.id,
        generation_mode="remaster",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    before_lufs = result["before_lufs"]
    after_lufs = result["after_lufs"]
    console.print(f"  [green]\u2713[/green] Remastered clip {clip_id} \u2192 clip {new_id}")
    console.print(f"    Path:   {dest_path}")
    console.print(f"    LUFS:   {before_lufs:.1f} \u2192 {after_lufs:.1f}")


# ---------------------------------------------------------------------------
# Extend command (US-6.1)
# ---------------------------------------------------------------------------


def _parse_from_flag(value: str, source_duration: float) -> float:
    """Resolve --from value to seconds. Accepts 'end' or a time string like '30s'."""
    if value.strip().lower() == "end":
        return source_duration
    return parse_time_string(value) / 1000.0


def _extend_via_elevenlabs(
    *,
    config,
    source: Clip,
    clip_id: int,
    from_ms: int,
    duration_ms: int,
    style: Optional[str],
    lyrics: Optional[str],
) -> None:
    """Extend a clip via ElevenLabs inpainting (upload → plan → compose).

    The source clip is uploaded to obtain a ``song_id``; a composition plan
    keeps [0, from] via ``source_from`` and appends a new [from, from+duration]
    section described by the source's style (or the overrides). Audio past the
    splice point is replaced, consistent with the ACE-Step behaviour — no
    local trimming is needed because the keep range handles it server-side.
    """
    _require_elevenlabs_key(config)

    # --style is an override: when given, it alone shapes the new section —
    # blending in the source's old style tags would send contradictory
    # directions to the model.
    if style:
        prompt, section_style = "continue the song", style
    else:
        prompt, section_style = (source.style_tags or source.title or "continue the song"), None
    keep_ranges = [(0, from_ms)]
    regenerate_range = (from_ms, from_ms + duration_ms)

    # Validate the plan shape before uploading — uploads are priced like a
    # generation, so range errors must fail before any credits are spent.
    try:
        build_inpaint_plan("pending-upload", keep_ranges, regenerate_range, prompt, section_style, lyrics)
    except ElevenLabsError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
    try:
        with console.status("[bold green]Uploading source clip to ElevenLabs…[/bold green]", spinner="dots"):
            song_id = el_client.upload_for_inpainting(source.file_path)
        plan = build_inpaint_plan(song_id, keep_ranges, regenerate_range, prompt, section_style, lyrics)
        with console.status("[bold green]Extending via ElevenLabs…[/bold green]", spinner="dots"):
            data = el_client.generate_from_plan(plan, seed=source.seed)
    except ElevenLabsError as exc:
        console.print(f"[red]ElevenLabs error: {exc}[/red]")
        raise typer.Exit(code=1)

    ext = _elevenlabs_ext(config.elevenlabs_output_format)
    try:
        clips_dir = get_workspace_path(source.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        dest_path = clips_dir / f"{make_slug(source.title or 'clip')}-extend-{uuid.uuid4().hex[:8]}.{ext}"
        dest_path.write_bytes(data)
    except OSError as exc:
        console.print(f"[red]Error writing extended clip: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"extended clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    new_title = f"{source.title} (extended)" if source.title else None
    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=lyrics or source.lyrics,
        vocal_language=source.vocal_language,
        model="elevenlabs",
        seed=source.seed,
        parent_clip_id=source.id,
        generation_mode="extend",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]✓[/green] Extended clip {clip_id} → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


@app.command()
def extend(
    clip_id: int = typer.Argument(..., help="ID of the source clip to extend."),
    duration: str = typer.Option(..., "--duration", help="Length of new audio to generate (e.g. '60s', '1m30s')."),
    from_: str = typer.Option("end", "--from", help="Extension point: 'end' (default) or a timestamp like '45s'."),
    style: Optional[str] = typer.Option(None, "--style", help="Optional style override for the extension."),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", help="Optional lyrics for the extended section."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto'/'ace-step' (ACE-Step repaint task) or 'elevenlabs' "
        "(cloud inpainting via composition plan; sections must be 3s–120s). "
        "Defaults to ACEMUSIC_BACKEND, then 'auto'.",
    ),
) -> None:
    """Extend an existing clip by generating audio that continues the song.

    Submits a `task_type=repaint` request to ACE-Step with the source clip as
    src_audio and a repainting region covering the new section. The result is
    saved as a new clip with `parent_clip_id` set to the source and
    `generation_mode='extend'`. Multiple extends can be chained.

    Note: Requires ACE-Step to run on the same host (or with shared filesystem
    access), since the source audio is passed via an absolute server-side path.
    Remote ACE-Step deployments are not yet supported.
    """
    try:
        duration_ms = parse_time_string(duration)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    duration_s = duration_ms / 1000.0
    if duration_s <= 0:
        console.print(f"[red]Error: --duration must be positive, got {duration!r}.[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if source.duration is None:
        console.print(
            f"[red]Error: clip {clip_id} has no duration metadata. Re-import the clip to detect duration.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        from_seconds = _parse_from_flag(from_, source.duration)
    except ValueError as exc:
        console.print(f"[red]Error: invalid --from value: {exc}[/red]")
        raise typer.Exit(code=1)

    if from_seconds <= 0 or from_seconds > source.duration:
        console.print(
            f"[red]Error: --from ({from_!r}) must be 'end' or a timestamp within the clip "
            f"(0 < t <= {source.duration:.2f}s).[/red]"
        )
        raise typer.Exit(code=1)

    repaint_start = from_seconds
    repaint_end = from_seconds + duration_s
    target_audio_duration = repaint_end

    config, effective_backend = _resolve_backend_or_exit(backend)

    if effective_backend == "elevenlabs":
        _extend_via_elevenlabs(
            config=config,
            source=source,
            clip_id=clip_id,
            from_ms=int(round(from_seconds * 1000)),
            duration_ms=duration_ms,
            style=style,
            lyrics=lyrics,
        )
        return

    _require_ace_step_url(config)
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    clips_dir = get_workspace_path(source.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    # If --from is not the end, send a trimmed source so ACE-Step's repaint region
    # lines up with the splice point even when the user wants to discard audio
    # past the splice. The trimmed file is held in a tmp location and not registered.
    src_for_api: Path = src_path
    trimmed: Optional[Path] = None
    if from_seconds < source.duration:
        trimmed = clips_dir / f"{uuid.uuid4().hex}-trim.wav"
        try:
            slice_audio(src_path, from_seconds, trimmed)
        except Exception as exc:
            trimmed.unlink(missing_ok=True)
            console.print(f"[red]Error trimming source audio: {exc}[/red]")
            raise typer.Exit(code=1)
        src_for_api = trimmed

    prompt = source.style_tags or source.title or "continue the song"
    ext = source.format or "wav"
    dest_name = f"{make_slug(source.title or 'clip')}-extend-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    try:
        try:
            task_id = ace_client.submit_task(
                prompt=prompt,
                num_clips=1,
                audio_duration=target_audio_duration,
                format=ext,
                style=style,
                lyrics=lyrics,
                bpm=source.bpm,
                key=source.key,
                seed=source.seed,
                task_type="repaint",
                src_audio_path=str(src_for_api.resolve()),
                repainting_start=repaint_start,
                repainting_end=repaint_end,
            )
        except AceStepError as exc:
            console.print(f"[red]Error submitting extend task: {exc}[/red]")
            raise typer.Exit(code=1)

        console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

        poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
        poll_interval = 2.0
        with console.status("[bold green]Extending\u2026[/bold green]", spinner="dots") as status_bar:
            result = _poll_until_complete(ace_client, task_id, status_bar, "Extending", poll_timeout, poll_interval)

        audio_urls: list[str] = result.get("audio_urls", [])
        if not audio_urls:
            console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
            raise typer.Exit(code=1)

        try:
            data = ace_client.download_audio(audio_urls[0])
        except AceStepError as exc:
            console.print(f"[red]Error downloading extended clip: {exc}[/red]")
            raise typer.Exit(code=1)

        try:
            dest_path.write_bytes(data)
        except OSError as exc:
            console.print(f"[red]Error writing extended clip: {exc}[/red]")
            raise typer.Exit(code=1)
    finally:
        if trimmed is not None:
            trimmed.unlink(missing_ok=True)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"extended clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    new_title = f"{source.title} (extended)" if source.title else None
    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=lyrics or source.lyrics,
        vocal_language=source.vocal_language,
        model=source.model,
        seed=source.seed,
        inference_steps=source.inference_steps,
        parent_clip_id=source.id,
        generation_mode="extend",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Extended clip {clip_id} \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


def _render_section_plan(seed: Clip, plan: list[Section], target_duration: int) -> None:
    """Render the planned section breakdown as a Rich table."""
    table = Table(title=f"Full-song plan (target {target_duration}s)", show_lines=False)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Section", style="bold")
    table.add_column("Duration", justify="right")
    table.add_column("Style hint", style="dim")
    table.add_row("0", "seed", f"{seed.duration:.1f}s", seed.style_tags or "\u2014")
    for i, section in enumerate(plan, start=1):
        table.add_row(str(i), section.name, f"{section.duration_s:.1f}s", section.style_hint)
    console.print(table)


def _generate_section(
    source: Clip,
    section_index: int,
    section_total: int,
    section: Section,
    base_style: Optional[str],
    base_style_tags: Optional[str],
    base_lyrics: Optional[str],
    is_final: bool,
    seed_title: Optional[str],
    ace_client: AceStepClient,
    clips_dir: Path,
) -> Clip:
    """Run one extend step for a full-song section and register the resulting clip.

    Submits a `task_type=repaint` request that grows ``source`` by
    ``section.duration_s`` seconds from its end, then writes the returned
    audio as a child clip with ``generation_mode='full-song'`` and
    ``parent_clip_id`` pointing at ``source``. Returns the new Clip.

    ``base_style_tags`` is the seed clip's original style \u2014 held stable across
    the whole chain so that section conditioning stays anchored. Without it,
    pulling ``source.style_tags`` from each previous extended clip would
    compound prior section hints into later prompts.

    Raises ``typer.Exit(code=1)`` on submission, polling, or download errors \u2014
    callers should not catch this; any successfully-committed earlier sections
    remain in the clip store as partial progress.
    """
    if source.duration is None:
        console.print("[red]Error: source clip lost duration metadata mid-pipeline.[/red]")
        raise typer.Exit(code=1)

    repaint_start = source.duration
    repaint_end = source.duration + section.duration_s
    target_audio_duration = repaint_end

    base_style_resolved = base_style or base_style_tags
    style_parts = [base_style_resolved, section.style_hint]
    section_style = ", ".join(p for p in style_parts if p)
    lyrics = base_lyrics if base_lyrics is not None else source.lyrics
    prompt = base_style_tags or seed_title or source.title or "continue the song"
    ext = source.format or "wav"

    if is_final and seed_title:
        section_title: Optional[str] = f"{seed_title} (full song)"
    elif seed_title:
        section_title = f"{seed_title} - {section.name}"
    else:
        section_title = None

    dest_name = f"{make_slug(seed_title or 'clip')}-fullsong-{section.name}-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    console.print(
        f"[bold]Section {section_index}/{section_total}[/bold]: "
        f"[cyan]{section.name}[/cyan] (+{section.duration_s:.1f}s)"
    )

    try:
        task_id = ace_client.submit_task(
            prompt=prompt,
            num_clips=1,
            audio_duration=target_audio_duration,
            format=ext,
            style=section_style,
            lyrics=lyrics,
            bpm=source.bpm,
            key=source.key,
            seed=source.seed,
            task_type="repaint",
            src_audio_path=str(Path(source.file_path).resolve()),
            repainting_start=repaint_start,
            repainting_end=repaint_end,
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting section {section.name!r}: {exc}[/red]")
        raise typer.Exit(code=1)

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status(f"[bold green]Generating {section.name}\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(
            ace_client, task_id, status_bar, f"Generating {section.name}", poll_timeout, poll_interval
        )

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print(f"[red]Error: ACE-Step returned no audio URLs for section {section.name!r}.[/red]")
        raise typer.Exit(code=1)

    try:
        data = ace_client.download_audio(audio_urls[0])
    except AceStepError as exc:
        console.print(f"[red]Error downloading section {section.name!r}: {exc}[/red]")
        raise typer.Exit(code=1)

    dest_path.write_bytes(data)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"section duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=section_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=section_style,
        lyrics=lyrics,
        vocal_language=source.vocal_language,
        model=source.model,
        seed=source.seed,
        inference_steps=source.inference_steps,
        parent_clip_id=source.id,
        generation_mode="full-song",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record for {section.name!r}: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] {section.name} \u2192 clip {new_id} ({dur_str})")
    new_clip.id = new_id
    return new_clip


@app.command("full-song")
def full_song(
    clip_id: int = typer.Argument(..., help="ID of the seed clip to grow into a full song."),
    target_duration: int = typer.Option(
        210, "--target-duration", help="Target total length in seconds (default: 210, ~3.5 min)."
    ),
    auto: bool = typer.Option(False, "--auto", help="Skip confirmation prompts and build the entire song unattended."),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Base style override; replaces the seed's style tags as the anchor for every section.",
    ),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", help="Optional lyrics applied to every generated section."),
) -> None:
    """Auto-extend a short seed clip into a full song (intro \u2192 verse \u2192 chorus \u2192 ... \u2192 outro).

    Plans seven canonical sections sized to fit ``--target-duration``, then
    chains seven ``extend`` calls \u2014 each generating one section with its own
    style hint (intro is sparse, choruses are full, the outro fades). Every
    intermediate section is registered as its own clip with
    ``generation_mode='full-song'`` so the user can audit lineage or rewind to
    any section.

    Interactive mode (default) pauses for confirmation between sections so the
    musician can stop early if a section goes off the rails; ``--auto`` runs
    end-to-end without prompts.
    """
    if target_duration <= 0:
        console.print(f"[red]Error: --target-duration must be positive, got {target_duration}.[/red]")
        raise typer.Exit(code=1)

    seed = get_clip(clip_id)
    if seed is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(seed.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: seed file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if seed.duration is None:
        console.print(
            f"[red]Error: clip {clip_id} has no duration metadata. Re-import the clip to detect duration.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        plan = plan_sections(seed_duration=seed.duration, target_duration=target_duration)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    _render_section_plan(seed, plan, target_duration)

    config = load_config()
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
    clips_dir = get_workspace_path(seed.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    current_source = seed
    last_section_clip: Optional[Clip] = None
    for i, section in enumerate(plan):
        is_final = i == len(plan) - 1
        new_clip = _generate_section(
            source=current_source,
            section_index=i + 1,
            section_total=len(plan),
            section=section,
            base_style=style,
            base_style_tags=seed.style_tags,
            base_lyrics=lyrics,
            is_final=is_final,
            seed_title=seed.title,
            ace_client=ace_client,
            clips_dir=clips_dir,
        )
        last_section_clip = new_clip
        current_source = new_clip

        if not auto and not is_final:
            next_section = plan[i + 1].name
            cont = typer.confirm(
                f"Section {section.name!r} complete. Continue to {next_section!r}?",
                default=True,
            )
            if not cont:
                console.print(f"[yellow]Stopped after section {i + 1}/{len(plan)} ({section.name!r}).[/yellow]")
                console.print(f"[yellow]Partial song saved at: {new_clip.file_path}[/yellow]")
                raise typer.Exit(code=0)

    if last_section_clip is None:
        console.print("[red]Error: no sections were generated.[/red]")
        raise typer.Exit(code=1)
    final_dur = f"{last_section_clip.duration:.1f}s" if last_section_clip.duration is not None else "unknown"
    console.print("")
    console.print(f"[bold green]\u2713 Full song complete[/bold green] \u2192 clip {last_section_clip.id}")
    console.print(f"    Path:     {last_section_clip.file_path}")
    console.print(f"    Duration: {final_dur} ({len(plan)} sections)")


@app.command()
def cover(
    clip_id: int = typer.Argument(..., help="ID of the source clip to cover."),
    style: str = typer.Option(..., "--style", help="Target style/genre for the cover (e.g. 'jazz piano trio')."),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", help="Optional lyrics override (melody preserved)."),
    voice: Optional[str] = typer.Option(None, "--voice", help="Optional custom voice id (Stage 25 feature)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the cover file."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix for the cover."),
) -> None:
    """Create a cover of an existing clip in a different style.

    Submits a `task_type=cover` request to ACE-Step with the source clip as
    src_audio. The result is saved as a new clip with `parent_clip_id` set to
    the source and `generation_mode='cover'`.

    Note: Requires ACE-Step to run on the same host (or with shared filesystem
    access), since the source audio is passed via an absolute server-side path.
    """
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if src_path.suffix.lower() not in SUPPORTED_FORMATS:
        console.print(
            f"[red]Error: source clip {clip_id} is not an audio file "
            f"({src_path.suffix or 'no extension'}). Cover requires one of: "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
        )
        raise typer.Exit(code=1)

    cover_duration = source.duration
    if cover_duration is None or cover_duration <= 0:
        try:
            cover_duration = get_duration(src_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id}: {exc}[/red]")
            raise typer.Exit(code=1)
        if cover_duration is None or cover_duration <= 0:
            console.print(f"[red]Error: source clip {clip_id} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    if voice is not None:
        console.print("[yellow]Voice selection available in Stage 25.[/yellow]")

    config = load_config()
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    if output is not None:
        clips_dir = output
    else:
        clips_dir = get_workspace_path(source.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ext = source.format or "wav"
    title_slug = make_slug(name or source.title or "clip")
    dest_name = f"{title_slug}-cover-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    try:
        task_id = ace_client.submit_task(
            prompt=style,
            num_clips=1,
            audio_duration=cover_duration,
            format=ext,
            style=style,
            lyrics=lyrics if lyrics is not None else source.lyrics,
            bpm=source.bpm,
            key=source.key,
            seed=source.seed,
            task_type="cover",
            src_audio_path=str(src_path.resolve()),
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting cover task: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status("[bold green]Covering\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(ace_client, task_id, status_bar, "Covering", poll_timeout, poll_interval)

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
        raise typer.Exit(code=1)

    try:
        data = ace_client.download_audio(audio_urls[0])
    except AceStepError as exc:
        console.print(f"[red]Error downloading cover clip: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        dest_path.write_bytes(data)
    except OSError as exc:
        console.print(f"[red]Error writing cover clip to {dest_path}: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"cover clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif source.title:
        new_title = f"{source.title} (cover)"
    else:
        new_title = None
    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style,
        lyrics=lyrics if lyrics is not None else source.lyrics,
        vocal_language=source.vocal_language,
        seed=source.seed,
        parent_clip_id=source.id,
        generation_mode="cover",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Covered clip {clip_id} \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")
    console.print(f"    Style:    {style}")


# ---------------------------------------------------------------------------
# Repaint command (US-6.3)
# ---------------------------------------------------------------------------


_DEFAULT_CROSSFADE_MS = 50


def _repaint_via_elevenlabs(
    *,
    config,
    source: Clip,
    clip_id: int,
    start_ms: int,
    end_ms: int,
    source_duration: float,
    prompt: str,
    style: Optional[str],
    output: Optional[Path],
    name: Optional[str],
    start_label: str,
    end_label: str,
) -> None:
    """Repaint a clip section via ElevenLabs inpainting (upload → plan → compose).

    The source clip (any supported format, including ACE-Step WAVs) is uploaded
    to obtain a ``song_id``; a composition plan keeps [0, start] and
    [end, duration] via ``source_from`` and regenerates [start, end] from the
    prompt/style. ElevenLabs composes the full track server-side, so no local
    crossfade stitching is needed.
    """
    _require_elevenlabs_key(config)

    duration_ms_total = int(round(source_duration * 1000))
    keep_ranges = [(0, start_ms), (end_ms, duration_ms_total)]
    regenerate_range = (start_ms, end_ms)

    # Validate the plan shape before uploading — uploads are priced like a
    # generation, so range errors must fail before any credits are spent.
    try:
        build_inpaint_plan("pending-upload", keep_ranges, regenerate_range, prompt, style)
    except ElevenLabsError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
    try:
        with console.status("[bold green]Uploading source clip to ElevenLabs…[/bold green]", spinner="dots"):
            song_id = el_client.upload_for_inpainting(source.file_path)
        plan = build_inpaint_plan(song_id, keep_ranges, regenerate_range, prompt, style)
        with console.status("[bold green]Repainting via ElevenLabs…[/bold green]", spinner="dots"):
            data = el_client.generate_from_plan(plan, seed=source.seed)
    except ElevenLabsError as exc:
        console.print(f"[red]ElevenLabs error: {exc}[/red]")
        raise typer.Exit(code=1)

    ext = _elevenlabs_ext(config.elevenlabs_output_format)
    title_slug = make_slug(name or source.title or "clip")
    try:
        clips_dir = output if output is not None else get_workspace_path(source.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        dest_path = clips_dir / f"{title_slug}-repaint-{uuid.uuid4().hex[:8]}.{ext}"
        dest_path.write_bytes(data)
    except OSError as exc:
        console.print(f"[red]Error writing repainted clip: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"repaint clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif source.title:
        new_title = f"{source.title} (repaint)"
    else:
        new_title = None

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=source.lyrics,
        vocal_language=source.vocal_language,
        model="elevenlabs",
        seed=source.seed,
        parent_clip_id=source.id,
        generation_mode="repaint",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]✓[/green] Repainted clip {clip_id} ({start_label}–{end_label}) → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


@app.command()
def repaint(
    clip_id: int = typer.Argument(..., help="ID of the source clip to repaint."),
    start: str = typer.Option(..., "--start", help="Start of the region to regenerate (e.g. '10s', '1m30s')."),
    end: str = typer.Option(..., "--end", help="End of the region to regenerate (e.g. '20s', '2m')."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt describing what should fill the region."),
    style: Optional[str] = typer.Option(None, "--style", help="Optional style override for the regenerated section."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the repainted clip."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix for the repainted clip."),
    crossfade_ms: int = typer.Option(
        _DEFAULT_CROSSFADE_MS,
        "--crossfade-ms",
        help="Crossfade length at the splice boundaries (milliseconds). ACE-Step backend only.",
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto'/'ace-step' (ACE-Step repaint + local stitch) or 'elevenlabs' "
        "(cloud inpainting via composition plan; sections must be 3s–120s). "
        "Defaults to ACEMUSIC_BACKEND, then 'auto'.",
    ),
) -> None:
    """Regenerate a section of a clip while preserving the surrounding audio.

    Submits a ``task_type=repaint`` request to ACE-Step with the source clip as
    src_audio and the [start, end] region marked for regeneration. The model's
    output for that section is spliced into the original audio with a short
    crossfade at each boundary so transitions are inaudible. The result is
    saved as a new clip with ``parent_clip_id`` set to the source and
    ``generation_mode='repaint'``.

    Note: Requires ACE-Step to run on the same host (or with shared filesystem
    access), since the source audio is passed via an absolute server-side path.
    """
    try:
        start_ms = parse_time_string(start)
        end_ms = parse_time_string(end)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0

    if start_s >= end_s:
        console.print(f"[red]Error: --start ({start!r}) must be less than --end ({end!r}).[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if src_path.suffix.lower() not in SUPPORTED_FORMATS:
        console.print(
            f"[red]Error: source clip {clip_id} is not a supported audio file "
            f"({src_path.suffix or 'no extension'}). Repaint requires one of: "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
        )
        raise typer.Exit(code=1)

    source_duration = source.duration
    if source_duration is None or source_duration <= 0:
        try:
            source_duration = get_duration(src_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id}: {exc}[/red]")
            raise typer.Exit(code=1)
        if source_duration is None or source_duration <= 0:
            console.print(f"[red]Error: source clip {clip_id} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    if end_s > source_duration + 0.01:
        console.print(
            f"[red]Error: --end ({end!r}={end_s:.2f}s) exceeds source duration ({source_duration:.2f}s).[/red]"
        )
        raise typer.Exit(code=1)

    if crossfade_ms < 0:
        console.print(f"[red]Error: --crossfade-ms must be non-negative, got {crossfade_ms}.[/red]")
        raise typer.Exit(code=1)

    config, effective_backend = _resolve_backend_or_exit(backend)

    if effective_backend == "elevenlabs":
        if crossfade_ms != _DEFAULT_CROSSFADE_MS:
            console.print(
                "[yellow]Warning: --crossfade-ms is ignored with the elevenlabs backend "
                "(composition happens server-side).[/yellow]"
            )
        _repaint_via_elevenlabs(
            config=config,
            source=source,
            clip_id=clip_id,
            start_ms=int(start_ms),
            end_ms=int(end_ms),
            source_duration=source_duration,
            prompt=prompt,
            style=style,
            output=output,
            name=name,
            start_label=start,
            end_label=end,
        )
        return

    _require_ace_step_url(config)
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    clips_dir = output if output is not None else get_workspace_path(source.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ext = source.format or "wav"
    title_slug = make_slug(name or source.title or "clip")
    dest_name = f"{title_slug}-repaint-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    try:
        task_id = ace_client.submit_task(
            prompt=prompt,
            num_clips=1,
            audio_duration=source_duration,
            format=ext,
            style=style,
            bpm=source.bpm,
            key=source.key,
            seed=source.seed,
            task_type="repaint",
            src_audio_path=str(src_path.resolve()),
            repainting_start=start_s,
            repainting_end=end_s,
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting repaint task: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status("[bold green]Repainting\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(ace_client, task_id, status_bar, "Repainting", poll_timeout, poll_interval)

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
        raise typer.Exit(code=1)

    try:
        repaint_bytes = ace_client.download_audio(audio_urls[0])
    except AceStepError as exc:
        console.print(f"[red]Error downloading repainted clip: {exc}[/red]")
        raise typer.Exit(code=1)

    # Splice the regenerated section into the original with crossfade at the seams.
    # Passing format= explicitly so pydub uses Python's wave module for WAVs and
    # avoids invoking ffprobe (which is not always available, e.g. in CI runners).
    try:
        original = AudioSegment.from_file(str(src_path), format=ext)
        repaint_full = AudioSegment.from_file(io.BytesIO(repaint_bytes), format=ext)
    except Exception as exc:
        console.print(f"[red]Error decoding audio for stitching: {exc}[/red]")
        raise typer.Exit(code=1)

    if len(repaint_full) < end_ms - 10:
        console.print(
            f"[red]Error: ACE-Step output is {len(repaint_full)}ms but the repaint "
            f"window ends at {end_ms}ms — the model returned a truncated clip.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        before = original[: int(start_ms)]
        middle = repaint_full[int(start_ms) : int(end_ms)]
        after = original[int(end_ms) :]
        stitched = crossfade_stitch(before, middle, after, fade_ms=crossfade_ms)
        stitched.export(str(dest_path), format=ext)
    except Exception as exc:
        console.print(f"[red]Error stitching repainted section: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"repaint clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif source.title:
        new_title = f"{source.title} (repaint)"
    else:
        new_title = None

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=source.lyrics,
        vocal_language=source.vocal_language,
        model=source.model,
        seed=source.seed,
        inference_steps=source.inference_steps,
        parent_clip_id=source.id,
        generation_mode="repaint",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Repainted clip {clip_id} ({start}\u2013{end}) \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


# ---------------------------------------------------------------------------
# Add-vocal command (US-6.6)
# ---------------------------------------------------------------------------


@app.command("add-vocal")
def add_vocal(
    clip_id: int = typer.Argument(..., help="ID of the source instrumental clip."),
    lyrics: str = typer.Option(..., "--lyrics", help="Lyrics to layer onto the instrumental."),
    voice: str = typer.Option(
        "default",
        "--voice",
        help="Voice identifier (Stage 25 stub — value is currently accepted but not forwarded to the model).",
    ),
    style: Optional[str] = typer.Option(None, "--style", help="Optional vocal style (e.g. 'breathy, soulful')."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the resulting clip."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix for the resulting clip."),
) -> None:
    """Layer vocals onto an instrumental clip.

    Submits a ``task_type=complete`` request to ACE-Step with the source clip as
    src_audio. The model generates a vocal layered over the instrumental, and
    the result is saved as a new clip with ``parent_clip_id`` set to the source
    and ``generation_mode='add_vocal'``.

    Note: Requires ACE-Step to run on the same host (or with shared filesystem
    access), since the source audio is passed via an absolute server-side path.
    """
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if src_path.suffix.lower() not in SUPPORTED_FORMATS:
        console.print(
            f"[red]Error: source clip {clip_id} is not a supported audio file "
            f"({src_path.suffix or 'no extension'}). add-vocal requires one of: "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
        )
        raise typer.Exit(code=1)

    source_duration = source.duration
    if source_duration is None or source_duration <= 0:
        try:
            source_duration = get_duration(src_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id}: {exc}[/red]")
            raise typer.Exit(code=1)
        if source_duration is None or source_duration <= 0:
            console.print(f"[red]Error: source clip {clip_id} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    if voice != "default":
        console.print("[yellow]Voice selection available in Stage 25.[/yellow]")

    config = load_config()
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    clips_dir = output if output is not None else get_workspace_path(source.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ext = source.format or "wav"
    title_slug = make_slug(name or source.title or "clip")
    dest_name = f"{title_slug}-vocal-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    # Prompt describes the instrumental backdrop (so the model knows what it's
    # singing over); --style separately controls the vocal performance style.
    vocal_prompt = source.style_tags or source.title or "layer vocals over the instrumental"

    try:
        task_id = ace_client.submit_task(
            prompt=vocal_prompt,
            num_clips=1,
            audio_duration=source_duration,
            format=ext,
            style=style,
            lyrics=lyrics,
            vocal_language=source.vocal_language,
            bpm=source.bpm,
            key=source.key,
            seed=source.seed,
            task_type="complete",
            src_audio_path=str(src_path.resolve()),
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting add-vocal task: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status("[bold green]Adding vocal\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(ace_client, task_id, status_bar, "Adding vocal", poll_timeout, poll_interval)

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
        raise typer.Exit(code=1)

    try:
        data = ace_client.download_audio(audio_urls[0])
    except AceStepError as exc:
        console.print(f"[red]Error downloading add-vocal clip: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        dest_path.write_bytes(data)
    except OSError as exc:
        console.print(f"[red]Error writing add-vocal clip to {dest_path}: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"add-vocal clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif source.title:
        new_title = f"{source.title} (vocal)"
    else:
        new_title = None

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=lyrics,
        vocal_language=source.vocal_language,
        model=source.model,
        seed=source.seed,
        inference_steps=source.inference_steps,
        parent_clip_id=source.id,
        generation_mode="add_vocal",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Added vocal to clip {clip_id} \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


# ---------------------------------------------------------------------------
# Replace command (US-6.6)
# ---------------------------------------------------------------------------


@app.command()
def replace(
    clip_id: int = typer.Argument(..., help="ID of the source clip whose section will be replaced."),
    start: str = typer.Option(..., "--start", help="Start of the region to regenerate (e.g. '30s', '1m30s')."),
    end: str = typer.Option(..., "--end", help="End of the region to regenerate (e.g. '45s', '2m')."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt describing what should fill the region."),
    lock_context: bool = typer.Option(
        True,
        "--lock-context/--no-lock-context",
        help="Blend replacement with surrounding audio via crossfade stitch (default: on).",
    ),
    style: Optional[str] = typer.Option(None, "--style", help="Optional style override for the regenerated section."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the resulting clip."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix for the resulting clip."),
    crossfade_ms: int = typer.Option(
        50,
        "--crossfade-ms",
        help="Crossfade length at the splice boundaries (milliseconds). Only used with --lock-context.",
    ),
) -> None:
    """Regenerate a specific time range of a clip with new instructions.

    Submits a ``task_type=repaint`` request to ACE-Step with the source clip as
    src_audio and the [start, end] region marked for regeneration. With
    ``--lock-context`` (default on), the regenerated section is stitched back
    into the original with a short crossfade at each boundary so surrounding
    audio is preserved. With ``--no-lock-context``, the model's full output is
    saved directly without stitching. The result is saved as a new clip with
    ``parent_clip_id`` set to the source and ``generation_mode='replace'``.

    Note: Requires ACE-Step to run on the same host (or with shared filesystem
    access), since the source audio is passed via an absolute server-side path.
    """
    try:
        start_ms = parse_time_string(start)
        end_ms = parse_time_string(end)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0

    if start_s >= end_s:
        console.print(f"[red]Error: --start ({start!r}) must be less than --end ({end!r}).[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if src_path.suffix.lower() not in SUPPORTED_FORMATS:
        console.print(
            f"[red]Error: source clip {clip_id} is not a supported audio file "
            f"({src_path.suffix or 'no extension'}). replace requires one of: "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
        )
        raise typer.Exit(code=1)

    source_duration = source.duration
    if source_duration is None or source_duration <= 0:
        try:
            source_duration = get_duration(src_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id}: {exc}[/red]")
            raise typer.Exit(code=1)
        if source_duration is None or source_duration <= 0:
            console.print(f"[red]Error: source clip {clip_id} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    if end_s > source_duration + 0.01:
        console.print(
            f"[red]Error: --end ({end!r}={end_s:.2f}s) exceeds source duration ({source_duration:.2f}s).[/red]"
        )
        raise typer.Exit(code=1)

    if crossfade_ms < 0:
        console.print(f"[red]Error: --crossfade-ms must be non-negative, got {crossfade_ms}.[/red]")
        raise typer.Exit(code=1)

    config = load_config()
    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    clips_dir = output if output is not None else get_workspace_path(source.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ext = source.format or "wav"
    title_slug = make_slug(name or source.title or "clip")
    dest_name = f"{title_slug}-replace-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    try:
        task_id = ace_client.submit_task(
            prompt=prompt,
            num_clips=1,
            audio_duration=source_duration,
            format=ext,
            style=style,
            bpm=source.bpm,
            key=source.key,
            seed=source.seed,
            task_type="repaint",
            src_audio_path=str(src_path.resolve()),
            repainting_start=start_s,
            repainting_end=end_s,
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting replace task: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status("[bold green]Replacing section\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(ace_client, task_id, status_bar, "Replacing section", poll_timeout, poll_interval)

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
        raise typer.Exit(code=1)

    try:
        replace_bytes = ace_client.download_audio(audio_urls[0])
    except AceStepError as exc:
        console.print(f"[red]Error downloading replaced clip: {exc}[/red]")
        raise typer.Exit(code=1)

    if lock_context:
        try:
            original = AudioSegment.from_file(str(src_path), format=ext)
            replace_full = AudioSegment.from_file(io.BytesIO(replace_bytes), format=ext)
        except Exception as exc:
            console.print(f"[red]Error decoding audio for stitching: {exc}[/red]")
            raise typer.Exit(code=1)

        # Use a 1ms tolerance for both checks so the pre-slice and post-slice
        # guards agree \u2014 anything that passes the first check produces a
        # `middle` that won't trip the second.
        if len(replace_full) < end_ms - 1:
            console.print(
                f"[red]Error: ACE-Step output is {len(replace_full)}ms but the replace "
                f"window ends at {end_ms}ms \u2014 the model returned a truncated clip.[/red]"
            )
            raise typer.Exit(code=1)

        try:
            before = original[: int(start_ms)]
            middle = replace_full[int(start_ms) : int(end_ms)]
            after = original[int(end_ms) :]
        except Exception as exc:
            console.print(f"[red]Error slicing audio for stitching: {exc}[/red]")
            raise typer.Exit(code=1)

        expected_middle_ms = end_ms - start_ms
        if len(middle) < expected_middle_ms - 1:
            console.print(
                f"[red]Error: replacement section is {len(middle)}ms but the window "
                f"expects {expected_middle_ms}ms \u2014 model output was shorter than the window.[/red]"
            )
            raise typer.Exit(code=1)

        try:
            stitched = crossfade_stitch(before, middle, after, fade_ms=crossfade_ms)
            stitched.export(str(dest_path), format=ext)
        except Exception as exc:
            console.print(f"[red]Error stitching replaced section: {exc}[/red]")
            raise typer.Exit(code=1)
    else:
        try:
            dest_path.write_bytes(replace_bytes)
        except OSError as exc:
            console.print(f"[red]Error writing replaced clip to {dest_path}: {exc}[/red]")
            raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"replace clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif source.title:
        new_title = f"{source.title} (replace)"
    else:
        new_title = None

    new_clip = Clip(
        workspace_id=source.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=style or source.style_tags,
        lyrics=source.lyrics,
        vocal_language=source.vocal_language,
        model=source.model,
        seed=source.seed,
        inference_steps=source.inference_steps,
        parent_clip_id=source.id,
        generation_mode="replace",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Replaced clip {clip_id} ({start}\u2013{end}) \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


# ---------------------------------------------------------------------------
# Mashup command (US-6.4)
# ---------------------------------------------------------------------------


def _align_clips_bpm(
    primary_path: Path,
    primary_bpm: int | None,
    secondary_path: Path,
    secondary_bpm: int | None,
    workdir: Path,
) -> Path:
    """Time-stretch ``secondary_path`` to match ``primary_path``'s BPM.

    Returns the path to use for the secondary clip when submitting the mashup.
    When both BPMs are known and differ, writes a stretched copy into ``workdir``
    and returns that path. Otherwise returns ``secondary_path`` unchanged.
    Callers are responsible for unlinking the returned path when it differs from
    ``secondary_path``.
    """
    if primary_bpm is None or secondary_bpm is None:
        console.print("[yellow]\u2139 BPM alignment skipped (one or both BPMs unknown).[/yellow]")
        return secondary_path
    if primary_bpm <= 0 or secondary_bpm <= 0:
        console.print(f"[yellow]\u2139 BPM alignment skipped (invalid BPM: {primary_bpm}, {secondary_bpm}).[/yellow]")
        return secondary_path
    if primary_bpm == secondary_bpm:
        return secondary_path

    rate = calculate_speed_multiplier(original_bpm=float(secondary_bpm), target_bpm=float(primary_bpm))
    aligned_path = workdir / f"aligned-{uuid.uuid4().hex[:8]}{secondary_path.suffix}"
    try:
        time_stretch_audio(str(secondary_path), str(aligned_path), rate)
    except Exception as exc:
        console.print(f"[yellow]ℹ BPM alignment failed, using original clip: {exc}[/yellow]")
        aligned_path.unlink(missing_ok=True)
        return secondary_path

    console.print(f"[cyan]\u2139 Aligned clip BPM {secondary_bpm} \u2192 {primary_bpm} (rate {rate:.3f}).[/cyan]")
    return aligned_path


def _mashup_via_elevenlabs(
    *,
    config,
    sources: list[Clip],
    style: Optional[str],
    output: Optional[Path],
    name: Optional[str],
) -> None:
    """Mash up clips via ElevenLabs composition plans (upload each → combine).

    Every source clip is uploaded to obtain a ``song_id``; a composition plan
    then references each source's full range via ``source_from`` in CLI order
    and ElevenLabs composes one combined track. Unlike ACE-Step's audio-level
    blend, recombination happens at the section/composition level, so
    ``--blend`` strategies do not apply.
    """
    _require_elevenlabs_key(config)

    durations_ms: list[int] = []
    for clip in sources:
        duration = clip.duration
        if duration is None or duration <= 0:
            try:
                duration = get_duration(Path(clip.file_path))
            except Exception as exc:
                console.print(f"[red]Error: unable to determine duration for clip {clip.id}: {exc}[/red]")
                raise typer.Exit(code=1)
            if duration is None or duration <= 0:
                console.print(f"[red]Error: clip {clip.id} has no valid duration metadata.[/red]")
                raise typer.Exit(code=1)
        durations_ms.append(int(round(duration * 1000)))

    # Validate the plan shape before uploading — every upload is priced like a
    # generation, so size errors must fail before the first credit is spent.
    # Sentinel ids name the actual clips so validation errors stay actionable.
    sentinel_sources = [(f"clip {clip.id}", duration_ms) for clip, duration_ms in zip(sources, durations_ms)]
    try:
        build_mashup_plan(sentinel_sources, style)
    except ElevenLabsError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
    song_sources: list[tuple[str, int]] = []
    for clip, duration_ms in zip(sources, durations_ms):
        try:
            with console.status(f"[bold green]Uploading clip {clip.id} to ElevenLabs…[/bold green]", spinner="dots"):
                song_id = el_client.upload_for_inpainting(clip.file_path)
        except ElevenLabsError as exc:
            console.print(f"[red]Error uploading clip {clip.id}: {exc}[/red]")
            if song_sources:
                # ElevenLabs has no upload-delete API; set cost expectations.
                console.print(
                    f"[yellow]Note: {len(song_sources)} earlier upload(s) succeeded and may "
                    "already have been billed (uploads are priced like a generation).[/yellow]"
                )
            raise typer.Exit(code=1)
        song_sources.append((song_id, duration_ms))

    try:
        plan = build_mashup_plan(song_sources, style)
        with console.status("[bold green]Composing mashup via ElevenLabs…[/bold green]", spinner="dots"):
            data = el_client.generate_from_plan(plan)
    except ElevenLabsError as exc:
        console.print(f"[red]ElevenLabs error: {exc}[/red]")
        console.print(
            f"[yellow]Note: {len(song_sources)} upload(s) succeeded and may already have "
            "been billed (uploads are priced like a generation).[/yellow]"
        )
        raise typer.Exit(code=1)

    primary = sources[0]
    ext = _elevenlabs_ext(config.elevenlabs_output_format)
    titles = [clip.title for clip in sources if clip.title]
    default_title = f"{' + '.join(titles)} (mashup)" if titles else None
    title_slug = make_slug(name or (f"{'-'.join(titles)}-mashup" if titles else "mashup"))
    try:
        clips_dir = output if output is not None else get_workspace_path(primary.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        dest_path = clips_dir / f"{title_slug}-{uuid.uuid4().hex[:8]}.{ext}"
        dest_path.write_bytes(data)
    except OSError as exc:
        console.print(f"[red]Error writing mashup clip: {exc}[/red]")
        raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"mashup clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    new_clip = Clip(
        workspace_id=primary.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=name or default_title,
        format=ext,
        duration=new_duration,
        style_tags=_merge_style_tags(*(clip.style_tags for clip in sources), style),
        model="elevenlabs",
        parent_clip_id=primary.id,
        parent_clip_ids=json.dumps([clip.id for clip in sources]),
        generation_mode="mashup",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    ids_str = " + ".join(str(clip.id) for clip in sources)
    console.print(f"  [green]✓[/green] Mashed up clips {ids_str} → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")


def _merge_style_tags(*sources: Optional[str]) -> Optional[str]:
    """Merge comma-separated style tags from several sources, deduplicated case-insensitively."""
    seen: set[str] = set()
    merged: list[str] = []
    for source in sources:
        if not source:
            continue
        for tag in (t.strip() for t in source.split(",")):
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                merged.append(tag)
    return ", ".join(merged) or None


@app.command()
def mashup(
    clip_ids: list[int] = typer.Argument(
        ...,
        help="IDs of the source clips to combine (two or more; the ACE-Step backend supports exactly two).",
    ),
    blend: str = typer.Option(
        "layered",
        "--blend",
        help="Blend strategy: 'layered' (concurrent), 'sequential' (section-by-section), or 'ai-guided'. "
        "ACE-Step backend only.",
    ),
    style: Optional[str] = typer.Option(
        None, "--style", help="Optional unifying style descriptor (e.g. 'lo-fi hip hop')."
    ),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the mashup file."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix and title for the mashup."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto'/'ace-step' (audio-level blend of exactly two clips) or 'elevenlabs' "
        "(section-level composition of two or more uploaded clips; sections 3s–120s, total ≤600s). "
        "Defaults to ACEMUSIC_BACKEND, then 'auto'.",
    ),
) -> None:
    """Combine elements from multiple clips into a single hybrid clip.

    With the ACE-Step backend (default), submits a ``task_type=mashup`` request
    with exactly two source clips and a blend strategy; differing BPMs are
    aligned by time-stretching the secondary clip (US-5.2). With the
    ElevenLabs backend, two or more source clips are uploaded and recombined
    at the section/composition level — ``--blend`` does not apply there.

    The result is saved as a new clip with ``parent_clip_ids`` recording all
    sources (and ``parent_clip_id`` the first) and ``generation_mode='mashup'``.

    Note: The ACE-Step backend requires ACE-Step on the same host (or shared
    filesystem), since source audio is passed via absolute server-side paths.
    """
    if blend not in VALID_BLEND_MODES:
        console.print(f"[red]Error: --blend must be one of {sorted(VALID_BLEND_MODES)}, got {blend!r}.[/red]")
        raise typer.Exit(code=1)

    if len(clip_ids) < 2:
        console.print("[red]Error: mashup needs at least two clip IDs.[/red]")
        raise typer.Exit(code=1)

    if len(set(clip_ids)) != len(clip_ids):
        console.print("[red]Error: clip IDs must be different clips.[/red]")
        raise typer.Exit(code=1)

    clips: list[Clip] = []
    for clip_id in clip_ids:
        clip = get_clip(clip_id)
        if clip is None:
            console.print(f"[red]Error: clip {clip_id} not found.[/red]")
            raise typer.Exit(code=1)
        clips.append(clip)

    for clip in clips:
        path = Path(clip.file_path)
        if not path.exists():
            console.print(f"[red]Error: source file not found: {path}[/red]")
            raise typer.Exit(code=1)
        if path.suffix.lower() not in SUPPORTED_FORMATS:
            console.print(
                f"[red]Error: clip {clip.id} is not a supported audio file "
                f"({path.suffix or 'no extension'}). Mashup requires one of: "
                f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
            )
            raise typer.Exit(code=1)

    config, effective_backend = _resolve_backend_or_exit(backend, capability="mashup")

    # auto prefers ACE-Step, but 3+ sources are an ElevenLabs-only capability —
    # auto never fails just because one engine can't do a job another can.
    if effective_backend == "auto" and len(clips) > 2:
        if config.elevenlabs_api_key:
            console.print("[cyan]Using the elevenlabs backend (ACE-Step mashup supports exactly two clips).[/cyan]")
            effective_backend = "elevenlabs"
        else:
            console.print(
                "[red]Error: the ACE-Step backend supports exactly two clips. "
                "Set ELEVENLABS_API_KEY (or pass --backend elevenlabs) to combine more sources.[/red]"
            )
            raise typer.Exit(code=1)

    if effective_backend == "elevenlabs":
        if blend != "layered":
            console.print(
                "[yellow]Warning: --blend is ignored with the elevenlabs backend "
                "(sources are recombined at the section/composition level).[/yellow]"
            )
        _mashup_via_elevenlabs(config=config, sources=clips, style=style, output=output, name=name)
        return

    if len(clips) != 2:
        console.print(
            "[red]Error: the ACE-Step backend supports exactly two clips. "
            "Use --backend elevenlabs to combine more sources.[/red]"
        )
        raise typer.Exit(code=1)

    _require_ace_step_url(config)
    primary, secondary = clips
    clip_id_1, clip_id_2 = clip_ids
    primary_path = Path(primary.file_path)
    secondary_path = Path(secondary.file_path)

    duration = primary.duration
    if duration is None or duration <= 0:
        try:
            duration = get_duration(primary_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id_1}: {exc}[/red]")
            raise typer.Exit(code=1)
        if duration is None or duration <= 0:
            console.print(f"[red]Error: clip {clip_id_1} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    clips_dir = output if output is not None else get_workspace_path(primary.workspace_id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ext = primary.format or "wav"
    title_slug = make_slug(name or f"{primary.title or 'clip'}-{secondary.title or 'clip'}-mashup")
    dest_name = f"{title_slug}-{uuid.uuid4().hex[:8]}.{ext}"
    dest_path = clips_dir / dest_name

    with tempfile.TemporaryDirectory(prefix="acemusic-mashup-") as align_dir:
        aligned_secondary = _align_clips_bpm(
            primary_path=primary_path,
            primary_bpm=primary.bpm,
            secondary_path=secondary_path,
            secondary_bpm=secondary.bpm,
            workdir=Path(align_dir),
        )

        # Key alignment is out of scope for this story (would require pitch-shifting
        # the secondary clip). When the two clips have known but different keys, warn
        # the user and submit without a key constraint so we don't falsely claim the
        # primary's key applies to the blended output.
        submitted_key = primary.key
        if primary.key and secondary.key and primary.key != secondary.key:
            console.print(
                f"[yellow]ℹ Key mismatch: {primary.key} vs {secondary.key}. "
                f"Submitting without a key constraint — output may sound dissonant.[/yellow]"
            )
            submitted_key = None

        prompt_parts = [part for part in (primary.title, secondary.title) if part]
        prompt_text = style or (f"mashup of {' and '.join(prompt_parts)}" if prompt_parts else "mashup")
        try:
            task_id = ace_client.submit_task(
                prompt=prompt_text,
                num_clips=1,
                audio_duration=duration,
                format=ext,
                style=style,
                bpm=primary.bpm,
                key=submitted_key,
                task_type="mashup",
                src_audio_path=str(primary_path.resolve()),
                ref_audio_path=str(aligned_secondary.resolve()),
                blend_mode=blend,
            )
        except AceStepError as exc:
            console.print(f"[red]Error submitting mashup task: {exc}[/red]")
            raise typer.Exit(code=1)

        console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

        poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
        poll_interval = 2.0
        with console.status("[bold green]Mashing up\u2026[/bold green]", spinner="dots") as status_bar:
            result = _poll_until_complete(ace_client, task_id, status_bar, "Mashing up", poll_timeout, poll_interval)

        audio_urls: list[str] = result.get("audio_urls", [])
        if not audio_urls:
            console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
            raise typer.Exit(code=1)

        try:
            data = ace_client.download_audio(audio_urls[0])
        except AceStepError as exc:
            console.print(f"[red]Error downloading mashup clip: {exc}[/red]")
            raise typer.Exit(code=1)

        try:
            dest_path.write_bytes(data)
        except OSError as exc:
            console.print(f"[red]Error writing mashup clip to {dest_path}: {exc}[/red]")
            raise typer.Exit(code=1)

    try:
        new_duration = get_duration(dest_path)
    except Exception as exc:
        warnings.warn(f"mashup clip duration probe failed: {exc}", stacklevel=2)
        new_duration = None

    if name:
        new_title = name
    elif primary.title and secondary.title:
        new_title = f"{primary.title} + {secondary.title} (mashup)"
    elif primary.title or secondary.title:
        new_title = f"{primary.title or secondary.title} (mashup)"
    else:
        new_title = None

    new_clip = Clip(
        workspace_id=primary.workspace_id,
        file_path=str(dest_path.resolve()),
        created_at=datetime.now(timezone.utc).isoformat(),
        title=new_title,
        format=ext,
        duration=new_duration,
        bpm=primary.bpm,
        key=submitted_key,
        style_tags=_merge_style_tags(primary.style_tags, secondary.style_tags, style),
        parent_clip_id=primary.id,
        parent_clip_ids=json.dumps([primary.id, secondary.id]),
        generation_mode="mashup",
    )
    try:
        new_id = create_clip(new_clip)
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        console.print(f"[red]Error saving clip record: {exc}[/red]")
        raise typer.Exit(code=1)

    dur_str = f"{new_duration:.1f}s" if new_duration is not None else "unknown"
    console.print(f"  [green]\u2713[/green] Mashed up clips {clip_id_1} + {clip_id_2} \u2192 clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {dur_str}")
    console.print(f"    Blend:    {blend}")


# ---------------------------------------------------------------------------
# Sample command (US-6.5)
# ---------------------------------------------------------------------------


_ROLE_PROMPT_PREFIX: dict[str, str] = {
    "loop-bed": "Create a track that works as an overlay on top of a repeating loop.",
    "intro-outro": "Create a track that transitions smoothly from and back to a musical phrase.",
    "rhythmic-element": "Create a track with space for a recurring rhythmic sample.",
    "melodic-hook": "Create a track that follows and develops from a melodic hook.",
}

# Guard against drift between the prompt prefixes and the canonical role set.
assert set(_ROLE_PROMPT_PREFIX) == SAMPLE_ROLES, "Sample roles in cli.py and audio.py must stay in sync."


def _build_sample_prompt(base_prompt: str, role: str, sample_duration_sec: float) -> str:
    """Prepend role-specific instructions and sample duration context to the prompt."""
    prefix = _ROLE_PROMPT_PREFIX.get(role, "")
    duration_hint = f"The reference sample is about {sample_duration_sec:.1f}s long."
    return f"{prefix} {duration_hint} {base_prompt}".strip()


@app.command()
def sample(
    clip_id: int = typer.Argument(..., help="ID of the source clip to sample from."),
    start: str = typer.Option(..., "--start", help="Sample start time (e.g. '4s', '0.5s', '1m30s')."),
    end: str = typer.Option(..., "--end", help="Sample end time (e.g. '8s')."),
    role: str = typer.Option(
        ...,
        "--role",
        help=f"Sample role: one of {', '.join(sorted(SAMPLE_ROLES))}.",
    ),
    prompt: str = typer.Option(..., "--prompt", help="Text prompt describing the new song to generate."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save the sampled clip."),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        help="Engine: 'auto'/'ace-step' (ACE-Step) or 'elevenlabs'. Defaults to ACEMUSIC_BACKEND, then 'auto'. "
        "(Automatic ElevenLabs fallback currently applies to `generate`, not `sample`.)",
    ),
    num_clips: int = typer.Option(1, "--num-clips", help="Number of variations to generate."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix and title for the new clip."),
) -> None:
    """Extract a sample from an existing clip and build a new song around it.

    The selected time range is extracted from the source clip and combined with
    text-generated audio according to ``--role``. The sample is physically
    present in the output so it is always audible. An attribution sidecar
    (``{filename}.meta.json``) records the source clip, time range, role, and
    prompt for later tooling.
    """
    if role not in SAMPLE_ROLES:
        console.print(f"[red]Error: --role must be one of {sorted(SAMPLE_ROLES)}, got {role!r}.[/red]")
        raise typer.Exit(code=1)

    if num_clips < 1:
        console.print(f"[red]Error: --num-clips must be >= 1, got {num_clips}.[/red]")
        raise typer.Exit(code=1)

    try:
        start_ms = parse_time_string(start)
        end_ms = parse_time_string(end)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    src_path = Path(source.file_path)
    if not src_path.exists():
        console.print(f"[red]Error: source file not found: {src_path}[/red]")
        raise typer.Exit(code=1)

    if src_path.suffix.lower() not in SUPPORTED_FORMATS:
        console.print(
            f"[red]Error: source clip {clip_id} is not an audio file "
            f"({src_path.suffix or 'no extension'}). Sample requires one of: "
            f"{', '.join(sorted(SUPPORTED_FORMATS))}.[/red]"
        )
        raise typer.Exit(code=1)

    source_duration = source.duration
    if source_duration is None or source_duration <= 0:
        try:
            source_duration = get_duration(src_path)
        except Exception as exc:
            console.print(f"[red]Error: unable to determine source duration for clip {clip_id}: {exc}[/red]")
            raise typer.Exit(code=1)
        if source_duration is None or source_duration <= 0:
            console.print(f"[red]Error: clip {clip_id} has no valid duration metadata.[/red]")
            raise typer.Exit(code=1)

    duration_ms = int(source_duration * 1000)
    # parse_time_string already rejects negatives, so we only check ordering and upper bound here.
    if end_ms <= start_ms or end_ms > duration_ms:
        console.print(
            f"[red]Error: invalid time range [{start_ms}, {end_ms}] ms \u2014 "
            f"must satisfy start < end <= {duration_ms} ms (source duration).[/red]"
        )
        raise typer.Exit(code=1)

    sample_duration_sec = (end_ms - start_ms) / 1000.0

    if output is not None:
        out_dir = output
    else:
        out_dir = get_workspace_path(source.workspace_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = source.format or "wav"
    config, effective_backend = _resolve_backend_or_exit(backend)
    title_slug = make_slug(name or source.title or "clip")
    enhanced_prompt = _build_sample_prompt(prompt, role, sample_duration_sec)

    with tempfile.TemporaryDirectory(prefix="acemusic-sample-") as workdir:
        workdir_path = Path(workdir)

        sample_path = workdir_path / f"sample.{ext}"
        try:
            crop_audio(
                input_path=str(src_path),
                output_path=str(sample_path),
                start_ms=start_ms,
                end_ms=end_ms,
            )
        except Exception as exc:
            console.print(f"[red]Error extracting sample range: {exc}[/red]")
            raise typer.Exit(code=1)

        if effective_backend in ("auto", "ace-step"):
            engine_used = "ace-step"
            _require_ace_step_url(config)
            ace_client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
            generated_paths = _generate_sample_via_ace_step(
                ace_client=ace_client,
                prompt=enhanced_prompt,
                num_clips=num_clips,
                workdir=workdir_path,
                ext=ext,
            )
        else:
            engine_used = "elevenlabs"
            _require_elevenlabs_key(config)
            el_client = ElevenLabsClient(
                api_key=config.elevenlabs_api_key,
                output_format=config.elevenlabs_output_format,
            )
            generated_paths = _generate_sample_via_elevenlabs(
                el_client=el_client,
                prompt=enhanced_prompt,
                num_clips=num_clips,
                workdir=workdir_path,
                output_format=config.elevenlabs_output_format,
            )

        created_ids: list[tuple[int, Path]] = []
        for idx, generated_path in enumerate(generated_paths, start=1):
            suffix = f"-{idx}" if num_clips > 1 else ""
            dest_name = f"{title_slug}-sample-{uuid.uuid4().hex[:8]}{suffix}.{ext}"
            dest_path = out_dir / dest_name

            try:
                combine_sample(
                    sample_path=sample_path,
                    generated_path=generated_path,
                    output_path=dest_path,
                    role=role,
                )
            except Exception as exc:
                dest_path.unlink(missing_ok=True)
                console.print(f"[red]Error combining sample with generated audio: {exc}[/red]")
                raise typer.Exit(code=1)

            sidecar_path: Path | None = None
            try:
                sidecar_path = write_sample_metadata(
                    dest_path,
                    source_clip_id=source.id,
                    source_file=str(src_path),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    role=role,
                    prompt=prompt,
                    backend=engine_used,
                )
            except Exception as exc:
                # Provenance is an acceptance criterion: refuse to ship a sample
                # output without its attribution sidecar.
                dest_path.unlink(missing_ok=True)
                console.print(f"[red]Error writing sample metadata sidecar: {exc}[/red]")
                raise typer.Exit(code=1)

            try:
                new_duration = get_duration(dest_path)
            except Exception as exc:
                warnings.warn(f"sampled clip duration probe failed: {exc}", stacklevel=2)
                new_duration = None

            if name:
                new_title = name if num_clips == 1 else f"{name}-{idx}"
            elif source.title:
                new_title = f"{source.title} (sample, {role})"
            else:
                new_title = None

            new_clip = Clip(
                workspace_id=source.workspace_id,
                file_path=str(dest_path.resolve()),
                created_at=datetime.now(timezone.utc).isoformat(),
                title=new_title,
                format=ext,
                duration=new_duration,
                bpm=source.bpm,
                key=source.key,
                style_tags=source.style_tags,
                parent_clip_id=source.id,
                generation_mode="sample",
            )
            try:
                new_id = create_clip(new_clip)
            except Exception as exc:
                dest_path.unlink(missing_ok=True)
                if sidecar_path is not None:
                    sidecar_path.unlink(missing_ok=True)
                console.print(f"[red]Error saving clip record: {exc}[/red]")
                raise typer.Exit(code=1)

            created_ids.append((new_id, dest_path))

    for new_id, dest_path in created_ids:
        console.print(f"  [green]\u2713[/green] Sampled clip {clip_id} \u2192 clip {new_id}")
        console.print(f"    Path:     {dest_path}")
        console.print(f"    Role:     {role}")
        console.print(f"    Range:    {start_ms}\u2013{end_ms} ms")


def _generate_sample_via_ace_step(
    *,
    ace_client: AceStepClient,
    prompt: str,
    num_clips: int,
    workdir: Path,
    ext: str,
) -> list[Path]:
    """Submit a single ACE-Step task and download up to ``num_clips`` audio files to ``workdir``."""
    try:
        task_id = ace_client.submit_task(
            prompt=prompt,
            num_clips=num_clips,
            format=ext,
        )
    except AceStepError as exc:
        console.print(f"[red]Error submitting generation task: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0
    with console.status("[bold green]Generating sample track\u2026[/bold green]", spinner="dots") as status_bar:
        result = _poll_until_complete(
            ace_client, task_id, status_bar, "Generating sample track", poll_timeout, poll_interval
        )

    audio_urls: list[str] = result.get("audio_urls", [])
    if not audio_urls:
        console.print("[red]Error: ACE-Step returned no audio URLs.[/red]")
        raise typer.Exit(code=1)
    if len(audio_urls) < num_clips:
        console.print(f"[red]Error: requested {num_clips} clip(s) but ACE-Step returned {len(audio_urls)}.[/red]")
        raise typer.Exit(code=1)

    generated_paths: list[Path] = []
    for i, url in enumerate(audio_urls[:num_clips], start=1):
        try:
            data = ace_client.download_audio(url)
        except AceStepError as exc:
            console.print(f"[red]Download failed for clip {i}: {exc}[/red]")
            raise typer.Exit(code=1)
        gen_path = workdir / f"generated-{i}.{ext}"
        gen_path.write_bytes(data)
        generated_paths.append(gen_path)
    return generated_paths


def _generate_sample_via_elevenlabs(
    *,
    el_client: ElevenLabsClient,
    prompt: str,
    num_clips: int,
    workdir: Path,
    output_format: str,
) -> list[Path]:
    """Generate ``num_clips`` audio files sequentially via ElevenLabs to ``workdir``."""
    ext = _elevenlabs_ext(output_format)
    generated_paths: list[Path] = []
    for i in range(1, num_clips + 1):
        with console.status(f"[bold green]Sample track {i}/{num_clips}\u2026[/bold green]", spinner="dots"):
            try:
                data = el_client.generate(prompt=prompt)
            except ElevenLabsError as exc:
                console.print(f"[red]ElevenLabs error: {exc}[/red]")
                raise typer.Exit(code=1)
        gen_path = workdir / f"generated-{i}.{ext}"
        gen_path.write_bytes(data)
        generated_paths.append(gen_path)
    return generated_paths


# ---------------------------------------------------------------------------
# Preset commands (US-4.3)
# ---------------------------------------------------------------------------


@presets_app.command("save")
def preset_save(
    name: str = typer.Argument(..., help="Name of the preset to save."),
    from_last: bool = typer.Option(False, "--from-last", help="Save parameters from the last generation."),
    style: Optional[str] = typer.Option(None, "--style", help="Comma-separated style descriptors."),
    lyrics: Optional[str] = typer.Option(None, "--lyrics", help="Lyrics text."),
    bpm: Optional[str] = typer.Option(None, "--bpm", help="Tempo in BPM."),
    key: Optional[str] = typer.Option(None, "--key", help="Tonal center."),
    duration: Optional[int] = typer.Option(None, "--duration", help="Duration in seconds."),
    model: Optional[str] = typer.Option(None, "--model", help="AI model variant."),
    seed: Optional[int] = typer.Option(None, "--seed", help="Fixed seed for reproducibility."),
    inference_steps: Optional[int] = typer.Option(None, "--inference-steps", help="Number of diffusion steps."),
    vocal_language: Optional[str] = typer.Option(None, "--vocal-language", help="ISO 639-1 vocal language code."),
    instrumental: bool = typer.Option(False, "--instrumental", help="Suppress vocals."),
    quality: Optional[str] = typer.Option(None, "--quality", help="Quality preset (turbo/standard/high)."),
    weirdness: Optional[int] = typer.Option(None, "--weirdness", help="Deviation from conventional (0-100)."),
    style_influence: Optional[int] = typer.Option(None, "--style-influence", help="Adherence to style (0-100)."),
    exclude_style: Optional[str] = typer.Option(None, "--exclude-style", help="Styles to exclude."),
    time_signature: Optional[str] = typer.Option(None, "--time-signature", help="Meter (4/4, 3/4, etc.)."),
) -> None:
    """Save a generation preset with parameters."""
    try:
        ws = _get_active_ws()

        if from_last:
            console.print("[red]Error: --from-last not yet implemented (requires tracking last generation).[/red]")
            raise typer.Exit(code=1)

        # Parse BPM
        parsed_bpm = None
        if bpm is not None:
            try:
                parsed_bpm = _parse_bpm(bpm)
                if isinstance(parsed_bpm, str):
                    parsed_bpm = None  # 'auto' is not stored in preset
            except typer.BadParameter:
                console.print(f"[red]Invalid --bpm: {bpm}[/red]")
                raise typer.Exit(code=1)

        # Create preset
        now = datetime.now(timezone.utc).isoformat()
        preset = Preset(
            workspace_id=ws.id,
            name=name,
            style=style,
            lyrics=lyrics,
            bpm=int(parsed_bpm) if isinstance(parsed_bpm, int) else None,
            key=key,
            duration=duration,
            model=model,
            seed=seed,
            inference_steps=inference_steps,
            vocal_language=vocal_language,
            instrumental=1 if instrumental else None,
            quality=quality,
            weirdness=float(weirdness) if weirdness is not None else None,
            style_influence=float(style_influence) if style_influence is not None else None,
            exclude_style=exclude_style,
            time_signature=time_signature,
            created_at=now,
        )

        create_preset(preset)
        console.print(f"[green]✓ Preset '{name}' saved successfully.[/green]")

    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    except sqlite3.IntegrityError:
        console.print(f"[red]Error: Preset '{name}' already exists in this workspace.[/red]")
        raise typer.Exit(code=1)
    except sqlite3.Error as exc:
        console.print(f"[red]Database error: {exc}[/red]")
        raise typer.Exit(code=1)


@presets_app.command("list")
def preset_list() -> None:
    """List all presets in the active workspace."""
    try:
        ws = _get_active_ws()
        presets = list_presets(ws.id)

        if not presets:
            console.print("No presets found in this workspace.")
            return

        table = Table(title="Presets", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Style")
        table.add_column("BPM", justify="right")
        table.add_column("Key")
        table.add_column("Model")
        table.add_column("Created", justify="right")

        for p in presets:
            table.add_row(
                p.name,
                p.style or "-",
                str(p.bpm) if p.bpm else "-",
                p.key or "-",
                p.model or "-",
                (p.created_at or "")[:10],
            )
        console.print(table)

    except (ValueError, sqlite3.Error) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@presets_app.command("load")
def preset_load(name: str = typer.Argument(..., help="Name of the preset to load.")) -> None:
    """Display parameters of a saved preset."""
    try:
        ws = _get_active_ws()
        preset = get_preset(ws.id, name)

        if not preset:
            console.print(f"[red]Error: Preset '{name}' not found.[/red]")
            raise typer.Exit(code=1)

        console.print(f"\n[bold]Preset: {preset.name}[/bold]")
        console.print(f"Created: {preset.created_at}")
        console.print("")

        params = [
            ("Style", preset.style),
            ("Lyrics", f"{len(preset.lyrics)} chars" if preset.lyrics else None),
            ("BPM", preset.bpm),
            ("Key", preset.key),
            ("Duration", f"{preset.duration}s" if preset.duration else None),
            ("Model", preset.model),
            ("Seed", preset.seed),
            ("Inference Steps", preset.inference_steps),
            ("Vocal Language", preset.vocal_language),
            ("Instrumental", "Yes" if preset.instrumental else None),
            ("Quality", preset.quality),
            ("Weirdness", f"{preset.weirdness}%" if preset.weirdness else None),
            ("Style Influence", f"{preset.style_influence}%" if preset.style_influence else None),
            ("Exclude Style", preset.exclude_style),
            ("Time Signature", preset.time_signature),
        ]

        for key, value in params:
            if value is not None:
                console.print(f"  {key}: {value}")

        console.print("")

    except (ValueError, sqlite3.Error) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)


@presets_app.command("delete")
def preset_delete(name: str = typer.Argument(..., help="Name of the preset to delete.")) -> None:
    """Delete a preset."""
    try:
        ws = _get_active_ws()
        success = delete_preset(ws.id, name)

        if not success:
            console.print(f"[red]Error: Preset '{name}' not found.[/red]")
            raise typer.Exit(code=1)

        console.print(f"[green]✓ Preset '{name}' deleted.[/green]")

    except (ValueError, sqlite3.Error) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
