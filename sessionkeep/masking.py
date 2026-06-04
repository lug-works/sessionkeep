"""Secret masking for session transcripts.

Built-in patterns are intentionally broad: a missed secret is worse than a false
positive. Users can extend them with their own regexes / literals via a config
file (see :mod:`sessionkeep.config`). Masking is best-effort insurance, not a
guarantee — always treat archived logs as sensitive.
"""

from __future__ import annotations

import re
from typing import Iterable

# (pattern, replacement). Ordered; applied sequentially to each chunk of text.
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Anthropic
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "sk-ant-***MASKED***"),
    # OpenAI
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{30,}"), "sk-***MASKED***"),
    # GitHub
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_***MASKED***"),
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "gho_***MASKED***"),
    (re.compile(r"ghu_[A-Za-z0-9]{20,}"), "ghu_***MASKED***"),
    (re.compile(r"ghs_[A-Za-z0-9]{20,}"), "ghs_***MASKED***"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_***MASKED***"),
    # GitLab
    (re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"), "glpat-***MASKED***"),
    # AWS
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***MASKED***"),
    (re.compile(r"ASIA[0-9A-Z]{16}"), "ASIA***MASKED***"),
    # Google API / GCP
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "AIza***MASKED***"),
    (re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}"), "ya29.***MASKED***"),
    # Slack
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "xox-***MASKED***"),
    # Stripe
    (re.compile(r"sk_live_[A-Za-z0-9]{20,}"), "sk_live_***MASKED***"),
    (re.compile(r"rk_live_[A-Za-z0-9]{20,}"), "rk_live_***MASKED***"),
    # Bearer tokens (conservative: require 20+ chars to avoid false positives)
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=\-]{20,}"), "Bearer ***MASKED***"),
    # PEM private keys (multi-line)
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "***PRIVATE_KEY_MASKED***",
    ),
]


class Masker:
    """Applies a list of (regex, replacement) pairs to text.

    ``Masker()`` uses the built-in :data:`SECRET_PATTERNS`. Extra patterns are
    appended (applied after the built-ins), so users can add organization-
    specific secret shapes without losing the defaults.
    """

    def __init__(
        self,
        patterns: Iterable[tuple[re.Pattern[str], str]] | None = None,
        *,
        use_builtins: bool = True,
    ) -> None:
        self.patterns: list[tuple[re.Pattern[str], str]] = []
        if use_builtins:
            self.patterns.extend(SECRET_PATTERNS)
        if patterns:
            self.patterns.extend(patterns)

    def mask(self, text: str) -> str:
        for pat, repl in self.patterns:
            text = pat.sub(repl, text)
        return text


#: Shared default masker (built-in patterns only).
DEFAULT_MASKER = Masker()


def mask_secrets(text: str) -> str:
    """Mask known secret shapes using the built-in patterns (convenience)."""
    return DEFAULT_MASKER.mask(text)
