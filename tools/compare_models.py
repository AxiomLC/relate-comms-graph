"""Head-to-head: qwen3.5:4b (dense 4B) vs lfm2.5:8b (MoE, ~1B active).

Same prompts, same JSON schema, same options. Measures what actually matters for
this pipeline: decode speed, wall-clock, and whether the JSON validates.

Run: python tools/compare_models.py
"""
from __future__ import annotations

import statistics
import sys
import time

import ollama
from pydantic import BaseModel
from typing import Literal

MODELS = ["qwen3.5:4b", "lfm2.5:8b"]

SYSTEM = (
    "You tag personal chat messages. Output only JSON. "
    "topics must be from: work, family, money, health, logistics, social."
)

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
    has_commitment: bool


def run(model: str) -> dict:
    ok = 0
    lat: list[float] = []
    tps: list[float] = []
    errors: list[str] = []

    # warmup, excluded from stats
    try:
        ollama.chat(
            model=model,
            messages=[{"role": "user", "content": "warmup"}],
            think=False,
            options={"num_predict": 1},
        )
    except TypeError:
        # model doesn't accept `think` - retry without it
        ollama.chat(model=model, messages=[{"role": "user", "content": "warmup"}],
                    options={"num_predict": 1})

    for msg in SAMPLES:
        t0 = time.perf_counter()
        try:
            resp = ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": msg},
                ],
                format=Tagged.model_json_schema(),
                think=False,
                options={"temperature": 0, "num_ctx": 8192},
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
            continue
        lat.append(time.perf_counter() - t0)

        try:
            Tagged.model_validate_json(resp.message.content)
            ok += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"invalid json: {e}")

        ec = getattr(resp, "eval_count", None)
        ed = getattr(resp, "eval_duration", None)
        if ec and ed:
            tps.append(ec / (ed / 1e9))

    return {
        "model": model,
        "json": f"{ok}/{len(SAMPLES)}",
        "median_s": round(statistics.median(lat), 2) if lat else None,
        "tok_s": round(statistics.median(tps), 1) if tps else None,
        "errors": errors[:3],
    }


def main() -> int:
    results = []
    for m in MODELS:
        print(f"\n=== {m} ===")
        r = run(m)
        results.append(r)
        print(f"  json ok : {r['json']}")
        print(f"  median  : {r['median_s']}s")
        print(f"  tok/s   : {r['tok_s']}")
        if r["errors"]:
            print(f"  errors  : {r['errors'][0]}")

    print("\n--- verdict ---")
    best_speed = max((r for r in results if r["tok_s"]), key=lambda r: r["tok_s"])
    best_json = max(results, key=lambda r: int(r["json"].split("/")[0]))
    print(f"fastest decode : {best_speed['model']} ({best_speed['tok_s']} tok/s)")
    print(f"best json      : {best_json['model']} ({best_json['json']})")

    base = results[0]["median_s"]
    for r in results[1:]:
        if base and r["median_s"]:
            delta = (base - r["median_s"]) / base * 100
            print(f"{r['model']} is {delta:+.0f}% vs {results[0]['model']} (median wall clock)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
