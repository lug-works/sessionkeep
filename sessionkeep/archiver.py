"""Core archiving logic: mask secrets, gzip, store under a dated tree."""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import os
import pathlib
import re
from typing import Optional

from .masking import DEFAULT_MASKER, Masker

#: Environment variable that overrides the default archive directory.
DIR_ENV = "SESSIONKEEP_DIR"

SCHEMA_VERSION = 1


def default_archive_dir() -> pathlib.Path:
    """Where archives go when no ``--out`` is given.

    Honors ``$SESSIONKEEP_DIR``; otherwise ``~/.sessionkeep/sessions``.
    """
    env = os.environ.get(DIR_ENV)
    if env:
        return pathlib.Path(env).expanduser()
    return pathlib.Path.home() / ".sessionkeep" / "sessions"


def derive_project_slug(cwd: str) -> str:
    """Use the last path component of ``cwd`` as a filesystem-safe project slug."""
    base = os.path.basename(cwd.rstrip("/\\")) if cwd else ""
    if not base:
        base = "unknown"
    slug = re.sub(r"[^A-Za-z0-9_\-]+", "-", base).strip("-")
    return slug or "unknown"


def archive_transcript(
    transcript_path: os.PathLike[str] | str,
    out_dir: os.PathLike[str] | str | None = None,
    *,
    project_slug: Optional[str] = None,
    cwd: str = "",
    session_id: str = "",
    dry_run: bool = False,
    now: Optional[_dt.datetime] = None,
    masker: Optional[Masker] = None,
) -> dict:
    """Mask secrets in ``transcript_path`` and write a gzipped copy + metadata.

    Returns a metadata dict. With ``dry_run=True`` nothing is written; the dict
    reports the would-be destination and how many lines contain secrets.
    Pass ``masker`` to use custom patterns (defaults to built-ins).
    """
    masker = masker or DEFAULT_MASKER
    transcript_path = os.fspath(transcript_path)
    if not transcript_path or not os.path.isfile(transcript_path):
        raise FileNotFoundError(f"transcript not found: {transcript_path!r}")
    abs_source = os.path.abspath(transcript_path)

    base_dir = pathlib.Path(out_dir).expanduser() if out_dir else default_archive_dir()
    if project_slug is None:
        project_slug = derive_project_slug(cwd)
    now = now or _dt.datetime.now()

    year = now.strftime("%Y")
    month = now.strftime("%m")
    date = now.strftime("%Y-%m-%d")
    time_hm = now.strftime("%H%M")
    short_id = session_id[:8] if session_id else "nosid"

    dest_dir = base_dir / year / month
    stem = f"{date}_{time_hm}_{project_slug}_{short_id}"
    dest_file = dest_dir / f"{stem}.jsonl.gz"
    meta_file = dest_dir / f"{stem}.meta.json"

    src_size = os.path.getsize(transcript_path)

    if dry_run:
        masked_hits, line_count = _count_masked(transcript_path, masker)
        return {
            "dry_run": True,
            "source": abs_source,
            "would_write": os.fspath(dest_file),
            "source_bytes": src_size,
            "line_count": line_count,
            "masked_lines": masked_hits,
            "project_slug": project_slug,
        }

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Avoid clobbering if the same session is archived more than once.
    counter = 1
    while dest_file.exists():
        stem_n = f"{stem}_{counter:02d}"
        dest_file = dest_dir / f"{stem_n}.jsonl.gz"
        meta_file = dest_dir / f"{stem_n}.meta.json"
        counter += 1

    masked_hits = 0
    line_count = 0
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as src, gzip.open(
        dest_file, "wt", encoding="utf-8"
    ) as dst:
        for line in src:
            line_count += 1
            masked = masker.mask(line)
            if masked != line:
                masked_hits += 1
            dst.write(masked)

    meta = {
        "session_id": session_id,
        "archived_at": now.isoformat(timespec="seconds"),
        "source": abs_source,
        "cwd": cwd,
        "project_slug": project_slug,
        "source_bytes": src_size,
        "archived_bytes": dest_file.stat().st_size,
        "line_count": line_count,
        "masked_lines": masked_hits,
        "archive_path": os.fspath(dest_file),
        "schema_version": SCHEMA_VERSION,
    }
    meta_file.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def _count_masked(transcript_path: str, masker: Masker) -> tuple[int, int]:
    masked_hits = 0
    line_count = 0
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as src:
        for line in src:
            line_count += 1
            if masker.mask(line) != line:
                masked_hits += 1
    return masked_hits, line_count


