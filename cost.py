import json
import time
from collections import defaultdict

import config

# USD per 1M tokens
TOKEN_PRICES = {
    "muse-spark-1.3": {"in": 1.25, "cached": 0.15, "out": 4.25},
    "muse-wonder-1.0": {"in": 4.00, "cached": 0.20, "out": 20.00},
}
SAM_PER_IMAGE = 2.50 / 1000
SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50
TRANSCRIBE_PER_HOUR = 0.18


class BudgetExceeded(RuntimeError):
    pass


def usd(model: str, usage: dict) -> float:
    if model.startswith("sam-"):
        frames = usage.get("video_frames_processed", 0)
        video = max(frames, SAM_MIN_FRAMES) * SAM_PER_FRAME if frames else 0.0
        return usage.get("images_processed", 0) * SAM_PER_IMAGE + video
    if model.startswith("muse-voice-transcribe"):
        return usage.get("audio_s", 0) / 3600 * TRANSCRIBE_PER_HOUR
    p = TOKEN_PRICES[model]
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    fresh = usage.get("input_tokens", 0) - cached
    return (fresh * p["in"] + cached * p["cached"] + usage.get("output_tokens", 0) * p["out"]) / 1e6


def record(model: str, purpose: str, usage: dict, latency_ms: int) -> float:
    amount = usd(model, usage)
    row = {"ts": time.time(), "model": model, "purpose": purpose, "usd": round(amount, 6),
           "latency_ms": latency_ms, "usage": usage}
    config.COST_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with config.COST_LEDGER.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return amount


def _rows():
    if not config.COST_LEDGER.exists():
        return []
    return [json.loads(line) for line in config.COST_LEDGER.read_text().splitlines() if line]


def spent_usd() -> float:
    return sum(r["usd"] for r in _rows())


def by_purpose() -> dict[str, float]:
    totals = defaultdict(float)
    for r in _rows():
        totals[r["purpose"]] += r["usd"]
    return dict(totals)


def check_budget():
    spent = spent_usd()
    if spent >= config.MAX_SPEND_USD:
        raise BudgetExceeded(f"spent ${spent:.2f} of ${config.MAX_SPEND_USD:.2f} budget")


def summary() -> str:
    lines = [f"  {k:<10} ${v:.4f}" for k, v in sorted(by_purpose().items())]
    lines.append(f"  {'total':<10} ${spent_usd():.4f} / ${config.MAX_SPEND_USD:.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
