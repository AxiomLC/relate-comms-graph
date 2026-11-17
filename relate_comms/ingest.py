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

from . import identity, paths, resolution, scrub, writer
from .adapters import (email_imap, linkedin, messenger, outlook_pst, sms, telegram,
                       whatsapp)
from .schema import IngestResult

# Files this module will consider. Suffix is a cheap filter only; the platform is
# still decided by inspecting the content.
_JSON_SUFFIXES = {".json"}
_ARCHIVE_SUFFIXES = {".zip"}
_TEXT_SUFFIXES = {".txt", ".md"}
_MAIL_SUFFIXES = {".pst", ".ost"}
# SMS Backup & Restore writes `.xml`, or `.xml.zip` when "compress backup" is on.
_XML_SUFFIXES = {".xml"}
_CONSIDER_SUFFIXES = (_JSON_SUFFIXES | _ARCHIVE_SUFFIXES | _TEXT_SUFFIXES
                      | _MAIL_SUFFIXES | _XML_SUFFIXES)

# Parse functions by platform. Adding an adapter means adding one line here.
# Parsers that read wall-clock times with no offset. Only these accept
# `tz_offset_hours`; passing it to others (LinkedIn states UTC) is a TypeError, which
# is the correct behaviour — the adapter refuses to be told a lie about its data.
_TZ_AWARE_PLATFORMS = {telegram.PLATFORM, whatsapp.PLATFORM, messenger.PLATFORM}

_PARSERS: dict[str, Callable[..., IngestResult]] = {
    telegram.PLATFORM: telegram.parse,
    whatsapp.PLATFORM: whatsapp.parse,
    messenger.PLATFORM: messenger.parse,
    linkedin.PLATFORM: linkedin.parse,
    outlook_pst.PLATFORM: outlook_pst.parse,
    sms.PLATFORM: sms.parse,
}

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
    identities: int = 0
    who_matched: int = 0
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
    """Which adapter owns this file? None means 'unrecognised, report and keep'."""
    suffix = path.suffix.lower()

    if suffix in _MAIL_SUFFIXES:
        return outlook_pst.PLATFORM if outlook_pst.detect(path) else None

    if suffix in _XML_SUFFIXES:
        # Only SMS Backup & Restore writes an `.xml` we read. Anything else is
        # reported and kept, never guessed at.
        return sms.PLATFORM if sms.detect(path) else None

    if suffix in {".zip", ".txt", ".md"}:
        # Four zip-shaped platforms. Detection is by content, never by filename:
        # a user renames downloads.
        if linkedin.detect(path):
            return linkedin.PLATFORM
        if messenger.detect(path):
            return messenger.PLATFORM
        if sms.detect(path):
            return sms.PLATFORM
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
                names = {Path(n).name for n in archive.namelist()}
                if "chat.txt" not in names and "_chat.txt" not in names:
                    return None
                member = "chat.txt" if "chat.txt" in names else "_chat.txt"
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
    """Every candidate file under `root`, in deterministic order.

    Directories named `result.json` are the normal case; a spool entry that is a
    folder of exports (Telegram's own layout) is descended into for the same file.
    """
    found: list[Batch] = []
    if not root.exists():
        return found

    candidates: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
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

    # `exclude_spam_groups` and `exclude_silent_groups` are Messenger-only. They are
    # popped here rather than passed to every adapter, so adding a platform never
    # means adding a no-op argument.
    if platform != messenger.PLATFORM:
        trimmed.pop("exclude_spam_groups", None)
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
        result = _PARSERS[platform](path, **_kwargs_for(platform, parse_kwargs))
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
    prune: bool = False,
    prune_after: timedelta = PRUNE_AFTER,
    workers: int | None = None,
    self_id: str | None = None,
    profile_dir: str | Path | None = None,
    tz_offset_hours: float | None = None,
    scrub_policy: dict[str, scrub.Verdict] | None | bool = None,
    extra_results: Iterable[IngestResult] = (),
) -> Report:
    """Parse everything in the spool, write it, verify it, and optionally prune.

    `root` is the directory to read; if omitted, `which` picks one of the two
    standard queues (`"real"` or `"sample"`). Both go through the same code path, so
    the sample proves the ingest rather than being a special case.

    `prune=False` is the default everywhere. Deleting a spool file is a user
    decision (§9.1.3: `prune` needs `confirm=true`), and the CLI gates it the same
    way the tool layer does.
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
        # Two queues, never mixed: `spool/real/` holds the user's own exports,
        # `spool/sample/` holds generated demo data (§6). Re-ingest is idempotent, so
        # whichever is chosen is read whole — never "most recent only", which would
        # silently skip a file and hide a bug.
        root = paths.sample_dir() if which == "sample" else paths.real_dir()
    root = Path(root)

    store_path = Path(store) if store else paths.store_path()
    profile = Path(profile_dir) if profile_dir else paths.profile_dir()

    workers = default_workers() if workers is None else max(1, workers)

    report = Report(store=str(store_path), workers=workers)
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

    # Messenger-only, and dropped for every other platform by `_kwargs_for`.
    if exclude_spam_groups:
        parse_kwargs["exclude_spam_groups"] = True
    if exclude_silent_groups:
        parse_kwargs["exclude_silent_groups"] = True

    parsed = parse_batches(batches, parse_kwargs=parse_kwargs, workers=workers)

    # Live mailboxes arrive already parsed: email is the one platform with no file to
    # drop (§5.3.1), so it is fetched by the caller and appended here. Giving it a
    # synthetic `Batch` keeps it in the same serialised write path as everything else.
    for extra in extra_results:
        parsed.append((Batch(path=Path(extra.export_path), platform=extra.platform),
                       extra, ""))

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

            # §3.2: resolution, then scrub, then write. Resolution needs real keys
            # to join on, so the gate comes after it and before anything lands.
            if scrub_policy is not False:
                candidates = resolution.collect(result)
                people, merged = resolution.merge(candidates)
                result, scrub_report, aliases = scrub.scrub_result(
                    result, policy=scrub_policy or None, aliases=aliases)
                outcome.who_matched = len(people)
                outcome.withheld = scrub_report.summary()
                outcome.identities = len(merged)

            try:
                written = writer.write(conn, result, owner=parse_kwargs.get("self_id"))
            except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the rest
                outcome.error = f"write failed: {type(exc).__name__}: {exc}"
                report.batches.append(outcome)
                continue

            # §5.6: the thread's counterparty, straight from the export's participant
            # list. After `write()` because `WITH` needs the Thread row to exist. This
            # is a fact, not the inference `write_people()` will later add.
            try:
                counted = writer.write_correspondents(
                    conn, result, owner=parse_kwargs.get("self_id"))
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

            if prune and ok and _older_than(batch.path, prune_after):
                try:
                    batch.path.unlink()
                    outcome.pruned = True
                    _remove_empty_parents(batch.path, root)
                except OSError as exc:
                    outcome.warnings.append(f"verified but not pruned: {exc}")

            report.batches.append(outcome)
    finally:
        conn.close()

    report.elapsed_s = time.perf_counter() - started
    return report


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


def _sample_root() -> Path:
    from .sample_data import build as build_module
    return build_module.SAMPLE


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

        candidates = [given]
        if given.is_dir():
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
                result = _PARSERS[batch.platform or ""](batch.path, **kwargs)
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
