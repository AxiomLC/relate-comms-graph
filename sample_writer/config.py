"""sample_writer — every knob, in one place.

The writers read this module; nothing else configures them. Change a number and the next
run produces different data. Nothing in `relate_comms/` or `app/` changes, ever.

Shape requirements come from `UNDESIRABLES.md` §12. These knobs control *size and
flavour*; the mandated-shape counts control whether a required shape exists at all.

Run:
    python -m sample_writer                  # wipe out/, write every platform
    python -m sample_writer --platform sms   # wipe & write only SMS
    python -m sample_writer --seed 7         # wipe & write, seed 7
    python -m sample_writer --huge           # wipe & write + 1,600-message thread
    python -m sample_writer add --seed 5     # write alongside out/ (name (1) on clash)
    python -m sample_writer append           # same world, later END
    python -m sample_writer clean            # wipe out/
    python -m sample_writer capture          # in/ -> schemas/*.json (shape refs)

`append` extends a world's clock so incremental ingest can be tested: set `END` to a past
date, build and ingest, set `END` back, then `append` and ingest again. See README
§"append" for the cycle and why the seed comes from the saved schedule.
"""
from __future__ import annotations

from pathlib import Path

# 1. FOLDERS ---------------------------------------------------------------

HERE = Path(__file__).resolve().parent
IN_DIR = HERE / "in"            # real downloads to imitate; read-only, gitignored
OUT_DIR = HERE / "out"          # generated fake downloads; drop into Ingest
SCHEMA_DIR = HERE / "schemas"   # captured shape references; committed

# 2. WORLD CONTRACT --------------------------------------------------------

SEED = 20261114                 # default world; --seed overrides
OWNER = "Mark Jones"            # the account holder; never fuzzed, never a Correspondent

# The world's calendar. Quiet threads need to be 3+ years older than the newest message
# (§10), so the window is deliberately longer than the data it carries.
START = "2024-06-01"
END = "2026-11-25"              # set to a past date, then `append`, to test delta ingest

# Cast size. Must exceed each platform's thread count, or `_pick_distinct` falls back to
# people who are not on that platform and CORR_MULTI_PLATFORM stops meaning anything.
CORRESPONDENTS = (260, 340)     # (min, max) people in the world

# 3. PLATFORMS -------------------------------------------------------------

# Written in this order. Dropping a name skips that platform entirely.
PLATFORMS = (
    "email",
    "telegram",
    "whatsapp",
    "messenger",
    "linkedin",
    "sms",
    "outlook",
)

# Which shapes to write per platform, under out/<platform>/<artifact>.
# `zip` and `dir` both exist where the adapter branches on is_dir(); `web` and `html` are
# WhatsApp's two dialects; `json_app` is a deliberate negative case (must report
# unrecognised).
VARIANTS = {
    "email": ("eml",),
    "telegram": ("bulk", "single"),
    "whatsapp": ("web", "html"),
    "messenger": ("zip", "dir"),
    "linkedin": ("zip", "dir"),
    "sms": ("xml", "xml_zip", "json_app"),
    "outlook": ("copy",),
}

# 4. MESSAGE VOLUME --------------------------------------------------------

# Ordinary threads per platform, before the mandated shapes are added. Each platform rolls
# its own count within ±THREADS_JITTER, because a real mailbox is lumpy.
AVG_THREADS_PER_PLATFORM = 25
THREADS_JITTER = 0.4            # half-width of the band; 0.4 = 15..35 at an average of 25

# Message-count weights for ordinary threads. 2-12 dominates; long threads are rare.
MESSAGE_WEIGHTS = {
    1: 4, 2: 16, 3: 20, 4: 18, 5: 14, 6: 12, 7: 8, 8: 6, 9: 4,
    10: 3, 11: 2, 12: 2, 13: 1, 14: 1, 20: 1, 30: 1,
}

