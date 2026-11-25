# rework_extraction.md — retired

**Nothing here is open.** The extraction rework landed 2026-11-23 and the vocabulary
landed 2026-11-24; what remains is one optional measurement, recorded in `HANDOVER.md`.

Kept as a stub so old links do not 404. The durable facts live in
[`TECHREADME.md`](TECHREADME.md) §5, and the shipped record in
[`HANDOVER.md`](HANDOVER.md).

---

## What closed

| Item | Where it went |
|---|---|
| Place / Organization / Product lists (691 / 585 / 764) | `TECHREADME.md` §5 |
| The three load bugs (span truncation, products missing from the ruler, `NORP` dropped) | `HANDOVER.md`, one line each |
| `Product` as a live kind | `TECHREADME.md` §5, `HANDOVER.md` |
| Declined suggestions (`en_core_web_lg`, learned calibrator, stored `unresolved`, …) | `HANDOVER.md` §"Declined" |

## What is left

**GLiNER — optional, not needed now.** Unmeasured on this machine; `onnxruntime` is not
installed. Its quoted CPU range is 22–512 ms/message against our ~1.5 ms. The residual
recall hole is names nobody listed, which is small enough that this is a judgement call
rather than a gap. Measure before installing; if the hole is a handful of nodes per
thousand messages, it is not worth 200× the cost.

**Next work is the local LLM chat wired into the UI**, not extraction.
