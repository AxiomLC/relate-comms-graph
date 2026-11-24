"""Stage 3 acceptance: SMS Backup & Restore `.xml` -> canonical rows.

Every test here exists because the real 825 MB export broke something. The
synthetic fixture always runs; the real file is used when present.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from relate_comms.adapters import sms

# The sample world the app itself generates, not a personal export. It is a realistic
# Android `SMS Backup & Restore` download — the same shape a phone produces — and it is
# committed to `spool/real/`, so these tests run on any clone.
#
# **Text only, deliberately.** The generator writes no MMS, so the MMS-specific tests
# below use synthetic fixtures. That is not a gap: this app stores text, and an MMS
# attachment is a reference the graph never reads.
REAL_EXPORT = Path(__file__).resolve().parents[1] / "spool" / "real" / "sms" / "sms-20261101000000.xml"
_REAL = REAL_EXPORT if REAL_EXPORT.exists() else None

# The sample world's owner is not named in the export (no MMS, so no `<addrs>` to derive
# it from). `is_self` is still correct because SMS states direction per row.
OWNER = "+19174004025"


def _xml_text(body: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<smses count="0" backup_set="x" backup_date="1" type="full">\n'
            f'{body}\n</smses>')


def _xml(tmp_path: Path, body: str, name: str = "backup.xml") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    target = tmp_path / name
    target.write_text(_xml_text(body), encoding="utf-8")
    return target


def _sms(address: str, date: int, body: str = "hi", *, type_: str = "1",
         contact: str = "(Unknown)", date_sent: str | None = None) -> str:
    sent = f' date_sent="{date_sent}"' if date_sent is not None else ""
    return (f'<sms address="{address}" date="{date}" type="{type_}" body="{body}"'
            f' contact_name="{contact}"{sent} />')


def _mms(date: int, addrs: list[tuple[str, str]], *, msg_box: str = "1",
         address: str = "", contact: str = "(Unknown)", text: str = "hello",
         m_type: str = "132", extra_parts: str = "") -> str:
    addr_xml = "".join(f'<addr address="{a}" type="{t}" />' for a, t in addrs)
    return (f'<mms date="{date}" msg_box="{msg_box}" m_type="{m_type}"'
            f' address="{address}" contact_name="{contact}">'
            f'<parts><part seq="0" ct="text/plain" text="{text}" />{extra_parts}</parts>'
            f'<addrs>{addr_xml}</addrs></mms>')


# --------------------------------------------------------------------------- detect

def test_detect_accepts_smses_root(tmp_path):
    assert sms.detect(_xml(tmp_path, _sms("+15551234567", 1630048763654)))


def test_detect_refuses_a_call_log(tmp_path):
    """Same app, wrong export. A `<calls` document is not messages."""
    path = tmp_path / "calls.xml"
    path.write_text('<calls count="3" backup_set="x"><call number="1" /></calls>',
                    encoding="utf-8")
    assert not sms.detect(path)


def test_detect_refuses_an_unrelated_xml(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text('<?xml version="1.0"?><rss><channel /></rss>', encoding="utf-8")
    assert not sms.detect(path)


def test_detect_sees_inside_a_compressed_backup(tmp_path):
    """`.xml.zip` is what SyncTech's "compress backup" writes, and `parse()` reads it.

    Detection used to read the zip's raw bytes and look for `<smses` in them, which
    always failed because the bytes are compressed — so the one format the parser
    supports was the one the detector could never route to it.
    """
    import zipfile

    from relate_comms import ingest as ingest_module

    path = tmp_path / "sms-20261116212209.xml.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sms-20261116212209.xml",
                         _xml_text(_sms("+15551234567", 1630048763654)))

    assert sms.detect(path)
    assert ingest_module.detect_platform(path) == "sms"


def test_detect_refuses_a_compressed_call_log(tmp_path):
    """The refusal must survive the unwrap: same app, wrong export."""
    import zipfile

    path = tmp_path / "calls.xml.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("calls.xml",
                         '<calls count="1" backup_set="x"><call number="1" /></callsy>')
    assert not sms.detect(path)


def test_detect_refuses_a_zip_with_no_xml(tmp_path):
    import zipfile

    path = tmp_path / "not-sms.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "hello")
    assert not sms.detect(path)


# --------------------------------------------------------------------------- sms rows

def test_direction_is_structural(tmp_path):
    """`type=2` is sent. No owner inference is needed to get `is_self` right."""
    path = _xml(tmp_path, "\n".join([
        _sms("+15551234567", 1630048763654, "incoming", type_="1"),
        _sms("+15551234567", 1630048764000, "outgoing", type_="2"),
    ]))
    result = sms.parse(path)
    assert [m.is_self for m in result.messages] == [False, True]
    assert result.messages[0].sender_name == "+15551234567"
    assert result.messages[1].sender_name == ""


def test_date_sent_mixed_units_in_one_file(tmp_path):
    """4,272 rows are seconds and 5,168 are milliseconds in the real file."""
    path = _xml(tmp_path, "\n".join([
        _sms("+15551234567", 1630048763),        # seconds
        _sms("+15551234567", 1630048764000),     # milliseconds
    ]))
    result = sms.parse(path)
    assert result.messages[0].ts_utc == datetime(2021, 8, 27, 7, 19, 23, tzinfo=timezone.utc)
    assert result.messages[1].ts_utc == datetime(2021, 8, 27, 7, 19, 24, tzinfo=timezone.utc)


def test_null_is_a_string_not_a_value(tmp_path):
    path = _xml(tmp_path, _sms("+15551234567", 1630048763654, "x",
                               contact="null", date_sent="null"))
    result = sms.parse(path)
    assert result.messages[0].sender_name == "+15551234567"


def test_row_with_no_address_is_skipped_and_counted(tmp_path):
    path = _xml(tmp_path, _sms("null", 1630048763654))
    result = sms.parse(path)
    assert result.messages == []
    assert result.skipped["no address"] == 1


def test_same_second_identical_rows_stay_distinct(tmp_path):
    """The 31-row bug: two carrier notices 292 ms apart collapsed into one.

    `_message_id` truncates to the second, so the ordinal must key on the second
    too. Keying it on the full microsecond timestamp gave both rows ordinal 0.
    """
    path = _xml(tmp_path, "\n".join([
        _sms("729725", 1676561996292, "Enter your code"),
        _sms("729725", 1676561996976, "Enter your code"),
    ]))
    result = sms.parse(path)
    assert len(result.messages) == 2, "identical rows in one second were merged"
    assert "duplicate within run" not in result.skipped
    assert result.messages[0].key != result.messages[1].key


def test_three_identical_rows_in_one_second(tmp_path):
    path = _xml(tmp_path, "\n".join(
        _sms("+15551234567", 1630048763654, "retry") for _ in range(3)))
    result = sms.parse(path)
    assert len(result.messages) == 3
    assert len({m.key for m in result.messages}) == 3


# --------------------------------------------------------------------------- addresses

def test_nanp_forms_are_one_person(tmp_path):
    """`+19174004025` and `9174004025` are the same phone.

    `norm_phone` alone leaves them as 11 and 10 digits, which split 76 people in
    the real file into two identities — including the owner.
    """
    path = _xml(tmp_path, "\n".join([
        _sms("+19174004025", 1630048763654),
        _sms("9174004025", 1630048764000),
    ]))
    result = sms.parse(path)
    assert len(result.chats) == 1
    assert len({m.chat_id for m in result.messages}) == 1


def test_non_nanp_country_code_is_kept(tmp_path):
    """`27840258710` is South Africa. Only a leading `1` on 11 digits is dropped."""
    assert sms._canon_digits("+27840258710") == "27840258710"
    assert sms._canon_digits("+19174004025") == "9174004025"
    assert sms._canon_digits("9174004025") == "9174004025"


def test_alphanumeric_sender_is_its_own_thread(tmp_path):
    path = _xml(tmp_path, _sms("CellCApp", 1630048763654, "balance"))
    result = sms.parse(path)
    assert result.chats[0].participant_names == ("CellCApp",)


# --------------------------------------------------------------------------- groups

def test_group_key_excludes_the_owner(tmp_path):
    """`<addrs>` lists the owner on both directions; the key must not.

    Keeping them gives the same group two thread ids depending on who sent.
    """
    group = [("+15550000001", "137"), ("+15550000002", "151"), (OWNER, "151")]
    sent_group = [("+15550000001", "151"), ("+15550000002", "151"), (OWNER, "137")]
    path = _xml(tmp_path, "\n".join([
        _mms(1630048763654, group, msg_box="1", text="received"),
        _mms(1630048764000, sent_group, msg_box="2", text="sent"),
    ]))
    result = sms.parse(path)
    assert len({m.chat_id for m in result.messages}) == 1, "group split by direction"
    assert len(result.chats) == 1
    assert result.chats[0].is_group
    assert OWNER not in result.chats[0].participant_names


def test_two_person_mms_is_a_one_to_one_not_a_group(tmp_path):
    """110 of 123 two-person MMS in the real file are ordinary 1:1 conversations.

    Keying them as groups splits one conversation in two: its SMS rows under
    `sms_…` and its MMS rows under `sms_g_…`.
    """
    path = _xml(tmp_path, "\n".join([
        _sms("+15550000001", 1630048763654, "text message"),
        _mms(1630048764000, [("+15550000001", "137"), (OWNER, "151")], text="mms"),
    ]))
    result = sms.parse(path)
    assert len(result.chats) == 1, "1:1 MMS did not merge with its SMS thread"
    assert not result.chats[0].is_group
    assert len({m.chat_id for m in result.messages}) == 1


def test_group_address_forms_do_not_split_the_thread(tmp_path):
    """The same group writes `+14147950006` on one row and `4147950006` on the next."""
    a = [("+14147950006", "137"), ("+15550000002", "151"), (OWNER, "151")]
    b = [("4147950006", "137"), ("+15550000002", "151"), (OWNER, "151")]
    path = _xml(tmp_path, "\n".join([
        _mms(1630048763654, a, text="one"),
        _mms(1630048764000, b, text="two"),
    ]))
    result = sms.parse(path)
    assert len({m.chat_id for m in result.messages}) == 1


def test_contact_name_is_not_applied_to_every_group_member(tmp_path):
    """`contact_name` on a group is a label, not a per-participant name.

    Applying it to everyone produced 15 threads whose members were all called the
    same thing (`Sec AO Base, Sec AO Base`).
    """
    group = [("+15550000001", "137"), ("+15550000002", "151"), (OWNER, "151")]
    path = _xml(tmp_path, _mms(1630048763654, group, contact="Sec AO Base"))
    result = sms.parse(path)
    names = result.chats[0].participant_names
    assert len(set(names)) == len(names), f"duplicated participant names: {names}"


def test_contact_name_names_the_other_party_on_a_one_to_one(tmp_path):
    path = _xml(tmp_path, _mms(
        1630048763654, [("+15550000001", "137"), (OWNER, "151")], contact="Bill Cell"))
    result = sms.parse(path)
    assert result.chats[0].participant_names == ("Bill Cell",)


def test_sender_comes_from_the_from_addr_not_alphabetical_order(tmp_path):
    """`<addr type="137">` is the `From`. `sorted(everyone)[0]` is not."""
    group = [("+15559999999", "151"), ("+15550000001", "137"), (OWNER, "151")]
    path = _xml(tmp_path, _mms(1630048763654, group, contact="Alice"))
    result = sms.parse(path)
    assert result.messages[0].sender_id == "+15550000001"
    assert result.messages[0].sender_name == "Alice"


def test_note_to_self_keeps_its_rows(tmp_path):
    """A message with only the owner in `<addrs>` is real; it just has no one to name."""
    path = _xml(tmp_path, _mms(1630048763654, [(OWNER, "151")], text="note to self"))
    result = sms.parse(path)
    assert len(result.messages) == 1
    assert result.chats[0].participant_names == ()


# --------------------------------------------------------------------------- mms parts

def test_text_plain_is_the_body_and_smil_is_not(tmp_path):
    parts = ('<part seq="1" ct="application/smil" text="&lt;smil/&gt;" />'
             '<part seq="2" ct="image/jpeg" cl="photo.jpg" data="AAAA" />')
    path = _xml(tmp_path, _mms(1630048763654, [("+15550000001", "137")],
                               text="caption", extra_parts=parts))
    result = sms.parse(path)
    assert result.messages[0].body == "caption"
    assert result.messages[0].has_attachments
    assert [a.path for a in result.attachments] == ["photo.jpg"]
    assert result.attachments[0].mime == "image/jpeg"


def test_attachment_only_mms_is_its_own_kind(tmp_path):
    parts = '<part seq="0" ct="image/jpeg" cl="photo.jpg" data="AAAA" />'
    path = _xml(tmp_path, _mms(1630048763654, [("+15550000001", "137")],
                               text="", extra_parts=parts))
    result = sms.parse(path)
    assert result.messages[0].raw_kind == "mms_attachment"
    assert result.messages[0].body == ""


def test_delivery_receipt_is_counted_not_stored(tmp_path):
    """`m_type=134` is a receipt, not a message. 87 in the real file."""
    path = _xml(tmp_path, _mms(1630048763654, [("+15550000001", "137")],
                               m_type="134"))
    result = sms.parse(path)
    assert result.messages == []
    assert result.skipped["delivery receipt, not a message"] == 1


def test_insert_address_token_is_the_owner_placeholder(tmp_path):
    group = [("+15550000001", "137"), ("insert-address-token", "151")]
    path = _xml(tmp_path, _mms(1630048763654, group))
    result = sms.parse(path)
    assert "insert-address-token" not in result.chats[0].participant_names
    assert any("insert-address-token" in w for w in result.warnings)


# --------------------------------------------------------------------------- owner

def test_owner_is_derived_from_mms_direction(tmp_path):
    """Sent MMS name the owner as `From`; received ones as `To`."""
    path = _xml(tmp_path, "\n".join([
        _mms(1630048763654, [("+15550000001", "137"), (OWNER, "151")], msg_box="1"),
        _mms(1630048764000, [("+15550000001", "137"), (OWNER, "151")], msg_box="1"),
        _mms(1630048765000, [(OWNER, "137"), ("+15550000001", "151")], msg_box="2"),
    ]))
    result = sms.parse(path)
    assert any(f"owner: {OWNER}" in w for w in result.warnings)


def test_explicit_self_id_wins_and_is_persisted(tmp_path):
    path = _xml(tmp_path, _mms(
        1630048763654, [("+15550000001", "137"), ("+15559999999", "151")]))
    profile = tmp_path / "profile"
    result = sms.parse(path, self_id="+15559999999", profile_dir=profile)
    assert "+15559999999" not in result.chats[0].participant_names
    assert any("owner: +15559999999" in w for w in result.warnings)


# --------------------------------------------------------------------------- container

def test_compressed_backup_is_unwrapped(tmp_path):
    """SyncTech's "compress backup" writes the XML as the first zip entry."""
    inner = _xml(tmp_path, _sms("+15551234567", 1630048763654))
    target = tmp_path / "backup.xml.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.write(inner, "backup.xml")
    result = sms.parse(target)
    assert len(result.messages) == 1


