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
    python -m sample_writer append           # same world, later END (see below)
    python -m sample_writer clean            # wipe out/
    python -m sample_writer capture          # in/ -> schemas/*.json (shape refs)

`append` — testing incremental ingest
--------------------------------------
The app's delta rule skips messages the store already holds, so re-ingesting the same
export writes nothing. To prove it writes the genuinely new ones you need two exports of
ONE world where the second is the first plus a week.

    1. set END below to a past date (e.g. "2025-10-01")
    2. python -m sample_writer --seed 5      # build, then ingest it
    3. set END back to now
    4. python -m sample_writer append        # same world, one more stretch
    5. ingest again — most messages drop as already stored, only the new ones write

The clock is saved to `.schedule.json` BESIDE `out/` (never inside it — `out/` is what
gets staged). `append` reuses it, so every existing message keeps its exact timestamp
and therefore its key. **The seed comes from that file, not from `--seed`**, so a
mismatched flag cannot put a different world on top of the old one. To change the world,
delete `.schedule.json` and run a plain build.

Only a live thread grows (`APPEND_ALIVE_DAYS`); a thread that went quiet stays quiet.
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

# (min, max) random cast size.
#
# **This is what makes `CORR_MULTI_PLATFORM` mean anything.** Each platform needs one
# distinct person per thread, so the world demands ~180 person-platform slots. At a
# 60-120 cast the per-platform pools ran dry (Telegram had 14 people for 29 threads) and
# `_pick_distinct` fell back to anyone in the cast — including people whose `on` set never
# included that platform. Measured: 52 of 95 Correspondents merged against a knob of 8%.
#
# At 300 every platform's pool exceeds its thread count, so the fallback never fires and
# the knob is the only thing that creates a merge. Measured at 300: ~28 merged.
CORRESPONDENTS = (260, 340)

# --------------------------------------------------------------- message volume

# Ordinary threads per platform. Each platform then adds its mandated shapes on top.
#
# **Randomised per platform, not a flat count.** A real mailbox is lumpy: one week you
# open nine new chats, the next you open two. A flat 25 made every platform's thread
# count identical, which no real export has and which made the canvas read as generated.
#
# The average is the knob; each platform rolls its own count within ±30% of it, so the
# total stays predictable while the per-platform shape does not. `THREADS_JITTER` is the
# half-width of that band — 0.3 means 17..32 at an average of 25.
AVG_THREADS_PER_PLATFORM = 25
THREADS_JITTER = 0.4

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
# §9 — the long-running threads. **Four platforms, not two.**
#
# Telegram and Messenger used to be the only platforms that carried a big thread, which
# made "big" read as a property of the platform rather than of the conversation. In a real
# export SMS and WhatsApp carry them just as readily: people keep one thread open for
# years. LinkedIn, email and Outlook do not — LinkedIn is not used for continuous
# personal comms, and mail starts a new thread per subject.
BIG_THREAD_PLATFORMS = ("telegram", "messenger", "whatsapp", "sms")

# How many big threads the whole world gets, and where they land.
BIG_THREAD_COUNT = (3, 7)        # (min, max) rolled once per build
BIG_THREAD_RANGE = (150, 520)    # (min, max) message count

# **Weighted toward the low end.** A 500-message thread is rare; a 150-message one is
# ordinary. `BIG_THREAD_LOW_WEIGHT` is how much more likely the lower half is — 2.0 means
# 150-250 is twice as likely as 250-520. Uniform made every big thread look the same size.
BIG_THREAD_LOW_WEIGHT = 2.0
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

# ------------------------------------------------------------------- fuzz knobs
#
# Each percentage is a share of the WHOLE population of that kind, rolled
# independently. "Fuzzy or otherwise", "multi-platform or not" — a roll never
# conditions on an earlier one. See `README.md` §Fuzz for why that matters.
# **The Owner is never fuzzed.**

# Correspondents: sender display names.
CORR_FUZZY = 0.07            # share spelled one alternate way (uniform per variant)
CORR_MULTI_PLATFORM = 0.15  # share on 2+ platforms; bounds from PLATFORMS

# Bodies: Place, Organization, Product.
#
# **How often each kind is chosen for a body line.** This is a *share*, not a count: the
# draw is weighted by `share x pool size`, so a kind with a bigger list is not penalised
# for it and a kind with a smaller one is not over-represented.
#
# Measured 2026-11-24 on the live store: Place 117, Organization 80, Product 73. A chat
# corpus names cities and companies more readily than products, but not by this much —
# the app is for tech people, who talk about tools and gear far more than about geography.
# So places come down 30% and products come up.
#
# Set a kind to 0 to stop bodies naming it at all; the pool stays in the world, so the
# fuzz report still counts its items.
BODY_ENTITY_SHARE = {"org": 1.0, "place": 0.7, "product": 1.6}

