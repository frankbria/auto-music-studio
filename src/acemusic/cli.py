"""CLI entry point for acemusic (US-2.1, US-2.2, US-2.3, US-4.2, US-5.1, US-5.3, US-5.4)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from acemusic import __version__
from acemusic.audio import (
    SUPPORTED_FORMATS,
    calculate_speed_multiplier,
    crop_audio,
    detect_bpm,
    detect_key,
    time_stretch_audio,
)
from acemusic.client import AceStepClient, AceStepError
from acemusic.config import load_config
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
from acemusic.elevenlabs_client import ElevenLabsClient, ElevenLabsError
from acemusic.midi_client import MidiClient, MidiError
from acemusic.models import Clip, Preset
from acemusic.stems_client import StemsClient, StemsError
from acemusic.utils import get_duration, make_filename, make_slug, parse_time_string, snap_to_beat
from acemusic.workspace import (
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

# ACE-Step model registry (US-3.4).
# Keys map directly to the --model flag value and the API's model field.
# All fields are rendered in `acemusic models` output.
MODELS: dict[str, dict[str, str]] = {
    "turbo": {
        "description": "Fastest generation; best for quick drafts and iteration",
        "vram": "~2.4GB",
        "steps": "8",
        "dit_size": "2B",
    },
    "base": {
        "description": "Balanced quality/speed; general-purpose generation",
        "vram": "~2.4GB",
        "steps": "32-64",
        "dit_size": "2B",
    },
    "sft": {
        "description": "Fine-tuned on supervised data; improved coherence",
        "vram": "~2.4GB",
        "steps": "32-64",
        "dit_size": "2B",
    },
    "xl-base": {
        "description": "Highest quality; best for professional-grade output",
        "vram": "~8GB",
        "steps": "32-64",
        "dit_size": "4B",
    },
    "xl-sft": {
        "description": "XL fine-tuned; premium quality with improved coherence",
        "vram": "~8GB",
        "steps": "32-64",
        "dit_size": "4B",
    },
    "xl-turbo": {
        "description": "Fast XL generation; high quality with reduced steps",
        "vram": "~8GB",
        "steps": "8",
        "dit_size": "4B",
    },
}
VALID_MODELS: frozenset[str] = frozenset(MODELS.keys())


def _version_callback(value: bool) -> None:
    """Print version string and exit when --version flag is set."""
    if value:
        typer.echo(f"acemusic {__version__}")
        raise typer.Exit()


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
        "crop",
        "speed",
        "stems",
        "midi",
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

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="bold")
        table.add_column("Value")
        table.add_row("Server URL", config.api_url)
        table.add_row("Loaded models", models_str)
        table.add_row("Active jobs", str(active_jobs))
        table.add_row("Avg job time", avg_str)
        console.print(table)

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
        keyword in msg for keyword in ("connection refused", "connect", "timeout", "unreachable", "name or service")
    )


_VALID_TIME_SIGNATURES = {"4/4", "3/4", "6/8", "5/4", "7/8"}
_BPM_MIN = 60
_BPM_MAX = 180
_DURATION_MIN = 30.0
_DURATION_MAX = 240.0


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
    backend: str = typer.Option("ace-step", "--backend", help="AI backend: 'ace-step' (default) or 'elevenlabs'."),
    preset: Optional[str] = typer.Option(None, "--preset", help="Apply a saved preset (flags override preset values)."),
    style: Optional[str] = typer.Option(
        None, "--style", help="Comma-separated style descriptors (e.g. 'dark electro, punchy drums')."
    ),
    lyrics: Optional[str] = typer.Option(
        None, "--lyrics", help="Inline lyrics text (supports structure tags like [Verse])."
    ),
    lyrics_file: Optional[Path] = typer.Option(None, "--lyrics-file", help="Path to a text file containing lyrics."),
    vocal_language: Optional[str] = typer.Option(
        None, "--vocal-language", help="ISO 639-1 vocal language code (ACE-Step only, e.g. 'en', 'ja')."
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
    _VALID_FORMATS = {"wav", "flac", "mp3", "aac", "opus"}
    if format not in _VALID_FORMATS:
        console.print(f"[red]Invalid --format: {format!r}. Allowed values: {', '.join(sorted(_VALID_FORMATS))}[/red]")
        raise typer.Exit(code=1)

    if inference_steps is not None and inference_steps <= 0:
        console.print(
            f"[red]Invalid --inference-steps: {inference_steps}. --inference-steps must be a positive integer.[/red]"
        )
        raise typer.Exit(code=1)

    if not (0 <= weirdness <= 100):
        console.print(f"[red]Invalid --weirdness: {weirdness}. Must be between 0 and 100.[/red]")
        raise typer.Exit(code=1)

    if not (0 <= style_influence <= 100):
        console.print(f"[red]Invalid --style-influence: {style_influence}. Must be between 0 and 100.[/red]")
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

    if duration is not None and not (_DURATION_MIN <= duration <= _DURATION_MAX):
        if duration == 15.0:
            console.print(
                f"[yellow]Warning: --duration 15 is below the minimum ({int(_DURATION_MIN)}s). "
                f"Clamping to {int(_DURATION_MIN)}s. Update your integration to use --duration {int(_DURATION_MIN)} or higher.[/yellow]"
            )
            duration = _DURATION_MIN
        else:
            console.print(
                f"[red]Invalid --duration: {duration}. Must be between {int(_DURATION_MIN)} and {int(_DURATION_MAX)} seconds.[/red]"
            )
            raise typer.Exit(code=1)

    config = load_config()

    # Load and apply preset if provided
    if preset is not None:
        try:
            ensure_default_workspace()
            ws = get_active_workspace()
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

    # Determine effective backend (may change on auto-fallback)
    effective_backend = backend.lower()

    if effective_backend == "ace-step":
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
            )
            return
        except AceStepError as exc:
            if not _is_connection_error(exc):
                # API-level error — do not fall back
                console.print(f"[red]Error: {exc}[/red]")
                raise typer.Exit(code=1)
            # Connection failure — attempt auto-fallback
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
        if vocal_language is not None:
            console.print(
                "[yellow]Warning: --vocal-language is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]"
            )
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

        prompt_additions: list[str] = []
        if parsed_bpm is not None and parsed_bpm != "auto":
            console.print(
                f"[yellow]Warning: --bpm is ACE-Step-specific; injecting '{parsed_bpm} BPM' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(f"{parsed_bpm} BPM")
        elif parsed_bpm == "auto":
            console.print(
                "[yellow]Warning: --bpm auto has no ElevenLabs equivalent; skipping prompt injection.[/yellow]"
            )
        if key is not None and key.lower() != "any":
            console.print(
                f"[yellow]Warning: --key is ACE-Step-specific; injecting '{key}' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(key)
        elif key is not None and key.lower() == "any":
            console.print(
                "[yellow]Warning: --key any has no ElevenLabs equivalent; skipping prompt injection.[/yellow]"
            )
        if time_signature is not None:
            console.print(
                f"[yellow]Warning: --time-signature is ACE-Step-specific; injecting '{time_signature} time signature' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(f"{time_signature} time signature")
        if seed is not None:
            console.print(
                "[yellow]Warning: --seed requires ElevenLabs composition_plan mode, which is not yet implemented. Seed is ignored.[/yellow]"
            )

        augmented_prompt = prompt
        if prompt_additions:
            augmented_prompt = f"{prompt}, {', '.join(prompt_additions)}"

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

    console.print(f"[red]Unknown backend: {backend!r}. Use 'ace-step' or 'elevenlabs'.[/red]")
    raise typer.Exit(code=1)


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
) -> None:
    """Submit, poll, and download audio via the ACE-Step backend."""
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

    start = time.monotonic()
    result: dict = {}
    with console.status("[bold green]Generating…[/bold green]", spinner="dots") as status:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= poll_timeout:
                console.print(f"[red]Timed out after {poll_timeout:.0f} seconds.[/red]")
                raise typer.Exit(code=1)

            try:
                result = ace_client.query_result(task_id)
            except AceStepError as exc:
                console.print(f"[red]Error polling status: {exc}[/red]")
                raise typer.Exit(code=1)

            job_status = result.get("status", "unknown")
            status.update(f"[bold green]Generating… ({elapsed:.0f}s) — {job_status}[/bold green]")

            if job_status == "completed":
                break
            if job_status == "failed":
                error_msg = result.get("error", "unknown error")
                console.print(f"[red]Generation failed: {error_msg}[/red]")
                raise typer.Exit(code=1)

            time.sleep(poll_interval)

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


_VALID_SOUND_TYPES = {"one-shot", "loop"}


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
) -> None:
    """Generate short audio samples (loops or one-shots) using the ACE-Step model."""
    _VALID_FORMATS = {"wav", "flac", "mp3", "aac", "opus"}
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

    config = load_config()

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

    start = time.monotonic()
    result: dict = {}
    with console.status("[bold green]Generating…[/bold green]", spinner="dots") as status:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= poll_timeout:
                console.print(f"[red]Timed out after {poll_timeout:.0f} seconds.[/red]")
                raise typer.Exit(code=1)

            try:
                result = ace_client.query_result(task_id)
            except AceStepError as exc:
                console.print(f"[red]Error polling status: {exc}[/red]")
                raise typer.Exit(code=1)

            job_status = result.get("status", "unknown")
            status.update(f"[bold green]Generating… ({elapsed:.0f}s) — {job_status}[/bold green]")

            if job_status == "completed":
                break
            if job_status == "failed":
                error_msg = result.get("error", "unknown error")
                console.print(f"[red]Generation failed: {error_msg}[/red]")
                raise typer.Exit(code=1)

            time.sleep(poll_interval)

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
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")


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
        ensure_default_workspace()
        ws = get_active_workspace()
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

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="bold")
    table.add_column("Value")
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
    for field_name, value in fields:
        table.add_row(field_name, value)
    console.print(table)


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
        ensure_default_workspace()
        ws = get_active_workspace()
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
        ensure_default_workspace()
        ws = get_active_workspace()
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
    # Validate that exactly one of --target-bpm or --rate is provided
    if target_bpm is not None and rate is not None:
        console.print("[red]Error: provide either --target-bpm or --rate, not both.[/red]")
        raise typer.Exit(code=1)

    if target_bpm is None and rate is None:
        console.print("[red]Error: must provide either --target-bpm or --rate.[/red]")
        raise typer.Exit(code=1)

    # Get source clip
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    # Determine the rate to use
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

    # Validate rate
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

    # Validate source has duration
    if source.duration is None:
        console.print(
            f"[red]Error: clip {clip_id} has no duration metadata — cannot calculate new duration. "
            f"Re-import the clip to detect duration.[/red]"
        )
        raise typer.Exit(code=1)

    # Get workspace and create output path
    try:
        clips_dir = get_workspace_path(source.workspace_id)
        clips_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, sqlite3.Error, OSError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    src_ext = Path(source.file_path).suffix.lower() or ".wav"
    dest_name = f"{uuid.uuid4().hex}{src_ext}"
    dest_path = clips_dir / dest_name

    # Perform time-stretch
    try:
        time_stretch_audio(
            input_path=source.file_path,
            output_path=str(dest_path),
            rate=final_rate,
        )
    except Exception as exc:
        console.print(f"[red]Error during time-stretch: {exc}[/red]")
        raise typer.Exit(code=1)

    # Calculate new duration and BPM
    new_duration_s = source.duration / final_rate
    new_bpm = None
    if source.bpm is not None:
        new_bpm = source.bpm * final_rate

    # Create new clip record
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

    # Format output message
    rate_pct = final_rate * 100
    bpm_str = f" (→ {new_bpm:.1f} BPM)" if new_bpm is not None else ""
    console.print(f"  [green]✓[/green] Speed adjusted on clip {clip_id} → clip {new_id}")
    console.print(f"    Path:     {dest_path}")
    console.print(f"    Duration: {_fmt_duration(source.duration)} → {_fmt_duration(new_duration_s)}")
    console.print(f"    Speed:    {rate_pct:.1f}%{bpm_str}")


# ---------------------------------------------------------------------------


@app.command()
def stems(
    clip_id: int = typer.Argument(..., help="ID of the source clip to separate into stems."),
    output_format: str = typer.Option("wav", "--output-format", help="Stem output format: wav or flac."),
    output: Optional[Path] = typer.Option(None, "--output", help="Output directory (default: stems/ next to source)."),
) -> None:
    """Separate a clip into individual stems (vocals, drums, bass, other) using AI source separation."""
    # Validate output format
    if output_format not in ("wav", "flac"):
        console.print(f"[red]Error: --output-format must be wav or flac, got {output_format!r}.[/red]")
        raise typer.Exit(code=1)

    # Get source clip
    source = get_clip(clip_id)
    if source is None:
        console.print(f"[red]Error: clip {clip_id} not found.[/red]")
        raise typer.Exit(code=1)

    # Resolve output directory
    if output is not None:
        stems_dir = output
    else:
        stems_dir = Path(source.file_path).parent / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    # Derive base name from source file
    base_name = Path(source.file_path).stem

    # Separate stems
    client = StemsClient()
    start_time = time.time()
    try:
        with console.status("[bold green]Loading model and separating stems...") as status:

            def _progress(msg: str) -> None:
                status.update(f"[bold green]{msg}")

            stem_data = client.separate(source.file_path, progress_callback=_progress)
            status.update("[bold green]Saving stems...")
            stem_path_map = client.save_stems(
                stem_data,
                stems_dir,
                base_name,
                sample_rate=client.model_samplerate,
                output_format=output_format,
            )
    except StemsError as exc:
        console.print(f"[red]Error during separation: {exc}[/red]")
        raise typer.Exit(code=1)

    elapsed = time.time() - start_time

    # Register each stem as a child clip
    new_ids = []
    for label, stem_path in stem_path_map.items():
        dur = get_duration(stem_path)
        stem_clip = Clip(
            workspace_id=source.workspace_id,
            file_path=str(stem_path.resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
            format=output_format,
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

    # Print summary
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

    # Resolve output directory
    if output is not None:
        midi_dir = output
    else:
        midi_dir = Path(source.file_path).parent / "midi"
    midi_dir.mkdir(parents=True, exist_ok=True)

    base_name = Path(source.file_path).stem

    # Load stem paths if requested
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
        ensure_default_workspace()
        ws = get_active_workspace()

        # TODO: If from_last, load last generation parameters from config or state file
        # For now, just require explicit parameters
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
        ensure_default_workspace()
        ws = get_active_workspace()
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
        ensure_default_workspace()
        ws = get_active_workspace()
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
        ensure_default_workspace()
        ws = get_active_workspace()
        success = delete_preset(ws.id, name)

        if not success:
            console.print(f"[red]Error: Preset '{name}' not found.[/red]")
            raise typer.Exit(code=1)

        console.print(f"[green]✓ Preset '{name}' deleted.[/green]")

    except (ValueError, sqlite3.Error) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
