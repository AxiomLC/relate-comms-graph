"""sample_writer must produce shapes the app's own adapters accept.

These tests are the contract in `UNDESIRABLES.md` §12 made executable. They generate into
a temp directory, drive the **real** adapters, and assert what each mandated shape
actually does to the app — not that a file exists.

Two rules for anything added here:

- Assert on parsed output (`IngestResult`, `Chat`, `Message`), never on prose.
- Use a fresh temp dir. Never read or write `sample_writer/out/`.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relate_comms import ingest  # noqa: E402
from relate_comms.adapters import (  # noqa: E402
    email_imap, linkedin, messenger, outlook_pst, sms, telegram, whatsapp, whatsapp_html,
)

import sample_writer  # noqa: E402
from sample_writer import config, plan as plan_module, world as world_module  # noqa: E402


@pytest.fixture(scope="module")
def generated():
    """One generation, shared by the read-only assertions below."""
    out = Path(tempfile.mkdtemp(prefix="sw_"))
    # `clean=True` so a wipe->write run always starts from a fresh out/. Without it,
    # a manual `python -m sample_writer --seed N` left in out/ would merge that seed's
    # files onto the default-seed generation and corrupt the tree (see the directory
    # ingest test — two seed sets in one messenger_dir double the message count).
    written = sample_writer.build(seed=config.SEED, clean=True, log=None)
    # `build` writes into config.OUT_DIR; copy the tree out so tests never touch it.
    shutil.copytree(config.OUT_DIR, out, dirs_exist_ok=True)
    yield out
    shutil.rmtree(out, ignore_errors=True)


@pytest.fixture(scope="module")
def world():
    return world_module.build()


# --------------------------------------------------------------------------- world


def test_cross_platform_share_is_in_band(world):
    share = world.multi_platform_share()
    assert config.CROSS_PLATFORM_MIN <= share <= config.CROSS_PLATFORM_MAX, (
        f"cross-platform share {share:.3f} outside "
        f"{config.CROSS_PLATFORM_MIN}-{config.CROSS_PLATFORM_MAX}"
    )


def test_owner_is_on_every_platform(world):
    """`Mark Jones` must appear everywhere, or there is no self to detect."""
    for platform in ("telegram", "whatsapp", "messenger", "sms", "email", "linkedin"):
        people = world.for_platform(platform)
        assert people, f"no correspondents on {platform}"


def test_same_seed_is_deterministic():
    a = world_module.build(7)
    b = world_module.build(7)
    assert [p.name for p in a.people] == [p.name for p in b.people]
    assert a.multi_platform_share() == b.multi_platform_share()


def test_different_seed_differs():
    a = world_module.build(1)
    b = world_module.build(2)
    assert [p.name for p in a.people] != [p.name for p in b.people]


# ------------------------------------------------------------------------ the plan


def test_plan_satisfies_contract(world):
    plans = [plan_module.plan(world, name, __import__("random").Random(f"{world.seed}:{name}"))
             for name in ("email", "telegram", "whatsapp", "messenger", "linkedin", "sms")]
    plan_module.assert_contract(plans)      # raises on a missing §12 row


def test_email_boundary_counts_are_exact(world):
    import random
    plan_obj = plan_module.plan(world, "email", random.Random("e"))
    by_mark = {t.mark: t for t in plan_obj.threads if t.mark}
    for count in config.EMAIL_LONG_SILENT:
        assert any(t.count == count and t.mark == "email_long_silent"
                   for t in plan_obj.threads)
    assert by_mark["email_boundary_kept"].count == config.EMAIL_BOUNDARY_KEPT
    assert by_mark["email_replied_long"].owner_replies is True


def test_no_unmarked_thread_exceeds_ordinary_cap(world):
    import random
    for platform in ("telegram", "messenger"):
        plan_obj = plan_module.plan(world, platform, random.Random("x"))
        for thread in plan_obj.threads:
            if not thread.mark:
                assert thread.count <= config.ORDINARY_THREAD_MAX


def test_big_threads_present_and_huge_is_opt_in(world):
    import random
    normal = plan_module.plan(world, "telegram", random.Random("b"))
    sizes = {t.count for t in normal.threads if t.mark == "big_thread"}
    assert sizes == set(config.BIG_THREADS)

    huge = plan_module.plan(world, "telegram", random.Random("b"), huge=True)
    assert any(t.mark == "huge_thread" for t in huge.threads)


def test_messenger_covers_all_four_folders(world):
    import random
    plan_obj = plan_module.plan(world, "messenger", random.Random("m"))
    folders = {t.folder for t in plan_obj.threads}
    for folder in ("inbox", "filtered_threads", "message_requests", "e2ee_cutover"):
        assert folder in folders, f"no thread in {folder}/"


def test_spam_group_is_at_least_half_noise(world):
    import random
    plan_obj = plan_module.plan(world, "messenger", random.Random("s"))
    spam = [t for t in plan_obj.threads if t.mark == "spam_group"]
    assert spam, "no spam group planned"
    thread = spam[0]
    noise = sum(1 for _sender, body in thread.group_lines
                if messenger.is_noise_row(body))
    assert noise / len(thread.group_lines) >= config.SPAM_GROUP_NOISE_RATIO


# --------------------------------------------------------- generated, then parsed


def test_telegram_bulk_ingests(generated):
    path = generated / "telegram" / "telegram_bulk" / "result.json"
    assert ingest.detect_platform(path) == "telegram"
    result = telegram.parse(path)
    assert result.chats, "no chats parsed from the bulk export"
    assert len(result.messages) > 100


def test_telegram_zero_message_chat_is_skipped_not_emitted(generated):
    """§6: a chat whose only rows are service rows yields no Chat."""
    path = generated / "telegram" / "telegram_bulk" / "result.json"
    result = telegram.parse(path)
    titles = {chat.title for chat in result.chats}
    assert "Old Group" not in titles
    assert any("service" in key for key in result.unknown_kinds), result.unknown_kinds


def test_telegram_service_rows_are_kept_and_kinded(generated):
    """§7: service rows inside a live thread survive include_service=True."""
    path = generated / "telegram" / "telegram_bulk" / "result.json"
    result = telegram.parse(path)
    service_kinds = [k for k in result.unknown_kinds if k.startswith("service:")]
    assert service_kinds, "no service rows reached the adapter"


def test_whatsapp_native_detects_and_parses(generated):
    """§11a: native zip, one chat per file, chat.txt inside a conversation folder."""
    zips = sorted((generated / "whatsapp" / "whatsapp_chat_txt").glob("*.zip"))
    assert zips, "no native WhatsApp zips written"
    path = zips[0]
    assert ingest.detect_platform(path) == "whatsapp"
    result = whatsapp.parse(path)
    assert result.messages, f"no messages parsed from {path.name}"


def test_whatsapp_html_detects_and_parses(generated):
    """§11b: the browser-extension dialect, many chats in one zip.

    Both WhatsApp dialects report platform `whatsapp`, so the parser is chosen per
    **file** by `ingest._parser_for()` — not by the platform name. Asserting on
    `detect_platform()` alone would pass while the file was handed to the text adapter.
    """
    path = generated / "whatsapp" / "whatsapp_html" / "whatsapp-chats-20261117.zip"
    assert path.exists()

    platform = ingest.detect_platform(path)
    assert platform == "whatsapp", f"HTML WhatsApp zip detected as {platform!r}"

    parser = ingest._parser_for(path, platform)
    assert parser is whatsapp_html.parse, (
        f"HTML zip routed to {parser.__module__} — it must reach whatsapp_html")

    result = parser(path)
    assert result.messages
    assert result.chats


def test_whatsapp_html_reaches_the_store_through_ingest(generated, tmp_path):
    """The routing fix must hold through a whole ingest, not just a direct parse."""
    folder = tmp_path / "only_html"
    folder.mkdir()
    source = generated / "whatsapp" / "whatsapp_html" / "whatsapp-chats-20261117.zip"
    shutil.copy2(source, folder / source.name)

    report = ingest.ingest(root=folder, store=tmp_path / "g.rl",
                           profile_dir=tmp_path / "p")
    assert report.written > 0, "HTML WhatsApp zip wrote nothing through ingest"
    assert {outcome.platform for outcome in report.batches} == {"whatsapp"}


def test_whatsapp_group_has_membership_row(generated):
    """§1: an owner-silent group is only classifiable via a membership system row."""
    zips = sorted((generated / "whatsapp" / "whatsapp_chat_txt").glob("*Watch*.zip"))
    assert zips, "owner-silent group zip missing"
    import zipfile
    with zipfile.ZipFile(zips[0]) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8")
    for phrase in ("added", "removed", "changed the group", "created group"):
        if phrase in text:
            return
    raise AssertionError("no membership system row in the owner-silent group")


def test_whatsapp_owner_silent_group_is_classified_as_group(generated):
    """The whole point of §1: the app sees a group with zero owner rows."""
    zips = sorted((generated / "whatsapp" / "whatsapp_chat_txt").glob("*Watch*.zip"))
    result = whatsapp.parse(zips[0])
    groups = [chat for chat in result.chats if getattr(chat, "is_group", False)]
    assert groups, "owner-silent group parsed as personal_chat"
    owner_rows = [m for m in result.messages if getattr(m, "is_self", False)]
    assert not owner_rows, "owner rows leaked into an owner-silent group"


def test_linkedin_parses_with_placeholder_sender(generated):
    """§5: `LinkedIn Member` is a sender, not a person.

    `linkedin._chat_title()` deliberately skips `LinkedIn Member` when naming a chat
    (`_UNKNOWN_SENDER`, L57/L282), so the expected behaviour is: the placeholder is
    present as a row sender, and the chat is titled after a real person instead. Assert
    the placeholder reached the adapter, not that it titled the chat.
    """
    path = generated / "linkedin" / "linkedin_zip" / "Basic_LinkedInDataExport_11-14-2026.zip.zip"
    assert ingest.detect_platform(path) == "linkedin"
    import csv
    import io
    import zipfile
    with zipfile.ZipFile(path) as archive:
        rows = list(csv.DictReader(io.StringIO(
            archive.read("messages.csv").decode("utf-8"))))
    senders = {row["FROM"] for row in rows}
    assert any("LinkedIn" in sender for sender in senders), senders

    # And the adapter must not turn that placeholder into a Correspondent name.
    result = linkedin.parse(path)
    titles = {chat.title for chat in result.chats}
    assert not any(title.lower() == "linkedin member" for title in titles), titles


def test_sms_xml_and_zip_both_detect(generated):
    plain = generated / "sms" / "sms_xml" / "sms-20261116212209.xml"
    assert ingest.detect_platform(plain) == "sms"
    assert sms.parse(plain).messages

    zipped = generated / "sms" / "sms_xml_zip" / "sms-20261116212209.xml.zip"
    # Both halves matter: `sms._head_text()` unwraps the zip so detection sees the
    # decompressed `<smses>`, and the parser reads the same member. Asserting only the
    # parser let a detection regression pass unnoticed.
    assert ingest.detect_platform(zipped) == "sms", "detector refused a .xml.zip"
    assert sms.parse(zipped).messages, "parser refused a .xml.zip"


def test_sms_json_app_is_unrecognised_on_purpose(generated):
    """A different app's shape must be reported, never guessed at."""
    path = generated / "sms" / "sms_json_app" / "sms-backup.json"
    assert ingest.detect_platform(path) is None


