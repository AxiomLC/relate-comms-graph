"""Bodies that read like dialogue, built from topic pools rather than an LLM.

The rules are deliberately dumb and deterministic: an opener, then alternating turns
where a question gets an answer, a statement draws a short acknowledgement, and every
so often a topic word from the cast's interests is dropped in.
"""
from __future__ import annotations

import random

from .world import ORG_FORMS, PLACES, TOPIC_WORDS, Person, World

# ---------------------------------------------------------------- subject subjects
#
# A subject is Subject -> Predicate -> Result, assembled from three slots rather than
# written out per sentence, so one seed yields hundreds of distinct lines from a few
# dozen words. `SUBJECTS` are noun phrases that read as a *topic of mail*; `PREDICATES`
# say what happened to it, and `RESULTS` say what follows. Not every combination reads
# perfectly English, and that is deliberate: real inboxes do not either.

SUBJECTS = [
    "the invoice", "the contract", "the deck", "the payment run", "the renewal",
    "the migration", "the onboarding call", "the schema change", "the outage",
    "the proposal", "the handover", "the audit", "the estimate", "the statement",
    "the Q3 numbers", "the data pull", "the API key", "the trial", "the ticket",
]
PREDICATES = [
    "is late", "came through", "needs a signature", "is on hold", "was rejected",
    "is ready for review", "got pushed to Friday", "looks fine to me",
    "needs another look", "is stuck with legal", "went out this morning",
    "has a typo on page 2", "is roughly double what we scoped",
]
RESULTS = [
    "can you check it?", "no rush.", "let me know.", "thoughts?",
    "we can pick it up Monday.", "I've attached what I have.", "shout if it's a problem.",
    "happy to jump on a call.", "that's all from me.", "any objection?",
]

# Bodies that name an organisation, split from the place ones: a template is filled
# with exactly one of them, so sharing a list would leave the other slot empty.
ORG_LINES = [
    "{org} finally came back to me.",
    "did you ever hear from {org}?",
    "{org} pushed their deadline again.",
    "I'm at {org} all week.",
    "{org} want the numbers by Friday.",
    "the {org} call is still on?",
    "nothing new from {org}.",
]
PLACE_LINES = [
    "{place} is worse than I remembered.",
    "just landed in {place}.",
    "flying out to {place} next month.",
    "is the {place} office still open?",
    "{place} was a nightmare to get to.",
]

# Bodies that name a colleague. `{person}` uses that person's body-entity spelling, so
# `Bob Mercer` on one platform is `Robert Mercer` on another.
PERSON_LINES = [
    "{person} is picking it up.",
    "did {person} send that over?",
    "{person} said it was fine.",
    "I'll cc {person}.",
    "{person} reckons Monday.",
]

# Sign-offs. `None` means the body simply stops, which is what most chat does.
SIGNOFFS = [
    None, None, None, None,        # no sign-off dominates: weighted by repetition
    "thanks,", "thanks!", "cheers,", "ok", "ok...", "talk later", "speak soon",
    "sincerely,", "best,", "regards,", "ta,", "no worries,", "catch you later",
]

# A bare name is a real sign-off in email — `Bob` on its own line, nothing else.
SIGNOFF_BARE_NAME = True

OPENERS = [
    "hi", "hey", "hello", "morning", "evening", "hiya", "you about?", "quick one",
    "sorry to bother you", "how's it going",
]
QUESTIONS = [
    "did you get my last message?",
    "are you around this week?",
    "what do you reckon?",
    "is that still happening?",
    "can you check {topic} for me?",
    "have you heard back about {topic}?",
    "shall we sort {topic} out?",
    "did {topic} get sorted?",
    "are you free {when}?",
    "could you send that over?",
    "what time works for you?",
    "did the payment go through?",
]
STATEMENTS = [
    "just sent it over.",
    "will do.",
    "got it, thanks.",
    "that's fine by me.",
    "no problem at all.",
    "I'll look at {topic} tonight.",
    "been flat out with {topic}.",
    "talked to {topic} about it already.",
    "should be sorted by {when}.",
    "give me ten minutes.",
    "sorry, only seeing this now.",
    "perfect, thanks.",
    "{topic} can wait until {when}.",
]
ACKS = [
    "ok", "cheers", "ta", "nice one", "sounds good", "great", "cool", "no worries",
    "thanks", "yep", "right you are", "much appreciated",
]
CLOSERS = [
    "speak soon", "thanks again", "cheers", "catch you later", "have a good one",
    "talk {when}", "laters",
]
WHEN = ["tonight", "tomorrow", "Saturday", "Monday", "next week", "the weekend", "this afternoon"]
SMALLTALK = [
    "how's the dog?", "still playing baseball?", "how's Mary Jones doing?",
    "any news on the ABC Corp thing?", "how are the kids?",
]
MEDIA_BODIES = [
    "<Media omitted>", "\u200eimage omitted", "\u200evideo omitted",
    "\u200eContact card omitted", "\u200eGIF omitted",
]
LINKS = [
    "https://example.com/share/1QwqfAd0CRJi4tY",
    "https://example.com/article/invoice-guide",
    "https://example.com/tickets/saturday",
]

