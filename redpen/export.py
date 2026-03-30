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
    load_iteration_comments,
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


def export_html(root: Path, output: Path | None = None) -> Path:
    """Export a single-page HTML report with full iteration timeline."""
    if output is None:
        output = root / "report.html"

    status = get_status(root)
    iterations = status.get("iterations", [])

    # Collect all data
    iter_data: list[dict[str, Any]] = []
    for it in iterations:
        n = it["number"]
        scores = load_iteration_scores(root, n)
        comments = load_iteration_comments(root, n)
        summary = load_iteration_summary(root, n)
        diff_path = root / "data" / f"iter_{n:02d}" / "diff.md"
        diff = diff_path.read_text().strip() if diff_path.exists() else ""
        snapshot_path = root / "data" / f"iter_{n:02d}" / "snapshot.md"
        snapshot = snapshot_path.read_text().strip() if snapshot_path.exists() else ""

        iter_data.append({
            "number": n,
            "status": it.get("status", "?"),
            "reason": it.get("reason", ""),
            "scores": scores,
            "comments": comments,
            "summary": summary,
            "diff": diff,
            "snapshot": snapshot,
        })

    draft = current_draft(root)

    html = _build_html_report(status, iter_data, draft)
    output.write_text(html)
    return output


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_html_report(
    status: dict[str, Any],
    iterations: list[dict[str, Any]],
    final_draft: str,
) -> str:
    """Build the full HTML report."""
    rows = ""
    for it in iterations:
        n = it["number"]
        st = it["status"]
        color = "#22c55e" if st == "kept" else "#ef4444" if st == "discarded" else "#a3a3a3"
        stats = it.get("summary", {}).get("stats", {}) if it.get("summary") else {}
        min_s = f"{stats['min_score']:.1f}" if stats.get("min_score") is not None else "—"
        mean_s = f"{stats['mean_score']:.1f}" if stats.get("mean_score") is not None else "—"
        rows += f'<tr><td>{n}</td><td style="color:{color};font-weight:600">{st}</td><td>{min_s}</td><td>{mean_s}</td><td>{_esc(it.get("reason", ""))}</td></tr>\n'

    # Build iteration detail cards
    cards = ""
    for it in iterations:
        n = it["number"]
        st = it["status"]
        border = "#22c55e" if st == "kept" else "#ef4444" if st == "discarded" else "#d4d4d4"

        # Scores table
        score_rows = ""
        scores = it.get("scores", {})
        for persona, dims in sorted(scores.items()):
            if isinstance(dims, dict):
                for dim, info in sorted(dims.items()):
                    if isinstance(info, dict):
                        sc = info.get("score", "?")
                        score_rows += f"<tr><td>{_esc(persona)}</td><td>{_esc(dim)}</td><td><strong>{sc}</strong></td></tr>\n"

        # Comments
        comment_html = ""
        for entry in it.get("comments", []):
            persona = entry.get("persona", "?")
            model = entry.get("model", "?")
            comment_html += f'<div class="comment-source">{_esc(persona)} ({model})</div>\n'
            for c in entry.get("comments", []):
                comment_html += f'<div class="comment">{_esc(c)}</div>\n'

        # Edit description
        diff = it.get("diff", "")
        diff_html = f'<div class="edit-desc">{_esc(diff)}</div>' if diff else ""

        cards += f"""
<div class="iter-card" style="border-left: 4px solid {border}">
    <h3>Iteration {n} — <span style="color:{border}">{st.upper()}</span></h3>
    <p class="reason">{_esc(it.get('reason', ''))}</p>
    {diff_html}
    <details><summary>Scores</summary>
    <table class="scores"><tr><th>Persona</th><th>Dimension</th><th>Score</th></tr>
    {score_rows}</table></details>
    <details><summary>Reader Comments</summary>{comment_html}</details>
    <details><summary>Draft Snapshot</summary><pre class="snapshot">{_esc(it.get('snapshot', ''))}</pre></details>
</div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RedPen Report — {_esc(status.get('tag', 'run'))}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 24px; background: #0a0a0a; color: #e5e5e5; line-height: 1.6; }}
h1 {{ color: #ef4444; margin-bottom: 4px; font-size: 28px; }}
h2 {{ color: #a3a3a3; font-size: 18px; margin: 32px 0 12px; border-bottom: 1px solid #262626; padding-bottom: 8px; }}
h3 {{ font-size: 16px; margin-bottom: 8px; }}
.meta {{ color: #737373; font-size: 14px; margin-bottom: 24px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }}
th {{ text-align: left; padding: 8px 12px; background: #171717; color: #a3a3a3; font-weight: 500; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #1a1a1a; }}
.iter-card {{ background: #141414; border-radius: 8px; padding: 20px; margin: 16px 0; }}
.reason {{ color: #737373; font-size: 14px; margin-bottom: 8px; }}
.edit-desc {{ background: #1a1a3a; border-left: 3px solid #6366f1; padding: 12px 16px; border-radius: 4px; margin: 12px 0; font-size: 14px; }}
details {{ margin: 8px 0; }}
summary {{ cursor: pointer; color: #a3a3a3; font-size: 14px; padding: 4px 0; }}
summary:hover {{ color: #e5e5e5; }}
.scores th {{ font-size: 13px; }}
.scores td {{ font-size: 13px; }}
.comment-source {{ color: #6366f1; font-size: 13px; font-weight: 600; margin-top: 12px; }}
.comment {{ background: #1a1a1a; padding: 10px 14px; border-radius: 6px; margin: 6px 0; font-size: 13px; color: #d4d4d4; }}
.final-draft {{ background: #0f1a0f; border: 1px solid #22c55e33; border-radius: 8px; padding: 24px; white-space: pre-wrap; font-size: 15px; line-height: 1.8; }}
pre.snapshot {{ background: #0a0a0a; padding: 16px; border-radius: 6px; font-size: 13px; white-space: pre-wrap; overflow-x: auto; color: #a3a3a3; }}
.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0; }}
.stat-card {{ background: #171717; border-radius: 8px; padding: 16px; text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: 700; }}
.stat-label {{ font-size: 12px; color: #737373; margin-top: 4px; }}
</style>
</head>
<body>
<h1>🔴 RedPen Report</h1>
<div class="meta">
    Tag: {_esc(status.get('tag', ''))} &nbsp;|&nbsp;
    Format: {_esc(status.get('format', ''))} &nbsp;|&nbsp;
    Status: {_esc(status.get('status', ''))} &nbsp;|&nbsp;
    {_esc(status.get('stop_reason', ''))}
</div>

<div class="summary-grid">
    <div class="stat-card"><div class="stat-value">{status.get('total_iterations', 0)}</div><div class="stat-label">Iterations</div></div>
    <div class="stat-card"><div class="stat-value" style="color:#22c55e">{status.get('kept', 0)}</div><div class="stat-label">Kept</div></div>
    <div class="stat-card"><div class="stat-value" style="color:#ef4444">{status.get('discarded', 0)}</div><div class="stat-label">Discarded</div></div>
</div>

<h2>Score Trajectory</h2>
<table>
<tr><th>#</th><th>Decision</th><th>Min Score</th><th>Mean Score</th><th>Reason</th></tr>
{rows}
</table>

<h2>Iteration Details</h2>
{cards}

<h2>Final Draft</h2>
<div class="final-draft">{_esc(final_draft)}</div>

</body>
</html>"""


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