def test_zip_without_xml_is_refused(tmp_path):
    target = tmp_path / "empty.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("readme.txt", "nothing here")
    with pytest.raises(ValueError, match="no .xml"):
        sms.parse(target)


def test_naive_window_is_refused(tmp_path):
    path = _xml(tmp_path, _sms("+15551234567", 1630048763654))
    with pytest.raises(ValueError, match="timezone-aware"):
        sms.parse(path, since=datetime(2021, 1, 1))


def test_window_bounds_are_applied(tmp_path):
    path = _xml(tmp_path, "\n".join([
        _sms("+15551234567", 1630048763),
        _sms("+15551234567", 1730048763),
    ]))
    result = sms.parse(path, since=datetime(2022, 1, 1, tzinfo=timezone.utc))
    assert len(result.messages) == 1
    assert result.skipped["before window"] == 1


# --------------------------------------------------------------------------- real file

@pytest.mark.skipif(_REAL is None, reason="sample SMS export not present")
def test_real_export_reconciles_exactly():
    """Every row is either stored or counted. Nothing vanishes silently."""
    result = sms.parse(_REAL)
    stored = len(result.messages)
    skipped = sum(result.skipped.values())
    # The count comes from the file's own header, so regenerating the world cannot make
    # this assertion lie — it stays a reconciliation, not a magic number.
    declared = int(re.search(r'<smses count="(\d+)"', _REAL.read_text(encoding="utf-8")).group(1))
    assert stored + skipped == declared, f"{stored} + {skipped} != {declared}"
    assert "duplicate within run" not in result.skipped
    assert result.skipped == {}


