"""Canonical flattening — one pipe, four kinds of name.

WHY THIS FILE EXISTS
--------------------
A name arrives from an export as the platform spelled it. The same person can appear
as `David Sartori`, `dave sartori`, `Dave S.` and `davesartori@gmail.com` — in one
platform, in one year. Keying a node on the raw string mints four nodes for one human,
and the graph stops being readable: fifteen threads with one person should fan into one
`Correspondent`, not fifteen.

So every name is flattened **before** it becomes a node key. One module, one call site,
four kinds:

    person        `Dave Sartori`      -> `david sartori`
    organization  `ABC Corp, Inc.`    -> `abc corp`
    place         `New York, NY`      -> `new york`
    product       `the Coke account`  -> `coke`

The four kind names are the **node type names**, not internal jargon: `Person`,
`Organization`, `Place`, `Product`. `thing` and `company` were the old spellings and
are gone — a caller passing one now fails loudly instead of silently taking the
`person` branch, which would strip credentials and resolve nicknames on a product
name.

`Person` extracted from a message body uses the same pipe as a `Correspondent` taken
from export metadata. Nothing here assumes a person.

WHAT THIS FILE DOES NOT DO
--------------------------
It does not touch the store, and it does not merge anything. It returns a `Canonical`
record; the caller decides what to do with it. Fuzzy candidates are **reported, not
applied** — see `candidates()`.

THE OWNER
---------
The Owner is the person using the app. No leg, present or future, may emit a node for
them. The guard lives here rather than in each adapter because the adapters disagree
about what the Owner's identifier *is*: Telegram resolves a user id
(`user1426445212`), Messenger and LinkedIn resolve a display name (`David Sartori`),
Email resolves an address. Comparing a Telegram id against a display name matches
nothing, which is why the old per-adapter guard was inert on four of five platforms.

`is_owner()` therefore compares against every form the caller can supply, and the
caller supplies the platform's own resolved owner.

WHY HAND-CODED NICKNAMES
------------------------
`Bob` and `Robert` share no characters, so no string-similarity scorer can join them.
`corp-names` ships a 15,197-entry multilingual table (1.07 MB) that would solve it, but
this app is English-only, and that library also mangles Arabic (`باسي موسى` -> `bsy mws~`)
and silently drops characters (`Øyvind Ås` -> `oyvind`). A hand-written English table is
smaller, auditable, and cannot lose a name it does not recognise.

`rapidfuzz` is used for what a table cannot do: `Pete Brown` vs `Peter Brown` after the
nickname pass, and surname typos. It is already a dependency.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Literal

Kind = Literal["person", "organization", "place", "product"]

# The kind names, in the order the UI lists them. `Correspondent` is deliberately
# absent: it is written by ingest, not extracted from a body.
KINDS: tuple[str, ...] = ("person", "organization", "place", "product")

# --------------------------------------------------------------------------- tables

# English nicknames -> the canonical given name. Deliberately short: every entry is a
# claim that two spellings are one person, and a wrong entry merges two people.
# Extend only from evidence in a real export.
NICKNAMES: dict[str, str] = {
    # male
    "abe": "abraham", "al": "albert", "alex": "alexander", "andy": "andrew",
    "art": "arthur", "bart": "bartholomew", "ben": "benjamin", "bernie": "bernard",
    "bert": "albert", "bill": "william", "billy": "william", "bob": "robert",
    "bobby": "robert", "brad": "bradley", "charlie": "charles", "chuck": "charles",
    "dan": "daniel", "danny": "daniel", "dave": "david", "dick": "richard",
    "don": "donald", "doug": "douglas", "ed": "edward", "eddie": "edward",
    "frank": "francis", "fred": "frederick", "freddy": "frederick", "gene": "eugene",
    "greg": "gregory", "hank": "henry", "harry": "henry", "jack": "john",
    "jake": "jacob", "jim": "james", "jimmy": "james", "joe": "joseph",
    "joey": "joseph", "johnny": "john", "ken": "kenneth", "kenny": "kenneth",
    "larry": "lawrence", "len": "leonard", "matt": "matthew", "mike": "michael",
    "mikey": "michael", "nate": "nathan", "nick": "nicholas", "pat": "patrick",
    "pete": "peter", "phil": "philip", "ray": "raymond", "rich": "richard",
    "rick": "richard", "ricky": "richard", "rob": "robert", "ron": "ronald",
    "russ": "russell", "sam": "samuel", "steve": "stephen", "stevie": "stephen",
    "ted": "theodore", "teddy": "theodore", "tim": "timothy", "tom": "thomas",
    "tommy": "thomas", "tony": "anthony", "vic": "victor", "vince": "vincent",
    "walt": "walter", "will": "william", "willy": "william", "zach": "zachary",
    # female
    "abby": "abigail", "becky": "rebecca", "beth": "elizabeth", "betsy": "elizabeth",
    "betty": "elizabeth", "cathy": "catherine", "cindy": "cynthia", "debbie": "deborah",
    "deb": "deborah", "dot": "dorothy", "ellie": "eleanor", "fran": "francis",
    "gabby": "gabrielle", "jen": "jennifer", "jenny": "jennifer", "jess": "jessica",
    "kate": "katherine", "kathy": "katherine", "katie": "katherine", "liz": "elizabeth",
    "lizzie": "elizabeth", "maggie": "margaret", "marge": "margaret", "meg": "margaret",
    "nancy": "ann", "patty": "patricia", "peg": "margaret", "peggy": "margaret",
    "sue": "susan", "susie": "susan", "tina": "christina", "vicky": "victoria",
}

# Professional credentials that follow a name. `Steve Mikano CIA, AIC-M, AINS, SSBB` is
# ONE person; the commas are inside the name. Stripped only from the tail.
CREDENTIALS = frozenset({
    "aia", "aic", "ains", "aic-m", "aicm", "asla", "caia", "cfa", "cfe", "cfp",
    "cia", "cissp", "cipm", "cisa", "cma", "cmc", "cpa", "cpcu", "cpcu", "cpe", "cpm",
    "cppm", "cscp", "csm", "dds", "dmd", "dvm", "esq", "facs", "frcs", "jd",
    "llm", "lpc", "lsw", "mba", "mbe", "md", "mfa", "mph", "msc", "msn", "np",
    "obe", "pe", "pgce", "phd", "ph.d", "pmp", "psyd", "pmp", "rn", "rph",
    "ssbb", "six sigma", "sr", "jr", "ii", "iii", "iv",
})

# Legal forms that end an organisation name. `ABC Corp, Inc.` and `ABC Corporation` are
# one company. Only stripped from the tail, and only when a real word precedes them —
# `Corp` alone is not a company.
LEGAL_SUFFIXES = frozenset({
    "ag", "as", "bhd", "bv", "co", "company", "corp", "corporation", "gmbh",
    "group", "holdings", "inc", "incorporated", "limited", "llc", "ltd", "nv",
    "oy", "partners", "plc", "pte", "pty", "sa", "sarl", "sas", "spa", "srl",
    "trust",
})

# Leading articles that carry no identity for a thing or place.
ARTICLES = frozenset({"the", "a", "an"})

# A place's region tail is dropped only when it cannot change which place is meant:
# a two-letter code (`new york, ny`) or a country (`london, uk`). A province or state
# spelled out is identity — `london, ontario` is not `london` — so it is kept.
_COUNTRY_TAIL = frozenset({
    "uk", "usa", "us", "u.s.", "u.s.a.", "united kingdom", "united states",
    "united states of america", "england", "scotland", "wales", "ireland",
    "canada", "australia", "new zealand", "france", "germany", "spain", "italy",
    "netherlands", "belgium", "portugal", "sweden", "norway", "denmark",
    "finland", "poland", "switzerland", "austria", "mexico", "brazil",
    "argentina", "india", "china", "japan", "singapore", "south africa",
    "united arab emirates", "uae", "israel", "turkey", "greece", "czechia",
})
_REGION_TAIL = re.compile(r",\s*([a-z][a-z. ]{1,24})\s*$")

# `New York, NY 10001` -> the postal code is not identity.
_POSTAL = re.compile(r"\s+\d{4,10}$")

# A comma with NO space after it separates list members; a comma WITH a space is inside
# a name (`Steve Mikano CIA, AIC-M`). This is the only reliable signal in the exports.
_LIST_COMMA = re.compile(r",(?=\S)")

# camelCase / PascalCase boundary: `PeteBromill` -> `Pete Bromill`.
#
# The lookbehind requires at least two lowercase letters before the capital, so a
# surname prefix is not split: `DeNegris` stays `DeNegris`, while `PeteBromill` splits.
# `McDonald` and `MacLeod` are protected by the same rule.
_CAMEL = re.compile(r"(?<=[a-z]{2})(?=[A-Z])")

# Anything that looks like a phone number rather than a name.
_PHONE_LIKE = re.compile(r"^\+?[\d\s()\-.]{7,}$")

# rapidfuzz is optional: without it, fuzzy candidates are simply not produced.
try:  # pragma: no cover - import-time capability probe
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover
    _fuzz = None

# Below this a pair is noise; at or above it the pair is *reported* as a candidate.
# Nothing is merged on a fuzzy score — see `candidates()`.
FUZZY_REPORT = 0.85


# --------------------------------------------------------------------------- record


@dataclass(frozen=True)
class Canonical:
    """One name, flattened. `key` is what a node is keyed on; `display` is what is shown.

    `evidence` says *why* two spellings collapsed, which is what makes a merge
    explainable after the fact:

        exact       the strings were already identical
        case        differed only by case
        diacritic   differed only by accents or invisible marks
        whitespace  differed only by spacing
        camel       differed only by a missing space (`PeteBromill`)
        nickname    a table entry joined them (`Bob` -> `Robert`)
        credential  a trailing credential was stripped
        suffix      a legal form was stripped (organisations)
        article     a leading `the`/`a`/`an` was stripped
        phone       the name is a phone number, compared as digits
        email       the name is an address, compared lowercased
        placeholder not a person; never merged
        owner       the Owner; never a node
        raw         nothing applied, the name is already canonical
    """

    raw: str
    key: str
    display: str
    kind: Kind
    evidence: str
    confidence: float = 1.0

    @property
    def is_placeholder(self) -> bool:
        return self.evidence == "placeholder"

    @property
    def is_owner(self) -> bool:
        return self.evidence == "owner"


# --------------------------------------------------------------------------- helpers


def strip_marks(raw: str) -> str:
    """NFKD, drop combining marks, casefold, collapse whitespace.

    NFKD rather than `unidecode`: it decomposes `é` into `e` + a mark and drops the
    mark, which is exactly right for names. `unidecode` transliterates whole scripts
    and would turn `李` into `Li`, inventing a spelling the export never had.
    """
    if not raw:
        return ""
    decomposed = unicodedata.normalize("NFKD", raw)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.category(ch).startswith("M"))
    return " ".join(without_marks.casefold().split())


def split_camel(raw: str) -> str:
    """`PeteBromill` -> `Pete Bromill`. A missing space is a formatting accident."""
    return _CAMEL.sub(" ", raw)


def is_phone(raw: str | None) -> bool:
    return bool(raw and _PHONE_LIKE.match(raw.strip()))


def phone_digits(raw: str | None) -> str | None:
    """Digits only. `+1 (917) 400-4025` and `917-400-4025` are one line."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) >= 8 else None


