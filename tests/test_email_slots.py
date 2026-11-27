"""One mailbox, four keys, no provider table.

The bug this replaces: `w57th.agency` resolved to the pseudo-provider `custom`, which
`account_from_env` refused — and the refusal was printed to stderr and swallowed, so the
ingest reported success with zero messages. Four fixed keys leave nothing to guess.
"""
from __future__ import annotations

import pytest

from relate_comms.adapters import email_imap


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Never read the real `.env` — it holds a configured mailbox."""
    monkeypatch.setattr(email_imap, "_dotenv", lambda environ=None: {})


def test_there_is_one_set_of_keys():
    assert email_imap.IMAP_KEYS == (
        "IMAP_EMAIL", "IMAP_PASSWORD", "IMAP_HOST", "IMAP_PORT",
    )


def test_slot_keys_ignores_its_argument():
    """`slot` is kept for callers that still pass one; it is not a choice."""
    assert email_imap.slot_keys() == email_imap.IMAP_KEYS
    assert email_imap.slot_keys("email") == email_imap.IMAP_KEYS
    assert email_imap.slot_keys("gmail") == email_imap.IMAP_KEYS


def test_a_configured_mailbox_resolves(monkeypatch):
    monkeypatch.setenv("IMAP_EMAIL", "dev@w57th.agency")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("IMAP_HOST", "imap.hostinger.com")
    monkeypatch.setenv("IMAP_PORT", "993")

    assert email_imap.account_from_slot() == {
        "host": "imap.hostinger.com",
        "user": "dev@w57th.agency",
        "password": "secret",
        "port": "993",
    }


def test_a_custom_domain_needs_no_table(monkeypatch):
    """The whole point: any domain works, because the host is given, not derived."""
    monkeypatch.setenv("IMAP_EMAIL", "someone@nowhere-at-all.example")
    monkeypatch.setenv("IMAP_PASSWORD", "pw")
    monkeypatch.setenv("IMAP_HOST", "mail.nowhere-at-all.example")

    assert email_imap.account_from_slot()["host"] == "mail.nowhere-at-all.example"


def test_gmail_is_not_a_special_case(monkeypatch):
    monkeypatch.setenv("IMAP_EMAIL", "someone@gmail.com")
    monkeypatch.setenv("IMAP_PASSWORD", "pw")
    monkeypatch.setenv("IMAP_HOST", "imap.gmail.com")

    assert email_imap.account_from_slot()["host"] == "imap.gmail.com"


def test_a_missing_key_names_itself(monkeypatch):
    for name in email_imap.IMAP_KEYS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="IMAP_EMAIL"):
        email_imap.account_from_slot()


def test_app_password_spaces_are_stripped(monkeypatch):
    monkeypatch.setenv("IMAP_EMAIL", "someone@gmail.com")
    monkeypatch.setenv("IMAP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("IMAP_HOST", "imap.gmail.com")

    assert email_imap.account_from_slot()["password"] == "abcdefghijklmnop"
