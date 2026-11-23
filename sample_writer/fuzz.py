"""Fuzz — one value, many spellings, from rules rather than a list of variants.

Real downloads spell the same thing differently. One correspondent is `Chris Fowley`
on WhatsApp and `Christopher Fowley` on Telegram; an organisation appears as
`Celestica`, `celestica` and `Celstica`; a place as `North Dakota` and `N Dakota`.
The generator has to manufacture those mismatches so the app's flatten pass has
something to chew on.

WHAT IS A RULE AND WHAT IS A TABLE
----------------------------------
Everything mechanical is a pure function of the string plus a seeded index, so a word
nobody anticipated still gets varied:

    lower / upper / title      `celestica`, `CELESTICA`, `Celestica`
    possessive                 `Celestica's`
    drop_letter                `Celestica` -> `Celstica`
    swap                       `Celestica` -> `Celestcia`
    abbrev                     `North Dakota` -> `N Dakota`

The one thing no rule reaches is a nickname (`Chris` -> `Christopher`): that is a
lexical fact about English, not a transformation of the letters. `NICKNAMES` is the
single explicit table, and it only maps between names already drawn from `FIRST_NAME`.

Nothing here reads config or the world; the caller decides how often to call it. That
keeps it unit-testable on its own and keeps the seeded randomness in one visible place.
"""
from __future__ import annotations

import random

# English given-name nicknames -> the long form. Small on purpose: a wrong guess here
# invents a person who does not exist, so only pairs that are genuinely the same name
# belong. Applied only to a token that is already a name from `world.GIVEN`.
NICKNAMES = {
    "Chris": "Christopher",
    "Christopher": "Chris",
    "Bob": "Robert",
    "Robert": "Bob",
    "Bobby": "Robert",
    "Rob": "Robert",
    "Dave": "David",
    "David": "Dave",
    "Pete": "Peter",
    "Peter": "Pete",
    "Jim": "James",
    "James": "Jim",
    "Bill": "William",
    "William": "Bill",
    "Liz": "Elizabeth",
    "Elizabeth": "Liz",
    "Alex": "Alexander",
    "Alexander": "Alex",
    "Tom": "Thomas",
    "Thomas": "Tom",
    "Dan": "Daniel",
    "Daniel": "Dan",
    "Nick": "Nicholas",
    "Nicholas": "Nick",
}

# Which mechanical forms may appear in a **sender field**. Uppercase and possessive
# are not here: no contact list stores `ALAN WIRTH`, and `Alan Wirth's` is a body
# phrase, not a name. A sender field carries the spelling a person typed, so the only
# believable variants are a different given name (nicknames, handled separately) or a
# mistyping inside the given name (`drop_letter`, `swap`).
SENDER_MODES = ("drop_letter", "swap")

# The mechanical forms, in the order `vary()` prefers when handed no explicit mode.
MECHANICAL = ("plain", "lower", "upper", "possessive", "drop_letter", "swap")

# Short words lose meaning when a letter is removed (`ND` -> `N`), so the destructive
# modes skip anything below this length. A given name is short by nature (4-5 letters
# is normal), so the sender path passes its own, lower floor.
MIN_DESTRUCTIVE_LEN = 6
MIN_NAME_LEN = 4

# Words that are abbreviated to their initial when they qualify a place name:
# `North Dakota` -> `N Dakota`. A rule, not a variant list — any place whose first
# word is one of these gets abbreviated, and the rest of the name is untouched.
#
# **Only the compass words.** `St`, `Saint`, `Port`, `Fort`, `Mount`, `Little`,
# `New`, `Lower`, `Upper`, `Greater` were here too, and every one of them was a bug:
# `canon` expands a single leading `n`/`s`/`e`/`w` and nothing else, so `St Paul` ->
# `S Paul` was folded to `south paul` — a different place, silently. An abbreviation
# is only honest when the flattener can expand it back.
ABBREVIABLE = {"North", "South", "East", "West"}

# Short words that should not be initialised (`the` -> `t`).
_MIN_ABBREV_WORD = 3

# Trailing legal forms an organisation may carry: `Acme` -> `Acme Ltd`. Mirrors
# `canon.LEGAL_SUFFIXES` in shape, not in size — only the forms a body would plausibly
# print, and only ones `canon` strips again.
LEGAL_FORMS = ("Ltd", "Inc", "LLC", "PLC", "GmbH", "Holdings", "Partners")

# Credential suffixes a person's name attracts in a signature block. `canon.CREDENTIALS`
# strips these again; a two-letter one (`CIA`) is the shape the HANDOVER's example uses.
CREDENTIALS = ("CIA", "CPA", "PMP", "PhD", "MBA", "RN")

# Two-letter region codes a place name gets a tail from: `Austin` -> `Austin, TX`.
# Must be a real two-letter code, because `canon` drops the tail ONLY when it is two
# letters or a country name — `Austin, Travis County` would never fold.
REGION_CODES = ("TX", "CA", "NY", "MA", "WA", "IL", "FL", "CO", "OR", "NC")

