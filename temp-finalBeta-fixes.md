# temp-finalBeta-fixes.md

**The build plan. This is the source of truth for the next round.**

`HANDOVER.md` points here. `TECHREADME.md` gets updated after the code lands.

Everything below marked **VERIFIED** was checked against the code and a live ingest on
2026-11-18, not inferred. Everything marked **UNVERIFIED** is a plan, not a fact.

---

## STATUS — 2026-11-19 (read this first)

**`pytest tests -q` → 380 passed, 2 skipped.**

| Edit | State |
|---|---|
| **1. Node structure** | **DONE** |
| **2. `tools.py` API shape** | **DONE** |
| **3. UI node types** | **NOT STARTED** |
| **4. `link.py` cross-connect** | **NOT STARTED** — this is the next thing to build |

**Where to resume:** edit 4 (`relate_comms/link.py`). Edits 1–2 are stable and tested;
edit 3 is UI-only and independent of 4, so either order works, but 4 is the one that
produces the merged nodes the samples were built to exercise.

### What edit 1 actually did — and where it deviated from this plan

Three things below were **wrong or incomplete** in the plan as written. They are now
resolved in code; do not re-derive them.

1. **Relate rejects map properties.** `SET c.handles = {…}` raises
   `DataError: InvalidPropertyType`. The plan's `handles: map` is stored **flat** as
   `handle_<platform>` / `seen_<platform>`, and `writer.handles_from()` assembles the dict
   at the API edge. Do not try to store a map.

2. **Relate evaluates every `UNWIND` row against the node as it stood *before* the
   statement.** Two rows for one key both read the old value, so the last row wins.
   Accumulating in Cypher is therefore impossible. The row statement writes only
   per-platform facts; `writer._reconcile()` computes `platform`, `platforms`,
   `display_name`, `first_seen_utc`, `platform_label` and `:Merged` afterwards.

3. **`first_seen_utc` is built from `result.messages`,** as the plan said, but the
   participant list is the only source for a thread with no messages — those nodes get
   `first_seen_utc = null` and sort last. 11 of 93 on the sample store.

**Measured on the seven sample variants:** 93 correspondents, **34 merged across
platforms**, 2 placeholders. Re-ingest is byte-identical.

### What edit 2 actually did — plus one addition not in this plan

- `_platform_clause()` → `ANY(p IN $platforms WHERE p IN coalesce(alias.platforms, [alias.platform]))`.
  One clause serves every node type.
- `_NODE_ALIAS` replaces the `if` chain.
- `Person` / `Place` / `Organization` / `Product`: node query, count query, three sort
  entries, `MENTIONS_<KIND>` edge query. **All return 0** until extraction lands.
- `POSSIBLY` edge query added.
- **Not in the plan: `primaryPlatform` + `dominance`.** `graph_slice` now returns both per
  Correspondent, derived from a two-stage per-platform message count. `primaryPlatform` is
  **most messages**; `platform` stays **first by date**. On the sample store **17 of 34
  merged nodes disagree**, so they are genuinely two fields. `dominance` is the leash
  length the canvas will use — see `CytoGravityRecommend.md`.

### Naming — settled

`canon.KINDS = ("person", "organization", "place", "product")` is the single source;
`tools.ENTITY_KINDS` is derived from it. `kind="thing"` is gone. `canon.canonical()` now
**raises** on an unknown kind — the pipeline's last branch is `person`, so a typo would
silently strip credentials off a product name. `Company` appears nowhere.

---

## Where the store actually stands

Live store rebuilt 2026-11-18 from the six sample variants that mirror `sample_writer/in/`.
**1,853 messages · 133 threads · 131 correspondents · 140 `WITH` edges.** Zero failed, zero
unverified, zero unrecognised.

| platform | threads | groups | correspondents |
|---|---|---|---|
| messenger | 29 | 2 | 31 |
| telegram | 26 | 2 | 27 |
| sms | 27 | 0 | 27 |
| linkedin | 23 | 0 | 23 |
| whatsapp | 22 | 2 | 23 |
| outlook | 6 | 0 | **0** |

**Outlook's zero is correct, not a bug.** The `.pst` fixture is a single-account Aspose demo
mailbox — all 6 messages are `is_self` from `saqib.razzaq@xp.local`, so the owner guard
excluded the only sender and there is no counterparty to attach. Do not "fix" it.

**One variant per platform, always.** `out/` holds 4 WhatsApp dialects, 2 Messenger, 2
LinkedIn, 3 SMS, 2 Telegram. They are alternate *packaging* of the same conversations.
Ingesting more than one per platform stores every message twice. That is a test error, not
product behaviour — and it is exactly the mistake that made a duplicate-thread bug look
like a dialect bug earlier today.

