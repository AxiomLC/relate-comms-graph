"""The thread plan. One decision, shared by every writer.

Every mandated shape from `UNDESIRABLES.md` §12 is a **named mark**: a `Thread` with a
`mark` field saying which requirement it satisfies. Ordinary threads are drawn from
`config.MESSAGE_WEIGHTS` and carry no mark.

A mark is present or it is not, and `assert_contract()` says which. Ordinary randomness
never decides whether a required shape appears — that was the bug with the old
`fixtures`/`extremes` split: the edges were a matter of luck in one division and artificial
in the other.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config, dialogue
from .world import Person, World


@dataclass
class Thread:
    key: str
    title: str
    platform: str
    is_group: bool
    participants: list[Person]
    count: int
    owner_replies: bool = True
    start: datetime | None = None
    end: datetime | None = None
    # Which §12 requirement this thread satisfies. "" for ordinary threads.
    mark: str = ""
    # Group members by display name, in message order, for group threads.
    group_lines: list[tuple[str, str]] = field(default_factory=list)
    # (is_owner, body) for 1:1 threads.
    lines: list[tuple[bool, str]] = field(default_factory=list)
    # When each message was sent. Filled by `plan()` from `world.message_times`, so
    # every writer renders one clock and the schedule is irregular (bursts, silences).
    times: list[datetime] = field(default_factory=list)
    # Messenger folder, "" when the platform has no folder concept.
    folder: str = ""
    subject: str = ""
    # §5: a sender name that is not a person (`Facebook user`, `LinkedIn Member`).
    placeholder_sender: str = ""

    @property
    def silent(self) -> bool:
        return self.count == 0


@dataclass
class Plan:
    platform: str
    threads: list[Thread]
    observations: list[str] = field(default_factory=list)

    def marked(self, mark: str) -> list[Thread]:
        return [t for t in self.threads if t.mark == mark]

    def by_folder(self, folder: str) -> list[Thread]:
        return [t for t in self.threads if t.folder == folder]


def _pick(world: World, platform: str, rng: random.Random,
          exclude: set[str] | None = None) -> Person:
    exclude = exclude or set()
    pool = [p for p in world.for_platform(platform) if p.name not in exclude]
    if not pool:
        pool = [p for p in world.people if p.name not in exclude] or list(world.people)
    return pool[rng.randrange(len(pool))]


def _pick_distinct(world: World, platform: str, rng: random.Random,
                   used: set[str]) -> tuple[Person, bool]:
    """A person not yet used on this platform, and whether the name was free.

    A real export cannot hold two 1:1 threads with the same title, and on WhatsApp the
    title IS the thread key — a repeated name silently overwrites a file. When the pool
    runs out the caller disambiguates the title instead.
    """
    pool = [p for p in world.for_platform(platform) if p.name not in used]
    if not pool:
        pool = [p for p in world.people if p.name not in used]
    if pool:
        chosen = pool[rng.randrange(len(pool))]
        used.add(chosen.name)
        return chosen, True
    chosen = world.people[rng.randrange(len(world.people))]
    return chosen, False


def _ordinary_count(rng: random.Random) -> int:
    counts = list(config.MESSAGE_WEIGHTS)
    weights = [config.MESSAGE_WEIGHTS[c] for c in counts]
    return rng.choices(counts, weights=weights, k=1)[0]


# --------------------------------------------------------------------------- marks


def _mark_silent_group(world, platform, rng, observations, used: set[str]) -> Thread | None:
    """§1. A group the Owner never wrote in. Zero owner rows, 3+ other senders."""
    if not config.OWNER_SILENT_GROUPS:
        return None
    lead, _ = _pick_distinct(world, platform, rng, used)
    others = [world.people[rng.randrange(len(world.people))] for _ in range(3)]
    thread = Thread(
        key=f"{platform}:silent-group",
        title="Neighbourhood Watch",
        platform=platform,
        is_group=True,
        participants=[lead, *others],
        count=rng.randint(6, 14),
        owner_replies=False,
        start=world.random_time(rng),
        mark="owner_silent_group",
    )
    observations.append(f"{platform}: owner-silent group ({thread.count} msgs)")
    return thread


def _mark_spam_group(world, platform, rng, observations, used: set[str]) -> Thread | None:
    """§2. Messenger only: >=50% of rows are housekeeping noise, no owner reply."""
    if platform != "messenger" or not config.SPAM_GROUPS:
        return None
    members = [world.people[rng.randrange(len(world.people))] for _ in range(4)]
    thread = Thread(
        key="messenger:spam-group",
        title="Claims Review Group",
        platform=platform,
        is_group=True,
        participants=members,
        count=rng.randint(8, 16),
        owner_replies=False,
        start=world.random_time(rng),
        mark="spam_group",
        folder="filtered_threads",
    )
    observations.append(f"messenger: spam group ({thread.count} msgs, "
                        f"{config.SPAM_GROUP_NOISE_RATIO:.0%} noise)")
    return thread


def _mark_zero_message(world, platform, rng, observations, used: set[str]) \
        -> Thread | None:
    """§6. A thread that exists in the export but yields no messages."""
    if platform not in {"telegram", "whatsapp"} or not config.ZERO_MESSAGE_THREADS:
        return None
    thread = Thread(
        key=f"{platform}:zero-message",
        title="Old Group",
        platform=platform,
        is_group=True,
        participants=[world.people[1], world.people[2]],
        count=0,
        start=world.random_time(rng),
        mark="zero_message",
    )
    observations.append(f"{platform}: zero-message thread")
    return thread


def _mark_service_rows(world, platform, rng, observations, used: set[str]) \
        -> Thread | None:
    """§7. A live thread that also carries service rows — distinct from §6."""
    if platform not in {"telegram", "whatsapp"} or not config.SERVICE_ROW_THREADS:
        return None
    person, _ = _pick_distinct(world, platform, rng, used)
    thread = Thread(
        key=f"{platform}:service-rows",
        title="Trip planning",
        platform=platform,
        # A group on both platforms: `pin_message` and `changed the subject` are group
        # actions, and §7 asks for service rows in a thread that also has real messages.
        is_group=True,
        participants=[person, world.people[3]],
        count=rng.randint(6, 10),
        start=world.random_time(rng),
        mark="service_rows",
    )
    observations.append(f"{platform}: service rows inside a live thread")
    return thread


def _mark_unreplied_1to1(world, platform, rng, observations, used: set[str]) \
        -> Thread | None:
    """§8. A 1:1 the Owner never answered. Must survive exclude_silent_groups."""
    if not config.UNREPLIED_1TO1:
        return None
    person, _ = _pick_distinct(world, platform, rng, used)
    thread = Thread(
        key=f"{platform}:unreplied",
        title=person.name,
        platform=platform,
        is_group=False,
        participants=[person],
        count=rng.randint(1, 3),
        owner_replies=False,
        start=world.random_time(rng),
        mark="unreplied_1to1",
    )
    observations.append(f"{platform}: 1:1 the Owner never replied to")
    return thread


def _mark_big_threads(world, platform, rng, observations, used: set[str],
                      huge: bool) -> list[Thread]:
    """§9. 200 and 500 baked in; 1,600 only with `--huge`."""
    if platform not in {"messenger", "telegram"}:
        return []
    sizes = list(config.BIG_THREADS) + (list(config.HUGE_THREADS) if huge else [])
    made = []
    for size in sizes:
        person, _ = _pick_distinct(world, platform, rng, used)
        mark = "huge_thread" if size >= 1000 else "big_thread"
        made.append(Thread(
            key=f"{platform}:big-{size}",
            title=f"{person.name} ({size})",
            platform=platform,
            is_group=False,
            participants=[person],
            count=size,
            start=world.random_time(rng),
            mark=mark,
        ))
        observations.append(f"{platform}: big thread {size}")
    return made


def _mark_quiet(world, platform, rng, observations, used: set[str]) -> Thread | None:
    """§10. Last message `QUIET_YEARS`+ before the newest message in the export."""
    if not config.QUIET_THREADS:
        return None
    person, _ = _pick_distinct(world, platform, rng, used)
    start = world.start + (world.end - world.start) * 0.05
    thread = Thread(
        key=f"{platform}:quiet",
        title=f"{person.name} (old)",
        platform=platform,
        is_group=False,
        participants=[person],
        count=rng.randint(3, 8),
        start=start,
        mark="quiet",
    )
    observations.append(f"{platform}: quiet thread starting {start:%Y-%m}")
    return thread


def _mark_placeholders(world, platform, rng, observations, used: set[str]) \
        -> list[Thread]:
    """§5. Senders that are not people. Messenger also titles threads with them."""
    names = config.PLACEHOLDER_NAMES.get(platform, [])
    if not names:
        return []
    made = []
    for index in range(config.PLACEHOLDER_THREADS.get(platform, 1)):
        name = names[index % len(names)]
        title = name if platform == "messenger" else f"{name} (sponsored)"
        made.append(Thread(
            key=f"{platform}:placeholder-{index}",
            title=title,
            platform=platform,
            is_group=False,
            participants=[world.people[1]],
            count=rng.randint(1, 4),
            owner_replies=False,
            start=world.random_time(rng),
            mark="placeholder",
            placeholder_sender=name,
        ))
        observations.append(f"{platform}: placeholder '{name}'")
    return made


def _email_boundaries(world: World, rng: random.Random, observations: list[str]) \
        -> list[Thread]:
    """§3 / §3b / §3c. The off-by-one the whole rule turns on."""
    made = []
    sender = _PersonStub(name="Newsletter", email="digest@list.example")
    for count in config.EMAIL_LONG_SILENT:
        made.append(Thread(
            key=f"email:long-silent-{count}",
            title=f"Weekly digest ({count})",
            platform="email",
            is_group=False,
            participants=[sender],
            count=count,
            owner_replies=False,
            start=world.random_time(rng),
            mark="email_long_silent",
            subject="Weekly digest",
        ))
        observations.append(f"email: {count} messages, no reply (must drop)")
    made.append(Thread(
        key="email:boundary-kept",
        title=f"Weekly digest ({config.EMAIL_BOUNDARY_KEPT})",
        platform="email",
        is_group=False,
        participants=[sender],
        count=config.EMAIL_BOUNDARY_KEPT,
        owner_replies=False,
        start=world.random_time(rng),
        mark="email_boundary_kept",
        subject="Monthly digest",
    ))
    observations.append(f"email: {config.EMAIL_BOUNDARY_KEPT} messages, no reply "
                        "(must be kept)")
    made.append(Thread(
        key="email:replied-long",
        title="Invoice thread",
        platform="email",
        is_group=False,
        participants=[world.people[2]],
        count=config.EMAIL_REPLIED_LONG,
        owner_replies=True,
        start=world.random_time(rng),
        mark="email_replied_long",
        subject="Invoice 4471",
    ))
    observations.append("email: long thread with an Owner reply (must be kept)")
    return made


@dataclass
class _PersonStub:
    """A non-person sender (a newsletter list) that looks like a Person to the writers."""
    name: str
    email: str
    phone: str | None = None
    role: str = "newsletter"
    org: str | None = None
    topics: list[str] = field(default_factory=list)
    on: set[str] = field(default_factory=set)
    is_fixed: bool = True

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "")

    def label(self, platform: str) -> str:
        """No per-platform spelling: a newsletter has one name everywhere."""
        return self.name

    def email_for(self, domain: str | None = None) -> str:
        return self.email


# ------------------------------------------------------------------------- messaging


def _messenger_folders(threads: list[Thread], rng: random.Random) -> None:
    """§4. Spread threads across the four folders Messenger writes."""
    folders = ["inbox", "inbox", "inbox", "filtered_threads", "message_requests",
               "e2ee_cutover"]
    for index, thread in enumerate(threads):
        if thread.folder:
            continue                  # already set by a mark
        thread.folder = folders[index % len(folders)]


def _fill_bodies(world: World, thread: Thread, rng: random.Random) -> None:
    """Give a thread its messages. One place, so every writer renders the same dialogue."""
    if thread.silent:
        return

    if thread.mark == "spam_group":
        thread.group_lines = dialogue.noise_lines(thread.count, rng)
        return

    if thread.is_group:
        thread.group_lines = dialogue.group_chatter(
            world, thread.participants, thread.count, rng,
            owner_name=None if not thread.owner_replies else world.owner,
            platform=thread.platform,
        )
        return

    sender = getattr(thread, "placeholder_sender", None)
    if thread.mark == "email_long_silent":
        thread.lines = [(False, body) for body in dialogue.one_sided(thread.count, rng)]
        return
    thread.lines = dialogue.turn_pairs(
        world, thread.participants[0], thread.count, rng,
        polite_open=thread.count > 1,
        owner_replies=thread.owner_replies,
        sender_name=sender,
        platform=thread.platform,
    )


# ---------------------------------------------------------------------------- plan


def plan(world: World, platform: str, rng: random.Random, *, huge: bool = False) -> Plan:
    observations: list[str] = []
    threads: list[Thread] = []

    if platform == "email":
        threads = _email_boundaries(world, rng, observations)
        used: set[str] = set()
        for index in range(config.THREADS_PER_PLATFORM - len(threads)):
            person, fresh = _pick_distinct(world, platform, rng, used)
            threads.append(Thread(
                key=f"email:{person.slug}-{index}",
                title=person.name if fresh else f"{person.name} ({index + 1})",
                platform=platform,
                is_group=False,
                participants=[person],
                count=_ordinary_count(rng),
                start=world.random_time(rng),
                subject=dialogue.subject(person, rng),
            ))
        # §8 and §10 apply to email too — it is a platform like any other.
        for builder in (_mark_unreplied_1to1, _mark_quiet):
            made = builder(world, platform, rng, observations, used)
            if made:
                threads.append(made)
    else:
        # Ordinary threads first, so the marks read as additions to a real mailbox.
        # Each gets a distinct person: duplicate titles overwrite each other on the
        # platforms that derive the thread key from the title (WhatsApp).
        used: set[str] = set()
        for index in range(config.THREADS_PER_PLATFORM):
            person, fresh = _pick_distinct(world, platform, rng, used)
            title = person.name if fresh else f"{person.name} ({index + 1})"
            threads.append(Thread(
                key=f"{platform}:{person.slug}-{index}",
                title=title,
                platform=platform,
                is_group=False,
                participants=[person],
                count=min(config.ORDINARY_THREAD_MAX, _ordinary_count(rng)),
                start=world.random_time(rng),
            ))

        for builder in (_mark_silent_group, _mark_spam_group, _mark_zero_message,
                        _mark_service_rows, _mark_unreplied_1to1, _mark_quiet):
            made = builder(world, platform, rng, observations, used)
            if made:
                threads.append(made)

        threads.extend(_mark_big_threads(world, platform, rng, observations, used, huge))
        threads.extend(_mark_placeholders(world, platform, rng, observations, used))

        if platform == "messenger":
            _messenger_folders(threads, rng)

    for thread in threads:
        _fill_bodies(world, thread, rng)

    for thread in threads:
        if thread.silent:
            continue
        # Message times are decided once, here, so every writer renders the same clock.
        # They arrive in bursts with long silences between them (`world.message_times`),
        # not spread evenly — an even spread made every thread look machine-generated.
        thread.times = world.message_times(thread.start, thread.count, rng)
        thread.end = thread.times[-1] if thread.times else thread.start

    return Plan(platform=platform, threads=threads, observations=observations)


# ------------------------------------------------------------------ contract check


def assert_contract(plans: list[Plan], *, huge: bool = False,
                    world: World | None = None) -> list[str]:
    """Check §12 row by row, and the fuzz knobs. Returns notes; raises on a miss."""
    problems: list[str] = []
    notes: list[str] = []
    by_platform = {p.platform: p for p in plans}

    def require(platform: str, mark: str, label: str) -> None:
        plan_obj = by_platform.get(platform)
        if plan_obj is None:
            return
        if not plan_obj.marked(mark):
            problems.append(f"{platform}: missing {label} (mark '{mark}')")

    for platform in ("telegram", "whatsapp", "messenger"):
        require(platform, "owner_silent_group", "§1 owner-silent group")
    require("messenger", "spam_group", "§2 spam group")
    require("email", "email_long_silent", "§3 long silent email")
    require("email", "email_boundary_kept", "§3b 10-message kept email")
    require("email", "email_replied_long", "§3c replied long email")
    for platform in ("telegram", "whatsapp"):
        require(platform, "zero_message", "§6 zero-message thread")
        require(platform, "service_rows", "§7 service rows in a live thread")
    for platform in by_platform:
        require(platform, "unreplied_1to1", "§8 unreplied 1:1")
        require(platform, "quiet", "§10 quiet thread")
    for platform in ("messenger", "telegram"):
        require(platform, "big_thread", "§9 big thread")

    # §4: all four Messenger folders represented.
    messenger = by_platform.get("messenger")
    if messenger:
        for folder in ("inbox", "filtered_threads", "message_requests", "e2ee_cutover"):
            if not messenger.by_folder(folder):
                problems.append(f"messenger: no thread in '{folder}/' (§4)")

    # §9: nothing above the ordinary cap unless it is a marked big thread.
    for plan_obj in plans:
        for thread in plan_obj.threads:
            if thread.count > 600 and thread.mark != "huge_thread":
                problems.append(
                    f"{plan_obj.platform}: {thread.title} has {thread.count} messages "
                    "but is not a marked big thread (§9)"
                )

    # Duplicate titles are a writer hazard, not a nicety: WhatsApp derives the thread
    # key from the title, so two threads sharing one silently overwrite a file. The one
    # permitted repeat is §5's placeholder titles, which are identical by definition and
    # only occur on Messenger, where the folder name carries the identity.
    for plan_obj in plans:
        seen: dict[str, list[str]] = {}
        for thread in plan_obj.threads:
            seen.setdefault(thread.title, []).append(thread.mark)
        for title, marks in seen.items():
            if len(marks) > 1 and "placeholder" not in marks:
                problems.append(
                    f"{plan_obj.platform}: {len(marks)} threads share the title {title!r}"
                )
    if huge and not any(p.marked("huge_thread") for p in plans):
        problems.append("--huge was requested but no huge thread was planned")

    # Fuzz knobs. A knob that says 2 and silently produces 0 is the failure this
    # generator exists to prevent, so each is checked against what the world holds.
    if world is not None:
        summary = world.fuzz_summary()
        if config.FUZZ_SENDERS_CROSS and summary["cross"] < config.FUZZ_SENDERS_CROSS:
            problems.append(
                f"fuzz: {summary['cross']} cross-platform sender pairs, "
                f"FUZZ_SENDERS_CROSS={config.FUZZ_SENDERS_CROSS}")
        if config.FUZZ_SENDERS_INTRA and summary["intra"] < config.FUZZ_SENDERS_INTRA:
            problems.append(
                f"fuzz: {summary['intra']} intra-platform sender spellings, "
                f"FUZZ_SENDERS_INTRA={config.FUZZ_SENDERS_INTRA}")
        for label, table, knob in (
                ("org", world.body_orgs, config.FUZZ_BODIES_INTRA),
                ("place", world.body_places, config.FUZZ_BODIES_INTRA),
                ("person", world.body_persons, config.FUZZ_BODIES_INTRA)):
            if knob and not table:
                problems.append(f"fuzz: no {label} body variants (FUZZ_BODY_KINDS)")
        notes.extend(config.fuzz_lines(world, summary))

    if problems:
        raise AssertionError("UNDESIRABLES §12 not satisfied:\n  " + "\n  ".join(problems))

    for plan_obj in plans:
        notes.extend(plan_obj.observations)
    return notes


def total_messages(plans: list[Plan]) -> int:
    """Messages that will be written, excluding silent threads."""
    return sum(t.count for plan_obj in plans for t in plan_obj.threads if not t.silent)
