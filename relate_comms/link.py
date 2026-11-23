"""Cross-connect — fold the nodes whose keys differ.

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

ONE OUTCOME: THE FOLD
---------------------
An earlier version also drew `(:Correspondent)-[:POSSIBLY]->(:Correspondent)` for fuzzy
pairs on the theory that a visible guess beats a silent fold. It was removed 2026-11-23.
The six edges it ever produced were all typo pairs (`vikrm ross`/`vikram ross`) that a
user wants as ONE node, the edge carried no score the UI could rank, and a near-miss of
two genuinely different people is not something this store can tell apart from a
typo. So: a pair folds, or it does not match. There is no third state.

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
    fuzzy       same name within `FUZZY_THRESHOLD`, decided by the same `canon.score`
                a human review would use. Last in the chain, so a pair that folds on
                `phone` never reports itself as a fuzzy fold.

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
#
# `fuzzy` is last by construction: it is the weakest claim, and it is only reached for a
# pair nothing stronger explained. Keeping it in the same chain is what makes the fold
# deterministic — there is no second pass that could fold a pair the first one skipped.
EVIDENCE_ORDER: tuple[str, ...] = ("phone", "email", "exact_name", "nickname", "fuzzy")

# The entity labels `link()` folds after the Correspondent pass. `Place` is the only
# member in v1; `canon.KINDS`-derived so a second kind joins by existing in `canon`.
# Correspondent is excluded on purpose — it has its own loader and its own evidence.
ENTITY_LABELS: tuple[str, ...] = tuple(
    kind.capitalize() for kind in canon.KINDS if kind != "person"
)

# A Place has one kind of evidence and only one: its canonical name. There is no phone
# and no address to fall back on, so `:Merged` on a Place means "same canonical name,
# seen on two platforms" — a weaker claim than the Correspondent case, and the UI must
# not imply otherwise. That is accepted rather than gated: name matching is what we
# have, so it is done as well as it can be.
ENTITY_EVIDENCE_ORDER: tuple[str, ...] = ("exact_name",)

# Below this two names are not the same person. The knob is `canon`'s, so the fold and
# any report that quotes it cannot disagree.
#
# **Why a threshold and not an exact match.** A typo'd surname (`esposio`/`esposito`) is
# one human, and the old design drew a `POSSIBLY` line instead of folding on the theory
# that a wrong fold is unrecoverable. In practice the lines were never acted on and the
# graph showed one person twice. A wrong fold is recoverable the same way anything else
# in this store is: delete the derived node and re-ingest.
FUZZY_THRESHOLD = canon.FUZZY_REPORT


def link(conn: Any, *, fold_on_name: bool | None = None) -> dict[str, Any]:
    """Fold matching nodes. Idempotent.

    Returns a report the ingest panel can show:

        folded      how many nodes were deleted into another
        merged_by   {phone: n, email: n, exact_name: n, nickname: n, fuzzy: n}
        groups      the fold groups, as `[[survivor, loser, …], …]`, for the log

    `entities` carries the Place pass, in the same shape but counting `place`:

        entities    {Place: {folded, merged_by, groups}}

    Running it twice changes nothing: the second run finds one node per group.
    """
    if fold_on_name is None:
        fold_on_name = canon.FOLD_ON_NAME

    report = _link_correspondents(conn, fold_on_name=fold_on_name)
    report["entities"] = {
        label: _link_entity(conn, label) for label in ENTITY_LABELS
    }
    return report


def _link_correspondents(conn: Any, *, fold_on_name: bool) -> dict[str, Any]:
    """The Correspondent pass. Split out so `link()` reads as two calls, not two halves.
    """
    nodes = _load(conn)
    if len(nodes) < 2:
        return {"folded": 0, "merged_by": {}, "groups": []}

    # The per-platform spellings are the evidence a fold reads: a name fold needs them
    # to find a phone-keyed node's name, and the fuzzy pass scores the same forms.
    handles = _handles(conn, [node["key"] for node in nodes])
    for node in nodes:
        node["handles"] = handles.get(node["key"], {})

    groups = _fold_groups(nodes, fold_on_name=fold_on_name)
    folded = 0
    by_reason: dict[str, int] = defaultdict(int)
    report_groups: list[list[str]] = []

    for survivor, losers, reason in groups:
        _fold(conn, survivor, losers, reason=reason)
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

    # `_fold_groups` already includes the fuzzy class, so there is no second pass below:
    # a pair that is not in `groups` is not the same person, and nothing is drawn.
    return {
        "folded": folded,
        "merged_by": dict(by_reason),
        "groups": report_groups,
    }


# ------------------------------------------------------------------------ reading


def _load(conn: Any, label: str = "Correspondent") -> list[dict[str, Any]]:
    """Every Correspondent, with the facts a fold decision needs.

    `label` generalises it to an entity kind (`Place`). The two differ in exactly one
    way that matters: a Correspondent's weight is its `WITH` threads, a Place's is the
    threads that `MENTIONS` it — which needs two hops, because the edge hangs off the
    `Message` (see `writer._write_one_kind`). Everything the fold itself reads — `key`,
    per-platform `handle_<p>` / `seen_<p>` — is identical, which is why the fold can be
    shared.

    Placeholders are excluded: `messenger:placeholder:facebook user` and
    `linkedin:placeholder:linkedin member` are two different accounts that happen to
    both be anonymous, and folding them would claim one platform's spam is the
    other's. `canon` already keeps them platform-scoped; this keeps them unfolded.
    """
    if label == "Correspondent":
        cypher = (
            "MATCH (c:Correspondent) "
            "OPTIONAL MATCH (t:Thread)-[:WITH]->(c) "
            "RETURN c.key AS key, c.platform AS platform, "
            "       coalesce(c.platforms, [c.platform]) AS platforms, "
            "       c.display_name AS display_name, c.phone_e164 AS phone, "
            "       c.email AS email, count(DISTINCT t) AS threads "
        )
    else:
        # Two hops, matching the write: `MENTIONS` hangs off the Message, so a `Thread`
        # count has to go through `IN`. Counting distinct threads is what the survivor
        # ranking wants — a person's weight is the conversations they appear in, not
        # the raw message count.
        cypher = (
            f"MATCH (e:{label}) "
            "OPTIONAL MATCH (t:Thread)<-[:IN]-(m:Message)-[:MENTIONS]->(e) "
            "RETURN e.key AS key, e.platform AS platform, "
            "       coalesce(e.platforms, [e.platform]) AS platforms, "
            "       e.display_name AS display_name, null AS phone, "
            "       null AS email, count(DISTINCT t) AS threads "
        )

    cur = conn.cursor()
    cur.execute(cypher)
    nodes = []
    for row in cur.fetchall():
        node = dict(row)
        if str(node["key"]).split(":", 1)[-1].startswith("placeholder:"):
            continue
        nodes.append(node)
    return nodes


def _handles(conn: Any, keys: Iterable[str], *, label: str = "Correspondent") -> dict[str, dict[str, str]]:
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
        f"MATCH (n:{label}) WHERE n.key IN $keys RETURN properties(n) AS p",
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
    evidence: tuple[str, ...] = EVIDENCE_ORDER,
) -> list[tuple[dict[str, Any], list[dict[str, Any]], str]]:
    """Group nodes that are provably one entity. Returns (survivor, losers, reason).

    Union-find over the evidence, so a chain folds as one group: a phone-only node
    joined to a named node by phone, and that named node joined to a third by email,
    is one person with three keys. Folding pairwise would leave two of the three
    apart depending on iteration order.

    `evidence` is the ladder this pass may use, strongest first. A `Place` passes
    `ENTITY_EVIDENCE_ORDER`, which holds only `exact_name` — it has no identifier to
    read, and asking for one would fold on a property the node never has.
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
        #
        # **Both roots' reasons are considered.** `rb` may already carry a reason from
        # an earlier union, and dropping it silently downgraded a whole group — the
        # fuzzy rung exposed it: two pairs unioned in sequence kept only the first
        # root's reason and the group reported `exact_name` for a fuzzy fold.
        previous = reason_of.pop(rb, None)
        current = reason_of.get(ra)
        candidates = [r for r in (current, previous, reason) if r is not None]
        best = min(candidates, key=evidence.index)
        if current != best:
            reason_of[ra] = best

    # --- phone and email: the identifiers ------------------------------------
    for field, reason in (("phone", "phone"), ("email", "email")):
        if reason not in evidence:
            continue
        buckets: dict[str, list[int]] = defaultdict(list)
        for position, node in enumerate(nodes):
            value = node.get(field)
            if value:
                buckets[str(value)].append(position)
        for members in buckets.values():
            for other in members[1:]:
                union(members[0], other, reason)

    # --- names: only when asked, and only on the canonical form --------------
    if fold_on_name and "exact_name" in evidence:
        buckets = defaultdict(list)
        for position, node in enumerate(nodes):
            for form in _name_forms(node):
                buckets[form].append(position)
        for form, members in buckets.items():
            reason = "nickname" if form.startswith("~") else "exact_name"
            for other in members[1:]:
                union(members[0], other, reason)

    # --- fuzzy: the last rung, and only for a pair nothing stronger explained --
    #
    # This replaced the `POSSIBLY` edge (removed 2026-11-23). It is deliberately the
    # weakest rung: `union()` keeps the strongest reason for a group, so a pair that
    # already folded on phone or an exact name never reports itself as `fuzzy`.
    #
    # **Blocked on the surname's first letter, the same cheap block the old edge used.**
    # Comparing every node to every node is quadratic; on a 123-node store that matters
    # and on a real one it would not finish inside an ingest. A surname is a stable
    # anchor — a typo in the first letter of a surname is rare enough that missing it
    # costs a fold, not a wrong one.
    if fold_on_name and "fuzzy" in evidence and canon.fuzzy_available():
        named = [
            (position, _readable_name(node)) for position, node in enumerate(nodes)
        ]
        blocks: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for position, name in named:
            if not name:
                continue
            parts = name.split()
            blocks[parts[-1][:1] if len(parts) > 1 else name[:1]].append((position, name))
        for members in blocks.values():
            for index, (left_position, left) in enumerate(members):
                for right_position, right in members[index + 1:]:
                    if canon.score(left, right) >= FUZZY_THRESHOLD:
                        union(left_position, right_position, "fuzzy")

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


