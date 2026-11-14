"""Stage 10a: settle the two open Ollama questions on THIS box with measurements.

  1. Which num_thread wins on a 4P+8E Alder Lake-H? (theory: 6 beats 4 beats 8)
  2. Does the Iris Xe iGPU help decode? (theory: no - it shares the same memory bus)

Also measures the thing that actually matters for this pipeline: JSON schema
adherence under grammar-constrained decoding.

Run: python tools/bench_ollama.py [--quick]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Any

import ollama
from pydantic import BaseModel
from typing import Literal

MODEL = "qwen3.5:4b"

# A fixed, realistic prefix. In the real pipeline this is the system prompt + schema
# and it is byte-identical on all ~50k requests, so prefix caching amortises it.
SYSTEM = "You tag personal chat messages. Output only JSON matching the schema."

SAMPLES = [
    "see you thursday at the pub then?",
    "can you send me the invoice for last month please",
    "mum said shes coming over sunday, bringing the dog",
    "loved that place on otley road, we should go again",
    "running 20 mins late sorry, traffic on the ring road",
    "did you ever hear back about the leeds job?",
    "happy birthday!! hope you have a good one",
    "i'll transfer you the 40 tonight",
]


class Tagged(BaseModel):
    topics: list[Literal["work", "family", "money", "health", "logistics", "social"]]
    sentiment: Literal["positive", "neutral", "negative"]
    has_commitment: bool


def make_model(threads: int) -> str:
    """num_thread is NOT an env var - it must live in a Modelfile."""
    name = f"qwen35-4b-t{threads}"
    ollama.create(
        model=name,
        from_=MODEL,
        parameters={"num_thread": threads, "num_ctx": 8192, "temperature": 0},
    )
    return name


def bench(threads: int, samples: list[str]) -> dict[str, Any]:
    model = make_model(threads)
    ok = 0
    latencies: list[float] = []
    tok_rates: list[float] = []

    # warm the model so load time isn't counted as generation time
    ollama.chat(model=model, messages=[{"role": "user", "content": "warmup"}],
                options={"num_predict": 1})

    for msg in samples:
        t0 = time.perf_counter()
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": msg},
            ],
            format=Tagged.model_json_schema(),
            options={"temperature": 0, "num_ctx": 8192},
        )
        latencies.append(time.perf_counter() - t0)
        try:
            Tagged.model_validate_json(resp.message.content)
            ok += 1
        except Exception:
            pass
        # ollama reports eval counts on the response
        ec = getattr(resp, "eval_count", None)
        ed = getattr(resp, "eval_duration", None)
        if ec and ed:
            tok_rates.append(ec / (ed / 1e9))

    return {
        "threads": threads,
        "json_ok": f"{ok}/{len(samples)}",
        "median_s": round(statistics.median(latencies), 2),
        "tok_s": round(statistics.median(tok_rates), 1) if tok_rates else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="3 samples instead of 8")
    args = ap.parse_args()

    samples = SAMPLES[:3] if args.quick else SAMPLES
    print(f"model: {MODEL}   samples: {len(samples)}")
    print(f"{'threads':>8} {'json':>8} {'median_s':>9} {'tok/s':>7}")
    print("-" * 36)

    results = []
    for t in (4, 6, 8):
        r = bench(t, samples)
        results.append(r)
        print(f"{r['threads']:>8} {r['json_ok']:>8} {r['median_s']:>9} {str(r['tok_s']):>7}")

    best = min((r for r in results if r["tok_s"]), key=lambda r: r["median_s"])
    print(f"\nwinner by median latency: num_thread {best['threads']}")
    print("note: tok_s is decode only; latency includes prefill and is what you feel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
