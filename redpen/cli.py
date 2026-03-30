"""Click CLI for RedPen.

Commands: init, run, status, export, go (init + run combo).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console

from redpen.config import load_config
from redpen.display import show_header, show_status

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """RedPen — AI writing refinement engine."""
    _setup_logging(verbose)


@main.command()
@click.argument("draft", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", default="blog", help="Content format (blog, linkedin, thread)")
@click.option("--tag", default="", help="Tag for this run")
def init(draft: Path, fmt: str, tag: str) -> None:
    """Initialize a new RedPen run from a draft file."""
    from redpen.data import init_run

    root = Path.cwd()
    config = load_config(path=root / "config.toml")

    # Validate format
    if fmt not in config.formats:
        available = ", ".join(config.formats.keys())
        console.print(f"[red]Unknown format '{fmt}'. Available: {available}[/red]")
        raise SystemExit(1)

    data_dir = init_run(root, draft, fmt=fmt, tag=tag)
    console.print(f"[green]Initialized RedPen run[/green]")
    console.print(f"  Draft: {draft}")
    console.print(f"  Format: {fmt}")
    console.print(f"  Data dir: {data_dir}")
    if tag:
        console.print(f"  Tag: {tag}")
    console.print(f"\nRun [bold]redpen run[/bold] to start the optimization loop.")


@main.command()
@click.option("--max-iterations", type=int, default=None, help="Override max iterations")
@click.option("--format", "fmt", default=None, help="Override content format")
def run(max_iterations: int | None, fmt: str | None) -> None:
    """Run the optimization loop on an initialized draft."""
    from redpen.data import get_status
    from redpen.loop import run_loop

    root = Path.cwd()
    config = load_config(
        path=root / "config.toml",
        overrides={"max_iterations": max_iterations},
    )

    status = get_status(root)
    if status["status"] == "unknown" or status["total_iterations"] == 0:
        # Check if data/draft.md exists
        if not (root / "data" / "draft.md").exists():
            console.print("[red]No initialized run found. Run 'redpen init <draft>' first.[/red]")
            raise SystemExit(1)

    run_fmt = fmt or status.get("format", "blog")
    show_header(status.get("tag", ""), run_fmt)

    asyncio.run(run_loop(config, fmt=run_fmt))


@main.command()
def status() -> None:
    """Show current run status and iteration history."""
    from redpen.data import get_status

    root = Path.cwd()
    st = get_status(root)

    if st["status"] == "unknown":
        console.print("[dim]No run found. Run 'redpen init <draft>' to start.[/dim]")
        return

    show_status(st)


@main.command()
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None, help="Output file path")
@click.option("--json", "as_json", is_flag=True, help="Export scores as JSON")
def export(output: Path | None, as_json: bool) -> None:
    """Export final draft + changelog + score trajectory."""
    from redpen.export import export_final, export_scores_json

    root = Path.cwd()

    if as_json:
        out = export_scores_json(root, output)
        console.print(f"[green]Scores exported to {out}[/green]")
    else:
        out = export_final(root, output)
        console.print(f"[green]Final draft exported to {out}[/green]")


@main.command()
@click.argument("draft", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", default="blog", help="Content format")
@click.option("--tag", default="", help="Tag for this run")
@click.option("--max-iterations", type=int, default=None, help="Override max iterations")
def go(draft: Path, fmt: str, tag: str, max_iterations: int | None) -> None:
    """Initialize and run in one command."""
    from redpen.data import init_run
    from redpen.loop import run_loop

    root = Path.cwd()
    config = load_config(
        path=root / "config.toml",
        overrides={"max_iterations": max_iterations},
    )

    if fmt not in config.formats:
        available = ", ".join(config.formats.keys())
        console.print(f"[red]Unknown format '{fmt}'. Available: {available}[/red]")
        raise SystemExit(1)

    init_run(root, draft, fmt=fmt, tag=tag)
    show_header(tag, fmt)

    asyncio.run(run_loop(config, fmt=fmt))