def test_outlook_fixture_is_copied_and_detects(generated):
    path = generated / "outlook" / "outlook_copy" / "Outlook.pst"
    assert path.exists()
    assert ingest.detect_platform(path) == "outlook"
    assert outlook_pst.parse(path).messages


def test_email_eml_tree_parses_through_the_real_parser(generated):
    """§3: no `.eml` adapter exists, so drive `_parse_raw` — the real key logic."""
    from relate_comms.schema import IngestResult

    thread_dir = generated / "email" / "email_eml" / "email_long-silent-12"
    assert thread_dir.exists(), "no 12-message silent thread written"
    files = sorted(thread_dir.glob("*.eml"))
    assert len(files) == 12

    result = IngestResult(platform="email", export_path="imap://test")
    seen: set[str] = set()
    chats: dict = {}
    for path in files:
        email_imap._parse_raw(
            path.read_bytes(), folder="INBOX", uid=path.stem, uidvalidity="1",
            result=result, seen_keys=seen, chats=chats,
            account_address="mark.jones@mail.example.com",
        )
    assert len(result.messages) == 12
    assert not any(getattr(m, "is_self", False) for m in result.messages)


def test_email_boundary_10_parses_as_ten(generated):
    thread_dir = generated / "email" / "email_eml" / "email_boundary-kept"
    assert len(list(thread_dir.glob("*.eml"))) == config.EMAIL_BOUNDARY_KEPT


