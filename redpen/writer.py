"""Writer agent — generates surgical edits based on evaluation feedback.

Reads all evaluation scores, reader comments, voice config, goal, and focus
weights to produce one focused edit targeting the highest-impact weakness.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import anthropic

from redpen.config import RedPenConfig, load_goal, load_voice
from redpen.scorer import find_weaknesses

logger = logging.getLogger(__name__)

_TIMEOUT = 180.0


def _format_voice_config(voice: dict[str, Any]) -> str:
    """Format voice config into a readable string for the writer prompt."""
    parts: list[str] = []

    if "author" in voice:
        a = voice["author"]
        parts.append(f"Author: {a.get('name', '')} — {a.get('role', '')} at {a.get('company', '')}")
        if "background" in a:
            parts.append(f"Background: {a['background']}")

    if "tone" in voice:
        parts.append("\nTone spectrum (1-10):")
        for k, v in voice["tone"].items():
            label = k.replace("_vs_", " vs ").replace("_", " ").title()
            parts.append(f"  {label}: {v}")

    if "style" in voice:
        parts.append("\nStyle rules:")
        for k, v in voice["style"].items():
            parts.append(f"  {k}: {v}")

    if "rules" in voice:
        items = voice["rules"].get("items", voice["rules"].get("rules", []))
        if items:
            parts.append("\nWriting rules:")
            for r in items:
                parts.append(f"  - {r}")

    if "blacklist" in voice:
        words = voice["blacklist"].get("words", [])
        if words:
            parts.append(f"\nBlacklisted words/phrases (NEVER use these):\n  {', '.join(words)}")

    if "blacklist_patterns" in voice:
        items = voice["blacklist_patterns"].get("items", [])
        if items:
            parts.append("\nBlacklisted patterns:")
            for p in items:
                parts.append(f"  - {p}")

    return "\n".join(parts)


def _format_scores(
    persona_scores: dict[str, dict[str, dict[str, Any]]],
    focus: dict[str, int],
) -> str:
    """Format evaluation scores into a readable summary."""
    lines: list[str] = []
    total_focus = sum(focus.values()) or 1

    for persona, dims in sorted(persona_scores.items()):
        weight = focus.get(persona, 0)
        pct = (weight / total_focus) * 100
        lines.append(f"\n### {persona} (focus weight: {pct:.0f}%)")
        for dim, info in sorted(dims.items()):
            lines.append(f"  {dim}: {info['score']:.1f}/10")
            if info.get("reasoning"):
                lines.append(f"    Reasoning: {info['reasoning']}")

    return "\n".join(lines)


def _format_comments(comments: list[dict[str, Any]]) -> str:
    """Format reader comments into a readable summary."""
    if not comments:
        return "(No reader comments available)"

    lines: list[str] = []
    for entry in comments:
        persona = entry.get("persona", "unknown")
        model = entry.get("model", "unknown")
        lines.append(f"\n### {persona} ({model})")
        for i, comment in enumerate(entry.get("comments", []), 1):
            lines.append(f"  {i}. {comment}")

    return "\n".join(lines)


def _format_weaknesses(weaknesses: list[dict[str, Any]], top_n: int = 5) -> str:
    """Format top weaknesses for the writer."""
    if not weaknesses:
        return "(No weaknesses detected)"

    lines: list[str] = ["Top weaknesses by focus-weighted impact:"]
    for w in weaknesses[:top_n]:
        lines.append(
            f"  {w['persona']}:{w['dimension']} — "
            f"score={w['score']:.1f}, impact={w['impact']:.2f}"
        )
        if w.get("reasoning"):
            lines.append(f"    {w['reasoning']}")

    return "\n".join(lines)


def _build_writer_prompt(
    draft: str,
    persona_scores: dict[str, dict[str, dict[str, Any]]],
    comments: list[dict[str, Any]],
    voice: dict[str, Any],
    goal: str,
    focus: dict[str, int],
    writer_system: str,
    *,
    stuck_weakness: str | None = None,
) -> tuple[str, str]:
    """Build the system and user prompts for the writer agent.

    Returns (system_prompt, user_prompt).
    """
    weaknesses = find_weaknesses(persona_scores, focus)
    scores_text = _format_scores(persona_scores, focus)
    comments_text = _format_comments(comments)
    weakness_text = _format_weaknesses(weaknesses)
    voice_text = _format_voice_config(voice)

    stuck_note = ""
    if stuck_weakness:
        stuck_note = (
            f"\n\n**STUCK ALERT**: The last 3 edits targeting '{stuck_weakness}' were all "
            f"discarded. Try a DIFFERENT approach to this weakness — restructure, cut, "
            f"or address it from a completely different angle. Do not repeat what failed."
        )

    user_prompt = f"""# Current Draft

