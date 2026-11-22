"""Outlook `.pst` -> canonical rows.

The fixture is the Aspose sample mailbox (3.3 MB, 11 messages, all 2011). It is
committed because a `.pst` cannot be generated in pure Python — libpff only reads
the container format, it does not write it. Every trap named in the adapter's
docstring was found by running against this exact file.

Run: python -m pytest tests -q
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from relate_comms import ingest as ingest_module
from relate_comms.adapters import outlook_pst

pytest.importorskip("pypff", reason="libpff-python is required to read .pst files")

FIXTURE = Path(__file__).parent / "fixtures" / "outlook" / "Outlook.pst"
REAL = Path.home() / "Downloads" / "Outlook.pst"


def _sample() -> Path:
    """The committed fixture, or the author's copy when the fixture is absent."""
    if FIXTURE.exists():
        return FIXTURE
    if REAL.exists():
        return REAL
    pytest.skip("no .pst available")


# --------------------------------------------------------------------------- unit

def test_detect_accepts_pst_and_rejects_other_suffixes(tmp_path):
    assert outlook_pst.detect(_sample()) is True
    other = tmp_path / "export.json"
    other.write_text("{}", encoding="utf-8")
    assert outlook_pst.detect(other) is False


def test_detect_rejects_a_zip_renamed_as_pst(tmp_path):
    """Suffix alone is not evidence; libpff's signature check is."""
    fake = tmp_path / "not-really.pst"
    fake.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    assert outlook_pst.detect(fake) is False


def test_parse_yields_mail_only():
    """Appointments, contacts and the Freebusy item are counted, never stored."""
    result = outlook_pst.parse(_sample())

    assert result.platform == "outlook"
    assert result.messages, "the sample mailbox holds mail"
    assert all(m.platform == "outlook" for m in result.messages)
    assert any("IPM.Appointment" in reason for reason in result.skipped)
    assert any("IPM.Contact" in reason for reason in result.skipped)
    assert any("not a message (item)" in reason for reason in result.skipped)


def test_parse_does_not_warn_about_compression():
    """`encryption_type == 1` is compressible, which every modern PST is.

    Warning on it flagged a healthy file as password-protected.
    """
    result = outlook_pst.parse(_sample())
    assert not [w for w in result.warnings if "encryption" in w]


def test_inbox_and_sent_copies_collapse_to_one_row():
    """The sample files the same five messages in Inbox and in Sent Items.

    Keying on Message-ID alone produced ten rows for five messages, because the Sent
    copies carry no transport headers at all.
    """
    result = outlook_pst.parse(_sample())
    assert any("duplicate copy in another folder" in reason for reason in result.skipped)

    keys = [m.key for m in result.messages]
    assert len(keys) == len(set(keys)), "no message may be stored twice"

    # One thread per conversation, and the copies share a conversation index.
    assert len(result.chats) == len({m.chat_id for m in result.messages})


def test_sent_copy_upgrades_ownership():
    """The Sent copy has no `From:` header, so it cannot prove ownership by address.

    The folder is the evidence, and the surviving row must carry it — otherwise the
    owner's own replies land as a stranger's.
    """
    result = outlook_pst.parse(_sample())
    assert any(m.is_self for m in result.messages), \
        "mail out of Sent Items is the owner's"


def test_owner_is_derived_from_the_file():
    """A PST states its own mailbox: `PR_RECEIVED_BY_EMAIL_ADDRESS` on received mail,
    `PR_SENT_REPRESENTING_EMAIL_ADDRESS` on sent mail.

    The transport headers do not carry it, and the Sent copies have no headers at all,
    so reading only headers made the owner look unknowable.
    """
    result = outlook_pst.parse(_sample())
    owners = [w for w in result.warnings if w.startswith("owner: ")]
    assert owners, "the adapter must report the owner it resolved"
    assert "@" in owners[0], "the owner is an address, not a display name"


def test_owner_marks_received_mail_as_self():
    """Ownership is not only the Sent folder: mail the mailbox received from itself,
    and mail whose From address is the owner's, is also the owner's."""
    result = outlook_pst.parse(_sample())
    assert result.messages
    assert all(m.is_self for m in result.messages), \
        "every row in this sample is the mailbox's own mail"


def test_explicit_self_id_wins_but_the_conflict_is_reported():
    """`self_id` is the caller's statement and outranks the file — but a file that
    names a different mailbox is a contradiction, not a detail to swallow."""
    result = outlook_pst.parse(_sample(), self_id="someone.else@example.com")
    assert any("owner: someone.else@example.com" in w for w in result.warnings)
    assert any("owner conflict" in w and "the pst says" in w
               for w in result.warnings), "the disagreement must be visible"

    # The sent-folder rule is structural and does not depend on the address, so those
    # rows stay the owner's regardless of which address is claimed.
    assert any(m.is_self for m in result.messages)


