"""The cast, the topics, and the schedule — one seed, one world, one clock.

Everything the writers emit comes from here. That is what makes `Mary Olver` the same
person on WhatsApp and in email, and it is what makes two runs at the same seed
byte-identical.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config

# --------------------------------------------------------------------------- topics

TOPIC_WORDS = {
    "dog": ["the dog", "Biscuit", "the vet", "walkies", "the lead", "kennel"],
    "baseball": ["the game", "the Sox", "the season", "tickets", "the bullpen", "Saturday's match"],
    "cola": ["the Coca-Cola thing", "the Coke account", "the campaign", "the vending machine"],
    "mary": ["Mary Jones", "Mary's birthday", "Mary Jones's place"],
    "abc": ["ABC Corp", "the ABC contract", "the ABC invoice", "their accounts team"],
    "invoice": ["the invoice", "the payment run", "the statement", "the remittance"],
    "weekend": ["the weekend", "Sunday", "the drive up", "the weather"],
    "work": ["the deck", "the review", "the deadline", "the client call"],
}

PEOPLE_ROLES = [
    ("colleague", "ABC Corp"),
    ("client", "ABC Corp"),
    ("supplier", "Northwind Supplies"),
    ("friend", None),
    ("family", None),
    ("recruiter", "Talent Partners"),
    ("landlord", None),
    ("contractor", None),
]

GIVEN = [
    "Mary", "Brandon", "Alexandra", "Lida", "Fred", "Sergio", "Kenny", "Morgan", "Anna",
    "Dimitri", "Priya", "Owen", "Ines", "Tomas", "Hannah", "Rahul", "Clare", "Nadia",
    "Ivo", "Beth", "Marco", "Sofia", "Jonas", "Amara", "Peter", "Yuki", "Fatima",
    "Callum", "Rosa", "Ahmed",
]
SURNAMES = [
    "Olver", "Steinhart", "Lonon", "Geller", "Aaen", "Habegger", "Settens", "Davin",
    "Kowalski", "Petrov", "Nair", "Blythe", "Costa", "Novak", "Whitfield", "Iyer",
    "Mercer", "Haddad", "Ellis", "Ferreira", "Bauer", "Ricci", "Lindqvist", "Okafor",
    "Vance", "Tanaka", "Hassan", "Ross", "Marsh", "Zaman",
]

COMPANIES = ["ABC Corp", "Northwind Supplies", "Talent Partners", "Coca-Cola", "Sox Tickets"]


@dataclass
class Person:
    name: str
    email: str | None
    phone: str | None
    on: set[str]
    role: str
    org: str | None
    topics: list[str]
    is_fixed: bool = False

    @property
    def handle(self) -> str:
        return "".join(ch for ch in self.name.lower() if ch.isalnum())

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "")

    def email_for(self, domain: str | None = None) -> str:
        if domain:
            return f"{self.name.split()[0].lower()}.{self.name.split()[-1].lower()}@{domain}"
        return self.email or f"{self.slug}@example.com"


# ------------------------------------------------------------------------ the world


@dataclass
class World:
    seed: int
    owner: str
    start: datetime
    end: datetime
    people: list[Person] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)

    # --- construction ------------------------------------------------------------

    @classmethod
    def build(cls, seed: int | None = None) -> "World":
        seed = config.SEED if seed is None else seed
        rng = random.Random(seed)
        world = cls(
            seed=seed,
            owner=config.OWNER,
            start=datetime.fromisoformat(config.START),
            end=datetime.fromisoformat(config.END),
            rng=rng,
        )
        world._populate()
        world._assert_contract()
        return world

    def _populate(self) -> None:
        low, high = config.CORRESPONDENTS
        target = self.rng.randint(low, high)

        # The fixed cast, so the names the brief asks for are always present.
        fixed = [
            Person("Mary Jones", "mary.jones@example.com", "+447700900001",
                   {"whatsapp", "sms", "email"}, "family", None,
                   ["mary", "dog", "weekend"], is_fixed=True),
            Person("Mary Olver", "mary.olver@abccorp.example", "+447700900002",
                   {"whatsapp", "email"}, "colleague", "ABC Corp",
                   ["abc", "invoice", "work"], is_fixed=True),
            Person("Brandon Steinhart", "brandon@northwindsupplies.example", "+447700900003",
                   {"telegram", "linkedin"}, "supplier", "Northwind Supplies",
                   ["invoice", "work"], is_fixed=True),
            Person("ABC Corp", "accounts@abccorp.example", "+441134960000",
                   {"email", "linkedin"}, "client", "ABC Corp", ["abc", "invoice"],
                   is_fixed=True),
        ]
        self.people.extend(fixed)

        used = {p.name for p in self.people}
        while len(self.people) < target:
            name = f"{self.rng.choice(GIVEN)} {self.rng.choice(SURNAMES)}"
            if name in used:
                continue
            used.add(name)
            role, org = self.rng.choice(PEOPLE_ROLES)
            topics = self.rng.sample(list(TOPIC_WORDS), k=self.rng.randint(1, 3))
            self.people.append(Person(
                name=name,
                email=f"{name.lower().replace(' ', '.')}@example.com",
                phone=f"+4477009{self.rng.randint(10000, 99999)}",
                on=set(),
                role=role,
                org=org,
                topics=topics,
            ))

        # Presence. Everyone gets at least one platform; only a small share get more
        # than one. The share is drawn over the random cast only — the fixed cast is
        # multi-platform by construction, so including it would push the ratio past the
        # band for reasons that are not a bug.
        platforms = ["whatsapp", "telegram", "messenger", "sms", "linkedin", "email"]
        share = self.rng.uniform(config.CROSS_PLATFORM_MIN, config.CROSS_PLATFORM_MAX)
        random_cast = [p for p in self.people if not p.on]
        multi_count = int(round(len(random_cast) * share))
        order = list(self.people)
        self.rng.shuffle(order)
        for index, person in enumerate(order):
            if person.on:
                continue
            first = self.rng.choice(platforms)
            person.on.add(first)
            if index < multi_count:
                extra = self.rng.choice([p for p in platforms if p != first])
                person.on.add(extra)

    def _assert_contract(self) -> None:
        share = self.multi_platform_share()
        if not (config.CROSS_PLATFORM_MIN <= share <= config.CROSS_PLATFORM_MAX):
            raise AssertionError(
                f"cross-platform share {share:.3f} outside "
                f"{config.CROSS_PLATFORM_MIN}-{config.CROSS_PLATFORM_MAX}"
            )

    # --- queries -----------------------------------------------------------------

    def multi_platform_share(self) -> float:
        """Share of the *random* cast on more than one platform.

        The fixed cast is excluded: it exists to be multi-platform, so counting it would
        measure the brief rather than the generator.
        """
        random_cast = [p for p in self.people if not p.is_fixed]
        if not random_cast:
            return 0.0
        return sum(1 for p in random_cast if len(p.on) > 1) / len(random_cast)

    def for_platform(self, platform: str) -> list[Person]:
        return [p for p in self.people if platform in p.on]

    def topic_words(self, topics: list[str]) -> list[str]:
        words: list[str] = []
        for topic in topics:
            words.extend(TOPIC_WORDS.get(topic, []))
        return words or ["it"]

    # --- time --------------------------------------------------------------------

    def random_time(self, rng: random.Random | None = None) -> datetime:
        rng = rng or self.rng
        span = (self.end - self.start).total_seconds()
        moment = self.start + timedelta(seconds=rng.uniform(0, span))
        # Working-ish hours bias; some night owls, because real exports have them.
        if rng.random() < 0.85:
            moment = moment.replace(
                hour=rng.randint(7, 22), minute=rng.randint(0, 59), second=rng.randint(0, 59)
            )
        return moment

    def message_count(self, rng: random.Random) -> int:
        counts = list(config.MESSAGE_WEIGHTS)
        weights = [config.MESSAGE_WEIGHTS[c] for c in counts]
        return rng.choices(counts, weights=weights, k=1)[0]


def build(seed: int | None = None) -> World:
    return World.build(seed)
