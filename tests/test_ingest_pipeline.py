"""Stage 1 (`ingest.py`) acceptance.

Covers the four promises the module makes:

1. parallel parse, serialised write, deterministic order;
2. a bad or unknown file is reported and **kept**, never silently dropped;
3. re-ingest is idempotent through the full pipeline, not just the writer;
4. prune happens only after verification, and never for a young or failed file.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from relate_comms import ingest as ingest_module
from relate_comms import paths, writer
from relate_comms.sample_data import build as build_module
from relate_comms.schema import Chat, IngestResult, Message, make_key


def _make_sample(root: Path) -> None:
    """Write the generated sample payloads (gitignored, reproducible)."""
    code = build_module.main(["--dest", "generated"])
    assert code == 0


@pytest.fixture()
def spool(tmp_path):
    """A spool holding one Telegram bulk export and one single-chat export."""
    _make_sample(build_module.GENERATED)

    root = tmp_path / "spool"
    for shape in ("telegram_bulk", "telegram_single"):
        target = root / shape
        target.mkdir(parents=True)
        source = build_module.GENERATED / shape / "result.json"
        (target / "result.json").write_text(source.read_text(encoding="utf-8"),
                                            encoding="utf-8")
    return root


def _run(root: Path, store: Path, **kwargs) -> ingest_module.Report:
    return ingest_module.ingest(
        root=root,
        store=store,
        profile_dir=root.parent / "profile",
        self_id="user900000",
        **kwargs,
    )


def test_detects_and_ingests_both_telegram_shapes(spool, tmp_path):
    report = _run(spool, tmp_path / "g.rl")
    assert report.ok, ingest_module.format_report(report)
    assert {b.platform for b in report.batches} == {"telegram"}
    assert len(report.batches) == 2
    assert report.written > 0
    # Both files verified against the store, not just "the job exited 0".
    assert all(b.verified for b in report.batches)
    assert all(b.verification["missing"] == 0 for b in report.batches)


def test_write_order_is_deterministic(spool, tmp_path):
    first = _run(spool, tmp_path / "a.rl")
    second = _run(spool, tmp_path / "b.rl")
    assert [b.path for b in first.batches] == [b.path for b in second.batches]
    assert first.written == second.written


def test_ingest_twice_is_idempotent(spool, tmp_path):
    store = tmp_path / "idem.rl"
    first = _run(spool, store)
    second = _run(spool, store)
    assert first.ok and second.ok

    conn = writer.connect(store)
    try:
        keys = writer.stored_keys(conn, "telegram")
    finally:
        conn.close()
    assert len(keys) == second.written, "store rows != rows written"
    # Every key from the second run was already there: no growth.
    assert first.written == second.written


def test_parallel_and_serial_agree(spool, tmp_path):
    parallel = _run(spool, tmp_path / "p.rl", workers=2)
    serial = _run(spool, tmp_path / "s.rl", workers=1)
    assert parallel.written == serial.written
    assert [b.messages for b in parallel.batches] == [b.messages for b in serial.batches]


def test_unrecognised_file_is_reported_and_kept(spool, tmp_path):
    stray = spool / "notes.json"
    stray.write_text('{"hello": "world"}', encoding="utf-8")

    report = _run(spool, tmp_path / "u.rl")
    assert str(stray) in report.unrecognised
    assert stray.exists(), "an unrecognised file must never be deleted"
    assert not report.ok, "an unrecognised file must make the run visibly incomplete"
    assert report.written > 0, "the good files must still ingest"


def test_bad_file_does_not_abort_the_run(spool, tmp_path):
    broken = spool / "broken"
    broken.mkdir()
    # Valid shape markers so detection claims it, then JSON that cannot parse.
    (broken / "result.json").write_text('{"chats": {', encoding="utf-8")

    report = _run(spool, tmp_path / "bad.rl")
    errors = [b for b in report.batches if b.error]
    assert errors, "a parse failure must be reported, not swallowed"
    assert broken.joinpath("result.json").exists(), "failed file kept for inspection"
    assert report.written > 0, "other batches must still land"


def test_prune_requires_verification_and_age(spool, tmp_path):
    store = tmp_path / "prune.rl"

    # Young files are verified but never pruned.
    young = _run(spool, store, prune=True)
    assert all(b.verified for b in young.batches)
    assert not any(b.pruned for b in young.batches)
    assert all(Path(b.path).exists() for b in young.batches)

    # Age one file past the threshold: exactly that file goes.
    victim = next(Path(b.path) for b in young.batches if "bulk" in b.path)
    old = time.time() - timedelta(days=4).total_seconds()
    os.utime(victim, (old, old))

    aged = _run(spool, store, prune=True)
    pruned = {Path(b.path) for b in aged.batches if b.pruned}
    assert victim in pruned
    assert not victim.exists()
    # The other file is still young, so it survives.
    assert any(Path(b.path).exists() for b in aged.batches if Path(b.path) != victim)


def test_unverified_file_is_not_pruned(tmp_path, monkeypatch):
    """A file whose keys do not land must stay on disk."""
    store = tmp_path / "keep.rl"
    root = tmp_path / "spool"
    root.mkdir()
    payload = root / "result.json"
    payload.write_text(json.dumps({"chats": {"list": []}, "messages": []}),
                       encoding="utf-8")
    old = time.time() - timedelta(days=10).total_seconds()
    os.utime(payload, (old, old))

    monkeypatch.setattr(ingest_module.writer, "verify_present",
                        lambda conn, result: (False, {"expected": 1, "present": 0,
                                                      "missing": 1, "missing_sample": []}))
    report = ingest_module.ingest(root=root, store=store, prune=True,
                                  profile_dir=tmp_path / "profile", self_id="user900000")
    assert payload.exists(), "unverified spool file must be kept"
    assert not any(b.pruned for b in report.batches)
    assert not report.ok


def test_prune_spool_helper_deletes_nothing_without_a_store(spool, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "store_path", lambda: tmp_path / "absent.rl")
    assert ingest_module.prune_spool(root=spool) == []
    assert all(Path(b).exists() for b in spool.rglob("result.json"))


def test_cli_refuses_prune_without_confirm():
    from relate_comms import cli

    code = cli.main(["ingest", "--source", "real", "--prune"])
    assert code == 2


def test_cli_json_report_is_serialisable(spool, tmp_path):
    from relate_comms import cli

    code = cli.main([
        "ingest", "--source", "real", "--root", str(spool),
        "--store", str(tmp_path / "cli.rl"), "--self-id", "user900000", "--json",
    ])
    assert code == 0
