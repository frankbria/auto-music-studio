"""CLI entry point for acemusic (US-2.1)."""

from typing import Optional

import typer

from acemusic import __version__
from acemusic.config import load_config

app = typer.Typer(help="acemusic — AI music generation CLI")


def _version_callback(value: bool) -> None:
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
    if ctx.invoked_subcommand is not None:
        config = load_config()
        if not config.api_url:
            typer.echo("ACE-Step server URL not configured. " "Set ACEMUSIC_BASE_URL in .env or config.yaml")
            raise typer.Exit(1)


@app.command()
def generate() -> None:
    """Generate music using the ACE-Step model."""
    typer.echo("Not yet implemented")


@app.command()
def status() -> None:
    """Check the status of the ACE-Step server."""
    typer.echo("Not yet implemented")
