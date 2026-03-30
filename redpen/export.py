"""Export pipeline — final draft, changelog, and score trajectory.

Produces a clean export of the best draft version along with a record
of every kept edit and how scores evolved across iterations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from redpen.data import (
    current_draft,
    get_status,
    load_iteration_scores,
    load_iteration_summary,
)
from redpen.scorer import overall_stats


def export_final(root: Path, output: Path | None = None) -> Path:
    """Export the final draft, changelog, and score trajectory.

    Returns the path to the exported file.
    """
    if output is None:
        output = root / "final.md"

    draft = current_draft(root)
    status = get_status(root)
    iterations = status.get("iterations", [])

    changelog = _build_changelog(root, iterations)
    trajectory = _build_trajectory(root, iterations)

    parts: list[str] = []
    parts.append(draft)
    parts.append("\n\n---\n\n")
    parts.append("# Changelog\n\n")
    parts.append(changelog)
    parts.append("\n\n---\n\n")
    parts.append("# Score Trajectory\n\n")
    parts.append(trajectory)

    output.write_text("".join(parts))
    return output


def _build_changelog(root: Path, iterations: list[dict[str, Any]]) -> str:
    """Build a changelog of all kept edits."""
    lines: list[str] = []

    for it in iterations:
        if it.get("status") != "kept":
            continue
        n = it["number"]
        reason = it.get("reason", "")

        # Try to load the diff description
        diff_path = root / "data" / f"iter_{n:02d}" / "diff.md"
        description = ""
        if diff_path.exists():
            description = diff_path.read_text().strip()

        # Load summary for score info
        summary = load_iteration_summary(root, n)
        stats = summary.get("stats", {}) if summary else {}

        entry = f"## Iteration {n}\n\n"
        if description:
            entry += f"{description}\n\n"
        entry += f"Decision: kept — {reason}\n"
        if stats:
            entry += f"Scores: min={stats.get('min_score', '?'):.1f}, mean={stats.get('mean_score', '?'):.1f}\n"

        lines.append(entry)

    return "\n".join(lines) if lines else "(No kept iterations)"


def _build_trajectory(root: Path, iterations: list[dict[str, Any]]) -> str:
    """Build a score trajectory showing how scores evolved."""
    lines: list[str] = []
    lines.append("| Iteration | Min Score | Mean Score | Decision |")
    lines.append("|-----------|-----------|------------|----------|")

    for it in iterations:
        n = it["number"]
        status = it.get("status", "?")
        summary = load_iteration_summary(root, n)
        stats = summary.get("stats", {}) if summary else {}

        min_s = f"{stats['min_score']:.1f}" if "min_score" in stats else "—"
        mean_s = f"{stats['mean_score']:.1f}" if "mean_score" in stats else "—"
        lines.append(f"| {n} | {min_s} | {mean_s} | {status} |")

    return "\n".join(lines)


def export_scores_json(root: Path, output: Path | None = None) -> Path:
    """Export all iteration scores as a single JSON file."""
    if output is None:
        output = root / "scores.json"

    status = get_status(root)
    iterations = status.get("iterations", [])

    all_scores: list[dict[str, Any]] = []
    for it in iterations:
        n = it["number"]
        scores = load_iteration_scores(root, n)
        summary = load_iteration_summary(root, n)
        all_scores.append({
            "iteration": n,
            "status": it.get("status"),
            "scores": {
                persona: {
                    dim: info["score"]
                    for dim, info in dims.items()
                }
                for persona, dims in scores.items()
            },
            "stats": summary.get("stats") if summary else None,
        })

    output.write_text(json.dumps(all_scores, indent=2) + "\n")
    return output
