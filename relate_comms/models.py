"""Which Ollama model this project uses, and when.

One place to change the default. Every call site goes through here so a model swap is
a one-line edit, not a grep.

Measured on this box (Lenovo17, i5-12500H, CPU only, 8 sample messages, 2026-11-14):

    model          json    median wall clock   decode
    qwen3.5:4b     8/8     4.12 s              8.5 tok/s
    lfm2.5:8b      8/8     1.99 s              21.3 tok/s

lfm2.5:8b is an 8B MoE with ~1B active per token. On a CPU that is the whole point:
you read one eighth of the weights per token, and decode is bandwidth-bound.

CAVEAT: 8 easy messages is not a benchmark. Both scored perfectly, but the samples were
unambiguous. Re-run tools/compare_models.py against ~50 real redacted messages before
trusting the default on hard input.
"""
from __future__ import annotations

# The model used unless a caller explicitly asks for another.
DEFAULT_MODEL = "qwen3.5:4b" # qwen3.5:4b  lfm2.5:8b

# **Currently the same as DEFAULT_MODEL**, because the default was switched to qwen.
# Kept as a separate name so `pick()` still has a second rung: when the default moves
# back to lfm2.5:8b, this is the denser model for `thread_summary` / `semantic_pii`.
FALLBACK_MODEL = "qwen3.5:4b"  # lfm2.5:8b

EMBED_MODEL = "embeddinggemma"

# Ask for no reasoning. Honoured by qwen3.5:4b; a NO-OP on lfm2.5:8b, which is a
# reasoning-only model with no switch (Liquid AI: "Can switch off: No"). Kept because
# it is the only legal value there and it is load-bearing on the fallback model.
#
# The old "368 tokens / 39.1 s -> 10 tokens / 1.4 s" note was measured on a model
# that honours the flag. It does NOT describe lfm2.5:8b.
THINK = False

# Speed knobs, CPU-only box. Every one of these was chosen from measurement or from
# the engine's own defaults, not taste:
#
#   num_ctx      8192  prefill is the CPU bottleneck; unused context still costs.
#   num_predict  2048  MUST be set. The default (-1) lets reasoning tokens eat the
#                      whole budget, and the model is then cut off mid-thought with
#                      an EMPTY answer. That is the empty-reply bug.
#   num_thread      4  the i5-12500H is 4 P-cores + 8 E-cores. llama.cpp scales
#                      poorly onto E-cores and oversubscribing often LOSES tok/s.
#                      Raise to 6/8 only if a local benchmark says so.
OPTIONS = {
    "temperature": 0,
    "num_ctx": 8192,
    "num_predict": 2048,
    "num_thread": 4,
}

# Keep the model resident. A cold load of a 5 GB model is pure latency, and the
# default 5-minute idle eviction means the first question after a pause pays it.
KEEP_ALIVE = -1


def pick(task: str, explicit: str | None = None) -> str:
    """Choose a model for a task.

    Default is the MoE for everything - fast and good enough on the samples we have.
    Use FALLBACK_MODEL when the task needs maximum consistency over speed.
    """
    if explicit:
        return explicit
    if task in {"thread_summary", "semantic_pii"}:
        # Fewer items, more tokens each, and a wrong answer is expensive.
        return FALLBACK_MODEL
    return DEFAULT_MODEL
