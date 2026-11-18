"""`canon.py` — one pipe, four kinds of name.

The cases here are the ones real exports actually contain, not invented ones. Each
group states the *rule* being tested, because the rule is the thing that must not
regress: a merge is a claim that two spellings are one entity, and a wrong claim is
worse than a missed one.

Run: python -m pytest tests/test_canon.py -q
"""
from __future__ import annotations

import pytest

from relate_comms import canon


# --------------------------------------------------------------------- person: exact

@pytest.mark.parametrize("raw", ["David Sartori", "david sartori", "DAVID SARTORI",
                                 "  David   Sartori  "])
def test_case_and_spacing_never_make_a_second_person(raw):
    assert canon.canonical(raw).key == "david sartori"


def test_diacritics_are_stripped_not_transliterated():
    # NFKD, not unidecode: `é` becomes `e`, it does not become a different spelling.
    assert canon.canonical("Cédric Balli").key == "cedric balli"
    assert canon.canonical("Adrián Pérez Hernández").key == "adrian perez hernandez"


def test_cyrillic_survives_as_its_own_letters():
    # A name in a non-Latin script must not be mangled into nonsense.
    assert canon.canonical("Иван Петров").key == "иван петров"


# ------------------------------------------------------------------ person: nickname

@pytest.mark.parametrize("short,long_", [
    ("Dave Sartori", "David Sartori"),
    ("Pete Bromill", "Peter Bromill"),
    ("Bob Murphy", "Robert Murphy"),
    ("Bill Bunt", "William Bunt"),
    ("Steve Mikano", "Stephen Mikano"),
    ("Jim Webb", "James Webb"),
    ("Liz Taylor", "Elizabeth Taylor"),
])
def test_nickname_resolves_to_one_key(short, long_):
    assert canon.canonical(short).key == canon.canonical(long_).key


def test_nickname_evidence_is_recorded():
    assert canon.canonical("Dave Sartori").evidence == "nickname"
    assert canon.canonical("David Sartori").evidence == "raw"


def test_a_surname_that_looks_like_a_nickname_is_left_alone():
    # Only the first token is nickname-resolved, so a surname `Will` stays `Will`.
    assert canon.canonical("Anna Will").key == "anna will"


# -------------------------------------------------------------------- person: camel

def test_missing_space_is_a_formatting_accident():
    assert canon.canonical("PeteBromill").key == canon.canonical("Pete Bromill").key
    assert canon.canonical("PeteBromill").evidence == "camel"


# --------------------------------------------------------------- person: credentials

@pytest.mark.parametrize("raw,expected", [
    ("John Samoska, CPA", "john samoska"),
    ("Richard Freishtat, Ph.D.", "richard freishtat"),
    ("Steve Mikano CIA, AIC-M, AINS, SSBB", "stephen mikano"),
    ("Michael DeNegris, AIC, AINS", "michael denegris"),
])
def test_trailing_credentials_are_stripped(raw, expected):
    assert canon.canonical(raw).key == expected


def test_a_credential_never_empties_the_name():
    # `CPA` alone is not a person, but it must not become an empty key either.
    assert canon.canonical("CPA").key == "cpa"


# ----------------------------------------------------------------- person: phone/email

def test_a_phone_number_is_its_digits():
    # WhatsApp states only a number, never a contact name.
    assert canon.canonical("+27 84 518 9029").key == "27845189029"
    assert canon.canonical("+1 (917) 400-4025").key == "19174004025"
    assert canon.canonical("+27 84 518 9029").evidence == "phone"


def test_an_address_is_lowercased():
    assert canon.canonical("DaveSartori@Gmail.com").key == "davesartori@gmail.com"
    assert canon.canonical("davesartori@gmail.com").evidence == "email"


# ------------------------------------------------------------------- person: placeholder

@pytest.mark.parametrize("raw", ["Facebook user", "LinkedIn Member", "You", "(Unknown)",
                                 "LinkedIn Talent Solutions"])
def test_placeholders_are_marked_never_merged(raw):
    record = canon.canonical(raw)
    assert record.is_placeholder
    assert record.key.startswith("placeholder:")


def test_a_placeholder_keeps_its_display_form():
    # The caller attaches it to a per-platform pseudo-node; it must stay readable.
    assert canon.canonical("Facebook user").display == "Facebook user"


# ---------------------------------------------------------------------------- owner

def test_the_owner_is_never_a_node():
    owner = ["user1426445212", "Axiom LoftCoin", "david sartori",
             "davesartori@gmail.com", "+19174004025"]
    for raw in owner:
        assert canon.canonical(raw, owner=owner).is_owner, raw


def test_the_owner_guard_survives_a_nickname_spelling():
    # The profile says `David Sartori`; the export says `Dave Sartori`.
    assert canon.canonical("Dave Sartori", owner=["David Sartori"]).is_owner
    assert canon.canonical("DAVE SARTORI", owner=["David Sartori"]).is_owner


def test_the_owner_guard_compares_phone_digits_not_formatting():
    assert canon.canonical("+1 (917) 400-4025", owner=["19174004025"]).is_owner


