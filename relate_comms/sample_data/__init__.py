"""Shipped sample data. `ingest --source sample` reads from here.

WHY THIS SHIPS
--------------
A developer will not point this app at their own comms until they have watched it
work on data they generated themselves. So sample generation is a product
feature, not a dev helper: clone, run, see a graph, then decide.

Two ways sample data arrives here:

1. `python -m relate_comms sample build` writes generated dummies to `generated/`.
   Each platform has its own generator in `generators/`.
2. `generated/` is gitignored — the dummies are reproducible, so committing them
   would only create a second copy that can drift.

Tests do NOT read from here. `tests/fixtures/` holds pinned copies so a parser
change cannot be "fixed" by regenerating.

Layout:

    sample_data/
      generators/          one module per platform, models that platform's structure
        telegram.py        validated against real exports 2026-11-14
        whatsapp.py        TODO - Android .txt, DD/MM/YY HH:MM - Name: body, U+200E mark
        messenger.py       TODO - Facebook takeout JSON
        linkedin.py        TODO - messages.csv
        sms.py             TODO - SMS Backup & Restore XML
        email.py           TODO - .eml / mbox
      generated/           output; gitignored
"""
