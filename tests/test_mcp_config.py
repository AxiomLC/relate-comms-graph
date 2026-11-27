"""The MCP surface's two keys and the path rule.

These are the gate tests, and they run with no transport at all — which is why the config
module is built before the server. Every case here must **fail closed**: no key, a wrong
key, or a path outside the repo is a refusal, never a default.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mcp import config


@pytest.fixture()
def profile(tmp_path, monkeypatch):
    """Point the key file at a scratch profile."""
    monkeypatch.setattr(config.paths, "profile_dir", lambda: tmp_path / "profile")
    monkeypatch.delenv(config.KEY_ENV, raising=False)
    return tmp_path / "profile"


# ------------------------------------------------------------------ key file

def test_first_run_generates_two_distinct_keys(profile):
    data = config.load()
    assert data["read_key"].startswith("r_")
    assert data["write_key"].startswith("w_")
    assert data["read_key"] != data["write_key"]
    assert (profile / "mcp.json").exists()


def test_keys_are_stable_across_reads(profile):
    first = config.load()
    second = config.load()
    assert first == second


def test_a_malformed_file_is_regenerated(profile):
    path = profile / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    data = config.load()
    assert data["read_key"] and data["write_key"]
    assert json.loads(path.read_text(encoding="utf-8")) == data


def test_a_file_missing_a_key_is_regenerated(profile):
    path = profile / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"read_key": "r_only"}), encoding="utf-8")

    data = config.load()
    assert data["write_key"].startswith("w_")


# ------------------------------------------------------------------ levels

def test_no_key_is_no_access(profile):
    assert config.resolve(None) is None


def test_empty_key_is_no_access(profile):
    assert config.resolve("") is None


def test_read_key_grants_read(profile):
    assert config.resolve(config.load()["read_key"]) == "read"


def test_write_key_grants_write(profile):
    assert config.resolve(config.load()["write_key"]) == "write"


def test_a_wrong_key_grants_nothing(profile):
    config.load()
    assert config.resolve("r_not_the_key") is None


def test_the_key_comes_from_the_environment(profile, monkeypatch):
    data = config.load()
    monkeypatch.setenv(config.KEY_ENV, data["read_key"])
    assert config.resolve() == "read"


def test_an_absent_environment_variable_is_no_access(profile):
    config.load()
    assert config.resolve() is None


def test_whitespace_around_the_key_is_tolerated(profile, monkeypatch):
    data = config.load()
    monkeypatch.setenv(config.KEY_ENV, f"  {data['write_key']}\n")
    assert config.resolve() == "write"


# ------------------------------------------------------------------ paths

def test_the_repo_root_is_allowed():
    assert config.path_allowed(config.REPO_ROOT)


def test_the_spool_is_allowed():
    assert config.path_allowed(config.paths.real_dir())


def test_sample_writer_out_is_allowed():
    assert config.path_allowed(config.REPO_ROOT / "sample_writer" / "out")


def test_a_path_outside_the_repo_is_refused():
    assert not config.path_allowed(Path.home() / "Downloads")


def test_dotdot_cannot_walk_out_of_the_repo():
    assert not config.path_allowed(config.REPO_ROOT / ".." / ".." / "Windows")


def test_a_nonexistent_path_inside_the_repo_is_allowed():
    """`stage()` raises its own FileNotFoundError, which is a better message."""
    assert config.path_allowed(config.REPO_ROOT / "spool" / "real" / "nope.zip")
