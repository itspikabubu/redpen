"""Async evaluation harness for multi-persona draft scoring.

Runs N personas in parallel using the Anthropic SDK (primary) and OpenAI SDK
(secondary, for reader comments). Parses structured scores, handles retries
with exponential backoff, and manages timeouts.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import anthropic
import openai

from redpen.config import RedPenConfig, load_goal, load_voice
from redpen.scorer import parse_scores

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona parsing
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"^##\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)


def parse_persona(path: Path) -> dict[str, str]:
    """Parse a persona .md file into sections.

    Returns a dict with keys like 'identity', 'rubric', 'dealbreaker',
    'how_you_comment', etc.  Keys are lowercased section titles with
    spaces replaced by underscores.
    """
    text = path.read_text()
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        title = m.group("title").strip().lower().replace(" ", "_")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[title] = body
    # Also store the full text and the persona name from line 1
    sections["_raw"] = text
    first_line = text.split("\n", 1)[0]
    name_match = re.match(r"#\s+Persona:\s*(.+)", first_line)
    sections["_name"] = name_match.group(1).strip() if name_match else path.stem
    return sections


def is_reader_persona(persona: dict[str, str]) -> bool:
    """Detect reader personas (no rubric section)."""
    return "rubric" not in persona


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_scoring_prompt(
    persona: dict[str, str],
    draft: str,
    goal: str,
) -> str:
    """Build the evaluation prompt for a scoring persona."""
    name = persona["_name"]
    identity = persona.get("identity", "")
    cares = persona.get("what_they_care_about", "")
    value_prop = persona.get("value_proposition_lens", "")
    rubric = persona.get("rubric", "")
    dealbreaker = persona.get("dealbreaker", "")

    return f"""You are evaluating a piece of writing as the following persona.

# Persona: {name}

## Identity
{identity}

## What they care about
{cares}

## Value proposition lens
{value_prop}

## Rubric
{rubric}

## Dealbreaker
{dealbreaker}

---

# Article Goal
{goal}

---

# Draft to Evaluate

{draft}

---

# Instructions

Evaluate this draft from the perspective of your persona. For each dimension in your rubric:

1. Quote a specific passage from the draft (1-2 sentences) that is most relevant to this dimension.
2. Explain your reasoning in 2-3 sentences.
3. Assign a score from 0-10.

**Output format** — one line per dimension, exactly like this:

DIMENSION_NAME: [your reasoning, referencing specific passages] -> [integer score]

For example:
Founder empathy: The opening paragraph references "debugging auth at 2am" which shows real builder understanding, but the middle section lapses into generic VC advice that any associate could write -> 6

Score every dimension in your rubric. Be specific and honest. Do not inflate scores."""


def _build_reader_prompt(
    persona: dict[str, str],
    draft: str,
    goal: str,
) -> str:
    """Build the comment-generation prompt for a reader persona."""
    name = persona["_name"]
    identity = persona.get("identity", "")
    how = persona.get("how_you_comment", persona.get("how_you_react", ""))
    comment_types = persona.get("comment_types_you_might_write", "")
    reaction_types = persona.get("reaction_types_you_might_write", "")
    neg = persona.get("what_triggers_you_negatively", persona.get("what_makes_you_dunk", ""))
    pos = persona.get("what_earns_your_respect", persona.get("what_makes_you_quote-tweet_positively", ""))

    types_section = comment_types or reaction_types

    return f"""You are reacting to a piece of writing as the following persona.

# Persona: {name}

## Identity
{identity}

## How you comment
{how}

## Types of reactions you might write
{types_section}

## What triggers you negatively
{neg}

## What earns your respect
{pos}

---

# Article Goal (context only — you don't know this as a reader)
{goal}

---

# The Post

{draft}

---

# Instructions

Write exactly 3 reactions/comments in character. Each should be:
- A distinct reaction (not three versions of the same take)
- Written in your authentic voice
- 1-5 sentences each