BODY_FUZZY = 0.15            # raised from .07: only ~1/3 of items reach a body
BODY_MULTI_MENTION = 0.07    # named 2+ times on ONE platform
BODY_MULTI_PLATFORM = 0.06   # on 2+ platforms; mention count independent of this
MENTIONS_MULTI = (2, 5)      # (min, max) mentions for a multi-mention item

# How many entity lines are forced into the opening of every thread.
#
# **This, not the pool size, sets how often a name reaches the corpus.** Every thread gets
# up to this many entity rows before the random mixing starts, so the total mention slots
# are `AVG_THREADS_PER_PLATFORM x this`, divided across `ORGS` + `PLACES` + `PRODUCTS`.
#
# Measured 2026-11-24: at 3 with a 586-item pool, roughly **1 body in 12** names an entity,
# and only 25 of 184 product names landed in any body at all. Growing a pool without
# raising this makes every item *rarer* — which is realistic, but it means a bigger list
# buys variety rather than more product nodes.
#
# 4 is the middle: enough that a 184-name product pool is actually exercised, short enough
# that a 2-message thread is not nothing but names.
BODY_ENTITY_LINES = 4

# Upstream spelling mismatches. `FUZZ_SENDERS_INTRA` is a shape of its own — one
# sender, two spellings inside ONE export — and is not implied by the axes above.
FUZZ_SENDERS_INTRA = 4
FUZZ_SENDERS_INTRA_PLATFORMS = ("whatsapp", "telegram", "messenger")

# Which entity kinds a body may name. `person` stays on the list but is documented,
# NOT wired: a person drawn from a body competes with the Correspondent already on
# the thread — a merge with a wrong answer that looks right.
FUZZ_BODY_KINDS = ("org", "place", "product", "person")

# The fuzzy variants per kind. Uniform: each is 1/len(list), so the row is 100% by
# construction and there is no weight table to keep in sync (§5).
FUZZ_VARIANTS = {
    # `acronym` and `legal_suffix` are meaningless for a person's name.
    "corr": ["lower", "upper", "drop_letter", "swap", "nickname", "credentials"],
    "org": ["lower", "upper", "drop_letter", "swap", "legal_suffix", "acronym"],
    "place": ["lower", "upper", "drop_letter", "swap", "abbrev", "postal_code",
              "region_tail"],
    "product": ["lower", "upper", "drop_letter", "swap", "hyphen"],
    # **Physical goods do not hyphenate.** `hyphen` exists for software names that carry
    # one (`Coca-Cola`) or are joined in real writing (`MacBook Pro`); applied to a car it
    # produces `Mazda-CX-5`, which nobody writes and no normaliser should be asked to
    # fold. Everything else about the dice is identical.
    "product_durable": ["lower", "upper", "drop_letter", "swap"],
    "product_food": ["lower", "upper", "drop_letter", "swap"],
}

# --------------------------------------------------------------- thread timing
#
# Messages are NOT spread evenly across a thread's life. Real threads arrive in bursts,
# with long silences between them: three messages in one evening, then eight months of
# nothing, then two more. Even spacing made every thread read as machine-generated and
# left the month histogram flat.

TIMING_BURSTS = (1, 5)        # (min, max) bursts of activity in one thread
TIMING_SPAN_DAYS = 730        # how far after `start` the last burst may land (~2 years)

# ------------------------------------------------------------- append (incremental)
#
# `python -m sample_writer append` re-runs the same world with a later `END` and writes
# it over `out/`. The previous run's clock is read from `out/.schedule.json`, so every
# message that already existed keeps its exact timestamp — and therefore its key — and
# only the new ones are new. That is what makes an incremental ingest testable: the
# delta drops the old week and accepts the new one.
#
# A thread only grows if it was still alive at the end of the previous run. A
# conversation whose last message is months old is over; adding to it would be a thread
# that went silent and then resumed for no reason.
APPEND_ALIVE_DAYS = 30        # a thread whose last message is older than this is done
APPEND_MESSAGES = (1, 4)      # (min, max) messages a live thread gains per append

# How many messages a body runs to. A thread mixes one-word acknowledgements with
# two-and-three-sentence paragraphs; the long tail is what makes a message-length
# view interesting.
BODY_SENTENCES_WEIGHTS = {1: 55, 2: 30, 3: 15}


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

# ------------------------------------------------------------------ flavour toggles

WRITE_MESSY_VARIANTS = True   # wrong filename / double extension variants
INCLUDE_MEDIA_ROWS = True     # `<Media omitted>`, photo rows alongside text
INCLUDE_SERVICE_ROWS = True   # "joined_telegram", "You created group", ...
SUBJECT_ON_LINKEDIN = True
SUBJECT_ON_EMAIL = True