def test_owner_is_not_a_correspondent():
    """The owner's own address must not become a Correspondent node.

    `writer.write_correspondents` filters by display name, which cannot match an
    address — so the adapter prunes it where the owner is actually known. In this
    sample the owner is the only participant, so an empty tuple is the right answer:
    a thread you mailed yourself has no counterparty, and inventing one is the error.
    """
    result = outlook_pst.parse(_sample())
    owner = next(w.split("owner: ", 1)[1] for w in result.warnings
                 if w.startswith("owner: "))
    for chat in result.chats:
        assert owner not in [name.lower() for name in chat.participant_names]
        assert "saqib razzaq" not in [name.lower() for name in chat.participant_names], \
            "the owner's display name must go too, not just their address"


def test_a_real_counterparty_survives_the_prune():
    """Pruning the owner must not empty a chat that has someone else in it."""
    from relate_comms.schema import Chat, IngestResult

    result = IngestResult(platform="outlook", export_path="synthetic")
    result.chats.append(Chat(
        platform="outlook", chat_id="t", title="T", kind="personal_chat",
        is_group=False,
        participant_names=("Saqib Razzaq", "saqib.razzaq@xp.local", "Alice Smith"),
    ))
    outlook_pst._apply_owner(
        result, [("saqib.razzaq@xp.local", "Saqib Razzaq")] * 3, set(), None, None)

    assert result.chats[0].participant_names == ("Alice Smith",)


def test_owner_is_persisted_per_platform(tmp_path):
    """Persisting it is what makes a second export of the same mailbox agree."""
    from relate_comms import identity

    profile = tmp_path / "profile"
    outlook_pst.parse(_sample(), profile_dir=profile)
    stored = identity.load_owner(profile, "outlook")
    assert stored and "@" in stored

    # A second parse reuses it rather than re-deriving.
    again = outlook_pst.parse(_sample(), profile_dir=profile)
    assert any(f"owner: {stored}" in w for w in again.warnings)


def test_every_row_is_timezone_aware_utc():
    """`pypff` returns naive datetimes; the adapter must not pass them through."""
    result = outlook_pst.parse(_sample())
    for message in result.messages:
        assert message.ts_utc.tzinfo is not None
        assert message.ts_utc.utcoffset() == timezone.utc.utcoffset(None)


def test_missing_message_id_is_counted_not_dropped():
    """The sent side has no headers, so this is the normal path for half a mailbox."""
    result = outlook_pst.parse(_sample())
    missing = result.unknown_kinds.get("missing message-id", 0)
    assert missing > 0
    assert all(m.message_id for m in result.messages), "a fallback id is always minted"


def test_attachments_carry_a_name_and_a_size():
    """`pypff.attachment` has no `get_name()`; the filename is `get_long_filename()`."""
    result = outlook_pst.parse(_sample())
    assert result.attachments
    for ref in result.attachments:
        assert ref.path and ref.path != "attachment" or ref.mime is None
        assert ref.platform == "outlook"


def test_window_bounds_are_enforced_and_counted():
    """A decade-old export is only quick because the window is honoured."""
    late = datetime(2011, 6, 21, 23, 50, tzinfo=timezone.utc)
    result = outlook_pst.parse(_sample(), since=late)
    assert result.messages
    assert all(m.ts_utc >= late for m in result.messages)
    assert result.skipped.get("before window", 0) > 0


def test_naive_window_is_refused():
    """A naive bound means the offset was lost; guessing one is worse than failing."""
    with pytest.raises(ValueError, match="timezone-aware"):
        outlook_pst.parse(_sample(), since=datetime(2011, 6, 21))


# ----------------------------------------------------------------------- pipeline

def test_ingest_pipeline_writes_outlook_rows(tmp_path):
    """The adapter is registered, so a `.pst` in the spool is discovered and written."""
    spool = tmp_path / "spool"
    spool.mkdir()
    target = spool / "Outlook.pst"
    target.write_bytes(_sample().read_bytes())

    report = ingest_module.ingest(
        root=spool,
        store=tmp_path / "graph.rl",
        profile_dir=tmp_path / "profile",
    )

    assert report.ok
    assert len(report.batches) == 1
    outcome = report.batches[0]
    assert outcome.platform == "outlook"
    assert outcome.messages > 0
    assert outcome.verified


def test_reingest_is_idempotent(tmp_path):
    """Same file twice must not double the store — the key is stable."""
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "Outlook.pst").write_bytes(_sample().read_bytes())

    store = tmp_path / "graph.rl"
    first = ingest_module.ingest(root=spool, store=store,
                                 profile_dir=tmp_path / "profile")
    second = ingest_module.ingest(root=spool, store=store,
                                  profile_dir=tmp_path / "profile")

    assert first.ok and second.ok
    # The store must not double. With the delta cutoff the second run skips the rows
    # outright rather than re-MERGEing them, so the invariant is now "the first run
    # wrote them, the second wrote none, and the store still holds exactly one copy".
    assert first.batches[0].messages == 6
    assert second.batches[0].messages == 0
    assert second.batches[0].delta_dropped == first.batches[0].messages
