"""The WhatsApp HTML dialect.

Two promises:

1. **It reads the same conversation as `chat.txt`.** Verified against real exports of
   the same two chats in both formats: 46 of 47 message keys are identical.
2. **A chat downloaded both ways lands in one thread, not two.** `_chat_id()` hashes the
   chat *title*, and `message_key()` truncates to the minute, so `MERGE` collapses them.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone

import pytest

from relate_comms import ingest as ingest_module
from relate_comms.adapters import whatsapp, whatsapp_html

# A minimal page in the exporter's shape: header, day separator, rows.
PAGE = """<!DOCTYPE html><html><body><div class="wrap">
<div class="hd">{title}<small>{meta}</small></div><div class="msgs">
{body}
</div><div class="ftr">Exported with WASendly</div></div></body></html>"""


def _page(title: str, meta: str, body: str) -> str:
    return PAGE.format(title=title, meta=meta, body=body)


def _row(direction: str, text: str, clock: str, sender: str | None = None) -> str:
    who = f'<div class="sender">{sender}</div>' if sender else ""
    return (f'<div class="row {direction}"><div class="bubble">'
            f'<div class="txt">{who}{text}</div>'
            f'<div class="time">{clock}</div></div></div>')


def _zip(tmp_path, name: str, pages: dict[str, str]):
    target = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for member, document in pages.items():
            archive.writestr(member, document)
        if "index.html" not in pages:
            archive.writestr("index.html", "<html><body>contents</body></html>")
    return target


ONE_TO_ONE = _page(
    "Thad Zurawski Chicago", "Chat · 3 messages · exported 17 Nov 2026",
    '<div class="daysep"><span>16 Nov 2026</span></div>'
    + _row("out", "Hey man", "15:01")
    + _row("in", "Hey Dave", "23:09")
    + _row("out", "Yea sure", "23:19"),
)

GROUP = _page(
    "Neighbourhood Watch", "Group · 3 messages · exported 17 Nov 2026",
    '<div class="daysep"><span>16 Nov 2026</span></div>'
    + _row("in", "anyone seen the van?", "10:00", sender="Alice")
    + _row("in", "yes, white transit", "10:01", sender="Bob")
    + _row("in", "thanks", "10:02", sender="Carol"),
)


# --------------------------------------------------------------------------- detect

def test_detects_a_zip_of_chat_pages(tmp_path):
    path = _zip(tmp_path, "bulk", {"chats/One.html": ONE_TO_ONE})
    assert whatsapp_html.detect(path)
    assert ingest_module.detect_platform(path) == "whatsapp"


def test_detects_a_loose_html_page(tmp_path):
    path = tmp_path / "chat.html"
    path.write_text(ONE_TO_ONE, encoding="utf-8")
    assert whatsapp_html.detect(path)


def test_refuses_a_zip_of_unrelated_html(tmp_path):
    path = tmp_path / "site.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("index.html", "<html><body>hello</body></html>")
        archive.writestr("about.html", "<html><body>about</body></html>")
    assert not whatsapp_html.detect(path)


def test_refuses_a_native_chat_txt_zip(tmp_path):
    """The two dialects must not claim each other's files."""
    path = tmp_path / "native.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("chat.txt", "[5/22/26, 8:45:50 AM] You: hi\n")
    assert not whatsapp_html.detect(path)


# ---------------------------------------------------------------------------- parse

def test_reads_a_one_to_one(tmp_path):
    path = _zip(tmp_path, "one", {"chats/One.html": ONE_TO_ONE})
    result = whatsapp_html.parse(path)

    assert len(result.chats) == 1
    chat = result.chats[0]
    assert chat.title == "Thad Zurawski Chicago"
    assert chat.is_group is False
    assert len(result.messages) == 3
    assert [m.is_self for m in result.messages] == [True, False, True]


def test_owner_rows_are_named_you_and_correspondents_by_the_title(tmp_path):
    """A 1:1 has no sender div on either side, so the row class decides.

    Using `SELF_NAME` as a blanket fallback named every correspondent "You", which then
    matched the Owner's own key and would have merged two people's messages.
    """
    path = _zip(tmp_path, "one", {"chats/One.html": ONE_TO_ONE})
    result = whatsapp_html.parse(path)
    senders = [m.sender_name for m in result.messages]
    assert senders == ["You", "Thad Zurawski Chicago", "You"]


