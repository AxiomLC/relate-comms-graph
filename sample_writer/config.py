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
START = "2022-01-01"
END = "2026-11-01"

CORRESPONDENTS = (60, 120)       # (min, max) random cast size
CROSS_PLATFORM_MIN = 0.08        # 8-12% of the random cast appears on >1 platform
CROSS_PLATFORM_MAX = 0.12
BODY_OVERLAP_MAX = 0.05          # body mentions stay rare and never make edges

# --------------------------------------------------------------- message volume

# Ordinary threads per platform. Each platform then adds its mandated shapes on top.
THREADS_PER_PLATFORM = 20

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
    "whatsapp": ("chat_txt", "underscore", "bare", "html"),
    "messenger": ("zip", "dir"),
    "linkedin": ("zip", "dir"),
    # `sms_json_app` is a negative case: a different Android app's shape, which the app
    # should report unrecognised. Keep it to prove "we do not guess".
    "sms": ("xml", "xml_zip", "json_app"),
    "outlook": ("copy",),
}

# --------------------------------------------------------------- flavour toggles

WRITE_MESSY_VARIANTS = True   # wrong filename / double extension variants
INCLUDE_MEDIA_ROWS = True     # `<Media omitted>`, photo rows alongside text
INCLUDE_SERVICE_ROWS = True   # "joined_telegram", "You created group", ...
SUBJECT_ON_LINKEDIN = True
SUBJECT_ON_EMAIL = True
