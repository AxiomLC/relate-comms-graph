"""Email. A tree of `.eml` files shaped like what Gmail and Hostinger return over IMAP.

There is no download to imitate — `email_imap.detect()` returns False by design. The unit
is one RFC 5322 message per file, with the headers the adapter reads (`From`, `To`,
`Subject`, `Date`, `Message-ID`, `In-Reply-To`, `References`).

**Subject chaining matters.** The adapter derives a thread key from the subject chain, so
follow-ups carry `Re:` and every message in a thread shares `References`. §3's boundary
cases (11 and 12 messages must drop, 10 must be kept) are decided by message count versus
owner rows, so the counts must be exact — the writer never adds a courtesy reply.
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from random import Random

from .. import config
from ..plan import Plan, Thread
from ..world import World

KIND = "email"
DOMAIN = "mail.example.com"
OWNER_ADDRESS = f"mark.jones@{DOMAIN}"


def _moment(thread: Thread, index: int, total: int):
    """When message `index` was sent.

    Uses `thread.times`, which `plan()` fills from `world.message_times` in bursts.
    Falls back to an even split only if a thread somehow has no schedule — never the
    normal path, since an even split is the flat shape this generator removed.
    """
    if thread.times and index < len(thread.times):
        return thread.times[index]
    start = thread.start
    end = thread.end or start
    return start + (end - start) * (index / max(1, total - 1))


def _message(thread: Thread, world: World, is_owner: bool, body: str, index: int,
             rng: Random) -> EmailMessage:
    person = thread.participants[0]
    # A display name in `From`/`To` is a sender field, so the platform spelling is
    # used. The address stays derived from the structural name, so the mailbox of a
    # person does not change when their display name does.
    label = person.label("email")
    address = person.email_for("abccorp.example" if person.org else None)
    msg = EmailMessage()
    if is_owner:
        msg["From"] = f"{world.owner} <{OWNER_ADDRESS}>"
        msg["To"] = f"{label} <{address}>"
    else:
        msg["From"] = f"{label} <{address}>"
        msg["To"] = f"{world.owner} <{OWNER_ADDRESS}>"
    subject = thread.subject or thread.title
    msg["Subject"] = subject if index == 0 else (
        subject if subject.lower().startswith("re:") else f"Re: {subject}"
    )
    msg["Date"] = format_datetime(_moment(thread, index, thread.count))
    root = f"<{abs(hash((thread.key, 0)))}@{DOMAIN}>"
    msg["Message-ID"] = f"<{abs(hash((thread.key, index)))}@{DOMAIN}>"
    msg["References"] = root
    if index > 0:
        msg["In-Reply-To"] = f"<{abs(hash((thread.key, index - 1)))}@{DOMAIN}>"
    msg.set_content(body)
    return msg


def write_eml(plan: Plan, world: World, out_dir: Path, rng: Random,
              filer) -> Path:
    """A saved mailbox: `Inbox/<thread>/NNN.eml` and `Sent/<thread>/NNN.eml`.

    The two top folders are not decoration. `email_imap._parse_raw` decides ownership
    structurally — a message in a folder whose path segment is `Sent` is the Owner's —
    and `folder_is_sent()` is the only signal a saved mailbox has that a live IMAP
    server states outright. Writing a flat `<thread>/NNN.eml` tree meant that branch
    could never fire, so the generated sample exercised the address-match fallback and
    nothing else.

    `parse_eml` walks with `rglob` and passes `entry.parent.name` as the folder, so a
    nested layout is read exactly as IMAP folders are.
    """
    root = filer.dir(out_dir, "email_eml")
    for thread in plan.threads:
        if thread.silent:
            continue
        for index, (is_owner, body) in enumerate(thread.lines):
            folder = root / ("Sent" if is_owner else "Inbox") \
                / thread.key.replace(":", "_")
            folder.mkdir(parents=True, exist_ok=True)
            msg = _message(thread, world, is_owner, body, index, rng)
            (folder / f"{index:03d}.eml").write_bytes(msg.as_bytes())
    return root


WRITERS = {"eml": write_eml}


def write(plan: Plan, world: World, out_dir: Path, filer) -> list[Path]:
    rng = Random(f"{world.seed}:{plan.platform}")
    return [WRITERS[v](plan, world, out_dir, rng, filer) for v in config.VARIANTS[KIND]]
