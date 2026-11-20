"""`run_cypher`'s write guard, and the `:Merged` label it used to refuse.

The guard is a word-bounded scan, not a substring test. `:Merged` contains `MERGE`,
so a substring scan rejected the audit query the build plan specifies — a read-only
statement refused as a write. These tests pin both directions: the label passes, the
keyword does not.

Run: python -m pytest tests/test_cypher_guard.py -q
"""
from __future__ import annotations

import pytest

from relate_comms import tools


@pytest.fixture
def store(tmp_path):
    """One merged and one unmerged Correspondent, so `:Merged` has something to find."""
    from relate_comms import writer
    from relate_comms.schema import Chat, IngestResult, Message, make_key
    from datetime import datetime, timezone

    path = tmp_path / "graph.rl"
    conn = writer.connect(path)
    try:
        cur = conn.cursor()
        cur.execute("MERGE (a:Correspondent {key: 'person:ada lovelace'}) "
                    "SET a.display_name = 'Ada Lovelace', a.platform = 'telegram', "
                    "    a.platforms = ['telegram'], a.merged_by = 'exact_name'")
        cur.execute("MERGE (b:Correspondent {key: 'person:grace hopper'}) "
                    "SET b.display_name = 'Grace Hopper', b.platform = 'telegram', "
                    "    b.platforms = ['telegram', 'whatsapp'], "
                    "    b.merged_by = 'nickname'")
        cur.execute("MATCH (b:Correspondent {key: 'person:grace hopper'}) SET b:Merged")
        conn.commit()
    finally:
        conn.close()

    previous = tools.store_path()
    tools.configure(store=path)
    try:
        yield path
    finally:
        tools.configure(store=previous if previous.exists() else None)


def test_the_merged_label_is_queryable(store):
    """The audit query from the build plan must run."""
    rows = tools.run_cypher(
        "MATCH (c:Correspondent:Merged) RETURN c.merged_by AS by, count(*) AS n"
    )["rows"]
    assert rows == [{"by": "nickname", "n": 1}]


def test_merged_as_a_boolean_projection_is_queryable(store):
    rows = tools.run_cypher(
        "MATCH (c:Correspondent) RETURN c.key AS k, c:Merged AS m ORDER BY k"
    )["rows"]
    assert rows == [
        {"k": "person:ada lovelace", "m": False},
        {"k": "person:grace hopper", "m": True},
    ]


def test_a_merged_by_property_is_not_read_as_a_write(store):
    """`merged_by` contains `MERGE` too — the guard must not trip on a property name."""
    rows = tools.run_cypher(
        "MATCH (c:Correspondent) WHERE c.merged_by = 'nickname' RETURN c.key AS k"
    )["rows"]
    assert rows == [{"k": "person:grace hopper"}]


@pytest.mark.parametrize("query", [
    "MATCH (c:Correspondent) SET c.x = 1",
    "MERGE (c:Correspondent {key: 'x'})",
    "MATCH (c:Correspondent) DETACH DELETE c",
    "MATCH (c:Correspondent) REMOVE c.x",
    "MATCH (c:Correspondent) FOREACH (_ IN [1] | SET c.x = 1)",
])
def test_writes_are_still_refused(store, query):
    with pytest.raises(tools.ToolError, match="read-only tool"):
        tools.run_cypher(query)


def test_a_keyword_inside_a_string_literal_is_not_a_write(store):
    """`WHERE m.body CONTAINS 'create'` is a read."""
    rows = tools.run_cypher(
        "MATCH (c:Correspondent) WHERE c.display_name CONTAINS 'set' "
        "RETURN count(c) AS n"
    )["rows"]
    assert rows == [{"n": 0}]
