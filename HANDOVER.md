# HANDOVER.md

Short and dated. **Newest entry at the bottom.** What is next, not what was built —
that lives in [`TECHREADME.md`](TECHREADME.md).

---

## 2026-11-16 — UI built, docs consolidated

**Where it stands.** The app runs end to end: `start.bat` → `http://127.0.0.1:8100`.
Store holds 12,499 messages / 955 threads / 591 correspondents across five platforms.
`pytest tests -q` → 137 passed, 2 skipped.

**Built this session:**

- Full React + esbuild UI in `app/ui/src/` — three columns, Cytoscape + fcose canvas,
  two-state Viewer, local Ollama chat, five modals.
- Six shared size rungs, platform colours, per-node shade jitter, optional source icons
  (title-bar toggle), zoom-gated labels with a source line.
- Source filter (Utilities modal) wired through the tool layer, so graph, search bar and
  chat all agree.
- Viewer stack persisted to `localStorage`; character-budgeted message loads; Newer/Older
  paging; per-thread search.
- `start.bat` — one window, closing it stops the app.
- Docs consolidated: `README.md`, `TECHREADME.md`, `HANDOVER.md`. `buildNOTES.md` deleted;
  `buildUI.md` → `archive_docs/UI-Cytoscape.md`; Ollama and download guides archived.

**Next, in order:**

1. **Tweak the UI with the author.** This is the current work — styling and behaviour
   iteration, driven by looking at it. Everything tunable is in
   `app/ui/src/config/theme.js` and editable live from Graph Style.
2. **`Person` / `SENT` wiring.** `write_people()` and `sent_edges()` both exist and
   neither is called from `ingest()`. This is what makes cross-platform identity real —
   and it is the prerequisite for cross-cluster edges on the canvas, which are currently
   impossible because no cross-platform edge exists in the store.
3. **Place / Company / Product.** Blocked on a candidate generator. Do not start before
   the Viewer is settled, or there is no way to see whether it is right.
4. **SMS adapter.** Payload pending.

**Open decisions:**

- The source filter narrows the AI chat as well as the search bar. The author chose this
  deliberately, overriding the earlier "UI state never narrows an agent's query" rule. The
  alternative is a per-call `sources` argument instead of module state in `tools.py`.
- Per-node gravity is not a fcose feature. Big threads can only be approximated as anchors
  via lower `nodeRepulsion`.

**Known cosmetic issues in the real store:**

- `Facebook user` spans 31 Messenger threads — a pseudo-person by design, but a viewer
  should render it as a spam account, not a contact.
- One thread holds 707 messages. The Viewer pages, so this is fine, but it is the test case.
- Hostinger sent mail has no `Message-ID` (133 of 221) — keyed by `uid:<UIDVALIDITY>:<UID>`.
