"""CLI entry point for acemusic (US-2.1, US-2.2)."""

from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from acemusic import __version__
from acemusic.client import AceStepClient
from acemusic.config import load_config

app = typer.Typer(help="acemusic — AI music generation CLI")


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
def generate() -> None:
    """Generate music using the ACE-Step model."""
    typer.echo("Not yet implemented")


@app.command()
def health() -> None:
    """Check connectivity and stats for the ACE-Step server."""
    console = Console()
    config = load_config()

    client = AceStepClient(base_url=config.api_url, api_key=config.api_key)
    try:
        stats = client.get_stats(timeout=5.0)
    except httpx.TimeoutException:
        console.print("[red]Server: unreachable — connection timed out[/red]")
        raise typer.Exit(code=1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Server: error — {exc.response.status_code} {exc.response.text}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
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
def status() -> None:
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")
