"""Body-entity extraction: Places, one generic pipeline, three steps that never blur.

The contract these tests hold:

    extract   proposes spans with offsets; decides nothing
    canon     folds spellings inside one platform
    link      merges across platforms

A wrong extractor must be re-runnable; a wrong merge must be undoable. Both are only
true if the three steps stay separate, so most of what follows asserts a boundary
rather than an outcome.

Run: python -m pytest tests/test_extract_places.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import canon, extract, link, tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

# spaCy is a declared dependency, but a machine without the English model must skip
# these rather than fail: the feature degrades to "no nodes", which is the design.
pytestmark = pytest.mark.skipif(
    not extract.available(), reason=extract.unavailable_reason() or "no extractor"
)


def _chat(platform: str, chat_id: str, people: tuple[str, ...]) -> Chat:
    return Chat(platform=platform, chat_id=chat_id, title=people[0],
                kind="personal_chat", is_group=False, participant_names=people)


def _message(chat: Chat, index: int, sender: str, body: str) -> Message:
    message_id = f"m{index:03d}"
    return Message(
        key=make_key(chat.platform, chat.chat_id, message_id),
        platform=chat.platform, chat_id=chat.chat_id, message_id=message_id,
        ts_utc=_BASE + timedelta(minutes=index),
        sender_name=sender, sender_id=None, body=body,
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
    """Write -> places -> link, the order `ingest()` uses."""
    result = IngestResult(platform=chats[0].platform, export_path="fixture",
                          chats=chats, messages=messages)
    conn = writer.connect(path)
    try:
        writer.write(conn, result)
        writer.write_correspondents(conn, result)
        found = extract.extract((m.key, m.platform, m.body) for m in result.messages)
        meta = {
            m.key: (writer.thread_key(m), m.ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
            for m in result.messages
        }
        counted = writer.write_places(conn, found, message_meta=meta)
        report = link.link(conn)
        return counted, report
    finally:
        conn.close()


def _places() -> dict[str, dict]:
    rows = tools.run_cypher(
        "MATCH (p:Place) RETURN p.key AS k, p.platforms AS ps, p.mention_count AS n, "
        "labels(p) AS l")["rows"]
    return {row["k"]: row for row in rows}


# ------------------------------------------------------------------- extraction


def test_extraction_returns_offsets_that_index_the_body():
    """A mention must be re-derivable: the span has to point at the text it claims."""
    body = "Flying to Austin tomorrow, then 12 Baker Street."
    mentions = extract.places(body, message_key="k", platform="sms")
    assert mentions
    for mention in mentions:
        assert body[mention.start:mention.end] == mention.text
        assert mention.message_key == "k"
        assert mention.platform == "sms"


def test_extraction_never_merges_two_spellings():
    """The whole point of step one: two spellings in one body stay two mentions."""
    mentions = extract.places("Denver tomorrow, then denver again.")
    texts = [mention.text for mention in mentions]
    assert texts.count("Denver") == 1
    assert texts.count("denver") == 1


def test_the_ruler_rescues_a_bare_city_the_model_calls_a_person():
    """`en_core_web_sm` says PERSON when the sentence gives no locative cue."""
    mentions = extract.places("Then Austin on Friday")
    assert [mention.text for mention in mentions] == ["Austin"]
    assert mentions[0].label == "GPE"


def test_a_leading_article_is_kept_in_the_span():
    """Slicing past `the` in `the Tate Modern` leaves a tail that reads as a place.

    `canon` strips the article for identity, so the key is the same either way; the
    span must stay whole so the text is what the model actually matched.
    """
    mentions = extract.places("meet at the Tate Modern")
    assert [mention.text for mention in mentions] == ["the Tate Modern"]


def test_a_body_with_no_places_is_an_empty_list_not_an_error():
    assert extract.places("lol ok, sounds good") == []


def test_extraction_batch_matches_single_message_extraction():
    rows = [("k1", "telegram", "Meet in Denver"), ("k2", "sms", "no places here"),
            ("k3", "email", "Flying to Seattle on Friday")]
    batched = {(mention.message_key, mention.text) for mention in extract.extract(rows)}
    assert batched == {("k1", "Denver"), ("k3", "Seattle")}


# --------------------------------------------------------------------- language


def test_non_latin_script_is_flagged_without_being_parsed():
    assert extract.language_guess("Спасибо большое за всё, увидимся завтра") == "non-en"
    assert extract.language_guess("شكرا جزيلا لك، أراك غدا في المكتب") == "non-en"


def test_a_short_body_is_not_accused_of_anything():
    """`ok` is English and Dutch. Below the word floor the guess must abstain."""
    assert extract.language_guess("ok") == "unknown"


def test_plain_english_is_english():
    body = ("Thanks for the update, I will call you tomorrow about the contract "
            "and we should have the numbers you asked for.")
    assert extract.language_guess(body) == "en"


# ------------------------------------------------------------------------ folding


def test_spellings_fold_to_one_place_on_one_platform(store):
    """Dropping the country tail is `canon`'s work, not the extractor's."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    messages = [
        _message(chat, 1, "David Sartori", "Meet me in Austin, TX"),
        _message(chat, 2, "David Sartori", "austin is lovely this time of year"),
    ]
    counted, _report = _write(store, [chat], messages)

    assert counted["places"] == 1
    assert set(_places()) == {"place:austin"}