def _readable_name(node: dict[str, Any]) -> str:
    """The name a human would read, for scoring two nodes against each other.

    A phone-keyed node uses its handle, because its key is digits and scores against
    nothing. Returns `""` when the node has no name at all — a node that is only ever a
    number must not block on `""`, or every unnamed node would land in one bucket and
    score against every other.
    """
    forms = sorted(_name_forms(node))
    plain = [form for form in forms if not form.startswith("~")]
    return plain[0] if plain else ""


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


def _fold(
    conn: Any, survivor: dict[str, Any], losers: list[dict[str, Any]],
    *, label: str = "Correspondent", edge: str = "WITH", reason: str = "",
) -> None:
    """Move every edge onto the survivor, then delete the losers.

    `DETACH DELETE` is deliberately not used: it would drop the edges that are the
    whole reason the node exists — `WITH` for a Correspondent, `MENTIONS` for an entity.
    Each edge type is re-pointed explicitly, and a duplicate is removed rather than
    merged into a self-edge.

    `label` / `edge` generalise it to an entity kind. The **source** differs by kind:
    a Correspondent hangs off a `Thread` via `WITH`, an entity hangs off a `Message` via
    `MENTIONS` (since 2026-11-23). Re-pointing the wrong source silently deletes every
    edge the node had, because `DETACH DELETE` takes whatever is left.

    `reason` is the evidence class that made this fold (`fuzzy`, `exact_name`, `phone`…)
    and is **stamped onto the survivor here**. This is the only place that knows why a
    merge happened — the writer sees one batch and cannot, and `coalesce` let a stale
    write-time value win, which is how every fuzzy fold on the live store came to report
    `exact_name`.
    """
    source = "m:Message" if edge == "MENTIONS" else "t:Thread"
    cur = conn.cursor()
    for loser in losers:
        cur.execute(
            f"MATCH ({source})-[r:{edge}]->(l:{label} {{key: $loser}}) "
            f"MATCH (s:{label} {{key: $survivor}}) "
            f"MERGE ({source.split(':')[0]})-[:{edge}]->(s) "
            "DELETE r",
            {"loser": loser["key"], "survivor": survivor["key"]},
        )
        # The loser's per-platform facts are copied onto the survivor *before* the
        # delete, so `_reconcile` can rebuild `platforms` / `platform_label` from the
        # union rather than from the survivor alone.
        _inherit(cur, survivor["key"], loser["key"], label=label)
        cur.execute(
            f"MATCH (l:{label} {{key: $loser}}) DETACH DELETE l",
            {"loser": loser["key"]},
        )
    if reason:
        # After the deletes, so a survivor that was itself a loser elsewhere cannot have
        # the stamp overwritten by a later group in the same pass.
        cur.execute(
            f"MATCH (s:{label} {{key: $key}}) SET s.merged_by = $reason",
            {"key": survivor["key"], "reason": reason},
        )
    conn.commit()


