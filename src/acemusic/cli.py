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

    client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
    try:
        stats = client.get_stats(timeout=5.0)
    except Exception as exc:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            console.print("[red]Server: unreachable — connection timed out[/red]")
        elif isinstance(exc, httpx.HTTPStatusError):
            console.print(f"[red]Server: error — {exc.response.status_code} {exc.response.text}[/red]")
        else:
            console.print(f"[red]Server: unreachable — {exc}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Server: healthy[/green]")

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

    # ElevenLabs key status
    if config.elevenlabs_api_key:
        el_client = ElevenLabsClient(api_key=config.elevenlabs_api_key, output_format=config.elevenlabs_output_format)
        key_valid = el_client.validate_key()
        if key_valid:
            console.print("[green]ElevenLabs: configured (valid)[/green]")
        else:
            console.print("[red]ElevenLabs: configured (invalid — check ELEVENLABS_API_KEY)[/red]")
    else:
        console.print("[yellow]ElevenLabs: not configured (ELEVENLABS_API_KEY not set)[/yellow]")


def _is_connection_error(exc: AceStepError) -> bool:
    """Return True if the AceStepError is a connection/timeout failure (not an API error)."""
    msg = str(exc).lower()
    return any(
        keyword in msg for keyword in ("connection refused", "connect", "timeout", "unreachable", "name or service")
    )


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Text description of the music to generate."),
    num_clips: int = typer.Option(2, "--num-clips", help="Number of audio clips to generate."),
    duration: Optional[float] = typer.Option(None, "--duration", help="Desired audio duration in seconds."),
    format: str = typer.Option("wav", "--format", help="Output audio format."),
    output: Optional[Path] = typer.Option(None, "--output", help="Directory to save generated files."),
    name: Optional[str] = typer.Option(None, "--name", help="Custom filename prefix (e.g. 'demo' → demo-1.wav)."),
    backend: str = typer.Option("ace-step", "--backend", help="AI backend: 'ace-step' (default) or 'elevenlabs'."),
) -> None:
    """Generate music from a text prompt using the ACE-Step model or ElevenLabs cloud."""
    config = load_config()

    # Resolve output directory: --output > config output_dir > CWD
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
        el_client = ElevenLabsClient(
            api_key=config.elevenlabs_api_key,
            output_format=config.elevenlabs_output_format,
        )
        _generate_via_elevenlabs(
            el_client=el_client,
            prompt=prompt,
            num_clips=num_clips,
            duration=duration,
            output_path=output_path,
            slug=slug,
            timestamp=timestamp,
            safe_name=safe_name,
            output_format=config.elevenlabs_output_format,
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
) -> None:
    """Submit, poll, and download audio via the ACE-Step backend."""
    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0

    task_id = ace_client.submit_task(prompt=prompt, num_clips=num_clips, audio_duration=duration, format=format)
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
) -> None:
    """Generate N clips sequentially via ElevenLabs and save them to disk."""
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
            dur = get_duration(dest)
            dur_str = f"{dur:.1f}s"
        except Exception:
            dur_str = "unknown"

        console.print(f"  [green]✓[/green] {dest.resolve()}  ({dur_str})")


@app.command()
def status() -> None:
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")
