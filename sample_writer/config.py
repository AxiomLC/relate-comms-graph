"""sample_writer — every knob, in one place.

This module is the whole configuration surface. The writers read it; nothing else
configures them. Change a number here and the next run produces different data — that is
the point of the tool. Nothing in `relate_comms/` or `app/` needs to change, ever.

Shape requirements come from `UNDESIRABLES.md` §12. The knobs below control *size and
flavour*; the `MARK_*` knobs control whether a required shape is present at all.

Run:
    python -m sample_writer                  # wipe out/, write every platform
    python -m sample_writer --platform sms   # wipe & write only SMS
    python -m sample_writer --seed 7         # wipe & write, seed 7
    python -m sample_writer --huge           # wipe & write + 1,600-message thread
    python -m sample_writer add --seed 5     # write alongside out/ (name (1) on clash)
    python -m sample_writer clean            # wipe out/
    python -m sample_writer capture          # in/ -> schemas/*.json (shape refs)
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- folders

HERE = Path(__file__).resolve().parent
IN_DIR = HERE / "in"      # real downloads to imitate. Read-only, gitignored.
OUT_DIR = HERE / "out"    # generated fake downloads. Drop these into Ingest.
SCHEMA_DIR = HERE / "schemas"   # captured shape references, committed

# ------------------------------------------------------------------- world contract

SEED = 20261114
OWNER = "Mark Jones"
# Quiet threads need to be 3+ years older than the newest message (UNDESIRABLES §10),
# so the window is deliberately longer than the data it carries.
START = "2024-01-01"
END = "2026-11-01"

CORRESPONDENTS = (60, 120)       # (min, max) random cast size
CROSS_PLATFORM_MIN = 0.05        # 8-12% of the random cast appears on >1 platform
CROSS_PLATFORM_MAX = 0.08
BODY_OVERLAP_MAX = 0.05          # body mentions stay rare and never make edges

# --------------------------------------------------------------- message volume

# Ordinary threads per platform. Each platform then adds its mandated shapes on top.
THREADS_PER_PLATFORM = 25

# Message-count weights for ordinary threads. 2-12 dominates; long threads are rare.
# The mandated shapes (below) are added regardless of this distribution.
MESSAGE_WEIGHTS = {
    1: 4, 2: 16, 3: 20, 4: 18, 5: 14, 6: 12, 7: 8, 8: 6, 9: 4,
    10: 3, 11: 2, 12: 2, 13: 1, 14: 1, 20: 1, 30: 1,
}

# --------------------------------------------------------- mandated shapes (§12)

# Each is a count. 0 disables the shape; the contract check reports it rather than
# failing silently, so a disabled shape is visible in the build log.

OWNER_SILENT_GROUPS = 1          # §1  per group platform
SPAM_GROUPS = 1                  # §2  messenger only
SPAM_GROUP_NOISE_RATIO = 0.5     # §2  must be >= messenger.SPAM_NOISE_RATIO
EMAIL_LONG_SILENT = (11, 12)     # §3  message counts that must drop
EMAIL_BOUNDARY_KEPT = 10         # §3b the count that must not
EMAIL_REPLIED_LONG = 12          # §3c
ZERO_MESSAGE_THREADS = 1         # §6  telegram + whatsapp
SERVICE_ROW_THREADS = 1          # §7  a live thread that also has service rows
UNREPLIED_1TO1 = 1               # §8  must survive exclude_silent_groups
BIG_THREADS = (200, 500)         # §9  baked in
HUGE_THREADS = (1600,)           # §9b opt-in only, `--huge`
QUIET_THREADS = 1                # §10 per platform
QUIET_YEARS = 3                  # §10 minimum age gap

# §9: no ordinary thread above this, so the big ones stay identifiable by size.
ORDINARY_THREAD_MAX = 60

# --------------------------------------------------------- placeholder senders (§5)

# Names real exports contain that are not people. Each writer drops these in as senders;
# `messenger` also uses them as thread titles.
PLACEHOLDER_NAMES = {
    "messenger": ["Facebook user"],
    "linkedin": ["LinkedIn Member", "LinkedIn Talent Solutions"],
    "sms": ["(Unknown)", "Me"],
}
PLACEHOLDER_THREADS = {"messenger": 3, "linkedin": 1}

# ------------------------------------------------------------------------ platforms

# Written in this order. Dropping a name from this tuple skips that platform entirely.
PLATFORMS = (
    "email",
    "telegram",
    "whatsapp",
    "messenger",
    "linkedin",
    "sms",
    "outlook",
)

# Which shapes to write per platform. `out/<platform>/<artifact>`.
#
# `messenger` and `linkedin` offer both a zip and a loose directory because the adapters
# branch on `is_dir()` — two code paths, so both are worth generating. `whatsapp` offers
# text and HTML because the app reads both dialects and the User chooses what to ingest.
VARIANTS = {
    "email": ("eml",),
    "telegram": ("bulk", "single"),
    "whatsapp": ("web", "html"),
    "messenger": ("zip", "dir"),
    "linkedin": ("zip", "dir"),
    # `sms_json_app` is a negative case: a different Android app's shape, which the app
    # should report unrecognised. Keep it to prove "we do not guess".
    "sms": ("xml", "xml_zip", "json_app"),
    "outlook": ("copy",),
}

# ----------------------------------------------------------- body & label fuzz knobs
#
# Real downloads name the same organisation, place and person differently, on
# different platforms and even inside one export. These knobs say how many of those
# mismatches the build must contain. 0 disables a shape; the contract check reports a
# disabled shape rather than silently dropping it.
#
# **The Owner is never fuzzed.** The owner is the app's user and every writer emits
# their one exact spelling. Only the correspondent label and message bodies vary.

# --- sender fields: the correspondent label
# One person, two spellings of their name. `FUZZ_SENDERS_INTRA` is how many such
# people appear with two spellings *inside one export*; the platforms it uses are
# pinned below so the build is predictable, and `FUZZ_SENDER_INTRA_RATE` is the
# fallback when you would rather let the seed choose (roughly 15-20% of platforms).
FUZZ_SENDERS_INTRA = 4
FUZZ_SENDERS_INTRA_PLATFORMS = ("whatsapp", "telegram", "messenger")
FUZZ_SENDER_INTRA_RATE = 0.15
# One person, two spellings across two different platforms (`Chris` / `Christopher`).
FUZZ_SENDERS_CROSS = 4

# --- message bodies: organisation, place and person names
# Inside one platform's export. `FUZZ_BODIES_INTRA_PLATFORMS` is roughly half the
# written platforms at the default 7.
FUZZ_BODIES_INTRA = 8
FUZZ_BODIES_INTRA_PLATFORMS = 4
# The same entity spelled differently across two platforms (`N Dakota` / `North Dakota`).
FUZZ_BODIES_CROSS = 6

# Which entity kinds may vary in a body. `Thing` is deliberately excluded.
FUZZ_BODY_KINDS = ("org", "place", "product", "person")

# Abbreviation is places-only: `North Dakota` -> `N Dakota` reads well, while
# `North Dakota DOT` -> `N Dakota DOT` would collide with the un-abbreviated form.
FUZZ_ORG_ABBREV = False

# Sentence count per generated body. A thread mixes 1-sentence acknowledgements with
# 3-sentence paragraphs, which is what real exports look like.
BODY_SENTENCES = (1, 3)

# --------------------------------------------------------------- thread timing
#
# Messages are NOT spread evenly across a thread's life. Real threads arrive in bursts,
# with long silences between them: three messages in one evening, then eight months of
# nothing, then two more. Even spacing made every thread read as machine-generated and
# left the month histogram flat.

TIMING_BURSTS = (1, 5)        # (min, max) bursts of activity in one thread
TIMING_SPAN_DAYS = 730        # how far after `start` the last burst may land (~2 years)

# How many messages a body runs to. A thread mixes one-word acknowledgements with
# two-and-three-sentence paragraphs; the long tail is what makes a message-length
# view interesting.
BODY_SENTENCES_WEIGHTS = {1: 55, 2: 30, 3: 15}


def fuzz_lines(world, summary: dict[str, int]) -> list[str]:
    """The build log's one-line report of what the fuzz knobs produced.

    Printed rather than silent so a knob set to 0, or one the cast was too small to
    satisfy, is visible in the run output instead of being discovered from the data.
    """
    orgs = sum(len(v) for v in world.body_orgs.values())
    places = sum(len(v) for v in world.body_places.values())
    products = sum(len(v) for v in world.body_products.values())
    persons = sum(len(v) for v in world.body_persons.values())
    return [
        # `intra` is per platform, so the denominator is the platform count times the
        # per-platform quota. Printed that way rather than as `4/2`, which read as an
        # over-run when it was exactly on target.
        f"fuzz: senders cross={summary['cross']}/{FUZZ_SENDERS_CROSS} "
        f"intra={summary['intra']}/"
        f"{FUZZ_SENDERS_INTRA * len(FUZZ_SENDERS_INTRA_PLATFORMS)} "
        f"on {', '.join(FUZZ_SENDERS_INTRA_PLATFORMS)}",
        f"fuzz: bodies org={orgs} place={places} product={products} person={persons} "
        f"(kinds={','.join(FUZZ_BODY_KINDS)})",
        "fuzz: outlook is a copied .pst, so its bodies cannot be fuzzed",
    ]

# ------------------------------------------------------------------ flavour toggles

WRITE_MESSY_VARIANTS = True   # wrong filename / double extension variants
INCLUDE_MEDIA_ROWS = True     # `<Media omitted>`, photo rows alongside text
INCLUDE_SERVICE_ROWS = True   # "joined_telegram", "You created group", ...
SUBJECT_ON_LINKEDIN = True
SUBJECT_ON_EMAIL = True
