"""Iteration data management — init, snapshots, scores, comments, manifest."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATA_DIR = "data"
MANIFEST_FILE = "manifest.json"
DRAFT_FILE = "draft.md"


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _manifest_path(root: Path) -> Path:
    return root / DATA_DIR / MANIFEST_FILE


def _load_manifest(root: Path) -> dict[str, Any]:
    p = _manifest_path(root)
    if not p.exists():
        return {"iterations": [], "status": "initialized", "format": "blog", "tag": ""}
    return json.loads(p.read_text())


def _save_manifest(root: Path, manifest: dict[str, Any]) -> None:
    p = _manifest_path(root)
    p.write_text(json.dumps(manifest, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Iteration directory
# ---------------------------------------------------------------------------

def _iter_dir(root: Path, iteration: int) -> Path:
    return root / DATA_DIR / f"iter_{iteration:02d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_run(root: Path, draft_path: Path, fmt: str = "blog", tag: str = "") -> Path:
    """Initialize a new RedPen run: copy draft, create manifest. Returns data dir."""
    data = root / DATA_DIR
    data.mkdir(exist_ok=True)

    # Copy source draft
    dest = data / DRAFT_FILE
    shutil.copy2(draft_path, dest)

    manifest: dict[str, Any] = {
        "source": str(draft_path),
        "format": fmt,
        "tag": tag,
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "iterations": [],
    }
    _save_manifest(root, manifest)
    return data


def current_draft(root: Path) -> str:
    """Read the current working draft."""
    p = root / DATA_DIR / DRAFT_FILE
    if not p.exists():
        raise FileNotFoundError(f"No draft found at {p}. Run 'redpen init' first.")
    return p.read_text()


def write_draft(root: Path, text: str) -> None:
    """Overwrite the working draft."""
    p = root / DATA_DIR / DRAFT_FILE
    p.write_text(text)


def new_iteration(root: Path) -> int:
    """Create a new iteration directory. Returns the iteration number."""
    manifest = _load_manifest(root)
    n = len(manifest["iterations"]) + 1
    d = _iter_dir(root, n)
    d.mkdir(parents=True, exist_ok=True)

    # Snapshot the current draft
    draft = current_draft(root)
    (d / "snapshot.md").write_text(draft)

    manifest["iterations"].append({
        "number": n,
        "status": "evaluating",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    manifest["status"] = "running"
    _save_manifest(root, manifest)
    return n


def _safe_filename(name: str) -> str:
    """Sanitize a persona name for use in filenames."""
    return name.replace("/", "_").replace(" ", "_").replace("\\", "_")


def save_scores(root: Path, iteration: int, persona: str, scores: dict[str, Any]) -> None:
    """Save a single persona's scores for an iteration."""
    d = _iter_dir(root, iteration)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"scores_{_safe_filename(persona)}.json"
    p.write_text(json.dumps(scores, indent=2) + "\n")


def save_comments(root: Path, iteration: int, persona: str, comments: list[str], model: str) -> None:
    """Save reader comments from a persona."""
    d = _iter_dir(root, iteration)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"comments_{_safe_filename(persona)}_{model}.json"
    p.write_text(json.dumps({"persona": persona, "model": model, "comments": comments}, indent=2) + "\n")


def save_summary(root: Path, iteration: int, summary: dict[str, Any]) -> None:
    """Save iteration summary (aggregate scores, decision, weakness)."""
    d = _iter_dir(root, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def save_diff(root: Path, iteration: int, diff_description: str) -> None:
    """Save the writer's edit description."""
    d = _iter_dir(root, iteration)
    d.mkdir(parents=True, exist_ok=True)
    (d / "diff.md").write_text(diff_description)


def finalize_iteration(
    root: Path,
    iteration: int,
    *,
    kept: bool,
    reason: str,
) -> None:
    """Mark an iteration as kept or discarded."""
    manifest = _load_manifest(root)
    for entry in manifest["iterations"]:
        if entry["number"] == iteration:
            entry["status"] = "kept" if kept else "discarded"
            entry["reason"] = reason
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            break
    _save_manifest(root, manifest)


def finish_run(root: Path, reason: str) -> None:
    """Mark the entire run as complete."""
    manifest = _load_manifest(root)
    manifest["status"] = "complete"
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["stop_reason"] = reason
    _save_manifest(root, manifest)


def load_iteration_scores(root: Path, iteration: int) -> dict[str, dict[str, Any]]:
    """Load all persona scores for an iteration. Returns {persona: scores_dict}."""
    d = _iter_dir(root, iteration)
    results: dict[str, dict[str, Any]] = {}
    if not d.exists():
        return results
    for p in d.glob("scores_*.json"):
        persona = p.stem.removeprefix("scores_")
        results[persona] = json.loads(p.read_text())
    return results


def load_iteration_comments(root: Path, iteration: int) -> list[dict[str, Any]]:
    """Load all reader comments for an iteration."""
    d = _iter_dir(root, iteration)
    results: list[dict[str, Any]] = []
    if not d.exists():
        return results
    for p in d.glob("comments_*.json"):
        results.append(json.loads(p.read_text()))
    return results


def load_iteration_summary(root: Path, iteration: int) -> dict[str, Any] | None:
    """Load iteration summary if it exists."""
    p = _iter_dir(root, iteration) / "summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def get_status(root: Path) -> dict[str, Any]:
    """Return current run status for display."""
    manifest = _load_manifest(root)
    return {
        "status": manifest.get("status", "unknown"),
        "format": manifest.get("format", ""),
        "tag": manifest.get("tag", ""),
        "total_iterations": len(manifest.get("iterations", [])),
        "kept": sum(1 for i in manifest.get("iterations", []) if i.get("status") == "kept"),
        "discarded": sum(1 for i in manifest.get("iterations", []) if i.get("status") == "discarded"),
        "iterations": manifest.get("iterations", []),
        "created_at": manifest.get("created_at", ""),
        "finished_at": manifest.get("finished_at", ""),
        "stop_reason": manifest.get("stop_reason", ""),
    }


def last_kept_iteration(root: Path) -> int | None:
    """Return the number of the most recent kept iteration, or None."""
    manifest = _load_manifest(root)
    for entry in reversed(manifest.get("iterations", [])):
        if entry.get("status") == "kept":
            return entry["number"]
    return None
