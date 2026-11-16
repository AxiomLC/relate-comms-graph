"""The tool layer: what the UI, the chat and MCP all bind.

Three promises are tested here, because they are the ones a surface can break
without noticing:

1. **The store is always whole.** No tool takes a UI toggle as an implicit input;
   `graph_slice` defaults to everything the canvas draws, and a hidden toggle can
   never narrow it.
2. **Truncation is never silent.** A slice or search that hits `limit` says so.
3. **A failure is a `ToolError` with a sentence in it**, never a traceback and
   never a silent empty result.

Run: python -m pytest tests -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import tools, writer
from relate_comms.schema import Chat, IngestResult, Message, make_key

_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _message(chat: Chat, index: int, body: str, sender: str, *, is_self: bool) -> Message:
    message_id = f"m{index:03d}"
    return Message(
        key=make_key(chat.platform, chat.chat_id, message_id),
        platform=chat.platform,
        chat_id=chat.chat_id,
        message_id=message_id,
        ts_utc=_BASE + timedelta(minutes=index),
        sender_name=sender,
        sender_id=None,
        body=body,
        reply_to=None,
        has_attachments=False,
        is_self=is_self,
        raw_kind="text",
    )


def _fixture_result() -> IngestResult:
    """Three threads, twelve messages, two correspondents — small but uneven.

    Written through `writer.write`, the same path ingest uses, so the tool layer
    is tested against the store shape it will actually meet.
    """
    alpha = Chat(platform="telegram", chat_id="chatA", title="Alpha", kind="private",
                 is_group=False, participant_names=("Me", "Ada Lovelace"))
    # No stated title: exercises the fallback chain (§3.3).
    beta = Chat(platform="telegram", chat_id="chatB", title="", kind="private",
                is_group=False, participant_names=("Me", "Grace Hopper"))
    gamma = Chat(platform="whatsapp", chat_id="chatC", title="Gamma", kind="group",
                 is_group=True, participant_names=("Me", "Ada Lovelace", "Alan Turing"))

    messages = [
        _message(alpha, i, f"alpha body {i} about the alpha project", "Me", is_self=True)
        for i in range(6)
    ]
    messages += [
        _message(beta, i, f"beta body {i}", "Grace Hopper", is_self=False)
        for i in range(4)
    ]
    messages += [
        _message(gamma, 0, "gamma body, call me on PHONE-1", "Alan Turing", is_self=False),
        _message(gamma, 1, "gamma body two", "Me", is_self=True),
    ]

    return IngestResult(platform="telegram", export_path="fixture", chats=[alpha, beta, gamma],
                        messages=messages)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "graph.rl"
    result = _fixture_result()

    conn = writer.connect(path)
    try:
        writer.write(conn, result, owner="Me")
        writer.write_correspondents(conn, result, owner="Me")
    finally:
        conn.close()

    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


def _a_thread_key() -> str:
    return tools.graph_slice(node_types=["Thread"], limit=1)["nodes"][0]["id"]


# ------------------------------------------------------------------ registry

def test_every_registered_tool_has_a_schema_and_a_description():
    assert tools.REGISTRY, "nothing registered"
    for name, tool in tools.REGISTRY.items():
        assert tool.name == name
        assert tool.description, f"{name} has no description for a model to read"
        schema = tool.schema
        assert schema["name"] == name
        assert schema["parameters"]["type"] == "object"


def test_write_toggle_is_not_a_model_settable_argument():
    """`write_enabled` is the surface's switch; a model must not be able to pass it."""
    for name in ("ingest", "prune_spool"):
        properties = tools.REGISTRY[name].schema["parameters"]["properties"]
        assert "write_enabled" not in properties, name


def test_confirm_is_visible_to_a_model():
    """`prune_spool` needs a deliberate confirm, so it must be in the schema."""
    properties = tools.REGISTRY["prune_spool"].schema["parameters"]["properties"]
    assert properties["confirm"]["type"] == "boolean"


def test_unimplemented_tools_are_not_registered():
    """A tool that always fails burns a model turn; absence is the honest signal."""
    for name in ("semantic_search", "hybrid_search", "person_profile",
                 "who_did_i_talk_to"):
        assert name not in tools.REGISTRY


