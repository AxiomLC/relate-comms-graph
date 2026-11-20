"""Cross-connect — fold the nodes whose keys differ, and draw a line where they might.

WHY THIS FILE EXISTS
--------------------
Edit 1 made `Correspondent.key` `person:<canonical>`, so one spelling of one name on
two platforms is already one node. What it cannot do is fold two nodes whose keys are
*different*:

    person:+27845189029      a WhatsApp contact the export only knows by phone
    person:david sartori     the same human, named on Telegram

Those never share a key, so they stay apart until something looks at the evidence
across them. That is this module. It runs **once, at the end of an ingest**, after
every batch is written — per batch it would only ever see one platform.

TWO OUTCOMES, NEVER ONE
-----------------------
`archive_docs/direction.md` §5: a fold is unrecoverable without a re-ingest, an edge
is a line you can look at and ignore. So:

  exact evidence   MERGE + DELETE + edge re-point   (`merged_by` records why)
  fuzzy evidence   `(:Correspondent)-[:POSSIBLY]->(:Correspondent)`, both stay

The fold is a **re-point, not a property set**. `WITH` edges hang off the node being
deleted, and `DETACH DELETE` would take them with it — the graph would silently lose
the threads that made the node worth folding. Every edge is moved first, then the
loser is deleted.

WHAT COUNTS AS EXACT
--------------------
    phone       same digits (`+27 84 518 9029` == `27845189029`)
    email       same lowercased address
    exact_name  same canonical name
    nickname    same canonical name after nickname resolution

Phone and email are the strong ones: a name is a claim, an address is an identifier.
Name folds are normally a no-op because edit 1 already collapsed identical canonical
names into one key — they matter for a node whose *handle* is a name while its key is
a phone.

WHY THE WINNER IS CHOSEN, NOT GUESSED
-------------------------------------
A fold must be deterministic or the graph reshuffles between ingests. The survivor is
the node with the **most `WITH` edges**, then the **lowest key** — a total order, so
the same store always folds the same way. `:Merged` and `merged_by` are then set by
`writer._reconcile`, which recomputes every derived property from the flat facts the
survivor inherited.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from . import canon

# The evidence classes, strongest first. `merged_by` on the surviving node is the
# weakest link in the chain that produced it — a phone fold that also matched on a
# name is still a phone fold, and the audit query should say so.
EVIDENCE_ORDER: tuple[str, ...] = ("phone", "email", "exact_name", "nickname")

# Below this a fuzzy pair is noise. Same knob the report uses, so a candidate that
# `canon.candidates()` would print is a candidate this draws.
FUZZY_THRESHOLD = canon.FUZZY_REPORT


def link(conn: Any, *, fold_on_name: bool | None = None) -> dict[str, Any]:
    """Fold exact matches, draw `POSSIBLY` for fuzzy ones. Idempotent.

    Returns a report the ingest panel can show:

        folded      how many nodes were deleted into another
        merged_by   {phone: n, email: n, exact_name: n, nickname: n}
        possibly    how many `POSSIBLY` edges were written
        groups      the fold groups, as `[[survivor, loser, …], …]`, for the log

    Running it twice changes nothing: the second run finds one node per group, and
    `MERGE` on the `POSSIBLY` edge is a no-op.
    """
    if fold_on_name is None:
        fold_on_name = canon.FOLD_ON_NAME

    nodes = _load(conn)
    if len(nodes) < 2:
        return {"folded": 0, "merged_by": {}, "possibly": 0, "groups": []}

    # The per-platform spellings are needed by BOTH passes: a name fold reads them to
    # find a phone-keyed node's name, and the fuzzy pass reads them to score a pair.
    handles = _handles(conn, [node["key"] for node in nodes])
    for node in nodes:
        node["handles"] = handles.get(node["key"], {})

    groups = _fold_groups(nodes, fold_on_name=fold_on_name)
    folded = 0
    by_reason: dict[str, int] = defaultdict(int)
    report_groups: list[list[str]] = []

    for survivor, losers, reason in groups:
        _fold(conn, survivor, losers)
        folded += len(losers)
        by_reason[reason] += len(losers)
        report_groups.append([survivor["key"], *[n["key"] for n in losers]])

    if folded:
        # A fold changes the flat facts the derived properties are built from, so
        # `platforms` / `platform_label` / `:Merged` must be recomputed. `_reconcile`
        # is idempotent and reads only `handle_<p>` / `seen_<p>`, which `_inherit`
        # has just unioned onto the survivor.
        from .writer import _reconcile

        _reconcile(conn.cursor(), [group[0] for group in report_groups])
        conn.commit()

    # Re-read: a fold changes which nodes exist, and a fuzzy pair must never be
    # drawn between two nodes that are now one.
    remaining = _load(conn) if folded else nodes
    if folded:
        handles = _handles(conn, [node["key"] for node in remaining])
        for node in remaining:
            node["handles"] = handles.get(node["key"], {})
    possibly = _draw_possibly(conn, remaining)

    return {
        "folded": folded,
        "merged_by": dict(by_reason),
        "possibly": possibly,
        "groups": report_groups,
    }


# ------------------------------------------------------------------------ reading


def _load(conn: Any) -> list[dict[str, Any]]:
    """Every Correspondent, with the facts a fold decision needs.

    Placeholders are excluded: `messenger:placeholder:facebook user` and
    `linkedin:placeholder:linkedin member` are two different accounts that happen to
    both be anonymous, and folding them would claim one platform's spam is the
    other's. `canon` already keeps them platform-scoped; this keeps them unfolded.
    """
    cur = conn.cursor()
    cur.execute(
        "MATCH (c:Correspondent) "
        "OPTIONAL MATCH (t:Thread)-[:WITH]->(c) "
        "RETURN c.key AS key, c.platform AS platform, "
        "       coalesce(c.platforms, [c.platform]) AS platforms, "
        "       c.display_name AS display_name, c.phone_e164 AS phone, "
        "       c.email AS email, count(DISTINCT t) AS threads "
    )
    nodes = []
    for row in cur.fetchall():
        node = dict(row)
        if str(node["key"]).split(":", 1)[-1].startswith("placeholder:"):
            continue
        nodes.append(node)
    return nodes


def _handles(conn: Any, keys: Iterable[str]) -> dict[str, dict[str, str]]:
    """`key -> {platform: spelling}` from the flat `handle_<p>` properties.

    A name fold needs the *spelling*, not the canonical key: `person:+27845189029`
    carries `handle_whatsapp = "David Sartori"`, and that is the only place the name
    exists for a phone-keyed node.
    """
    from .writer import HANDLE_PREFIX

    keys = sorted(set(keys))
    if not keys:
        return {}
    cur = conn.cursor()
    cur.execute(
        "MATCH (c:Correspondent) WHERE c.key IN $keys RETURN properties(c) AS p",
        {"keys": keys},
    )
    out: dict[str, dict[str, str]] = {}
    for record in cur.fetchall():
        props = record["p"]
        out[props["key"]] = {
            name[len(HANDLE_PREFIX):]: value
            for name, value in props.items()
            if name.startswith(HANDLE_PREFIX) and value
        }
    return out


# ------------------------------------------------------------------- fold groups


def _fold_groups(
    nodes: list[dict[str, Any]], *, fold_on_name: bool,
) -> list[tuple[dict[str, Any], list[dict[str, Any]], str]]:
    """Group nodes that are provably one entity. Returns (survivor, losers, reason).

    Union-find over the evidence, so a chain folds as one group: a phone-only node
    joined to a named node by phone, and that named node joined to a third by email,
    is one person with three keys. Folding pairwise would leave two of the three
    apart depending on iteration order.
    """
    index = {node["key"]: position for position, node in enumerate(nodes)}
    parent = list(range(len(nodes)))
    reason_of: dict[int, str] = {}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int, reason: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        parent[rb] = ra
        # Keep the strongest evidence for the group: a phone match outranks a name.
        current = reason_of.get(ra)
        if current is None or EVIDENCE_ORDER.index(reason) < EVIDENCE_ORDER.index(current):
            reason_of[ra] = reason

    # --- phone and email: the identifiers ------------------------------------
    for field, reason in (("phone", "phone"), ("email", "email")):
        buckets: dict[str, list[int]] = defaultdict(list)
        for position, node in enumerate(nodes):
            value = node.get(field)
            if value:
                buckets[str(value)].append(position)
        for members in buckets.values():
            for other in members[1:]:
                union(members[0], other, reason)

    # --- names: only when asked, and only on the canonical form --------------
    if fold_on_name:
        buckets = defaultdict(list)
        for position, node in enumerate(nodes):
            for form in _name_forms(node):
                buckets[form].append(position)
        for form, members in buckets.items():
            reason = "nickname" if form.startswith("~") else "exact_name"
            for other in members[1:]:
                union(members[0], other, reason)

    grouped: dict[int, list[int]] = defaultdict(list)
    for position in range(len(nodes)):
        grouped[find(position)].append(position)

    out = []
    for root, members in grouped.items():
        if len(members) < 2:
            continue
        # A named node beats a phone/email-keyed one, then the busiest, then the
        # lowest key. Keeping the human-readable key matters: the survivor's key is
        # what the Viewer shows and what every `WITH` edge ends up pointing at, and
        # `person:david sartori` reads better than `person:27845189029`.
        ranked = sorted(members, key=lambda i: (
            _is_identifier_key(nodes[i]["key"]),
            -int(nodes[i]["threads"] or 0),
            nodes[i]["key"],
        ))
        survivor = nodes[ranked[0]]
        losers = [nodes[i] for i in ranked[1:]]
        out.append((survivor, losers, reason_of.get(root, "exact_name")))
    return out


def _is_identifier_key(key: str) -> bool:
    """True when the key's tail is a phone or an address rather than a name."""
    tail = str(key).split(":", 1)[-1]
    return canon.is_phone(tail) or canon.is_email(tail)


