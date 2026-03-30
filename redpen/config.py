"""Configuration loading, validation, and CLI-arg merging."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ModelsConfig:
    primary: str = "claude-sonnet-4-20250514"
    secondary: str = "gpt-4o"
    writer: str = "claude-sonnet-4-20250514"
    temperature: float = 0.7


@dataclass
class EvalConfig:
    runs: int = 3
    min_improvement: float = 0.5
    mean_improvement: float = 0.3


@dataclass
class StoppingConfig:
    min_score_target: float = 7.5
    max_iterations: int = 25


@dataclass
class FormatConfig:
    max_words: int | None = None
    min_words: int | None = None
    max_chars: int | None = None
    min_chars: int | None = None
    max_chars_per_tweet: int | None = None
    max_tweets: int | None = None
    hook_required: bool = False
    personas: list[str] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)


@dataclass
class RedPenConfig:
    models: ModelsConfig = field(default_factory=ModelsConfig)
    eval: EvalConfig = field(default_factory=EvalConfig)
    stopping: StoppingConfig = field(default_factory=StoppingConfig)
    focus: dict[str, int] = field(default_factory=dict)
    formats: dict[str, FormatConfig] = field(default_factory=dict)
    project_root: Path = field(default_factory=lambda: Path.cwd())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_format(raw: dict[str, Any]) -> FormatConfig:
    return FormatConfig(
        max_words=raw.get("max_words"),
        min_words=raw.get("min_words"),
        max_chars=raw.get("max_chars"),
        min_chars=raw.get("min_chars"),
        max_chars_per_tweet=raw.get("max_chars_per_tweet"),
        max_tweets=raw.get("max_tweets"),
        hook_required=raw.get("hook_required", False),
        personas=raw.get("personas", []),
        readers=raw.get("readers", []),
    )


def load_config(path: Path | None = None, overrides: dict[str, Any] | None = None) -> RedPenConfig:
    """Load config.toml, apply CLI overrides, return validated config."""
    root = Path.cwd()
    if path is None:
        path = root / "config.toml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    cfg = RedPenConfig(project_root=root)

    # Models
    if "models" in raw:
        m = raw["models"]
        cfg.models = ModelsConfig(
            primary=m.get("primary", cfg.models.primary),
            secondary=m.get("secondary", cfg.models.secondary),
            writer=m.get("writer", cfg.models.writer),
            temperature=m.get("temperature", cfg.models.temperature),
        )

    # Eval
    if "eval" in raw:
        e = raw["eval"]
        cfg.eval = EvalConfig(
            runs=e.get("runs", cfg.eval.runs),
            min_improvement=e.get("min_improvement", cfg.eval.min_improvement),
            mean_improvement=e.get("mean_improvement", cfg.eval.mean_improvement),
        )

    # Stopping
    if "stopping" in raw:
        s = raw["stopping"]
        cfg.stopping = StoppingConfig(
            min_score_target=s.get("min_score_target", cfg.stopping.min_score_target),
            max_iterations=s.get("max_iterations", cfg.stopping.max_iterations),
        )

    # Focus
    cfg.focus = raw.get("focus", {})

    # Formats
    if "formats" in raw:
        for name, fmt_raw in raw["formats"].items():
            cfg.formats[name] = _build_format(fmt_raw)

    # CLI overrides
    if overrides:
        if "max_iterations" in overrides and overrides["max_iterations"] is not None:
            cfg.stopping.max_iterations = overrides["max_iterations"]
        if "model" in overrides and overrides["model"] is not None:
            cfg.models.primary = overrides["model"]
            cfg.models.writer = overrides["model"]

    return cfg


def get_format_config(cfg: RedPenConfig, fmt: str) -> FormatConfig:
    """Return format config, falling back to blog defaults."""
    if fmt in cfg.formats:
        return cfg.formats[fmt]
    if "blog" in cfg.formats:
        return cfg.formats["blog"]
    return FormatConfig(
        personas=["seed_founder", "fellow_gp", "lp_allocator", "linkedin_reader"],
        readers=["hn_reader", "x_reader"],
    )


def load_voice(root: Path | None = None) -> dict[str, Any]:
    """Load voice/default.toml and return raw dict."""
    if root is None:
        root = Path.cwd()
    path = root / "voice" / "default.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_goal(root: Path | None = None) -> str:
    """Load goal.md as text."""
    if root is None:
        root = Path.cwd()
    path = root / "goal.md"
    if not path.exists():
        return ""
    return path.read_text()
