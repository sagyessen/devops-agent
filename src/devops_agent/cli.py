from __future__ import annotations

import typer

from devops_agent import __version__

app = typer.Typer(name="devops-agent", help="Local-first AWS DevOps assistant.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"devops-agent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


if __name__ == "__main__":
    app()