# --------------------------------------------------------------------- graph

def test_graph_slice_draws_threads_and_correspondents_by_default(store):
    slice_ = tools.graph_slice()
    assert slice_["node_types"] == ["Thread", "Correspondent"]
    assert slice_["edge_types"] == ["WITH"]
    assert slice_["counts"]["nodes"] > 0
    types = {node["type"] for node in slice_["nodes"]}
    assert types == {"Thread", "Correspondent"}
    # Every edge has both endpoints drawn, or it is not returned.
    ids = {node["id"] for node in slice_["nodes"]}
    for edge in slice_["edges"]:
        assert edge["source"] in ids and edge["target"] in ids


def test_graph_slice_truncation_is_reported(store):
    full = tools.graph_slice()
    small = tools.graph_slice(limit=2)
    assert small["counts"]["nodes"] == 2
    assert small["truncated"] is True
    assert full["truncated"] is False


def test_graph_slice_never_inherits_a_ui_toggle(store):
    """`node_types=None` means everything, not "whatever the UI has on"."""
    everything = tools.graph_slice()
    explicit = tools.graph_slice(node_types=["Thread", "Correspondent"])
    assert everything["counts"] == explicit["counts"]


def test_graph_slice_rejects_an_unknown_type(store):
    with pytest.raises(tools.ToolError, match="unknown type"):
        tools.graph_slice(node_types=["Person"])


def test_graph_slice_can_draw_messages_on_request(store):
    slice_ = tools.graph_slice(node_types=["Message"], edge_types=["IN"], limit=5)
    assert {node["type"] for node in slice_["nodes"]} == {"Message"}
    assert slice_["truncated"] is True
    # `IN` edges point at Threads, which this slice did not draw.
    assert slice_["counts"]["edges"] == 0
    assert slice_["edges_skipped"] > 0


# -------------------------------------------------------------------- thread

def test_thread_arc_pages_and_says_whether_more_remains(store):
    key = _a_thread_key()
    first = tools.thread_arc(key, limit=2)
    assert first["thread"]["key"] == key
    assert first["thread"]["title"], "a thread title is never empty"
    assert len(first["messages"]) <= 2
    assert first["total"] >= len(first["messages"])

    if first["total"] > 2:
        second = tools.thread_arc(key, limit=2, skip=2)
        assert second["messages"][0]["key"] != first["messages"][0]["key"]
        assert first["has_more"] is True


def test_thread_arc_orders_newest_first(store):
    messages = tools.thread_arc(_a_thread_key(), limit=20)["messages"]
    stamps = [m["ts_utc"] for m in messages]
    assert stamps == sorted(stamps, reverse=True)


def test_thread_arc_filter_stays_inside_the_thread(store):
    key = _a_thread_key()
    unfiltered = tools.thread_arc(key, limit=1)
    filtered = tools.thread_arc(key, query="zzz-no-such-word-zzz", limit=5)
    assert filtered["total"] == 0
    assert filtered["messages"] == []
    assert filtered["thread"]["key"] == unfiltered["thread"]["key"]


def test_thread_arc_unknown_key_is_a_tool_error(store):
    with pytest.raises(tools.ToolError, match="no thread"):
        tools.thread_arc("telegram:does-not-exist")


# -------------------------------------------------------------------- search

def test_search_messages_finds_a_known_body(store):
    result = tools.search_messages("alpha", limit=5)
    assert result["mode"] == "substring"
    assert result["count"] == 5
    for hit in result["hits"]:
        assert hit["thread_key"].startswith(hit["platform"] + ":")
        assert "alpha" in hit["snippet"].lower()


def test_search_messages_is_case_insensitive(store):
    assert tools.search_messages("ALPHA", limit=5)["count"] == 5


def test_search_messages_truncation_is_reported(store):
    result = tools.search_messages("alpha", limit=1)
    assert result["count"] == 1
    assert result["truncated"] is True


def test_search_messages_rejects_an_empty_query(store):
    with pytest.raises(tools.ToolError, match="query is required"):
        tools.search_messages("   ")