def _name_forms(node: dict[str, Any]) -> set[str]:
    """Every canonical name this node is known by, plus its nickname form.

    Two spellings, both already canonical: the key's own tail (when the key is a
    name) and each platform handle. A phone-keyed node contributes only its handles,
    which is exactly the case a name fold exists for.
    """
    forms: set[str] = set()
    tail = str(node["key"]).split(":", 1)[-1]
    if tail and not canon.is_phone(tail) and not canon.is_email(tail):
        forms.add(tail)
    for spelling in (node.get("handles") or {}).values():
        record = canon.canonical(spelling, kind="person")
        if record.key and not record.is_placeholder and not record.is_owner:
            forms.add(record.key)
    # The nickname form is a *separate* bucket key, so `dave sartori` and
    # `david sartori` meet even when one side never went through the pipe.
    return forms | {f"~{canon.nickname_form(form)}" for form in forms}


# ------------------------------------------------------------------------- folding


def _fold(conn: Any, survivor: dict[str, Any], losers: list[dict[str, Any]]) -> None:
    """Move every edge onto the survivor, then delete the losers.

    `DETACH DELETE` is deliberately not used: it would drop the `WITH` edges that are
    the whole reason the node exists. Each edge type is re-pointed explicitly, and a
    duplicate (both nodes already attached to the same thread) is removed rather than
    merged into a self-edge.
    """
    cur = conn.cursor()
    for loser in losers:
        cur.execute(
            "MATCH (t:Thread)-[r:WITH]->(l:Correspondent {key: $loser}) "
            "MATCH (s:Correspondent {key: $survivor}) "
            "MERGE (t)-[:WITH]->(s) "
            "DELETE r",
            {"loser": loser["key"], "survivor": survivor["key"]},
        )
        # `POSSIBLY` is symmetric in meaning, so both directions are re-pointed and a
        # self-edge (the pair that just became one node) is dropped.
        cur.execute(
            "MATCH (a:Correspondent)-[r:POSSIBLY]->(l:Correspondent {key: $loser}) "
            "MATCH (s:Correspondent {key: $survivor}) "
            "FOREACH (_ IN CASE WHEN a.key = $survivor THEN [] ELSE [1] END | "
            "  MERGE (a)-[:POSSIBLY]->(s)) "
            "DELETE r",
            {"loser": loser["key"], "survivor": survivor["key"]},
        )
        cur.execute(
            "MATCH (l:Correspondent {key: $loser})-[r:POSSIBLY]->(b:Correspondent) "
            "MATCH (s:Correspondent {key: $survivor}) "
            "FOREACH (_ IN CASE WHEN b.key = $survivor THEN [] ELSE [1] END | "
            "  MERGE (s)-[:POSSIBLY]->(b)) "
            "DELETE r",
            {"loser": loser["key"], "survivor": survivor["key"]},
        )
        # The loser's per-platform facts are copied onto the survivor *before* the
        # delete, so `_reconcile` can rebuild `platforms` / `platform_label` from the
        # union rather than from the survivor alone.
        _inherit(cur, survivor["key"], loser["key"])
        cur.execute(
            "MATCH (l:Correspondent {key: $loser}) DETACH DELETE l",
            {"loser": loser["key"]},
        )
    conn.commit()


