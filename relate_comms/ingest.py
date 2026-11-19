"""Spool -> store. Parse in parallel, write serialised, verify, then (maybe) prune.

§9.1.4 fixes the shape: `.rl` is one file with one writer, so parsing is the only
part that may run concurrently. Everything downstream is a single ordered queue.

    spool/**  -> detect platform -> parse (process pool) -> write one at a time
              -> verify_present per batch -> prune a file only if verified

FOUR RULES THIS FILE EXISTS TO ENFORCE
--------------------------------------
1. **Detection is by shape, not by folder name.** A user drops whatever the platform
   gave them into the spool. A Telegram export is `result.json` with `chats` or a
   bare chat object; anything unrecognised is **reported and kept**, never guessed
   at and never deleted.
2. **Verify before delete.** A spool file is removed only after every key it produced
   is present in the store. An unverified file stays on disk for inspection —
   §9.1: "Unverified spool files are never pruned."
3. **A file that fails to parse is not a reason to abort the run.** One bad download
   must not stop the other five. It is counted, named in the report, and left alone.
4. **Deterministic order.** Batches are sorted by (platform, path) so two runs over
   the same spool produce the same report and the same write order.

PARALLELISM IS BOUNDED BY THE MACHINE, NOT BY THE FILE COUNT
------------------------------------------------------------
There is no GPU here (TECHREADME.md §9). A process pool of `os.cpu_count()` on a
4P+8E chip would spawn 12 workers to parse 12 JSON files, and the E-cores would
finish the same work slower than 6. `default_workers()` encodes that.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import shutil
import zipfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import identity, manifest, paths, scrub, writer
from .adapters import (email_imap, linkedin, messenger, outlook_pst, sms, telegram,
                       whatsapp, whatsapp_html)
from .schema import IngestResult

# Files this module will consider. Suffix is a cheap filter only; the platform is
# still decided by inspecting the content.
_JSON_SUFFIXES = {".json"}
_ARCHIVE_SUFFIXES = {".zip"}
_TEXT_SUFFIXES = {".txt", ".md"}
# WhatsApp's browser-extension exporter writes standalone `.html` pages.
_HTML_SUFFIXES = {".html"}
_MAIL_SUFFIXES = {".pst", ".ost"}
# A saved mailbox: one RFC 5322 message per file. `sample_writer` writes these, and so
# does any mail client's "Save As". Distinct from `.pst`, which is a paged database.
_EML_SUFFIXES = {".eml"}
# SMS Backup & Restore writes `.xml`, or `.xml.zip` when "compress backup" is on.
_XML_SUFFIXES = {".xml"}
_CONSIDER_SUFFIXES = (_JSON_SUFFIXES | _ARCHIVE_SUFFIXES | _TEXT_SUFFIXES
                      | _MAIL_SUFFIXES | _EML_SUFFIXES | _XML_SUFFIXES
                      | _HTML_SUFFIXES)

# Parse functions by platform. Adding an adapter means adding one line here.
# Parsers that read wall-clock times with no offset. Only these accept
# `tz_offset_hours`; passing it to others (LinkedIn states UTC) is a TypeError, which
# is the correct behaviour — the adapter refuses to be told a lie about its data.
_TZ_AWARE_PLATFORMS = {telegram.PLATFORM, whatsapp.PLATFORM, messenger.PLATFORM}

# Platforms whose adapters accept `exclude_silent_groups`. A group the owner was added
# to and never spoke in is not a conversation they had; the rule is group-scoped, so a
# platform without groups must not be handed the keyword.
_SILENT_GROUP_PLATFORMS = {telegram.PLATFORM, whatsapp.PLATFORM, messenger.PLATFORM}

# Platforms the long-silent-thread spam rule applies to. A mailbox thread the owner
# never replied to and that runs past `SPAM_THREAD_MIN_MESSAGES` is a broadcast, a
# notification chain or a mailing list — the shape spam takes in email. It is NOT the
# group gate: different scope, different threshold, and the two must not be merged.
_SPAM_THREAD_PLATFORMS = {email_imap.PLATFORM, outlook_pst.PLATFORM}
SPAM_THREAD_MIN_MESSAGES = 10

_PARSERS: dict[str, Callable[..., IngestResult]] = {
    telegram.PLATFORM: telegram.parse,
    whatsapp.PLATFORM: whatsapp.parse,
    messenger.PLATFORM: messenger.parse,
    linkedin.PLATFORM: linkedin.parse,
    outlook_pst.PLATFORM: outlook_pst.parse,
    sms.PLATFORM: sms.parse,
    # A saved mailbox (a folder of `.eml`). A live IMAP mailbox is not discoverable
    # and never reaches here — it is fetched by the caller and appended as an
    # `extra_results` entry, which is why `email_imap.fetch` is not in this table.
    email_imap.PLATFORM: email_imap.parse,
}

# WhatsApp has two dialects and one platform key. The parser is chosen per FILE, not
# per platform, because both report `whatsapp` — see `_parser_for`.
_DIALECT_PARSERS: dict[str, Callable[..., IngestResult]] = {
    "whatsapp_html": whatsapp_html.parse,
}


def _parser_for(path: Path, platform: str) -> Callable[..., IngestResult]:
    """The parser for one file. WhatsApp is the only platform with two dialects."""
    if platform == whatsapp.PLATFORM and whatsapp_html.detect(path):
        return _DIALECT_PARSERS["whatsapp_html"]
    return _PARSERS[platform]


def _parse_root(path: Path, platform: str) -> Path:
    """The path an adapter should be handed.

    **A safety net, not the main path.** `discover()` now emits a recognised directory as
    one batch, so a Messenger folder reaches the adapter as a folder. This exists for the
    case where a caller hands a loose `message_N.html` straight to `parse()` — Messenger
    resolves thread ids from the archive-relative path, so a bare file has no thread to
    belong to and would parse the whole export once per file.

    Everything else is handed the path it was discovered as.
    """
    if platform != messenger.PLATFORM or path.suffix.lower() != ".html":
        return path
    for parent in path.parents:
        if parent.name == "your_facebook_activity":
            # The folder *containing* `your_facebook_activity`, so `_thread_members`
            # builds the same relative paths it builds from a zip.
            return parent.parent
    return path

# A file older than this, once verified, may be deleted. Nothing younger is touched,
# so a user who is still copying a download into the spool is never racing us.
PRUNE_AFTER = timedelta(days=3)

# Cap the pool even on a many-core box: parsing is dominated by holding one JSON
# document in memory, not by arithmetic.
MAX_WORKERS = 6

# `[5/22/26, 8:45:50 AM] ` at the start of a WhatsApp text export. Used only to
# detect, never to parse — the adapter owns the real header.
_WA_HEADER = re.compile(r"^\[?\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}", re.MULTILINE)


@dataclass
class Batch:
    """One export file, before it is parsed."""

    path: Path
    platform: str | None       # None => unrecognised
    reason: str = ""           # why it was skipped, if it was

    @property
    def recognised(self) -> bool:
        return self.platform is not None


@dataclass
class BatchOutcome:
    """What happened to one batch. One of these per discovered file."""

    path: str
    platform: str | None
    messages: int = 0
    attachments: int = 0
    verified: bool = False
    pruned: bool = False
    error: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    kinds: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    withheld: str = ""
    fingerprint: str = ""
    correspondents: int = 0

    @property
    def ok(self) -> bool:
        return self.verified and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "platform": self.platform,
            "messages": self.messages,
            "attachments": self.attachments,
            "verified": self.verified,
            "pruned": self.pruned,
            "error": self.error,
            "verification": self.verification,
            "kinds": self.kinds,
            "skipped": self.skipped,
            "withheld": self.withheld,
            "fingerprint": self.fingerprint,
            # Warnings are potentially numerous; the CLI prints them, the JSON
            # summary keeps them so nothing is lost between surfaces.
            "warnings": self.warnings,
        }


@dataclass
class Report:
    """The result of one ingest run. This is what the UI panel renders."""

    store: str
    batches: list[BatchOutcome] = field(default_factory=list)
    unrecognised: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    workers: int = 1
    owner_note: str = ""
    keys: set[str] = field(default_factory=set)
    # platform -> offset actually used. Wall-clock platforms only; a run that fell
    # back to the persisted value says so here rather than looking like a default.
    tz_offsets: dict[str, float] = field(default_factory=dict)
    tz_note: str = ""
    # The profile this run wrote to. Needed by the prune policy, which reads the
    # manifest — and the manifest follows a redirected store.
    profile_dir: str = ""

    @property
    def written(self) -> int:
        """Distinct message keys this run touched.

        Not `sum(b.messages)`: two batches can legitimately contain the same key (a
        bulk export and a single-chat export overlap by design), and summing then
        reports more rows than the store holds. The store merges on the key, so the
        report must count the same thing the store does.
        """
        return len(self.keys)

    @property
    def failed(self) -> list[BatchOutcome]:
        return [b for b in self.batches if b.error]

    @property
    def unverified(self) -> list[BatchOutcome]:
        return [b for b in self.batches if not b.verified and not b.error]

    @property
    def pruned(self) -> list[BatchOutcome]:
        return [b for b in self.batches if b.pruned]

    @property
    def ok(self) -> bool:
        return not self.failed and not self.unverified and not self.unrecognised

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "written": self.written,
            "elapsed_s": round(self.elapsed_s, 3),
            "workers": self.workers,
            "ok": self.ok,
            "batches": [b.to_dict() for b in self.batches],
            "unrecognised": self.unrecognised,
            "tz_offsets": self.tz_offsets,
            "tz_note": self.tz_note,
        }


# --------------------------------------------------------------------- discovery

def default_workers() -> int:
    """P-priented default: leave headroom, never exceed the core count.

    Measured context: `num_thread` is still unmeasured, so this is
    deliberately conservative — parallel parsing must not make a single-file ingest
    slower by stealing cores from the same machine the user is using.
    """
    cores = os.cpu_count() or 1
    return max(1, min(MAX_WORKERS, cores // 2 or 1))


def looks_like_telegram(path: Path) -> bool:
    """Cheap pre-check on the first chunk, before paying for a full JSON load.

    Telegram's JSON is an object whose first key is `about`, `personal_information`,
    `chats` or, for a single-chat export, `name` + `messages`. Reading the head only
    keeps discovery fast over a spool of many large files.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(4096).lstrip()
    except OSError:
        return False
    if not head.startswith("{"):
        return False
    return any(
        marker in head
        for marker in ('"about"', '"personal_information"', '"chats"', '"messages"')
    )


