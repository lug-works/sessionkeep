"""Find agent session transcripts on disk so they can be imported.

Claude Code is archived live via the `hook` command. Codex CLI has no such
hook, so we discover its rollout files by scanning ``$CODEX_HOME``.
"""

from __future__ import annotations

import os
import pathlib
import re
import time
from typing import Iterable

#: Canonical session UUID shape (8-4-4-4-12 hex), used by both Claude Code
#: (``<uuid>.jsonl``) and Codex (``rollout-<iso>-<uuid>.jsonl``).
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

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


def filter_settled(
    paths: Iterable[os.PathLike[str] | str],
    min_age_seconds: float,
    *,
    now: float | None = None,
) -> list[pathlib.Path]:
    """Keep only paths last modified at least ``min_age_seconds`` ago.

    Useful for catch-up scans: a transcript still being written (an active
    session) is skipped until it has been idle long enough, so we never freeze
    a partial copy and mark it as already-archived.

    ``min_age_seconds <= 0`` disables the filter and returns everything.
    """
    out: list[pathlib.Path] = []
    paths = [pathlib.Path(p) for p in paths]
    if min_age_seconds <= 0:
        return paths
    cutoff = (now if now is not None else time.time()) - min_age_seconds
    for p in paths:
        try:
            if os.path.getmtime(p) <= cutoff:
                out.append(p)
        except OSError:
            continue
    return out


def source_session_id(path: os.PathLike[str] | str) -> str:
    """Best-effort stable id from a transcript filename.

    Both agents embed a full session UUID in the filename:

    * Claude Code: ``<uuid>.jsonl`` (the stem *is* the UUID).
    * Codex CLI:   ``rollout-<iso-timestamp>-<uuid>.jsonl``.

    We extract the whole UUID so the id matches what the live hook records and
    can be used to correlate an archive back to its session. Splitting on the
    last ``-`` would keep only the final hex group (the UUID itself contains
    hyphens), so we match the full 8-4-4-4-12 shape instead. Falls back to the
    stem when there is no UUID (e.g. an arbitrary ``--from`` directory).
    """
    stem = pathlib.Path(path).stem
    match = _UUID_RE.search(stem)
    if match:
        return match.group(0)
    return stem


def dedupe_existing(paths: Iterable[pathlib.Path], archived_sources: set[str]) -> list[pathlib.Path]:
    """Drop paths whose absolute form was already archived."""
    out = []
    for p in paths:
        if os.path.abspath(os.fspath(p)) not in archived_sources:
            out.append(p)
    return out