def _inherit(cur: Any, survivor_key: str, loser_key: str) -> None:
    """Copy the loser's `handle_<p>` / `seen_<p>` / address onto the survivor.

    Written as a read-then-write rather than one Cypher statement because the property
    names are dynamic (`handle_telegram`), and Relate cannot parameterise a property
    name in a `SET`. The values are flat strings, so this is a handful of assignments.
    """
    from .writer import HANDLE_PREFIX, SEEN_PREFIX

    cur.execute(
        "MATCH (l:Correspondent {key: $key}) RETURN properties(l) AS p",
        {"key": loser_key},
    )
    rows = cur.fetchall()
    if not rows:
        return
    props = rows[0]["p"]

    assignments: dict[str, Any] = {}
    for name, value in props.items():
        if name.startswith((HANDLE_PREFIX, SEEN_PREFIX)) and value:
            assignments[name] = value
    for field in ("email", "phone_e164"):
        if props.get(field):
            assignments[field] = props[field]
    if not assignments:
        return

    # `coalesce` throughout: the survivor's own value wins, because it is the one the
    # earlier ingest recorded and re-deciding it would make the store drift.
    sets = []
    params: dict[str, Any] = {"key": survivor_key}
    for position, (name, value) in enumerate(sorted(assignments.items())):
        slot = f"v{position}"
        params[slot] = value
        sets.append(f"SET s.{name} = coalesce(s.{name}, ${slot}) ")
    cur.execute(
        "MATCH (s:Correspondent {key: $key}) " + "".join(sets),
        params,
    )


