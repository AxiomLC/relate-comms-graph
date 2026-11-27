# SCHEMA.md

**The store's data model, and the tool layer that reads it.** Two things that belong
together: what exists in `store/graph.rl`, and what can call it.

App flow: [`TECHREADME.md`](TECHREADME.md). UI: [`UIREADME.md`](UIREADME.md).

---

## 1. Schema — what exists today

```cypher
(:Thread        {key, platform, title, is_group})
(:Message       {key, platform, chat_id, message_id, ts_utc, body,
                 has_attachments, is_self, sender_name, sender_id, raw_kind})
(:Attachment    {key, filename_scrubbed, mime, sha256, size})
(:Correspondent {key, display_name, platform, platforms, platform_label,
                 first_seen_utc, merged_by, email, phone_e164,
                 handle_<platform>, seen_<platform>})
(:Place         {key, display_name, platform, platforms, platform_label,
                 first_seen_utc, merged_by, mention_count,
                 handle_<platform>, seen_<platform>})
(:Organization  … same shape as Place)
(:Product       … same shape as Place)

(:Message)-[:IN]->(:Thread)        (:Message)-[:REPLY_TO]->(:Message)
(:Message)-[:HAS_ATTACHMENT]->(:Attachment)
(:Thread)-[:WITH]->(:Correspondent)
(:Message)-[:MENTIONS]->(:Place | :Organization | :Product)
```

**Five edge types, and no more.** `REPLY_TO` is declared and written by nothing. Both
endpoints of an entity edge are `Message`, so `Thread → Entity` is a projection, not an
edge — see below.

**The store holds facts, not summaries.** `(message)-[:MENTIONS]->(entity)` and
`(message)-[:IN]->(thread)` are what actually happened; "this thread is about Grafana" is
computed at read time by `tools._EDGE_QUERIES` as a two-hop `MATCH (t:Thread)<-[:IN]-(m)
-[:MENTIONS]->(e)`. That is the triple model another graph engine would accept — do not
let `_EDGE_QUERIES` become the schema.

**All three entity kinds share one write path.** `writer._ENTITY_WRITE_KINDS` maps kind to
store label; the fold, `mention_count`, the `MENTIONS` edge and `_reconcile` are identical.
`mention_count` is **message-based** (not thread-based).

**`Product` is gated by `extract.PRODUCT_ENABLED`.** Off returns the graph to Place+Org with
no rebuild: the index stops promoting spans and `DRAWABLE_*` drops `Product`.

**`Message.emb` is optional and never written by ingest.** A 768-float vector from
`embeddinggemma`, written only by `tools.embed_messages`. `msg_emb` is a vector index;
`msg_body` is a BM25 fulltext index. Both are created in `writer._SCHEMA` and re-ensured by
the search tools, so a store written before either existed still works.

**`Message.emb_skipped` is a stamp, not a deletion.** `screen_body()` drops a body with no
subject and no predicate (`hi`, `ok`, `thanks`) before embedding — those vectors are
near-identical and crowd every semantic result. It **fails open**: no spaCy means embed
everything.

**Relate's vector index is exact NN, not HNSW** — a brute-force scan. Fine at a few
thousand, linear at a million.

**`Correspondent` is keyed `person:<canonical>`.** Two spellings of one name on one
platform already collapsed via `canon`; dropping the platform prefix means the same
canonical name on two platforms is now **one node** with a `WITH` edge per thread.
Placeholders keep their platform prefix (`messenger:placeholder:facebook user`) so
`Facebook user` and `LinkedIn Member` never fold into one node.

| Property | Rule |
|---|---|
| `platform` | the **first** platform by date — a single string, because the filter reads it |
| `platforms` | every platform, date order. **The filter reads this list.** |
| `platform_label` | `Telegram-WhatsApp-Fcbk Mssgr`, same order |
| `first_seen_utc` | earliest message timestamp across platforms |
| `merged_by` | why a fold happened: `fuzzy` / `exact_name` / `nickname` / `phone` / `email`, or `same_name` when two platforms met under one key with **no fold at all**. `link._fold` owns it. |
| `handle_<p>` · `seen_<p>` | that platform's spelling and first sighting, stored **flat** |