| `in/` (real) | ingest this `out/` variant |
|---|---|
| `Basic_LinkedInDataExport_*.zip` | `linkedin/linkedin_zip` |
| `facebook-*.zip` | `messenger/messenger_zip` |
| `Outlook.pst` | `outlook/outlook_copy` |
| `sms-*.xml` | `sms/sms_xml` |
| `Telegram Desktop/` | `telegram/telegram_bulk` |
| `whatsapp-chats-*.zip` | `whatsapp/whatsapp_html` |

---

## Fixed this round — do not re-litigate

| Fix | Evidence |
|---|---|
| `.eml` mailboxes are discoverable | Was unreachable: no suffix, no detector, no parser entry. Email could only be reached from a test. Now 151 messages from `email_eml/`. |
| WhatsApp thread dedupe | `WhatsApp Chat with X.txt` vs `X.zip` hashed to two `wa_` ids. 48 threads → 24. Prefix stripped in `read_export`. |
| WhatsApp HTML 1:1 correspondents | Title-derived sender was never added to `participants`, so 16 of 20 threads had no `WITH` edge. Correspondents 5 → 23. |
| Viewer in-house note removed | The "not a Person — merging is a later step" paragraph is gone, with its dead `.arc` CSS. |

---

## The build order

Four edits. **The order matters** — each one depends on the last.

### 1. Node structure — `Correspondent.key` becomes `person:<canonical>`

> **DONE 2026-11-19.** Kept below as the record of what the edit had to handle. Three
> corrections were needed beyond this text — see *STATUS* at the top.

**VERIFIED: this is the foundation, and the doc's original version of it was wrong in
three ways.** Read all of this before writing code.

**What the key change alone does and does not do.** Today `write_correspondents` inlines
`f"{chat.platform}:{record.key}"` twice. Dropping the platform prefix makes two spellings of
one name on *one* platform collapse — that already happens via `canon`. It does **not**
merge across platforms, because a WhatsApp phone-only contact (`person:+27845189029`) and a
Telegram named contact (`person:david sartori`) never share a key. **Cross-platform merging
is edit 4, not edit 1.** Do not expect it here.

**`writer.correspondent_key()` is dead code.** Nothing calls it. The real edit is in
`write_correspondents` plus `_CORRESPONDENT_CYPHER`.

**The Cypher currently overwrites, it does not accumulate.** `_CORRESPONDENT_CYPHER` does
`SET c.platform = row.platform` — last batch wins. Every new property below needs an
explicit accumulate-or-keep rule, or a merged node will silently lose platforms.

**`first_seen_utc` has no data source today.** `write_correspondents` only sees
`chat.participant_names` — it has no access to message timestamps. It must build
`(platform, canonical) → min(ts)` from `result.messages` first. This is the real work of
edit 1 and it is not a one-liner.

**Placeholders must stay platform-scoped.** `canon` returns `placeholder:facebook user`.
Under a bare `person:<canonical>` key that would merge Messenger's `Facebook user` with
LinkedIn's `LinkedIn Member` into one node representing two different platforms' placeholder
accounts. Keep the platform prefix for placeholders explicitly.

**Properties on a merged node:**

| Property | Type | Rule |
|---|---|---|
| `key` | `person:<canonical>` | identity |
| `display_name` | string | what the UI shows |
| `platform` | string | **first** platform, date order — keeps the filter working |
| `platforms` | list | every platform, accumulated (not overwritten) |
| `platform_label` | string | `Telegram-Whatsapp-Fcbk Mssgr`, date order |
| `handles` | map | `{telegram: "Axiom LoftCoin", messenger: "David Sartori"}` |
| `first_seen_utc` | string | earliest across all platforms |
| `merged_by` | string | `phone` / `email` / `exact_name` / `nickname` |

**Why `platform` stays a single string:** `_platform_clause()` does `c.platform IN $platforms`.
A merged node with `platform = "Telegram-Whatsapp-Fcbk Mssgr"` fails that test and vanishes
when filtering by Telegram. So `platform` is the first one, `platforms` is the list, and the
filter reads the list.

**`:Merged` label** — additive, so `MATCH (c:Correspondent)` still finds it:

```
(:Correspondent:Merged {key: "person:owen ross", ...})
```

Generalises to `:Organization:Merged`, `:Place:Merged`, `:Product:Merged`.

**`types_present()` will report `Merged` as a node type.** It enumerates `db.labels()` and
reports any label with a count, so `Merged` appears in the Toggles modal as a switchable
node type. Filter it out there.

---

### 2. `tools.py` — the API shape

> **DONE 2026-11-19.** Plus `primaryPlatform` / `dominance`, which this plan did not
> anticipate — see *STATUS*.

Must land before the UI: the UI cannot render a `platforms` array the API does not return.

