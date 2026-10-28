"""Smoke-test every Meta model we use with tiny, cheap calls. Usage: uv run check_api.py"""
import subprocess
import tempfile
import time
from pathlib import Path

import config
import cost
import meta_client
import sam

FIXTURES = config.ROOT / "tests" / "fixtures"


def timed(label, fn):
    start = time.monotonic()
    try:
        result = fn()
        print(f"ok    {label} ({time.monotonic() - start:.1f}s): {result}")
    except Exception as e:
        print(f"FAIL  {label}: {e}")


def check_structured():
    schema = {
        "type": "object",
        "properties": {"field": {"type": "string"}, "is_variable": {"type": "boolean"}},
        "required": ["field", "is_variable"],
        "additionalProperties": False,
    }
    prompt = "The user typed NV07AB1234 into 'Vehicle registration number' and said 'this changes per row'."
    return meta_client.structured(meta_client.SPARK, prompt, schema, "field_check", purpose="spike")


def check_sam():
    detections = sam.segment((FIXTURES / "form.png").read_bytes(), "calculate tax button", purpose="spike")
    return [(d.box, round(d.confidence or 0, 2)) for d in detections]


def check_transcribe():
    text = "This is the vehicle number from the sheet. Now I click calculate tax."
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"flite=text='{text}'",
             "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(wav)],
            check=True,
        )
        resp = meta_client.transcribe(wav, keywords=["vehicle number", "calculate tax"], purpose="spike")
    return [(t["startMs"], t["endMs"], t["transcript"]) for t in resp.get("turns", [])] or resp


if __name__ == "__main__":
    timed("spark structured output", check_structured)
    timed("sam-3.1 data url", check_sam)
    timed("voice transcribe", check_transcribe)
    print(cost.summary())
