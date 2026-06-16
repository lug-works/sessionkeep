# sessionkeep

> Keep your AI coding agent sessions. Mask the secrets. Never lose the history.

`sessionkeep` is a tiny, zero-dependency CLI that archives the session logs from
AI coding agents — [Claude Code](https://www.anthropic.com/claude-code),
[Codex](https://developers.openai.com/codex), and friends — **after masking API
keys and other secrets**, then stores them gzip-compressed in a dated, searchable
tree.

Agent sessions are valuable: they're a record of how a problem was actually
solved. But they also routinely contain pasted API keys, tokens, and `.env`
contents. `sessionkeep` solves both problems at once:

- **Don't lose them.** Each session is archived to `~/.sessionkeep/sessions/YYYY/MM/`.
- **Don't leak them.** Secrets are masked *before* anything is written to disk.

Pure Python standard library. No dependencies. One file you could read in a sitting.

## Install

```bash
pipx install sessionkeep   # recommended (isolated, puts `sessionkeep` on your PATH)
# or
pip install sessionkeep
```

Zero dependencies, so it's quick either way. You can also install straight from
source:

```bash
pip install git+https://github.com/lug-works/sessionkeep.git
```

Or clone and install in editable mode for hacking on it:

```bash
git clone https://github.com/lug-works/sessionkeep.git
cd sessionkeep
pip install -e .
```

## Usage

### Archive a transcript file

```bash
sessionkeep archive /path/to/session.jsonl
# [sessionkeep] archived 1423 lines (2 masked) -> ~/.sessionkeep/sessions/2026/06/2026-06-05_1430_my-project_a1b2c3d4.jsonl.gz
```

Check what *would* be masked, without writing anything:

```bash
sessionkeep archive /path/to/session.jsonl --dry-run
```

Choose where archives live (overrides `$SESSIONKEEP_DIR`):

```bash
sessionkeep archive session.jsonl --out ~/backups/agent-sessions
```

### Auto-archive every Claude Code session

`sessionkeep hook` reads a Claude Code `SessionEnd` hook payload from stdin.
Add this to your Claude Code `settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "sessionkeep hook" } ] }
    ]
  }
}
```

Now every session is masked and archived automatically when it ends. The hook is
deliberately fail-safe: if anything goes wrong it exits quietly without
disrupting your agent.

### Import Codex CLI sessions

Codex CLI has no end-of-session hook, but it writes rollout transcripts to
`$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`. `sessionkeep import` discovers
them and archives anything not already saved (safe to run repeatedly):

```bash
sessionkeep import --codex
# [sessionkeep] Codex: archived 7, skipped 23 already-archived
```

Run it on a schedule (cron / Task Scheduler) to keep a masked, compressed mirror
of your Codex history. You can also import any directory of transcripts —
including Claude Code's own transcript tree, to catch sessions that ended without
firing `SessionEnd` (a GUI window close or a crash):

```bash
sessionkeep import --from ./logs --pattern '*.jsonl'
sessionkeep import --from ~/.claude/projects   # catch-up for missed Claude Code sessions
```

For scheduled catch-up scans, add `--min-age MIN` to skip transcripts modified in
the last `MIN` minutes. This leaves still-active sessions alone, so an in-progress
transcript is never frozen as a partial copy and marked already-archived:

```bash
sessionkeep import --codex --min-age 30
sessionkeep import --from ~/.claude/projects --min-age 30
```

### Browse and search your archive

```bash
sessionkeep list                      # newest first: when, project, lines, masked, size
sessionkeep list --limit 10
sessionkeep list --project my-repo     # filter by project
sessionkeep list --since 2026-06-01    # only on/after a date
sessionkeep list --json                # full metadata as JSON (for scripting)
sessionkeep search "TypeError"         # grep across all archived (masked) transcripts
sessionkeep search "token" -i --max 50
```

Search runs against the **masked** contents, so secrets never resurface in
results.

## Custom masking patterns

The built-in patterns cover common providers, but you'll often have your own
secrets — internal hostnames, customer IDs, bespoke token formats. Add them in a
JSON config at `~/.sessionkeep/config.json` (or `$SESSIONKEEP_CONFIG`, or
`--config PATH`):

```json
{
  "mask_patterns": [
    { "pattern": "ACME-[0-9]{6}", "replacement": "ACME-***MASKED***" }
  ],
  "mask_literals": ["internal-host.corp", "my-customer-name"]
}
```

- `mask_patterns` — regexes. Give a string for shorthand, or an object with an
  optional `replacement`.
- `mask_literals` — plain strings (escaped automatically) for when you don't want
  to write a regex.

Custom rules are applied **in addition to** the built-ins. An invalid config
fails loudly (the command stops) rather than archiving something unmasked — the
one exception is the `hook` command, which falls back to built-in masking so it
can never break your agent.

## What gets masked

Best-effort pattern matching for common secret shapes, including:

| Provider | Examples |
|---|---|
| Anthropic | `sk-ant-…` |
| OpenAI | `sk-…`, `sk-proj-…` |
| GitHub | `ghp_…`, `gho_…`, `ghu_…`, `ghs_…`, `github_pat_…` |
| GitLab | `glpat-…` |
| AWS | `AKIA…`, `ASIA…` |
| Google / GCP | `AIza…`, `ya29.…` |
| Slack | `xoxb-…` etc. |
| Stripe | `sk_live_…`, `rk_live_…` |
| Generic | `Bearer <token>`, PEM private keys |

Masking is **insurance, not a guarantee** — patterns can't catch everything.
Treat archived logs as sensitive. The archive directory is meant to stay
local and out of version control (it lives under `~` by default).

## Output layout

```
~/.sessionkeep/sessions/
└── 2026/06/
    ├── 2026-06-05_1430_my-project_a1b2c3d4.jsonl.gz   # masked, compressed transcript
    └── 2026-06-05_1430_my-project_a1b2c3d4.meta.json  # session id, sizes, masked-line count
```

Filenames encode date, time, project (derived from the working directory), and a
short session id — so they're easy to grep and sort.

## Roadmap

- Structured (per-message) views of Codex rollout / Claude transcripts
- Retention / pruning policies (e.g. keep last N, drop after M months)
- A `--redact-only` mode that masks in place without archiving

Contributions welcome — see [CHANGELOG.md](CHANGELOG.md).

## License

MIT
