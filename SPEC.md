# RedPen — Build Specification

## What This Is

A standalone Python CLI that implements the "autoresearch for prose" pattern: iterative AI evaluation + editing loop where drafts can only get better, never worse. Inspired by [ghostwriter](https://github.com/leozc/ghostwriters) but built from scratch with significant improvements.

## Key Differentiators from Ghostwriter

1. **Standalone CLI** — runs via `redpen run draft.md`, no Claude Code/Codex CLI dependency. Direct Anthropic + OpenAI API calls with async parallel evaluation.
2. **Multi-format** — `--format blog|linkedin|thread` selects format-specific persona presets and constraints (character limits, hook requirements, etc.)
3. **Author voice deeply integrated** — Leo's specific writing rules, phrase blacklist, and tone preferences baked into writer agent config.
4. **Better personas** — tailored for VC/thought leadership audience (LPs, founders, fellow GPs, LinkedIn readers, VC Twitter), not dev-tools startups.
5. **Rich terminal dashboard** — live progress via `rich`, not just log lines.
6. **Export pipeline** — `redpen export` produces final draft + full changelog.

## Architecture

```
redpen/
├── README.md
├── pyproject.toml           # uv/pip project, entry point: redpen
├── config.toml              # Default config (models, thresholds, focus points)
├── Makefile                 # Convenience commands
├── redpen/
│   ├── __init__.py
│   ├── cli.py               # Click-based CLI: run, status, export, init
│   ├── loop.py              # Main autoresearch loop orchestrator
│   ├── evaluate.py          # Async evaluation harness (Anthropic + OpenAI)
│   ├── writer.py            # Writer agent (makes surgical edits)
│   ├── scorer.py            # Scoring math (medians, aggregates, focus weighting)
│   ├── data.py              # Iteration data management (snapshots, manifests)
│   ├── config.py            # Config loading + validation
│   ├── export.py            # Export final draft + changelog
│   └── display.py           # Rich terminal output + dashboard
├── personas/
│   ├── _template.md         # Template for creating new personas
│   ├── seed_founder.md      # Seed-stage founder reading your content
│   ├── fellow_gp.md         # Fellow VC partner
│   ├── lp_allocator.md      # LP / fund allocator
│   ├── linkedin_reader.md   # LinkedIn power user / fast scroller
│   ├── hn_reader.md         # HN skeptic (reader, not scorer — writes comments)
│   └── x_reader.md          # VC/tech Twitter (reader, not scorer — writes reactions)
├── voice/
│   └── default.toml         # Author voice config (Leo's rules pre-loaded)
├── prompts/
│   ├── writer.md            # Writer agent system prompt
│   └── evaluate.md          # Evaluation protocol reference
├── goal.md                  # Article goal (user edits per post)
└── tests/
    ├── test_scorer.py       # Scoring math tests
    └── test_data.py         # Data management tests
```

## CLI Interface

```bash
# Initialize a new run from a draft
redpen init draft.md --format blog --tag "ai-agents-mar30"

# Run the optimization loop (autonomous)
redpen run --max-iterations 20

# Check iteration history
redpen status

# Export final draft + changelog
redpen export --output final.md

# One-shot: init + run in one command
redpen go draft.md --format blog --max-iterations 15
```

## Config (config.toml)

```toml
[models]
primary = "claude-sonnet-4-20250514"        # Primary evaluator model (cheaper, fast)
secondary = "gpt-4o"                        # Secondary evaluator (different perspective)  
writer = "claude-sonnet-4-20250514"          # Writer agent model
temperature = 0.7

[eval]
runs = 3                              # Evaluations per persona (median for noise)
min_improvement = 0.5                 # min_score must improve by this to keep
mean_improvement = 0.3                # mean_score tiebreaker threshold

[stopping]
min_score_target = 7.5                # Stop when min_score >= this
max_iterations = 25                   # Hard stop

[focus]
# Distribute 100 points. Keys = persona filenames (without .md)
seed_founder = 25
fellow_gp = 30
lp_allocator = 25
linkedin_reader = 20

[formats.blog]
max_words = 3000
min_words = 800
personas = ["seed_founder", "fellow_gp", "lp_allocator", "linkedin_reader"]
readers = ["hn_reader", "x_reader"]

[formats.linkedin]
max_chars = 3000
min_chars = 500
hook_required = true                  # First line must be a hook
personas = ["linkedin_reader", "fellow_gp", "seed_founder"]
readers = ["x_reader"]

[formats.thread]
max_chars_per_tweet = 280
max_tweets = 15
personas = ["x_reader", "linkedin_reader"]
readers = ["x_reader"]
```

## Evaluation Harness (evaluate.py)

**Key design: async parallel evaluation with both Anthropic and OpenAI.**

For each iteration:
1. Load all scoring personas (exclude reader personas like hn_reader, x_reader)
2. For each persona, run 3 evaluations in parallel using the PRIMARY model
3. For reader personas, run comment generation using BOTH primary and secondary models
4. All API calls are async (aiohttp/httpx) for maximum parallelism
5. Parse structured scores from each evaluation
6. Compute medians per persona-dimension

**Evaluation prompt structure:**
- Persona identity + rubric injected from persona .md file
- Draft text included inline
- Goal.md included for context
- Evaluator must quote specific passages before scoring
- Returns structured format: `DIMENSION: [reasoning] -> [score]`

**API integration:**
- Anthropic: use `anthropic` Python SDK with async client
- OpenAI: use `openai` Python SDK with async client  
- Both use environment variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- If one is missing, fall back to the other for all evals

## Writer Agent (writer.py)

The writer agent receives:
- All evaluation scores + reasoning
- Reader comments (HN + X from both models)
- Current draft
- Voice config (voice/default.toml)
- Goal (goal.md)
- Focus point weights

It makes ONE focused edit targeting the highest-impact weakness (weighted by focus points).

**Writer prompt includes Leo's anti-slop rules:**
- No em dashes
- No hollow intensifiers (significantly, dramatically, incredibly)
- No hedge-then-assert patterns
- No motivational filler
- No summary sentences that restate what was just said
- Specific phrase blacklist from Leo's preferences
- Short sentences, active voice, concrete nouns

## Persona Files

Each scoring persona follows this structure:

```markdown
# Persona: [Name]

## Identity
[Vivid second-person description]

## What they care about
[Bullet list of evaluation criteria]

## Value proposition lens
[What would make them act — share, forward, take a meeting]

## Rubric
- **[Dimension]** (0-10): [What a 10 looks like]
- **[Dimension]** (0-10): [What a 10 looks like]
[4-6 dimensions]

## Dealbreaker
[One sentence — what causes instant dismissal]
```

Reader personas (hn_reader, x_reader) don't have rubrics — they write free-form comments instead.

### Personas to build:

**seed_founder.md** — A seed-stage AI/infra founder. Has taken 50+ investor meetings. Can smell VC marketing from a mile away. Cares about: does this person understand my world? Would I want them on my cap table? Does the writing show genuine founder empathy or just buzzword pattern-matching?
- Rubric: Founder empathy (0-10), Genuine insight (0-10), Practical value (0-10), Authenticity (0-10), "Would I share this with my co-founder?" (0-10)

**fellow_gp.md** — A partner at a peer seed fund. Reads VC content to calibrate other investors' thinking quality. Extremely allergic to generic VC platitudes. Cares about: is there original thinking here? Would I forward this to my partners? Does this person see something I don't?
- Rubric: Original thesis (0-10), Market understanding (0-10), Intellectual rigor (0-10), Signal vs noise (0-10), "Would I DM this to another GP?" (0-10)

**lp_allocator.md** — An LP evaluating emerging managers. Reads GP content to assess thinking quality and market access. Cares about: does this GP have genuine differentiated insight? Do they sound like a thought leader or a thought follower? Is the writing evidence of real expertise?
- Rubric: Differentiated perspective (0-10), Evidence of access/expertise (0-10), Clarity of thinking (0-10), Professional credibility (0-10), "Does this make me more confident in this GP?" (0-10)

**linkedin_reader.md** — A senior tech/VC professional scrolling LinkedIn during their commute. Gives each post 3 seconds before scrolling past. Cares about: does the hook grab me? Is there a single sharp insight I can take away? Would I hit "like" or keep scrolling?
- Rubric: Hook strength (0-10), Insight density (0-10), Readability/flow (0-10), Shareability (0-10), "Would I engage with this?" (0-10)

**hn_reader.md** — Reader persona (writes 3 HN-style comments, doesn't score). Senior engineer / technical founder. Skeptical of VC hand-waving. Respects genuine insight but will call out marketing dressed as thought leadership.

**x_reader.md** — Reader persona (writes 3 X/Twitter reactions, doesn't score). VC/tech Twitter native. Will quote-tweet if genuinely insightful, dunk if it's generic content-machine output.

## Voice Config (voice/default.toml)

```toml
[author]
name = "Leo"
role = "VC Partner / Seed Investor"
company = "Foundation Capital"

[tone]
# 1-10 spectrum
visionary_vs_practical = 5          # Balanced — grounded insights, not hand-waving
technical_vs_accessible = 5         # Smart but not jargon-heavy
confident_vs_humble = 7             # Confident in thesis, humble about unknowns  
formal_vs_conversational = 4        # More conversational — direct, natural
provocative_vs_safe = 7             # Takes positions, not afraid to disagree
builder_vs_analyst = 6              # Has builder background, now analyzes from that lens

[style]
sentence_length = "short"           # 8-15 words preferred, vary for rhythm
voice = "active"                    # Name the actor
specificity = "high"                # Concrete numbers, named examples
max_adjective_chain = 2             # Never list 3+ adjectives

[rules]
# Leo's 16-point writing rubric (learned from LP email exercise)
rules = [
    "Explain jargon inline for the audience — context without condescension",
    "Name specific things — specifics = credibility",
    "Add the honest detail — real work is messy, don't over-dramatize",
    "No theatrical quote framing — just state the data point",
    "Soften hard numbers — 'about 85%' not '85%'",
    "Drop survey citations mid-paragraph — fold in naturally",
    "Use 'which means' to chain ideas — keep flow, don't start dramatic new sentences",
    "Mix 'I' and 'we' naturally — 'I' for personal, 'we' for firm work",
    "Use '/' for casual alternatives — efficient, real",
    "End when the point is made — no rhetorical closers",
    "Passive attribution > dramatic framing",
    "Swap technical terms for general ones when it doesn't lose meaning",
    "Don't overuse dashes — AI tell. Use commas, periods, or 'which' instead",
    "Don't start answers with 'Yes' when speaking on behalf of others",
    "Chain naturally with 'so,' 'which means,' 'and' — but don't overdo transitions",
    "No AI-sounding thesis openers — write like a person, not a blog post headline",
]

[blacklist]
# Words/phrases to never use
words = [
    "strive", "eager", "funny enough", "zeroing in", "by way of introduction",
    "shadowing", "portfolio highlights", "looking forward to your guidance",
    "leverage", "utilize", "robust", "scalable", "cutting-edge", "game-changing",
    "paradigm shift", "innovative", "state-of-the-art", "holistic", "synergy",
    "significantly", "dramatically", "incredibly", "remarkably",
    "This represents an opportunity", "This shift enables",
    "Moreover", "Furthermore", "Additionally", "It is important to note",
    "can potentially", "may help to", "aims to provide",
]

[blacklist_patterns]
# Regex patterns to flag
patterns = [
    "— ",                             # Em dashes (AI tell)
    "\\w+, \\w+, and \\w+ly",         # Triple adjective chains
    "While .+ is important, .+ is also", # Hedge-then-assert
]
```

## Data Management (data.py)

Same concept as ghostwriter but cleaner:
- `data/` directory holds all runtime artifacts
- `data/draft.md` is the working copy
- `data/manifest.json` indexes all iterations
- `data/iter_NN/` per iteration: snapshot, diff, scores, comments, summary
- Each persona's scores go in a separate file (parallel-safe)

## Scoring (scorer.py)

- Median of 3 runs per persona-dimension (noise reduction)
- Focus-point-weighted weakness detection
- Keep/discard logic: min_score must improve by >= threshold, else discard
- Stuck detection: 3 consecutive discards on same weakness → try different approach

## Display (display.py)

Use `rich` library for:
- Live progress panel during evaluation (which personas are done, pending)
- Iteration history table
- Score trend visualization (text-based)
- Color-coded improvement/regression per dimension

## Export (export.py)

`redpen export` produces:
- Final polished draft (the best version)
- Changelog: list of every kept edit with description + score delta
- Score trajectory: starting scores → final scores per persona

## Dependencies (pyproject.toml)

```toml
[project]
name = "redpen"
version = "0.1.0"
description = "AI writing refinement engine — autoresearch for prose"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "click>=8.0",
    "rich>=13.0",
    "tomli>=2.0; python_version < '3.11'",
]

[project.scripts]
redpen = "redpen.cli:main"
```

## Implementation Priority

1. **Core loop** — cli.py + loop.py + data.py + scorer.py (the ratchet works)
2. **Evaluation** — evaluate.py with async Anthropic calls (OpenAI secondary)
3. **Writer** — writer.py with Leo's voice config
4. **Personas** — all 6 persona files
5. **Display** — rich terminal output
6. **Export** — export command
7. **Tests** — scorer tests, data tests
8. **README** — thorough docs

## Non-Negotiable Quality Rules

- All Python code uses type hints
- Async where it matters (parallel API calls), sync where it doesn't
- Error handling: API failures retry 3x with backoff, then skip that persona
- No hardcoded API keys — always from environment variables
- Git operations use `git -c commit.gpgsign=false`
- Every file has a module docstring explaining what it does
- The CLI should work after `uv sync && redpen --help`
