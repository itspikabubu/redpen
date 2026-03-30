"""Main autoresearch loop orchestrator.

Runs the iterative refinement cycle: evaluate → diagnose weakness → write edit →
evaluate again → keep/discard → repeat. Handles stuck detection and stopping
conditions.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from redpen.config import RedPenConfig, get_format_config
from redpen.data import (
    current_draft,
    finalize_iteration,
    finish_run,
    load_iteration_scores,
    new_iteration,
    save_comments,
    save_diff,
    save_scores,
    save_summary,
    write_draft,
)
from redpen.display import (
    console,
    show_comments,
    show_decision,
    show_edit_description,
    show_eval_progress,
    show_iteration_start,
    show_overall_stats,
    show_scores,
    show_stop_reason,
    show_stuck_warning,
)
from redpen.evaluate import evaluate_draft, load_personas
from redpen.scorer import (
    aggregate_persona_scores,
    detect_stuck,
    find_weaknesses,
    overall_stats,
    should_keep,
)
from redpen.writer import generate_edit

logger = logging.getLogger(__name__)


def _git_commit(root: Path, message: str) -> bool:
    """Create a git commit with the current data/ contents."""
    try:
        subprocess.run(
            ["git", "add", "data/"],
            cwd=root, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", message],
            cwd=root, capture_output=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Git commit failed: %s", exc.stderr.decode() if exc.stderr else exc)
        return False


async def run_loop(config: RedPenConfig, fmt: str = "blog") -> None:
    """Run the full autoresearch loop until stopping conditions are met."""
    root = config.project_root
    fmt_config = get_format_config(config, fmt)

    # Load personas
    scoring_personas, reader_personas = load_personas(
        root, fmt_config.personas, fmt_config.readers,
    )

    if not scoring_personas:
        console.print("[red]No scoring personas loaded. Check your config and personas/ directory.[/red]")
        return

    # Track state for stuck detection
    discard_history: list[dict[str, Any]] = []
    prev_scores: dict[str, dict[str, dict[str, Any]]] | None = None
    baseline_scores: dict[str, dict[str, dict[str, Any]]] | None = None

    async def on_persona_complete(name: str, result_type: str) -> None:
        show_eval_progress(name, result_type)

    for iteration_num in range(1, config.stopping.max_iterations + 1):
        show_iteration_start(iteration_num)
        iteration = new_iteration(root)
        draft = current_draft(root)

        # --- Evaluate ---
        console.print("  Evaluating...", style="dim")
        eval_result = await evaluate_draft(
            config, draft, scoring_personas, reader_personas,
            on_persona_complete=on_persona_complete,
        )

        current_scores = eval_result["scores"]
        comments = eval_result["comments"]

        # Save raw results
        for persona, scores in current_scores.items():
            save_scores(root, iteration, persona, scores)
        for entry in comments:
            save_comments(
                root, iteration,
                entry["persona"], entry["comments"], entry["model"],
            )

        # Show results
        show_scores(current_scores, config.focus, prev_scores)
        show_comments(comments)
        stats = overall_stats(current_scores)
        show_overall_stats(stats)

        # --- First iteration: this is our baseline ---
        if baseline_scores is None:
            baseline_scores = current_scores
            prev_scores = current_scores

            summary: dict[str, Any] = {
                "iteration": iteration,
                "decision": "baseline",
                "stats": stats,
                "persona_means": aggregate_persona_scores(current_scores),
            }
            save_summary(root, iteration, summary)
            finalize_iteration(root, iteration, kept=True, reason="baseline evaluation")
            _git_commit(root, f"redpen: iteration {iteration} — baseline scores")

            # Check if we already meet the target
            if stats["min_score"] >= config.stopping.min_score_target:
                reason = f"min_score {stats['min_score']:.1f} >= target {config.stopping.min_score_target}"
                finish_run(root, reason)
                show_stop_reason(reason)
                return

        else:
            # --- For subsequent iterations, this was a post-edit evaluation ---
            # Decide keep/discard
            keep, reason = should_keep(
                prev_scores, current_scores,
                min_improvement=config.eval.min_improvement,
                mean_improvement=config.eval.mean_improvement,
            )
            show_decision(keep, reason)

            weaknesses = find_weaknesses(current_scores, config.focus)
            top_weakness = weaknesses[0] if weaknesses else {}

            summary = {
                "iteration": iteration,
                "decision": "kept" if keep else "discarded",
                "reason": reason,
                "stats": stats,
                "persona_means": aggregate_persona_scores(current_scores),
                "top_weakness": top_weakness,
            }
            save_summary(root, iteration, summary)

            if keep:
                prev_scores = current_scores
                finalize_iteration(root, iteration, kept=True, reason=reason)
                _git_commit(root, f"redpen: iteration {iteration} — kept ({reason})")
                discard_history.clear()
            else:
                # Revert draft to pre-edit version
                prev_draft_path = root / "data" / f"iter_{iteration:02d}" / "snapshot.md"
                if prev_draft_path.exists():
                    write_draft(root, prev_draft_path.read_text())
                finalize_iteration(root, iteration, kept=False, reason=reason)
                _git_commit(root, f"redpen: iteration {iteration} — discarded ({reason})")

                if top_weakness:
                    discard_history.append(top_weakness)

            # --- Check stopping conditions ---
            if keep and stats["min_score"] >= config.stopping.min_score_target:
                reason = f"min_score {stats['min_score']:.1f} >= target {config.stopping.min_score_target}"
                finish_run(root, reason)
                show_stop_reason(reason)
                return

        # --- Stuck detection ---
        stuck_weakness: str | None = None
        stuck_key = detect_stuck(discard_history)
        if stuck_key:
            show_stuck_warning(stuck_key)
            stuck_weakness = stuck_key
            discard_history.clear()

        # --- Write edit ---
        console.print("\n  Writing edit...", style="dim")
        try:
            edit = await generate_edit(
                config, current_draft(root),
                prev_scores or current_scores,
                comments,
                stuck_weakness=stuck_weakness,
            )
        except Exception:
            logger.exception("Writer agent failed")
            console.print("  [red]Writer agent failed, skipping iteration[/red]")
            continue

        show_edit_description(edit["description"])
        write_draft(root, edit["draft"])
        save_diff(root, iteration, edit["description"])

    # Max iterations reached
    reason = f"max iterations ({config.stopping.max_iterations}) reached"
    finish_run(root, reason)
    show_stop_reason(reason)
