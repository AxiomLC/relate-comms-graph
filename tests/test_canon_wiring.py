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
    assert rows[0]["k"] == "person:david sartori"
    assert rows[0]["n"] == 2


def test_a_phone_number_correspondent_keeps_its_display_form(store):
    # WhatsApp states only a number. The key is digits; the display is what was written.
    chat = _chat("whatsapp", "c1", "", ("+27 84 518 9029", "You"))
    messages = [_message(chat, 0, "+27 84 518 9029", is_self=False)]
    _write(store, _result([chat], messages))

    rows = tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k, c.display_name AS n")["rows"]
    assert rows[0]["k"] == "person:27845189029"
    assert rows[0]["n"] == "+27 84 518 9029"


# ------------------------------------------------------- the merged node shape

def _node(store, key):
    rows = tools.run_cypher(
        "MATCH (c:Correspondent {key: $k}) RETURN properties(c) AS p", {"k": key},
    )["rows"]
    assert rows, f"no correspondent {key!r}"
    return rows[0]["p"]


def test_one_name_on_two_platforms_is_one_node_with_both_platforms(store):
    # The whole point of dropping the platform prefix from the key.
    telegram = _chat("telegram", "t1", "", ("Mary Olver", "Mark Jones"))
    whatsapp = _chat("whatsapp", "w1", "", ("Mary Olver", "Mark Jones"))
    messages = [
        _message(telegram, 0, "Mary Olver", is_self=False, day=0),
        _message(whatsapp, 0, "Mary Olver", is_self=False, day=5),
    ]
    _write(store, _result([telegram, whatsapp], messages), owner="Mark Jones")

    rows = tools.run_cypher(
        "MATCH (t:Thread)-[:WITH]->(c:Correspondent) "
        "RETURN c.key AS k, count(t) AS n")["rows"]
    assert len(rows) == 1
    assert rows[0]["k"] == "person:mary olver"
    assert rows[0]["n"] == 2

    node = _node(store, "person:mary olver")
    assert sorted(node["platforms"]) == ["telegram", "whatsapp"]
    # `platform` is the first by date, so the platform filter keeps working.
    assert node["platform"] == "telegram"
    assert node["platform_label"] == "Telegram-WhatsApp"
    assert node["merged_by"] == "exact_name"


def test_a_merged_node_carries_the_merged_label(store):
    telegram = _chat("telegram", "t1", "", ("Mary Olver",))
    sms = _chat("sms", "s1", "", ("Mary Olver",))
    messages = [
        _message(telegram, 0, "Mary Olver", is_self=False, day=0),
        _message(sms, 0, "Mary Olver", is_self=False, day=1),
    ]
    _write(store, _result([telegram, sms], messages))

    labels = tools.run_cypher(
        "MATCH (c:Correspondent {key: 'person:mary olver'}) "
        "RETURN labels(c) AS lb")["rows"][0]["lb"]
    assert "Correspondent" in labels and "Merged" in labels


def test_a_single_platform_node_is_not_merged(store):
    chat = _chat("telegram", "t1", "", ("Mary Olver",))
    _write(store, _result([chat], [_message(chat, 0, "Mary Olver", is_self=False)]))

    labels = tools.run_cypher(
        "MATCH (c:Correspondent {key: 'person:mary olver'}) "
        "RETURN labels(c) AS lb")["rows"][0]["lb"]
    assert "Merged" not in labels