# ---- Reading back the archive (list / search / import dedupe) --------------------


def iter_archive_meta(base_dir: os.PathLike[str] | str | None = None) -> list[dict]:
    """Return metadata for all archived sessions, newest first."""
    base = pathlib.Path(base_dir).expanduser() if base_dir else default_archive_dir()
    if not base.is_dir():
        return []
    metas: list[dict] = []
    for meta_file in base.rglob("*.meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stem = meta_file.name[: -len(".meta.json")]
        meta["_meta_path"] = os.fspath(meta_file)
        meta["_archive_path"] = os.fspath(meta_file.with_name(stem + ".jsonl.gz"))
        metas.append(meta)
    metas.sort(key=lambda m: m.get("archived_at", ""), reverse=True)
    return metas


def archived_sources(base_dir: os.PathLike[str] | str | None = None) -> set[str]:
    """Set of absolute source paths already archived (for import dedupe)."""
    out: set[str] = set()
    for meta in iter_archive_meta(base_dir):
        src = meta.get("source")
        if src:
            out.add(os.path.abspath(src))
    return out


def search_archives(
    query: str,
    base_dir: os.PathLike[str] | str | None = None,
    *,
    ignore_case: bool = False,
    max_results: int | None = None,
) -> list[dict]:
    """Search archived transcripts for ``query``.

    Returns dicts: ``{archive_path, line_no, text}``. Searches the masked
    contents, so secrets never resurface in results.
    """
    base = pathlib.Path(base_dir).expanduser() if base_dir else default_archive_dir()
    needle = query.lower() if ignore_case else query
    results: list[dict] = []
    if not base.is_dir():
        return results
    for gz in sorted(base.rglob("*.jsonl.gz")):
        try:
            with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fh:
                for line_no, line in enumerate(fh, start=1):
                    hay = line.lower() if ignore_case else line
                    if needle in hay:
                        results.append(
                            {
                                "archive_path": os.fspath(gz),
                                "line_no": line_no,
                                "text": line.rstrip("\n"),
                            }
                        )
                        if max_results is not None and len(results) >= max_results:
                            return results
        except OSError:
            continue
    return results


def import_transcripts(
    paths,
    out_dir: os.PathLike[str] | str | None = None,
    *,
    project_slug: Optional[str] = None,
    use_source_mtime: bool = True,
    derive_id_from_name: bool = True,
    dry_run: bool = False,
    masker: Optional[Masker] = None,
) -> dict:
    """Archive a batch of transcript files, skipping ones already archived.

    Returns ``{"archived": [meta, ...], "skipped": [path, ...]}``.
    """
    from .discovery import source_session_id  # local import avoids cycle

    already = archived_sources(out_dir)
    archived: list[dict] = []
    skipped: list[str] = []

    for raw in paths:
        path = os.fspath(raw)
        abs_path = os.path.abspath(path)
        if abs_path in already:
            skipped.append(abs_path)
            continue

        now = None
        if use_source_mtime:
            try:
                now = _dt.datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                now = None
        session_id = source_session_id(path) if derive_id_from_name else ""

        try:
            meta = archive_transcript(
                path,
                out_dir=out_dir,
                project_slug=project_slug,
                session_id=session_id,
                dry_run=dry_run,
                now=now,
                masker=masker,
            )
        except FileNotFoundError:
            continue

        archived.append(meta)
        if not dry_run:
            already.add(abs_path)  # guard against duplicate inputs in one batch

    return {"archived": archived, "skipped": skipped}
