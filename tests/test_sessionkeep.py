"""Tests for sessionkeep. Uses fake, non-functional tokens only."""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import os

import pytest

from sessionkeep import (
    archive_transcript,
    archived_sources,
    import_transcripts,
    iter_archive_meta,
    mask_secrets,
    search_archives,
)
from sessionkeep.archiver import default_archive_dir, derive_project_slug
from sessionkeep.config import build_masker, extra_patterns_from_config, load_config
from sessionkeep.discovery import filter_settled, find_codex_sessions, source_session_id
from sessionkeep.masking import Masker

# Fake tokens: correct *shape*, never real credentials.
FAKE_OPENAI = "sk-proj-" + "A1b2C3d4" * 5
FAKE_ANTHROPIC = "sk-ant-" + "Zz9Yy8Xx" * 4
FAKE_GITHUB = "ghp_" + "abcDEF123456" * 2
FAKE_AWS = "AKIA" + "ABCDEFGH12345678"[:16]


@pytest.mark.parametrize(
    "secret",
    [FAKE_OPENAI, FAKE_ANTHROPIC, FAKE_GITHUB, FAKE_AWS],
)
def test_known_secrets_are_masked(secret):
    masked = mask_secrets(f"my key is {secret} ok")
    assert secret not in masked
    assert "MASKED" in masked


def test_pem_private_key_masked():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA1234567890\n"
        "-----END RSA PRIVATE KEY-----"
    )
    masked = mask_secrets(pem)
    assert "PRIVATE_KEY_MASKED" in masked
    assert "1234567890" not in masked


def test_ordinary_text_untouched():
    text = "just a normal log line with no secrets, value=42\n"
    assert mask_secrets(text) == text


def test_derive_project_slug():
    assert derive_project_slug("/home/me/my-project") == "my-project"
    assert derive_project_slug("/home/me/proj_v2") == "proj_v2"
    # Non-ASCII components collapse away; fall back to a safe default.
    assert derive_project_slug("/home/me/プロジェクト") == "unknown"
    assert derive_project_slug("") == "unknown"


def test_default_archive_dir_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSIONKEEP_DIR", str(tmp_path / "custom"))
    assert default_archive_dir() == tmp_path / "custom"
    monkeypatch.delenv("SESSIONKEEP_DIR", raising=False)
    assert default_archive_dir().name == "sessions"


def _write_transcript(tmp_path):
    src = tmp_path / "session.jsonl"
    src.write_text(
        '{"role": "user", "text": "here is my key ' + FAKE_OPENAI + '"}\n'
        '{"role": "assistant", "text": "ok, ignoring it"}\n',
        encoding="utf-8",
    )
    return src