{draft}

---

# Evaluation Scores
{scores_text}

---

# Reader Comments
{comments_text}

---

# Weakness Analysis
{weakness_text}{stuck_note}

---

# Voice Config
{voice_text}

---

# Article Goal
{goal}

---

# Your Task

Make ONE focused edit targeting the highest-impact weakness above. Describe what you changed and why, then provide the complete updated draft.

**Output format:**

## Edit Description
[2-3 sentences: what you changed, why, which weakness it targets]

## Updated Draft
[The complete draft with your edit applied]"""

    return writer_system, user_prompt


async def generate_edit(
    config: RedPenConfig,
    draft: str,
    persona_scores: dict[str, dict[str, dict[str, Any]]],
    comments: list[dict[str, Any]],
    *,
    stuck_weakness: str | None = None,
) -> dict[str, str]:
    """Call the writer agent to generate one surgical edit.

    Returns {"description": str, "draft": str}.
    """
    voice = load_voice(config.project_root)
    goal = load_goal(config.project_root)

    # Load writer system prompt
    writer_prompt_path = config.project_root / "prompts" / "writer.md"
    if writer_prompt_path.exists():
        writer_system = writer_prompt_path.read_text()
    else:
        writer_system = "You are a professional writing editor. Make precise, surgical edits."

    system_prompt, user_prompt = _build_writer_prompt(
        draft, persona_scores, comments, voice, goal, config.focus,
        writer_system, stuck_weakness=stuck_weakness,
    )

    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        client_a = anthropic.AsyncAnthropic()
        try:
            response = await asyncio.wait_for(
                client_a.messages.create(
                    model=config.models.writer,
                    max_tokens=8192,
                    temperature=config.models.temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
                timeout=_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Writer agent timed out after {_TIMEOUT}s")
        raw = response.content[0].text
    elif os.environ.get("OPENAI_API_KEY"):
        import openai
        client_o = openai.AsyncOpenAI()
        try:
            response = await asyncio.wait_for(
                client_o.chat.completions.create(
                    model=config.models.secondary,
                    max_tokens=8192,
                    temperature=config.models.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                ),
                timeout=_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Writer agent timed out after {_TIMEOUT}s")
        raw = response.choices[0].message.content or ""
    else:
        raise RuntimeError("No API key available. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
    return _parse_writer_output(raw)


def _parse_writer_output(text: str) -> dict[str, str]:
    """Parse the writer's output into description and updated draft."""
    # Look for ## Edit Description and ## Updated Draft sections
    description = ""
    draft = ""

    # Split on ## headers
    import re
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)

    for section in sections:
        lower = section.lower()
        if lower.startswith("edit description"):
            description = section.split("\n", 1)[1].strip() if "\n" in section else ""
        elif lower.startswith("updated draft"):
            draft = section.split("\n", 1)[1].strip() if "\n" in section else ""

    if not draft:
        # Fallback: treat everything after the first description-like block as draft
        logger.warning("Could not parse writer output sections; using full text as draft")
        draft = text

    return {"description": description, "draft": draft}