**`primaryPlatform` and `dominance` are query-time, not stored.** `graph_slice` returns
them on every Correspondent: `primaryPlatform` is the platform with the most **messages**,
`dominance` its share (0.0–1.0). Deliberately *not* the same as `platform` — that is
first-by-**date**, so the filter and label never drift between ingests. They are not a
layout input: a merged node is pulled **equally** by every platform it touches.

**`graph_slice` also returns `merged`** (the `:Merged` label as a boolean). The canvas uses
it as the bag-membership test, inverted. `:Merged` is additive and filtered out of
`types_present()` — a marker, not a node type.

**Relate rejects map properties** (`InvalidPropertyType`), so `handles` is stored flat as
`handle_<platform>` and assembled by `writer.handles_from()` at the API edge.

**Relate evaluates every `UNWIND` row against the node as it stood before the statement.**
Accumulating in Cypher cannot work — the last row wins. The row statement writes only
per-platform facts; `writer._reconcile()` computes the derived properties afterwards.

**Queryable but empty — the queries exist, the rows do not:** `Person`. A person extracted
from a body would compete with the `Correspondent` already on the thread, so it is
documented but never written.

**Cross-connect is `relate_comms/link.py`, run once at the end of `ingest()`.** Union-find
over phone / email / name / **fuzzy**, re-pointing every `WITH` or `MENTIONS` edge before
the loser is deleted, then `writer._reconcile()` rebuilds `platforms` / `platform_label` /
`:Merged`. The fuzzy rung is blocked on the surname's first letter and is **last**, so a
pair that folds on phone never reports itself as fuzzy. Two places a letter apart stay two
places — entities use `exact_name` only. A named contact's phone or address comes from
`sender_id` (`writer._contact_ids()`), only when the value actually is one. Fold knobs:
`NICKNAME_ENABLED`, `FOLD_ON_NAME` in `canon.py`.

### Thread title schema — LOCKED

```
<Name>; <MM-DD-YYYY>[-][>][ #n]
```

| Case | Example |
|---|---|
| 1:1, single day | `Bryan Rodgers; 06-02-2026` |
| 1:1, spans days | `Ryan Phillip; 02-13-2025->` |
| Group | `Come to Africa; 10-25-2026->` |
| With subject | `n8n Hackathon today - log in!🪐; 08-16-2025` |
| Same person, same start date | `Ryan Phillip; 02-13-2025-> #2` |
| Name contains a date | `Invoice due 08-16-2025; 08-16-2025` |
| No messages | `Mary Olver` (second `;` omitted) |

**Parse from the outside in:** date block after the **last** `;`, name before it.
**No platform token** — the glyph is platform-coloured and the Viewer draws a pill.
**Why `;`:** measured across 500 real titles — `;` 0 occurrences, `|` 3, `-` 6. `-` collides
on day one. **Why `->` not an end date:** an end date moves on every ingest; `->` changes at
most once, ever. **`#n` by date collision only**, ordered by `chat_id`, never ingest order.
**Display only** — never parse the title for the platform key.

### Naming — settled

`Organization` not `Company`; `Product` not `Thing`; `Person` is extraction-only and never
the Owner. `canon.KINDS` is the single source; `tools.ENTITY_KINDS` derives from it. An
unknown kind raises rather than falling through to the `person` branch.

---

## 2. The tool layer — one registry, three surfaces

**Every capability is a plain function in `relate_comms/tools.py`.** Three surfaces bind the
same functions and differ only in *policy*:

```
relate_comms/tools.py   REGISTRY — 19 tools, one definition each
        |
        +-- app/routers/*.py     the UI's HTTP routes
        +-- app/routers/chat.py  _CHAT_TOOLS (6) + write toggle + platform filter
        +-- app/mcp/server.py    all 19 + two keys + repo-root path rule
```

**`Tool.schema` is derived from the signature**, in the shape Ollama and MCP both accept.
A tool's **docstring is its description** — editing it changes what a model sees.

### The 19 tools, by access

| Access | Tools |
|---|---|
| **READ** | `graph_slice` `thread_arc` `search_messages` `search_fulltext` `search_vector` `embed_status` `screen_body` `message_view` `types_present` `evidence_counts` `run_cypher` `preview_ingest` `verify_ingest` |
| **WRITE** | `embed_messages` `ingest` |
| **DESTRUCTIVE** | `flush_embeddings` `truncate_store` `prune_spool` `delete_spool` |