def test_group_ness_is_stated_in_the_header(tmp_path):
    """`chat.txt` has to infer this; the HTML says it outright."""
    path = _zip(tmp_path, "group", {"groups/G.html": GROUP})
    result = whatsapp_html.parse(path)
    assert result.chats[0].is_group is True
    assert result.chats[0].kind == "group_chat"


def test_group_senders_come_from_the_sender_div(tmp_path):
    path = _zip(tmp_path, "group", {"groups/G.html": GROUP})
    result = whatsapp_html.parse(path)
    assert [m.sender_name for m in result.messages] == ["Alice", "Bob", "Carol"]
    assert set(result.chats[0].participant_names) == {"Alice", "Bob", "Carol"}


def test_the_day_separator_supplies_the_date(tmp_path):
    """A row carries only `HH:MM`; the date is the most recent separator before it."""
    body = ('<div class="daysep"><span>16 Nov 2026</span></div>'
            + _row("in", "first", "23:59")
            + '<div class="daysep"><span>17 Nov 2026</span></div>'
            + _row("in", "second", "00:01"))
    path = _zip(tmp_path, "days", {"chats/D.html": _page("D", "Chat · 2", body)})
    result = whatsapp_html.parse(path)
    stamps = [m.ts_utc for m in result.messages]
    assert stamps == [
        datetime(2026, 11, 16, 23, 59, tzinfo=timezone.utc),
        datetime(2026, 11, 17, 0, 1, tzinfo=timezone.utc),
    ]


def test_placeholders_are_normalised_to_the_chat_txt_wording(tmp_path):
    """The two dialects write the same event differently; the body must agree.

    Without this the same media row stores twice when a chat is downloaded both ways.
    """
    body = ('<div class="daysep"><span>16 Nov 2026</span></div>'
            '<div class="row out"><div class="bubble"><div class="txt">'
            '<div class="ph">🎤 Voice / Audio message</div></div>'
            '<div class="time">10:00</div></div></div>')
    path = _zip(tmp_path, "ph", {"chats/P.html": _page("P", "Chat · 1", body)})
    result = whatsapp_html.parse(path)
    message = result.messages[0]
    assert message.raw_kind == "voice_message"
    assert message.body == "<voice message omitted>"


def test_a_media_caption_is_the_body_not_a_separate_message(tmp_path):
    body = ('<div class="daysep"><span>16 Nov 2026</span></div>'
            '<div class="row in"><div class="bubble"><div class="txt">'
            '<a class="medialink" href="data:image/jpeg;base64,AAAA">'
            '<img class="media" src="data:image/jpeg;base64,AAAA"></a>'
            '<div class="cap">look at this</div></div>'
            '<div class="time">10:00</div></div></div>')
    path = _zip(tmp_path, "cap", {"chats/C.html": _page("C", "Chat · 1", body)})
    result = whatsapp_html.parse(path)
    assert len(result.messages) == 1
    assert result.messages[0].body == "look at this"
    assert result.messages[0].has_attachments is True


def test_base64_is_never_decoded(tmp_path):
    """The 307-row real group is 336 KB of mostly base64. It must not be stored."""
    blob = "A" * 5000
    body = ('<div class="daysep"><span>16 Nov 2026</span></div>'
            f'<div class="row in"><div class="bubble"><div class="txt">'
            f'<img class="media" src="data:image/jpeg;base64,{blob}"></div>'
            '<div class="time">10:00</div></div></div>')
    path = _zip(tmp_path, "b64", {"chats/B.html": _page("B", "Chat · 1", body)})
    result = whatsapp_html.parse(path)
    assert all(blob not in m.body for m in result.messages)


def test_index_html_is_not_a_chat(tmp_path):
    path = _zip(tmp_path, "bulk", {
        "chats/One.html": ONE_TO_ONE,
        "index.html": "<html><body>table of contents</body></html>",
    })
    result = whatsapp_html.parse(path)
    assert len(result.chats) == 1