def test_the_same_place_on_two_platforms_becomes_merged(store):
    telegram = _chat("telegram", "t1", ("Dave", "David Sartori"))
    messenger = _chat("messenger", "m1", ("Dan", "Dan Brown"))
    messages = [
        _message(telegram, 1, "David Sartori", "Meet me in Austin, TX"),
        _message(messenger, 3, "Dan Brown", "See you in Austin next week"),
    ]
    counted, _report = _write(store, [telegram, messenger], messages)

    row = _places()["place:austin"]
    assert sorted(row["ps"]) == ["messenger", "telegram"]
    assert "Merged" in row["l"]
    assert counted["mentions"] == 2


def test_a_place_on_one_platform_is_not_merged(store):
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    _write(store, [chat], [_message(chat, 1, "David Sartori", "Meet me in Denver")])

    row = _places()["place:denver"]
    assert row["ps"] == ["telegram"]
    assert "Merged" not in row["l"]


def test_mentions_hang_off_the_thread_not_the_message(store):
    """`tools.py` asks `(t:Thread)-[:MENTIONS]->(e)`; anything else is a dangling query."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    _write(store, [chat], [_message(chat, 1, "David Sartori", "Meet me in Denver")])

    edges = tools.run_cypher(
        "MATCH (t:Thread)-[:MENTIONS]->(p:Place) RETURN t.key AS t, p.key AS p")["rows"]
    assert edges == [{"t": "telegram:t1", "p": "place:denver"}]


def test_a_place_is_drawable_once_the_caller_asks(store):
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    _write(store, [chat], [_message(chat, 1, "David Sartori", "Meet me in Denver")])

    payload = tools.graph_slice(node_types=["Place"], edge_types=["MENTIONS_PLACE"])
    assert [node["id"] for node in payload["nodes"]] == ["place:denver"]
    assert payload["nodes"][0]["type"] == "Place"


# -------------------------------------------------------------- re-run / undo


def test_extraction_is_re_runnable_without_a_re_ingest(store):
    """The store holds messages, not spans. A second extraction adds nothing."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    messages = [_message(chat, 1, "David Sartori", "Meet me in Denver")]
    _write(store, [chat], messages)
    before = _places()

    conn = writer.connect(store)
    try:
        result = IngestResult(platform="telegram", export_path="fixture",
                              chats=[chat], messages=messages)
        found = extract.extract((m.key, m.platform, m.body) for m in messages)
        meta = {m.key: (writer.thread_key(m), m.ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
                for m in messages}
        writer.write_places(conn, found, message_meta=meta)
        second = link.link(conn)
    finally:
        conn.close()

    assert _places() == before
    assert second["entities"]["Place"]["folded"] == 0


def test_a_place_fold_is_undoable_by_deleting_the_node(store):
    """A place node is derived; deleting it must not touch the messages."""
    telegram = _chat("telegram", "t1", ("Dave", "David Sartori"))
    messenger = _chat("messenger", "m1", ("Dan", "Dan Brown"))
    messages = [
        _message(telegram, 1, "David Sartori", "Meet me in Austin, TX"),
        _message(messenger, 3, "Dan Brown", "See you in Austin next week"),
    ]
    _write(store, [telegram, messenger], messages)
    messages_before = tools.run_cypher("MATCH (m:Message) RETURN count(m) AS n")["rows"][0]["n"]
    conn = writer.connect(store)
    try:
        conn.cursor().execute("MATCH (p:Place) DETACH DELETE p")
        conn.commit()
    finally:
        conn.close()

    assert _places() == {}
    assert tools.run_cypher("MATCH (m:Message) RETURN count(m) AS n")["rows"][0]["n"] \
        == messages_before


# ------------------------------------------------------------------ guard rails


def test_an_organisation_the_model_finds_is_not_a_place(store):
    """`Kensington Market` is an ORG. Guessing it is a place would be extraction deciding."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    _write(store, [chat], [_message(chat, 1, "David Sartori", "Kensington Market is closed")])
    assert _places() == {}


def test_a_place_is_never_drawn_as_a_fuzzy_candidate(store):
    """Two places a letter apart are two places; there is no second signal to weigh."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    messages = [
        _message(chat, 1, "David Sartori", "I am in Fargo"),
        _message(chat, 2, "David Sartori", "I am in Largo"),
    ]
    _counted, report = _write(store, [chat], messages)

    assert report["entities"]["Place"]["possibly"] == 0
    edges = tools.run_cypher(
        "MATCH (:Place)-[r:POSSIBLY]->(:Place) RETURN count(r) AS n")["rows"][0]["n"]
    assert edges == 0