`require(access, write_enabled=…, confirmed=…)` is the gate. A surface passes its own
toggle; a model never sets one. `_HIDDEN_PARAMS` (`write_enabled`, `platforms`,
`extra_results`) are stripped from every schema for that reason.

### The signatures that matter

```python
# relate_comms/tools.py — the whole surface
graph_slice(node_types=None, edge_types=None, limit=2000, sort="messages")
configure_platforms(platforms)   active_platforms()
thread_arc(thread_key, *, skip=0, limit=50, query=None)
search_fulltext(query, *, limit=20, platform=None)   # BM25 bodies + names — the default
search_vector(query, *, limit=20, platform=None)     # semantic; needs an embed pass
search_messages(query, *, limit=20, platform=None, thread_key=None)  # legacy scan
embed_status()   embed_messages(*, limit=5000, write_enabled=False)
flush_embeddings(*, write_enabled=False, confirm=False)   # rebuild, reclaims disk
screen_body(body) -> (keep, reason)   # subject+predicate test, fails open
message_view(message_key)
types_present()   evidence_counts()   run_cypher(query, params, *, limit=500, write_enabled=False)
ingest(...)   preview_ingest(which)   verify_ingest(which)
truncate_store(...)   prune_spool(older_than_days, ...)   delete_spool(...)

# relate_comms/ingest.py
parse_batches(...)   ingest(*, which="real", delta=True, extra_results=(), ...) -> Report
preview(...) -> dict   stage(paths_in) -> list[Path]   detect_platform(path)

# relate_comms/extract.py — proposes spans, merges nothing
extract(rows) -> list[Mention]        places(body) / organizations(body)
fragments(body) -> list[Fragment]     # `<br>` split; offsets index the ORIGINAL body
_arbitrate(text, label, body) -> (kind, candidates)

# relate_comms/products.py — the four-rule ladder, no weights
products.decide(text, body) -> (bool, reason)
products.lookup(text) -> ProductEntry | None     products.has_context(body) -> bool

# relate_comms/writer.py
write(conn, result, *, owner=None) -> dict[str, int]   # UNWIND, BATCH_SIZE = 500
write_correspondents(...)   write_entities(conn, mentions, *, message_meta, kinds)
_reconcile(cur, keys)       thread_display_title(chat, owner=None)   verify_present(...)

# relate_comms/canon.py — the flattening pipe
canonical(raw, *, kind="person", owner=None) -> Canonical
candidates(...)   nickname_form(raw)   score(a, b)   fuzzy_available()
KINDS = ("person", "organization", "place", "product")

# relate_comms/link.py — cross-connect, once per ingest
link(conn, *, fold_on_name=None) -> dict   # {folded, merged_by, groups, entities}
```

### Search — three modes, three promises

| Mode | What it is |
|---|---|
| `fulltext` | **BM25 over bodies, the default.** Ranked, indexed, milliseconds. **Word** matching, not substring: `"graf"` does not match `"grafana"`. |
| `vector` | Semantic. Needs an embed pass; raises a message the UI turns into the *run embeds* pill. |
| `cypher` | Whatever the user typed, refused if it would write. |

**Both fulltext and vector call `_name_matches()`**, which substring-matches
`Correspondent.display_name` and returns **thread** rows. Without it a person's name was
unfindable — `Alicia Moreno` had 8 messages and zero bodies containing "moreno".

**`run_cypher`'s guard is a pattern match, not a parser.** It strips string literals,
uppercases, and looks for write keywords word-bounded. A statement it reads as a write is
refused unless `write_enabled` — the surface's toggle is the real protection, the guard is
a speed bump.

### The chat surface

`_CHAT_TOOLS` is **6** tools (`evidence_counts`, `search_vector`, `search_fulltext`,
`thread_arc`, `message_view`, `run_cypher`) because a local 8B model given 19 overlapping
options picks the wrong one. `ingest` joins only when the UI write toggle is on.

**Open defect:** one tool round only, and an empty reply is silent. `_run_turn` pops `tools`
before the second pass, so `search → thread_arc` can never happen.

**`think: false` is a no-op on `lfm2.5:8b`** — Liquid AI's table says the model cannot switch
thinking off. What matters is `num_predict` (unset lets reasoning eat the budget and return
empty) and `keep_alive: -1`. `qwen3.5:4b` is already pulled, ~2× faster, better at tools,
and its `think: false` genuinely works — one line in `models.py`.
