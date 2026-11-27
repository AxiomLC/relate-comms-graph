"""The spool scaffold: one definition, used by a fresh clone and by a wipe.

The bug this fixes: `delete_spool` unlinked files and left every directory any previous
ingest had created, so the spool became a skeleton of empty folders that looked like
data. The scaffold is now rebuilt after a wipe, so "empty" means the same thing in both
places.
"""
from __future__ import annotations

import pytest

from relate_comms import paths, tools


@pytest.fixture()
def spool(tmp_path, monkeypatch):
    root = tmp_path / "real"
    monkeypatch.setattr(paths, "real_dir", lambda: root)
    return root


def test_the_scaffold_mirrors_the_sample_writer_out_tree(spool):
    paths.ensure_spool_scaffold(spool)

    made = sorted(
        str(p.relative_to(spool)).replace("\\", "/")
        for p in spool.rglob("*") if p.is_dir()
    )
    assert made == [
        "email", "email/email_eml",
        "linkedin", "linkedin/linkedin_zip",
        "messenger", "messenger/messenger_zip",
        "outlook", "outlook/outlook_copy",
        "sms", "sms/sms_xml",
        "telegram", "telegram/Telegram Desktop",
        "whatsapp", "whatsapp/whatsapp_html",
    ]


def test_there_is_no_imap_or_gmail_folder(spool):
    """A live mailbox is fetched, not staged — those folders were never written to."""
    paths.ensure_spool_scaffold(spool)

    assert not (spool / "imap").exists()
    assert not (spool / "gmail").exists()


def test_the_scaffold_is_idempotent(spool):
    paths.ensure_spool_scaffold(spool)
    paths.ensure_spool_scaffold(spool)

    assert (spool / "telegram" / "Telegram Desktop").is_dir()


def test_a_wipe_leaves_the_scaffold_and_nothing_else(spool):
    paths.ensure_spool_scaffold(spool)
    # Pollute it the way real ingests did: junk folders and files at several depths.
    (spool / "unrecognised" / "Telegram Desktop").mkdir(parents=True)
    (spool / "telegram" / "ChatExport_2026-01-01").mkdir(parents=True)
    (spool / "email" / "Inbox" / "thread-1").mkdir(parents=True)
    (spool / "email" / "Inbox" / "thread-1" / "a.eml").write_text("x", encoding="utf-8")
    (spool / "outlook" / "outlook_copy" / "Outlook.pst").write_bytes(b"pst")

    tools.delete_spool(write_enabled=True, confirm=True)

    remaining = sorted(
        str(p.relative_to(spool)).replace("\\", "/")
        for p in spool.rglob("*") if p.is_dir()
    )
    assert remaining == [
        "email", "email/email_eml",
        "linkedin", "linkedin/linkedin_zip",
        "messenger", "messenger/messenger_zip",
        "outlook", "outlook/outlook_copy",
        "sms", "sms/sms_xml",
        "telegram", "telegram/Telegram Desktop",
        "whatsapp", "whatsapp/whatsapp_html",
    ]
    assert not any(p.is_file() for p in spool.rglob("*"))


def test_a_wipe_removes_files_at_any_depth(spool):
    paths.ensure_spool_scaffold(spool)
    deep = spool / "email" / "email_eml" / "Inbox" / "t" / "m"
    deep.mkdir(parents=True)
    (deep / "1.eml").write_text("x", encoding="utf-8")

    result = tools.delete_spool(write_enabled=True, confirm=True)

    assert result["count"] == 1
    assert not deep.exists()


def test_a_wipe_keeps_gitkeep(spool):
    paths.ensure_spool_scaffold(spool)
    (spool / ".gitkeep").write_text("", encoding="utf-8")

    tools.delete_spool(write_enabled=True, confirm=True)

    assert (spool / ".gitkeep").exists()


def test_a_wipe_needs_confirm(spool):
    with pytest.raises(tools.ToolError, match="confirm"):
        tools.delete_spool(write_enabled=True, confirm=False)
