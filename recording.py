"""Teach recordings: save the uploaded bundle, clean up raw DOM events, convert media for the models."""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

import config

REC_DIR = config.DATA_DIR / "recordings"
FIELD_TAGS = {"input", "select", "textarea"}
BUTTON_TYPES = {"submit", "button", "reset", "image"}


def strip_required(name: str) -> str:
    """Accessible names include the trailing " *" of required fields."""
    return re.sub(r"\s*\*$", "", name or "")


def is_field(target: dict) -> bool:
    return target.get("tag") in FIELD_TAGS and target.get("type") not in BUTTON_TYPES


def action_for(event: dict) -> str:
    t = event.get("target") or {}
    match event["type"]:
        case "change" if t.get("tag") == "select":
            return "select"
        case "change" if t.get("type") == "checkbox":
            return "check" if event.get("checked") else "uncheck"
        case "change" if t.get("type") == "radio":
            return "check"
        case "change" if t.get("type") == "date":
            return "fill_date"
        case "change":
            return "fill"
        case "keydown":
            return "press"
        case other:
            return other


def normalize(raw: list[dict]) -> list[dict]:
    """Keep one event per user intent.

    Clicks on form fields and labels are dropped (the change event carries the result), as are
    Tab presses and submits caused by the click or Enter just before them.
    """
    out = []
    for e in sorted(raw, key=lambda e: e["ts_ms"]):
        t = e.get("target") or {}
        if e["type"] == "click" and (t.get("tag") == "label" or is_field(t)):
            continue
        if e["type"] == "keydown" and e.get("key") != "Enter":
            continue
        if e["type"] == "submit" and out and out[-1]["type"] in ("click", "keydown") and e["ts_ms"] - out[-1]["ts_ms"] < 1000:
            continue
        out.append(dict(e))
    for i, e in enumerate(out):
        e["idx"] = i
        e["action"] = action_for(e)
    return out


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


def to_mp4(src: Path, dst: Path, frame_rect: dict | None):
    """Crop the tab video to the portal frame, then 720p at 10 fps (what Spark gets)."""
    filters = []
    if frame_rect:
        w, h = frame_rect["inner_w"], frame_rect["inner_h"]
        x, y, fw, fh = frame_rect["x"], frame_rect["y"], frame_rect["w"], frame_rect["h"]
        filters.append(f"crop=trunc(iw*{fw / w}/2)*2:trunc(ih*{fh / h}/2)*2:iw*{x / w}:ih*{y / h}")
    filters += ["scale=-2:720", "fps=10"]
    ffmpeg("-i", src, "-vf", ",".join(filters), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", dst)


def to_wav(src: Path, dst: Path):
    ffmpeg("-i", src, "-ac", 1, "-ar", 24000, "-sample_fmt", "s16", "-map_metadata", -1, dst)


def duration_ms(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return int(float(out) * 1000) if out and out != "N/A" else 0


def write_jsonl(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def save(meta: dict, events: list[dict], screen: bytes, mic: bytes | None) -> str:
    rec_id = datetime.now().strftime("rec_%Y%m%d_%H%M%S")
    d = REC_DIR / rec_id
    d.mkdir(parents=True)
    write_jsonl(d / "events_raw.jsonl", events)
    write_jsonl(d / "events.jsonl", normalize(events))
    (d / "screen.webm").write_bytes(screen)
    to_mp4(d / "screen.webm", d / "teach.mp4", meta.get("frame_rect"))
    if mic:
        (d / "mic.webm").write_bytes(mic)
        to_wav(d / "mic.webm", d / "narration.wav")
    meta.update(rec_id=rec_id, duration_ms=duration_ms(d / "teach.mp4"), has_narration=bool(mic))
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return rec_id


def load(rec_id: str) -> dict:
    d = REC_DIR / rec_id
    if not (d / "meta.json").exists():
        raise FileNotFoundError(rec_id)
    events = [json.loads(line) for line in (d / "events.jsonl").read_text().splitlines()]
    return {"meta": json.loads((d / "meta.json").read_text()), "events": events, "dir": d}


def list_all() -> list[dict]:
    if not REC_DIR.exists():
        return []
    metas = [json.loads(p.read_text()) for p in REC_DIR.glob("*/meta.json")]
    return sorted(metas, key=lambda m: m["rec_id"], reverse=True)