# US postcode used for the `postal_code` variant. Five digits because `canon._POSTAL`
# matches `\d{4,10}` — a three-digit code would never be stripped.
POSTAL_CODE = "78701"


def lower(text: str) -> str:
    return text.lower()


def upper(text: str) -> str:
    return text.upper()


def possessive(text: str) -> str:
    """`Celestica` -> `Celestica's`. Already-possessive input is left alone."""
    return text if text.endswith(("'s", "\u2019s")) else f"{text}'s"


def drop_letter(text: str, rng: random.Random, *, floor: int = MIN_DESTRUCTIVE_LEN) -> str:
    """Remove one interior letter, never the first or the last, and never a space.

    `Celestica` -> `Celstica`. Kept interior so the result still reads as the same
    word: a dropped first letter is a different kind of typo and a dropped last one
    changes the surname the resolver matches on.

    Never drops from a short word, even inside a long string: `the Bay Area` must not
    become `the ay Area`, which is a broken word rather than a misspelling.
    """
    words = text.split(" ")
    eligible = [i for i, word in enumerate(words)
                if len(word.strip(",.()")) >= floor]
    if not eligible:
        return text
    index = rng.choice(eligible)
    word = words[index]
    slots = [i for i in range(1, len(word) - 1) if word[i] != " "]
    if not slots:
        return text
    cut = rng.choice(slots)
    words[index] = word[:cut] + word[cut + 1:]
    return " ".join(words)


def swap(text: str, rng: random.Random, *, floor: int = MIN_DESTRUCTIVE_LEN) -> str:
    """Transpose two adjacent letters inside one word: `Celestica` -> `Celestcia`.

    Never across a space: `Callum Lovelace` -> `Callu mLovelace` is not a typo anyone
    makes, and it turns one name into two tokens, which would defeat the surname the
    resolver matches on. Also never inside a word shorter than `floor`.
    """
    words = text.split(" ")
    eligible = [i for i, word in enumerate(words)
                if len(word.strip(",.()")) >= floor]
    if not eligible:
        return text
    index = rng.choice(eligible)
    word = words[index]
    slots = [i for i in range(1, len(word) - 1) if word[i] != " " and word[i + 1] != " "]
    if not slots:
        return text
    cut = rng.choice(slots)
    words[index] = word[:cut] + word[cut + 1] + word[cut] + word[cut + 2:]
    return " ".join(words)


def abbrev(text: str) -> str:
    """Initialise a leading qualifier: `North Dakota` -> `N Dakota`.

    Only words in `ABBREVIABLE` are shortened, and only the rest of the name is left
    alone — initialising every long word gave `N D` for `North Dakota`, which is not
    a spelling anyone writes. `Austin, TX` and `the Bay Area` pass through unchanged,
    because their words are not qualifiers.
    """
    parts = text.split(" ")
    if not parts:
        return text
    core = parts[0].strip(",.()")
    if core in ABBREVIABLE and len(core) > 1:
        parts[0] = parts[0].replace(core, core[0], 1)
    return " ".join(parts)


def nicknamed(name: str) -> str | None:
    """The nickname (or long form) of a given name, or None when there is no pair.

    Only the first token is considered: `Chris Fowley` -> `Christopher Fowley`, with
    the surname untouched, because it is the *combining* evidence a flatten pass uses.
    """
    if not name:
        return None
    first, _, rest = name.partition(" ")
    replacement = NICKNAMES.get(first)
    if not replacement or replacement == first:
        return None
    return f"{replacement} {rest}" if rest else replacement


# --------------------------------------------------- forms `canon` folds, per kind
#
# Each is a pure function of `(text, rng)` returning a spelling `canon` normalises back
# to the same key. The kinds are enforced by the caller (`FUZZ_VARIANTS`), not here.


def legal_suffix(text: str, rng: random.Random) -> str:
    """`Acme` -> `Acme Ltd`. A name already carrying one keeps it (returns unchanged)."""
    tail = text.rsplit(" ", 1)[-1].rstrip(".,")
    if tail in LEGAL_FORMS or any(word in LEGAL_FORMS for word in text.split()):
        return text
    return f"{text} {rng.choice(LEGAL_FORMS)}"


def credentials(text: str, rng: random.Random) -> str:
    """`Steve Mikano` -> `Steve Mikano CIA`. Already-credentialed names pass through."""
    last = text.rsplit(" ", 1)[-1].rstrip(",")
    if last in CREDENTIALS:
        return text
    return f"{text} {rng.choice(CREDENTIALS)}"


def postal_code(text: str, rng: random.Random) -> str:
    """`Austin` -> `Austin 78701`. Skips a name that already ends in digits."""
    if text.rsplit(" ", 1)[-1].isdigit():
        return text
    return f"{text} {POSTAL_CODE}"


