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
single explicit table, and it only maps between names already drawn from `GIVEN`.

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
ABBREVIABLE = {
    "North", "South", "East", "West", "New", "Lower", "Upper", "Greater",
    "Little", "Port", "Fort", "Mount", "Saint", "St",
}

# Short words that should not be initialised (`the` -> `t`).
_MIN_ABBREV_WORD = 3


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
        else:
            raise ValueError(f"unknown fuzz mode {mode!r}")
        if candidate != text:
            return candidate
    return text
