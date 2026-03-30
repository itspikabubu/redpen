"""Scoring math: medians, focus-weighted weakness detection, keep/discard logic."""

from __future__ import annotations

import re
import statistics
from typing import Any


# ---------------------------------------------------------------------------
# Score parsing
# ---------------------------------------------------------------------------

# Expected format from evaluator:  DIMENSION_NAME: [reasoning text] -> [integer score]
_SCORE_LINE_RE = re.compile(
    r"^\s*\*?\*?(?P<dimension>[A-Za-z][A-Za-z _/'-]+?)\*?\*?"
    r"\s*(?:\(0-10\))?\s*:\s*"
    r"(?P<reasoning>.+?)\s*->\s*(?P<score>\d+(?:\.\d+)?)\s*$",
    re.MULTILINE,
)


def parse_scores(text: str) -> dict[str, dict[str, Any]]:
    """Parse evaluator output into {dimension: {score, reasoning}}."""
    results: dict[str, dict[str, Any]] = {}
    for m in _SCORE_LINE_RE.finditer(text):
        dim = m.group("dimension").strip().lower().replace(" ", "_")
        score = float(m.group("score"))
        reasoning = m.group("reasoning").strip()
        results[dim] = {"score": score, "reasoning": reasoning}
    return results


# ---------------------------------------------------------------------------
# Median aggregation
# ---------------------------------------------------------------------------

def median_scores(runs: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Compute median score per dimension across multiple runs.

    Each run is {dimension: {score, reasoning}}.
    Returns {dimension: {score (median), reasoning (from median run)}}.
    """
    if not runs:
        return {}

    # Gather all dimensions
    all_dims: set[str] = set()
    for run in runs:
        all_dims.update(run.keys())

    result: dict[str, dict[str, Any]] = {}
    for dim in sorted(all_dims):
        entries = [(run[dim]["score"], run[dim]["reasoning"]) for run in runs if dim in run]
        if not entries:
            continue
        scores = [e[0] for e in entries]
        med = statistics.median(scores)
        # Pick the reasoning from the run closest to the median
        closest = min(entries, key=lambda e: abs(e[0] - med))
        result[dim] = {"score": med, "reasoning": closest[1]}

    return result


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------

def aggregate_persona_scores(
    persona_scores: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, float]:
    """Compute per-persona mean from {persona: {dimension: {score, reasoning}}}.

    Returns {persona: mean_score}.
    """
    result: dict[str, float] = {}
    for persona, dims in persona_scores.items():
        scores = [d["score"] for d in dims.values()]
        result[persona] = statistics.mean(scores) if scores else 0.0
    return result


def overall_stats(
    persona_scores: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, float]:
    """Compute overall min_score and mean_score across all personas/dimensions."""
    all_scores: list[float] = []
    for dims in persona_scores.values():
        for d in dims.values():
            all_scores.append(d["score"])
    if not all_scores:
        return {"min_score": 0.0, "mean_score": 0.0}
    return {
        "min_score": min(all_scores),
        "mean_score": statistics.mean(all_scores),
    }


# ---------------------------------------------------------------------------
# Focus-weighted weakness detection
# ---------------------------------------------------------------------------

def find_weaknesses(
    persona_scores: dict[str, dict[str, dict[str, Any]]],
    focus: dict[str, int],
) -> list[dict[str, Any]]:
    """Find weaknesses ranked by focus-weighted impact.

    Returns sorted list of {persona, dimension, score, weight, impact}.
    Impact = (10 - score) * weight / 100.
    """
    weaknesses: list[dict[str, Any]] = []
    total_focus = sum(focus.values()) or 1

    for persona, dims in persona_scores.items():
        weight = focus.get(persona, 0) / total_focus
        for dim, info in dims.items():
            score = info["score"]
            impact = (10.0 - score) * weight
            weaknesses.append({
                "persona": persona,
                "dimension": dim,
                "score": score,
                "weight": weight,
                "impact": impact,
                "reasoning": info.get("reasoning", ""),
            })

    weaknesses.sort(key=lambda w: w["impact"], reverse=True)
    return weaknesses


# ---------------------------------------------------------------------------
# Keep / discard decision
# ---------------------------------------------------------------------------

def should_keep(
    prev_scores: dict[str, dict[str, dict[str, Any]]],
    new_scores: dict[str, dict[str, dict[str, Any]]],
    *,
    min_improvement: float = 0.5,
    mean_improvement: float = 0.3,
) -> tuple[bool, str]:
    """Decide whether to keep a new draft based on score changes.

    Primary: min_score must improve by >= min_improvement.
    Tiebreaker: if min_score is flat, mean must improve by >= mean_improvement.
    Returns (keep: bool, reason: str).
    """
    prev = overall_stats(prev_scores)
    curr = overall_stats(new_scores)

    min_delta = curr["min_score"] - prev["min_score"]
    mean_delta = curr["mean_score"] - prev["mean_score"]

    if min_delta >= min_improvement:
        return True, f"min_score improved by {min_delta:+.2f} (>= {min_improvement})"

    if min_delta > -0.01 and mean_delta >= mean_improvement:
        return True, f"min_score flat ({min_delta:+.2f}), mean improved by {mean_delta:+.2f} (>= {mean_improvement})"

    if min_delta < -0.01:
        return False, f"min_score regressed by {min_delta:+.2f}"

    return False, f"insufficient improvement: min_delta={min_delta:+.2f}, mean_delta={mean_delta:+.2f}"


# ---------------------------------------------------------------------------
# Stuck detection
# ---------------------------------------------------------------------------

def detect_stuck(
    discard_history: list[dict[str, Any]],
    *,
    threshold: int = 3,
) -> str | None:
    """Check if the last N discards targeted the same weakness.

    Returns the stuck weakness key (persona:dimension) or None.
    """
    if len(discard_history) < threshold:
        return None

    recent = discard_history[-threshold:]
    keys = [f"{d['persona']}:{d['dimension']}" for d in recent if "persona" in d and "dimension" in d]
    if len(keys) == threshold and len(set(keys)) == 1:
        return keys[0]
    return None