def test_archive_writes_masked_gzip_and_meta(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    now = _dt.datetime(2026, 6, 5, 14, 30)

    meta = archive_transcript(
        src, out_dir=out, session_id="abcdef123456", cwd="/x/demo-proj", now=now
    )

    archive_path = out / "2026" / "06" / "2026-06-05_1430_demo-proj_abcdef12.jsonl.gz"
    assert archive_path.exists()
    assert meta["line_count"] == 2
    assert meta["masked_lines"] == 1
    assert meta["project_slug"] == "demo-proj"

    with gzip.open(archive_path, "rt", encoding="utf-8") as fh:
        content = fh.read()
    assert FAKE_OPENAI not in content
    assert "MASKED" in content

    meta_path = out / "2026" / "06" / "2026-06-05_1430_demo-proj_abcdef12.meta.json"
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 1


def test_dry_run_writes_nothing(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    meta = archive_transcript(src, out_dir=out, dry_run=True)
    assert meta["dry_run"] is True
    assert meta["masked_lines"] == 1
    assert not out.exists()


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        archive_transcript(tmp_path / "nope.jsonl", out_dir=tmp_path)


def test_no_clobber_on_repeat(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    now = _dt.datetime(2026, 6, 5, 14, 30)
    m1 = archive_transcript(src, out_dir=out, session_id="dup12345", now=now)
    m2 = archive_transcript(src, out_dir=out, session_id="dup12345", now=now)
    assert m1["archive_path"] != m2["archive_path"]


def test_source_stored_as_absolute(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    meta = archive_transcript(src, out_dir=out)
    assert os.path.isabs(meta["source"])


# ---- list / search / import -----------------------------------------------------


def test_iter_archive_meta_newest_first(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    archive_transcript(src, out_dir=out, session_id="aaa11111", now=_dt.datetime(2026, 6, 1, 9, 0))
    archive_transcript(src, out_dir=out, session_id="bbb22222", now=_dt.datetime(2026, 6, 5, 9, 0))
    metas = iter_archive_meta(out)
    assert len(metas) == 2
    assert metas[0]["session_id"] == "bbb22222"  # newest first
    assert all("_archive_path" in m for m in metas)


def test_search_finds_masked_content(tmp_path):
    src = _write_transcript(tmp_path)
    out = tmp_path / "archive"
    archive_transcript(src, out_dir=out)
    # the secret was masked, so we can find the placeholder but not the secret
    assert search_archives("MASKED", out)
    assert search_archives(FAKE_OPENAI, out) == []
    assert search_archives("ASSISTANT", out, ignore_case=True)


def test_search_max_results(tmp_path):
    out = tmp_path / "archive"
    src = tmp_path / "many.jsonl"
    src.write_text("hit\nhit\nhit\n", encoding="utf-8")
    archive_transcript(src, out_dir=out)
    assert len(search_archives("hit", out, max_results=2)) == 2


def test_import_dedupes(tmp_path):
    out = tmp_path / "archive"
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text('{"t":"one"}\n', encoding="utf-8")
    b.write_text('{"t":"two"}\n', encoding="utf-8")

    r1 = import_transcripts([a, b], out_dir=out)
    assert len(r1["archived"]) == 2
    assert r1["skipped"] == []

    # second run: both already archived -> all skipped
    r2 = import_transcripts([a, b], out_dir=out)
    assert r2["archived"] == []
    assert len(r2["skipped"]) == 2

    assert archived_sources(out) == {os.path.abspath(a), os.path.abspath(b)}


def test_import_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "archive"
    a = tmp_path / "a.jsonl"
    a.write_text('{"t":"one"}\n', encoding="utf-8")
    r = import_transcripts([a], out_dir=out, dry_run=True)
    assert len(r["archived"]) == 1
    assert r["archived"][0]["dry_run"] is True
    assert not out.exists()


def test_source_session_id():
    assert source_session_id("rollout-2025-01-22T10-30-00-abc123.jsonl") == "abc123"
    assert source_session_id("plain.jsonl") == "plain"


def test_filter_settled_keeps_idle_drops_active(tmp_path):
    old = tmp_path / "old.jsonl"
    fresh = tmp_path / "fresh.jsonl"
    old.write_text("x\n", encoding="utf-8")
    fresh.write_text("y\n", encoding="utf-8")
    # Make `old` look modified 1 hour ago; `fresh` modified just now.
    now = 1_000_000.0
    os.utime(old, (now - 3600, now - 3600))
    os.utime(fresh, (now, now))
    # min age 30 min: only `old` survives.
    kept = filter_settled([old, fresh], 30 * 60, now=now)
    assert kept == [old]


def test_filter_settled_zero_age_keeps_all(tmp_path):
    a = tmp_path / "a.jsonl"
    a.write_text("x\n", encoding="utf-8")
    assert filter_settled([a], 0) == [a]


def test_find_codex_sessions_missing_home(tmp_path):
    assert find_codex_sessions(tmp_path / "nope") == []


def test_find_codex_sessions_discovers_rollouts(tmp_path):
    day = tmp_path / "sessions" / "2026" / "06" / "05"
    day.mkdir(parents=True)
    roll = day / "rollout-2026-06-05T10-00-00-zzz999.jsonl"
    roll.write_text('{"type":"message","payload":{}}\n', encoding="utf-8")
    (day / "not-a-rollout.txt").write_text("ignore", encoding="utf-8")
    found = find_codex_sessions(tmp_path)
    assert found == [roll]


# ---- config / custom masking ----------------------------------------------------


def test_extra_patterns_regex_and_literal():
    config = {
        "mask_patterns": [{"pattern": r"ACME-\d{4}", "replacement": "ACME-***"}],
        "mask_literals": ["internal.host.corp"],
    }
    masker = Masker(extra_patterns_from_config(config))
    out = masker.mask("see ACME-1234 at internal.host.corp now")
    assert "ACME-1234" not in out and "ACME-***" in out
    assert "internal.host.corp" not in out
    # built-ins still apply
    assert masker.mask(FAKE_ANTHROPIC).startswith("sk-ant-***")


def test_extra_patterns_string_shorthand():
    masker = Masker(extra_patterns_from_config({"mask_patterns": ["TOPSECRET[0-9]+"]}))
    assert "TOPSECRET99" not in masker.mask("x TOPSECRET99 y")


def test_invalid_regex_raises():
    with pytest.raises(ValueError):
        extra_patterns_from_config({"mask_patterns": [{"pattern": "([unclosed"}]})


def test_load_config_missing_default_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSIONKEEP_CONFIG", str(tmp_path / "absent.json"))
    assert load_config() == {}


def test_load_config_explicit_missing_raises(tmp_path):
    with pytest.raises(ValueError):
        load_config(tmp_path / "absent.json")


def test_build_masker_from_file_applies_in_archive(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"mask_literals": ["banana-token-42"]}), encoding="utf-8")
    src = tmp_path / "s.jsonl"
    src.write_text('{"t":"my banana-token-42 here"}\n', encoding="utf-8")
    out = tmp_path / "archive"
    masker = build_masker(cfg)
    meta = archive_transcript(src, out_dir=out, masker=masker)
    assert meta["masked_lines"] == 1
    assert search_archives("banana-token-42", out) == []
    assert search_archives("MASKED", out)