def _inherit(cur: Any, survivor_key: str, loser_key: str,
             *, label: str = "Correspondent") -> None:
    """Copy the loser's `handle_<p>` / `seen_<p>` / address onto the survivor.

    Written as a read-then-write rather than one Cypher statement because the property
    names are dynamic (`handle_telegram`), and Relate cannot parameterise a property
    name in a `SET`. The values are flat strings, so this is a handful of assignments.

    `mention_count` is a Place's own flat fact and joins the copy: the survivor of a
    Place fold has seen every message either loser saw, so the counts are summed. It is
    the one place the two labels differ, and the difference is deliberate rather than
    an oversight — a Correspondent has no equivalent scalar.
    """
    from .writer import HANDLE_PREFIX, SEEN_PREFIX

    cur.execute(
        f"MATCH (l:{label} {{key: $key}}) RETURN properties(l) AS p",
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

    # `mention_count` is additive, not coalesced: both nodes counted distinct messages,
    # and the survivor has now seen the union of them.
    if props.get("mention_count"):
        params["mentions"] = int(props["mention_count"])
        sets.append(
            "SET s.mention_count = coalesce(s.mention_count, 0) + $mentions "
        )
    cur.execute(
        f"MATCH (s:{label} {{key: $key}}) " + "".join(sets),
        params,
    )


# ------------------------------------------------------------------------ fuzzy


# ----------------------------------------------------------------- entities


def _link_entity(conn: Any, label: str) -> dict[str, Any]:
    """Fold one entity kind across platforms. Correspondent rules, one weaker ladder.

    A Place has no phone and no address, so `ENTITY_EVIDENCE_ORDER` holds only
    `exact_name`. That means a fold here is "the same canonical name, seen on more than
    one platform" — the canonical name having already absorbed case, accents, a postal
    code and a trailing region code via `canon`. It is the best evidence a place can
    offer, and it is weaker than the Correspondent case; `:Merged` carries the same
    label, so the UI must say "same spelling" rather than "same place".

    Places fold on their canonical name only; **no fuzzy rung**.

    `ENTITY_EVIDENCE_ORDER` deliberately omits `fuzzy` while a Correspondent uses it.
    A name is enough evidence to say two Correspondent nodes are one human — a typo'd
    surname has no other reading. A Place has no second signal to weigh: `Fargo` and
    `Largo` are two towns, and folding them on a score would be the graph inventing a
    place. The same rule holds for Organization and Product.
    """
    nodes = _load(conn, label)
    if len(nodes) < 2:
        return {"folded": 0, "merged_by": {}, "groups": []}

    handles = _handles(conn, [node["key"] for node in nodes], label=label)
    for node in nodes:
        node["handles"] = handles.get(node["key"], {})

    groups = _fold_groups(
        nodes, fold_on_name=True, evidence=ENTITY_EVIDENCE_ORDER,
    )
    folded = 0
    by_reason: dict[str, int] = defaultdict(int)
    report_groups: list[list[str]] = []

    for survivor, losers, reason in groups:
        _fold(conn, survivor, losers, label=label, edge="MENTIONS", reason=reason)
        folded += len(losers)
        by_reason[reason] += len(losers)
        report_groups.append([survivor["key"], *[n["key"] for n in losers]])

    if folded:
        # Same reason as the Correspondent pass: the union of two nodes' platforms can
        # cross the `:Merged` threshold, so the derived properties must be rebuilt from
        # the facts `_inherit` just merged.
        from .writer import _reconcile

        _reconcile(conn.cursor(), [group[0] for group in report_groups], label=label)
        conn.commit()

    return {"folded": folded, "merged_by": dict(by_reason),
            "groups": report_groups, "possibly": 0}
