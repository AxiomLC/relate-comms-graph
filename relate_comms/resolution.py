"""Identity resolution — many platform accounts, one person.

THE ONE RULE THIS FILE OBEYS
----------------------------
§3.1: **two resolution edge types, never one.** A confident match and a guess must be
distinguishable in the graph, or a demo cannot tell them apart and a wrong guess looks
as certain as a fact:

    exact key  (phone in E.164 digits, lowercase email, platform user id) -> 1.0
    fuzzy name (rapidfuzz over normalised display names)                  -> 0.4-0.8

`POSSIBLY` and `MATCHED_BY` are separate edges in the writer. Nothing here touches the
store; this module only produces `Identity` records carrying their evidence.

WHAT REAL PAYLOADS TAUGHT US
----------------------------
1. **`You` is not a name.** WhatsApp writes the literal `You` for the owner. Matching
   `You` to `You` across chats would merge every contact into one person.
2. **Phone formats differ per platform and are unreliable.** One warse export wrote
   `+1 (917) 400-4025`, another `+27 84 518 9029`. Compare digits, never the string.
3. **Some "names" are placeholders.** `LinkedIn Member` (35 rows) and `Facebook user`
   (8,171 rows) are not people. Matching on them merges spam into a fake person.
4. **Volume must never raise confidence.** A spam thread can send thousands of
   messages; only distinct-thread breadth is evidence.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .schema import Identity, IngestResult, Person

# Names that mean "we do not know who this is". Never match on them.
PLACEHOLDER_NAMES = frozenset({
    "you",
    "linkedin member",
    "facebook user",
    "facebook",
    "instagram user",
    "user",
    "unknown",
    "participant",
})

# Anything that looks like a phone number rather than a name.
_PHONE_LIKE = re.compile(r"^\+?[\d\s()\-.]{7,}$")

# rapidfuzz is optional: without it, name matching degrades to exact-only and says so.
try:  # pragma: no cover - import-time capability probe
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover
    _fuzz = None

# Thresholds. Below 0.40 a name match is noise; above 0.80 it is a guess pretending
# to be a fact, which §3.1 forbids.
NAME_MIN = 0.40
NAME_MAX = 0.80
NAME_ACCEPT = 0.72


def phone_match_key(raw: str | None) -> str | None:
    """The part two numbers must share to be the same line.

    `+1 (917) 400-4025` and `917-400-4025` are the same US number; comparing full
    digit strings says they differ (11 vs 10 digits). Whatever the country, the
    subscriber part is the last 9-10 digits, so that is the comparison key.

    Deliberately **not** a parse of country codes: a wrong E.164 guess would merge
    strangers, and we have no library or evidence to do better here.
    """
    digits = norm_phone(raw)
    return digits[-10:] if digits else None


def norm_phone(raw: str | None) -> str | None:
    """Digits only: `+1 (917) 400-4025` -> `19174004025`.

    Comparing formatted strings is how the same number becomes two people.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) >= 8 else None


def norm_email(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().strip(".,;:").lower()
    return value if "@" in value and " " not in value else None


def norm_name(raw: str | None) -> str:
    """Casefold, drop diacritics and invisible marks, collapse spaces."""
    if not raw:
        return ""
    decomposed = unicodedata.normalize("NFKD", raw)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.category(ch).startswith("M"))
    return " ".join(without_marks.casefold().split())


def is_placeholder(name: str | None) -> bool:
    return norm_name(name) in PLACEHOLDER_NAMES


def looks_like_phone(value: str | None) -> bool:
    return bool(value and _PHONE_LIKE.match(value.strip()))


@dataclass
class Candidate:
    """A sender observed during ingest, before any merging."""

    platform: str
    handle: str
    display_name: str = ""
    phone_raw: str | None = None
    email: str | None = None
    is_self: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    threads: set[str] = field(default_factory=set)

    def identity_key(self) -> str:
        """Stable per (platform, handle). One account on one platform."""
        return f"{self.platform}:{self.handle}"


def candidate_from(platform: str, handle: str, **kw) -> Candidate:
    """Build a Candidate, deriving phone/email from the handle when it is one.

    WhatsApp and SMS present the phone number *as* the sender name, so the handle is
    also the best available phone evidence.
    """
    handle = handle.strip()
    phone = kw.pop("phone_raw", None)
    email = kw.pop("email", None)
    display = kw.pop("display_name", handle)

    if phone is None and looks_like_phone(handle):
        phone = handle
    if email is None and "@" in handle:
        email = handle

    return Candidate(platform=platform, handle=handle, display_name=display or handle,
                     phone_raw=phone, email=email, **kw)


