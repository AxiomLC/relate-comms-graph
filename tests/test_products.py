"""The product index and the arbitration ladder.

The contract:

    products.decide()   a categorical verdict, first rule wins, no weights
    extract._arbitrate  the model's label may be overruled, in one direction only

What these tests pin, and why each one matters:

  * a generic noun is never a Product, in any casing  — `seat` appears in ordinary chat
  * a plain name is a Product on sight                — this is the recall the index buys
  * a context-gated name needs a commercial sentence  — `Support Plan` vs `support`
  * an ORG span is never demoted                      — `Grafana Labs` keeps its company
  * the flag is a hard gate                           — model output cannot leak through

Run: python -m pytest tests/test_products.py -q
"""
from __future__ import annotations

import pytest

from relate_comms import canon, extract, products

# ------------------------------------------------------------------ the ladder


@pytest.mark.parametrize("text", ["Grafana", "grafana", "GRAFANA", "Docker", "Excel"])
def test_a_plain_name_is_a_product_on_sight(text):
    """Case never matters: the index matches on `canon`'s key, which casefolds."""
    assert products.decide(text, "no context at all")[0] is True


@pytest.mark.parametrize("text", ["Seat", "seat", "SEAT", "Contract", "SLA", "Credits"])
def test_a_generic_noun_is_never_a_product(text):
    """The precision guard. `canon` folds `Seat`/`seat` to one key, so this must live here.

    Every one of these is a genuine common noun that the sample generator also lists as a
    product, which is exactly why the live store already has `organization:seat`-shaped
    noise. Ten of the 100 generated product names are in this class.
    """
    verdict, reason = products.decide(text, "the renewal quote is due")
    assert verdict is False
    assert reason == "generic noun"


def test_the_generic_reason_is_reported_not_masked_by_the_index():
    """`seat` is not IN the index, so an index-first ladder would say "not indexed".

    The verdict was right either way; the *reason* was wrong, and the reason is what lands
    in provenance. Generics are checked first for that reason alone.
    """
    assert products.lookup("Seat") is None
    assert products.decide("Seat", "anything") == (False, "generic noun")


def test_a_stranger_is_not_a_product():
    assert products.decide("Retool", "we use Retool daily") == (False, "not indexed")


def test_a_context_gated_name_needs_a_commercial_sentence():
    assert products.decide("Support Plan", "the support plan renewal is due")[0] is True
    assert products.decide("Support Plan", "I like the support plan")[0] is False


def test_context_cues_are_commercial_words_only():
    """`seat` and `contract` were cues once, and promoted every gated entry in the body.

    `a seat by the window` has no procurement in it, so it must not satisfy the test.
    """
    assert products.has_context("the renewal is due") is True
    assert products.has_context("can you get me a Xeon") is False
    assert products.has_context("a seat by the window") is False


def test_context_matching_is_word_bounded():
    """`renew` must not fire on `renewable`, and `deploy` must not fire on `employment`."""
    assert products.has_context("renewable energy") is False
    assert products.has_context("employment law") is False


# ---------------------------------------------------------------------- the index


def test_every_index_key_is_what_canon_produces():
    """The index and the store must agree on a key, or a Product node looks up as a miss."""
    for key, entry in products.INDEX.items():
        assert canon.canonical(entry.display, kind="product").key == key


def test_no_generic_word_survives_into_the_index():
    for word in products.GENERIC:
        assert word not in products.INDEX, word


def test_hyphen_and_case_variants_converge():
    """`canon` folds hyphens for products, so the index gets it for free."""
    assert products.lookup("coca-cola") is products.lookup("Coca Cola")
    assert products.lookup("Irn-Bru") is products.lookup("irn bru")


# ----------------------------------------------------------------- arbitration


def test_a_place_span_can_be_reclaimed_as_a_product(monkeypatch):
    """The 29 mislabelled nodes: `place:tableau`, `place:gemini`, `place:pulsar`.

    A product name is routinely read as a place (`I'm at Grafana Labs all week` is a
    GPE), and in a professional corpus the product reading is usually right.
    """
    monkeypatch.setattr(extract, "PRODUCT_ENABLED", True)
    kind, candidates = extract._arbitrate("Tableau", "GPE", "the Tableau renewal is due")
    assert kind == "product"
    assert candidates[0] == "product"
    assert "place" in candidates, "the model's own label stays as a candidate"


def test_an_org_span_is_never_demoted_to_a_product(monkeypatch):
    """`Grafana Labs` the company contains `Grafana` the product. The company is real too."""
    monkeypatch.setattr(extract, "PRODUCT_ENABLED", True)
    kind, _ = extract._arbitrate("Grafana Labs", "ORG", "I'm at Grafana Labs all week")
    assert kind == "organization"


def test_with_the_flag_off_a_gpe_stays_a_place(monkeypatch):
    monkeypatch.setattr(extract, "PRODUCT_ENABLED", False)
    assert extract._arbitrate("Tableau", "GPE", "the Tableau renewal is due")[0] == "place"


def test_the_model_product_label_is_gated_by_the_flag(monkeypatch):
    """`en_core_web_sm` does emit `PRODUCT`; the flag must stop it reaching the store.

    Without the gate the mention would pass arbitration and then be dropped by the
    writer's `kinds=` filter — vanishing between two layers that each looked correct.
    """
    body = "I've moved everything onto Ansible."

    monkeypatch.setattr(extract, "PRODUCT_ENABLED", False)
    assert [m for m in extract.extract([("k", "p", body)]) if m.kind == "product"] == []

    monkeypatch.setattr(extract, "PRODUCT_ENABLED", True)
    products_found = [m for m in extract.extract([("k", "p", body)]) if m.kind == "product"]
    assert products_found, "the model does label this body PRODUCT; the gate is the only change"
    assert products_found[0].text == "Ansible"


def test_the_model_product_label_is_frame_sensitive():
    """Documented because it is the whole argument for the index.

    The same name in a different frame proposes nothing at all. This is not a bug to fix —
    it is why a dictionary is needed rather than a better prompt.
    """
    found = extract._NLP("I've moved everything onto Ansible.").ents
    missing = extract._NLP("Ansible keeps falling over.").ents
    assert any(e.label_ == "PRODUCT" for e in found)
    assert not any(e.text == "Ansible" for e in missing)


def test_arbitration_needs_the_body_not_just_the_span():
    """A gated entry is a product only in a procurement sentence, so the call must carry it."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(extract, "PRODUCT_ENABLED", True)
        assert extract._arbitrate("Support Plan", "GPE", "the support plan renewal is due")[0] == "product"
        assert extract._arbitrate("Support Plan", "GPE", "I like the support plan")[0] == "place"