def test_a_false_positive_is_one_node_and_never_a_merge(store):
    """The accepted failure mode: model mislabels an org `GPE`, `link` must not act on it."""
    chat = _chat("telegram", "t1", ("Dave", "David Sartori"))
    _write(store, [chat], [
        _message(chat, 1, "David Sartori", "nothing new from Databricks."),
    ])
    row = _places().get("place:databricks")
    if row is not None:  # the model's answer is frame-sensitive; accept either
        assert "Merged" not in row["l"]
        assert row["n"] == 1
    assert tools.run_cypher(
        "MATCH (:Place)-[r:POSSIBLY]->(:Place) RETURN count(r) AS n")["rows"][0]["n"] == 0


def test_place_canonicalisation_drops_a_country_or_code_but_keeps_a_region():
    """The fold rule the tests above rely on, asserted directly on `canon`.

    `London` as a tail is *not* a country: it is the city in Ontario. `Kensington,
    London` therefore stays two tokens, which is the correct, if surprising, answer —
    the tail rule exists to remove redundancy, not to guess geography.
    """
    assert canon.canonical("Austin, TX", kind="place").key == "austin"
    assert canon.canonical("Kensington, UK", kind="place").key == "kensington"
    # A region spelled out is identity, so it is kept.
    assert canon.canonical("London, Ontario", kind="place").key == "london, ontario"
    assert canon.canonical("Kensington, London", kind="place").key == "kensington, london"


def test_a_leading_article_is_not_identity_for_a_place():
    """`the Bay Area` and `Bay Area` were two nodes before this branch stripped it."""
    assert canon.canonical("the Bay Area", kind="place").key == "bay area"
    assert canon.canonical("Bay Area", kind="place").key == "bay area"
    assert canon.canonical("The Bay Area", kind="place").key == "bay area"


def test_an_abbreviated_qualifier_expands_to_its_real_word():
    """The sample writer emits `N Dakota` on one platform and `North Dakota` on another."""
    assert canon.canonical("N Dakota", kind="place").key == "north dakota"
    assert canon.canonical("North Dakota", kind="place").key == "north dakota"
    assert canon.canonical("S Dakota", kind="place").key == "south dakota"
    # A bare initial is not a qualifier: `N` alone stays `n`.
    assert canon.canonical("N", kind="place").key == "n"