def is_email(raw: str | None) -> bool:
    if not raw:
        return False
    value = raw.strip().strip(".,;:")
    return "@" in value and " " not in value


def split_list(raw: str) -> list[str]:
    """Split a recipient field that holds several people.

    `Nigel Harrison,Anat Malkin,Christian Davis` -> three names (comma, no space).
    `Steve Mikano CIA, AIC-M, AINS, SSBB`       -> one name  (comma, then a space).

    This is the only signal the exports give, and it is the one that separates the two
    cases in real LinkedIn data. It is a heuristic, not a parse: a list written with
    spaces after its commas will not split, and a name with no space after its
    credential comma will split wrongly.
    """
    if not raw:
        return []
    return [part.strip() for part in _LIST_COMMA.split(raw) if part.strip()]


def _strip_credentials(words: list[str]) -> tuple[list[str], bool]:
    """Drop trailing credential tokens. Never empties the name.

    A credential arrives attached to a comma: `John Samoska, CPA`. The comma is part of
    the credential, not of the name, so it is stripped with it — otherwise the key ends
    in a dangling `,` and `John Samoska, CPA` never meets `John Samoska`.
    """
    stripped = False
    while len(words) > 1 and words[-1].rstrip(".,").casefold() in CREDENTIALS:
        words = words[:-1]
        stripped = True
    if stripped and words:
        words[-1] = words[-1].rstrip(",")
    return words, stripped


