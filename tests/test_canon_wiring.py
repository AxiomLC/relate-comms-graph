"""The canon pipe, wired into the writer.

`tests/test_canon.py` tests the pipe in isolation. This file tests the two things the
pipe exists to guarantee once it is wired:

1. **The Owner is never a Correspondent** — on any platform, under any spelling.
2. **Threads fan in** — one person, many threads, one node with many `WITH` edges.

Both were broken in the live store: the Owner appeared as a Correspondent in 236
threads, and a person's threads were separate nodes whenever the export spelled the
name differently.

Run: python -m pytest tests/test_canon_wiring.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _chat(platform: str, chat_id: str, title: str, people: tuple[str, ...],
          *, is_group: bool = False) -> Chat:
    return Chat(platform=platform, chat_id=chat_id, title=title,
                kind="group_chat" if is_group else "personal_chat",
                is_group=is_group, participant_names=people)


def _message(chat: Chat, index: int, sender: str, *, is_self: bool,
             day: int = 0) -> Message:
    message_id = f"m{index:03d}"
    return Message(
        key=make_key(chat.platform, chat.chat_id, message_id),
        platform=chat.platform, chat_id=chat.chat_id, message_id=message_id,
        ts_utc=_BASE + timedelta(days=day, minutes=index),
        sender_name=sender, sender_id=None, body=f"body {index}",
        reply_to=None, has_attachments=False, is_self=is_self, raw_kind="text",
    )


def _result(chats: list[Chat], messages: list[Message]) -> IngestResult:
    return IngestResult(platform=chats[0].platform, export_path="fixture",
                        chats=chats, messages=messages)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "graph.rl"
    conn = writer.connect(path)
    conn.close()
    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


def _write(path, result, *, owner=None, owner_forms=None):
    conn = writer.connect(path)
    try:
        writer.write(conn, result, owner=owner)
        writer.write_correspondents(conn, result, owner=owner,
                                    owner_forms=owner_forms)
    finally:
        conn.close()


# ------------------------------------------------------------------- owner guard

def test_the_owner_is_never_a_correspondent(store):
    chat = _chat("messenger", "c1", "Mary Olver", ("Mark Jones", "Mary Olver"))
    messages = [
        _message(chat, 0, "Mark Jones", is_self=True),
        _message(chat, 1, "Mary Olver", is_self=False),
    ]
    _write(store, _result([chat], messages), owner="Mark Jones")

    names = [row["n"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.display_name AS n")["rows"]]
    assert names == ["Mary Olver"]


def test_the_owner_guard_survives_a_nickname_spelling(store):
    # The profile says `David Sartori`; the export says `Dave Sartori`.
    chat = _chat("messenger", "c1", "", ("Dave Sartori", "Mary Olver"))
    messages = [_message(chat, 0, "Mary Olver", is_self=False)]
    _write(store, _result([chat], messages), owner_forms=["David Sartori"])

    names = [row["n"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.display_name AS n")["rows"]]
    assert names == ["Mary Olver"]


def test_the_owner_guard_works_when_the_platform_names_them_differently(store):
    # Telegram names the owner `user1426445212`; the participant list says
    # `Axiom LoftCoin`. One form must not be compared against the other — both are
    # supplied, so the display name is caught.
    chat = _chat("telegram", "c1", "", ("Axiom LoftCoin", "Mary Olver"))
    messages = [_message(chat, 0, "Mary Olver", is_self=False)]
    _write(store, _result([chat], messages),
           owner="user1426445212",
           owner_forms=["user1426445212", "Axiom LoftCoin"])

    names = [row["n"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.display_name AS n")["rows"]]
    assert names == ["Mary Olver"]


def test_a_placeholder_becomes_a_pseudo_node_not_a_person(store):
    chat = _chat("messenger", "c1", "", ("Facebook user", "Mary Olver"))
    messages = [_message(chat, 0, "Mary Olver", is_self=False)]
    _write(store, _result([chat], messages))

    keys = [row["k"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k")["rows"]]
    assert any("placeholder" in key for key in keys)
    assert any("mary olver" in key for key in keys)


# ------------------------------------------------------------------------ fan-in

def test_one_person_many_threads_is_one_node(store):
    # The whole point of canonicalising the key: fifteen threads, one node.
    chats = [
        _chat("telegram", f"c{i}", "", ("Mary Olver", "Mark Jones"))
        for i in range(3)
    ]
    messages = [_message(chat, 0, "Mary Olver", is_self=False) for chat in chats]
    _write(store, _result(chats, messages), owner="Mark Jones")

    rows = tools.run_cypher(
        "MATCH (t:Thread)-[:WITH]->(c:Correspondent) "
        "RETURN c.key AS k, count(t) AS n")["rows"]
    assert len(rows) == 1
    assert rows[0]["n"] == 3


def test_differently_spelled_threads_still_fan_in(store):
    # `Dave Sartori` in one thread, `david sartori` in another: one node, two edges.
    chats = [
        _chat("messenger", "c1", "", ("Dave Sartori", "Mark Jones")),
        _chat("messenger", "c2", "", ("david sartori", "Mark Jones")),
    ]
    messages = [_message(chat, 0, "Dave Sartori", is_self=False) for chat in chats]
    _write(store, _result(chats, messages), owner="Mark Jones")

    rows = tools.run_cypher(
        "MATCH (t:Thread)-[:WITH]->(c:Correspondent) "
        "RETURN c.key AS k, count(t) AS n")["rows"]
    assert len(rows) == 1
    assert rows[0]["k"] == "messenger:david sartori"
    assert rows[0]["n"] == 2


def test_a_phone_number_correspondent_keeps_its_display_form(store):
    # WhatsApp states only a number. The key is digits; the display is what was written.
    chat = _chat("whatsapp", "c1", "", ("+27 84 518 9029", "You"))
    messages = [_message(chat, 0, "+27 84 518 9029", is_self=False)]
    _write(store, _result([chat], messages))

    rows = tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k, c.display_name AS n")["rows"]
    assert rows[0]["k"] == "whatsapp:27845189029"
    assert rows[0]["n"] == "+27 84 518 9029"


# ------------------------------------------------------------------ thread titles

def test_a_single_day_thread_has_no_arrow():
    chat = _chat("sms", "c1", "", ("Bryan Rodgers", "Mark Jones"))
    title = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE + timedelta(hours=2))
    assert title == "SMS; Bryan Rodgers; 01-01-2026"


def test_a_thread_spanning_days_gets_an_arrow():
    chat = _chat("messenger", "c1", "", ("Ryan Phillip", "Mark Jones"))
    title = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE + timedelta(days=20))
    assert title == "Fcbk Mssgr; Ryan Phillip; 01-01-2026->"


def test_the_arrow_does_not_drift_with_a_later_end_date():
    # The reason `->` beats an end date: once true, always true.
    chat = _chat("messenger", "c1", "", ("Ryan Phillip", "Mark Jones"))
    early = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE + timedelta(days=2))
    late = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE + timedelta(days=300))
    assert early == late


def test_a_group_uses_its_own_name_not_a_participant():
    chat = _chat("whatsapp", "c1", "Come to Africa",
                 ("Mark Jones", "Mary Olver", "Owen Lonon"), is_group=True)
    title = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE)
    assert title == "WhatsApp; Come to Africa; 01-01-2026"


def test_a_subject_containing_a_date_is_not_ambiguous():
    # Two separators: the date block is delimited, so a name may contain a date.
    chat = _chat("linkedin", "c1", "Invoice due 08-16-2025", ("Mary Olver", "Mark Jones"))
    title = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE)
    assert title == "LinkedIn; Invoice due 08-16-2025; 01-01-2026"


def test_a_collision_gets_an_ordinal():
    chat = _chat("messenger", "c1", "", ("Ryan Phillip", "Mark Jones"))
    title = writer.thread_display_title(
        chat, "Mark Jones", first_ts=_BASE, last_ts=_BASE, ordinal=2)
    assert title.endswith("#2")


def test_no_date_means_no_second_separator():
    chat = _chat("telegram", "c1", "", ("Mary Olver", "Mark Jones"))
    title = writer.thread_display_title(chat, "Mark Jones")
    assert title == "Telegram; Mary Olver"


def test_the_platform_token_is_the_display_label():
    # Never the store key: the UI shows `Fcbk Mssgr`, not `messenger`.
    assert writer.platform_title_label("messenger") == "Fcbk Mssgr"
    assert writer.platform_title_label("whatsapp") == "WhatsApp"
    assert writer.platform_title_label("email") == "Email"