# One-liners a spam sender uses. Real spam in real exports is exactly this blunt.
SPAM = [
    "Congratulations! You have been selected for a GBP 1000 reward. Reply WIN to claim.",
    "Your parcel could not be delivered. Reschedule here: example.com/redeliver",
    "Final notice: your account will be suspended unless you verify today.",
    "Earn from home, 4 hours a day, no experience needed. Reply YES.",
    "You have 1 unread voicemail. Call 0800 000 0000 to listen.",
    "Your verification code is 481920. Do not share it with anyone.",
]


def _fill(template: str, topics: list[str], rng: random.Random,
          extras: dict[str, str] | None = None) -> str:
    values = {"topic": rng.choice(topics), "when": rng.choice(WHEN)}
    if extras:
        values.update(extras)
    return template.format(**values)


def entity_line(world: World, platform: str, rng: random.Random,
                *, require_own: bool = False) -> str | None:
    """A body sentence naming an org, place or person — or None if none is available.

    The entity is spelled as `platform` spells it (`world.body_entity`). Entities that
    actually carry a variant for `platform` are preferred, because drawing uniformly
    from every entity made a variant land on its own platform rarely enough that the
    knob's output could not be observed — measured at 0 of 6 variants before this.

    `require_own=True` returns only an entity with a spelling of its own on this
    platform, and None if there is none. A caller that needs the guarantee (the first
    body of a thread) uses that so a decided variant is never left unwritten.
    """
    pools: list[tuple[str, list[str], list[str]]] = []
    if world.body_orgs:
        pools.append(("org", sorted(world.body_orgs), ORG_LINES))
    if world.body_places:
        pools.append(("place", sorted(world.body_places), PLACE_LINES))
    if world.body_persons:
        pools.append(("person", sorted(world.body_persons), PERSON_LINES))
    if not pools:
        return None

    def has_variant(kind: str, canonical: str) -> bool:
        table = {"org": world.body_orgs, "place": world.body_places,
                 "person": world.body_persons}[kind]
        return platform in table.get(canonical, {})

    # Prefer an entity that has a spelling of its own on this platform.
    preferred = [(kind, canonical, lines) for kind, canon, lines in pools
                 for canonical in canon if has_variant(kind, canonical)]
    if require_own:
        if not preferred:
            return None
        kind, canonical, lines = rng.choice(preferred)
    elif preferred and rng.random() < 0.75:
        kind, canonical, lines = rng.choice(preferred)
    else:
        kind, canon, lines = rng.choice(pools)
        canonical = rng.choice(canon)

    if kind == "org":
        return rng.choice(lines).format(org=world.body_entity(canonical, platform))
    if kind == "place":
        return rng.choice(lines).format(place=world.body_entity(canonical, platform))
    return rng.choice(lines).format(person=world.body_entity(canonical, platform))


def _is_question(text: str) -> bool:
    return text.rstrip().endswith("?")