def _strip_legal(words: list[str]) -> tuple[list[str], bool]:
    """Drop a trailing legal form, but never down to nothing.

    `ABC Corp` -> `abc`, `ABC Corp, Inc.` -> `abc`. The guard is the same one
    frontal-lobe uses: a legal suffix only counts when a real word precedes it, so
    `Corp` alone stays `corp` rather than vanishing.

    `&` and `and` are dropped too: `Northwind & Co` and `Northwind and Co` are one
    company, and the conjunction carries no identity.
    """
    stripped = False
    while len(words) > 1 and words[-1].rstrip(".,").casefold() in LEGAL_SUFFIXES:
        words = words[:-1]
        stripped = True
    if stripped and words:
        words[-1] = words[-1].rstrip(",")
    while len(words) > 1 and words[-1] in {"&", "and"}:
        words = words[:-1]
        stripped = True
    return words, stripped


def _resolve_nicknames(words: list[str]) -> tuple[list[str], bool]:
    """Map a nickname to its canonical given name. Only the first token is considered.

    `Dave Sartori` -> `david sartori`. Deliberately first-token-only: a surname that
    happens to match a nickname (`Will` as a surname) must not be rewritten.
    """
    if not words:
        return words, False
    canonical = NICKNAMES.get(words[0].casefold())
    if canonical and canonical != words[0].casefold():
        return [canonical, *words[1:]], True
    return words, False


