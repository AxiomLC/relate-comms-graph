"""Text hygiene before NER.

Measured on the live 224-message mailbox: 8 bodies carried HTML entities, 11 carried tags,
157 opened with a salutation, and 186 contained a scrub alias. Each produced junk nodes —
`Account &amp`, `href="https://help.figma.com`, `Marko Srsan <EMAIL-9>`,
`organization:hello memgraph` beside `organization:memgraph`.

None of it is a model error. The span is exactly what the string said, so no recogniser —
GLiNER included — can classify `&lt;EMAIL-9&gt` correctly. The fix is to stop handing it
over, which is what `fragments()` now does.
"""
from __future__ import annotations

import pytest

from relate_comms import extract


def _texts(body: str) -> list[str]:
    return [f.text for f in extract.fragments(body)]


# ------------------------------------------------------------------ line breaks

def test_a_real_newline_splits_like_an_html_break():
    """Email/Telegram/WhatsApp store `\\n`; Messenger stores `<br>`. Both must split."""
    assert _texts("first line\nsecond line") == ["first line", "second line"]
    assert _texts("first line<br>second line") == ["first line", "second line"]


def test_the_original_body_is_never_modified():
    body = "Hello Onix Networking,\r\n\r\nI built a thing."
    fragment = extract.fragments(body)[0]
    # The greeting is stripped from what the MODEL sees, but the offset still points at
    # the stored body, and the body itself is untouched.
    assert fragment.text == "I built a thing."
    assert body[fragment.offset:].startswith("I built a thing.")
    assert body == "Hello Onix Networking,\r\n\r\nI built a thing."


# ------------------------------------------------------------------ HTML hygiene

@pytest.mark.parametrize("body", [
    "Account &amp Settings",
    "Contact &lt;support&gt; today",
    "Cost&nbsp;is listed",
    "Marko Srsan &lt;EMAIL-9&gt; wrote in",
])
def test_entities_are_decoded_and_tags_removed(body):
    joined = " ".join(_texts(body))
    for junk in ("&amp;", "&amp", "&lt;", "&gt;", "&nbsp;"):
        assert junk not in joined


def test_a_tag_with_a_quoted_url_is_removed_whole():
    body = '<p>Contact <a href="https://help.figma.com/x">Figma</a>.</p>'
    joined = " ".join(_texts(body))
    assert "href" not in joined
    assert "help.figma.com" not in joined
    assert "Figma" in joined


def test_a_dangling_attribute_is_removed():
    """`href="https://help.figma.com` became an Organization on the live store."""
    joined = " ".join(_texts('href="https://help.figma.com and www.memgraph.com/x'))
    assert "href" not in joined
    assert "help.figma.com" not in joined


# ------------------------------------------------------------------ greetings

@pytest.mark.parametrize("body,expect", [
    ("Hello Onix Networking,\n\nI built a thing.", "I built a thing."),
    ("Hi Team,\nWe work with agencies.", "We work with agencies."),
    ("Dear Invitee,\n\nYou are invited.", "You are invited."),
    ("Hello,\n\nThanks for contacting Pinecone.", "Thanks for contacting Pinecone."),
])
def test_a_leading_salutation_is_dropped(body, expect):
    assert _texts(body)[0] == expect


def test_a_quoted_greeting_is_dropped_too():
    """A reply quotes the original; the greeting then sits mid-text, after `wrote:`.

    The company name lived ONLY in the greeting here, so removing the greeting removes
    the name from that fragment entirely — which is the point. On the live store the
    real `organization:memgraph` still exists, from the message that mentions it in
    prose; what goes away is the second node spelled `Hello Memgraph`.
    """
    body = ("Marko, thanks! Two things.\n\nOn Mon David <EMAIL-1> wrote:\n\n"
            "> Hello Memgraph team,\n>\n> I built Frontal Lobe.")
    joined = " ".join(_texts(body))
    assert "Hello Memgraph" not in joined
    assert "Frontal Lobe" in joined
    assert "thanks!" in joined


def test_a_greeting_mid_sentence_is_not_a_greeting():
    """`I said hello to Marko` must survive — only a line-start salutation is dropped."""
    assert "hello to Marko" in " ".join(_texts("I said hello to Marko yesterday."))


# ------------------------------------------------------------------ scrub aliases

def test_a_scrub_alias_never_becomes_an_entity():
    """`EMAIL-1` became a Place and `EMAIL-9` an Organization on the live store."""
    mentions = extract.extract([
        ("k1", "email", "Marko Srsan EMAIL-9 wrote about Memgraph."),
        ("k2", "email", "Forward to EMAIL-1 please."),
    ])
    for m in mentions:
        assert "EMAIL" not in m.text.upper()
