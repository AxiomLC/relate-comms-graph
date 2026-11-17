"""The "keep the last N ingests" prune policy.

The age rule (`prune_after`) is per file. This one is per **run**, because "the last
ingest" is a property of the run, not of a file — a file cannot know whether it belongs
to the newest run until the run is over.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import json

from relate_comms import ingest as ingest_module
from relate_comms import manifest


def _telegram(path, marker: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "personal_information": {"user_id": 1},
        "chats": {"list": [{
            "name": marker, "type": "personal_chat", "id": 1,
            "messages": [{"id": 1, "type": "message",
                          "date_unixtime": "1700000000",
                          "from_id": "user1", "text": marker}],
        }]},
    }), encoding="utf-8")
    return path


def _run(spool, store, profile, **kwargs):
    return ingest_module.ingest(
        root=spool, store=store, profile_dir=profile, workers=1, **kwargs)


def test_keep_last_deletes_the_older_run(tmp_path):
    spool = tmp_path / "spool"
    store = tmp_path / "g.rl"
    profile = tmp_path / "profile"

    old = _telegram(spool / "old" / "result.json", "old")
    first = _run(spool, store, profile)
    assert all(b.verified for b in first.batches)

    # A second run over a spool holding both files. `keep=1` means only the newest
    # run's files survive — and the newest run touched both, so nothing is deleted.
    new = _telegram(spool / "new" / "result.json", "new")
    second = _run(spool, store, profile, prune=True, prune_keep=1)
    assert all(b.verified for b in second.batches)
    assert old.exists() and new.exists(), (
        "both files belong to the newest run, so keep=1 must delete neither")


def test_keep_zero_deletes_everything_verified(tmp_path):
    spool = tmp_path / "spool"
    store = tmp_path / "g.rl"
    profile = tmp_path / "profile"
    path = _telegram(spool / "a" / "result.json", "a")

    report = _run(spool, store, profile, prune=True, prune_keep=0)
    assert all(b.verified for b in report.batches)
    assert all(b.pruned for b in report.batches)
    assert not path.exists()


def test_an_unverified_file_is_never_pruned(tmp_path):
    """The rule that outranks every policy: no verification, no deletion."""
    spool = tmp_path / "spool"
    store = tmp_path / "g.rl"
    profile = tmp_path / "profile"
    path = _telegram(spool / "a" / "result.json", "a")

    # No prune on the run itself, so the file is still there to test against.
    report = _run(spool, store, profile)
    assert report.batches[0].verified

    # Now pretend it had not verified, and apply the policy directly.
    report.batches[0].verified = False
    ingest_module._prune_keep_last(report, spool, 0)
    assert path.exists(), "an unverified file must survive every prune policy"


def test_a_file_with_no_manifest_entry_is_left_alone(tmp_path):
    """It cannot be placed in a run, and guessing is worse than keeping."""
    spool = tmp_path / "spool"
    store = tmp_path / "g.rl"
    profile = tmp_path / "profile"
    path = _telegram(spool / "a" / "result.json", "a")

    report = _run(spool, store, profile)
    # Wipe the manifest, as a Truncate would.
    (profile / manifest.MANIFEST_FILE).unlink()

    ingest_module._prune_keep_last(report, spool, 0)
    assert path.exists()


def test_age_rule_still_applies_when_no_keep_policy_is_given(tmp_path):
    """`prune_keep=None` must not silently become `keep=0`."""
    spool = tmp_path / "spool"
    store = tmp_path / "g.rl"
    profile = tmp_path / "profile"
    path = _telegram(spool / "a" / "result.json", "a")

    report = _run(spool, store, profile, prune=True)
    assert all(b.verified for b in report.batches)
    assert not any(b.pruned for b in report.batches), (
        "a young file must not be pruned by the age rule")
    assert path.exists()
