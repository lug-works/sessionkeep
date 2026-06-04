# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.3.0] - 2026-06-05
### Added
- Custom masking via a JSON config (`~/.sessionkeep/config.json`,
  `$SESSIONKEEP_CONFIG`, or `--config`): `mask_patterns` (regex) and
  `mask_literals` (plain strings), applied on top of the built-ins.
- `Masker` class and `config` helpers (`load_config`, `build_masker`) in the
  public API; `archive_transcript`/`import_transcripts` accept a `masker`.
- `list` filters: `--project`, `--since`, and `--json` output.
### Changed
- Invalid config fails loudly (commands exit non-zero) so nothing is archived
  unmasked — except `hook`, which falls back to built-in masking to stay
  non-disruptive.

## [0.2.0] - 2026-06-05
### Added
- `sessionkeep import --codex` — discover Codex CLI rollouts under `$CODEX_HOME`
  and bulk-archive them, skipping anything already saved. Also `--from DIR`
  `--pattern` for arbitrary transcript directories.
- `sessionkeep list` — show archived sessions (newest first) with project, line
  count, masked-line count, and size.
- `sessionkeep search <query>` — grep across archived (masked) transcripts, with
  `-i/--ignore-case` and `--max`.
- Library API: `iter_archive_meta`, `search_archives`, `import_transcripts`,
  `archived_sources`, and `discovery` helpers (`find_codex_sessions`, etc.).
### Changed
- `meta.json` now records the source path as an absolute path (reliable import
  de-duplication).

## [0.1.0] - 2026-06-05
### Added
- `sessionkeep archive <path>` — mask secrets in a transcript and store a
  gzipped copy plus a `.meta.json` under a dated tree.
- `sessionkeep hook` — fail-safe archiving from a Claude Code `SessionEnd`
  hook payload read on stdin.
- `--dry-run`, `--out`, `--project`, `--quiet` flags; `$SESSIONKEEP_DIR` support.
- Secret masking for Anthropic, OpenAI, GitHub, GitLab, AWS, Google/GCP, Slack,
  Stripe tokens, generic Bearer tokens, and PEM private keys.
- Test suite covering masking, archiving, dry-run, and no-clobber behavior.
