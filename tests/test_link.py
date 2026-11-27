"""Cross-connect: folding nodes whose keys differ.

Edit 1 folds identical canonical names at write time, so the only thing left for
`link.py` is the case it exists for:

    person:+27845189029      a WhatsApp contact the export only knows by phone
    person:david sartori     the same human, named on Telegram

Those never share a key. These tests build that shape by hand, because the generated
samples do not contain it — `sample_writer` names every SMS contact, so no phone-only
node is ever produced.

Run: python -m pytest tests/test_link.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import canon, link, tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _chat(platform: str, chat_id: str, people: tuple[str, ...]) -> Chat:
    return Chat(platform=platform, chat_id=chat_id, title=people[0],
                kind="personal_chat", is_group=False, participant_names=people)


def _message(chat: Chat, index: int, sender: str, *, sender_id: str | None = None,
             day: int = 0) -> Message:
    message_id = f"m{index:03d}"
    return Message(
        key=make_key(chat.platform, chat.chat_id, message_id),
        platform=chat.platform, chat_id=chat.chat_id, message_id=message_id,
        ts_utc=_BASE + timedelta(days=day, minutes=index),
        sender_name=sender, sender_id=sender_id, body=f"body {index}",
        reply_to=None, has_attachments=False, is_self=False, raw_kind="text",
    )


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "graph.rl"
    writer.connect(path).close()
    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


def _write(path, chats, messages):
    result = IngestResult(platform=chats[0].platform, export_path="fixture",
                          chats=chats, messages=messages)
    conn = writer.connect(path)
    try:
        writer.write(conn, result)
        writer.write_correspondents(conn, result)
        return link.link(conn)
    finally:
        conn.close()


def _keys() -> set[str]:
    return {row["k"] for row in tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k")["rows"]}


def _with_edges() -> list[tuple[str, str]]:
    return [(row["t"], row["c"]) for row in tools.run_cypher(
        "MATCH (t:Thread)-[:WITH]->(c:Correspondent) "
        "RETURN t.key AS t, c.key AS c")["rows"]]


# ------------------------------------------------------------------- phone fold


def test_a_phone_only_contact_folds_onto_the_named_one(store):
    """The case the whole module exists for."""
    whatsapp = _chat("whatsapp", "w1", ("+27 84 518 9029",))
    telegram = _chat("telegram", "t1", ("David Sartori",))
    messages = [
        # WhatsApp knows the contact only by phone; the sender field is the number.
        _message(whatsapp, 0, "+27 84 518 9029", sender_id="+27845189029"),
        # Telegram names them, and the export's id carries the same phone.
        _message(telegram, 0, "David Sartori", sender_id="+27845189029"),
    ]

    report = _write(store, [whatsapp, telegram], messages)

    assert report["folded"] == 1
    assert report["merged_by"] == {"phone": 1}
    # The named key survives: it is the one a human reads.
    assert _keys() == {"person:david sartori"}


def test_the_fold_keeps_every_with_edge(store):
    """A fold is a re-point, not a delete. Losing `WITH` would orphan the threads."""
    whatsapp = _chat("whatsapp", "w1", ("+27 84 518 9029",))
    telegram = _chat("telegram", "t1", ("David Sartori",))
    messages = [
        _message(whatsapp, 0, "+27 84 518 9029", sender_id="+27845189029"),
        _message(telegram, 0, "David Sartori", sender_id="+27845189029"),
    ]
    _write(store, [whatsapp, telegram], messages)

    edges = _with_edges()
    assert len(edges) == 2
    assert {target for _thread, target in edges} == {"person:david sartori"}


def test_the_folded_node_reports_both_platforms(store):
    whatsapp = _chat("whatsapp", "w1", ("+27 84 518 9029",))
    telegram = _chat("telegram", "t1", ("David Sartori",))
    messages = [
        _message(whatsapp, 0, "+27 84 518 9029", sender_id="+27845189029"),
        _message(telegram, 0, "David Sartori", sender_id="+27845189029"),
    ]
    _write(store, [whatsapp, telegram], messages)

    node = tools.run_cypher(
        "MATCH (c:Correspondent {key: 'person:david sartori'}) "
        "RETURN c.platforms AS ps, c.platform_label AS label, labels(c) AS lb"
    )["rows"][0]
    assert sorted(node["ps"]) == ["telegram", "whatsapp"]
    assert "Merged" in node["lb"]


def test_the_fold_is_idempotent(store):
    whatsapp = _chat("whatsapp", "w1", ("+27 84 518 9029",))
    telegram = _chat("telegram", "t1", ("David Sartori",))
    messages = [
        _message(whatsapp, 0, "+27 84 518 9029", sender_id="+27845189029"),
        _message(telegram, 0, "David Sartori", sender_id="+27845189029"),
    ]
    _write(store, [whatsapp, telegram], messages)

    conn = writer.connect(store)
    try:
        second = link.link(conn)
    finally:
        conn.close()
    assert second["folded"] == 0
    assert _keys() == {"person:david sartori"}


# ------------------------------------------------------------------- email fold


def test_an_address_folds_two_spellings(store):
    """Email writes the address as the id; a name on another platform meets it there."""
    email = _chat("email", "e1", ("dave.sartori@example.com",))
    telegram = _chat("telegram", "t1", ("Dave Sartori",))
    messages = [
        _message(email, 0, "dave.sartori@example.com",
                 sender_id="dave.sartori@example.com"),
        _message(telegram, 0, "Dave Sartori", sender_id="dave.sartori@example.com"),
    ]

    report = _write(store, [email, telegram], messages)

    assert report["folded"] == 1
    assert report["merged_by"] == {"email": 1}
    # `canon` resolves the nickname, so the surviving key is the long form.
    assert _keys() == {"person:david sartori"}


# ---------------------------------------------------------------------- fuzzy


def test_a_mistyped_name_folds_into_one_node(store):
    """Two spellings of one person: a fold, not a drawn guess.

    The `POSSIBLY` edge was removed 2026-11-23. A typo'd surname has no second reading
    — it is the same human — and the edge was never acted on, so the person appeared
    twice in the graph with a line nobody clicked.
    """
    telegram = _chat("telegram", "t1", ("Chris Tanaka",))
    whatsapp = _chat("whatsapp", "w1", ("Chirs Tanaka",))
    messages = [
        _message(telegram, 0, "Chris Tanaka"),
        _message(whatsapp, 0, "Chirs Tanaka"),
    ]

    report = _write(store, [telegram, whatsapp], messages)

    assert report["folded"] == 1
    assert report["merged_by"] == {"fuzzy": 1}
    # One node, and the survivor carries both platforms.
    assert _keys() == {"person:chirs tanaka"}
    row = tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.platforms AS p, c.merged_by AS why"
    )["rows"][0]
    assert sorted(row["p"]) == ["telegram", "whatsapp"]
    # **Not `fuzzy`.** The stored `merged_by` is set by the *writer* from `canon`
    # evidence, and `link` can only fill it with `coalesce` — so a node that entered the
    # store as `exact_name` keeps that value even when a later fold was fuzzy. The
    # link-time reason is in `report["merged_by"]`, asserted above. Recording this
    # rather than quietly asserting `exact_name`: it is a real mismatch between the two
    # sources, and `HANDOVER.md` Open decisions notes it.


def test_a_different_surname_is_not_a_candidate(store):
    """`Will Sell` vs `Will Castellanos` shares a given name and nothing else."""
    telegram = _chat("telegram", "t1", ("Will Sell",))
    whatsapp = _chat("whatsapp", "w1", ("Will Castellanos",))
    messages = [
        _message(telegram, 0, "Will Sell"),
        _message(whatsapp, 0, "Will Castellanos"),
    ]

    report = _write(store, [telegram, whatsapp], messages)

    assert report["folded"] == 0
    assert len(_keys()) == 2


# ------------------------------------------------------------------ guard rails


def test_placeholders_are_never_folded(store):
    """Two anonymous accounts on two platforms are not one person."""
    messenger = _chat("messenger", "m1", ("Facebook user",))
    linkedin = _chat("linkedin", "l1", ("LinkedIn Member",))
    messages = [
        _message(messenger, 0, "Facebook user"),
        _message(linkedin, 0, "LinkedIn Member"),
    ]

    report = _write(store, [messenger, linkedin], messages)

    assert report["folded"] == 0
    assert _keys() == {"messenger:placeholder:facebook user",
                       "linkedin:placeholder:linkedin member"}


def test_fold_on_name_can_be_switched_off(store):
    """`FOLD_ON_NAME = False` leaves only the identifier folds."""
    whatsapp = _chat("whatsapp", "w1", ("+27 84 518 9029",))
    telegram = _chat("telegram", "t1", ("David Sartori",))
    messages = [
        _message(whatsapp, 0, "+27 84 518 9029", sender_id="+27845189029"),
        _message(telegram, 0, "David Sartori", sender_id="+27845189029"),
    ]
    result = IngestResult(platform="whatsapp", export_path="fixture",
                          chats=[whatsapp, telegram], messages=messages)
    conn = writer.connect(store)
    try:
        writer.write(conn, result)
        writer.write_correspondents(conn, result)
        # Phone evidence still folds; the knob only removes the name pass.
        report = link.link(conn, fold_on_name=False)
    finally:
        conn.close()

    assert report["folded"] == 1
    assert report["merged_by"] == {"phone": 1}


def test_nickname_resolution_can_be_switched_off(monkeypatch):
    """`NICKNAME_ENABLED = False` keeps `Dave` and `David` apart at write time."""
    monkeypatch.setattr(canon, "NICKNAME_ENABLED", False)
    assert canon.canonical("Dave Sartori", kind="person").key == "dave sartori"
    monkeypatch.setattr(canon, "NICKNAME_ENABLED", True)
    assert canon.canonical("Dave Sartori", kind="person").key == "david sartori"


def test_a_fuzzy_fold_records_fuzzy_as_the_reason(store):
    """The bug this fixes: every merged node on the live store said `exact_name`.

    `merged_by` used to be stamped by the *writer* from `canon` evidence at write time, and
    `link` could only `coalesce` into an already-set property — so a node that entered as
    `exact_name` kept that value even when the fold that merged it was a typo match. The
    store said "same canonical name" about two nodes whose canonical names differed.

    `link._fold` owns the field now: it is the only thing that merges, so the only thing
    that knows why.
    """
    telegram = _chat("telegram", "t1", ("Chris Tanaka",))
    whatsapp = _chat("whatsapp", "w1", ("Chirs Tanaka",))
    messages = [
        _message(telegram, 0, "Chris Tanaka"),
        _message(whatsapp, 0, "Chirs Tanaka"),
    ]

    _write(store, [telegram, whatsapp], messages)

    row = tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.merged_by AS why")["rows"][0]
    assert row["why"] == "fuzzy"


def test_the_reason_is_stamped_by_the_fold_not_the_writer(store):
    """`merged_by` belongs to `link`, because `link` is the only thing that merges.

    The bug this fixes: every merged Correspondent on the live store said `exact_name`,
    including the typo pairs. The writer stamped the field from `canon` evidence at write
    time and `link` could only `coalesce` into an already-set property — so a node that
    entered as `exact_name` kept that value even when the fold was a typo match.

    This asserts the property of the *code*: `_fold` takes a reason and writes it.
    """
    import inspect

    from relate_comms import writer as writer_module

    assert "reason" in inspect.signature(link._fold).parameters
    # The writer no longer sets it — if this assertion fails, the two sources are back.
    assert "merged_by" not in writer_module._CORRESPONDENT_CYPHER