**`_platform_clause()` reads the list:**

```cypher
ANY(p IN $platforms WHERE p IN c.platforms)
```

**This is more than one line.** The original plan said otherwise. In practice:

- `_node_where()` picks its alias with an `if node_type == "Correspondent"` chain — needs a
  kind-aware mapping, not a chain.
- `_SORTS` is a per-type dict and will `KeyError` for any new type.
- `_COUNT_QUERIES` and `_NODE_QUERIES` have no entries for Person / Place / Organization /
  Product. **The queries are not written.** They must be.
- `graph_slice` must return `platforms` and `platform_label`.

**`POSSIBLY` edges need an `_EDGE_QUERIES` entry** or they are invisible to `graph_slice` —
they will not draw, and they will not even appear in `edges_skipped`.

**`App.jsx:249` does parse a platform out of a key** (`String(entry.id).split(":")[0]`). It
runs on a Thread key, so it is safe today — but the original claim that "nothing parses a
platform out of a key" is false. Do not rely on it.

---

### 3. Node types in the UI

> **NOT STARTED.** One item is already done: the canvas platform filter now reads
> `platforms` (landed with edit 1, because a merged node vanished otherwise). The rest of
> this section stands.

**`GraphCanvas.jsx` becomes `NODE_TYPES`-driven.** Today it tests strings:

```js
if (hideSilent && node.type === "Thread" && node.is_silent) return false;
const isThread = node.type === "Thread";
```

Replace with `NODE_TYPES[type].drawable`, `.shape`, `.sizeLadder`. Adding a kind becomes a
config entry.

**The canvas filter reads `platform`, not `platforms`.** `GraphCanvas` builds
`hiddenPlatforms` from `node.platform`. A merged node with `platform: "telegram"` and
`platforms: [telegram, whatsapp]` disappears when WhatsApp is unticked, even though the
server kept it. **This is a third place the list must be read**, and the original plan named
only two.

**`icon <kind>` class.** Today the selector is `node.icon.person[platform = "..."]`, keyed on
platform only — an `Organization` on Telegram would get the *person* glyph. The class becomes
`icon person` / `icon org` / `icon place` / `icon product`, keyed by kind.

**Size ladders** (already in `theme.js`):

```
Thread        A / C / E
Correspondent B / D / F
Person, Place, Organization, Product   D / E / F
```

---

### 4. Cross-connect wiring — the actual merge

> **NOT STARTED — resume here.** Edits 1–2 are stable. `POSSIBLY` already has an
> `_EDGE_QUERIES` entry, so the edge will draw the moment `link.py` writes one.

Last, because it needs 1–3 stable. **This is the edit that produces merged nodes.**

**New `relate_comms/link.py`**, called at the **end of ingest**, after every batch is
written. Per-batch would only ever see one platform.

**What it must actually do.** With edit 1, same-canonical-name folding already happens at
write time via the key. What `link.py` must handle is nodes whose **keys differ**:

- a WhatsApp phone-only contact (`person:+27845189029`)
- a Telegram named contact (`person:david sartori`)

Those never share a key. Merging them is a **MERGE + DELETE + edge re-point**, not a
property set. Get the edge re-point right or the graph loses `WITH` edges.

**Exact match → fold into one node:**

| Evidence | `merged_by` |
|---|---|
| same phone digits | `phone` |
| same lowercased email | `email` |
| same canonical name | `exact_name` |
| same canonical name after nickname resolution | `nickname` |

**Fuzzy match → `POSSIBLY` edge, both nodes stay.**

```
(:Correspondent)-[:POSSIBLY]->(:Correspondent)
```

Spec: `archive_docs/direction.md` §5 — *"two edge types, never one"*. A fold is
unrecoverable without a re-ingest; an edge is a line you can look at and ignore.

**The samples are built for this.** `sample_writer` deliberately emits:
- `FUZZ_SENDERS_CROSS` — one person, two platform spellings (`Chris Fowley` / `Christopher Fowley`)
- `FUZZ_SENDERS_INTRA` — two spellings inside one export
- 8–12% of the cast on more than one platform

So a correct `link.py` has real work to do on this store, and a broken one is visible
immediately. That is the test.

---

## Knobs — the audit story

> **NOT BUILT.** `FUZZY_REPORT = 0.85` exists in `canon.py`. `NICKNAME_ENABLED` and
> `FOLD_ON_NAME` do not — they belong with `link.py` (edit 4), which is what would honour
> them. Do not add them before there is a fold to switch off.

Three switches in `canon.py`, so a bad class of merge can be turned off without a code change:

```python
NICKNAME_ENABLED = True   # off = `Dave` and `David` stay separate
FOLD_ON_NAME     = True   # off = only phone/email folds
FUZZY_REPORT     = 0.85   # raise to report fewer candidates
```

