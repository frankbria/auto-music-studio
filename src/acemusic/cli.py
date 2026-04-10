"""CLI entry point for acemusic (US-2.1, US-2.2, US-2.3)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from acemusic import __version__
from acemusic.client import AceStepClient, AceStepError
from acemusic.config import load_config
from acemusic.elevenlabs_client import ElevenLabsClient, ElevenLabsError
from acemusic.utils import get_duration, make_filename, make_slug

app = typer.Typer(help="acemusic — AI music generation CLI")
console = Console()


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
    else:
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
) -> None:
    """Generate music from a text prompt using the ACE-Step model or ElevenLabs cloud."""
    # --- Validate musical parameters ---
    parsed_bpm: int | str | None = None
    if bpm is not None:
        try:
            parsed_bpm = _parse_bpm(bpm)
        except typer.BadParameter as exc:
            console.print(f"[red]Invalid --bpm: {exc}[/red]")
            raise typer.Exit(code=1)

    if time_signature is not None and time_signature not in _VALID_TIME_SIGNATURES:
        console.print(
            f"[red]Invalid --time-signature: {time_signature!r}. "
            f"Allowed values: {', '.join(sorted(_VALID_TIME_SIGNATURES))}[/red]"
        )
        raise typer.Exit(code=1)

    if duration is not None and not (_DURATION_MIN <= duration <= _DURATION_MAX):
        console.print(
            f"[red]Invalid --duration: {duration}. Must be between {int(_DURATION_MIN)} and {int(_DURATION_MAX)} seconds.[/red]"
        )
        raise typer.Exit(code=1)

    config = load_config()

    # Resolve output directory: --output > config output_dir > CWD
    if output is not None:
        output_path = output
    elif config.output_dir:
        output_path = Path(config.output_dir).expanduser()
    else:
        output_path = Path.cwd()
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
                    f"[red]ACE-Step unavailable ({exc}). " "Set ELEVENLABS_API_KEY to enable automatic fallback.[/red]"
                )
                raise typer.Exit(code=1)
            console.print("[yellow]ACE-Step unavailable — falling back to ElevenLabs[/yellow]")
            effective_backend = "elevenlabs"

    if effective_backend == "elevenlabs":
        if not config.elevenlabs_api_key:
            console.print(
                "[red]ELEVENLABS_API_KEY is not configured. " "Set it in .env to use the ElevenLabs backend.[/red]"
            )
            raise typer.Exit(code=1)
        if vocal_language is not None:
            console.print(
                "[yellow]Warning: --vocal-language is ACE-Step-specific and is ignored by ElevenLabs.[/yellow]"
            )

        # Build augmented prompt: inject ACE-Step-specific musical params as text descriptors
        prompt_additions: list[str] = []
        if parsed_bpm is not None:
            console.print(
                f"[yellow]Warning: --bpm is ACE-Step-specific; injecting '{parsed_bpm} BPM' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(f"{parsed_bpm} BPM")
        if key is not None:
            console.print(
                f"[yellow]Warning: --key is ACE-Step-specific; injecting '{key}' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(key)
        if time_signature is not None:
            console.print(
                f"[yellow]Warning: --time-signature is ACE-Step-specific; injecting '{time_signature} time signature' into prompt for ElevenLabs.[/yellow]"
            )
            prompt_additions.append(f"{time_signature} time signature")
        if seed is not None:
            console.print(
                "[yellow]Warning: --seed is ACE-Step-specific and cannot be replicated in ElevenLabs. Seed is ignored.[/yellow]"
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
        try:
            dur = get_duration(dest)
            dur_str = f"{dur:.1f}s"
        except Exception:
            dur_str = "unknown"

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


@app.command()
def status() -> None:
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")
