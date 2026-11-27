# Ollama on Windows — for this app

Short guide. The app talks to Ollama on `127.0.0.1:11434`; nothing here is specific to one
machine beyond the paths.

---

## 1. Three things that waste your time

### 1a. The service and `keep_alive` are different things

| | What it is | How to control it |
|---|---|---|
| **Ollama service** | The background program that *can* serve models | Start it, or let it autostart |
| **`keep_alive`** | How long a **loaded model** stays in RAM after the last request | Env var or per-request option |

The service can run with **zero models in memory**. `keep_alive` decides what happens
*after* a request, not whether the program starts.

**Closing the service window frees everything**, regardless of `keep_alive`.

### 1b. Thinking is on by default on some models, and it is expensive

Measured on `qwen3.5:4b`, same prompt ("Hello"):

| | tokens generated | wall time |
|---|---|---|
| default (thinking) | **368** | **39.1 s** |
| `"think": false` | **10** | **1.4 s** |

The fix is an API parameter, not a prompt:

```python
from relate_comms.models import pick, THINK, OPTIONS

resp = ollama.chat(
    model=pick("chat"),
    messages=[{"role": "user", "content": msg}],
    think=THINK,          # False
    options=OPTIONS,
)
```

⚠️ **`/no_think` in the system prompt does NOT work** on Qwen3.5 — tested, still 368 tokens.
Blog posts recommend it because it worked on Qwen3.

⚠️ **`think: false` is a no-op on `lfm2.5:8b`.** Liquid AI's own table says that model cannot
switch thinking off; there is no `enable_thinking` in its chat template. What actually
matters there is `num_predict` (unset lets reasoning eat the budget and return an empty
answer) and `keep_alive: -1`.

### 1c. Model choice — measured, not guessed

Head-to-head on 8 sample messages, same schema, CPU only:

| Model | JSON valid | Median wall clock | Decode |
|---|---|---|---|
| `qwen3.5:4b` | 8/8 | 4.12 s | 8.5 tok/s |
| **`lfm2.5:8b`** | 8/8 | **1.99 s** | **21.3 tok/s** |

`lfm2.5:8b` is an 8B model with **~1B active parameters** per token (MoE). On a CPU that is
decisive: decode is bandwidth-bound, so reading one eighth of the weights per token is a
2.5× win.

**Honest caveat:** 8 easy messages is not a benchmark. Both scored perfectly because the
samples were unambiguous. Re-run `tools/compare_models.py` on ~50 real redacted messages
before trusting either on messy input.

---

## 2. Where things live

| Thing | Path |
|---|---|
| Program | `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` |
| Models | `%USERPROFILE%\.ollama\models` |
| Server | `http://127.0.0.1:11434` |
| OpenAI-compatible API | `http://127.0.0.1:11434/v1` (any dummy key) |

**Is the server up?**

```bash
curl -s http://127.0.0.1:11434/api/version
```

The bare URL showing "Ollama is running" is normal — that is the root status page, not an
app. The useful endpoints are `/api/...`.

---

## 3. Testing it

### The 10-second test (terminal — proves the *API*, not just the UI)

```bash
curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"lfm2.5:8b\",\"prompt\":\"hi\",\"stream\":false}"
```

### The test that matters — structured output

The pipeline lives or dies on valid JSON. Pass a schema to `format` and the decoder is
**grammar-constrained** — it cannot emit malformed JSON:

```bash
curl -s http://127.0.0.1:11434/api/chat -d "{
  \"model\":\"lfm2.5:8b\",
  \"messages\":[{\"role\":\"user\",\"content\":\"see you thursday\"}],
  \"stream\":false,
  \"format\":{\"type\":\"object\",\"properties\":{\"topics\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"topics\"]}
}"
```

### Did it use the CPU or the GPU?

```bash
ollama ps
```

The `PROCESSOR` column should say **100% CPU**. An integrated GPU shares the same memory bus,
so it cannot help decode.

---

## 4. Settings

Set at **user scope**, then restart the service — env vars are read at startup.

```
OLLAMA_CONTEXT_LENGTH=8192   # default 4096
OLLAMA_FLASH_ATTENTION=1     # required for KV quantisation
OLLAMA_KV_CACHE_TYPE=q8_0    # halves KV memory; ~zero speed cost
OLLAMA_KEEP_ALIVE=5m         # models evict 5 min after last use
OLLAMA_NUM_PARALLEL=1        # parallel multiplies KV and can OOM a 16 GB box
OLLAMA_MAX_LOADED_MODELS=1   # one model in RAM at a time
OLLAMA_NO_CLOUD=1            # the product promise. Nothing leaves the machine.
```

Re-apply on this machine: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/set_ollama_env.ps1`

### The one thing that is NOT an env var

**`num_thread`.** `OLLAMA_NUM_THREADS` does not exist — the feature request was closed as a
duplicate. Thread count must go in a **Modelfile**:

```dockerfile
FROM lfm2.5:8b
PARAMETER num_thread 4
PARAMETER num_ctx 8192
PARAMETER temperature 0
```

```bash
ollama create relate-batch -f Modelfile
```

On a 4P+8E laptop, theory says 4–6 threads wins and 16 is worst — every layer waits for the
slowest thread, and E-cores are slow. **Unmeasured here.**

---

## 5. Day-to-day commands

```bash
ollama list                  # what's installed
ollama ps                    # what's loaded, and CPU vs GPU
ollama pull lfm2.5:8b        # download (RESUMES if interrupted - just re-run it)
ollama rm <model>            # remove
ollama show lfm2.5:8b        # model details, context length, parameters
ollama serve                 # run the server manually
```

---

## 6. If something is wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl` to 11434 fails | server not running | `ollama serve`, leave the window open |
| Model answers in UI, not in a script | wrong port/host | use `127.0.0.1:11434`, not `localhost`, if DNS is odd |
| Very slow, fans loud | it is on CPU (expected) | accept it; run batch jobs overnight |
| `ollama ps` shows GPU | env var not applied | restart the service after setting vars |
| Out of memory | `OLLAMA_NUM_PARALLEL` not 1, or `num_ctx` raised | set both per §4 |
| JSON comes back malformed | schema not passed to `format` | §3 — the grammar is what guarantees it |
| Chat answers a different question | tool result exceeded `MAX_TOOL_CHARS` | summarised, not silently cut |

---

## 7. What we chose, and why

| | |
|---|---|
| **Runtime** | Ollama — single installer, no Python deps, and **grammar-constrained JSON** |
| **Model** | `lfm2.5:8b` — MoE, 8B total / ~1B active, 2.5× faster than a dense 4B. Measured |
| **Fallback** | `qwen3.5:4b` — Apache-2.0, 3.3 GB, denser output, and its `think: false` works |
| **Embeddings** | `embeddinggemma` — 768-dim, 621 MB. **Needs task prefixes** or retrieval quality silently drops |
| **Rejected** | The iGPU (shared bus, no gain). IPEX-LLM/BigDL (Intel archived it). |

Despite the name, **nothing here talks to a cloud.** `OLLAMA_NO_CLOUD=1` is set, and the
whole point of this project is that the data stays on the disk.
