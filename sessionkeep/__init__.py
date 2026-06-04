"""sessionkeep — archive AI coding agent session logs with secret masking."""

__version__ = "0.3.0"

from .archiver import (
    archive_transcript,
    archived_sources,
    default_archive_dir,
    derive_project_slug,
    import_transcripts,
    iter_archive_meta,
    search_archives,
)
from .config import build_masker, load_config
from .discovery import codex_home, find_codex_sessions, find_transcripts
from .masking import DEFAULT_MASKER, Masker, mask_secrets

__all__ = [
    "archive_transcript",
    "archived_sources",
    "default_archive_dir",
    "derive_project_slug",
    "import_transcripts",
    "iter_archive_meta",
    "search_archives",
    "build_masker",
    "load_config",
    "codex_home",
    "find_codex_sessions",
    "find_transcripts",
    "mask_secrets",
    "Masker",
    "DEFAULT_MASKER",
    "__version__",
]
