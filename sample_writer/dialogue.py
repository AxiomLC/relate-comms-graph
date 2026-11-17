"""Bodies that read like dialogue, built from topic pools rather than an LLM.

The rules are deliberately dumb and deterministic: an opener, then alternating turns
where a question gets an answer, a statement draws a short acknowledgement, and every
so often a topic word from the cast's interests is dropped in.
"""
from __future__ import annotations

import random

from .world import Person, World

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


def _fill(template: str, topics: list[str], rng: random.Random) -> str:
    return template.format(topic=rng.choice(topics), when=rng.choice(WHEN))


def _is_question(text: str) -> bool:
    return text.rstrip().endswith("?")


def turn_pairs(world: World, person: Person, count: int, rng: random.Random,
               *, polite_open: bool = True, owner_replies: bool = True,
               sender_name: str | None = None) -> list[tuple[bool, str]]:
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

    while len(out) < count:
        roll = rng.random()
        if roll < 0.30:                     # question
            body = _fill(rng.choice(QUESTIONS), topics, rng)
        elif roll < 0.72:                   # statement
            body = _fill(rng.choice(STATEMENTS), topics, rng)
        elif roll < 0.86:                   # short acknowledgement
            body = rng.choice(ACKS)
        elif roll < 0.92:                   # smalltalk that names a person
            body = rng.choice(SMALLTALK)
        elif roll < 0.96:
            body = rng.choice(LINKS)
        else:
            body = rng.choice(CLOSERS)

        # A question must draw an answer, not another question, most of the time.
        if _is_question(last_body) and rng.random() < 0.75:
            body = _fill(rng.choice(STATEMENTS), topics, rng)

        out.append((owner_turn, body))
        last_body = body

        if rng.random() < 0.72:
            owner_turn = not owner_turn
        if len(out) == count - 1 and rng.random() < 0.5:
            out.append((not owner_turn, rng.choice(CLOSERS)))
            break
    return out[:count]


def spam_turns(count: int, rng: random.Random) -> list[str]:
    """One-sided spam: the same sender repeating variations, no owner reply."""
    return [rng.choice(SPAM) for _ in range(count)]


def subject(person: Person, rng: random.Random) -> str:
    topics = person.topics
    choice = rng.randrange(5)
    if choice == 0:
        return f"Re: {rng.choice(topics).capitalize()}"
    if choice == 1:
        return f"{rng.choice(topics).capitalize()} - quick question"
    if choice == 2:
        return "Invoice attached"
    if choice == 3:
        return f"{person.org or person.name} - {'update' if rng.random() < 0.5 else 'follow up'}"
    return ""


def group_chatter(world: World, members: list[Person], count: int,
                  rng: random.Random, *, owner_name: str | None = None) \
        -> list[tuple[str, str]]:
    """(sender_name, body) for a group chat, rotating through `members`.

    `owner_name=None` means the Owner never speaks in this group — the §1 shape. The
    rotation then never lands on a name that would read as the Owner.
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
        lines.append((member.name, body))
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
