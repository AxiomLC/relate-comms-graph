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
DEFAULT_MODEL = "lfm2.5:8b"

# Kept for tasks that need denser, more consistent output (or when lfm misses).
# Not the default, but not deleted - it earns its disk on hard inputs.
FALLBACK_MODEL = "qwen3.5:4b"

EMBED_MODEL = "embeddinggemma"

# Turn thinking off. Measured: 368 tokens / 39.1 s -> 10 tokens / 1.4 s for "hello".
# Anything that honours `think` gets this for tagging and extraction.
THINK = False

# num_ctx is set globally via OLLAMA_CONTEXT_LENGTH; kept here so calls are explicit.
OPTIONS = {"temperature": 0, "num_ctx": 8192}


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
