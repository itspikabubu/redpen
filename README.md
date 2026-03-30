# RedPen

AI writing refinement engine — autoresearch for prose. Iterative multi-persona evaluation + editing loop where drafts can only get better, never worse.

## How It Works

RedPen runs a ratchet loop:

1. **Evaluate** — Multiple AI personas score your draft on specific dimensions (0-10). Reader personas (HN skeptic, VC Twitter) write realistic comments instead of scores. Each persona runs 3 times; scores are medianed for noise reduction.
2. **Diagnose** — Focus-weighted weakness detection finds the highest-impact dimension to fix. Persona weights let you prioritize whose opinion matters most.
3. **Edit** — A writer agent makes one surgical edit targeting the top weakness, following your voice config and style rules.
4. **Keep/Discard** — The edited draft is re-evaluated. If the min score improved, the edit is kept. If not, it's discarded and the draft reverts. Drafts can only get better.
5. **Repeat** — Until min_score hits your target or max iterations are reached.

## Quick Start

```bash
# Install
uv sync

# Set API keys
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."  # Optional, used for reader comments

# Edit goal.md with your article's purpose, audience, and thesis

# Run
redpen go draft.md --format blog --max-iterations 15

# Or step by step:
redpen init draft.md --format blog --tag "ai-agents-post"
redpen run
redpen status
redpen export -o final.md
```

## CLI Commands

### `redpen init <draft.md>`

Initialize a new run. Copies the draft to `data/draft.md` and creates the manifest.

```bash
redpen init draft.md --format blog --tag "march-post"
```

Options:
- `--format` — Content format: `blog`, `linkedin`, `thread` (default: `blog`)
- `--tag` — Label for this run

### `redpen run`

Run the optimization loop on an initialized draft.

```bash
redpen run --max-iterations 20
```

Options:
- `--max-iterations` — Override max iterations from config
- `--format` — Override format from init

### `redpen status`

Show run status, iteration history, and keep/discard decisions.

### `redpen export`

Export the final draft with changelog and score trajectory.

```bash
redpen export -o final.md
redpen export --json  # scores only, as JSON
```

### `redpen go <draft.md>`

Shortcut: init + run in one command.

```bash
redpen go draft.md --format linkedin --max-iterations 10 --tag "q1-update"
```

## Configuration

Edit `config.toml` to customize:

```toml
[models]
primary = "claude-sonnet-4-20250514"    # Evaluator model
secondary = "gpt-4o"                    # Reader comment model
writer = "claude-sonnet-4-20250514"      # Writer model
temperature = 0.7

[eval]
runs = 3                          # Runs per persona (medianed)
min_improvement = 0.5             # Min score delta to keep
mean_improvement = 0.3            # Mean score tiebreaker

[stopping]
min_score_target = 7.5            # Stop when min_score >= this
max_iterations = 25

[focus]
seed_founder = 25                 # Weight distribution (higher = fix first)
fellow_gp = 30
lp_allocator = 25
linkedin_reader = 20
```

## Personas

Six personas evaluate your writing from different perspectives:

| Persona | Type | Role |
|---------|------|------|
| `seed_founder` | Scorer | Seed-stage AI founder evaluating investor content |
| `fellow_gp` | Scorer | Partner at a peer fund calibrating your thinking |
| `lp_allocator` | Scorer | LP assessing GP thinking quality |
| `linkedin_reader` | Scorer | VP of Product scrolling LinkedIn |
| `hn_reader` | Reader | HN skeptic writing 3 comments |
| `x_reader` | Reader | VC Twitter writing 3 reactions |

Scoring personas rate dimensions 0-10. Reader personas write realistic comments. Create custom personas from `personas/_template.md`.

## Voice Config

`voice/default.toml` controls the writer agent's output:

- **Tone spectrum** — visionary vs practical, formal vs conversational, etc.
- **Style rules** — sentence length, active voice, specificity
- **Writing rules** — 16-point rubric for natural, human-sounding prose
- **Blacklist** — Words and patterns the writer must never use

## Project Structure

```
data/                  # Runtime artifacts (gitignored)
├── draft.md           # Working copy
├── manifest.json      # Iteration index
└── iter_01/           # Per-iteration data
    ├── snapshot.md     # Draft at start of iteration
    ├── scores_*.json   # Per-persona scores
    ├── comments_*.json # Reader comments
    ├── summary.json    # Aggregate scores + decision
    └── diff.md         # Edit description
```

## Makefile

```bash
make init DRAFT=draft.md FORMAT=blog TAG=my-post
make run MAX=20
make status
make export OUTPUT=final.md
make test
make clean
```

## Development

```bash
uv sync
python -m pytest tests/ -v
```

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable (required)
- `OPENAI_API_KEY` environment variable (optional, for reader comments from GPT)
