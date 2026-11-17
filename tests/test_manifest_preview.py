"""The dedup manifest and the read-only preview.

Two promises:

1. **A file already ingested is recognised before the parse, not after it.** The
   fingerprint is size + both ends, so an 825 MB export costs milliseconds to check.
2. **The manifest is a shortcut, never the authority.** `verify_present()` still
   decides whether a spool file may be pruned; a manifest entry is not proof that the
   rows landed.

Run: python -m pytest tests -q
"""
from __future__ import annotations

import json

from relate_comms import ingest as ingest_module
from relate_comms import manifest


def _telegram(path):
    path.write_text(json.dumps({
        "personal_information": {"user_id": 1},
        "chats": {"list": []},
    }), encoding="utf-8")
    return path


def test_fingerprint_is_stable_and_size_sensitive(tmp_path):
    one = _telegram(tmp_path / "a.json")
    same = _telegram(tmp_path / "b.json")
    assert manifest.fingerprint(one) == manifest.fingerprint(same), (
        "the same bytes under a different name must share a fingerprint"
    )

    bigger = tmp_path / "c.json"
    bigger.write_text(one.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert manifest.fingerprint(bigger) != manifest.fingerprint(one), (
        "a changed file must not look like a duplicate"
    )


def test_fingerprint_full_matches_sampled_for_small_files(tmp_path):
    """Under the sample window the two paths read the same bytes, so they must agree."""
    path = _telegram(tmp_path / "small.json")
    assert manifest.fingerprint(path) == manifest.fingerprint(path, full=True)


def test_record_and_lookup_round_trip(tmp_path):
    profile = tmp_path / "profile"
    digest = "abc123"
    assert manifest.lookup(profile, digest) is None

    manifest.record(profile, digest, platform="telegram", path="spool/x.json",
                    messages=7, threads=2, bytes_=99)
    found = manifest.lookup(profile, digest)
    assert found["platform"] == "telegram"
    assert found["messages"] == 7
    assert found["ingested_at"]

    assert manifest.forget(profile, digest) is True
    assert manifest.lookup(profile, digest) is None


def test_broken_manifest_is_empty_not_fatal(tmp_path):
    """A half-written file must not stop an ingest."""
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / manifest.MANIFEST_FILE).write_text("{not json", encoding="utf-8")
    assert manifest.load(profile) == {}


def test_preview_reports_new_then_duplicate(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    profile = tmp_path / "profile"
    _telegram(spool / "result.json")

    first = ingest_module.preview(root=spool, profile_dir=profile)
    assert first["duplicates"] == 0
    assert first["legs"][0]["platform"] == "telegram"
    assert first["legs"][0]["duplicate"] is False
    assert first["legs"][0]["bytes"] > 0

    digest = manifest.fingerprint(spool / "result.json")
    manifest.record(profile, digest, platform="telegram",
                    path=str(spool / "result.json"), messages=3, threads=1, bytes_=10)

    second = ingest_module.preview(root=spool, profile_dir=profile)
    assert second["duplicates"] == 1
    assert second["legs"][0]["duplicate"] is True
    assert second["legs"][0]["previous_messages"] == 3


def test_preview_never_writes(tmp_path):
    """Read-only means the store and the manifest are untouched."""
    spool = tmp_path / "spool"
    spool.mkdir()
    profile = tmp_path / "profile"
    _telegram(spool / "result.json")

    ingest_module.preview(root=spool, profile_dir=profile)
    assert not (profile / manifest.MANIFEST_FILE).exists()


def test_preview_flags_a_large_file(tmp_path, monkeypatch):
    """Size is reported so the UI can warn before the copy, not after it."""
    spool = tmp_path / "spool"
    spool.mkdir()
    _telegram(spool / "result.json")

    monkeypatch.setattr(ingest_module, "LARGE_FILE_BYTES", 1)
    result = ingest_module.preview(root=spool, profile_dir=tmp_path / "profile")
    assert result["legs"][0]["large"] is True


def test_preview_marks_unrecognised_without_fingerprinting(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "notes.txt").write_text("not an export", encoding="utf-8")

    result = ingest_module.preview(root=spool, profile_dir=tmp_path / "profile")
    leg = result["legs"][0]
    assert leg["recognised"] is False
    assert leg["fingerprint"] == ""
    assert result["unrecognised"] == 1
