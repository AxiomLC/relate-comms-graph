"""Resolution + scrub gate (stage 5/6).

The failure mode this file exists to prevent is a *confident wrong merge*. §3.1: a
guess must look like a guess, so every test here pairs a true duplicate with a
lookalike and asserts the two behave differently.

Run: python -m pytest tests -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from relate_comms import resolution as R
from relate_comms import scrub as S
from relate_comms.adapters import whatsapp
from relate_comms.schema import Chat, IngestResult, Message, make_key

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def cand(platform, handle, **kw):
    return R.candidate_from(platform, handle, **kw)


def people_of(*candidates):
    people, identities = R.merge(candidates)
    return {i.key: i for i in identities}, people


# ------------------------------------------------------------------------ normalising

def test_phone_formats_collapse_to_one_key():
    assert R.norm_phone("+1 (917) 400-4025") == R.norm_phone("19174004025")
    assert R.norm_phone("+27 84 518 9029") == "27845189029"
    assert R.norm_phone("123") is None, "too short to be a phone"


def test_names_normalise_diacritics_and_case():
    assert R.norm_name("Дарья Саяпина") == R.norm_name("ДАРЬЯ САЯПИНА")
    assert R.norm_name("Edgar  González") == R.norm_name("edgar gonzalez")


def test_placeholders_are_never_people():
    for name in ("You", "LinkedIn Member", "Facebook user", "unknown"):
        assert R.is_placeholder(name), name


# ------------------------------------------------------------------- true positives

def test_same_phone_on_two_platforms_is_one_person():
    identities, people = people_of(
        cand("whatsapp", "+1 (917) 400-4025"),
        cand("sms", "917-400-4025"),
    )
    assert len({i.person_key for i in identities.values()}) == 1, \
        "same number must resolve to one person"
    # The first occurrence creates the person (`new`); the second must match on phone.
    assert sorted(i.matched_by for i in identities.values()) == ["new", "phone"]


def test_same_email_is_one_person():
    identities, _ = people_of(
        cand("linkedin", "morgan.davin@n8n.io"),
        cand("email", "morgan.davin@n8n.io"),
    )
    assert len({i.person_key for i in identities.values()}) == 1


def test_identical_name_is_one_person():
    identities, _ = people_of(
        cand("linkedin", "Morgan Davin"),
        cand("messenger", "Morgan Davin"),
    )
    assert len({i.person_key for i in identities.values()}) == 1


def test_name_match_never_exceeds_the_honesty_ceiling():
    """A fuzzy merge must never claim 1.0 (§3.1)."""
    identities, _ = people_of(
        cand("linkedin", "Morgan Davin"),
        cand("messenger", "Morgan  Davin"),
    )
    scores = [i.confidence for i in identities.values() if i.matched_by != "new"]
    assert scores, "expected at least one merged identity"
    assert max(scores) <= R.NAME_MAX


# ------------------------------------------------------------------- false positives

def test_shared_first_name_does_not_merge():
    """Real regression: `Will Sell` was merged into `Will Castellanos`."""
    identities, _ = people_of(
        cand("linkedin", "Will Castellanos"),
        cand("messenger", "Will Sell"),
    )
    assert len({i.person_key for i in identities.values()}) == 2


def test_shared_surname_does_not_merge():
    """Real regression: `Austin Johnson` was merged into `Casey Johnson`."""
    identities, _ = people_of(
        cand("linkedin", "Casey Johnson"),
        cand("messenger", "Austin Johnson"),
    )
    assert len({i.person_key for i in identities.values()}) == 2


def test_single_token_names_never_fuzzy_match():
    assert R._fuzzy("dave", "dave") == 1.0          # exact is exact
    assert R._fuzzy("dave", "dan") == 0.0           # never guess on one token


def test_placeholder_accounts_do_not_become_contacts():
    """8,171 rows of `Facebook user` must not merge into one innocent person."""
    identities, people = people_of(
        cand("messenger", "Facebook user"),
        cand("linkedin", "LinkedIn Member"),
    )
    assert all(i.matched_by == "placeholder" for i in identities.values())
    assert all(p.key.startswith("placeholder:") for p in people)


def test_volume_never_raises_confidence():
    """A spam thread's message count is not evidence; breadth is."""
    loud = cand("messenger", "Spam Bot", is_self=False)
    loud.threads = {f"spam-{i}" for i in range(5000)}
    quiet = cand("messenger", "Real Person")
    quiet.threads = {"t1", "t2", "t3"}
    identities, _ = people_of(loud, quiet)
    assert len({i.person_key for i in identities.values()}) == 2


def test_owner_accounts_merge_across_platforms():
    identities, people = people_of(
        cand("whatsapp", "You", is_self=True),
        cand("messenger", "David Sartori", is_self=True),
        cand("linkedin", "David Sartori"),
    )
    owners = [i for i in identities.values() if i.person_key == "owner"]
    assert len(owners) == 2, "both owner accounts attach to the owner person"
    assert any(p.key == "owner" for p in people)


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
    assert R.norm_phone(aliases.reveal("PHONE-1")) == "19174004025"


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