def turn_pairs(world: World, person: Person, count: int, rng: random.Random,
               *, polite_open: bool = True, owner_replies: bool = True,
               sender_name: str | None = None, platform: str = "") \
        -> list[tuple[bool, str]]:
    """Produce `count` (is_owner, body) tuples.

    `is_owner` alternates but is not rigid: runs of two from one side appear, because
    real threads have them (and the Messenger writer needs them for `_2` sections).

    `owner_replies=False` produces a one-sided thread: every row is the correspondent.
    `sender_name` overrides the correspondent's display name, for placeholder senders
    such as `Facebook user` (§5) where the body comes from nobody in particular.
    """
    topics = world.topic_words(person.topics)
    out: list[tuple[bool, str]] = []
    owner_turn = rng.random() < 0.5 and owner_replies
    last_body = ""

    if not owner_replies:
        opener = _fill(rng.choice(OPENERS), topics, rng)
        out.append((False, opener))
        while len(out) < count:
            roll = rng.random()
            if roll < 0.45:
                out.append((False, _fill(rng.choice(QUESTIONS), topics, rng)))
            elif roll < 0.8:
                out.append((False, _fill(rng.choice(STATEMENTS), topics, rng)))
            else:
                out.append((False, rng.choice(SPAM)))
        return out[:count]

    if polite_open and count:
        out.append((owner_turn, _fill(rng.choice(OPENERS), topics, rng)))
        owner_turn = not owner_turn

    # The opening rows of every thread carry entities that have a spelling of their
    # own on this platform, until none are left. Without this guarantee a decided
    # variant could go unwritten, which made the fuzz knob unobservable on a platform
    # (`Tom Ross` was chosen for linkedin and never appeared). Rows 2-4 rather than 1:
    # at the higher quotas there are more entities per platform than one row can hold.
    for _ in range(3):
        if len(out) >= count:
            break
        forced = entity_line(world, platform, rng, require_own=True)
        if not forced:
            break
        out.append((owner_turn, forced))
        owner_turn = not owner_turn

    while len(out) < count:
        roll = rng.random()
        if roll < 0.30:                     # question
            body = _fill(rng.choice(QUESTIONS), topics, rng)
        elif roll < 0.72:                   # statement
            body = _fill(rng.choice(STATEMENTS), topics, rng)
        elif roll < 0.86:                   # short acknowledgement
            body = rng.choice(ACKS)
        elif roll < 0.90:                   # smalltalk that names a person
            body = rng.choice(SMALLTALK)
        elif roll < 0.97:                   # an org, place or colleague by name
            body = entity_line(world, platform, rng) or rng.choice(LINKS)
        else:
            body = rng.choice(CLOSERS)

        # A question must draw an answer, not another question, most of the time.
        if _is_question(last_body) and rng.random() < 0.75:
            body = _fill(rng.choice(STATEMENTS), topics, rng)
        elif not _is_question(body):
            # Short templates get a follow-on sentence at the weighted rate, so a
            # third of messages run to two or three sentences rather than one line.
            body = _extend(body, topics, rng)

        out.append((owner_turn, body))
        last_body = body

        if rng.random() < 0.72:
            owner_turn = not owner_turn
        if len(out) == count - 1 and rng.random() < 0.5:
            out.append((not owner_turn, rng.choice(CLOSERS)))
            break
    return out[:count]


def sentence_count(rng: random.Random) -> int:
    """How many sentences this message runs to, from `BODY_SENTENCES_WEIGHTS`.

    Default is 55/30/15 — most are one short line, but a third of messages carry two
    or three sentences, which is what makes a message-length view worth looking at.
    """
    from .config import BODY_SENTENCES_WEIGHTS

    counts = list(BODY_SENTENCES_WEIGHTS)
    weights = [BODY_SENTENCES_WEIGHTS[c] for c in counts]
    return rng.choices(counts, weights=weights, k=1)[0]


def _extend(body: str, topics: list[str], rng: random.Random) -> str:
    """Append follow-on sentences until `sentence_count` is reached.

    The first sentence is whatever the caller chose; this only makes a short line into
    a two-or-three-sentence message. A follow-on is a statement or a question, never a
    sign-off, so a body does not end `thanks.\n\ncheers`.
    """
    target = sentence_count(rng)
    parts = [body]
    while len(parts) < target:
        parts.append(_fill(rng.choice(STATEMENTS), topics, rng))
    return " ".join(parts)


def spam_turns(count: int, rng: random.Random) -> list[str]:
    """One-sided spam: the same sender repeating variations, no owner reply."""
    return [rng.choice(SPAM) for _ in range(count)]


def subject(person: Person, rng: random.Random) -> str:
    """Subject -> Predicate -> Result.

    Nine of ten subjects state the topic only (`the invoice`); the rest are a whole
    sentence with a sign-off dropped, because a real inbox holds both. A leading `Re:`
    appears when the thread is already running — the caller does not ask for it twice
    (see `email._message`), so it is not generated here.
    """
    roll = rng.random()
    if roll < 0.35:
        return rng.choice(SUBJECTS).capitalize()
    if roll < 0.7:
        return f"{rng.choice(SUBJECTS).capitalize()} - {rng.choice(PREDICATES)}"
    if roll < 0.9:
        return f"{rng.choice(SUBJECTS).capitalize()}: {rng.choice(RESULTS)}"
    # One subject in ten is an org name, because people mail about who it is from.
    return person.org or person.role.capitalize()


def sentence(rng: random.Random, topics: list[str], *,
             extras: dict[str, str] | None = None) -> str:
    """One Subject-Predicate-Result sentence."""
    head = rng.choice(SUBJECTS)
    tail = rng.choice(RESULTS)
    if rng.random() < 0.5:
        return f"{head.capitalize()} {rng.choice(PREDICATES)}."
    return f"{head.capitalize()} {rng.choice(PREDICATES)} - {tail}"