def detect_platform(path: Path) -> str | None:
    """Which adapter owns this path? None means 'unrecognised, report and keep'.

    A **directory** is a valid answer, not just a file: Messenger and Telegram both ship
    a folder tree, and `discover()` needs to know whether to emit the folder as one batch
    or walk into it. Only the adapters that can read a folder are consulted.
    """
    if path.is_dir():
        if messenger.detect(path):
            return messenger.PLATFORM
        if linkedin.detect(path):
            return linkedin.PLATFORM
        # A folder of `.eml` files. Checked before WhatsApp's folder branch because a
        # saved mailbox is a folder of files, not a chat export.
        if email_imap.detect(path):
            return email_imap.PLATFORM
        if whatsapp_html.detect(path):
            return whatsapp.PLATFORM
        # `whatsapp` has no `detect()` of its own — its shape check lives in
        # `_detect_whatsapp`, which reads a `chat.txt` from a zip or a bare text file.
        if _detect_whatsapp(path) is not None:
            return whatsapp.PLATFORM
        # Telegram's folder holds `result.json`; the file branch below handles it once
        # `discover()` has walked in, so a folder is not claimed here.
        return None

    suffix = path.suffix.lower()

    if suffix in _MAIL_SUFFIXES:
        return outlook_pst.PLATFORM if outlook_pst.detect(path) else None

    if suffix in _EML_SUFFIXES:
        return email_imap.PLATFORM if email_imap.detect(path) else None

    if suffix in _XML_SUFFIXES:
        # Only SMS Backup & Restore writes an `.xml` we read. Anything else is
        # reported and kept, never guessed at.
        return sms.PLATFORM if sms.detect(path) else None

    if suffix in {".zip", ".txt", ".md", ".html"}:
        # Zip-shaped platforms, plus the HTML exporter. Detection is by content, never
        # by filename: a user renames downloads.
        if linkedin.detect(path):
            return linkedin.PLATFORM
        if messenger.detect(path):
            return messenger.PLATFORM
        if sms.detect(path):
            return sms.PLATFORM
        # WhatsApp has two dialects: the native `chat.txt` and the browser extension's
        # HTML pages. Both report `whatsapp`, because they are the same platform and
        # the same chat — `_chat_id()` hashes the chat title, so a chat downloaded both
        # ways lands in one Thread.
        if whatsapp_html.detect(path):
            return whatsapp.PLATFORM
        return _detect_whatsapp(path)

    if suffix not in _JSON_SUFFIXES:
        return None
    if looks_like_telegram(path):
        return telegram.PLATFORM
    return None


