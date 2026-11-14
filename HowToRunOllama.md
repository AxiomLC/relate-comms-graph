# HowToRunOllama.md

Plain-language guide to Ollama on **this machine (Lenovo17)**, for when there's no agent
around to do it for you.

Verified 2026-11-14: Ollama **0.40.16**, models `qwen3.5:4b` (3.3 GB) and `embeddinggemma`
(621 MB), API on `127.0.0.1:11434`.

---

## 0. THREE THINGS THAT WASTE YOUR TIME — fix all three first

### 0a. The service and `keep_alive` are DIFFERENT things

This trips people up, so be clear:

| | What it is | How to control it |
|---|---|---|
| **Ollama service** | The background program that *can* serve models | Start manually. Autostart is **off**. |
| **`keep_alive`** | How long a **loaded model** stays in RAM after your last request | Env var / per-request option |

The service can run with **zero models in memory**. `keep_alive` decides what happens
*after* a request, not whether the program starts.

**This box's policy:**

- **Service = manual.** Startup shortcut renamed to `Ollama.lnk.disabled`. Boot cost now 0 GB
  (was ~4 GB). Start it when needed:
  `"C:/Users/q1fre/AppData/Local/Programs/Ollama/ollama.exe" serve`
- **`keep_alive = 5m`.** Models evict themselves 5 min after you stop using them, so RAM comes
  back without a reboot. (Was `-1` = never unload, which is only right for a long unattended
  batch run — that's why free RAM dropped to 1.1 GB after testing.)
- **Closing the service window frees everything**, regardless of `keep_alive`.

**Default model is `lfm2.5:8b`.** `qwen3.5:4b` is kept but only used on request or for the
few tasks that need denser output. See §0c.

### 0b. Thinking is ON by default, and it costs you ~28×

Measured on this box, same prompt ("Hello"), `qwen3.5:4b`:

| | tokens generated | wall time |
|---|---|---|
| default (thinking) | **368** | **39.1 s** |
| `"think": false` | **10** | **1.4 s** |

The model writes a whole internal reasoning block for *any* input, including "hello". You
almost never want that for tagging or extraction.

**The fix is an API parameter, not a prompt:**

```json
{
  "model": "lfm2.5:8b",
  "messages": [{"role": "user", "content": "Hello"}],
  "think": false
}
```

In Python:

```python
from relate_comms.models import pick, THINK, OPTIONS

resp = ollama.chat(
    model=pick("tag"),          # lfm2.5:8b by default
    messages=[{"role": "user", "content": msg}],
    think=THINK,                # False - this one line is a 28x speedup
    options=OPTIONS,
)
```

⚠️ **`/no_think` in the system prompt does NOT work** on Qwen3.5. I tested it: still 368
tokens, still 39 s. Blog posts recommend it because it worked on Qwen3. Do not waste time.

**When you DO want thinking:** thread summaries and semantic PII detection, where extra
reasoning genuinely improves the answer and latency doesn't matter (batch).

### 0c. Model choice — measured, not guessed

Head-to-head on 8 sample messages, same schema, CPU only:

| Model | JSON valid | Median wall clock | Decode |
|---|---|---|---|
| `qwen3.5:4b` | 8/8 | 4.12 s | 8.5 tok/s |
| **`lfm2.5:8b`** | 8/8 | **1.99 s** | **21.3 tok/s** |

**`lfm2.5:8b` is the default.** It's an 8B model with **~1B active parameters** per token
(MoE). On a CPU that's decisive: decode is bandwidth-bound, so reading one eighth of the
weights per token is a 2.5× win. Research predicted 18–24 tok/s; measured 21.3.

This roughly halves a 50k-message enrichment from ~28 h to ~14 h.

**Honest caveat:** 8 easy messages is not a benchmark. Both scored perfectly because the
samples were unambiguous. `relate_comms/models.py` routes `thread_summary` and
`semantic_pii` to `qwen3.5:4b` anyway — fewer items, more tokens, and a wrong answer there
costs more than the time saved. Re-run `tools/compare_models.py` on ~50 real redacted
messages before trusting either on messy input.

---

## TL;DR — what you'd do by hand

1. **Start it when you need it** (it no longer runs at boot — that was costing ~4 GB of RAM):
   `"C:/Users/q1fre/AppData/Local/Programs/Ollama/ollama.exe" serve`. Leave that window open.
2. **Open the UI** if you want a chat box — the Ollama app, pick a model from the dropdown.
   Optional. Closing it does not stop the server.
3. **Pick the model**: `lfm2.5:8b` (default, fastest). `qwen3.5:4b` only if asked for.
   (Not `embeddinggemma` — that's vectors only, not chat.)
4. **Test it** by typing "hi". If it answers, server + model + CPU path all work.
   **First reply may be slow while the model loads — that's normal.**
5. **Connect a harness** — point Zed, or any Python script, at `http://127.0.0.1:11434`.
   OpenAI-compatible endpoint: `http://127.0.0.1:11434/v1` with any dummy API key.

**Then read §0 — thinking is on by default and makes everything 28× slower.**

That's it. Everything below is the detail behind those five steps.

---

## 1. Where things live

| Thing | Path |
|---|---|
| Program | `C:\Users\q1fre\AppData\Local\Programs\Ollama\ollama.exe` |
| Models (on **C:**) | `C:\Users\q1fre\.ollama\models` |
| Server | `http://127.0.0.1:11434` |
| Compatible API | `http://127.0.0.1:11434/v1` (OpenAI-style) |

Models are **3.9 GB total** on C: right now. To move them to another drive later, set
`OLLAMA_MODELS` to a new folder **before** re-pulling.

**Is the server up?**

```bash
curl -s http://127.0.0.1:11434/api/version
```

Should return `{"version":"0.40.16"}`. If it doesn't, start it: `ollama serve` (leave the
window open — closing it stops the server now that autostart is off).

The bare URL showing **"Ollama is running"** is normal — that's just the root status page,
not an app. The useful endpoints are `/api/...`.

---

## 2. The UI vs the API — which to use when

The Ollama desktop window is a **chat app**. It's fine for "does this model work", and
useless for our pipeline.

Our pipeline is a **batch job**: thousands of short messages in, strict JSON out. That means
the API, not the chat box. The UI can't force a JSON schema; the API can.

So the UI has exactly one job here: **sanity-check that the model answers.** After that, close
it — a chat window burning CPU competes with the batch run.

---

## 3. Testing it

### 3a. The 10-second test (UI)
Open the Ollama window, pick `qwen3.5:4b`, type `hi`. If words come back, everything works.

### 3b. The 10-second test (terminal — better, because it proves the *API*)

```bash
curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"qwen3.5:4b\",\"prompt\":\"hi\",\"stream\":false}"
```

That returns JSON with a `response` field. If you see text in it, the API path works.

### 3c. The real test — structured output

This is the one that matters, because our pipeline lives or dies on valid JSON.

```bash
curl -s http://127.0.0.1:11434/api/chat -d "{
  \"model\":\"qwen3.5:4b\",
  \"messages\":[{\"role\":\"user\",\"content\":\"see you thursday\"}],
  \"stream\":false,
  \"think\":false,
  \"format\":{\"type\":\"object\",\"properties\":{\"topics\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"topics\"]}
}"
```

Pass a schema to `format` and the decoder is **grammar-constrained** — it cannot emit
malformed JSON. If that returns a parseable object, the enrichment layer will work.

### 3d. Did it use the CPU or the iGPU?

```bash
ollama ps
```

Look at the `PROCESSOR` column. It should say **100% CPU**. If it says GPU, something changed —
see §5 for why we don't want that.

---

## 4. Connecting a harness

### Zed
Settings → Assistant/LLM → add an OpenAI-compatible provider:
- Base URL: `http://127.0.0.1:11434/v1`
- API key: anything (e.g. `ollama`) — it's ignored locally
- Model: `qwen3.5:4b`

### Python (what our pipeline uses)

```python
import ollama

resp = ollama.chat(
    model="qwen3.5:4b",
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.message.content)
```

### Any other tool
Anything that can POST JSON to `http://127.0.0.1:11434/api/chat` works. Nothing is locked in.

---

## 5. Configuration — the env vars, and why each exists

Set at **user scope**, so they apply to the background service after a restart.

```
OLLAMA_VULKAN=0              # force CPU - the iGPU shares the same RAM, so it can't help
OLLAMA_CONTEXT_LENGTH=8192   # default 4096; 8K costs ~0.27 GB with Qwen3.5
OLLAMA_FLASH_ATTENTION=1     # required for KV quantisation
OLLAMA_KV_CACHE_TYPE=q8_0    # halves KV memory; ~zero speed cost
OLLAMA_KEEP_ALIVE=5m         # models evict themselves 5 min after last use
OLLAMA_NUM_PARALLEL=1        # MUST be 1: parallel multiplies KV and OOMs a 16 GB box
OLLAMA_MAX_LOADED_MODELS=1   # one model in RAM at a time
OLLAMA_NO_CLOUD=1            # the product promise. Nothing leaves the machine.
```

To (re)apply them: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/set_ollama_env.ps1`

**Then restart the service** — env vars are read at startup:
quit Ollama from the system tray, reopen it (or reboot). Check with `ollama ps`.

### The one thing that is NOT an env var

**`num_thread`.** You'll see `OLLAMA_NUM_THREADS` in blog posts. It doesn't exist — the
feature request was closed as a duplicate. Thread count must go in a **Modelfile**:

```dockerfile
FROM qwen3.5:4b
PARAMETER num_thread 6
PARAMETER num_ctx 8192
PARAMETER temperature 0
```

```bash
ollama create qwen35-batch -f Modelfile
ollama run qwen35-batch
```

This box has **4 performance + 8 efficiency cores**. Theory says 6 threads (4P+2E) wins,
4 is safest, 16 is worst — because every layer waits for the slowest thread, and E-cores are
slow. **Unmeasured on this machine** (the benchmark stalled; see §7).

---

## 6. Day-to-day commands

```bash
ollama list                  # what's installed
ollama ps                    # what's loaded, and CPU vs GPU
ollama pull qwen3.5:4b       # download (RESUMES if interrupted - just re-run it)
ollama rm <model>            # remove
ollama show qwen3.5:4b       # model details, context length, parameters
ollama serve                 # run the server manually (if the service isn't up)
```

Interrupted a big download? **Just run the same `ollama pull` again.** Partial blobs are
kept and it continues from where it stopped. Worth knowing on a slow connection.

---

## 7. Known unknowns on this box

Honest list, so nobody trusts a number that was never measured:

| Item | Status |
|---|---|
| tok/s | **MEASURED.** `qwen3.5:4b` 8.5 tok/s, `lfm2.5:8b` 21.3 tok/s. §0c |
| Best `num_thread` (4 vs 6 vs 8) | **Unmeasured.** Theory says 6. `tools/bench_ollama.py` stalls at `ollama.create` — bug in that script, not the install. Low priority now that MoE gives the speed. |
| Thinking on/off | **MEASURED — 39.1 s vs 1.4 s.** Use `"think": false`. §0a |
| iGPU Vulkan | **Deliberately not attempted.** 80 EU, no XMX, shared memory bus — the research is unanimous that it can't help decode. |
| `OLLAMA_NO_CLOUD=1` effect | Set, not yet confirmed in logs. Should show `Ollama cloud disabled: true`. |

The token-rate ceiling is roughly **sustained bandwidth ÷ model file size**, so don't expect
better than ~16–20 tok/s from a 3.3 GB model here, whatever the thread setting.

---

## 8. If something is wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl` to 11434 fails | server not running | `ollama serve`, leave the window open |
| Model answers in UI, not in a script | script pointed at the wrong port/host | use `127.0.0.1:11434`, not `localhost`, if DNS is odd |
| Very slow, fans loud | it's on CPU (expected), thermal throttling on a 45 W laptop | accept it; run batch jobs overnight |
| `ollama ps` shows GPU | env var not applied | restart the service after setting vars |
| Out of memory | `OLLAMA_NUM_PARALLEL` not 1, or `num_ctx` raised | set both per §5 |
| JSON comes back malformed | schema not passed to `format` | see §3c — the grammar is what guarantees it |

---

## 9. What we actually chose, and why

| | |
|---|---|
| **Runtime** | Ollama — single installer, no Python deps, and crucially **grammar-constrained JSON** |
| **Model** | `lfm2.5:8b` — **MoE, 8B total / ~1B active**, 2.5× faster than a dense 4B. Measured, not guessed |
| **Fallback model** | `qwen3.5:4b` — **Apache-2.0**, 3.3 GB, denser output for summaries and semantic PII |
| **Embeddings** | `embeddinggemma` — 768-dim, 621 MB. **Needs task prefixes** or retrieval quality silently drops |
| **Rejected** | The iGPU (shared bus, no gain). IPEX-LLM/BigDL (**Intel archived it**, one component with acknowledged security issues). `internlm3`, `nanbeige` (**couldn't verify they exist**). |

Despite the name, **nothing here talks to a cloud.** `OLLAMA_NO_CLOUD=1` is set, and the whole
point of this project is that the data stays on the disk.