def test_placeholders_stay_platform_scoped(store):
    # `Facebook user` and `LinkedIn Member` are two different placeholder accounts.
    # Under a bare `person:` key they would fold into one node claiming both.
    messenger = _chat("messenger", "m1", "", ("Facebook user",))
    linkedin = _chat("linkedin", "l1", "", ("LinkedIn Member",))
    messages = [
        _message(messenger, 0, "Facebook user", is_self=False),
        _message(linkedin, 0, "LinkedIn Member", is_self=False),
    ]
    _write(store, _result([messenger, linkedin], messages))

    keys = {row["k"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k")["rows"]}
    assert keys == {"messenger:placeholder:facebook user",
                   "linkedin:placeholder:linkedin member"}


def test_first_seen_is_the_earliest_message_not_the_first_ingest(store):
    # The participant list carries no timestamp, so this is built from the messages.
    chat = _chat("telegram", "t1", "", ("Mary Olver",))
    messages = [
        _message(chat, 0, "Mary Olver", is_self=False, day=10),
        _message(chat, 1, "Mary Olver", is_self=False, day=2),
    ]
    _write(store, _result([chat], messages))

    node = _node(store, "person:mary olver")
    # `_message` offsets by its index in minutes, so the day-2 row is 12:01.
    assert node["first_seen_utc"] == "2026-01-03T12:01:00Z"


def test_each_platform_keeps_its_own_spelling(store):
    # `handles` is flat in the store (`handle_<platform>`), assembled at the API edge.
    telegram = _chat("telegram", "t1", "", ("Axiom LoftCoin",))
    messenger = _chat("messenger", "m1", "", ("Axiom LoftCoin",))
    messages = [
        _message(telegram, 0, "Axiom LoftCoin", is_self=False, day=0),
        _message(messenger, 0, "Axiom LoftCoin", is_self=False, day=1),
    ]
    _write(store, _result([telegram, messenger], messages))

    # `canon` splits the camelCase, so the key is `axiom loft coin`; the handle keeps
    # the spelling the export used.
    node = _node(store, "person:axiom loft coin")
    assert writer.handles_from(node) == {
        "telegram": "Axiom LoftCoin", "messenger": "Axiom LoftCoin",
    }


def test_dominance_is_the_largest_platforms_share_of_messages(store):
    # Telegram gets 3 messages, WhatsApp 1: dominance 0.75, primary telegram.
    telegram = _chat("telegram", "t1", "", ("Mary Olver",))
    whatsapp = _chat("whatsapp", "w1", "", ("Mary Olver",))
    messages = [
        _message(telegram, i, "Mary Olver", is_self=False, day=0) for i in range(3)
    ] + [_message(whatsapp, 0, "Mary Olver", is_self=False, day=5)]
    _write(store, _result([telegram, whatsapp], messages))

    node = next(n for n in tools.graph_slice()["nodes"]
                if n["id"] == "person:mary olver")
    assert node["primaryPlatform"] == "telegram"
    assert node["dominance"] == 0.75
    # `platform` is still the first by DATE, which is a different question.
    assert node["platform"] == "telegram"
    assert node["platforms"] == ["telegram", "whatsapp"]


def test_primary_platform_can_disagree_with_platform(store):
    # WhatsApp is seen first (date) but Telegram carries more messages.
    telegram = _chat("telegram", "t1", "", ("Mary Olver",))
    whatsapp = _chat("whatsapp", "w1", "", ("Mary Olver",))
    messages = [
        _message(whatsapp, 0, "Mary Olver", is_self=False, day=0),
    ] + [
        _message(telegram, i, "Mary Olver", is_self=False, day=10) for i in range(4)
    ]
    _write(store, _result([telegram, whatsapp], messages))

    node = next(n for n in tools.graph_slice()["nodes"]
                if n["id"] == "person:mary olver")
    assert node["platform"] == "whatsapp"       # first by date
    assert node["primaryPlatform"] == "telegram"  # most messages
    assert node["dominance"] == 0.8


def test_a_single_platform_node_has_full_dominance(store):
    chat = _chat("telegram", "t1", "", ("Mary Olver",))
    _write(store, _result([chat], [_message(chat, 0, "Mary Olver", is_self=False)]))

    node = next(n for n in tools.graph_slice()["nodes"]
                if n["id"] == "person:mary olver")
    assert node["primaryPlatform"] == "telegram"
    assert node["dominance"] == 1.0


def test_a_correspondent_with_no_messages_still_gets_a_primary_platform(store):
    # A thread with no messages: `write()` mints no Thread row, so the `WITH` MATCH
    # finds nothing and the node lands with no edge. The node itself still exists,
    # and it must still answer `primaryPlatform` — the canvas would otherwise get a
    # null leash target.
    chat = _chat("telegram", "t1", "", ("Mary Olver",))
    _write(store, _result([chat], []))

    node = next(n for n in tools.graph_slice()["nodes"]
                if n["id"] == "person:mary olver")
    assert node["primaryPlatform"] == "telegram"
    assert node["dominance"] == 1.0
    assert node["thread_count"] == 0


def test_the_platform_filter_finds_a_merged_node_by_either_platform(store):
    # `platform` is one string (the first by date); the filter must read `platforms`,
    # or a merged node disappears when the user filters by anything but the first.
    telegram = _chat("telegram", "t1", "", ("Mary Olver",))
    whatsapp = _chat("whatsapp", "w1", "", ("Mary Olver",))
    messages = [
        _message(telegram, 0, "Mary Olver", is_self=False, day=0),
        _message(whatsapp, 0, "Mary Olver", is_self=False, day=5),
    ]
    _write(store, _result([telegram, whatsapp], messages))

    try:
        tools.configure_platforms(["whatsapp"])
        ids = {node["id"] for node in tools.graph_slice()["nodes"]}
        assert "person:mary olver" in ids
    finally:
        tools.configure_platforms(None)


def test_re_ingest_does_not_duplicate_a_platform_in_the_list(store):
    telegram = _chat("telegram", "t1", "", ("Mary Olver",))
    result = _result([telegram], [_message(telegram, 0, "Mary Olver", is_self=False)])
    _write(store, result)
    _write(store, result)

    node = _node(store, "person:mary olver")
    assert node["platforms"] == ["telegram"]


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
