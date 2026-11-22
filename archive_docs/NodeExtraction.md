LATER REFINED OUTPUT w/out Product and with canonicalization and deduplication:

# **Recommended local entity extraction for your message graph**

For your Windows 11 Lenovo (i5-12500H, 16 GB RAM, no dedicated GPU), I'd simplify the first version to three entity types:

- **Person** — contacts and people mentioned in conversations.
- **Place** — cities, countries, addresses and other named locations.
- **Organization** — companies, government departments, groups, employers and other institutions.

Leave Product out of the initial release. Standard NLP tools can recognize some products, but coverage is inconsistent, especially for software, AI models and unfamiliar brands. You can test product extraction later without redesigning the pipeline.

## **1. The tools I'd use**

[Python NLPライブラリspacyの機能紹介 - okpy](https://images.openai.com/static-rsc-4/Mr5_228Kw5KvyBnp7mG5OjQoT5rpmbfg2ynKpX--L_X3YTulB1pvQAUhiQpf4Syo2ht9o6E-D8zN2S17i6feX35f1hDsZe_l6Ov9ifRkewtPVIHrJH2X1wqYJ4FdTqCa5FlDXQ2mmKhRJ8jIq9aYVWICAA0TmBpTktTU8Tp2vWY?purpose=inline)

**spaCy — primary extractor**

Run its small English model locally to identify people, places and organizations. It is mature, CPU-friendly and provides rule-based matching for custom names.

[Website](https://spacy.io/?utm_source=chatgpt.com) · [Matching documentation](https://spacy.io/usage/rule-based-matching?utm_source=chatgpt.com)

[GitHub - rapidfuzz/RapidFuzz: Rapid fuzzy string matching in Python using various string metrics · GitHub](https://images.openai.com/static-rsc-4/gn85XU5cMRaUjKS_YqdJ6vJ0kdKFUqBLC47th8UIiHr2FJrx4B9M8O_mik5LEIalLFs5Org_6HPT0iW4yHzcnEPBm7OmWNeRsI7DB-y3i2auU2-CnnV61ew1EA6coePRSb--0Hy6yDNoDARUisKuHr_dVAaUVdm0vcAoFuxEbZE?purpose=inline)

**RapidFuzz — canonical name matching**

Compares names efficiently to identify likely duplicates and spelling variants. It should suggest matches for review or contextual checking, not blindly merge every similar name.

[GitHub](https://github.com/rapidfuzz/RapidFuzz?utm_source=chatgpt.com)

[Extract Any Entity Type with Zero-Shot NER using GLiNER | Khuyen Tran posted on the topic | LinkedIn](https://images.openai.com/static-rsc-4/FcgjiL1Z0z-taZ0K8N9HLrdex3bMINmgLFv0AlLpPVqSebyxkb_omfLvj1yumzvkhnL0JkUlJkGV4ElM1hd_vC5xmp8pllR75OcUscR0OrPmWRZaZA__HvuimdhVfBjhVM23O1KpdaHaM-rEW1_4R_E4vcKT1qS08j_rxz8Fs3o?purpose=inline)

**GLiNER — optional later**

Test it only if spaCy misses too many people, places or organizations in your actual messages. It is not necessary for the first implementation.

[GitHub](https://github.com/urchade/GLiNER?utm_source=chatgpt.com)

The initial pipeline can run without GLiNER. Start with spaCy and measure actual accuracy and speed before adding another model.

## **2. The important addition: canonicalization and deduplication**

This is arguably as important as entity extraction itself. Your app needs to recognize that different spellings and names can refer to the same real-world entity, then **fold them into one canonical graph node**.

I would call this the *canonicalization and entity-resolution layer*.

| Message contains                | Canonical entity | Method                        |
| ------------------------------- | ---------------- | ----------------------------- |
| `John Smith`, `john smith`      | John Smith       | Case normalization            |
| `Pete Woods`, `Peter Woods`     | Peter Woods      | Alias matching / verification |
| `Stephen Black`, `Stepen blcak` | Stephen Black    | Fuzzy matching + context      |
| `Pairs`, `Paris`                | Paris            | Typo correction + context     |
| `S Africa`, `South Africa`      | South Africa     | Known alias dictionary        |
| `Microsoft`, `MS`               | Microsoft        | Alias dictionary + context    |

These examples require different levels of certainty. Lowercasing is safe; merging two similar people's names is not. `MS`, for example, could mean Microsoft or something entirely different.

### **How I would implement it**

**1. Normalize text**

Case, whitespace, punctuation and Unicode normalization

**2. Find exact matches and known aliases**

Aliases, nicknames, abbreviations and approved spelling variants

**3. Find likely duplicates**

RapidFuzz suggests spelling errors and near-matches; context helps decide

**4. Resolve to canonical entity ID**

One node, many aliases and references to the original messages

**Critical rule:** fuzzy matching should propose a merge, not automatically perform one. For example, two different people named John Smith must remain separate entities even though their names match exactly.

For uncertain matches, retain them as separate nodes until there is enough evidence to merge them.

## **3. What the graph should retain**

Each canonical entity should have:

- `entity_id` — permanent internal ID.
- `canonical_name` — preferred display name.
- `entity_type` — Person, Place or Organization.
- `aliases` — alternative names and spellings.
- `mentions` — references to the original messages.
- `merge_history` — optional audit trail of merges and corrections.

Never discard the original spelling from a message. It is evidence that allows you to undo incorrect merges and improve matching later.

## **Final stack**

| Component                          | Initial choice                          |
| ---------------------------------- | --------------------------------------- |
| Entity extraction                  | spaCy small English model               |
| Exact matching and aliases         | Python dictionaries + spaCy matching    |
| Fuzzy duplicate detection          | RapidFuzz                               |
| Canonical identity and merge logic | Your app's own Python code              |
| Product extraction                 | Defer                                   |
| Additional neural NER              | GLiNER, only if testing shows a benefit |

This is a lightweight, local-first approach suitable for your laptop. The main engineering effort should go into **getting canonical entity resolution right**, rather than adding more extraction models.

---

EARLIER LENGTHY OUTPUT - with Product:
For your local Windows 11 app, I would build a **CPU-only entity extraction pipeline that turns message bodies into graph nodes and edges**, without calling an LLM or sending your private conversations to an API.

The key distinction is that identifying a person or place is relatively straightforward; identifying a *product* consistently across SMS, emails, WhatsApp, Telegram and LinkedIn is much harder. Most conventional named-entity recognition (NER) tools were trained to identify people, organizations, locations and dates — not every brand, software package, model, product or service.

I'd evaluate the tools against three requirements:

- **No generative LLM:** conventional NLP, statistical NER or a compact dedicated entity model.
- **Local inference:** runs on your Lenovo's CPU, without a GPU or cloud service.
- **Graph-ready output:** stable entity identities, aliases, message references and relationships, rather than just highlighting names in text.

## **1. My shortlist: the tools worth testing**

[Python NLPライブラリspacyの機能紹介 - okpy](https://images.openai.com/static-rsc-4/Mr5_228Kw5KvyBnp7mG5OjQoT5rpmbfg2ynKpX--L_X3YTulB1pvQAUhiQpf4Syo2ht9o6E-D8zN2S17i6feX35f1hDsZe_l6Ov9ifRkewtPVIHrJH2X1wqYJ4FdTqCa5FlDXQ2mmKhRJ8jIq9aYVWICAA0TmBpTktTU8Tp2vWY?purpose=inline)

### **1. spaCy**

Best foundation

A mature Python NLP library with a small English model, built-in NER, and a rule-based entity matcher. It is a strong starting point for extracting people, organizations, geographical locations and recognized product names, then adding your own dictionaries. Its documented CPU benchmark for the larger `en_core_web_lg` model is around 10,000 words per second on its test corpus; this is a published benchmark, not a prediction for your laptop.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://spacy.io\&sz=32)

spaCy Usage Documentation+1



Best for: your everyday ingestion pipeline, predictable local processing, custom rules and easy integration.

[Official site](https://spacy.io/?utm_source=chatgpt.com) · [Rule-based matching](https://spacy.io/usage/rule-based-matching?utm_source=chatgpt.com)

[GLiNER/gliner/model.py at main · urchade/GLiNER · GitHub](https://images.openai.com/static-rsc-4/rr5D_coQiHTxu1VOSHWRiuT7LZEG6IZpwwPv1TaZW4m0caCJZJeWHzgs6xF4fb4Yic23Alyq-kmsEvVciS8lrUjvAcPmak6-R-qDB2wdTZqwsQo_4Nv_OahG5HvKw9l0E0SHEIBThZJBfdWMEkoumnD4XFOu6WY83T5iWDiFyzM?purpose=inline)

### **2. GLiNER**

Best challenger for products

A compact entity-recognition model that accepts entity types you specify, such as “software product,” “consumer product,” “person,” “organization,” and “place.” Unlike a generative LLM, it scores text spans against entity labels rather than generating a free-form answer. It supports CPU inference and quantization.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



Best for: discovering entities that a standard four-class NER model was never trained to recognize.

[GitHub project](https://github.com/urchade/GLiNER?utm_source=chatgpt.com) · [Model collection](https://huggingface.co/gliner-community?utm_source=chatgpt.com)

[Investigate massive leaks for investigative reporting - Open Semantic Search](https://images.openai.com/static-rsc-4/e7bAVHHuuMn_7XrSda_vkzX9pUQEr15aQcQ95UTKexVngR8LQSU2LsMTU7zzkuuNNZGOD7gn_zI-NSJa3JQdcBcNaeu5Eo8J4NFH9NmyDSzee_yMVSuXekUHZAvnZ9TeanhkSmmdlKOKiG3AKTvD9xvH2ejgGED1--rdYWC3n1I?purpose=inline)

### **3. Open Semantic Entity Search**

A more complete, configurable system for recognizing, normalizing and linking names against your own lists, thesauri, databases and knowledge graphs. This is particularly relevant if you want a prebuilt entity-linking service instead of building every component yourself. It is heavier architecturally than simply installing a Python library, so I would investigate it as an alternative rather than automatically adding it to your app.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub



Best for: a later stage where graph identity, alias reconciliation and knowledge-base integration become the main problem.

[GitHub project](https://github.com/opensemanticsearch/open-semantic-entity-search-api?utm_source=chatgpt.com)

[Overview - Stanza](https://images.openai.com/static-rsc-4/jywe6rG0HZTjj0aKIYZ3oAaD7oAxAdoREZOevu6SS-J-5pZsMZm0x6WfO1AvRqas39wls9ODL0xe7U6H4mguspOt7f2Uo5TxjCRLgmvdVMN20abis3RIysRfXcf4Iez4wr7TSFrX9RCmTirEmAv2fMmO8dYG5g3zDw1GTH2uOIk?purpose=inline)

### **4. Stanza**

Stanford's NLP toolkit provides tokenization, linguistic processing and NER, with pretrained models across multiple languages. Its English NER models cover standard entity classes, but do not solve your product-specific problem by themselves.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://stanfordnlp.github.io\&sz=32)

Stanza+1



Best for: a multilingual comparison if your messages contain languages beyond English.

[Official documentation](https://stanfordnlp.github.io/stanza/?utm_source=chatgpt.com)

[GitHub - flairNLP/flair: A very simple framework for state-of-the-art Natural Language Processing (NLP) · GitHub](https://images.openai.com/static-rsc-4/l5NzUCIwMhq0Rp3xNHSU8nhGbDjanCFcn1XXBhmfq-7Hl6PDrev8Pw1UWbWH3_j62ueZoVlcUlVmmZeNG4s0vGmevaIgEoRzvePGuKY3bk7pnUUjUhiP4gOK4LnOVoRNBG8d-lSo8YsE7D-qTG-Qu7uhpWE7s1Ez_9NAPeiE1QI?purpose=inline)

### **5. Flair**

Another conventional NER option with pretrained sequence-tagging models. Its standard English model targets four entity classes; its documented benchmarks are competitive, but the framework is not my first choice for a lightweight, maintainable Windows application.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://huggingface.co\&sz=32)

Hugging Face+1



Best for: a comparison benchmark, or if you later want to train a specialized sequence tagger.

[GitHub project](https://github.com/flairNLP/flair?utm_source=chatgpt.com)

My initial recommendation is **spaCy + GLiNER + a local alias/entity-resolution layer**. Keep the first two as independent extractors and compare their results before deciding how much of GLiNER you actually need.

## **2. What each tool can actually recognize**

This is the most important distinction for your graph.

| Entity type         | spaCy standard model                       | GLiNER                          | Your additional logic                   |
| ------------------- | ------------------------------------------ | ------------------------------- | --------------------------------------- |
| Person              | Strong starting point                      | Can identify people             | Resolve names to existing contacts      |
| Organization        | Strong starting point                      | Can identify organizations      | Merge company aliases and abbreviations |
| Place               | Good for common named places               | Can identify places             | Resolve geographic ambiguity            |
| Product             | Has a `PRODUCT` label, but coverage varies | Can target custom product types | Essential for reliable product coverage |
| Software / AI model | Inconsistent under generic NER             | Can target these labels         | Maintain a software/product catalogue   |
| Company vs. product | Can confuse them                           | Can confuse them too            | Type rules and entity resolution        |

spaCy's English model has a `PRODUCT` label, but its training data determines what it recognizes. The label does not mean it knows every product or software package. Its published model card documents the standard entity types and evaluation results.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://huggingface.co\&sz=32)

Hugging Face+1



GLiNER is attractive because you can test custom labels without training a new model. But **zero-shot does not mean guaranteed accuracy**. Label wording, context, overlap and the particular model version can affect its results.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



For example, your messages might contain:

- “I use Ollama with Continue and VS Code.”
- “Apple sent me the invoice for my MacBook.”
- “Meet John at Apple Park.”
- “I spoke to Apple about the MacBook issue.”

The desired graph distinguishes the organization Apple, the MacBook product, the Apple Park location, the person John, and the software products Ollama, Continue and VS Code. It must also avoid creating a new node every time the same entity is mentioned with a slightly different name.

No single NER model reliably handles all those decisions. That is why the entity-resolution layer matters as much as extraction.

## **3. The architecture I would use for your app**

Do not make extraction and graph construction the same operation. Treat them as separate stages so you can improve recognition without corrupting existing graph identities.

**1. Existing message store**

SMS · Email · WhatsApp · Telegram · LinkedIn

Preserve original message ID, timestamp, sender and body.

**2. Text normalization**

Remove quoted email history where appropriate, signatures, URLs and repeated boilerplate. Preserve original text and offsets.

**3A. spaCy NER**

People, organizations, locations, standard products

**3B. GLiNER**

Custom product, software, AI model and other entity labels

**4. Merge, validate and resolve**

Deduplicate overlapping spans, apply rules, match known aliases and retain uncertainty.

**5. Graph writer**

Create or update entity nodes, message-to-entity edges, and explicitly supported relationships.

### **Why this design works**

- **You can disable GLiNER.** If spaCy and your dictionaries already cover most of your data, you don't need to pay the extra CPU and memory cost of another model.
- **You can rerun extraction.** Keep the original message and the extractor version, so improved models can be tested against old messages.
- **You can explain every node.** Store which message mentioned it, the exact text span, the entity type, the extractor and the confidence or matching method.
- **You can correct mistakes.** If two names were merged incorrectly, you can reverse that identity decision without re-ingesting the original conversations.

One important qualification: extracting two entities from the same message does not prove a relationship between them. A message mentioning a person, a company and a product should create three mention links, not automatically assert that the person works for the company or owns the product.

## **4. The graph data I would store**

Keep the original mention separate from the canonical entity. That distinction will save you a lot of trouble later.

**Entity node**

Canonical record

`entity_id`, `canonical_name`, `entity_type`, `aliases[]`, `created_at`

**Mention record**

Evidence from a specific message

`message_id`, `entity_id`, `surface_text`, `start_offset`, `end_offset`, `extractor`, `confidence`

**Relationship edge**

Only a supported relationship

`source_entity_id`, `relation_type`, `target_entity_id`, `message_id`, `evidence`

For example, these mentions:

- `Ollama`
- `ollama`
- `Ollama app`

might resolve to one canonical software entity if your matching rules and context support that decision. But don't automatically merge `Apple`, `Apple Park` and `Apple Music` into the same entity merely because they share a word.

For matching and reconciliation, RapidFuzz is a useful lightweight addition. It provides fast string-similarity algorithms, but similarity should generate a candidate match, not independently decide identity.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://rapidfuzz.github.io\&sz=32)

rapidfuzz.github.io+1



## **5. CPU and memory: what makes sense on your Lenovo?**

Your 12th-generation Intel Core i5-12500H, 16 GB RAM and lack of a dedicated GPU are sufficient for a local extraction pipeline. I would not start with a large transformer model.

| Configuration          | CPU suitability             | Memory/complexity                                          | Recommendation                         |
| ---------------------- | --------------------------- | ---------------------------------------------------------- | -------------------------------------- |
| spaCy `en_core_web_sm` | Excellent starting point    | Low                                                        | Run first                              |
| spaCy `en_core_web_lg` | Suitable for CPU            | Higher than `sm`                                           | Benchmark only if accuracy warrants it |
| GLiNER small model     | Designed to support CPU use | Additional model weights and inference memory              | Test on a representative subset        |
| Stanza                 | CPU-capable                 | More processing overhead for a basic English-only use case | Consider for multilingual requirements |
| Flair standard NER     | CPU-capable                 | PyTorch-based model stack                                  | Secondary benchmark                    |

spaCy publishes comparative CPU performance measurements, and GLiNER explicitly supports consumer hardware and CPU inference. Neither source guarantees a specific throughput on your exact laptop.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://spacy.io\&sz=32)

spaCy Usage Documentation+1



**My practical setup:**

- Use `en_core_web_sm` first, because it gives you a cheap baseline.
- Run extraction in batches instead of starting a new model process for every message.
- Load the models once and keep them resident while the ingestion worker is running.
- Run GLiNER only where it adds value — for example, on messages where product and software discovery matters.
- Cache results using message ID, content hash, extractor version and configuration. Reprocess only changed messages or messages selected for a new extraction version.

I would not promise a messages-per-second figure until it has been measured on your machine. Message length, batching, model choice and the number of custom entity labels all matter.

## **6. If you mean strictly deterministic — no neural models at all**

There is an important distinction here.

| Approach           | How it decides                           | Reproducible?                               | Finds unfamiliar names?                    |
| ------------------ | ---------------------------------------- | ------------------------------------------- | ------------------------------------------ |
| Dictionary / rules | Exact names, patterns and rules          | Yes                                         | Poorly, unless added to the dictionary     |
| spaCy NER          | Trained statistical model                | Normally yes, with fixed configuration      | Yes, within its learned capabilities       |
| GLiNER             | Compact neural span-scoring model        | Normally yes, with fixed model and settings | Better flexibility for custom entity types |
| Generative LLM     | Generates a response based on the prompt | Not necessarily                             | Flexible, but you said you don't want this |

If you want *zero neural inference*, use spaCy's rule-based `EntityRuler` and `PhraseMatcher` without its statistical NER component. These support exact phrase and token-pattern matching.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://spacy.io\&sz=32)

spaCy Usage Documentation+1



For your application, I would actually use a hybrid:

- **Rules and dictionaries:** known contacts, company names, products, software packages and locations.
- **Statistical NER:** discover unfamiliar people, organizations, places and common product names.
- **Optional GLiNER:** discover new entities in custom categories, such as AI models and software tools.
- **Deterministic identity rules:** normalize aliases and decide whether a mention matches an existing node.

That gives you reproducible processing while retaining the ability to discover things you haven't manually catalogued.

## **7. How I would test this before integrating it**

Don't choose the winner based on a general NER leaderboard. Your private messages are a different dataset from news articles and curated benchmark sentences.

Build a small benchmark from approximately 300–500 representative messages, including:

- Short, informal WhatsApp and SMS messages.
- Emails with signatures, quoted replies and forwarded content.
- LinkedIn discussions mentioning companies, people and job titles.
- Technical discussions mentioning software, AI models, products and repositories.
- Messages with ambiguous names, typos and repeated aliases.

Manually mark the correct entities in those messages. Then run each candidate and compare the output.

## **Entity extraction test plan**

0 of 6 test criteria reviewed

Reset

**Person precision and recall**

How many detected people are correct, and how many real people were missed?

**Organization precision and recall**

Can it distinguish companies from people, products and ordinary words?

**Place precision and recall**

Does it recognize actual locations without treating every capitalized name as a place?

**Product and software recall**

Can it find names such as Ollama, VS Code, product brands and AI model names?

**Duplicate-node rate**

How often do aliases incorrectly create separate graph nodes, or different entities get merged?

**CPU throughput and memory**

Measure messages per second, peak RAM and time to process a fixed sample.

Use precision and recall separately for each entity type. A tool that finds every product but produces hundreds of false positives may be worse for graph construction than a more conservative tool. Measure graph identity resolution separately from NER accuracy.

## **8. Final recommendation**

I would implement these in this order:

1. **spaCy small English model** — baseline extraction for people, organizations, places and standard products.
2. **spaCy EntityRuler + your own product dictionary** — reliable recognition of known contacts, companies, software and brands.
3. **RapidFuzz** — candidate matching against existing graph entities and aliases.
4. **GLiNER small** — benchmark custom product/software recognition against the baseline. Keep it only if it materially improves results.
5. **Graph evidence and identity management** — store mentions, canonical IDs, provenance and explicit relationships separately.

I would defer Stanza, Flair and a larger spaCy model unless your own test set shows a specific advantage. I would also defer Open Semantic Entity Search until you need a full entity-linking service.

The one design decision I would make now is to **treat product discovery as a separate extraction category, not just an ordinary&#x20;**`PRODUCT`**&#x20;label**. In an AI-infrastructure and personal knowledge graph, you will likely want to distinguish `SOFTWARE`, `AI_MODEL`, `CONSUMER_PRODUCT`, `BRAND`, `PERSON`, `ORGANIZATION` and `PLACE`. You can then decide which categories become distinct node types and which are subtypes of a broader entity.

That approach remains local, avoids generative LLMs, and gives you a path from basic extraction to a useful, searchable graph without overloading your laptop.