def test_a_different_person_is_not_the_owner():
    assert not canon.canonical("Dave Webb", owner=["David Sartori"]).is_owner
    assert canon.canonical("Dave Webb", owner=["David Sartori"]).key == "david webb"


# --------------------------------------------------------------------- organization

@pytest.mark.parametrize("raw", ["ABC Corp", "ABC Corporation", "ABC Corp.", "abc corp",
                                 "ABC Corp, Inc."])
def test_legal_forms_collapse(raw):
    assert canon.canonical(raw, kind="organization").key == "abc"


@pytest.mark.parametrize("raw", ["Northwind & Co", "Northwind and Co", "Northwind Co"])
def test_conjunctions_and_legal_forms_collapse(raw):
    assert canon.canonical(raw, kind="organization").key == "northwind"


def test_a_legal_suffix_alone_is_not_an_organisation():
    assert canon.canonical("Corp", kind="organization").key == "corp"


def test_different_organisations_stay_apart():
    # `Holdings` is a legal form, so it is stripped like `Corp` — both are `abc`.
    # Two genuinely different companies differ in their *name*, not their suffix.
    assert (canon.canonical("ABC Corp", kind="organization").key
            != canon.canonical("ABC Logistics", kind="organization").key)


# ----------------------------------------------------------------------------- place

@pytest.mark.parametrize("raw", ["New York", "New York, NY", "New York, NY 10001",
                                 "new york"])
def test_a_region_code_and_postal_code_are_not_identity(raw):
    assert canon.canonical(raw, kind="place").key == "new york"


@pytest.mark.parametrize("raw", ["London, UK", "London, United Kingdom", "London"])
def test_a_country_tail_is_not_identity(raw):
    assert canon.canonical(raw, kind="place").key == "london"


def test_a_province_is_identity():
    # `London, Ontario` is not `London`. Only codes and countries are dropped.
    assert canon.canonical("London, Ontario", kind="place").key == "london, ontario"


def test_a_prefix_collision_is_not_a_merge():
    assert (canon.canonical("New York", kind="place").key
            != canon.canonical("New York Mills", kind="place").key)


# ----------------------------------------------------------------------------- thing

@pytest.mark.parametrize("raw", ["Coca-Cola", "Coca Cola", "CocaCola", "coca-cola"])
def test_hyphen_and_space_are_one_product(raw):
    assert canon.canonical(raw, kind="thing").key == "coca cola"


def test_a_leading_article_is_not_identity():
    assert canon.canonical("the Coke account", kind="thing").key == "coke account"


def test_a_product_line_stays_distinct():
    assert (canon.canonical("Coca-Cola", kind="thing").key
            != canon.canonical("Coca-Cola Zero", kind="thing").key)


# ------------------------------------------------------------------------ list split

def test_a_comma_without_a_space_separates_people():
    assert canon.split_list("Nigel Harrison,Anat Malkin,Christian Davis") == [
        "Nigel Harrison", "Anat Malkin", "Christian Davis"]


def test_a_comma_with_a_space_is_inside_one_name():
    assert canon.split_list("Steve Mikano CIA, AIC-M, AINS, SSBB") == [
        "Steve Mikano CIA, AIC-M, AINS, SSBB"]


# --------------------------------------------------------------------------- fuzzy

def test_a_surname_typo_is_reported():
    found = canon.candidates(["Peter Bromill", "Peter Bromil"])
    assert len(found) == 1
    assert found[0].score >= canon.FUZZY_REPORT


def test_a_shared_first_name_is_not_reported():
    # `Will Sell` vs `Will Castellanos` scores 0.72 on token_sort_ratio alone.
    assert canon.candidates(["Will Sell", "Will Castellanos"]) == []


def test_an_initial_is_reported():
    found = canon.candidates(["David Sartori", "Dave S."])
    assert len(found) == 1


def test_a_nickname_pair_is_not_reported_because_it_already_merged():
    # `Bob Murphy` and `Robert Murphy` share one key, so there is no pair to report.
    assert canon.candidates(["Bob Murphy", "Robert Murphy"]) == []


def test_candidates_are_never_applied():
    # The function returns records; it does not mutate or merge anything.
    names = ["Peter Bromill", "Peter Bromil"]
    before = [canon.canonical(n).key for n in names]
    canon.candidates(names)
    assert [canon.canonical(n).key for n in names] == before


def test_placeholders_are_excluded_from_candidates():
    assert canon.candidates(["Facebook user", "Facebook User"]) == []


# ------------------------------------------------------------------------ invariants

def test_canonical_is_idempotent():
    for raw, kind in [("Dave Sartori", "person"), ("ABC Corp, Inc.", "organization"),
                      ("New York, NY", "place"), ("Coca-Cola", "thing")]:
        once = canon.canonical(raw, kind=kind).key
        assert canon.canonical(once, kind=kind).key == once


def test_an_empty_name_is_an_empty_key():
    assert canon.canonical("").key == ""
    assert canon.canonical(None).key == ""


def test_display_always_keeps_the_original_spelling():
    # The key is for merging; the display is what the UI shows.
    record = canon.canonical("Dave Sartori")
    assert record.display == "Dave Sartori"
    assert record.key == "david sartori"