def region_tail(text: str, rng: random.Random) -> str:
    """`Austin` -> `Austin, TX`. Only a REAL two-letter code, because that is the only
    tail `canon` drops — `Austin, Travis County` would become a second node."""
    if "," in text or text.rsplit(" ", 1)[-1] in REGION_CODES:
        return text
    return f"{text}, {rng.choice(REGION_CODES)}"


def hyphen(text: str, rng: random.Random) -> str:
    """`Coca Cola` -> `Coca-Cola`; `Coca-Cola` -> `Coca Cola`.

    `canon` flattens the hyphen for products only, so both directions fold to one key.
    """
    if "-" in text:
        return text.replace("-", " ")
    words = text.split(" ")
    if len(words) < 2:
        return text
    cut = rng.randrange(1, len(words))
    return " ".join(words[:cut]) + "-" + " ".join(words[cut:])


def acronym(text: str, rng: random.Random) -> str:
    """`International Business Machines` -> `IBM`.

    **Not a fold.** `canon` keeps `ibm` and `international business machines` as two
    keys, and should: an initialism is not always the same identity. Included because
    real exports do it, and because the *node count* is what is being observed — but a
    second node here is the expected result, not a failed fold.
    """
    if text.isupper():
        return text
    words = [w for w in text.split() if w[:1].isalpha()]
    if len(words) < 2:
        return text
    return "".join(w[0].upper() for w in words)


def _in_word(text: str, rng: random.Random, *, mode: str) -> str:
    """Apply `drop_letter`/`swap` inside the *first* token only.

    A sender field is `Given Surname`, and the surname is the token the resolver keys
    on. Mutilating it (`Olver` -> `lver`) is neither a typo people make nor a fair test
    of a flattener; mangling the given name is both. The surname is left exact.
    """
    first, sep, rest = text.partition(" ")
    if mode == "drop_letter":
        return drop_letter(first, rng, floor=MIN_NAME_LEN) + sep + rest
    return swap(first, rng, floor=MIN_NAME_LEN) + sep + rest


def vary_sender(name: str, rng: random.Random) -> str:
    """One believable alternate spelling of a sender name, or the name itself.

    Only mistypings, and only inside the given name. See `SENDER_MODES`.
    """
    mode = rng.choice(SENDER_MODES)
    return _in_word(name, rng, mode=mode)


def vary(text: str, rng: random.Random, modes: tuple[str, ...] | None = None) -> str:
    """One spelling of `text`, drawn from `modes` (default: every mechanical form).

    The caller decides *whether* to fuzz; this decides *how*. A mode that cannot apply
    to this string is skipped rather than returned unchanged, so asking for a
    `drop_letter` variant of `ND` still produces variety instead of silently doing
    nothing.

    `abbrev` is intentionally absent from `MECHANICAL`: abbreviating an organisation
    name yields collisions (`North Dakota DOT` -> `N D DOT`), so it is opt-in per
    caller via `modes=`.
    """
    choices = modes or MECHANICAL
    for mode in rng.sample(choices, k=len(choices)):
        if mode == "plain":
            return text
        if mode == "lower":
            return lower(text)
        if mode == "upper":
            return upper(text)
        if mode == "possessive":
            return possessive(text)
        if mode == "drop_letter":
            candidate = drop_letter(text, rng)
        elif mode == "swap":
            candidate = swap(text, rng)
        elif mode == "abbrev":
            candidate = abbrev(text)
        elif mode == "nickname":
            candidate = nicknamed(text) or text
        elif mode == "legal_suffix":
            candidate = legal_suffix(text, rng)
        elif mode == "credentials":
            candidate = credentials(text, rng)
        elif mode == "postal_code":
            candidate = postal_code(text, rng)
        elif mode == "region_tail":
            candidate = region_tail(text, rng)
        elif mode == "hyphen":
            candidate = hyphen(text, rng)
        elif mode == "acronym":
            candidate = acronym(text, rng)
        else:
            raise ValueError(f"unknown fuzz mode {mode!r}")
        if candidate != text:
            return candidate
    return text


def pick_variant(text: str, rng: random.Random,
                 variants: tuple[str, ...] | list[str]) -> tuple[str, str | None]:
    """One variant of `text`, retrying until one actually applies.

    A variant that cannot apply must not consume the item's fuzz share: several are
    kind- or name-specific (`abbrev` needs a qualifier word, `legal_suffix` needs a name
    not already carrying one). Walking a shuffled copy means the first that changes
    something wins, and every item still gets a genuinely different spelling.

    Returns `(spelling, applied_variant)`. A total failure returns the input unchanged
    with `None`, which the caller reports — the same rule `config.fuzz_lines()` applies
    to a knob that produces nothing.
    """
    for variant in rng.sample(list(variants), k=len(variants)):
        candidate = vary(text, rng, (variant,))
        if candidate != text:
            return candidate, variant
    return text, None