def test_silent_group_gate_uses_the_stated_group_ness(tmp_path):
    path = _zip(tmp_path, "group", {"groups/G.html": GROUP})
    kept = whatsapp_html.parse(path)
    assert len(kept.chats) == 1

    trimmed = whatsapp_html.parse(path, exclude_silent_groups=True)
    assert trimmed.chats == []
    assert trimmed.messages == []
    assert trimmed.skipped.get("group thread the owner never spoke in") == 1


def test_window_filter_counts_skips(tmp_path):
    path = _zip(tmp_path, "one", {"chats/One.html": ONE_TO_ONE})
    since = datetime(2026, 11, 16, 23, 10, tzinfo=timezone.utc)
    result = whatsapp_html.parse(path, since=since)
    # 15:01 and 23:09 are before the bound; only 23:19 survives.
    assert result.skipped.get("before window") == 2
    assert len(result.messages) == 1
    assert all(m.ts_utc >= since for m in result.messages)


# ------------------------------------------------------- cross-dialect agreement

def test_both_dialects_produce_the_same_chat_id(tmp_path):
    """`_chat_id()` hashes the title, so the same chat is one Thread either way."""
    html_path = _zip(tmp_path, "one", {"chats/One.html": ONE_TO_ONE})
    html_result = whatsapp_html.parse(html_path)

    # The native route takes the chat title from the FILE NAME, so the zip must be
    # named after the chat — that is how a real export arrives.
    native = tmp_path / "Thad Zurawski Chicago.zip"
    with zipfile.ZipFile(native, "w") as archive:
        archive.writestr("chat.txt", (
            "[11/16/26, 3:01:48 PM] You: Hey man\n"
            "[11/16/26, 11:09:15 PM] Thad Zurawski Chicago: Hey Dave\n"
            "[11/16/26, 11:19:20 PM] You: Yea sure\n"
        ))
    native_result = whatsapp.parse(native)

    assert html_result.chats[0].chat_id == native_result.chats[0].chat_id


def test_both_dialects_produce_the_same_message_keys(tmp_path):
    """The whole point: a chat downloaded both ways must not store every row twice.

    `message_key()` truncates to the minute and collapses whitespace, so the HTML's
    `23:09` and the native `23:09:15` agree.
    """
    html_path = _zip(tmp_path, "one", {"chats/One.html": ONE_TO_ONE})
    html_keys = {m.key for m in whatsapp_html.parse(html_path).messages}

    native = tmp_path / "Thad Zurawski Chicago.zip"
    with zipfile.ZipFile(native, "w") as archive:
        archive.writestr("chat.txt", (
            "[11/16/26, 3:01:48 PM] You: Hey man\n"
            "[11/16/26, 11:09:15 PM] Thad Zurawski Chicago: Hey Dave\n"
            "[11/16/26, 11:19:20 PM] You: Yea sure\n"
        ))
    native_keys = {m.key for m in whatsapp.parse(native).messages}

    assert html_keys == native_keys


def test_ingesting_both_dialects_does_not_duplicate(tmp_path):
    """End to end through the pipeline: one thread, no doubled rows."""
    from relate_comms import writer

    spool = tmp_path / "spool"
    spool.mkdir()
    _zip(spool, "bulk", {"chats/One.html": ONE_TO_ONE})

    native = spool / "Thad Zurawski Chicago.zip"
    with zipfile.ZipFile(native, "w") as archive:
        archive.writestr("chat.txt", (
            "[11/16/26, 3:01:48 PM] You: Hey man\n"
            "[11/16/26, 11:09:15 PM] Thad Zurawski Chicago: Hey Dave\n"
            "[11/16/26, 11:19:20 PM] You: Yea sure\n"
        ))

    store = tmp_path / "g.rl"
    ingest_module.ingest(root=spool, store=store, workers=1)
    conn = writer.connect(store)
    keys = writer.stored_keys(conn, "whatsapp")
    conn.close()

    assert len(keys) == 3, f"expected 3 rows, got {len(keys)}"
