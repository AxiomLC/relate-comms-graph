"""The scrub gate: keep / hide / block, applied before anything is written.

Split out of `test_resolution_scrub.py` when the identity resolver was removed — the
gate is live code, the resolver was not.

Run: python -m pytest tests/test_scrub.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import canon
from relate_comms import scrub as S
from relate_comms.adapters import whatsapp
from relate_comms.schema import Chat, IngestResult, Message, make_key

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ----------------------------------------------------------------------- scrub gate

def _result(bodies: list[str]) -> IngestResult:
    result = IngestResult(platform="whatsapp", export_path="test")
    result.chats.append(Chat(platform="whatsapp", chat_id="c1", title="T",
                             kind="personal_chat", is_group=False))
    for i, body in enumerate(bodies):
        key = make_key("whatsapp", "c1", str(i))
        result.messages.append(Message(
            key=key, platform="whatsapp", chat_id="c1", message_id=str(i),
            ts_utc=BASE + timedelta(seconds=i), sender_name="Alice", sender_id=None,
            body=body, reply_to=None, has_attachments=False, is_self=False,
            raw_kind="text",
        ))
    return result


def test_phone_is_hidden_with_a_stable_alias():
    result, report, aliases = S.scrub_result(
        _result(["call +1 (917) 400-4025", "again 19174004025"]))
    assert "917" not in result.messages[0].body
    assert "PHONE-1" in result.messages[0].body
    assert "PHONE-1" in result.messages[1].body, "same number, same alias"
    assert report.hidden.get("phones") == 2
    # `reveal` returns the first spelling seen; the normalised form is the key.
    assert canon.phone_digits(aliases.reveal("PHONE-1")) == "19174004025"


def test_email_and_address_are_hidden():
    result, report, _ = S.scrub_result(
        _result(["mail morgan.davin@n8n.io", "meet 2261 Gulf to Bay Blvd, #335"]))
    assert "@n8n.io" not in result.messages[0].body
    assert "EMAIL-1" in result.messages[0].body
    assert "Gulf to Bay" not in result.messages[1].body
    assert report.hidden.get("emails") == 1
    assert report.hidden.get("addresses") == 1


def test_block_refuses_the_message_and_logs_it():
    result, report, _ = S.scrub_result(
        _result(["call +1 (917) 400-4025", "harmless"]),
        policy={"phones": S.Verdict.BLOCK},
    )
    assert len(result.messages) == 1
    assert result.messages[0].body == "harmless"
    assert report.refused_messages == 1
    assert report.blocked.get("phones") == 1
    assert report.refused_samples[0]["kind"] == "phones"


def test_keep_leaves_everything_alone():
    result, report, aliases = S.scrub_result(
        _result(["call +1 (917) 400-4025"]),
        policy={k: S.Verdict.KEEP for k in S.DEFAULT_POLICY})
    assert result.messages[0].body == "call +1 (917) 400-4025"
    assert report.withheld_total == 0
    assert aliases.size == 0


def test_ordinary_numbers_are_not_scrubbed():
    """Years, counts and short numbers must survive: over-scrubbing destroys meaning."""
    body = "we met in 2026, 911 times, order 12345"
    result, report, _ = S.scrub_result(_result([body]))
    assert result.messages[0].body == body
    assert report.withheld_total == 0


def test_message_key_is_unchanged_by_scrubbing():
    """Scrub must not re-key a message, or re-ingest would duplicate it."""
    before = _result(["call +1 (917) 400-4025"])
    original_key = before.messages[0].key
    after, _, _ = S.scrub_result(before)
    assert after.messages[0].key == original_key


def test_luhn_rejects_ids_that_look_like_cards():
    """Real regression: Facebook ids in URLs were aliased as card numbers.

    `facebook.com/reel/2777889439060846` was mangled, breaking the link the graph
    exists to preserve, and inflated the withheld count from 12 to 150.
    """
    assert S.luhn_ok("4111111111111111") is True
    assert S.luhn_ok("2777889439060846") is False
    assert S.luhn_ok("61557936115389") is False

    body = "see https://facebook.com/reel/2777889439060846 ok"
    result, report, _ = S.scrub_result(_result([body]))
    assert result.messages[0].body == body, "a URL must survive scrubbing intact"
    assert report.hidden.get("card_numbers") is None


def test_real_card_number_is_still_hidden():
    result, report, _ = S.scrub_result(_result(["card 4111 1111 1111 1111"]))
    assert "4111" not in result.messages[0].body
    assert "CARD-1" in result.messages[0].body


def test_input_result_is_not_mutated():
    before = _result(["call +1 (917) 400-4025"])
    S.scrubbed_copy(before)
    assert before.messages[0].body == "call +1 (917) 400-4025"
