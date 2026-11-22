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

from collections.abc import Iterable
from dataclasses import dataclass


# The spaCy labels that mean "a place". Anything else spaCy proposes is ignored —
# an `ORG` is not a `Place` even when the words look like one (`Kensington Market`
# comes back as an ORG, and guessing otherwise would be extraction deciding).
PLACE_LABELS: tuple[str, ...] = ("GPE", "LOC", "FAC")

# Below this many characters a span is noise (`NY` survives, `N` does not). Applied
# after trimming, never to the canonical form: `canon` owns that decision.
MIN_SPAN_CHARS = 2

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

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "message_key": self.message_key,
            "platform": self.platform,
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
    ruler = _NLP.add_pipe("entity_ruler", name="place_ruler", before="ner",
                         config={"overwrite_ents": True})
    ruler.add_patterns([
        {"label": "GPE", "pattern": name, "id": name.casefold()}
        for name in PLACE_DICTIONARY
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
    """
    _ensure_model()
    if _NLP is None or not (body or "").strip():
        return []
    return _mentions_from_doc(_NLP(body), message_key, platform, body)


def extract(
    messages: Iterable[tuple[str, str, str]],
) -> list[Mention]:
    """Places from `(message_key, platform, body)` triples, batched through spaCy.

    One `nlp.pipe` call rather than one per message: the parser pays a fixed cost per
    call, and an ingest hands over thousands of bodies at once.
    """
    _ensure_model()
    rows = [(key, platform, body or "") for key, platform, body in messages]
    if _NLP is None or not rows:
        return []

    out: list[Mention] = []
    for doc, mentions in _pipe_with_context(rows):
        out.extend(mentions)
    return out


def _pipe_with_context(rows: list[tuple[str, str, str]]):
    """Pair each parsed doc with its provenance, skipping empty bodies.

    spaCy's `pipe` skips nothing, so empty bodies would still cost a parse; they are
    filtered here and the surviving indices re-zip to their own key and platform.
    """
    live = [(index, body) for index, (_k, _p, body) in enumerate(rows) if body.strip()]
    if not live or _NLP is None:
        return
    docs = _NLP.pipe([body for _index, body in live], batch_size=64)
    for (index, body), doc in zip(live, docs):
        key, platform, _body = rows[index]
        yield doc, _mentions_from_doc(doc, key, platform, body)


def _mentions_from_doc(doc, key: str, platform: str, body: str) -> list[Mention]:
    """The span loop, over an already-parsed doc. Shared with `places()`.

    **The span is taken whole.** A leading `the` is *not* stripped here, and that is a
    deliberate reversal: slicing past the article of `the Coca-Cola` leaves `Coca-Cola`,
    a tail with no determiner, which is exactly the shape that reads as a place and was
    minting a false `place:coca-cola`. `canon` already drops a leading article for
    identity (`the Bay Area` -> `bay area`), so the key is unaffected and the span stays
    honest about what the model actually matched.
    """
    out: list[Mention] = []
    for ent in doc.ents:
        if ent.label_ not in PLACE_LABELS:
            continue
        text = ent.text.strip()
        if len(text) < MIN_SPAN_CHARS:
            continue
        start = ent.start_char
        end = start + len(ent.text.rstrip())
        if end > len(body):
            continue
        out.append(Mention(
            text=text, label=ent.label_, start=start, end=end,
            message_key=key, platform=platform,
        ))
    return out