def test_search_messages_scopes_to_a_thread(store):
    key = "telegram:chatA"
    result = tools.search_messages("alpha", limit=20, thread_key=key)
    assert result["count"] == 6
    assert {hit["thread_key"] for hit in result["hits"]} == {key}


# ------------------------------------------------------------------- message

def test_message_view_returns_the_body_and_its_thread(store):
    hit = tools.search_messages("alpha", limit=1)["hits"][0]
    message = tools.message_view(hit["key"])
    assert message["key"] == hit["key"]
    assert message["thread_key"] == hit["thread_key"]
    assert message["body"]
    assert isinstance(message["attachments"], list)


def test_message_view_unknown_key_is_a_tool_error(store):
    with pytest.raises(tools.ToolError, match="no message"):
        tools.message_view("telegram:nope:nope")


# -------------------------------------------------------------------- cypher

def test_run_cypher_returns_columns_and_rows(store):
    result = tools.run_cypher("MATCH (t:Thread) RETURN t.key AS key LIMIT 3")
    assert result["columns"] == ["key"]
    assert result["count"] == len(result["rows"]) <= 3


def test_run_cypher_refuses_writes(store):
    for statement in ("CREATE (x:Zzz)", "MATCH (t:Thread) DELETE t",
                      "MATCH (t:Thread) SET t.title = 'x'"):
        with pytest.raises(tools.ToolError, match="read-only"):
            tools.run_cypher(statement)


def test_run_cypher_allows_the_word_create_inside_a_string(store):
    """A body search for the word `create` is not a write."""
    result = tools.run_cypher(
        "MATCH (m:Message) WHERE m.body CONTAINS 'create' RETURN count(m) AS n"
    )
    assert result["count"] == 1


def test_run_cypher_truncation_is_reported(store):
    result = tools.run_cypher("MATCH (t:Thread) RETURN t.key AS key", limit=1)
    assert result["count"] == 1
    assert result["truncated"] is True


def test_run_cypher_does_not_rewrite_the_query(store):
    """A statement with its own LIMIT is returned as written."""
    statement = "MATCH (t:Thread) RETURN t.key AS key LIMIT 2"
    result = tools.run_cypher(statement, limit=500)
    assert result["query"] == statement
    assert result["count"] == 2
    assert result["truncated"] is False


# ------------------------------------------------------------------ evidence

def test_types_present_lists_only_types_with_rows(store):
    present = tools.types_present()
    counts = {t["type"]: t["count"] for t in present["node_types"]}
    assert counts["Thread"] == 3
    assert counts["Message"] == 12
    # One per (platform, name): Ada is two nodes, one per platform (§5.6).
    assert counts["Correspondent"] == 4
    assert all(t["count"] > 0 for t in present["node_types"])
    assert all(t["count"] > 0 for t in present["edge_types"])


def test_evidence_counts_reports_the_store_and_the_withheld_aliases(store):
    evidence = tools.evidence_counts()
    assert evidence["messages"] == 12
    assert evidence["threads"] == 3
    assert evidence["messages"] >= evidence["non_text_total"]
    # One distinct alias, repeated nowhere: counted once, not per message.
    assert evidence["withheld"] == {"phones": 1}
    assert evidence["withheld_total"] == 1


# --------------------------------------------------------------------- gates

def test_write_tools_are_refused_without_the_toggle(store):
    with pytest.raises(tools.ToolError, match="write access is disabled"):
        tools.ingest(which="sample")


def test_destructive_tool_needs_write_and_confirm(store):
    with pytest.raises(tools.ToolError, match="write access is disabled"):
        tools.prune_spool()
    with pytest.raises(tools.ToolError, match="confirm=true"):
        tools.prune_spool(write_enabled=True)


def test_a_missing_store_is_a_tool_error_not_a_traceback(tmp_path):
    previous = tools.store_path()
    tools.configure(store=tmp_path / "absent.rl")
    try:
        with pytest.raises(tools.ToolError, match="no store"):
            tools.types_present()
    finally:
        tools.configure(store=previous)