def _detect_whatsapp(path: Path) -> str | None:
    """A zip holding `chat.txt`, or a text file whose first lines are WA-shaped."""
    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                # WhatsApp packs the chat inside a folder named after the conversation
                # (`WhatsApp Chat with X/chat.txt`), so the member must be matched by
                # basename and then opened by its FULL name. Opening the bare
                # "chat.txt" raises KeyError on every real export.
                members = archive.namelist()
                candidates = [n for n in members
                              if Path(n).name in {"chat.txt", "_chat.txt"}]
                if not candidates:
                    return None
                preferred = [n for n in candidates if Path(n).name == "chat.txt"]
                member = (preferred or candidates)[0]
                with archive.open(member) as handle:
                    head = handle.read(4096).decode("utf-8-sig", errors="replace")
        else:
            head = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
    except (OSError, zipfile.BadZipFile):
        return None

    if _WA_HEADER.search(head):
        return whatsapp.PLATFORM
    if head.lstrip().startswith("{"):
        return None
    return None


def discover(root: Path) -> list[Batch]:
    """Every candidate export under `root`, in deterministic order.

    **A recognised directory is one batch, not one per file inside it.** Messenger and
    Telegram both ship a folder tree, and their adapters resolve thread ids from the
    archive-relative path — so handing them a single `message_1.html` makes each batch
    parse the *whole* export. Measured before this rule: a 29-thread Messenger folder
    produced 29 batches and parsed 18,330 messages to write 611.

    So a directory is offered to `detect_platform()` first. If it is recognised, it is
    emitted once and not descended into. Only an unrecognised directory is walked, which
    is the case for a spool folder holding several unrelated exports.
    """
    found: list[Batch] = []
    if not root.exists():
        return found

    candidates: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            # One batch for the folder when an adapter claims it as a whole.
            if detect_platform(entry) is not None:
                candidates.append(entry)
                continue
            nested = sorted(entry.rglob("*"))
            candidates.extend(p for p in nested if p.is_file()
                              and p.suffix.lower() in _CONSIDER_SUFFIXES)
        elif entry.is_file() and entry.suffix.lower() in _CONSIDER_SUFFIXES:
            candidates.append(entry)

    for path in candidates:
        platform = detect_platform(path)
        found.append(Batch(path=path, platform=platform,
                           reason="" if platform else "unrecognised export shape"))

    found.sort(key=lambda b: ((b.platform or "~"), str(b.path)))
    return found


# ----------------------------------------------------------------------- parsing

