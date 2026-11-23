"""The product index — the vocabulary that lets a span be claimed as a Product.

WHY A DICTIONARY AT ALL
-----------------------
Recall for this kind is a dictionary problem, and the dictionary is the feature.

**Corrected 2026-11-23:** `en_core_web_sm` *does* have a `PRODUCT` label — the earlier note
in this repo said it did not, and that was wrong. What it has is a deeply unreliable one.
Measured on the sample corpus: of 77 known product names present in message bodies it
proposes no span at all for **23** — every lowercase spelling (`the excel renewal`,
`iphone`, `rtx`, `gguf`) and most capitalised but contextless names (`Temporal`,
`Grafana`, `Surface Pro`, `Pixel`, `Raspberry Pi`).

Its `PRODUCT` label is also **frame-sensitive**, exactly like the `GPE` false positives
already documented in `extract.py`: `"I've moved everything onto Ansible."` is labelled
`PRODUCT`, while `"Ansible keeps falling over."` proposes nothing. A label that fires on
one preposition and not another is not a taxonomy, it is a coincidence.

So the index is not compensating for an absent label — it is compensating for an
**unreliable** one, which is the same argument `PLACE_DICTIONARY` and `ORG_DICTIONARY`
rest on. There is no rule that reads `the excel renewal is due` and decides `Excel` is a
name without already knowing it.

But a dictionary alone is precision-hostile, which is the other half of the design:

WHAT THE INDEX IS NOT
---------------------
`canon.canonical(kind="product")` folds `Seat` and `seat` to the same key `seat`. That is
correct — it is a spelling function. It cannot know that one of those is a licence concept
and the other is furniture. **The generic block therefore lives here, not in `canon`.**

A case-insensitive dictionary match on `seat`, `contract`, `credits`, `rack`, `switch` would
manufacture a junk node for every ordinary sentence. Measured on the live store: ten of the
sample generator's 100 product names are common nouns, and they already exist as
`organization:sla`, `organization:seat`-shaped noise.

THE THREE TIERS
---------------
Each tier exists because a rule in `arbitrate()` consumes it. A field nothing reads would
be a field to maintain for no reason.

    Tier 1  blocked generics    never a standalone product   `seat`, `sla`, `credits`
    Tier 2  context-gated       a product only with a cue     `support plan`, `free tier`
    Tier 3  plain names         a product on sight            `grafana`, `raspberry pi`

**A vendor is not a product.** `Grafana Labs` was removed from the index on 2026-11-23:
the company ships `Grafana`, and listing both made `I'm at Grafana Labs all week` mint a
Product node for a premises. `Snowflake` and `Databricks` stay because the words *are* the
product — there is no separate product name — which is the same ambiguity §5 open decision 2
records.

WHERE ENTRIES COME FROM
-----------------------
Hand-typed, for now, deliberately. The fuzz generator's `PRODUCT_LISTS` is the seed because
it is the only labelled product vocabulary this repo has, and the tier assignment is a human
judgement a generator cannot make: nothing in a package registry says `Seat` is a bad node
and `Slack Connect` is a good one.

`rework_extraction.md` §4 step 3 records the intended generation sources (the live graph's
own mislabelled nodes, package registries, vendor catalogues) and why each was deferred:
registries bias hard toward a developer's vocabulary, and the live graph cannot seed a
correction until the corrections exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from .canon import canonical

# --------------------------------------------------------------------------- entries


@dataclass(frozen=True)
class ProductEntry:
    """One known product name, and how confident the index is about it.

    Deliberately small. `vendor`, `kind`, `source[]` and `version` all appeared in the
    design notes and all were dropped: nothing in the rule ladder reads them, and a field
    with no reader is a field that rots.
    """

    display: str
    key: str
    # A product only when the sentence is about procurement, deployment or licensing.
    requires_context: bool = False


def _entry(display: str, **kwargs) -> ProductEntry:
    """Build an entry whose key is `canon`'s, so the index and the store cannot disagree."""
    return ProductEntry(display=display, key=canonical(display, kind="product").key, **kwargs)


# Tier 1 — common nouns that are ALSO product names. Never a standalone Product node.
#
# Each of these appears in the sample generator's product list because a body says
# `can you get me a {product} seat?` — which is also exactly why `organization:seat` and
# `organization:sla` exist as junk in the live store. Blocking them here is the fix for
# that noise, and it must happen in the index because `canon` sees only a spelling.
GENERIC: frozenset[str] = frozenset({
    "seat", "contract", "credits", "credit", "sla", "rack", "switch", "san", "ups",
    "nas", "embeddings", "embedding", "support", "plan", "tier", "storage",
})

# Tier 2 — a real product name that is also ordinary English. A Product only when the
# body is talking about buying, renewing, deploying or being licensed something.
_CONTEXT_GATED: tuple[str, ...] = (
    "Support Plan", "Enterprise Licence", "Free Tier", "Onboarding Pack",
    "Migration Kit", "Cold Storage", "Training Day", "Tape Library",
)