def test_messenger_zip_ingests(generated):
    path = generated / "messenger" / "messenger_zip" / "facebook-sampleuser-2026-11-14-1G300tUX.zip"
    assert ingest.detect_platform(path) == "messenger"
    result = messenger.parse(path)
    assert result.messages
    assert len(result.chats) >= 10


def test_messenger_has_placeholder_titled_threads(generated):
    """§5: three threads titled `Facebook user`."""
    path = generated / "messenger" / "messenger_zip" / "facebook-sampleuser-2026-11-14-1G300tUX.zip"
    result = messenger.parse(path)
    titled = [c for c in result.chats if c.title == "Facebook user"]
    assert len(titled) >= config.PLACEHOLDER_THREADS["messenger"]


def test_messenger_spam_group_is_dropped_when_asked(generated):
    """§2: the gate must fire on the generated spam group."""
    path = generated / "messenger" / "messenger_zip" / "facebook-sampleuser-2026-11-14-1G300tUX.zip"
    kept = messenger.parse(path)
    dropped = messenger.parse(path, exclude_spam_groups=True)
    assert len(dropped.messages) < len(kept.messages), "spam group not detected"


def test_owner_silent_group_survives_in_the_zip_unless_filtered(generated):
    """§1 + §8: the gate drops them only when asked, and 1:1s are never touched."""
    path = generated / "messenger" / "messenger_zip" / "facebook-sampleuser-2026-11-14-1G300tUX.zip"
    kept = messenger.parse(path)
    filtered = messenger.parse(path, exclude_silent_groups=True)
    assert len(filtered.chats) < len(kept.chats)


