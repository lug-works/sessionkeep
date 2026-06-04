"""User configuration: custom masking patterns.

Config is a small JSON file (stdlib-only, works on every supported Python).
Resolution order for the path:

  1. explicit ``--config PATH`` / ``path`` argument
  2. ``$SESSIONKEEP_CONFIG``
  3. ``~/.sessionkeep/config.json``

Example::

    {
      "mask_patterns": [
        {"pattern": "ACME-[0-9]{6}", "replacement": "ACME-***MASKED***"}
      ],
      "mask_literals": ["my-internal-hostname.corp"]
    }

``mask_patterns`` are regexes (with an optional replacement). ``mask_literals``
are plain strings — handy when you don't want to write a regex; they're escaped
automatically. Both are applied *after* the built-in patterns.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Optional

from .masking import Masker

CONFIG_ENV = "SESSIONKEEP_CONFIG"
DEFAULT_REPLACEMENT = "***MASKED***"


def default_config_path() -> pathlib.Path:
    env = os.environ.get(CONFIG_ENV)
    if env:
        return pathlib.Path(env).expanduser()
    return pathlib.Path.home() / ".sessionkeep" / "config.json"


def load_config(path: os.PathLike[str] | str | None = None) -> dict:
    """Load the config dict. Missing file -> empty config.

    Raises ``ValueError`` if an explicit ``path`` is given but cannot be parsed,
    so misconfiguration fails loudly instead of silently archiving unmasked.
    """
    explicit = path is not None
    cfg_path = pathlib.Path(path).expanduser() if explicit else default_config_path()
    if not cfg_path.is_file():
        if explicit:
            raise ValueError(f"config file not found: {cfg_path}")
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid config {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"config {cfg_path} must be a JSON object")
    return data


def extra_patterns_from_config(config: dict) -> list[tuple[re.Pattern[str], str]]:
    """Turn ``mask_patterns`` + ``mask_literals`` into compiled (regex, repl) pairs."""
    pairs: list[tuple[re.Pattern[str], str]] = []

    for entry in config.get("mask_patterns", []) or []:
        if isinstance(entry, str):
            pattern, repl = entry, DEFAULT_REPLACEMENT
        elif isinstance(entry, dict) and "pattern" in entry:
            pattern = entry["pattern"]
            repl = entry.get("replacement", DEFAULT_REPLACEMENT)
        else:
            raise ValueError(f"invalid mask_patterns entry: {entry!r}")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
        pairs.append((compiled, repl))

    for literal in config.get("mask_literals", []) or []:
        if not isinstance(literal, str) or not literal:
            raise ValueError(f"invalid mask_literals entry: {literal!r}")
        pairs.append((re.compile(re.escape(literal)), DEFAULT_REPLACEMENT))

    return pairs


def build_masker(path: os.PathLike[str] | str | None = None, config: Optional[dict] = None) -> Masker:
    """Build a :class:`Masker` = built-in patterns + any configured extras."""
    if config is None:
        config = load_config(path)
    return Masker(extra_patterns_from_config(config))