Separate each comment with a blank line. Do NOT number them or add labels."""


# ---------------------------------------------------------------------------
# API call helpers with retry
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_TIMEOUT = 120.0


async def _call_anthropic(
    client: anthropic.AsyncAnthropic,
    model: str,
    prompt: str,
    temperature: float,
) -> str:
    """Call the Anthropic API with retry and backoff."""
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=4096,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=_TIMEOUT,
            )
            return response.content[0].text
        except (anthropic.APIError, asyncio.TimeoutError) as exc:
            last_error = exc
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Anthropic API attempt %d/%d failed: %s. Retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"Anthropic API failed after {_MAX_RETRIES} retries: {last_error}")


async def _call_openai(
    client: openai.AsyncOpenAI,
    model: str,
    prompt: str,
    temperature: float,
) -> str:
    """Call the OpenAI API with retry and backoff."""
    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    max_tokens=4096,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=_TIMEOUT,
            )
            return response.choices[0].message.content or ""
        except (openai.APIError, asyncio.TimeoutError) as exc:
            last_error = exc
            delay = _BASE_DELAY * (2 ** attempt)
            logger.warning(
                "OpenAI API attempt %d/%d failed: %s. Retrying in %.1fs",
                attempt + 1, _MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"OpenAI API failed after {_MAX_RETRIES} retries: {last_error}")


# ---------------------------------------------------------------------------
# Single persona evaluation
# ---------------------------------------------------------------------------

async def _evaluate_persona_once(
    client: anthropic.AsyncAnthropic,
    model: str,
    persona: dict[str, str],
    draft: str,
    goal: str,
    temperature: float,
) -> dict[str, dict[str, Any]]:
    """Run a single scoring evaluation for one persona. Returns parsed scores."""
    prompt = _build_scoring_prompt(persona, draft, goal)
    raw = await _call_anthropic(client, model, prompt, temperature)
    scores = parse_scores(raw)
    if not scores:
        logger.warning(
            "Failed to parse scores for persona %s. Raw output:\n%s",
            persona["_name"], raw[:500],
        )
    return scores


async def _generate_reader_comments(
    client_anthropic: anthropic.AsyncAnthropic | None,
    client_openai: openai.AsyncOpenAI | None,
    persona: dict[str, str],
    draft: str,
    goal: str,
    primary_model: str,
    secondary_model: str,
    temperature: float,
) -> list[dict[str, Any]]:
    """Generate reader comments using both primary and secondary models."""
    prompt = _build_reader_prompt(persona, draft, goal)
    results: list[dict[str, Any]] = []

    tasks: list[asyncio.Task[tuple[str, str]]] = []

    async def _run_anthropic() -> tuple[str, str]:
        assert client_anthropic is not None
        text = await _call_anthropic(client_anthropic, primary_model, prompt, temperature)
        return text, "anthropic"

    async def _run_openai() -> tuple[str, str]:
        assert client_openai is not None
        text = await _call_openai(client_openai, secondary_model, prompt, temperature)
        return text, "openai"

    if client_anthropic:
        tasks.append(asyncio.create_task(_run_anthropic()))
    if client_openai:
        tasks.append(asyncio.create_task(_run_openai()))

    for coro in asyncio.as_completed(tasks):
        try:
            text, source = await coro
            comments = _parse_comments(text)
            results.append({
                "persona": persona["_name"],
                "model": source,
                "comments": comments,
            })
        except Exception:
            logger.exception("Reader comment generation failed for %s", persona["_name"])

    return results


def _parse_comments(text: str) -> list[str]:
    """Split raw comment output into individual comments."""
    # Split on double newlines, filter empty
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Full evaluation run
# ---------------------------------------------------------------------------

async def evaluate_draft(
    config: RedPenConfig,
    draft: str,
    scoring_personas: list[tuple[str, dict[str, str]]],
    reader_personas: list[tuple[str, dict[str, str]]],
    *,
    on_persona_complete: Any | None = None,
) -> dict[str, Any]:
    """Run full evaluation: all scoring personas (N runs each) + reader comments.

    Args:
        config: RedPen configuration.
        draft: The draft text to evaluate.
        scoring_personas: List of (name, parsed_persona) for scoring.
        reader_personas: List of (name, parsed_persona) for comments.
        on_persona_complete: Optional async callback(persona_name, result_type).

    Returns:
        {
            "scores": {persona: {dimension: {score, reasoning}}},
            "comments": [{persona, model, comments}],
        }
    """
    goal = load_goal(config.project_root)

    # Initialize API clients
    client_anthropic: anthropic.AsyncAnthropic | None = None
    client_openai: openai.AsyncOpenAI | None = None

    try:
        client_anthropic = anthropic.AsyncAnthropic()
    except Exception:
        logger.warning("Anthropic client initialization failed; skipping Anthropic evals")

    try:
        client_openai = openai.AsyncOpenAI()
    except Exception:
        logger.warning("OpenAI client initialization failed; skipping OpenAI evals")

    if not client_anthropic and not client_openai:
        raise RuntimeError(
            "No API clients available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
        )

    # --- Scoring personas: N runs each, all in parallel ---
    from redpen.scorer import median_scores

    async def _score_persona(
        name: str, persona: dict[str, str],
    ) -> tuple[str, dict[str, dict[str, Any]]]:
        runs: list[dict[str, dict[str, Any]]] = []
        tasks = []
        for _ in range(config.eval.runs):
            if client_anthropic:
                tasks.append(
                    _evaluate_persona_once(
                        client_anthropic,
                        config.models.primary,
                        persona,
                        draft,
                        goal,
                        config.models.temperature,
                    )
                )
            elif client_openai:
                # Fallback: use OpenAI for scoring if no Anthropic
                async def _openai_score() -> dict[str, dict[str, Any]]:
                    prompt = _build_scoring_prompt(persona, draft, goal)
                    raw = await _call_openai(
                        client_openai, config.models.secondary, prompt,  # type: ignore[arg-type]
                        config.models.temperature,
                    )
                    return parse_scores(raw)
                tasks.append(_openai_score())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, dict) and r:
                runs.append(r)
            elif isinstance(r, Exception):
                logger.warning("Scoring run failed for %s: %s", name, r)

        medians = median_scores(runs) if runs else {}
        if on_persona_complete:
            await on_persona_complete(name, "scores")
        return name, medians

    # --- Reader personas: comments from both models ---
    async def _read_persona(
        name: str, persona: dict[str, str],
    ) -> tuple[str, list[dict[str, Any]]]:
        comments = await _generate_reader_comments(
            client_anthropic, client_openai,
            persona, draft, goal,
            config.models.primary, config.models.secondary,
            config.models.temperature,
        )
        if on_persona_complete:
            await on_persona_complete(name, "comments")
        return name, comments

    # Launch all tasks
    score_tasks = [_score_persona(n, p) for n, p in scoring_personas]
    reader_tasks = [_read_persona(n, p) for n, p in reader_personas]

    all_results = await asyncio.gather(
        *score_tasks, *reader_tasks, return_exceptions=True,
    )

    # Collect results
    scores: dict[str, dict[str, dict[str, Any]]] = {}
    comments: list[dict[str, Any]] = []

    n_scorers = len(score_tasks)
    for i, result in enumerate(all_results):
        if isinstance(result, Exception):
            logger.error("Evaluation task failed: %s", result)
            continue
        if i < n_scorers:
            name, persona_scores = result
            if persona_scores:
                scores[name] = persona_scores
        else:
            _name, persona_comments = result
            comments.extend(persona_comments)

    return {"scores": scores, "comments": comments}


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------

def load_personas(
    root: Path,
    persona_names: list[str],
    reader_names: list[str],
) -> tuple[list[tuple[str, dict[str, str]]], list[tuple[str, dict[str, str]]]]:
    """Load and parse persona files.

    Returns (scoring_personas, reader_personas) as lists of (name, parsed_dict).
    """
    personas_dir = root / "personas"
    scoring: list[tuple[str, dict[str, str]]] = []
    readers: list[tuple[str, dict[str, str]]] = []

    for name in persona_names:
        path = personas_dir / f"{name}.md"
        if not path.exists():
            logger.warning("Persona file not found: %s", path)
            continue
        parsed = parse_persona(path)
        if is_reader_persona(parsed):
            logger.warning("Persona %s has no rubric, treating as reader", name)
            readers.append((name, parsed))
        else:
            scoring.append((name, parsed))

    for name in reader_names:
        path = personas_dir / f"{name}.md"
        if not path.exists():
            logger.warning("Reader persona file not found: %s", path)
            continue
        parsed = parse_persona(path)
        readers.append((name, parsed))

    return scoring, readers
