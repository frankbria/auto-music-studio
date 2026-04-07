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
    """Check connectivity and stats for the ACE-Step server."""
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


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Text description of the music to generate."),
    num_clips: int = typer.Option(2, "--num-clips", help="Number of audio clips to generate."),
    duration: Optional[float] = typer.Option(None, "--duration", help="Desired audio duration in seconds."),
    format: str = typer.Option("wav", "--format", help="Output audio format."),
    output: Path = typer.Option(Path("."), "--output", help="Directory to save generated files."),
) -> None:
    """Generate music from a text prompt using the ACE-Step model."""
    config = load_config()
    poll_timeout = float(os.environ.get("ACEMUSIC_POLL_TIMEOUT", "600"))
    poll_interval = 2.0

    output.mkdir(parents=True, exist_ok=True)
    slug = make_slug(prompt)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    client = AceStepClient(base_url=config.api_url, api_key=config.api_key)

    # Submit
    try:
        task_id = client.submit_task(prompt=prompt, num_clips=num_clips, audio_duration=duration, format=format)
    except AceStepError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"Task submitted: [cyan]{task_id}[/cyan]")

    # Poll
    start = time.monotonic()
    result: dict = {}
    with console.status("[bold green]Generating…[/bold green]", spinner="dots") as status:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= poll_timeout:
                console.print(f"[red]Timed out after {poll_timeout:.0f} seconds.[/red]")
                raise typer.Exit(code=1)

            try:
                result = client.query_result(task_id)
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

    # Download and save
    audio_urls: list[str] = result.get("audio_urls", [])
    for i, url in enumerate(audio_urls, start=1):
        filename = make_filename(slug, timestamp, i, ext=format)
        dest = output / filename
        try:
            data = client.download_audio(url)
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


@app.command()
def status() -> None:
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")