def body(rng: random.Random, topics: list[str], *, signer: str | None = None,
         sentence_range: tuple[int, int] = (1, 3),
         extras: dict[str, str] | None = None) -> str:
    """A message body: 1-3 sentences, an optional sign-off, an optional bare name.

    Length is drawn per message, so a thread mixes one-word acknowledgements with
    three-sentence paragraphs — the spread real exports have, and what makes a
    histogram or a 'longest message' view worth looking at.
    """
    low, high = sentence_range
    count = rng.randint(low, high)
    parts = [sentence(rng, topics, extras=extras) for _ in range(count)]
    if rng.random() < 0.35:
        signoff = rng.choice([s for s in SIGNOFFS if s is not None])
        parts.append(signoff)
        if signer and SIGNOFF_BARE_NAME and rng.random() < 0.4:
            parts.append(signer.split()[0])
    return "\n\n".join(parts)


def org_mention(org: str, rng: random.Random) -> str:
    """One org, spelled one of the ways a body really spells it.

    `plain` / `lower` are the easy flatten case; `drop_letter` (`Celstica`) is the
    hard one the flattener may legitimately miss; `possessive` exercises a trailing
    `'s` that must not become part of the entity name.
    """
    form = rng.choice(ORG_FORMS)
    if form == "lower":
        return org.lower()
    if form == "possessive":
        return f"{org}'s"
    if form == "drop_letter":
        # Drop one interior letter, never the first or last: `Celestica` -> `Celstica`.
        if len(org) > 5:
            cut = rng.randint(2, len(org) - 3)
            return org[:cut] + org[cut + 1:]
    return org


def place_mention(rng: random.Random) -> str:
    return rng.choice(PLACES)


def group_chatter(world: World, members: list[Person], count: int,
                  rng: random.Random, *, owner_name: str | None = None,
                  platform: str = "") -> list[tuple[str, str]]:
    """(sender_name, body) for a group chat, rotating through `members`.

    `owner_name=None` means the Owner never speaks in this group — the §1 shape. The
    rotation then never lands on a name that would read as the Owner.

    A group sender is a sender field, so it carries the person's spelling *for this
    platform*, not their structural `name`.
    """
    lines: list[tuple[str, str]] = []
    for index in range(count):
        member = members[index % len(members)]
        topics = world.topic_words(member.topics)
        roll = rng.random()
        if roll < 0.4:
            body = _fill(rng.choice(QUESTIONS), topics, rng)
        elif roll < 0.8:
            body = _fill(rng.choice(STATEMENTS), topics, rng)
        else:
            body = rng.choice(ACKS)
        # A third of group rows name an entity, so the fuzz reaches group threads too.
        # At a fifth the chance that one *specific* entity landed on its *specific*
        # platform was too low to observe, which made the knob untestable.
        if rng.random() < 0.33:
            body = entity_line(world, platform, rng) or body
        lines.append((member.label(platform) if platform else member.name, body))
    return lines


# The closed housekeeping phrase list Messenger's spam gate matches on. Quoted from
# `relate_comms/adapters/messenger.py` (`SPAM_NOISE_PHRASES`); keep in step with it, or a
# generated "spam" group will not trip the real gate.
NOISE_PHRASES = [
    "sent a link",
    "added {name} to the group",
    "named the group",
    "changed the group photo",
    "joined the group",
    "left the group",
    "created a poll",
]


def noise_lines(count: int, rng: random.Random) -> list[tuple[str, str]]:
    """Housekeeping rows for §2: exactly `SPAM_GROUP_NOISE_RATIO` of them or more.

    The share is computed, not sampled. A coin flip that lands at 45% would leave the
    thread just under `messenger.SPAM_NOISE_RATIO` and the app's gate would not fire —
    the generated "spam group" would then be a lie about what it tests.
    """
    from .config import SPAM_GROUP_NOISE_RATIO

    noise_count = max(1, int(count * SPAM_GROUP_NOISE_RATIO) + 1)
    noise_count = min(count, noise_count)
    lines: list[tuple[str, str]] = []
    for index in range(count):
        sender = f"Member {index % 4 + 1}"
        if index < noise_count:
            phrase = NOISE_PHRASES[index % len(NOISE_PHRASES)]
            lines.append((sender, phrase.format(name=f"Member {rng.randint(1, 9)}")))
        else:
            lines.append((sender, rng.choice(ACKS)))
    rng.shuffle(lines)
    return lines


def one_sided(count: int, rng: random.Random) -> list[str]:
    """Bodies for a thread the Owner never answered (§3): sender only."""
    return [rng.choice(SPAM + ACKS) if rng.random() < 0.3
            else rng.choice(STATEMENTS).format(topic="the newsletter",
                                               when=rng.choice(WHEN))
            for _ in range(count)]