def _kwargs_for(platform: str, parse_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keywords this adapter does not accept, instead of failing the whole run.

    LinkedIn's CSV states UTC, so it does not take `tz_offset_hours`. Passing one is
    a programming error, not a data error: the file must still ingest.

    `self_id` needs the same treatment for a different reason. A run resolves the
    owner once from Telegram and puts a Telegram user id in `self_id`; passing that
    to Messenger or LinkedIn matches nothing, so every row silently lands
    `is_self=False`. The id is only meaningful to the platform that produced it.
    """
    trimmed = dict(parse_kwargs)
    owner_platform = trimmed.pop("self_id_platform", None)
    if owner_platform is not None and platform != owner_platform:
        trimmed.pop("self_id", None)

    # `exclude_spam_groups` is Messenger-only: the noise heuristic (`sent a link`,
    # `added X to the group`) is a Facebook shape and means nothing elsewhere.
    if platform != messenger.PLATFORM:
        trimmed.pop("exclude_spam_groups", None)

    # `exclude_silent_groups` is a *group* rule, so it belongs to the three platforms
    # that have groups. Email, LinkedIn, Outlook and SMS have no group concept in the
    # sense the gate means — a group MMS is a thread the owner is a participant in by
    # construction — so the keyword is popped rather than passed as a no-op.
    #
    # `silent_group_platforms` narrows it further: the UI offers one toggle per
    # platform, so a user who leaves Messenger ticked and Telegram unticked must get
    # Telegram's groups. `None` means "all three", which is the CLI's behaviour.
    wanted = trimmed.pop("silent_group_platforms", None)
    if platform not in _SILENT_GROUP_PLATFORMS or (
            wanted is not None and platform not in wanted):
        trimmed.pop("exclude_silent_groups", None)

    # A spool can hold platforms that were exported in different timezones, and the
    # offset is part of every wall-clock key. `tz_offsets` is the per-platform map;
    # it is resolved here so no adapter ever sees it.
    offsets = trimmed.pop("tz_offsets", None)
    if platform not in _TZ_AWARE_PLATFORMS:
        trimmed.pop("tz_offset_hours", None)
    elif isinstance(offsets, dict) and platform in offsets:
        trimmed["tz_offset_hours"] = offsets[platform]
    return trimmed


def _parse_in_worker(payload: tuple[Path, str, dict[str, Any]]) -> tuple[str, Any]:
    """Module-level so it is picklable by the `spawn` process pool.

    Never raises: a failing file comes back as `("error", message)` so one bad
    download cannot abort the batch list. `IngestResult` is made of dataclasses and
    pickles back to the parent unchanged.
    """
    path, platform, parse_kwargs = payload
    try:
        parser = _parser_for(path, platform)
        result = parser(_parse_root(path, platform),
                        **_kwargs_for(platform, parse_kwargs))
    except Exception as exc:  # noqa: BLE001 - report, never crash the run
        return "error", f"{type(exc).__name__}: {exc}"
    return "ok", result


def parse_batches(
    batches: list[Batch],
    *,
    parse_kwargs: dict[str, Any],
    workers: int,
) -> list[tuple[Batch, IngestResult | None, str]]:
    """Parse every batch, in parallel when there is more than one.

    Order of the returned list matches `batches`, regardless of completion order, so
    the write order — and therefore the report — is stable.
    """
    if not batches:
        return []
    if workers <= 1 or len(batches) == 1:
        # Avoid paying pool start-up (spawn re-imports this module) for one file.
        outcomes = []
        for batch in batches:
            status, value = _parse_in_worker(
                (batch.path, batch.platform or "", parse_kwargs))
            outcomes.append((batch, value if status == "ok" else None,
                             "" if status == "ok" else value))
        return outcomes

    payloads = [(b.path, b.platform or "", parse_kwargs) for b in batches]
    with mp.get_context("spawn").Pool(processes=workers) as pool:
        results = pool.map(_parse_in_worker, payloads)

    return [
        (batch, value if status == "ok" else None, "" if status == "ok" else value)
        for batch, (status, value) in zip(batches, results)
    ]


# --------------------------------------------------------------------- the run

def ingest(
    *,
    root: str | Path | None = None,
    which: str = "real",
    store: str | Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    include_service: bool = True,
    exclude_spam_groups: bool = False,
    exclude_silent_groups: bool = False,
    silent_group_platforms: Iterable[str] | None = None,
    exclude_spam_threads: bool = False,
    spam_thread_platforms: Iterable[str] | None = None,
    prune: bool = False,
    prune_after: timedelta = PRUNE_AFTER,
    prune_keep: int | None = None,
    workers: int | None = None,
    self_id: str | None = None,
    profile_dir: str | Path | None = None,
    tz_offset_hours: float | None = None,
    scrub_policy: dict[str, scrub.Verdict] | None | bool = None,
    extra_results: Iterable[IngestResult] = (),
) -> Report:
    """Parse everything in the spool, write it, verify it, and optionally prune.

    `root` is the directory to read; if omitted it is the one spool queue. `which` is
    accepted for compatibility and no longer selects a second queue — see `paths.py`.

    `store` redirects the graph. **The profile follows it** unless `profile_dir` is
    given explicitly — a throwaway store must not write its manifest or tz offsets
    into the live `store/profile/`.

    `prune=False` is the default everywhere. Deleting a spool file is a user
    decision (§9.1.3: `prune` needs `confirm=true`), and the CLI gates it the same
    way the tool layer does.

    `prune_keep` is the "keep the last N ingests" policy. `None` means the age rule
    (`prune_after`); `0` means keep nothing; `1` keeps the newest run's files. It is
    applied **after** the whole run, not per batch, because "the last ingest" is a
    property of the run rather than of a file.
    """
    if since is not None and since.tzinfo is None:
        raise ValueError("since must be timezone-aware")
    if until is not None and until.tzinfo is None:
        raise ValueError("until must be timezone-aware")

    # The folder shape is part of the product: a fresh clone must have somewhere to
    # drop a file before anything is ingested. Created here rather than at install
    # time, so a user who deletes a folder gets it back on the next run.
    paths.ensure_layout()

    if root is None:
        # One queue. `which` is kept as a parameter because the CLI and the tool layer
        # pass it, but both values now mean the same directory: a sample is just a file
        # dropped in the spool, and `ingest` cannot tell it from a real export. Re-ingest
        # is idempotent, so the queue is read whole — never "most recent only", which
        # would silently skip a file and hide a bug.
        root = paths.real_dir()
    root = Path(root)

    store_path = Path(store) if store else paths.store_path()
    # A caller that redirects the store almost always means "a throwaway store", and
    # the profile must follow it. Without this, every test that passed `store=tmp/x.rl`
    # still wrote its manifest and tz offsets into the REAL `store/profile/` — 27
    # entries from pytest temp dirs accumulated in the live `ingested.json`, and the
    # live tz offsets could be overwritten by a test.
    #
    # An explicit `profile_dir` still wins, so a caller can separate them on purpose.
    if profile_dir is not None:
        profile = Path(profile_dir)
    elif store is not None:
        profile = store_path.parent / "profile"
    else:
        profile = paths.profile_dir()

    workers = default_workers() if workers is None else max(1, workers)

    report = Report(store=str(store_path), workers=workers, profile_dir=str(profile))
    started = time.perf_counter()

    # One alias map for the whole run: the same phone must get the same alias across
    # every platform, or the graph splits one person into three.
    aliases = scrub.AliasMap()

    batches = discover(root)
    report.unrecognised = [str(b.path) for b in batches if not b.recognised]
    batches = [b for b in batches if b.recognised]

    extra_results = list(extra_results)
    if not batches and not extra_results:
        report.elapsed_s = time.perf_counter() - started
        return report

    parse_kwargs: dict[str, Any] = {
        "since": since,
        "until": until,
        "include_service": include_service,
        "profile_dir": profile,
    }
    if self_id:
        parse_kwargs["self_id"] = self_id

    # The offset is part of every key on a wall-clock platform, so it is persisted
    # per platform and reused when the caller does not state one. Without this a
    # later `verify_ingest` / `prune_spool` re-parses at 0 and reports every row
    # missing — the store would look broken when it is only being read differently.
    tz_offsets: dict[str, float] = {}
    for platform in sorted({b.platform for b in batches if b.platform}):
        if platform not in _TZ_AWARE_PLATFORMS:
            continue
        # `None` means "not stated": reuse what this account was parsed with.
        # `0` means "these times are UTC" and is a real instruction, so it must not
        # be confused with the default — that is how a re-ingest at 0 used to
        # silently keep the old -5.
        if tz_offset_hours is not None:
            # An empty store has nothing to duplicate, so a different offset is
            # allowed there. That is the normal case while the app is being built:
            # wipe graph.rl, re-ingest, no complaint.
            try:
                identity.save_tz_offset(
                    profile, platform, tz_offset_hours,
                    allow_change=not _store_has_rows(store_path),
                )
            except ValueError as exc:
                report.tz_note = str(exc)
                raise ValueError(str(exc)) from exc
            tz_offsets[platform] = float(tz_offset_hours)
            continue
        stored = identity.load_tz_offset(profile, platform)
        if stored is not None:
            tz_offsets[platform] = stored
            report.tz_note = (
                f"{platform}: reusing persisted tz offset {stored:g} "
                "(pass tz_offset_hours to change it)"
            )
        else:
            tz_offsets[platform] = 0.0

    if tz_offsets:
        # Per platform, not per run: `_kwargs_for` resolves the map for each batch,
        # so a spool holding two timezones parses correctly in one pass.
        parse_kwargs["tz_offsets"] = tz_offsets
    report.tz_offsets = tz_offsets

    # Multi-file runs resolve the owner once, up front. Letting each worker infer
    # it independently would reopen the per-file `is_self` bug (§9.2) for the first
    # run, when nothing is persisted yet.
    #
    # The resolved id is a *Telegram* id (`user1426445212`). Handing it to Messenger
    # or LinkedIn makes every row is_self=False, because those platforms use display
    # names, not Telegram user ids. Only Telegram accepts a self_id inferred this way;
    # every other adapter resolves its own owner from its own export.
    if len(batches) > 1 and "self_id" not in parse_kwargs:
        resolved, note = _resolve_owner_once(batches, profile)
        if resolved:
            parse_kwargs["self_id"] = resolved
            parse_kwargs["self_id_platform"] = telegram.PLATFORM
        if note:
            report.owner_note = note

    # `exclude_spam_groups` is Messenger-only and `exclude_silent_groups` covers the
    # three group platforms; `_kwargs_for` pops whichever an adapter cannot take, so
    # both are set unconditionally here. `silent_group_platforms` narrows the group
    # gate to the platforms the user actually ticked.
    if exclude_spam_groups:
        parse_kwargs["exclude_spam_groups"] = True
    if exclude_silent_groups:
        parse_kwargs["exclude_silent_groups"] = True
        if silent_group_platforms is not None:
            parse_kwargs["silent_group_platforms"] = set(silent_group_platforms)

    parsed = parse_batches(batches, parse_kwargs=parse_kwargs, workers=workers)

    # Live mailboxes arrive already parsed: email is the one platform with no file to
    # drop (§5.3.1), so it is fetched by the caller and appended here. Giving it a
    # synthetic `Batch` keeps it in the same serialised write path as everything else.
    for extra in extra_results:
        parsed.append((Batch(path=Path(extra.export_path), platform=extra.platform),
                       extra, ""))

    # The long-silent-thread rule runs here, not inside an adapter, because IMAP hands
    # rows over one FETCH at a time — a thread is only countable once the whole mailbox
    # has been read. It is a post-pass over the parsed rows, before anything is written,
    # so a dropped thread still leaves no orphan messages.
    if exclude_spam_threads:
        for _batch, result, _error in parsed:
            if result is not None:
                _drop_spam_threads(result, spam_thread_platforms)

    # One connection, one writer, in discovery order. Concurrent writers to one `.rl`
    # is corruption, not a speed-up (§9.1.4).
    conn = writer.connect(store_path)
    try:
        for batch, result, error in parsed:
            outcome = BatchOutcome(path=str(batch.path), platform=batch.platform)
            if error or result is None:
                outcome.error = error or "parse produced no result"
                report.batches.append(outcome)
                continue

            outcome.kinds = dict(result.unknown_kinds)
            outcome.skipped = dict(result.skipped)
            outcome.warnings = list(result.warnings)

            # §3.2: scrub, then write. The scrub gate runs before anything lands.
            #
            # Identity resolution used to run here too and its result was discarded —
            # `resolution.collect/merge` produced `Person` nodes that were never
            # written. That scaffolding is gone: `Person` is a future extraction node
            # type, not the Owner, and the Owner is now excluded by `canon` at the
            # point a Correspondent is minted.
            if scrub_policy is not False:
                result, scrub_report, aliases = scrub.scrub_result(
                    result, policy=scrub_policy or None, aliases=aliases)
                outcome.withheld = scrub_report.summary()

            try:
                written = writer.write(conn, result, owner=parse_kwargs.get("self_id"))
            except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the rest
                outcome.error = f"write failed: {type(exc).__name__}: {exc}"
                report.batches.append(outcome)
                continue

            # §5.6: the thread's counterparty, straight from the export's participant
            # list. After `write()` because `WITH` needs the Thread row to exist.
            #
            # The Owner guard needs **every** form the Owner is known by on this
            # platform, not just `self_id`. A Telegram user id matches no display name,
            # which is why the old single-form guard let the Owner through on four of
            # five platforms. `_owner_forms()` collects the display name, the id, the
            # address and the phone from the profile and from this result.
            try:
                counted = writer.write_correspondents(
                    conn, result,
                    owner=parse_kwargs.get("self_id"),
                    owner_forms=_owner_forms(profile, result, parse_kwargs),
                )
                outcome.correspondents = counted["correspondents"]
            except Exception as exc:  # noqa: BLE001 - never fail the batch over this
                outcome.warnings.append(
                    f"correspondents not written: {type(exc).__name__}: {exc}")

            outcome.messages = written["messages"]
            report.keys.update(written["keys"])
            outcome.attachments = written["attachments"]

            ok, verification = writer.verify_present(conn, result)
            outcome.verified = ok
            outcome.verification = verification

            # Recorded only after verification said yes. A file that did not fully
            # land must not be remembered, or the next run would skip a parse that
            # never actually wrote anything.
            if ok:
                try:
                    digest = manifest.fingerprint(batch.path)
                    manifest.record(
                        profile, digest,
                        platform=batch.platform or "unrecognised",
                        path=str(batch.path),
                        messages=written["messages"],
                        threads=len(result.chats),
                        bytes_=batch.path.stat().st_size,
                    )
                    outcome.fingerprint = digest
                except OSError as exc:
                    outcome.warnings.append(f"not recorded in the manifest: {exc}")

            # The age rule is per batch: a file is old or it is not. The "keep the
            # last N" rule is per RUN and is applied below, once every batch has
            # landed — a file cannot know whether it belongs to the newest run until
            # the run is over.
            if prune and prune_keep is None and ok and _older_than(batch.path, prune_after):
                try:
                    batch.path.unlink()
                    outcome.pruned = True
                    _remove_empty_parents(batch.path, root)
                except OSError as exc:
                    outcome.warnings.append(f"verified but not pruned: {exc}")

            report.batches.append(outcome)
    finally:
        conn.close()

    if prune and prune_keep is not None:
        _prune_keep_last(report, root, prune_keep)

    report.elapsed_s = time.perf_counter() - started
    return report


def _prune_keep_last(report: Report, root: Path, keep: int) -> None:
    """Delete verified spool files from all but the newest `keep` ingests.

    "Ingest" here means a **run**, and a run is identified by the files it touched.
    The manifest already records `ingested_at` per file, so the newest runs are the
    distinct timestamps in it, newest first. A file whose timestamp is not among the
    newest `keep` is deleted — but only if this run verified it, because an unverified
    file is never pruned.

    `keep=0` deletes everything verified. A file with no manifest entry (never
    recorded, or recorded before the manifest existed) is left alone: it cannot be
    placed in a run, and guessing is worse than keeping.
    """
    from . import manifest

    # The profile this RUN used, not the global one. `ingest()` may have been given a
    # throwaway store, in which case its manifest lives beside that store — reading the
    # global profile here would find nothing and silently prune nothing.
    profile = report.profile_dir or paths.profile_dir()
    recorded = manifest.load(profile)

    # Newest run first. A run is a distinct `ingested_at`; several files share one.
    runs = sorted({entry.get("ingested_at") for entry in recorded.values()
                   if entry.get("ingested_at")}, reverse=True)
    keep_runs = set(runs[:keep]) if keep > 0 else set()

    for outcome in report.batches:
        if not outcome.verified or outcome.pruned:
            continue
        entry = recorded.get(outcome.fingerprint or "")
        if entry is None:
            continue
        if entry.get("ingested_at") in keep_runs:
            continue
        path = Path(outcome.path)
        try:
            path.unlink()
            outcome.pruned = True
            _remove_empty_parents(path, root)
        except OSError as exc:
            outcome.warnings.append(f"verified but not pruned: {exc}")


# ---------------------------------------------------------------------- preview

# A file this big is worth a warning before the parse, not after. Not a refusal: the
# adapters never read media, so a 4 GB WhatsApp zip with videos parses as fast as a
# 40 MB one — the cost is the copy and the disk, not the parse.
LARGE_FILE_BYTES = 500 * 1024 * 1024


def preview(
    *,
    root: str | Path | None = None,
    which: str = "real",
    profile_dir: str | Path | None = None,
) -> dict[str, Any]:
    """What is in the spool, and what has already been ingested.

    Read-only: nothing is parsed, nothing is written, nothing is deleted. This is the
    pass the modal runs before the Ingest button so the user is not asked to commit to
    an unknown quantity.

    It answers two questions and deliberately not a third:

    1. **Is this file already in the store?** A sampled fingerprint is compared against
       `store/profile/ingested.json`. That is the dedup the UI needs.
    2. **Is it large enough to warn about?** Size only — see `LARGE_FILE_BYTES`.

    It does **not** count messages. A message count needs a full parse, which is the
    work the preview exists to avoid; the report after the run is where real counts
    come from.
    """
    paths.ensure_layout()
    if root is None:
        root = paths.real_dir()
    root = Path(root)
    profile = Path(profile_dir) if profile_dir else paths.profile_dir()

    known = manifest.load(profile)
    legs: list[dict[str, Any]] = []
    total_bytes = 0

    for batch in discover(root):
        try:
            size = batch.path.stat().st_size
        except OSError:
            size = 0
        total_bytes += size

        digest = ""
        seen: dict[str, Any] | None = None
        if batch.recognised:
            try:
                digest = manifest.fingerprint(batch.path)
                seen = known.get(digest)
            except OSError:
                digest = ""

        legs.append({
            "platform": batch.platform,
            "path": str(batch.path),
            "bytes": size,
            "recognised": batch.recognised,
            "reason": batch.reason,
            "fingerprint": digest,
            "duplicate": seen is not None,
            "ingested_at": (seen or {}).get("ingested_at"),
            "previous_messages": (seen or {}).get("messages"),
            "large": size >= LARGE_FILE_BYTES,
        })

    return {
        "root": str(root),
        "legs": legs,
        "total_bytes": total_bytes,
        "large_file_bytes": LARGE_FILE_BYTES,
        "duplicates": sum(1 for leg in legs if leg["duplicate"]),
        "unrecognised": sum(1 for leg in legs if not leg["recognised"]),
    }


def _drop_spam_threads(
    result: IngestResult,
    platforms: Iterable[str] | None = None,
) -> None:
    """Drop long threads the owner never replied to, in place.

    The rule: **more than `SPAM_THREAD_MIN_MESSAGES` messages and no `is_self` row**.
    A 1:1 thread someone started with you is a real conversation, so "owner never
    spoke" alone is not enough to drop mail. A *long* thread the owner never
    contributed to is almost always a broadcast, a notification chain or a mailing
    list — the shape spam takes in a mailbox.

    Applies to Email and Outlook only. It is deliberately **not** the group gate:
    different scope (all threads, not groups), different threshold, and merging the
    two would make one toggle mean two things.

    Runs after parsing and before writing, so a dropped thread leaves no orphan
    messages. Counted in `skipped`, never silently lost.
    """
    allowed = set(platforms) if platforms is not None else _SPAM_THREAD_PLATFORMS
    if result.platform not in allowed:
        return

    spoke: set[str] = set()
    per_thread: dict[str, int] = {}
    for message in result.messages:
        per_thread[message.chat_id] = per_thread.get(message.chat_id, 0) + 1
        if message.is_self:
            spoke.add(message.chat_id)

    doomed = {
        chat_id for chat_id, count in per_thread.items()
        if count > SPAM_THREAD_MIN_MESSAGES and chat_id not in spoke
    }
    if not doomed:
        return

    result.messages = [m for m in result.messages if m.chat_id not in doomed]
    result.attachments = [a for a in result.attachments if a.chat_id not in doomed]
    result.chats = [c for c in result.chats if c.chat_id not in doomed]
    for _ in doomed:
        result.note_skip("spam thread (long, owner silent)")


def _owner_forms(
    profile: Path,
    result: IngestResult,
    parse_kwargs: dict[str, Any],
) -> list[str]:
    """Every form the Owner is known by on this platform.

    The Owner's identifier is not interchangeable between platforms: Telegram names
    them `user1426445212`, Messenger and LinkedIn name them `David Sartori`, Email
    names them an address. Comparing one form against another matches nothing, which
    is exactly how the Owner ended up written as a `Correspondent` in 236 threads.

    So collect all of them — the persisted owner, the caller's `self_id`, and every
    sender this result marks `is_self` — and let `canon.canonical` compare against the
    lot. A form that does not apply simply never matches.
    """
    forms: list[str] = []

    stored = identity.load_owner(profile, result.platform)
    if stored:
        forms.append(stored)

    caller = parse_kwargs.get("self_id")
    if caller:
        forms.append(str(caller))

    # The strongest evidence available: rows this adapter itself decided were ours.
    # A display name here is the Owner's name *on this platform*, which is the form
    # the participant list will contain.
    for message in result.messages:
        if message.is_self and message.sender_name:
            forms.append(message.sender_name)
        if message.is_self and message.sender_id:
            forms.append(str(message.sender_id))

    # A platform whose owner marker is not a name (`You` on WhatsApp) never marks a
    # row `is_self` under the Owner's real spelling, so the loop above learns nothing.
    # The profile's owner for *another* platform is still the same human, and a display
    # name is the form a participant list contains — so it is worth carrying across.
    # A form that does not apply simply never matches.
    for platform in ("messenger", "linkedin", "email", "telegram", "outlook", "sms"):
        if platform == result.platform:
            continue
        other = identity.load_owner(profile, platform)
        if other:
            forms.append(other)

    # Deduplicate while keeping order, so the list is stable across runs.
    seen: set[str] = set()
    unique: list[str] = []
    for form in forms:
        key = form.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(form.strip())
    return unique


def _resolve_owner_once(
    batches: list[Batch],
    profile_dir: Path,
) -> tuple[str | None, str]:
    """Persisted owner if known; otherwise infer from the Telegram file with the most evidence.

    Reads `personal_information` from the first file that states it, else infers by
    breadth — the same precedence as the adapter, applied once instead of once per
    worker.

    **Strongest file first, not first file.** A spool often holds both a bulk export
    (hundreds of chats) and a single-chat export (one). Taking whichever sorted first
    meant a one-chat file with two ids tied elected the *correspondent* as the owner,
    and every Telegram row then landed `is_self=False`. Files are therefore ranked by
    chat count, and a file that cannot support an inference is not consulted.
    """
    from . import identity

    stored = identity.load_owner(profile_dir, telegram.PLATFORM)
    if stored:
        return stored, ""

    tg = telegram
    documents: list[tuple[int, Path, dict[str, Any]]] = []
    for batch in batches:
        if batch.platform != tg.PLATFORM:
            continue
        try:
            document = json.loads(batch.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        chats, _ = tg._iter_chats(document)
        documents.append((len(chats), batch.path, document))

    # A file that states the owner outright wins regardless of size: that is a fact,
    # not an inference. Otherwise the widest file gives the best evidence.
    for _, path, document in documents:
        stated = identity.owner_from_personal_information(document)
        if stated:
            try:
                identity.save_owner(profile_dir, stated, evidence="personal_information",
                                    platform=tg.PLATFORM)
            except ValueError:
                pass
            return stated, ""

    for chat_count, path, document in sorted(documents, key=lambda d: -d[0]):
        chats, _ = tg._iter_chats(document)
        owner, breadth = identity.infer_owner(chats)
        if not owner:
            continue
        evidence = f"inferred from {path.name} ({breadth} of {chat_count} chats)"
        try:
            identity.save_owner(profile_dir, owner, evidence=evidence, platform=tg.PLATFORM)
        except ValueError:
            pass
        return owner, f"is_self owner inferred as {owner} ({evidence})"

    if not documents:
        return None, ""
    return None, ("is_self unresolved: no Telegram file states or permits inferring the "
                  "owner; all rows is_self=False. Pass --self-id to pin it.")


def _store_has_rows(store_path: Path) -> bool:
    """Does the store already hold messages? Used to decide if re-keying is safe."""
    if not store_path.exists():
        return False
    try:
        conn = writer.connect(store_path)
    except Exception:  # noqa: BLE001 - cannot read it, so assume it holds data
        return True
    try:
        cur = conn.cursor()
        cur.execute("MATCH (m:Message) RETURN count(m) AS n")
        rows = cur.fetchall()
        return bool(rows and rows[0]["n"])
    except Exception:  # noqa: BLE001
        return True
    finally:
        conn.close()


def _older_than(path: Path, age: timedelta) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return datetime.now(timezone.utc) - mtime >= age


def _remove_empty_parents(path: Path, root: Path) -> None:
    """Tidy an export folder we emptied. Never climbs above `root`."""
    parent = path.parent
    while parent != root and root in parent.parents:
        try:
            if any(parent.iterdir()):
                return
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent



def stage(paths_in: Iterable[str | Path], *, root: str | Path | None = None) -> list[Path]:
    """Copy downloaded exports into the spool and return what landed there.

    This is the dev path for "paste a path". The UI does the same thing through its
    drop zone: nothing is parsed from the user's Downloads folder and nothing there
    is ever moved or deleted. The spool is the one custody point, so verification
    and the 3-day prune keep working unchanged (§9.1).

    Files land in `spool/real/<platform>/`, chosen by **content**, not by the folder
    the user happened to download into. One level of the original folder is kept
    underneath, because Telegram's exporter writes a directory containing
    `result.json` and two exports of one account share that filename.

    A path that is already inside the spool is returned untouched, so re-running
    with the same path is a no-op rather than a copy of a copy.
    """
    top = Path(root) if root else paths.real_dir()
    top.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []

    for raw in paths_in:
        given = Path(raw).expanduser()
        if not given.exists():
            raise FileNotFoundError(f"no such export: {given}")

        # A directory an adapter claims **as a whole** is staged as one thing, exactly
        # as `discover()` treats it. Staging its files one-by-one filed every `.eml`
        # under `unrecognised/` (no single file is a mailbox) and lost the folder that
        # gives Messenger and email their thread ids — the drop zone then reported
        # success and wrote nothing.
        whole = given.is_dir() and detect_platform(given) is not None
        candidates = [given]
        if given.is_dir() and not whole:
            candidates = [p for p in sorted(given.rglob("*")) if p.is_file()
                          and p.suffix.lower() in _CONSIDER_SUFFIXES]

        for item in candidates:
            if top in item.parents:
                staged.append(item)
                continue

            platform = detect_platform(item)
            if platform is None:
                # Unrecognised: kept, not filed under a guess. The report names it.
                platform = "unrecognised"
            target_root = top / platform
            target_root.mkdir(parents=True, exist_ok=True)

            if item.is_dir():
                # Copy the recognised folder tree intact, with its own name as the
                # one level kept — `email_eml/` and `messenger_dir/` both rely on it.
                destination = target_root / item.name
                if not destination.exists():
                    shutil.copytree(item, destination)
                staged.append(destination)
                continue

            # Keep one folder level so two chats sharing a filename never collide.
            destination = target_root / item.parent.name / item.name
            if destination.exists():
                staged.append(destination)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            staged.append(destination)

    return staged


# ------------------------------------------------------------------------ report

def format_report(report: Report) -> str:
    """Human-readable panel. One line per file, plus a refusal list.

    Deliberately verbose about what did NOT land: the failure mode this guards is a
    user believing a batch ingested because the command exited 0.
    """
    lines: list[str] = []
    lines.append(f"store    : {report.store}")
    lines.append(f"workers  : {report.workers}")
    if report.owner_note:
        lines.append(f"owner    : {report.owner_note}")
    lines.append(f"elapsed  : {report.elapsed_s:.2f}s")

    if not report.batches and not report.unrecognised:
        lines.append("no exports found — nothing to do")
        return "\n".join(lines)

    lines.append("")
    for outcome in report.batches:
        name = Path(outcome.path).name
        parent = Path(outcome.path).parent.name
        label = f"{parent}/{name}" if parent else name
        if outcome.error:
            status = "ERROR   "
        elif not outcome.verified:
            status = "UNVERIF "
        elif outcome.pruned:
            status = "PRUNED  "
        else:
            status = "ok      "
        lines.append(f"  {status} {outcome.platform or '?':9} {label}  "
                     f"{outcome.messages:,} msgs, {outcome.attachments} attach")
        if outcome.kinds:
            kinds = ", ".join(f"{k}={v}" for k, v in sorted(outcome.kinds.items()))
            lines.append(f"           kinds: {kinds}")
        if outcome.skipped:
            skipped = ", ".join(f"{k}={v}" for k, v in sorted(outcome.skipped.items()))
            lines.append(f"           skipped: {skipped}")
        if outcome.error:
            lines.append(f"           !! {outcome.error}")
        if outcome.verification and not outcome.verified:
            missing = outcome.verification.get("missing", "?")
            lines.append(f"           !! {missing} keys not in store; file kept")

    for path in report.unrecognised:
        lines.append(f"  SKIPPED  ?         {path}  (unrecognised; kept)")
    for outcome in report.batches:
        for warning in outcome.warnings[:5]:
            lines.append(f"  note: {warning}")

    lines.append("")
    lines.append(f"total written: {report.written:,} msgs across {len(report.batches)} files")
    if report.failed:
        lines.append(f"REFUSED: {len(report.failed)} file(s) failed and were kept")
    if report.unverified:
        lines.append(f"REFUSED: {len(report.unverified)} file(s) did not verify and were kept")
    if report.unrecognised:
        lines.append(f"REFUSED: {len(report.unrecognised)} file(s) unrecognised and were kept")
    return "\n".join(lines)


def prune_spool(
    *,
    root: str | Path | None = None,
    older_than: timedelta = PRUNE_AFTER,
) -> list[str]:
    """Delete only spool files that already passed verification.

    Exists so `prune` has one implementation on every surface. With no store on disk
    there is no verification, therefore nothing is deleted.
    """
    root = Path(root) if root else paths.spool_dir()
    store_path = paths.store_path()
    if not store_path.exists():
        return []

    profile = paths.profile_dir()
    removed: list[str] = []
    conn = writer.connect(store_path)
    try:
        for batch in discover(root):
            if not batch.recognised or not _older_than(batch.path, older_than):
                continue
            # Re-parse with the offset the store was built with. Parsing at 0 when
            # the rows were written at -5 produces a disjoint key set, so every
            # file would look unverified and nothing would ever be pruned.
            kwargs: dict[str, Any] = {}
            stored_offset = identity.load_tz_offset(profile, batch.platform or "")
            if stored_offset is not None:
                kwargs["tz_offset_hours"] = stored_offset
            try:
                platform = batch.platform or ""
                result = _parser_for(batch.path, platform)(
                    _parse_root(batch.path, platform), **kwargs)
            except Exception:  # noqa: BLE001 - cannot verify => cannot delete
                continue
            ok, _ = writer.verify_present(conn, result)
            if not ok:
                continue
            try:
                batch.path.unlink()
                _remove_empty_parents(batch.path, root)
                removed.append(str(batch.path))
            except OSError:
                continue
    finally:
        conn.close()
    return removed