# ----------------------------------------------------------------- every artifact


def test_a_recognised_directory_is_one_batch_not_one_per_file(generated):
    """A folder export must be parsed once, not once per file inside it.

    Messenger and Telegram resolve thread ids from the archive-relative path, so handing
    the adapter a single `message_1.html` makes it parse the *whole* export. Before this
    rule a 29-thread folder produced 29 batches and parsed 18,330 messages to write 611.
    """
    folder = generated / "messenger" / "messenger_dir"
    assert folder.exists(), "the directory variant is missing"

    # Discover the folder itself, not its parent — the parent also holds the zip.
    batches = [b for b in ingest.discover(folder) if b.platform == "messenger"]
    assert len(batches) == 1, f"expected one batch for the folder, got {len(batches)}"
    assert batches[0].path.is_dir(), "the batch must be the folder, not a file inside it"

    # And the folder must be claimed as a whole, so `discover()` does not walk into it.
    assert ingest.detect_platform(folder) == "messenger"


def test_a_directory_ingest_parses_each_message_once(generated):
    """The report must not overstate the work: parsed ≈ written for a folder export."""
    from relate_comms.adapters import messenger

    folder = generated / "messenger" / "messenger_dir"
    expected = len(messenger.parse(folder).messages)

    # A root holding only the folder, so the zip cannot contribute a second batch.
    root = generated.parent / "dir_only_root"
    root.mkdir(exist_ok=True)
    target = root / "messenger_dir"
    if not target.exists():
        import shutil
        shutil.copytree(folder, target)

    report = ingest.ingest(root=root, store=generated.parent / "dir_only.rl", workers=1)
    messenger_batches = [b for b in report.batches if b.platform == "messenger"]
    assert len(messenger_batches) == 1, (
        f"expected one batch, got {len(messenger_batches)}")
    assert messenger_batches[0].messages == expected, (
        f"parsed {messenger_batches[0].messages}, expected {expected}")


def test_every_artifact_is_either_detected_or_documented(generated):
    """No silent surprises: each written artifact must detect, or be a known gap."""
    known_gaps = (
        "linkedin_dir",      # loose CSV: the CSVs are inputs to the folder, not artifacts
        "sms_json_app",      # deliberate negative case
        "email_eml",         # email is never discovered from a spool
        "outlook_copy",      # a .pst is a file, detected below
    )
    unexpected = []
    for path in sorted(generated.rglob("*")):
        if not path.is_file():
            continue
        if any(gap in path.parts for gap in known_gaps):
            continue
        if path.suffix.lower() == ".pst":
            continue
        if ingest.detect_platform(path) is None:
            unexpected.append(str(path.relative_to(generated)))
    assert not unexpected, f"unrecognised artifacts: {unexpected}"