@pytest.mark.skipif(_REAL is None, reason="sample SMS export not present")
def test_real_export_has_no_owner_leakage():
    """`Me` is the export's own marker for the owner and must never become a participant.

    The sample world names the owner `Me` on every sent row (`contact_name="Me"`), which
    is exactly the shape a real Android backup produces.
    """
    result = sms.parse(_REAL)
    for chat in result.chats:
        assert "me" not in {n.strip().lower() for n in chat.participant_names}, chat.title


@pytest.mark.skipif(_REAL is None, reason="sample SMS export not present")
def test_real_export_participant_names_are_unique():
    result = sms.parse(_REAL)
    for chat in result.chats:
        assert len(set(chat.participant_names)) == len(chat.participant_names), chat.title


@pytest.mark.skipif(_REAL is None, reason="sample SMS export not present")
def test_real_export_direction_is_stated_per_row():
    """`is_self` comes from the row's `type`, not from an owner guess.

    The sample world carries no MMS, so the owner's number cannot be derived — the
    adapter says so in `warnings` and still gets every direction right. That is the
    property worth pinning: a missing owner must not corrupt `is_self`.
    """
    result = sms.parse(_REAL)
    assert any("owner's number is unknown" in w for w in result.warnings)
    # Both directions must be present, and a sent row never carries a sender name —
    # that is what `is_self` means here. Counts move when the world is regenerated, so
    # the assertion is on the property, not the number.
    self_rows = [m for m in result.messages if m.is_self]
    assert 0 < len(self_rows) < len(result.messages)
    assert all(m.sender_name == "" for m in self_rows)
