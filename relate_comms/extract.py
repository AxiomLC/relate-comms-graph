"""Extraction — propose entity spans. Decide nothing.

WHY THIS FILE EXISTS
--------------------
`canon` flattens a name it is handed; it cannot decide that a span *is* a name. Run
every capitalised word through `canonical(kind="place")` and `monday`, `hi dave` and
`ny` come back as clean keys — no error, no useful node. Something has to read the
body first, and that is this module.

The order it belongs to, and never breaks:

    extract per message  ->  fold within a platform  ->  match across platforms

    extract   this file   proposes spans, with offsets and the message they came from
    canon     `canon.canonical(kind=…)` converges spellings inside one platform
    link      `link.link()` merges across platforms

Extraction must not merge. It emits a list; a better extractor can be re-run over
older messages without touching the graph, because nothing here writes.

ENGLISH ONLY, ON PURPOSE
------------------------
v1 ships the English model. A body that is not English yields no spans, not wrong
ones: silence is cheaper than a node the user cannot trust. `language_guess()` is the
seam — a later language is a second model and a per-message guess here, not a rewrite
of the pipeline. A caller may surface the guess as a **warning**; it never raises.

NO MODEL FALLBACK
-----------------
spaCy is the declared extractor. If it is not installed, `available()` is False and
extraction returns nothing — it does not quietly degrade to a regex that would mint
`monday` again. The ingest reports the absence once, as a warning.

WHAT IS A PLACE HERE
--------------------
    GPE   geo-political: a city, region or country          `Austin`, `Texas`
    LOC   a non-political location                          `the Bay Area`
    FAC   a facility, building or road                      `12 Baker Street`

The label is kept on the mention, so a later question can tell a city from a street.

KNOWN FALSE POSITIVE, ACCEPTED
The small model labels a product or company `GPE` in some frames, and the samples show
it: `nothing new from Databricks` and `did you ever hear from Retool` both propose a
`Place`. The same words in a different frame (`We use Databricks daily`) propose
nothing, so the error is frame-sensitive rather than deterministic.

This is **not** filtered by a second guess. Suppressing a `GPE` because the token also
looks like a company would be extraction deciding, and it would silently drop the
`Hermes`-the-street case to protect the `Hermes`-the-company one. The mitigation is
the design's own: a Place node is derived and re-runnable, `mention_count` makes a
one-off obvious, and `link` never fuzzy-merges an entity — so a stray `place:retool`
costs a node, not a merge, and deleting it touches no message.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


# The spaCy labels that mean "a place". Anything else spaCy proposes is ignored —
# an `ORG` is not a `Place` even when the words look like one (`Kensington Market`
# comes back as an ORG, and guessing otherwise would be extraction deciding).
PLACE_LABELS: tuple[str, ...] = ("GPE", "LOC", "FAC")

# The spaCy label that means "an organisation" — deliberately BROAD, matching the
# CoNLL/OntoNotes scheme the model was trained on: companies, government bodies,
# councils, NGOs, unions, clubs, societies, universities, teams.
#
# **One label, one kind.** A span is a Place or an Organization, never both — the
# `_mentions_from_doc` loop assigns exactly one kind per entity, so the two kinds can
# never be minted from the same words. That is the same boundary the Place comments
# draw from the other side.
ORG_LABELS: tuple[str, ...] = ("ORG",)

# A span that ENDS on one of these was cut short by the model, not named. Measured on
# `en_core_web_sm`: `University of Sydney` came back as `University of`, which would
# have become its own node. Dropped rather than extended — extending means deciding
# where the name stops, which is extraction inventing.
TRUNCATION_TAILS = frozenset({"of", "the", "and", "de", "du", "des", "for"})

# A shipped ORG dictionary, applied by the same `EntityRuler` as the place list.
#
# **Why it is needed, measured not assumed.** Over 18 clearly-named organisations,
# `en_core_web_sm` found 13. It missed exactly the names it was never trained to treat as
# institutions: product-style company names (`Snowflake`, `Databricks`, `BlackRock`),
# and an NGO whose name is not English (`Medecins Sans Frontieres`). It also split
# `Unite the Union` down to `Union`.
#
# This is not a substitute for the model — it is the same audit table `PLACE_DICTIONARY`
# is, for the names the model silently drops. Keep it boring: every entry is a claim
# that the words name an organisation. The Owner's own graph is the useful seed.
ORG_DICTIONARY: tuple[str, ...] = (
    # Product-style company names the model reads as brands, not institutions.
    "Snowflake", "Databricks", "BlackRock", "Scale AI", "Weights & Biases",
    "OpenAI", "Anthropic", "Retool", "Celestica", "Palantir", "Stripe",
    "Shopify", "Twilio", "Cloudflare", "MongoDB", "Hugging Face",
    # NGOs and bodies whose names are not English, which the English model skips.
    "Medecins Sans Frontieres", "Médecins Sans Frontières", "Amnesty International",
    "Oxfam", "Greenpeace", "Red Cross", "Brotherhood of St Laurence",
    # Long forms the model truncates or partial-matches.
    "Unite the Union", "University of Sydney", "NSW Health",
)

# Below this many characters a span is noise (`NY` survives, `N` does not). Applied
# after trimming, never to the canonical form: `canon` owns that decision.
MIN_SPAN_CHARS = 2

# A body above this many characters is not a chat message, and running chat-oriented
# NER over it is a category error.
# **Measured, not guessed.** On the live store of 2,085 messages the length
# distribution is: median 28 chars, p95 77, p99 122, max 11,719. Every junk
# Organization we saw (`pdf`, `swf`, `pptm`, `wordprocessing ml 2003`,
# `end user license agreement`, `jasper reports`) came from exactly ONE message — a
# 11,719-character marketing newsletter — which is 96x the p99.
#
# So the noise was never a long tail of uncertain mentions. It was one document being
# read as if it were a conversation. A frequency threshold (`count >= 2`) would have
# kept every one of those junk nodes, because the real signal (`sox`, 15 mentions
# across two platforms) and the junk differ by LENGTH, not by count.
#
# The number is derived, not chosen: 4x the p99 of this corpus (122 chars) rounded up to
# a clean boundary, i.e. ~400 chars. A genuine long message — a forwarded brief, a
# pasted transcript, a long email — sits in the hundreds and still extracts. The guard
# only catches a body that is orders of magnitude out of family with the corpus, which
# is what the 11,719-char newsletter was.
#
# **Getting this wrong once already:** the first version used 12,000, one round number
# picked by eye, which sat just ABOVE the 11,719-char message it was written to catch and
# therefore did nothing. A threshold next to the case it targets is a coincidence, not a
# rule; derive it from the distribution and the mistake cannot recur.
DOCUMENT_CHARS = 2_000

# Is the `Product` kind live? **Off until its dictionary exists.**
#
# The arbitration below is real and tested with the flag on, but a `Product` leg with no
# product vocabulary would be a guess: `en_core_web_sm` has no `PRODUCT` label at all, so
# the only thing that can claim a span is a dictionary entry, and there is no index yet
# (`rework_extraction.md` §4 step 3). Off means the seam exists, is exercised by tests,
# and writes nothing — the live store and every existing count are unchanged.
#
# Deliberately a module constant and not an env var: a switch that can differ between two
# machines running the same code makes a store impossible to explain.
PRODUCT_ENABLED = True

# A shipped place dictionary, applied by spaCy's `EntityRuler` **before** the learned
# NER. This is not a nicety: `en_core_web_sm` labels a bare city `PERSON` when the
# sentence gives no locative cue (`Then Austin on Friday` -> PERSON, `I am in Austin` ->
# GPE). Relying on the model alone would silently drop a real place for a reason the
# user cannot see or act on, which is precisely the failure the extraction design
# calls unacceptable. The ruler is a deliberate, auditable counterweight.
#
# Keep this list boring and English: every entry is a claim that a token is a place.
PLACE_DICTIONARY: tuple[str, ...] = (
    "Amsterdam", "Athens", "Atlanta", "Auckland", "Austin", "Baghdad",
    "Bangkok", "Barcelona", "Beijing", "Belfast", "Berlin", "Birmingham",
    "Bogota", "Bombay", "Boston", "Brisbane", "Brussels", "Budapest",
    "Buenos Aires", "Cairo", "Calgary", "Cape Town", "Cardiff", "Chicago",
    "Copenhagen", "Dallas", "Delhi", "Denver", "Detroit", "Dubai",
    "Dublin", "Durban", "Edinburgh", "Frankfurt", "Geneva", "Glasgow",
    "Hamburg", "Helsinki", "Hong Kong", "Houston", "Istanbul", "Jakarta",
    "Johannesburg", "Kansas City", "Kuala Lumpur", "Lagos", "Las Vegas",
    "Leeds", "Lisbon", "Liverpool", "London", "Los Angeles", "Madrid",
    "Manchester", "Manila", "Melbourne", "Mexico City", "Miami", "Milan",
    "Montreal", "Moscow", "Mumbai", "Nairobi", "New York", "Newcastle",
    "Oslo", "Ottawa", "Paris", "Perth", "Philadelphia", "Phoenix", "Prague",
    "Pretoria", "Rio de Janeiro", "Rome", "San Francisco", "Santiago",
    "Sao Paulo", "Seattle", "Seoul", "Shanghai", "Singapore", "Stockholm",
    "Sydney", "Taipei", "Tokyo", "Toronto", "Vancouver", "Vienna",
    "Warsaw", "Washington", "Wellington", "Zurich",
    # The generated samples' own pool, so a public clone exercises the pipeline.
    "North Dakota", "Fargo", "Bismarck", "Bay Area",
)


@dataclass(frozen=True)
class Mention:
    """One proposed place, with where it came from. Not yet a node, not yet a key.

    `message_key` and the offsets are the provenance the design insists on: a mention
    can be re-derived, re-scored or thrown away without asking the graph anything.

    `platform` rides along because folding is per platform, and asking the store for it
    later would be a second query for a fact the caller already has.
    """

    text: str
    label: str
    start: int
    end: int
    message_key: str
    platform: str
    # Which canonicalisation kind and store label this mention belongs to:
    # `"place"`, `"organization"` or `"product"`. Set here, because something has to
    # resolve the competing labels, and resolving it in the writer would mean re-deciding
    # per row what was already decided per span.
    kind: str = "place"
    # Every kind this span could plausibly be, strongest first — **provenance, not a
    # decision**. `kind` is what gets written; this is the record of what lost and why a
    # later reviewer might disagree. It exists because the arbitration is the newest and
    # least proven part of the pipeline (`rework_extraction.md` §4 step 2), and a wrong
    # choice should be visible without re-running the extractor.
    #
    # Empty on a mention from a path that never arbitrates (the old single-kind helpers),
    # so a caller can tell "considered and rejected" from "never considered".
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "message_key": self.message_key,
            "platform": self.platform,
            "kind": self.kind,
            "candidates": list(self.candidates),
        }


# The loaded pipeline. Loading is ~1s and allocates tens of MB, so it happens once,
# on first use, and a failure is remembered rather than retried per message.
_NLP = None
_LOAD_ERROR: str | None = None


def available() -> bool:
    """Is the English extractor installed and loadable?

    Checked by the ingest so a missing model is one warning on the report rather than
    a stack trace per batch, and so the rest of the run is unaffected.
    """
    _ensure_model()
    return _NLP is not None


def unavailable_reason() -> str:
    """Why `available()` said no, as a sentence a report can print. Empty when loaded."""
    _ensure_model()
    return _LOAD_ERROR or ""


def _ensure_model() -> None:
    global _NLP, _LOAD_ERROR
    if _NLP is not None or _LOAD_ERROR is not None:
        return
    try:
        import spacy
    except ImportError:
        _LOAD_ERROR = (
            "entity extraction skipped: spacy is not installed "
            "(python -m pip install spacy && python -m spacy download en_core_web_sm)"
        )
        return
    try:
        _NLP = spacy.load("en_core_web_sm", exclude=["lemmatizer", "attribute_ruler"])
    except OSError:
        _LOAD_ERROR = (
            "entity extraction skipped: the English model is not installed "
            "(python -m spacy download en_core_web_sm)"
        )
        return
    _install_ruler()


def _install_ruler() -> None:
    """Put a place dictionary in front of the learned NER.

    `before="ner"` and `overwrite_ents=True` together are what make the dictionary
    authoritative: the ruler's span wins over the learned pass, so `Then Austin on
    Friday` is a GPE rather than the PERSON the model would have produced. A `FAC` the
    model finds and the dictionary does not (`12 Baker Street`) is untouched — the
    ruler only speaks about the names it was given.
    """
    if _NLP is None or "place_ruler" in _NLP.pipe_names:
        return
    # Renamed in spirit, kept as `place_ruler` so an existing pipeline is not rebuilt.
    # One pipe holds both dictionaries: `overwrite_ents` gives the ruler precedence over
    # the learned pass, and two pipes would only make that precedence harder to reason
    # about (the second would silently win on an overlapping span).
    ruler = _NLP.add_pipe("entity_ruler", name="place_ruler", before="ner",
                         config={"overwrite_ents": True})
    ruler.add_patterns([
        {"label": "GPE", "pattern": name, "id": name.casefold()}
        for name in PLACE_DICTIONARY
    ])
    ruler.add_patterns([
        {"label": "ORG", "pattern": name, "id": name.casefold()}
        for name in ORG_DICTIONARY
    ])


# ------------------------------------------------------------------ language seam


# Words that are overwhelmingly English-commercial rather than merely shared with
# another Latin-script language. Deliberately tiny and boring: this is a *warning*
# signal, so a false negative costs nothing and a false positive costs a line of text.
_ENGLISH_MARKERS = frozenset({
    "the", "and", "you", "your", "for", "with", "that", "this", "have", "will",
    "from", "are", "was", "were", "not", "but", "can", "what", "when", "there",
    "about", "would", "should", "thanks", "please", "hello", "today", "tomorrow",
})

# Enough words before the guess means anything. Below this a body is too short to
# tell `ok` (English) from `ok` (Dutch), so it is not accused of anything.
_MIN_WORDS_FOR_GUESS = 12
_MARKER_SHARE = 0.12


def looks_like_document(body: str) -> bool:
    """Is this body too long to be a chat message? See `DOCUMENT_CHARS`.

    A warning signal like `language_guess`, not a silent gate: the ingest counts these
    and says so, because "N message(s) look like documents and contributed no entities"
    is actionable, whereas an unexplained empty result is not.
    """
    return len(body or "") > DOCUMENT_CHARS


def language_guess(body: str) -> str:
    """`"en"`, `"non-en"` or `"unknown"` — a warning signal, never a gate.

    Script decides first: Latin letters are required for the English model to have any
    chance, so a Cyrillic, CJK or Arabic body is `non-en` without counting words. For a
    Latin body, a short one is `unknown` rather than accused, and a long one is judged
    on the share of common English function words.

    Nothing downstream branches on this. It exists so the ingest can say "3 messages
    look non-English, so they contribute no Places" instead of leaving the user to
    wonder why a French export drew nothing.
    """
    text = (body or "").strip()
    if not text:
        return "unknown"
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return "unknown"
    latin = sum(1 for ch in letters if ch.isascii())
    if latin / len(letters) < 0.6:
        return "non-en"

    words = [word.strip(".,!?;:'\"()[]-").casefold() for word in text.split()]
    words = [word for word in words if word]
    if len(words) < _MIN_WORDS_FOR_GUESS:
        return "unknown"
    hits = sum(1 for word in words if word in _ENGLISH_MARKERS)
    return "en" if hits / len(words) >= _MARKER_SHARE else "non-en"


# -------------------------------------------------------------------- extraction


def places(body: str, *, message_key: str = "", platform: str = "") -> list[Mention]:
    """Every place span in one body, in order. No key, no node, no dedupe.

    The caller folds; this only reads. A message with no places returns `[]`, which is
    the ordinary answer and not a failure.

    **Fragmented, like `extract()`.** A single-body helper that read an HTML export
    whole would disagree with the batch path about the same message, and the difference
    would only show up on the platform that concatenates turns.
    """
    _ensure_model()
    if _NLP is None or not (body or "").strip():
        return []
    return [
        mention for fragment in fragments(body)
        for mention in _mentions_from_doc(
            _NLP(fragment.text), message_key, platform, body, offset=fragment.offset)
        if mention.kind == "place"
    ]


def organizations(
    body: str, *, message_key: str = "", platform: str = "",
) -> list[Mention]:
    """Every organization span in one body. Same contract as `places()`."""
    _ensure_model()
    if _NLP is None or not (body or "").strip():
        return []
    return [
        mention for fragment in fragments(body)
        for mention in _mentions_from_doc(
            _NLP(fragment.text), message_key, platform, body, offset=fragment.offset)
        if mention.kind == "organization"
    ]


def extract(
    messages: Iterable[tuple[str, str, str]],
) -> list[Mention]:
    """Every entity span — Places AND Organizations — from `(key, platform, body)`.

    One `nlp.pipe` call rather than one per message: the parser pays a fixed cost per
    call, and an ingest hands over thousands of bodies at once. Each `Mention` carries
    its own `kind`, so the caller splits rather than asking the model twice.
    """
    _ensure_model()
    rows = [(key, platform, body or "") for key, platform, body in messages]
    if _NLP is None or not rows:
        return []

    out: list[Mention] = []
    for mentions in _pipe_with_context(rows):
        out.extend(mentions)
    return out


# An exported HTML body is several chat turns concatenated by the exporter, not one turn.
#
# **Measured, not assumed.** 149 messages in the live store contain `<br>`, every one of
# them more than once, and the bodies read like this:
#
#     "I'll look at the Coke account tonight.<br>OpenSearch keeps falling over. just sent
#      it over.<br>shall we sort the campaign out?"
#
# Two unrelated procurement contexts and a social line, read by the model as one span
# context. Splitting them was measured on that corpus: +4 mentions found, and **six
# contaminated spans removed** — including `organization:abc corp?<br>`, which existed
# only because a dictionary name abutted a tag and the ruler matched across it.
#
# The tag itself is never part of a span once a body is split, which is the real prize.
# The split is here rather than in the adapters because it is an extraction concern: the
# stored body must stay as the export wrote it (`canon`'s display path and the Viewer both
# show it), and only the reading of it changes.
HTML_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)

# Below this many characters a fragment is not worth a spaCy parse.
#
# **Measured on the 374 fragments in the live store:** 8 are 2 characters (`ok`, `hi`),
# 25 are under 8. Those are real turns and they never name an entity, so paying a parse
# for them is waste. The floor is deliberately a single character, not a word — an empty
# piece between adjacent tags is the only thing being dropped.
MIN_FRAGMENT_CHARS = 1


@dataclass(frozen=True)
class Fragment:
    """One readable piece of a body, with where it sits in the concatenated original.

    `offset` is the fragment's start within the **original** body, so a span found here
    maps back to the stored text without the caller knowing a split happened. Nothing
    downstream needs a fragment id: the `MENTIONS` edge hangs off the message, and a
    message naming the same entity in two turns is one edge.
    """

    text: str
    offset: int


def fragments(body: str) -> list[Fragment]:
    """Split an exported body on HTML line breaks. Never returns an empty list for non-blank input.

    A body with no break is one fragment starting at 0, so the caller has one code path.
    Empty pieces between adjacent tags are dropped rather than parsed — `<br><br>` is a
    paragraph gap, not an empty message.
    """
    if not body:
        return []
    out: list[Fragment] = []
    position = 0
    for match in HTML_BREAK.finditer(body):
        piece = body[position:match.start()]
        if len(piece.strip()) >= MIN_FRAGMENT_CHARS:
            lead = len(piece) - len(piece.lstrip())
            out.append(Fragment(text=piece.strip(), offset=position + lead))
        position = match.end()
    piece = body[position:]
    if len(piece.strip()) >= MIN_FRAGMENT_CHARS:
        lead = len(piece) - len(piece.lstrip())
        out.append(Fragment(text=piece.strip(), offset=position + lead))
    return out


def _pipe_with_context(rows: list[tuple[str, str, str]]) -> Iterable[list[Mention]]:
    """Every mention for each body, skipping empty bodies.

    spaCy's `pipe` skips nothing, so empty bodies would still cost a parse; they are
    filtered here.

    **One doc per fragment, not per body.** `fragments()` is applied first, so an HTML
    export's concatenated turns are parsed separately (see `HTML_BREAK`). Each fragment
    carries its offset into the original body, and `_mentions_from_doc` adds it back, so
    every `Mention` keeps an offset that points at the stored text.

    **Yields mentions only, not `(doc, mentions)`.** The doc was never read by the
    caller, and with fragmentation there is no longer one doc per row to hand back — a
    tuple would invite a caller to assume there is.
    """
    live = [
        (index, body) for index, (_k, _p, body) in enumerate(rows)
        # `looks_like_document` skips a newsletter or pasted article: chat-oriented NER
        # over marketing copy mints file extensions as Organizations. Skipped here, so
        # the cost is not even paid, and reported by the caller rather than silently.
        if body.strip() and not looks_like_document(body)
    ]
    if not live or _NLP is None:
        return

    # Flatten to (row index, fragment) so `nlp.pipe` sees every fragment as its own text.
    units: list[tuple[int, Fragment]] = [
        (index, fragment) for index, body in live for fragment in fragments(body)
    ]
    if not units:
        return

    docs = _NLP.pipe([fragment.text for _i, fragment in units], batch_size=64)
    found: dict[int, list[Mention]] = {}
    for (index, fragment), doc in zip(units, docs):
        key, platform, body = rows[index]
        found.setdefault(index, []).extend(
            _mentions_from_doc(doc, key, platform, body, offset=fragment.offset)
        )
    for index in (i for i, _b in live):
        yield found.get(index, [])


def _mentions_from_doc(doc, key: str, platform: str, body: str, *,
                       offset: int = 0) -> list[Mention]:
    """The span loop, over an already-parsed doc. Shared with `places()`.

    `offset` is where the parsed text starts within `body` — non-zero when the body was
    split on HTML breaks. It is added to every span's `start`, so offsets point at the
    original stored text and a fragment id never has to travel downstream.

    **The span is taken whole.** A leading `the` is *not* stripped here, and that is a
    deliberate reversal: slicing past the article of `the Coca-Cola` leaves `Coca-Cola`,
    a tail with no determiner, which is exactly the shape that reads as a place and was
    minting a false `place:coca-cola`. `canon` already drops a leading article for
    identity (`the Bay Area` -> `bay area`), so the key is unaffected and the span stays
    honest about what the model actually matched.
    """
    out: list[Mention] = []
    for ent in doc.ents:
        # **The kind is arbitrated, not inherited.** Before this, `GPE` meant place and
        # `ORG` meant organization by the shape of an `if` statement, so whichever label
        # the model happened to fire owned the node. `_arbitrate` may return the same kind
        # — with the flag off it always does — but the decision now has one home.
        kind, candidates = _arbitrate(ent.text, ent.label_, body)
        if not kind:
            continue
        # **The flag gates the model's own `PRODUCT` label too.** `en_core_web_sm` does
        # emit it (rarely, and frame-sensitively), so without this a product mention would
        # reach the writer and be silently dropped by its `kinds=` filter — a mention that
        # passed arbitration and then evaporated. Dropped here, and counted, so the report
        # can say how much the leg would find.
        if kind == "product" and not PRODUCT_ENABLED:
            continue
        text = ent.text.strip()
        if len(text) < MIN_SPAN_CHARS:
            continue
        # A span the model cut short is a fragment, not a name — `University of` would
        # otherwise become an Organization node of its own. Dropped, never extended.
        if kind == "organization" and text.split()[-1].rstrip(".,").casefold() in TRUNCATION_TAILS:
            continue
        # A span must not contain markup. Before fragmentation this happened: a dictionary
        # name ending a turn abutted the tag and the ruler matched across it, minting
        # `organization:abc corp?<br>`. Fragmentation removes the cause; this keeps it
        # from returning by any other route.
        if HTML_BREAK.search(text):
            continue
        start = offset + ent.start_char
        end = start + len(ent.text.rstrip())
        if end > len(body):
            continue
        out.append(Mention(
            text=text, label=ent.label_, start=start, end=end,
            message_key=key, platform=platform, kind=kind, candidates=candidates,
        ))
    return out


# ------------------------------------------------------------------ arbitration

# Which kinds a spaCy label may propose, strongest first. The order is the tie-break:
# a span the model called `ORG` is an Organization before it is anything else.
#
# `PRODUCT` is included because `en_core_web_sm` DOES emit it — corrected 2026-11-23; an
# earlier note in this repo claimed it did not. It emits it rarely and frame-sensitively:
# `"I've moved everything onto Ansible."` is a `PRODUCT`, `"Ansible keeps falling over."`
# is nothing.
#
# **`PERSON` is deliberately ABSENT.** The model labels `Grafana`, `Tableau` and `Docker`
# as `PERSON` in most frames, and mapping `PERSON` to a kind would make every human name a
# candidate for something — `Dave said it was fine.` became a Product when this was tried.
# A `PERSON` span is therefore dropped by the model's opinion and can ONLY be rescued by
# the product index, which is `_PERSON_RESCUE_LABELS` below.
LABEL_KINDS: dict[str, tuple[str, ...]] = {
    **{label: ("place",) for label in PLACE_LABELS},
    **{label: ("organization",) for label in ORG_LABELS},
    "PRODUCT": ("product",),
}

# Labels the product index may overrule. `PERSON` is here because a bare product name with
# no cue reads as a person to the small model — the same failure `PLACE_DICTIONARY` exists
# to fix for bare cities (`Then Austin on Friday` -> PERSON). The index decides; an
# unrecognised `PERSON` is still dropped, so nothing is loosened but the names we claim.
PRODUCT_RESCUE_LABELS: frozenset[str] = frozenset({"PERSON"})


def _arbitrate(text: str, label: str, body: str = "") -> tuple[str, tuple[str, ...]]:
    """Decide what a proposed span **is**, returning `(winning kind, all candidates)`.

    This is the seam the rework exists for. Until 2026-11-23 the kind was simply
    "whichever spaCy label fired", which is how `place:tableau`, `place:gemini` and
    `organization:claude` got into the graph — 29 of 212 entity nodes were products
    wearing the wrong label.

    **With `PRODUCT_ENABLED` off this is the identity function.** It returns the same
    kind the label always implied, in the same order, so every existing count and node
    is byte-identical.

    **With it on, the index may overrule the model** — but only for these labels:

        GPE / LOC / FAC   the index may make it a Product
        PRODUCT           already a Product
        PERSON            the index may make it a Product, and ONLY the index
        ORG               the index may NOT

    `PERSON` is included because the small model labels `Grafana`, `Tableau` and `Docker`
    as people in most frames — and a dropped `PERSON` meant the index could never rescue
    the names it exists for. **Only the index promotes a `PERSON`**, never the label: an
    unrecognised human name is still dropped, which a test pins with `Dave said it was
    fine.`

    `ORG` is excluded on purpose. An `ORG` span is often a *longer* name than the product
    inside it — `Grafana Labs` the company contains `Grafana` the product — and demoting
    that would lose the organisation, which is a true fact the graph should keep. So
    `organization:snowflake` and `organization:claude` stay Organizations;
    `rework_extraction.md` §5 open decision 2 records that as deliberate.

    The arbitration is per span and needs the body, because a context-gated entry
    (`Support Plan`) is only a product in a procurement sentence.
    """
    possible = LABEL_KINDS.get(label, ())
    rescue = label in PRODUCT_RESCUE_LABELS
    if not possible and not rescue:
        return "", ()
    winning = possible[0] if possible else ""

    # Only titles the index can promote. `ORG` and `PERSON`-without-a-hit both fall through
    # to `winning`, which is `""` for a rescue label — a dropped span, as before.
    promotable = PRODUCT_ENABLED and (not possible or winning != "organization")
    if promotable:
        from . import products  # local: `products` imports `canon`, not `extract`

        verdict, _reason = products.decide(text, body)
        if verdict:
            # The model's own label, when it gave one, stays as a candidate.
            return "product", ("product", *possible)

    return winning, possible
