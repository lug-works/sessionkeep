"""Find agent session transcripts on disk so they can be imported.

Claude Code is archived live via the `hook` command. Codex CLI has no such
hook, so we discover its rollout files by scanning ``$CODEX_HOME``.
"""

from __future__ import annotations

import os
import pathlib
from typing import Iterable

#: Codex CLI stores rollouts under $CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl
CODEX_HOME_ENV = "CODEX_HOME"
CODEX_ROLLOUT_GLOB = "sessions/**/rollout-*.jsonl"


def codex_home() -> pathlib.Path:
    """Resolve ``$CODEX_HOME`` (default ``~/.codex``).

    ``$CODEX_HOME`` may be a comma-separated list; this returns the first entry.
    """
    env = os.environ.get(CODEX_HOME_ENV)
    if env:
        first = env.split(",")[0].strip()
        if first:
            return pathlib.Path(first).expanduser()
    return pathlib.Path.home() / ".codex"


def find_codex_sessions(home: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Return all Codex rollout transcript paths, sorted oldest-first."""
    root = home or codex_home()
    if not root.is_dir():
        return []
    return sorted(root.glob(CODEX_ROLLOUT_GLOB))


def find_transcripts(root: os.PathLike[str] | str, pattern: str = "*.jsonl") -> list[pathlib.Path]:
    """Return files under ``root`` matching ``pattern`` (recursive), sorted."""
    base = pathlib.Path(root).expanduser()
    if not base.is_dir():
        return []
    return sorted(base.rglob(pattern))


def source_session_id(path: os.PathLike[str] | str) -> str:
    """Best-effort stable id from a transcript filename.

    Codex rollouts look like ``rollout-2025-01-22T10-30-00-abc123.jsonl``; the
    trailing token is the most distinctive part. Falls back to the stem.
    """
    stem = pathlib.Path(path).stem
    if "-" in stem:
        tail = stem.rsplit("-", 1)[-1]
        if tail:
            return tail
    return stem


def dedupe_existing(paths: Iterable[pathlib.Path], archived_sources: set[str]) -> list[pathlib.Path]:
    """Drop paths whose absolute form was already archived."""
    out = []
    for p in paths:
        if os.path.abspath(os.fspath(p)) not in archived_sources:
            out.append(p)
    return out