# Sentences per message body. Most are one short line; the tail is what makes a
# message-length view interesting.
BODY_SENTENCES_WEIGHTS = {1: 55, 2: 30, 3: 15}

# No ordinary thread above this, so the big ones stay identifiable by size.
ORDINARY_THREAD_MAX = 60

# 5. THREAD TIMING ---------------------------------------------------------

# Messages arrive in bursts with long silences between them, never evenly spaced.
TIMING_BURSTS = (1, 5)          # (min, max) bursts of activity in one thread
TIMING_SPAN_DAYS = 730          # how far after START the last burst may land

# 6. MANDATED SHAPES -------------------------------------------------------

# Each is a count. 0 disables the shape; the contract check reports it rather than
# failing silently, so a disabled shape is visible in the build log.
OWNER_SILENT_GROUPS = 1         # §1  per group platform
SPAM_GROUPS = 1                 # §2  messenger only
SPAM_GROUP_NOISE_RATIO = 0.5    # §2  must be >= messenger.SPAM_NOISE_RATIO
EMAIL_LONG_SILENT = (11, 12)    # §3  message counts that must drop
EMAIL_BOUNDARY_KEPT = 10        # §3b the count that must not
EMAIL_REPLIED_LONG = 12         # §3c
ZERO_MESSAGE_THREADS = 1        # §6  telegram + whatsapp
SERVICE_ROW_THREADS = 1         # §7  a live thread that also has service rows
UNREPLIED_1TO1 = 1              # §8  must survive exclude_silent_groups
QUIET_THREADS = 1               # §10 per platform
QUIET_YEARS = 3                 # §10 minimum age gap

# §9 big threads. Four platforms, not two: people keep one thread open for years on
# Telegram, Messenger, WhatsApp and SMS alike. LinkedIn and mail start a new thread per
# subject, so they do not carry one.
BIG_THREAD_PLATFORMS = ("telegram", "messenger", "whatsapp", "sms")
BIG_THREAD_COUNT = (3, 7)       # (min, max) big threads in the whole world
BIG_THREAD_RANGE = (150, 520)   # (min, max) message count
BIG_THREAD_LOW_WEIGHT = 2.0     # lower half of the range is this much more likely
HUGE_THREADS = (1600,)          # §9b opt-in only, via --huge

# 7. PLACEHOLDER SENDERS ---------------------------------------------------

# Names real exports contain that are not people. Each writer drops these in as senders;
# messenger also uses them as thread titles.
PLACEHOLDER_NAMES = {
    "messenger": ["Facebook user"],
    "linkedin": ["LinkedIn Member", "LinkedIn Talent Solutions"],
    "sms": ["(Unknown)", "Me"],
}
PLACEHOLDER_THREADS = {"messenger": 3, "linkedin": 1}

# 8. FUZZ ------------------------------------------------------------------

# Every percentage is a share of the WHOLE population of that kind, rolled independently.
# A roll never conditions on an earlier one. The Owner is never fuzzed.

# Correspondents: sender display names.
CORR_FUZZY = 0.07               # share spelled one alternate way
CORR_MULTI_PLATFORM = 0.15      # share appearing on 2+ platforms

# Bodies: how often each kind is chosen for a body line. A share, not a count — the draw
# is weighted by share x pool size, so a bigger list is not penalised. 0 stops that kind
# being named at all; the pool stays in the world.
BODY_ENTITY_SHARE = {"org": 1.0, "place": 0.7, "product": 1.6}

BODY_FUZZY = 0.15               # share of items spelled an alternate way
BODY_MULTI_MENTION = 0.07       # share named 2+ times on ONE platform
BODY_MULTI_PLATFORM = 0.06      # share named on 2+ platforms
MENTIONS_MULTI = (2, 5)         # (min, max) mentions for a multi-mention item

# Entity lines forced into the opening of every thread. This, not the pool size, sets how
# often a name reaches the corpus: total slots are AVG_THREADS_PER_PLATFORM x this.
BODY_ENTITY_LINES = 4

