"""Search: BM25 fulltext, names, the screener, and vector.

The behaviours pinned here are the ones that were wrong in the live app and are
invisible in a graph screenshot:

1. **A name is not in any message body.** `search_fulltext` scanned bodies only, so
   typing a correspondent's name returned nothing. Measured on the live store:
   `Alicia Moreno` exists with 8 messages, and zero bodies contain "moreno".
2. **A greeting is not a sentence.** `hi`, `ok`, `thanks` embed to near-identical
   vectors and crowd every semantic result.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _chat(platform: str, chat_id: str, title: str, people: tuple[str, ...]) -> Chat:
    return Chat(platform=platform, chat_id=chat_id, title=title,
                kind="personal_chat", is_group=False, participant_names=people)


def _message(chat: Chat, index: int, sender: str, body: str, *,
             is_self: bool = False, day: int = 0) -> Message:
    return Message(
        key=make_key(chat.platform, chat.chat_id, f"m{index:03d}"),
        platform=chat.platform, chat_id=chat.chat_id, message_id=f"m{index:03d}",
        ts_utc=_BASE + timedelta(days=day, minutes=index),
        sender_name=sender, sender_id=None, body=body,
        reply_to=None, has_attachments=False, is_self=is_self, raw_kind="text",
    )


@pytest.fixture
def store(tmp_path):
    """A fresh store, closed before the test runs.

    Relate is single-writer: a connection held open by the fixture locks the file
    and every tool call fails with `storage locked`.
    """
    path = tmp_path / "graph.rl"
    writer.connect(path).close()
    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


def _write(path, result: IngestResult) -> None:
    conn = writer.connect(path)
    try:
        writer.write(conn, result)
        writer.write_correspondents(conn, result)
    finally:
        conn.close()


# ------------------------------------------------------------------ names

def test_a_correspondents_name_is_findable(store):
    """The bug: a name lives on the Correspondent, not in any body."""
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    messages = [
        _message(chat, 0, "Mark Jones", "did the invoice get sorted?", is_self=True),
        _message(chat, 1, "Alicia Moreno", "yes, all done"),
    ]
    _write(store, IngestResult(platform="telegram", export_path="fixture",
                               chats=[chat], messages=messages))

    result = tools.search_fulltext("Moreno", limit=10)

    assert result["name_matches"] == 1
    assert result["body_matches"] == 0, "no body contains the surname"
    assert result["hits"][0]["match"] == "name"
    assert "Alicia Moreno" in result["hits"][0]["snippet"]
    # A name hit is a THREAD row, so the Viewer opens the conversation.
    assert result["hits"][0]["type"] == "Thread"
    assert result["hits"][0]["thread_key"] == "telegram:c1"


def test_a_surname_fragment_matches_a_full_name(store):
    chat = _chat("telegram", "c1", "Mateo Burton", ("Mateo Burton", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[_message(chat, 0, "Mateo Burton", "hello there")],
    ))

    assert tools.search_fulltext("Burton", limit=10)["name_matches"] == 1
    assert tools.search_fulltext("Mateo", limit=10)["name_matches"] == 1


def test_a_name_hit_is_not_repeated_as_a_body_hit(store):
    """A thread surfaced by name must not appear twice."""
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[_message(chat, 0, "Mark Jones", "Moreno said yes", is_self=True)],
    ))

    result = tools.search_fulltext("Moreno", limit=10)
    keys = [hit["thread_key"] for hit in result["hits"]]
    assert len(keys) == len(set(keys)), "the thread appears once"


def test_body_search_still_works(store):
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[_message(chat, 0, "Mark Jones", "did the invoice get sorted?",
                           is_self=True)],
    ))

    result = tools.search_fulltext("invoice", limit=10)
    assert result["body_matches"] >= 1
    assert result["hits"][0]["match"] == "body"


# --------------------------------------------------------------- screener

@pytest.mark.parametrize("body", ["hello", "hi", "ok", "thanks", "im going there",
                                  "what time is it at", "where are we"])
def test_a_greeting_or_fragment_is_screened_out(body):
    keep, reason = tools.screen_body(body)
    assert not keep, f"{body!r} should not be embedded ({reason})"


@pytest.mark.parametrize("body", [
    "Hetzner is down",
    "can you check the ABC invoice for me?",
    "did the ABC invoice get sorted?",
    "are you free tonight?",
    "what did Rotary Club say?",
])
def test_a_real_sentence_is_kept(body):
    keep, reason = tools.screen_body(body)
    assert keep, f"{body!r} should be embedded ({reason})"


def test_the_screener_fails_open_without_spacy(monkeypatch):
    """A missing model must embed everything, not nothing.

    A missing vector is a silent hole in search; a junk vector is only noise, and
    noise is visible.
    """
    monkeypatch.setattr(tools, "_SCREENER", False)
    keep, reason = tools.screen_body("hello")
    assert keep
    assert reason == "no-screener"


def test_an_empty_body_is_not_embedded():
    keep, reason = tools.screen_body("   ")
    assert not keep
    assert reason == "empty"


# ---------------------------------------------------------------- status

def test_flush_keeps_the_graph_and_reclaims_disk(store):
    """Flush deletes vectors, keeps every node and edge, and shrinks the file.

    The bug this pins: the first version wrote the rebuild into `graph.rl.flush`,
    which Relate reads as a *directory* store, so the swap produced an empty graph
    and reported success.
    """
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[
            _message(chat, 0, "Mark Jones", "did the invoice get sorted?",
                     is_self=True),
            _message(chat, 1, "Alicia Moreno", "yes, all done"),
        ],
    ))

    before = tools.embed_status()
    result = tools.flush_embeddings(write_enabled=True, confirm=True)

    assert result["flushed"] is True
    assert result["nodes"] > 0
    # The graph survives.
    assert tools.run_cypher("MATCH (m:Message) RETURN count(m) AS n")["rows"][0]["n"] == 2
    assert tools.run_cypher("MATCH (t:Thread) RETURN count(t) AS n")["rows"][0]["n"] == 1
    assert tools.run_cypher("MATCH ()-[r]->() RETURN count(r) AS n")["rows"][0]["n"] > 0
    # The vectors do not.
    after = tools.embed_status()
    assert after["embedded"] == 0
    assert after["total"] == before["total"]


def test_search_works_immediately_after_a_flush(store):
    """The rebuild copies nodes and edges, not indexes — so it must recreate them.

    Without this the first search after a flush failed with `IndexDoesNotExist`.
    """
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[_message(chat, 0, "Mark Jones", "did the invoice get sorted?",
                           is_self=True)],
    ))

    tools.flush_embeddings(write_enabled=True, confirm=True)

    assert tools.search_fulltext("invoice", limit=5)["count"] >= 1
    assert tools.search_fulltext("Moreno", limit=5)["name_matches"] == 1


def test_flush_needs_write_and_confirm(store):
    with pytest.raises(tools.ToolError):
        tools.flush_embeddings(write_enabled=False, confirm=True)
    with pytest.raises(tools.ToolError):
        tools.flush_embeddings(write_enabled=True, confirm=False)


def _dump(path):
    """Every node (labels + all properties) and every edge, minus the vectors."""
    import relate

    conn = relate.connect(str(path), read_only=True)
    cur = conn.cursor()

    cur.execute("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props")
    nodes = []
    for row in cur.fetchall():
        data = dict(row)
        props = dict(data["props"] or {})
        props.pop("emb", None)
        props.pop("emb_skipped", None)
        nodes.append((tuple(sorted(data["labels"] or [])), props))

    cur.execute(
        "MATCH (a)-[r]->(b) RETURN type(r) AS type, properties(r) AS props, "
        "       a.key AS f, b.key AS t"
    )
    edges = []
    for row in cur.fetchall():
        data = dict(row)
        edges.append((
            data["type"], data["f"], data["t"], dict(data["props"] or {}),
        ))

    cur.execute("SHOW INDEXES")
    # Compare index **definitions**, not names. The live store's indexes were created
    # by an older `_SCHEMA` and carry auto-generated names (`Message_key`); a rebuild
    # replays the current `_SCHEMA` and names them `msg_key`. Same index, different
    # label — comparing names would fail on a difference that does not matter.
    indexes = set()
    for row in cur.fetchall():
        data = dict(row)
        indexes.add((
            data.get("type"),
            tuple(data.get("labelsOrTypes") or ()),
            tuple(data.get("properties") or ()),
        ))
    conn.close()
    return nodes, edges, indexes


def test_flush_is_byte_identical_for_every_node_and_edge(store):
    """**The fidelity guard.** Flush rewrites the store, so it must lose nothing.

    This is the test that makes the rebuild safe to ship. It compares every node's
    labels and every property, and every edge's type, endpoints and properties,
    before and after. A future change to the copy loop that drops a property, a
    label or a relationship property fails here rather than silently in a user's
    store.

    The only permitted difference is the vector index, which is meant to go.
    """
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    group = Chat(platform="telegram", chat_id="g1", title="Team", kind="group_chat",
                 is_group=True, participant_names=("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat, group],
        messages=[
            _message(chat, 0, "Mark Jones", "did the invoice get sorted?",
                     is_self=True),
            _message(chat, 1, "Alicia Moreno", "yes, all done"),
            _message(group, 2, "Mark Jones", "Hetzner is down", is_self=True),
        ],
    ))

    before_nodes, before_edges, before_idx = _dump(store)
    tools.flush_embeddings(write_enabled=True, confirm=True)
    after_nodes, after_edges, after_idx = _dump(store)

    # Compare as JSON strings: a property dict is not orderable, and a set of
    # tuples containing dicts is not hashable.
    def as_set(rows):
        return {json.dumps(row, sort_keys=True, default=str) for row in rows}

    assert as_set(before_nodes) == as_set(after_nodes), "a node or property changed"
    assert as_set(before_edges) == as_set(after_edges), "an edge or property changed"

    # **Every index definition survives, including the vector one.** The rebuild
    # replays `_SCHEMA`, so `msg_emb` comes back empty rather than missing — which is
    # what makes the first vector search after a flush say "vector store empty"
    # instead of failing with `IndexDoesNotExist`.
    assert before_idx - after_idx == set(), "an index was lost"
    assert after_idx - before_idx == set(), "an unexpected index appeared"
    assert any(i[0] == "FULLTEXT" for i in after_idx), "BM25 must survive"
    assert any(i[0] == "VECTOR" for i in after_idx), "the vector index must be recreated"
    assert any(i[0] == "RANGE" for i in after_idx), "key indexes must survive"


def test_embed_status_counts_skipped_separately(store):
    chat = _chat("telegram", "c1", "Alicia Moreno", ("Alicia Moreno", "Mark Jones"))
    _write(store, IngestResult(
        platform="telegram", export_path="fixture", chats=[chat],
        messages=[_message(chat, 0, "Mark Jones", "hello", is_self=True)],
    ))

    status = tools.embed_status()
    assert status["total"] == 1
    assert status["embedded"] == 0
    assert status["skipped"] == 0
    assert status["missing"] == 1
    assert status["ready"] is False