# ------------------------------------------------------------------------ fuzzy


def _draw_possibly(conn: Any, nodes: list[dict[str, Any]]) -> int:
    """`POSSIBLY` between pairs that score high enough to be worth a look.

    Nothing is folded. The edge is the whole product: it says "these two might be one
    person" in a way a human can see and ignore, which a fold cannot.

    Blocked on the surname's first letter, the same cheap block `canon.candidates()`
    uses — comparing every node to every node is quadratic and this store is small
    enough that the block is the only thing keeping the run instant.
    """
    if canon.fuzzy_available() is False:  # pragma: no cover - declared dependency
        return 0

    # One representative key per node: the name a human would read. A phone-keyed
    # node uses its handle, because its key is digits and scores against nothing.
    named: list[tuple[str, str]] = []
    for node in nodes:
        forms = sorted(_name_forms(node))
        plain = [form for form in forms if not form.startswith("~")]
        if plain:
            named.append((node["key"], plain[0]))

    blocks: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, name in named:
        parts = name.split()
        block = parts[-1][:1] if len(parts) > 1 else name[:1]
        blocks[block].append((key, name))

    pairs: list[tuple[str, str]] = []
    for members in blocks.values():
        for i, (left_key, left) in enumerate(members):
            for right_key, right in members[i + 1:]:
                if canon.score(left, right) >= FUZZY_THRESHOLD:
                    pairs.append((left_key, right_key))

    if not pairs:
        return 0
    cur = conn.cursor()
    cur.execute(
        "UNWIND $pairs AS pair "
        "MATCH (a:Correspondent {key: pair[0]}) "
        "MATCH (b:Correspondent {key: pair[1]}) "
        "MERGE (a)-[:POSSIBLY]->(b)",
        {"pairs": [list(pair) for pair in pairs]},
    )
    conn.commit()
    return len(pairs)