def _fuzzy(a: str, b: str) -> float:
    """Name similarity, deliberately conservative.

    `token_sort_ratio` scored `Will Sell` vs `Will Castellanos` at 0.72 — a false
    merge, because a shared first name dominated. Requiring the *last* token to
    agree is what makes a match mean something: in every name format we ingest
    (Western, and `Дарья Саяпинa` alike) the last token is the family name.

    Returns 0.0 when the last tokens disagree, so the caller cannot merge on a
    shared first name alone.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    a_parts, b_parts = a.split(), b.split()
    if len(a_parts) < 2 or len(b_parts) < 2:
        return 0.0        # a single token is not a name we can vouch for
    if a_parts[-1] != b_parts[-1]:
        return 0.0        # family names differ: not the same person

    # Matching surnames are not enough: `Austin Johnson` and `Casey Johnson` share
    # one, and so do thousands of strangers. At least one *given* token must also
    # agree, by fuzzy similarity, before the pair is a candidate at all.
    given_a, given_b = a_parts[:-1], b_parts[:-1]
    if _fuzz is None:
        return 0.0
    given_score = max(_fuzz.ratio(ga, gb) for ga in given_a for gb in given_b) / 100.0
    if given_score < 0.80:
        return 0.0

    return _fuzz.token_sort_ratio(a, b) / 100.0


def _person_key(display_name: str, identity_key: str) -> str:
    """A Person key from the strongest available anchor.

    Deterministic and stable: the same identity always produces the same person key,
    so re-ingest merges rather than duplicates. Never derived from a timestamp or an
    array index (§3.1).
    """
    anchor = norm_name(display_name) or identity_key
    return "person:" + hashlib.sha256(anchor.encode("utf-8")).hexdigest()[:16]


class Resolver:
    """Merge candidates into People. Exact evidence first, then names."""

    def __init__(self) -> None:
        self.people: dict[str, Person] = {}
        self.identities: dict[str, Identity] = {}
        self._by_phone: dict[str, str] = {}
        self._by_email: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self.owner_key: str | None = None
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ public

    def add(self, candidate: Candidate) -> Identity:
        """Register one observed account and return its Identity record."""
        ikey = candidate.identity_key()
        existing = self.identities.get(ikey)
        if existing is not None:
            # Same account appearing in a second export: widen the date window only.
            person = self.people.get(existing.person_key or "")
            if person and candidate.first_seen and candidate.first_seen < person.first_seen_utc:
                person.first_seen_utc = candidate.first_seen
            if person and candidate.last_seen and candidate.last_seen > person.last_seen_utc:
                person.last_seen_utc = candidate.last_seen
            return existing

        if not candidate.is_self and is_placeholder(candidate.handle):
            # Recorded, but attached to a pseudo-person per platform rather than
            # merged into anyone. Spam must not become a contact.
            return self._add_person(
                candidate, person_key=f"placeholder:{candidate.platform}",
                confidence=1.0, matched_by="placeholder",
                display_name=candidate.display_name or candidate.handle,
            )

        if candidate.is_self:
            return self._add_owner(candidate)

        phone = norm_phone(candidate.phone_raw)
        email = norm_email(candidate.email)
        phone_key = phone_match_key(candidate.phone_raw)

        if phone_key and phone_key in self._by_phone:
            return self._attach(ikey, candidate, self._by_phone[phone_key], 1.0, "phone")
        if email and email in self._by_email:
            return self._attach(ikey, candidate, self._by_email[email], 1.0, "email")

        name = norm_name(candidate.display_name)
        if name and name in self._by_name:
            # A name is evidence, never proof of identity: two people can share one.
            # Capped at NAME_MAX so the edge renders as POSSIBLY, not MATCHED_BY.
            return self._attach(ikey, candidate, self._by_name[name], NAME_MAX,
                                "exact_name")

        best_key, best_score = self._best_name_match(name)
        if best_key is not None:
            score = min(NAME_MAX, max(NAME_MIN, best_score))
            if score >= NAME_ACCEPT:
                return self._attach(ikey, candidate, best_key, score, "fuzzy_name")

        # Nobody matched: this account starts a new Person.
        key = _person_key(candidate.display_name, ikey)
        return self._add_person(candidate, person_key=key, confidence=1.0,
                                matched_by="new", display_name=candidate.display_name)

    def finish(self) -> tuple[list[Person], list[Identity]]:
        if _fuzz is None:
            self.warnings.append(
                "rapidfuzz is not installed: fuzzy name matching degraded to "
                "exact-only, so cross-platform name matches will be missed")
        return list(self.people.values()), list(self.identities.values())

    # ---------------------------------------------------------------- internals

    def _best_name_match(self, name: str) -> tuple[str | None, float]:
        if not name or is_placeholder(name):
            return None, 0.0
        best_key, best = None, 0.0
        for known, person_key in self._by_name.items():
            if is_placeholder(known):
                continue
            score = _fuzzy(name, known)
            if score > best:
                best_key, best = person_key, score
        return best_key, best

    def _add_owner(self, candidate: Candidate) -> Identity:
        if self.owner_key is None:
            self.owner_key = "owner"
            self.people[self.owner_key] = Person(
                key=self.owner_key,
                display_name=candidate.display_name or "Me",
                first_seen_utc=candidate.first_seen or _epoch(),
                last_seen_utc=candidate.last_seen or _epoch(),
            )
        return self._attach(candidate.identity_key(), candidate, self.owner_key,
                            1.0, "owner")

    def _add_person(
        self,
        candidate: Candidate,
        *,
        person_key: str,
        confidence: float,
        matched_by: str,
        display_name: str,
    ) -> Identity:
        if person_key not in self.people:
            self.people[person_key] = Person(
                key=person_key,
                display_name=display_name,
                first_seen_utc=candidate.first_seen or _epoch(),
                last_seen_utc=candidate.last_seen or _epoch(),
            )
        return self._attach(candidate.identity_key(), candidate, person_key,
                            confidence, matched_by)

    def _attach(
        self,
        ikey: str,
        candidate: Candidate,
        person_key: str,
        confidence: float,
        matched_by: str,
    ) -> Identity:
        phone = norm_phone(candidate.phone_raw)
        email = norm_email(candidate.email)

        identity = Identity(
            key=ikey,
            platform=candidate.platform,
            handle=candidate.handle,
            phone_e164=phone,
            email=email,
            display_name=candidate.display_name,
            person_key=person_key,
            confidence=confidence,
            matched_by=matched_by,
        )
        self.identities[ikey] = identity

        # Index this account so later candidates can find the person it belongs to.
        if phone:
            self._by_phone.setdefault(phone_match_key(phone) or phone, person_key)
        if email:
            self._by_email.setdefault(email, person_key)
        name = norm_name(candidate.display_name)
        if name and not is_placeholder(name):
            self._by_name.setdefault(name, person_key)

        person = self.people.get(person_key)
        if person:
            if candidate.first_seen and candidate.first_seen < person.first_seen_utc:
                person.first_seen_utc = candidate.first_seen
            if candidate.last_seen and candidate.last_seen > person.last_seen_utc:
                person.last_seen_utc = candidate.last_seen
        return identity


def _epoch() -> datetime:
    from datetime import timezone
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def resolve(
    candidates: Iterable[Candidate],
) -> tuple[list[Person], list[Identity], list[str]]:
    """Merge candidates into (people, identities, warnings). Order-independent:

    Candidates are sorted before merging so two runs over the same data produce the
    same Person keys, even though dict iteration order differs.
    """
    resolver = Resolver()
    ordered = sorted(candidates, key=lambda c: (c.platform, c.handle))
    for candidate in ordered:
        resolver.add(candidate)
    people, identities = resolver.finish()
    return people, identities, resolver.warnings


def sent_edges(
    result: IngestResult,
    identities: Iterable[Identity],
) -> list[tuple[str, str]]:
    """`(person_key, message_key)` for every message with a known author.

    Lives here, not in the writer, so authorship is decided in exactly one place.
    A row with no sender (a system notice) gets no SENT edge rather than a guess.
    """
    by_identity = {i.key: i.person_key for i in identities if i.person_key}
    edges: list[tuple[str, str]] = []
    for message in result.messages:
        handle = (message.sender_name or "").strip()
        if not handle:
            continue
        person_key = by_identity.get(f"{message.platform}:{handle}")
        if person_key:
            edges.append((person_key, message.key))
    return edges


def collect(result: IngestResult) -> list[Candidate]:
    """Every sender in a parsed result, as one Candidate per (platform, handle).

    `threads` counts *distinct chats*, never message volume — a spam thread with
    thousands of rows is one thread.
    """
    by_handle: dict[str, Candidate] = {}
    for message in result.messages:
        if not message.sender_name:
            continue
        handle = message.sender_name.strip()
        if not handle:
            continue
        candidate = by_handle.get(handle)
        if candidate is None:
            candidate = candidate_from(
                result.platform, handle,
                is_self=message.is_self,
                first_seen=message.ts_utc,
                last_seen=message.ts_utc,
            )
            by_handle[handle] = candidate
        candidate.threads.add(message.chat_id)
        if message.ts_utc < (candidate.first_seen or message.ts_utc):
            candidate.first_seen = message.ts_utc
        if message.ts_utc > (candidate.last_seen or message.ts_utc):
            candidate.last_seen = message.ts_utc
        # Self-ness is sticky: one row from the owner makes the account the owner.
        candidate.is_self = candidate.is_self or message.is_self

    return list(by_handle.values())


def merge(
    candidates: Iterable[Candidate],
    *,
    persisted: Iterable[Identity] = (),
) -> tuple[list[Person], list[Identity]]:
    """`resolve()` plus identities carried over from a previous ingest.

    A second run over a different platform must merge into the people the first run
    created, so persisted identities are replayed through the resolver *before* the
    new candidates.
    """
    resolver = Resolver()
    for identity in sorted(persisted, key=lambda i: (i.platform, i.handle)):
        resolver.add(candidate_from(
            identity.platform, identity.handle,
            display_name=identity.display_name,
            phone_raw=identity.phone_e164,
            email=identity.email,
            is_self=identity.person_key == "owner",
        ))
    for candidate in sorted(candidates, key=lambda c: (c.platform, c.handle)):
        resolver.add(candidate)
    people, identities = resolver.finish()
    return people, identities