# --------------------------------------------------------------------------- the pipe


def canonical(
    raw: str | None,
    *,
    kind: Kind = "person",
    owner: Iterable[str] | None = None,
) -> Canonical:
    """Flatten one name. The single entry point.

    `owner` is every form the caller knows the Owner by on this platform — a display
    name, a user id, an address. Supplying all of them is what makes the guard work
    where a single identifier did not.

    An unknown `kind` raises. The pipeline's last branch is `person`, so a typo or an
    old spelling (`thing`, `company`) would silently strip credentials and resolve
    nicknames on a product name — a wrong merge that looks like a working call.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; known kinds are {list(KINDS)}")

    text = (raw or "").strip()
    if not text:
        return Canonical(raw="", key="", display="", kind=kind, evidence="raw")

    # --- the Owner, before anything else -------------------------------------
    # Compared on every form: the raw string, the mark-stripped form, phone digits and
    # the lowercased address. A Telegram id and a display name never meet, which is
    # why the caller must pass both.
    for form in owner or ():
        if _same_identity(text, form):
            return Canonical(raw=text, key="", display=text, kind=kind,
                             evidence="owner")

    # --- placeholders --------------------------------------------------------
    # `Facebook user` is not a person. It is returned marked, never merged, so the
    # caller can attach it to a per-platform pseudo-node instead of dropping it.
    if kind == "person" and strip_marks(text) in PLACEHOLDER_NAMES:
        return Canonical(raw=text, key=f"placeholder:{strip_marks(text)}",
                         display=text, kind=kind, evidence="placeholder")

    # --- a phone number is its digits ----------------------------------------
    if kind == "person" and is_phone(text):
        digits = phone_digits(text) or text
        return Canonical(raw=text, key=digits, display=text, kind=kind,
                         evidence="phone")

    # --- an address is its lowercase form ------------------------------------
    if kind == "person" and is_email(text):
        address = text.strip().strip(".,;:").casefold()
        return Canonical(raw=text, key=address, display=text, kind=kind,
                         evidence="email")

    # --- everything else goes through the text pipeline ----------------------
    return _canonical_text(text, kind)


def _canonical_text(text: str, kind: Kind) -> Canonical:
    """The shared text pipeline. Records the strongest evidence that applied."""
    evidence = "raw"
    working = text

    # camelCase: a missing space is a formatting accident, not a different name.
    spaced = split_camel(working)
    if spaced != working:
        working, evidence = spaced, "camel"

    # Whitespace, case and diacritics in one pass.
    flattened = strip_marks(working)
    if flattened != working.casefold().strip():
        if evidence == "raw":
            evidence = "diacritic" if _differs_by_marks(working, flattened) else "case"
    working = flattened

    words = working.split()
    if not words:
        return Canonical(raw=text, key="", display=text, kind=kind, evidence="raw")

    if kind == "organization":
        words, stripped = _strip_legal(words)
        if stripped and evidence == "raw":
            evidence = "suffix"
    elif kind == "place":
        joined = " ".join(words)
        trimmed = _POSTAL.sub("", joined)
        if trimmed != joined:
            joined, evidence = trimmed, evidence if evidence != "raw" else "suffix"
        # `New York, NY` and `New York` are one place; `London, Ontario` is not
        # `London`. The tail is dropped only when it is a two-letter code or a country,
        # and only when a real name precedes it, so `NY` alone stays `ny`.
        match = _REGION_TAIL.search(joined)
        if match:
            tail = match.group(1).strip()
            is_code = len(tail) == 2 and tail.isalpha()
            if is_code or tail in _COUNTRY_TAIL:
                without_region = joined[:match.start()].strip()
                if without_region and len(without_region) > 2:
                    joined = without_region
                    if evidence == "raw":
                        evidence = "suffix"
        words = joined.split()
    elif kind == "product":
        if len(words) > 1 and words[0] in ARTICLES:
            words = words[1:]
            if evidence == "raw":
                evidence = "article"
        # `Coca-Cola` and `Coca Cola` are one product. The hyphen is punctuation, not
        # identity, so it is flattened to a space for things only — a person's
        # hyphenated surname must keep it (`Smith-Jones` is not `Smith Jones`).
        words = " ".join(words).replace("-", " ").split()
        if evidence == "raw" and "-" in working:
            evidence = "punctuation"
    else:  # person
        words, stripped = _strip_credentials(words)
        if stripped and evidence == "raw":
            evidence = "credential"
        words, resolved = _resolve_nicknames(words)
        if resolved and evidence == "raw":
            evidence = "nickname"

    key = " ".join(words)
    if not key:
        return Canonical(raw=text, key=strip_marks(text), display=text, kind=kind,
                         evidence="raw")

    return Canonical(raw=text, key=key, display=text, kind=kind, evidence=evidence)


def _differs_by_marks(original: str, flattened: str) -> bool:
    """True when the only difference was accents or invisible marks."""
    return strip_marks(original) == flattened and original.casefold().strip() != flattened


def _same_identity(a: str, b: str | None) -> bool:
    """Do two strings name the same account? Compared on every available form.

    Nicknames are resolved on both sides before comparing, because the Owner is
    recorded under one spelling and may appear in an export under another: the profile
    says `David Sartori`, the export says `Dave Sartori`. Without this the guard is
    inert for exactly the case it exists to catch.
    """
    if not b:
        return False
    if a.casefold().strip() == b.casefold().strip():
        return True
    if strip_marks(a) == strip_marks(b):
        return True
    a_digits, b_digits = phone_digits(a), phone_digits(b)
    if a_digits and b_digits and a_digits == b_digits:
        return True
    if is_email(a) and is_email(b):
        return a.strip().casefold() == b.strip().casefold()
    return _nickname_form(a) == _nickname_form(b)


def _nickname_form(raw: str) -> str:
    """The name with its first token nickname-resolved. Used only for comparison."""
    words = strip_marks(raw).split()
    if not words:
        return ""
    resolved, _ = _resolve_nicknames(words)
    return " ".join(resolved)


# --------------------------------------------------------------------------- fuzzy


@dataclass
class Candidate:
    """A pair that *might* be one entity. Reported, never applied."""

    kind: Kind
    left: str
    right: str
    score: float
    left_key: str
    right_key: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "left": self.left,
            "right": self.right,
            "score": round(self.score, 4),
            "left_key": self.left_key,
            "right_key": self.right_key,
            "reason": self.reason,
        }


def candidates(
    names: Iterable[str],
    *,
    kind: Kind = "person",
    threshold: float = FUZZY_REPORT,
) -> list[Candidate]:
    """Pairs that score high enough to be worth a human look. Nothing is merged.

    The first pass of this pipe writes exact/nickname/diacritic merges and only
    *reports* fuzzy ones, so the first two re-ingests show what fuzzy would have done
    before any threshold is committed to.

    Blocked on the first letter of the surname: comparing every name to every name is
    quadratic, and a surname's first letter is a cheap, safe block for the names this
    app sees.
    """
    if _fuzz is None:
        return []

    seen: dict[str, str] = {}
    for name in names:
        record = canonical(name, kind=kind)
        if not record.key or record.is_placeholder or record.is_owner:
            continue
        seen.setdefault(record.key, record.raw)

    keys = sorted(seen)
    blocks: dict[str, list[str]] = {}
    for key in keys:
        parts = key.split()
        block = parts[-1][:1] if len(parts) > 1 else key[:1]
        blocks.setdefault(block, []).append(key)

    out: list[Candidate] = []
    for block, members in blocks.items():
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                score = _score(left, right)
                if score >= threshold:
                    out.append(Candidate(
                        kind=kind, left=seen[left], right=seen[right],
                        score=score, left_key=left, right_key=right,
                        reason="surname block",
                    ))
    return sorted(out, key=lambda c: -c.score)


def _score(a: str, b: str) -> float:
    """Similarity for two already-canonical keys.

    The surname gate is the important part: `Will Sell` vs `Will Castellanos` scores
    0.72 on `token_sort_ratio` alone, which is a false merge driven by a shared first
    name. Requiring the last token to agree removes that whole class of error.

    Initials are handled before the gate: `david s` vs `david sartori` is a real pair,
    and the gate would reject it because `s` != `sartori`.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _fuzz is None:
        return 0.0

    a_parts, b_parts = a.split(), b.split()
    if len(a_parts) < 2 or len(b_parts) < 2:
        return 0.0

    # Initial: a single-letter last token is a truncation of the other's surname.
    # The trailing dot is punctuation, not part of the initial: `Dave S.` -> `s`.
    a_last, b_last = a_parts[-1].rstrip("."), b_parts[-1].rstrip(".")
    if len(a_last) == 1 or len(b_last) == 1:
        short, long_ = ((a_parts[:-1], a_last), (b_parts[:-1], b_last))
        if len(b_last) == 1:
            short, long_ = (b_parts[:-1], b_last), (a_parts[:-1], a_last)
        if long_[1].startswith(short[1]) and short[0] == long_[0]:
            return 0.90
        return 0.0

    # The surname must agree — exactly, or closely enough to be a typo of the same
    # name. `bromill` vs `bromil` is one person; `sell` vs `castellanos` is not.
    surname = _fuzz.ratio(a_parts[-1], b_parts[-1]) / 100.0
    if surname < 0.92:
        return 0.0

    given = max(_fuzz.ratio(ga, gb) for ga in a_parts[:-1] for gb in b_parts[:-1]) / 100.0
    if given < 0.80:
        return 0.0
    return _fuzz.token_sort_ratio(a, b) / 100.0


# --------------------------------------------------------------------------- constants

# The one definition of "this is not a person". `writer` and `canon` both read it from
# here, so there is no second copy to drift.
PLACEHOLDER_NAMES = frozenset({
    "you",
    "linkedin member",
    "linkedin talent solutions",
    "facebook user",
    "facebook",
    "instagram user",
    "user",
    "unknown",
    "participant",
    "(unknown)",
    "me",
})