# Tier 3 — names that are a product on sight. Multi-token entries are protected phrases
# by construction: `slack connect` cannot be confused with an ordinary sentence.
_PLAIN: tuple[str, ...] = (
    # SaaS and developer tooling
    "Databricks Lakehouse", "Snowflake Cortex", "Tableau", "Power BI", "Looker",
    "Excel", "Sheets", "Notion Calendar", "Slack Connect", "Teams", "Zoom Rooms",
    "Jira", "Confluence", "GitHub Copilot", "VS Code", "Cursor", "Vim", "Emacs",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Prometheus", "Grafana",
    "Kafka", "Spark", "Airflow", "dbt Core", "Temporal", "Pulsar", "Flink", "Nginx",
    "Apache", "Redis Enterprise", "Elasticsearch", "OpenSearch", "Snowflake",
    "Databricks",
    # Hardware and SKUs
    "MacBook Pro", "ThinkPad", "Surface Pro", "Pixel", "iPhone", "Galaxy",
    "Raspberry Pi", "Jetson Orin", "DGX Station", "Threadripper", "Xeon", "EPYC",
    "Apple Silicon", "Radeon", "GeForce", "RTX", "Ryzen", "NVMe", "SSD", "RAID",
    "Router", "Patch Panel", "PDU",
    # AI models and runtimes
    "Claude", "GPT-4", "Llama", "Mistral Large", "Gemini", "Whisper",
    "Stable Diffusion", "Ollama", "vLLM", "gguf", "LoRA", "RAG",
    # Consumer brands — ordinary chat, and genuinely products
    "Coca-Cola", "Diet Coke", "Sprite", "Fanta", "Powerade", "Monster Energy",
    "Weetabix", "Marmite", "Irn-Bru", "Yorkshire Tea",
    # Commercial artefacts that name a specific SKU rather than a category
    "Migration Kit", "Enterprise Licence",
)

def _build(
    plain: tuple[str, ...], gated: tuple[str, ...],
) -> dict[str, ProductEntry]:
    """Assemble the index, dropping anything that a harder tier already owns.

    Precedence is **generic > context-gated > plain**, so a name cannot be listed twice
    and a plain entry can never shadow a gated one. Listing `Migration Kit` in both
    tuples is therefore harmless, which is why it is (it reads as a SKU and as a
    generic pack).
    """
    index: dict[str, ProductEntry] = {}
    for name in gated:
        entry = _entry(name, requires_context=True)
        if entry.key not in GENERIC:
            index[entry.key] = entry
    for name in plain:
        entry = _entry(name)
        if entry.key not in GENERIC and entry.key not in index:
            index[entry.key] = entry
    return index


INDEX: dict[str, ProductEntry] = _build(_PLAIN, _CONTEXT_GATED)

# Words that make a body about procurement, deployment or licensing rather than chat.
#
# **`seat` and `contract` are deliberately absent**, though both are obvious procurement
# words in a real conversation. They are also furniture and an agreement, so a body
# containing `a seat by the window` would otherwise satisfy the cue test and promote
# every context-gated entry in it. A cue has to be a word that is *only* commercial.
CONTEXT_CUES: frozenset[str] = frozenset({
    "renewal", "renew", "renewed", "licence", "license", "licensed", "quote",
    "pricing", "subscription", "subscribe", "deployment", "deployed", "deploy",
    "instance", "sku", "purchase", "purchased", "bought", "upgrade", "upgraded",
    "migration", "migrated", "trial", "invoice", "invoiced", "billing", "billed",
    "install", "installed", "provision", "provisioned", "vendor", "onboarding",
    "expiry", "expires", "expiring",
})


# ------------------------------------------------------------------------- the ladder


def lookup(text: str) -> ProductEntry | None:
    """The index entry for a span's canonical form, or None. Exact key, never fuzzy.

    A typo'd product name is not folded here on purpose: `Northwnd` and `Northwind` are
    different strings, and a fuzzy product match would let one mistyping mint a second
    node against a dictionary the user never chose. The sample writer's `drop_letter` and
    `swap` variants are documented as producing a second key for exactly this reason.
    """
    return INDEX.get(canonical(text, kind="product").key)


def has_context(body: str) -> bool:
    """Does this text read like procurement, deployment or licensing?

    Word-bounded, case-folded, and deliberately shallow: the cue set is small and boring
    because it is a tie-break, not a classifier. `A seat by the window` has no cue and
    stays furniture; `can you get me a Xeon seat?` does and does not.
    """
    words = set(canonical(body, kind="product").key.split())
    return bool(words & CONTEXT_CUES)


def is_generic(text: str) -> bool:
    return canonical(text, kind="product").key in GENERIC


def decide(text: str, body: str) -> tuple[bool, str]:
    """Is this span a Product in this body? Returns `(verdict, reason)`.

    **The rule ladder, in order, first match wins. No weights.** Most of these decisions
    are categorical, not smoothly tradeable: `seat` is furniture or it is a SKU, and there
    is no score that expresses "blocked unless protected" better than a rule saying so.

        1  not in the index and not generic -> no   (`Retool`, a stranger)
        2  generic, anywhere               -> no   (`seat`)
        3  plain name                      -> yes  (`grafana`, `docker`)
        4  context-gated                   -> yes iff the body is a product sentence
        5  otherwise                        -> no

    **Generics are checked BEFORE the index.** `seat` is in `GENERIC` and deliberately not
    in `INDEX`, so an index-first ladder reported the true verdict for a false reason
    ("not indexed" when the reason is "generic"). Checking the block first keeps the
    reason honest, and the reason is what lands in `Mention.candidates` provenance.

    `reason` is returned for the report and for provenance — a decision nobody can
    explain is worse than no decision.
    """
    if is_generic(text):
        return False, "generic noun"
    entry = lookup(text)
    if entry is None:
        return False, "not indexed"
    if not entry.requires_context:
        return True, "indexed name"
    if has_context(body):
        return True, "indexed + context"
    return False, "needs procurement context"
