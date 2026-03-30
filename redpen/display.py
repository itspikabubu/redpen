"""Rich console helpers for terminal output.

Provides progress panels, iteration tables, score summaries, and
color-coded improvement/regression indicators.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


# ---------------------------------------------------------------------------
# Score formatting
# ---------------------------------------------------------------------------

def _score_color(score: float) -> str:
    """Return a color name based on score value."""
    if score >= 8.0:
        return "green"
    if score >= 6.0:
        return "yellow"
    if score >= 4.0:
        return "red"
    return "bold red"


def _delta_text(delta: float) -> Text:
    """Format a score delta with color."""
    if delta > 0.01:
        return Text(f"+{delta:.1f}", style="green")
    if delta < -0.01:
        return Text(f"{delta:.1f}", style="red")
    return Text("=", style="dim")


# ---------------------------------------------------------------------------
# Public display functions
# ---------------------------------------------------------------------------

def show_header(tag: str, fmt: str) -> None:
    """Display the RedPen header."""
    console.print()
    console.print(
        Panel(
            f"[bold]RedPen[/bold] — AI Writing Refinement Engine\n"
            f"Format: [cyan]{fmt}[/cyan]  Tag: [cyan]{tag or '(none)'}[/cyan]",
            border_style="red",
        )
    )


def show_iteration_start(iteration: int) -> None:
    """Display iteration start banner."""
    console.print(f"\n[bold]--- Iteration {iteration} ---[/bold]")


def show_eval_progress(persona: str, result_type: str) -> None:
    """Show that a persona evaluation completed."""
    icon = "[green]✓[/green]" if result_type == "scores" else "[blue]✓[/blue]"
    label = "scored" if result_type == "scores" else "commented"
    console.print(f"  {icon} {persona} {label}")


def show_scores(
    persona_scores: dict[str, dict[str, dict[str, Any]]],
    focus: dict[str, int],
    prev_scores: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> None:
    """Display a score table for all personas and dimensions."""
    table = Table(title="Evaluation Scores", show_lines=True)
    table.add_column("Persona", style="bold")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")
    if prev_scores:
        table.add_column("Delta", justify="right")
    table.add_column("Focus", justify="right")

    total_focus = sum(focus.values()) or 1

    for persona in sorted(persona_scores.keys()):
        dims = persona_scores[persona]
        weight = focus.get(persona, 0)
        pct = f"{(weight / total_focus) * 100:.0f}%"

        for dim in sorted(dims.keys()):
            info = dims[dim]
            score = info["score"]
            color = _score_color(score)
            row: list[Any] = [persona, dim, Text(f"{score:.1f}", style=color)]

            if prev_scores:
                prev_dim = prev_scores.get(persona, {}).get(dim)
                if prev_dim:
                    delta = score - prev_dim["score"]
                    row.append(_delta_text(delta))
                else:
                    row.append(Text("new", style="dim"))

            row.append(pct)
            table.add_row(*row)
            # Only show persona name and focus on first row
            persona = ""
            pct = ""

    console.print(table)


def show_comments(comments: list[dict[str, Any]]) -> None:
    """Display reader comments."""
    if not comments:
        return

    console.print("\n[bold]Reader Comments[/bold]")
    for entry in comments:
        persona = entry.get("persona", "unknown")
        model = entry.get("model", "unknown")
        console.print(f"\n  [cyan]{persona}[/cyan] ([dim]{model}[/dim]):")
        for comment in entry.get("comments", []):
            # Indent each line of the comment
            for line in comment.split("\n"):
                console.print(f"    {line}")


def show_decision(kept: bool, reason: str) -> None:
    """Display keep/discard decision."""
    if kept:
        console.print(f"\n  [green bold]KEPT[/green bold] — {reason}")
    else:
        console.print(f"\n  [red bold]DISCARDED[/red bold] — {reason}")


def show_edit_description(description: str) -> None:
    """Display the writer's edit description."""
    if description:
        console.print(Panel(description, title="Edit", border_style="blue"))


def show_overall_stats(stats: dict[str, float]) -> None:
    """Display overall score statistics."""
    min_s = stats.get("min_score", 0)
    mean_s = stats.get("mean_score", 0)
    console.print(
        f"  Overall: min=[{_score_color(min_s)}]{min_s:.1f}[/] "
        f"mean=[{_score_color(mean_s)}]{mean_s:.1f}[/]"
    )


def show_stuck_warning(weakness: str) -> None:
    """Display stuck detection warning."""
    console.print(
        f"\n  [yellow bold]STUCK[/yellow bold] on {weakness} — "
        f"switching approach"
    )


def show_stop_reason(reason: str) -> None:
    """Display why the loop stopped."""
    console.print(f"\n[bold]Run complete:[/bold] {reason}")


def show_status(status: dict[str, Any]) -> None:
    """Display run status overview."""
    table = Table(title="RedPen Run Status")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Status", status.get("status", "unknown"))
    table.add_row("Format", status.get("format", ""))
    table.add_row("Tag", status.get("tag", ""))
    table.add_row("Total iterations", str(status.get("total_iterations", 0)))
    table.add_row("Kept", str(status.get("kept", 0)))
    table.add_row("Discarded", str(status.get("discarded", 0)))
    if status.get("created_at"):
        table.add_row("Started", status["created_at"])
    if status.get("finished_at"):
        table.add_row("Finished", status["finished_at"])
    if status.get("stop_reason"):
        table.add_row("Stop reason", status["stop_reason"])

    console.print(table)

    # Iteration history
    iterations = status.get("iterations", [])
    if iterations:
        hist = Table(title="Iteration History")
        hist.add_column("#", justify="right")
        hist.add_column("Status")
        hist.add_column("Reason")

        for it in iterations:
            n = str(it.get("number", "?"))
            st = it.get("status", "?")
            style = "green" if st == "kept" else "red" if st == "discarded" else "dim"
            reason = it.get("reason", "")
            hist.add_row(n, Text(st, style=style), reason)

        console.print(hist)
