"""Command-line interface for sessionkeep.

Two entry points:

  sessionkeep archive <path>   Archive a transcript file directly.
  sessionkeep hook             Read a Claude Code SessionEnd hook payload from
                               stdin and archive its transcript. Designed to be
                               wired into your agent and never break it: on any
                               error it exits 0 quietly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .archiver import (
    archive_transcript,
    default_archive_dir,
    import_transcripts,
    iter_archive_meta,
    search_archives,
)
from .config import build_masker
from .discovery import find_codex_sessions, find_transcripts


def _report(meta: dict, quiet: bool) -> None:
    if quiet:
        return
    if meta.get("dry_run"):
        sys.stderr.write(
            "[sessionkeep] dry-run: {lines} lines, {masked} with secrets -> {dest}\n".format(
                lines=meta["line_count"],
                masked=meta["masked_lines"],
                dest=meta["would_write"],
            )
        )
        return
    sys.stderr.write(
        "[sessionkeep] archived {lines} lines ({masked} masked) -> {dest}\n".format(
            lines=meta["line_count"],
            masked=meta["masked_lines"],
            dest=meta["archive_path"],
        )
    )


def _cmd_archive(args: argparse.Namespace) -> int:
    try:
        masker = build_masker(args.config)
    except ValueError as exc:
        sys.stderr.write(f"[sessionkeep] config error: {exc}\n")
        return 2
    # When no explicit slug is given, derive it from the file's own directory.
    cwd = os.path.dirname(os.path.abspath(args.path)) if args.project is None else ""
    meta = archive_transcript(
        args.path,
        out_dir=args.out,
        project_slug=args.project,
        cwd=cwd,
        dry_run=args.dry_run,
        masker=masker,
    )
    _report(meta, args.quiet)
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    # Hook mode must never break the host agent: swallow everything, exit 0.
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    # In a hook we never crash: a bad config falls back to built-in masking.
    try:
        masker = build_masker(args.config)
    except ValueError as exc:
        sys.stderr.write(f"[sessionkeep] config error, using built-in masks: {exc}\n")
        masker = None

    try:
        meta = archive_transcript(
            transcript_path,
            out_dir=args.out,
            cwd=payload.get("cwd") or "",
            session_id=payload.get("session_id") or "",
            dry_run=args.dry_run,
            masker=masker,
        )
    except Exception as exc:  # noqa: BLE001 - resilience over precision in a hook
        sys.stderr.write(f"[sessionkeep] hook failed: {exc}\n")
        return 0

    _report(meta, args.quiet)
    return 0


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _cmd_list(args: argparse.Namespace) -> int:
    metas = iter_archive_meta(args.out)
    if args.project:
        metas = [m for m in metas if m.get("project_slug") == args.project]
    if args.since:
        # archived_at is ISO 8601, so lexicographic comparison is chronological.
        metas = [m for m in metas if m.get("archived_at", "") >= args.since]
    if args.limit:
        metas = metas[: args.limit]
    if args.json:
        print(json.dumps(metas, ensure_ascii=False, indent=2))
        return 0
    if not metas:
        sys.stderr.write("[sessionkeep] no archived sessions found\n")
        return 0
    for m in metas:
        print(
            "{when}  {proj:<20}  {lines:>6} lines  {masked:>3} masked  {size:>8}  {path}".format(
                when=m.get("archived_at", "?"),
                proj=(m.get("project_slug") or "?")[:20],
                lines=m.get("line_count", 0),
                masked=m.get("masked_lines", 0),
                size=_human_bytes(m.get("archived_bytes", 0)),
                path=m.get("_archive_path", ""),
            )
        )
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    results = search_archives(
        args.query,
        base_dir=args.out,
        ignore_case=args.ignore_case,
        max_results=args.max,
    )
    if not results:
        sys.stderr.write(f"[sessionkeep] no matches for {args.query!r}\n")
        return 1
    for r in results:
        print(f"{r['archive_path']}:{r['line_no']}: {r['text']}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    project = args.project
    if args.codex:
        paths = find_codex_sessions()
        label = "Codex"
        if project is None:
            project = "codex"
    elif args.from_dir:
        paths = find_transcripts(args.from_dir, pattern=args.pattern)
        label = args.from_dir
    else:
        sys.stderr.write("[sessionkeep] import requires --codex or --from DIR\n")
        return 2

    if not paths:
        sys.stderr.write(f"[sessionkeep] no transcripts found for {label}\n")
        return 0

    try:
        masker = build_masker(args.config)
    except ValueError as exc:
        sys.stderr.write(f"[sessionkeep] config error: {exc}\n")
        return 2

    result = import_transcripts(
        paths,
        out_dir=args.out,
        project_slug=project,
        dry_run=args.dry_run,
        masker=masker,
    )
    verb = "would archive" if args.dry_run else "archived"
    sys.stderr.write(
        "[sessionkeep] {label}: {verb} {n}, skipped {s} already-archived\n".format(
            label=label, verb=verb, n=len(result["archived"]), s=len(result["skipped"])
        )
    )
    if not args.quiet:
        for m in result["archived"]:
            dest = m.get("would_write") or m.get("archive_path", "")
            print(dest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sessionkeep",
        description="Archive AI coding agent session logs with secret masking.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help=f"archive directory (default: $SESSIONKEEP_DIR or {default_archive_dir()})",
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be archived (and secret hits) without writing",
    )
    common.add_argument("-q", "--quiet", action="store_true", help="suppress the summary line")
    common.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="JSON config with extra mask_patterns/mask_literals "
        "(default: $SESSIONKEEP_CONFIG or ~/.sessionkeep/config.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_archive = sub.add_parser(
        "archive", parents=[common], help="archive a transcript file by path"
    )
    p_archive.add_argument("path", help="path to the transcript/log file")
    p_archive.add_argument(
        "--project",
        default=None,
        help="override the project slug (default: derived from the file's directory)",
    )
    p_archive.set_defaults(func=_cmd_archive)

    p_hook = sub.add_parser(
        "hook", parents=[common], help="archive from a Claude Code SessionEnd hook payload (stdin)"
    )
    p_hook.set_defaults(func=_cmd_hook)

    # `out` is reused for read-only commands too (where to look), so build a
    # lighter parent without the write-only flags.
    out_only = argparse.ArgumentParser(add_help=False)
    out_only.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help=f"archive directory to read (default: $SESSIONKEEP_DIR or {default_archive_dir()})",
    )

    p_list = sub.add_parser("list", parents=[out_only], help="list archived sessions, newest first")
    p_list.add_argument("--limit", type=int, default=0, help="show only the N most recent")
    p_list.add_argument("--project", default=None, help="filter by project slug")
    p_list.add_argument(
        "--since", default=None, metavar="ISO", help="only sessions archived on/after this date (YYYY-MM-DD)"
    )
    p_list.add_argument("--json", action="store_true", help="output full metadata as JSON")
    p_list.set_defaults(func=_cmd_list)

    p_search = sub.add_parser(
        "search", parents=[out_only], help="search archived transcripts for text"
    )
    p_search.add_argument("query", help="text to search for")
    p_search.add_argument("-i", "--ignore-case", action="store_true", help="case-insensitive search")
    p_search.add_argument("--max", type=int, default=None, help="stop after N matches")
    p_search.set_defaults(func=_cmd_search)

    p_import = sub.add_parser(
        "import",
        parents=[common],
        help="bulk-archive existing transcripts (e.g. Codex CLI sessions), skipping duplicates",
    )
    src = p_import.add_mutually_exclusive_group()
    src.add_argument(
        "--codex", action="store_true", help="discover Codex CLI rollouts under $CODEX_HOME"
    )
    src.add_argument(
        "--from", dest="from_dir", metavar="DIR", help="scan a directory for transcripts"
    )
    p_import.add_argument(
        "--pattern", default="*.jsonl", help="glob for --from (default: *.jsonl)"
    )
    p_import.add_argument(
        "--project", default=None, help="override the project slug for imported sessions"
    )
    p_import.set_defaults(func=_cmd_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
