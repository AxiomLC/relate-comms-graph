# Local LLM choices for relate-comms-graph

> Companion to [`direction.md`](direction.md). Covers **which model**, **which quant**, and
> **how much of the pipeline actually needs an LLM** (answer: less than you'd think).
>
> ⚠️ **Hardware warning — verify before trusting any number here.** The candidate
> research these notes inherited was written for a *different machine*
> (**i5-1235U, 2P+8E, Iris Xe**). The box actually in use at time of writing is an
> **i7-6600U — 2 cores / 4 threads, 16 GB DDR3L-era dual-channel, Intel HD 520,
> Skylake 2015.** That is roughly **4–5× less CPU throughput and far less memory
> bandwidth** than the research assumed. Treat every tok/s figure below as
> *unverified on this hardware* until measured (§5).

---

## 1. First: how much LLM does this project actually need?

Messaging graphs are structurally different from document graphs, and that changes
the model requirements a lot.

| Task | Needs an LLM? | Why |
|---|---|---|
| Message → node/edge | **No** | `from`/`to`/`ts`/`reply_to`/`thread` are explicit fields. This is parsing, not extraction. |
| Identity resolution (phone/email exact) | **No** | String normalisation. |
| Identity resolution (fuzzy name) | **No** | `rapidfuzz` / Jaro-Winkler beats an LLM here — deterministic, explainable, instant. |
| PII scrubbing (shapes) | **No** | Regex, already built. |
| PII scrubbing (semantic: "his passport number is…") | **Yes** | The genuine LLM use case. |
| Commitment/meeting extraction ("dinner Thursday?") | **Yes** | This is the demo's value-add. |
| Person summaries / thread digests | **Yes** | High value, tolerant of latency. |
| Topic tagging for the cross-platform query | **Yes** | Enables "who did I talk to about X". |
| Embeddings (semantic search) | **Yes** (small model) | Separate, tiny model. |

**Implication:** the graph *skeleton* builds with zero LLM calls. An LLM only enriches
it. So the demo works on a machine with no model installed — it just looks dumber.
That is a much better failure mode than `desk-relate`'s, where binaries were silently
skipped.

**Batch shape matters more than raw speed.** Message enrichment is a background job
over thousands of short texts, not an interactive chat. A 6 tok/s model that runs
overnight is fine; a 30 tok/s model that OOMs is not.

---

## 2. Candidate models

Ordered by realistic fit for **this** box. All figures are the *research claims*,
not measurements here.

### 2.1 Qwen3 4B — `qwen3:4b` (current default, safe pick)
- ~4B dense, thinking-capable, **Q4_K_M ≈ 2.5 GB**.
- **Why start here:** it's a real, pullable Ollama tag — verifiable today. The other
  candidates in the inherited research may not exist under the names given.
- Good JSON-mode adherence for its size. Disable thinking (`/no_think`) for bulk
  extraction, or you pay 3–5× tokens for reasoning you don't need on a fixed schema.
- On this hardware: expect **single-digit tok/s**. Fine for batch.

### 2.2 Ling-3.0-Tiny (Ant Group / InclusionAI) — MoE, best speed *if obtainable*
- ~8B total, **1.3B active per token**; Q4_K_M ≈ 4.5 GB.
- **Why it's attractive:** MoE activation is the single best lever on a
  bandwidth-starved CPU — most weights sit idle per token.
- **Why to be careful:** the "25–32 tok/s on laptops" figure came from machines with
  far more cores. On 4 threads expect much less. Also **the Ollama tag is unverified**
  (`ling-3.0-tiny` / `inclusionai/ling-3.0-tiny` / `ling-tiny` all floated).
- Verdict: **try it, don't plan around it.**

### 2.3 Qwen3.5-4B — balanced, long context
- 4.7B dense hybrid, claimed 262K native context, Q4_K_M ≈ 2.5–3 GB.
- Hybrid attention keeps KV cache small on long threads — relevant because a chat
  thread can be far longer than a document chunk.
- Useful if you want to summarize **whole threads** in one pass.

### 2.4 Qwen3.5-9B — overnight batch only
- 9.7B dense, Q4_K_M ≈ 5.2–5.8 GB. Better on nested schemas and disambiguation.
- On a 2-core Skylake this is **hours**, not minutes, for a real corpus.
- Verdict: only for one-off re-summarisation runs.

### 2.5 Ultra-lean (if everything else is too slow)
- **Nanbeige4.2-3B** — Q8_0 ≈ 3.4 GB; reportedly clean at data parsing, but prefers
  the schema passed as a **tool/function definition** rather than `response_format`.
- **MiniCPM5-2B** — Q6_K/Q8_0 ≈ 2.2 GB, 128K ctx; fast background tagging.

### 2.6 Embeddings — `nomic-embed-text`
- ~274 MB, 768-dim. Runs fine on CPU. Use for semantic search over messages.
- Alternative if you want fewer moving parts: `bge-small-en-v1.5` (~130 MB).

---

## 3. Quantisation: what to actually pick

You asked about quant specifically. The rules that matter on a machine with **no
discrete GPU and limited bandwidth**:

| Quant | Use when | Notes |
|---|---|---|
| **Q4_K_M** | **Default for everything.** | Best quality/size knee. What to pull first. |
| Q5_K_M | Model is comfortably under budget and you want a little more accuracy | ~15% bigger than Q4_K_M |
| Q6_K | Small models only (2–4B) | Diminishing returns above this |
| Q8_0 | Only for tiny models (<3B) | Near-lossless; still fast when model is small |
| Q3_K / IQ3 | **Avoid** | Noticeably degrades structured-JSON adherence — exactly what this task needs |
| IQ4_XS / IQ2 | Avoid on CPU | IQ quants mainly help VRAM-constrained GPUs; on CPU they can be *slower* |

**Key point for this project:** the failure you care about is *invalid JSON*, not
slightly-worse prose. Quant damage shows up in schema adherence first. So **never
quantise below Q4_K_M** for the extraction passes, and measure JSON validity (§5) —
not vibes — before accepting a smaller quant.

**KV cache is the hidden cost.** Long email threads with 8K+ context can make KV
larger than the weights at Q4. Cap `num_ctx` to what you need (4096 is plenty for
single-message enrichment; 8192 only for thread summaries).

---

## 4. Runtime & settings for this box

- **Ollama is not installed** on this machine (verified). Installing it is a global
  install — user runs it, per standing rules:
  ```powershell
  # PowerShell as Administrator
  winget install Ollama.Ollama
  ```
- **Threads: set to 3, not 4.** Hyper-threading on 2 physical cores hurts when the
  model is bandwidth-bound; leave one logical core for the OS.
  `OLLAMA_NUM_THREAD=3`
- **HD 520 has no usable compute path.** Ollama may try Vulkan/OpenCL; on Skylake-era
  iGPU this is usually *slower* than pure CPU. Force CPU:
  `OLLAMA_LLM_LIBRARY=cpu` (or just ignore the GPU — verify with `ollama ps` showing
  `100% CPU`).
- **Keep the model resident:** `OLLAMA_KEEP_ALIVE=30m` for batch jobs, so you don't
  pay 10–30 s of load time per chunk.
- **Context:** 4096 default. Anything higher costs RAM quadratically in KV.

---

## 5. Bake-off harness (run this before changing the model)

The inherited notes proposed the right metrics; here they are adapted to this project
and to this hardware.

**Test set:** 3 hand-written fixtures per task, checked into `testdata/`:
1. `extract_commitment.json` — message pairs where one contains a commitment, one doesn't
2. `pii_semantic.json` — prose containing a name/address/passport that regex misses
3. `thread_digest.json` — a 40-message thread + reference summary

**Metrics (in priority order):**

| # | Metric | Pass bar |
|---|---|---|
| 1 | **JSON validity rate** — % responses parsing against the strict schema | ≥ 95% |
| 2 | **Recall on semantic PII** — how many seeded items caught | higher is better; compare, don't chase 100% |
| 3 | **False-positive rate** — things flagged that are not PII | must stay low; a paranoid model ruins the demo |
| 4 | **tok/s and wall-time per chunk** | record; 6+ tok/s is usable for batch |
| 5 | **Peak RSS** | must stay clear of swap (16 GB box, no swap thrash) |

```powershell
ollama pull qwen3:4b                 # baseline — verified to exist
ollama pull qwen3.5:4b               # tag may differ; check ollama.com/library
ollama pull nomic-embed-text
# then: python tools/bakeoff.py --model <tag> --suite testdata/
```

**Decision rule:** the default stays `qwen3:4b` until another model beats it on
**JSON validity ≥95% AND PII recall** on the same suite. That's one string in config,
no code change. Don't switch models for speed alone — a fast model that emits broken
JSON costs more than it saves, because every failure needs a retry.

---

## 6. Do you even need local? (worth an honest thought)

Two arguments for cloud here, and one strong argument against:

- **For:** the enrichment tasks are batch and cheap. At DeepSeek V4.1 Flash prices
  (~$0.022/M in, $0.40/M out), enriching 50,000 short messages is **well under $1**.
  That's fast, doesn't hog your laptop for hours, and needs no model download.
- **For:** no 2-core CPU bottleneck, no quant quality loss.
- **Against (decisive for this project):** the whole pitch is *"your messages never
  leave the machine."* Sending them to an API destroys the single strongest claim in
  the README. If the demo's differentiator is privacy, it has to be local — or be
  honest and call it "local-first with optional cloud enrichment."

**Recommendation:** local by default, cloud as an **opt-in** flag with a loud warning
in the UI. The aha moment (cross-platform relationship discovery) works either way,
but the privacy story only works local.

---

## 7. Open questions

1. Which machine is the real demo box — this i7-6600U, or the i5-1235U the research
   assumed? Big difference in what's viable.
2. Is Ollama going to be installed at all? If not, embeddings are unavailable and the
   semantic query demo needs a different approach (BM25/full-text first).
3. Is cloud enrichment acceptable for a *non-demo* personal use, if explicitly opt-in?
4. If `ling-3.0-tiny` isn't a real pullable tag, is it worth pulling the GGUF directly
   from HuggingFace and running under llama.cpp instead of Ollama?

---

## 8. Sources

- Inherited research: `desk-relate/NOTES-local-llm-models.md` (written for different hardware)
- Ollama library — <https://ollama.com/library>
- Qwen3 model card — <https://huggingface.co/Qwen/Qwen3-4B>
- GGUF quantisation guidance — <https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md>
- DeepSeek V4.1 Flash pricing — as recorded in `Nod/COST_EVAL.md` (Nov 2026)