Plus `merged_by` on every node, so the audit is a **query**, not a log:

```cypher
MATCH (c:Correspondent:Merged) RETURN c.merged_by, count(*)
```

---

## Why this holds up for Place / Org / Person / Product

| Mechanism | Generalises? |
|---|---|
| `canon.canonical(kind=...)` | Yes — already takes `kind` |
| `:Merged` label | Yes — `:Organization:Merged` etc. |
| `platforms` / `platform_label` / `first_seen_utc` | Yes — same shape |
| `_platform_clause()` | Yes — already takes an alias |
| `NODE_TYPES`-driven canvas | Yes — that is the point of edit 3 |

**One semantic difference to document:** a Correspondent is *inherently* platform-scoped —
"this person, as Telegram spells them". A Place is not: `New York` is `New York` whichever
platform mentioned it. For future kinds, `platforms` means "which platforms mentioned it",
and `:Merged` means "one place, several spellings". Same schema, different meaning.

---

## Naming decisions — DONE

| Use | Not |
|---|---|
| `Organization` | `Company` |
| `Product` | `Thing` |
| `Person` (extraction only, never the Owner) | — |

Settled 2026-11-19. `canon.KINDS` is the single source; `tools.ENTITY_KINDS` derives from
it. `kind="thing"` renamed to `kind="product"`; an unknown kind now raises instead of
falling through to the `person` branch. `Company` appears nowhere in the codebase.

---

## Thread title schema — LOCKED

```
<Platform>; <Name>; <MM-DD-YYYY>[-][>][ #n]
```

| Case | Example |
|---|---|
| 1:1, single day | `SMS; Bryan Rodgers; 06-02-2026` |
| 1:1, spans days | `Facebook; Ryan Phillip; 02-13-2025->` |
| Group | `Whatsapp; Come to Africa; 10-25-2026->` |
| With subject | `LinkedIn; n8n Hackathon today - log in!🪐; 08-16-2025` |
| Same person, same start date | `Facebook; Ryan Phillip; 02-13-2025-> #2` |
| Name contains a date | `LinkedIn; Invoice due 08-16-2025; 08-16-2025` |
| No messages | `Telegram; Mary Olver` (second `;` omitted) |

**Parse from the outside in:** platform before the **first** `;`, date block after the
**last** `;`, name between them.

**Why `;`:** measured across 500 real titles — `;` 0 occurrences, `[`/`]` 0, `->` 0, `#` 0,
`|` 3, `-` 6. `-` collides on day one; `;` does not.

**Why `->` not an end date:** an end date changes on every ingest because `max(ts)` moves.
`->` changes at most once, ever.

**`#n` by date collision only**, ordered by `chat_id`, never ingest order.

**Display only.** Never parse the title for the platform key; query the `platform` property.

**No PII scrubbing.** Personal sandboxed app.

---

## Still open

| Item | Note |
|---|---|
| **Edit 3 — UI node types** | `GraphCanvas` still tests `node.type === "Thread"` strings. The platform filter is fixed; the rest is not. |
| **Edit 4 — `link.py`** | The next build. Folds differing keys (phone-only vs named); fuzzy → `POSSIBLY`. |
| Messenger group titles | 117 of 134 real threads are groups; the adapter names each after `others[0]` (a participant) rather than the `<h1>`. The generated samples happen to be right for `Neighbourhood Watch` and wrong for the rest, so **the samples will not catch this**. |
| Body-entity extraction | `Person`, `Place`, `Organization`, `Product`. Blocked on a candidate generator. **The queries already exist and return 0** — only the writer is missing. |
| `MENTIONS` edges | Needs the extracted nodes to exist. The `MENTIONS_<KIND>` query entries are already written. |
| Canvas gravity / compound bags | `CytoGravityRecommend.md`. Needs `parent` on elements before any fcose param does anything. `dominance` is already on the API for the leash. |
| LinkedIn "Sponsored" HTML | 74 messages with raw `spinmail-quill-editor` markup. |
| Email: one mailbox per run | Two `--email` values currently merge into one platform. |
| Re-export mints a new thread | LinkedIn/WhatsApp/Email derive `chat_id`; a changed derivation duplicates the thread. WhatsApp's title-prefix case is now fixed; the general hazard remains. |
| Outlook correspondents | 0 by design (single-account fixture). Revisit only with a real multi-party `.pst`. |
| 11 correspondents with no `first_seen_utc` | 10 SMS phone-only contacts + 1 email address, all in threads with no messages. Correct by construction. |
| `App.jsx:249` parses a platform out of a key | Still true. It runs on a Thread key so it is safe, but do not extend the pattern — Correspondent keys are now `person:…`. |
