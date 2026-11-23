# Brief: build three entity lists for a personal communications graph

You are writing lists for an app that reads a person's exported chat history and builds a
graph of **who they talk to, what they talk about, and where**. All processing is local. The
lists you produce become a dictionary the extractor consults when reading message bodies.

Read this whole brief before writing anything. The *constraints* matter more than the volume,
and there are specific failure modes described at the end that have already bitten us.

---

## What the app does

A user drops their exported messages into the app — WhatsApp, Telegram, Facebook Messenger,
LinkedIn, SMS, email, Outlook. It parses them into a graph:

```
Thread ──> Correspondent        (who)
Thread ──> Message ──> Entity   (what was said, and what it named)
```

The entity kinds are **Place**, **Organization** and **Product**. There is no Person kind:
people come from message senders, not from reading the text.

The reading is done by a small NLP model (`spacy`'s `en_core_web_sm`). It guesses entity
types from sentence shape, and it guesses wrong constantly: it labels the city `Austin` as a
person, the software `Grafana` as a person, and the company `Databricks` as a place. So the
app carries hand-written dictionaries that run **before** the model and win. That is what you
are writing.

## Who the users are

**Professionals and technical people** — the kind of person who has a work Slack, a dozen
SaaS subscriptions, and also a car, a mortgage and opinions about coffee. Their messages are
roughly half ordinary personal life and half work.

This matters for the product list specifically. An earlier version of our test data was
overwhelmingly software names — enterprise data platforms, CLI tools, GPU part numbers —
which does not look like a real person's phone. We want lists that read like a real person
with money and taste, not like a vendor conference.

---

## The three lists

### List 1 — Places (~500 entries)

Cities, regions, countries, and well-known districts.

- **Include:** capitals and major cities worldwide; mid-size cities an educated professional
  would name; countries; well-known regions (`Bavaria`, `Tuscany`, `the Bay Area`);
  internationally-known districts (`Brooklyn`, `Shoreditch`, `Kreuzberg`).
- **Exclude:** streets, buildings, hotels, airports, stadiums — those are not what people put
  in a message when they say where they are.
- **Watch for:** the app has a normaliser that strips a trailing two-letter state code
  (`Austin, TX` → `Austin`) but keeps a spelled-out province. Give the **base city name**
  only: `Austin`, not `Austin, Texas`.
- **Bias by globe, not by anglophone.** The current list is heavily US/UK/EU. Oceania, Africa,
  South America, South and Southeast Asia are under-represented. A user in Lagos or Jakarta
  should find their city.

### List 2 — Organizations (~500 entries)

Companies, institutions and bodies — anything that is an **organisation** rather than a
product or a place.

- **Include:** large employers and well-known companies across tech, finance, retail,
  energy, industrials, healthcare, media; banks; airlines; consultancies; government
  departments and regulators; universities; NGOs and charities; sports clubs.
- **Deliberately included even though the model handles them:** organisations whose *names
  look like products* (`Snowflake`, `Databricks`, `BlackRock`, `Stripe`, `Cloudflare`). The
  model reads these as brands or places and skips them. These are the highest-value entries
  in the whole list.
- **Also important:** organisations whose names are **not English** or contain diacritics
  (`Médecins Sans Frontières`, `Deutsche Bank`). The English model drops them.
- **Give the full name**, not an abbreviation: `International Business Machines` is not the
  same entity as `IBM` and our normaliser does not expand acronyms. Where both are commonly
  used, prefer the form people actually type (`HSBC`, not `Hongkong and Shanghai Banking
  Corporation`).

### List 3 — Products (~400 entries)

Things bought, used, subscribed to or complained about. **This is the hard list.** Read the
"generic block" section before writing a single entry.

- **Include:** software and SaaS; hardware and devices; cars **as model names**; watches;
  branded clothing and footwear; furniture; home goods; appliances; electronics; airlines are
  *not* products (they are organisations); consumer brands people are loyal to.
- **Prefer model names over bare brands.** `Toyota Highlander`, `Mazda CX-5`, `Nike Air Max`,
  `Sony PlayStation` are unambiguous. Bare `Toyota`, `Nike`, `Sony` are companies, and the
  app will file them as Organizations — which is correct, but means they do not exercise the
  product list.
- **Multi-word names are the safe core.** Aim for the majority of the list to be two or more
  words. A multi-word name can never be mistaken for an ordinary sentence.
- **Aim for things a person mentions more than once,** or cares about enough to name: cars,
  watches, shoes, bikes, cameras, kitchens, holidays, tools, instruments, pets' brands,
  spirits. Not a packet of cigarettes, not a single apple.

---

## The generic block — read this before list 3

Some product names are **also ordinary English words**. Those cannot safely be a standalone
entry, because a message that happens to use the word in its everyday sense will mint a junk
node. The app already carries a block list for exactly this:

```
seat, contract, credits, credit, sla, rack, switch, san, ups,
nas, embeddings, embedding, support, plan, tier, storage
```

Why they are blocked, concretely:

- `seat` — "can you get me a seat?", "there's a seat by the window", "book a seat". Nine
  mentions in a busy conversation, none of them the licence concept.
- `rack`, `switch`, `storage`, `plan` — the same problem.
- Worse: these words appear **more often** than rare products, so a "hide anything mentioned
  only once" filter cannot suppress them. Frequency makes the problem worse, not better.

**Therefore, for every entry you propose, classify it as one of:**

| Class | Meaning | Example |
|---|---|---|
| `plain` | A product on sight. Multi-word, or a word with no everyday meaning. | `Toyota Highlander`, `Rolex`, `Roblox` |
| `gated` | A real product name that is also ordinary English — a product only when the sentence is about buying, renewing, deploying or licensing. | `Support Plan`, `Cold Storage` |
| `generic` | **Do not add.** If you cannot avoid it, put it here so we can see it was considered. | `Seat`, `Contract`, `Credits`, `Desk`, `Shoes`, `Watch`, `Flight` |

If a name is one word **and** an ordinary noun (`Desk`, `Shoes`, `Watch`, `Bike`, `House`,
`Painting`, `Speakers`, `Flights`), it belongs in `generic`. Do not sneak it into `plain`
because it is a nice example. We would rather have 300 safe products than 400 with 100 land
mines.

---

## Two more failure modes we have already hit

**1. Frame sensitivity.** The model's guess depends on the preposition.
`"I've moved everything onto Ansible."` → labels it a product.
`"Ansible keeps falling over."` → labels nothing at all.
That is why the dictionary exists. It also means an entry's usefulness cannot be predicted
from how famous it is.

**2. Vendors are not products.** `Grafana Labs` was briefly in our product list and produced
a Product node for a sentence that meant "I am at their office". If the entity is a company
that *sells* the thing, it belongs in List 2, not List 3. Where the same word is both
(`Snowflake` the company and the product), say so in the notes — we handle it, but we want
to know which entries those are.

---

## Output format

Three sections. For each, a simple list, one entry per line, with a short note for anything
non-obvious:

```
## PLACES
Austin
Lagos
...
Brooklyn          # district, not a city — kept because people say where they are

## ORGANIZATIONS
Snowflake         # very high value: model reads it as a place
Médecins Sans Frontières   # diacritics; English model drops it

## PRODUCTS
Toyota Highlander    plain
Nike Air Max         plain
Support Plan         gated — "the support plan renewal is due"
Desk                 generic — ordinary noun, do not add
```

Also include, at the end:

- **A short list of every entry you considered and rejected**, with a one-line reason. This is
  as valuable as the lists themselves — it shows us where the boundary was drawn.
- **Anything you were unsure about.** Flag it rather than guessing; a wrong entry is worse
  than a missing one.

---

## What "good" looks like

- The lists read like **a real professional's world**, not a software vendor's catalogue or a
  geography textbook.
- **Every product entry can be used in a natural sentence by a real person** — that is the
  test. If you cannot imagine someone texting it, cut it.
- **Nothing that is an ordinary noun is in `plain`.** This is the single most important rule.
- Duplicates and near-duplicates removed (`Deutsche Bank` once, not also `Deutsche Bank AG`).
- **British and American spellings:** give the form people type. Where they differ
  substantially (`Traveller`/`Traveler`), pick one and note it.

We would rather be told "this one is ambiguous, you decide" than be given a confident wrong
entry. The app is local and quiet: a junk node is not an error message, it is a wrong fact
that sits in someone's memory of who they know.