# One sender, two spellings inside ONE export. A shape of its own, not implied above.
FUZZ_SENDERS_INTRA = 4
FUZZ_SENDERS_INTRA_PLATFORMS = ("whatsapp", "telegram", "messenger")

# Which kinds a body may name. `person` is documented but NOT wired: a person drawn from
# a body competes with the Correspondent already on the thread.
FUZZ_BODY_KINDS = ("org", "place", "product", "person")

# Variants per kind. Uniform — each is 1/len(list), so the row is 100% by construction and
# there is no weight table to keep in sync (§5).
FUZZ_VARIANTS = {
    "corr": ["lower", "upper", "drop_letter", "swap", "nickname", "credentials"],
    "org": ["lower", "upper", "drop_letter", "swap", "legal_suffix", "acronym"],
    "place": ["lower", "upper", "drop_letter", "swap", "abbrev", "postal_code",
              "region_tail"],
    "product": ["lower", "upper", "drop_letter", "swap", "hyphen"],
    # Physical goods do not hyphenate: `Mazda-CX-5` is not a spelling anyone writes.
    "product_durable": ["lower", "upper", "drop_letter", "swap"],
    "product_food": ["lower", "upper", "drop_letter", "swap"],
}

# 9. APPEND ----------------------------------------------------------------

# `append` re-runs the same world with a later END, reusing the clock saved beside out/ so
# every existing message keeps its timestamp and therefore its key. Two rolls decide what
# the new stretch contains; length, entities and mentions come from the knobs above.
APPEND_THREAD_SHARE = 0.25      # share of EXISTING threads that gain messages
APPEND_NEW_THREAD_SHARE = 0.15  # share of NEW threads added to the world
APPEND_MESSAGES = (1, 4)        # (min, max) messages a thread that grows gains

# 10. FLAVOUR TOGGLES ------------------------------------------------------

WRITE_MESSY_VARIANTS = True     # wrong filename / double extension variants
INCLUDE_MEDIA_ROWS = True       # `<Media omitted>`, photo rows alongside text
INCLUDE_SERVICE_ROWS = True     # "joined_telegram", "You created group", ...
SUBJECT_ON_LINKEDIN = True
SUBJECT_ON_EMAIL = True


def fuzz_lines(world, summary: dict[str, object]) -> list[str]:
    """The build log's report of what the fuzz knobs produced.

    Printed rather than silent so a knob set to 0, or one the cast was too small to
    satisfy, is visible in the run output instead of being discovered from the data.
    Each line gives the share **requested** beside the count **achieved**, because at
    these defaults only about a third of the items flagged ever reach a body.
    """
    total = summary.get("corr_total") or 1
    lines = [
        (f"fuzz: corr fuzzy={summary.get('corr_fuzzy', 0)}/{CORR_FUZZY:.0%} "
         f"multi-platform={summary.get('corr_multi_platform', 0)}/"
         f"{CORR_MULTI_PLATFORM:.0%} of {total}"),
        (f"fuzz: senders intra={summary.get('intra', 0)}/"
         f"{FUZZ_SENDERS_INTRA * len(FUZZ_SENDERS_INTRA_PLATFORMS)} "
         f"on {', '.join(FUZZ_SENDERS_INTRA_PLATFORMS)}"),
    ]
    for kind in ("org", "place", "product", "person"):
        stats = summary.get(kind)
        if not isinstance(stats, dict):
            continue
        lines.append(
            f"fuzz: bodies {kind:<8} items={stats['items']} "
            f"fuzzy={stats['fuzzy']}/{BODY_FUZZY:.0%} "
            f"mention={stats['multi_mention']}/{BODY_MULTI_MENTION:.0%} "
            f"platform={stats['multi_platform']}/{BODY_MULTI_PLATFORM:.0%}")
    lines.append("fuzz: outlook is a copied .pst, so its bodies cannot be fuzzed")
    return lines
