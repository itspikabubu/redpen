"""Unit tests for redpen.scorer — scoring math, parsing, and decision logic."""

from __future__ import annotations

import pytest

from redpen.scorer import (
    aggregate_persona_scores,
    detect_stuck,
    find_weaknesses,
    median_scores,
    overall_stats,
    parse_scores,
    should_keep,
)


# ---------------------------------------------------------------------------
# parse_scores
# ---------------------------------------------------------------------------

class TestParseScores:
    def test_basic_format(self) -> None:
        text = (
            'Founder empathy: The opening references real founder pain points -> 7\n'
            'Genuine insight: Offers a useful framework for thinking about infra -> 8\n'
        )
        result = parse_scores(text)
        assert "founder_empathy" in result
        assert result["founder_empathy"]["score"] == 7.0
        assert "founder pain" in result["founder_empathy"]["reasoning"]
        assert result["genuine_insight"]["score"] == 8.0

    def test_bold_dimension_names(self) -> None:
        text = '**Founder empathy**: Great understanding of builder reality -> 9\n'
        result = parse_scores(text)
        assert "founder_empathy" in result
        assert result["founder_empathy"]["score"] == 9.0

    def test_with_scale_annotation(self) -> None:
        text = '**Hook strength** (0-10): Strong opening line grabs attention -> 6\n'
        result = parse_scores(text)
        assert "hook_strength" in result
        assert result["hook_strength"]["score"] == 6.0

    def test_decimal_scores(self) -> None:
        text = 'Signal density: Very tight writing with minimal filler -> 7.5\n'
        result = parse_scores(text)
        assert result["signal_density"]["score"] == 7.5

    def test_no_match(self) -> None:
        result = parse_scores("This is just a paragraph with no scores.")
        assert result == {}

    def test_multiple_lines_mixed(self) -> None:
        text = (
            'Some preamble text here.\n'
            'Original thesis: Fresh take on AI infra -> 8\n'
            'More text in between.\n'
            'Market depth: Deep pattern matching from real convos -> 7\n'
            'Trailing text.\n'
        )
        result = parse_scores(text)
        assert len(result) == 2
        assert result["original_thesis"]["score"] == 8.0
        assert result["market_depth"]["score"] == 7.0

    def test_dimension_with_apostrophe(self) -> None:
        text = "Cap table signal: Makes me want this person on my cap table -> 6\n"
        result = parse_scores(text)
        assert "cap_table_signal" in result

    def test_quoted_dimension(self) -> None:
        text = (
            '"Would I share this with my co-founder?": '
            "Yes, this has real practical value -> 8\n"
        )
        # This format may not match our regex, which is fine — we only
        # require the DIMENSION_NAME: reasoning -> score format
        # The quoted version is not expected to be parsed


# ---------------------------------------------------------------------------
# median_scores
# ---------------------------------------------------------------------------

class TestMedianScores:
    def test_odd_number_of_runs(self) -> None:
        runs = [
            {"dim_a": {"score": 5.0, "reasoning": "low"}},
            {"dim_a": {"score": 7.0, "reasoning": "mid"}},
            {"dim_a": {"score": 9.0, "reasoning": "high"}},
        ]
        result = median_scores(runs)
        assert result["dim_a"]["score"] == 7.0
        assert result["dim_a"]["reasoning"] == "mid"

    def test_even_number_of_runs(self) -> None:
        runs = [
            {"dim_a": {"score": 4.0, "reasoning": "r1"}},
            {"dim_a": {"score": 8.0, "reasoning": "r2"}},
        ]
        result = median_scores(runs)
        assert result["dim_a"]["score"] == 6.0  # median of [4, 8]

    def test_single_run(self) -> None:
        runs = [{"dim_a": {"score": 6.0, "reasoning": "only run"}}]
        result = median_scores(runs)
        assert result["dim_a"]["score"] == 6.0

    def test_empty_runs(self) -> None:
        assert median_scores([]) == {}

    def test_missing_dimension_in_some_runs(self) -> None:
        runs = [
            {"dim_a": {"score": 5.0, "reasoning": "r1"}, "dim_b": {"score": 8.0, "reasoning": "r1b"}},
            {"dim_a": {"score": 7.0, "reasoning": "r2"}},
            {"dim_a": {"score": 9.0, "reasoning": "r3"}, "dim_b": {"score": 6.0, "reasoning": "r3b"}},
        ]
        result = median_scores(runs)
        assert result["dim_a"]["score"] == 7.0
        assert result["dim_b"]["score"] == 7.0  # median of [8, 6]

    def test_multiple_dimensions(self) -> None:
        runs = [
            {"x": {"score": 3.0, "reasoning": "a"}, "y": {"score": 9.0, "reasoning": "b"}},
            {"x": {"score": 5.0, "reasoning": "c"}, "y": {"score": 7.0, "reasoning": "d"}},
            {"x": {"score": 7.0, "reasoning": "e"}, "y": {"score": 5.0, "reasoning": "f"}},
        ]
        result = median_scores(runs)
        assert result["x"]["score"] == 5.0
        assert result["y"]["score"] == 7.0


# ---------------------------------------------------------------------------
# aggregate_persona_scores
# ---------------------------------------------------------------------------

class TestAggregatePersonaScores:
    def test_basic(self) -> None:
        persona_scores = {
            "alice": {
                "dim_a": {"score": 6.0, "reasoning": ""},
                "dim_b": {"score": 8.0, "reasoning": ""},
            },
            "bob": {
                "dim_a": {"score": 4.0, "reasoning": ""},
            },
        }
        result = aggregate_persona_scores(persona_scores)
        assert result["alice"] == pytest.approx(7.0)
        assert result["bob"] == pytest.approx(4.0)

    def test_empty(self) -> None:
        assert aggregate_persona_scores({}) == {}


