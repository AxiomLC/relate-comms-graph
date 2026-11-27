"""Staging replaces a fixed-name export instead of skipping it.

`Outlook.pst` and `email_eml/` never change their name, so a re-export collides with the
copy already in the spool. Skipping meant the new snapshot never landed and the ingest
re-read the old one — the delta then found nothing new, forever, with no error.
"""
from __future__ import annotations

import pytest

from relate_comms import ingest, paths


@pytest.fixture()
def spool(tmp_path, monkeypatch):
    root = tmp_path / "real"
    monkeypatch.setattr(paths, "real_dir", lambda: root)
    paths.ensure_spool_scaffold(root)
    return root


def test_a_fixed_name_file_is_replaced(spool, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    payload = source / "Outlook.pst"

    payload.write_bytes(b"first export")
    ingest.stage([payload], root=spool)

    payload.write_bytes(b"second export, newer")
    ingest.stage([payload], root=spool)

    landed = list(spool.rglob("Outlook.pst"))
    assert len(landed) == 1
    assert landed[0].read_bytes() == b"second export, newer"


def test_a_fixed_name_folder_is_replaced(spool, tmp_path):
    source = tmp_path / "src"
    mailbox = source / "email_eml"
    (mailbox / "Inbox" / "thread-1").mkdir(parents=True)
    (mailbox / "Inbox" / "thread-1" / "a.eml").write_text("old", encoding="utf-8")

    ingest.stage([mailbox], root=spool)

    # The re-export has the same folder name and a different message.
    (mailbox / "Inbox" / "thread-1" / "a.eml").write_text("new", encoding="utf-8")
    (mailbox / "Inbox" / "thread-2").mkdir(parents=True)
    (mailbox / "Inbox" / "thread-2" / "b.eml").write_text("added", encoding="utf-8")
    ingest.stage([mailbox], root=spool)

    landed = list(spool.rglob("a.eml"))
    assert len(landed) == 1
    assert landed[0].read_text(encoding="utf-8") == "new"
    # The new thread landed too — a replace, not a merge of stale and fresh.
    assert list(spool.rglob("b.eml"))


def test_a_dated_export_keeps_both(spool, tmp_path):
    """Dated filenames never collide, so both weeks stay until prune removes the old."""
    source = tmp_path / "src"
    source.mkdir()

    first = source / "whatsapp-chats-20261125.zip"
    first.write_bytes(b"week one")
    ingest.stage([first], root=spool)

    second = source / "whatsapp-chats-20261202.zip"
    second.write_bytes(b"week two")
    ingest.stage([second], root=spool)

    names = sorted(p.name for p in spool.rglob("*.zip"))
    assert names == ["whatsapp-chats-20261125.zip", "whatsapp-chats-20261202.zip"]
