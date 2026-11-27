"""Staging a variant tree takes one artifact per platform.

`sample_writer/out/` holds several packagings of the same conversations. Ingesting more
than one stores every message twice, so `stage()` narrows a variant tree to the canonical
artifact per platform — and must never narrow anything else.
"""
from __future__ import annotations

import pytest

from relate_comms import ingest, paths


def _tree(root, *names):
    for name in names:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "payload.txt").write_text("x", encoding="utf-8")
    return root


def test_a_variant_tree_is_narrowed_to_one_per_platform(tmp_path):
    out = tmp_path / "out"
    _tree(out, "email/email_eml", "linkedin/linkedin_zip", "linkedin/linkedin_dir",
          "messenger/messenger_zip", "messenger/messenger_dir",
          "sms/sms_xml", "sms/sms_xml_zip", "sms/sms_json_app",
          "telegram/Telegram Desktop", "whatsapp/whatsapp_html", "whatsapp/whatsapp_web")

    chosen = ingest._canonical_children(out)

    assert chosen is not None
    names = sorted(path.name for path, _ in chosen)
    assert names == [
        "Telegram Desktop", "email_eml", "linkedin_zip",
        "messenger_zip", "sms_xml", "whatsapp_html",
    ]


def test_each_artifact_carries_its_platform(tmp_path):
    """The platform comes from the table: a folder holding a zip is not detectable."""
    out = tmp_path / "out"
    _tree(out, "email/email_eml", "messenger/messenger_zip", "sms/sms_xml")

    chosen = dict((path.name, platform) for path, platform in ingest._canonical_children(out))

    assert chosen == {"email_eml": "email", "messenger_zip": "messenger", "sms_xml": "sms"}


def test_the_pst_is_never_part_of_a_bulk_drop(tmp_path):
    out = tmp_path / "out"
    _tree(out, "email/email_eml", "outlook/outlook_copy", "sms/sms_xml")

    chosen = ingest._canonical_children(out)

    assert chosen is not None
    assert all("outlook" not in str(path).lower() for path, _ in chosen)


def test_a_single_platform_folder_is_not_narrowed(tmp_path):
    """`out/messenger/` holds two variants but is not a whole world."""
    folder = tmp_path / "messenger"
    _tree(folder, "messenger_zip", "messenger_dir")

    assert ingest._canonical_children(folder) is None


def test_a_real_download_folder_is_not_narrowed(tmp_path):
    folder = tmp_path / "Downloads"
    _tree(folder, "some_export")

    assert ingest._canonical_children(folder) is None


def test_the_spool_is_never_narrowed(tmp_path, monkeypatch):
    """The spool already holds one export per platform; re-narrowing would skip real data."""
    spool = tmp_path / "spool" / "real"
    _tree(spool, "email/email_eml", "messenger/messenger_zip", "sms/sms_xml")
    monkeypatch.setattr(paths, "real_dir", lambda: spool)

    assert ingest._canonical_children(spool) is None


def test_a_non_directory_is_not_narrowed(tmp_path):
    payload = tmp_path / "chat.zip"
    payload.write_text("x", encoding="utf-8")

    assert ingest._canonical_children(payload) is None