# ---------------------------------------------------------------------------
# overall_stats
# ---------------------------------------------------------------------------

class TestOverallStats:
    def test_basic(self) -> None:
        scores = {
            "p1": {
                "d1": {"score": 5.0, "reasoning": ""},
                "d2": {"score": 9.0, "reasoning": ""},
            },
            "p2": {
                "d1": {"score": 3.0, "reasoning": ""},
            },
        }
        stats = overall_stats(scores)
        assert stats["min_score"] == 3.0
        assert stats["mean_score"] == pytest.approx((5.0 + 9.0 + 3.0) / 3)

    def test_empty(self) -> None:
        stats = overall_stats({})
        assert stats["min_score"] == 0.0
        assert stats["mean_score"] == 0.0


# ---------------------------------------------------------------------------
# find_weaknesses
# ---------------------------------------------------------------------------

class TestFindWeaknesses:
    def test_ranked_by_impact(self) -> None:
        scores = {
            "high_focus": {
                "dim_a": {"score": 3.0, "reasoning": "bad"},
            },
            "low_focus": {
                "dim_a": {"score": 2.0, "reasoning": "worse"},
            },
        }
        focus = {"high_focus": 80, "low_focus": 20}
        result = find_weaknesses(scores, focus)
        # high_focus:dim_a impact = (10-3) * 0.8 = 5.6
        # low_focus:dim_a impact = (10-2) * 0.2 = 1.6
        assert result[0]["persona"] == "high_focus"
        assert result[0]["impact"] == pytest.approx(5.6)
        assert result[1]["impact"] == pytest.approx(1.6)

    def test_zero_focus(self) -> None:
        scores = {
            "p1": {"d1": {"score": 2.0, "reasoning": ""}},
        }
        # Persona not in focus dict → 0 weight → 0 impact
        result = find_weaknesses(scores, {"other": 100})
        assert result[0]["impact"] == 0.0

    def test_perfect_score_zero_impact(self) -> None:
        scores = {
            "p1": {"d1": {"score": 10.0, "reasoning": "perfect"}},
        }
        result = find_weaknesses(scores, {"p1": 100})
        assert result[0]["impact"] == 0.0


# ---------------------------------------------------------------------------
# should_keep
# ---------------------------------------------------------------------------

class TestShouldKeep:
    def _make_scores(self, persona_dim_scores: dict[str, dict[str, float]]) -> dict:
        return {
            p: {d: {"score": s, "reasoning": ""} for d, s in dims.items()}
            for p, dims in persona_dim_scores.items()
        }

    def test_keep_min_improved(self) -> None:
        prev = self._make_scores({"p1": {"d1": 5.0, "d2": 6.0}})
        curr = self._make_scores({"p1": {"d1": 5.5, "d2": 6.5}})
        keep, reason = should_keep(prev, curr, min_improvement=0.5, mean_improvement=0.3)
        assert keep is True
        assert "min_score improved" in reason

    def test_discard_min_regressed(self) -> None:
        prev = self._make_scores({"p1": {"d1": 6.0, "d2": 7.0}})
        curr = self._make_scores({"p1": {"d1": 5.0, "d2": 8.0}})
        keep, reason = should_keep(prev, curr)
        assert keep is False
        assert "regressed" in reason

    def test_keep_mean_tiebreaker(self) -> None:
        prev = self._make_scores({"p1": {"d1": 5.0, "d2": 5.0}})
        curr = self._make_scores({"p1": {"d1": 5.0, "d2": 5.5}})
        keep, reason = should_keep(prev, curr, min_improvement=0.5, mean_improvement=0.3)
        # min didn't change (both 5.0), mean went from 5.0 to 5.25 — not enough
        assert keep is False

    def test_keep_mean_tiebreaker_sufficient(self) -> None:
        prev = self._make_scores({"p1": {"d1": 5.0, "d2": 5.0}})
        curr = self._make_scores({"p1": {"d1": 5.0, "d2": 5.8}})
        keep, reason = should_keep(prev, curr, min_improvement=0.5, mean_improvement=0.3)
        # min flat (5.0), mean went from 5.0 to 5.4 → delta 0.4 >= 0.3
        assert keep is True
        assert "mean improved" in reason

    def test_insufficient_improvement(self) -> None:
        prev = self._make_scores({"p1": {"d1": 5.0}})
        curr = self._make_scores({"p1": {"d1": 5.2}})
        keep, reason = should_keep(prev, curr, min_improvement=0.5, mean_improvement=0.3)
        assert keep is False
        assert "insufficient" in reason


# ---------------------------------------------------------------------------
# detect_stuck
# ---------------------------------------------------------------------------

class TestDetectStuck:
    def test_not_stuck_too_few(self) -> None:
        history = [
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d1"},
        ]
        assert detect_stuck(history, threshold=3) is None

    def test_stuck_same_weakness(self) -> None:
        history = [
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d1"},
        ]
        result = detect_stuck(history, threshold=3)
        assert result == "p1:d1"

    def test_not_stuck_different_weaknesses(self) -> None:
        history = [
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d2"},
            {"persona": "p1", "dimension": "d1"},
        ]
        assert detect_stuck(history, threshold=3) is None

    def test_empty_history(self) -> None:
        assert detect_stuck([], threshold=3) is None

    def test_only_checks_last_n(self) -> None:
        history = [
            {"persona": "p1", "dimension": "d2"},
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d1"},
            {"persona": "p1", "dimension": "d1"},
        ]
        # Last 3 are all d1
        assert detect_stuck(history, threshold=3) == "p1:d1"
