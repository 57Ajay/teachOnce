import hashlib
import json
import time
from pathlib import Path

import httpx

import config
import cost

SPARK = "muse-spark-1.3"
WONDER = "muse-wonder-1.0"
SAM = "sam-3.1"
TRANSCRIBE = "muse-voice-transcribe-1.0"

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5

stats = {"calls": 0}


class MetaAPIError(RuntimeError):
    pass


def _cassette(key: list) -> Path:
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    return config.CASSETTE_DIR / f"{digest}.json"


def _post(path: str, key: list, timeout: float, **kwargs) -> tuple[dict, int | None]:
    """Return (body, latency_ms). latency_ms is None when served from a cassette."""
    stats["calls"] += 1
    cassette = _cassette(key)
    if config.META_CACHE in ("record", "replay") and cassette.exists():
        return json.loads(cassette.read_text()), None
    if config.META_CACHE == "replay":
        raise MetaAPIError(f"no cassette for POST {path} (META_CACHE=replay)")
    if not config.META_API_KEY:
        raise MetaAPIError("META_API_KEY is not set")
    cost.check_budget()

    headers = {"Authorization": f"Bearer {config.META_API_KEY}"}
    start = time.monotonic()
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            r = httpx.post(config.META_BASE_URL + path, headers=headers, timeout=timeout, **kwargs)
        except httpx.TransportError:
            if last:
                raise
        else:
            if r.status_code not in RETRY_STATUS or last:
                break
        time.sleep(2**attempt)
    if r.is_error:
        raise MetaAPIError(f"POST {path} -> {r.status_code}: {r.text[:500]}")

    body = r.json()
    if config.META_CACHE == "record":
        cassette.parent.mkdir(parents=True, exist_ok=True)
        cassette.write_text(json.dumps(body))
    return body, int((time.monotonic() - start) * 1000)


def responses(purpose: str = "dev", timeout: float = 30, **body) -> dict:
    resp, latency = _post("/responses", ["/responses", body], timeout, json=body)
    if latency is not None:
        cost.record(body["model"], purpose, resp.get("usage") or {}, latency)
    if resp.get("status") != "completed":
        raise MetaAPIError(f"response {resp.get('status')}: {resp.get('incomplete_details') or resp.get('error')}")
    return resp


def output_text(resp: dict) -> str:
    return "".join(
        part["text"]
        for item in resp.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def structured(model: str, input, schema: dict, name: str, effort: str = "low",
               max_output_tokens: int = 8000, **kw) -> dict:
    resp = responses(
        model=model,
        input=input,
        reasoning={"effort": effort},
        max_output_tokens=max_output_tokens,
        text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        **kw,
    )
    return json.loads(output_text(resp))


def upload_file(path: str | Path, purpose: str = "user_data") -> str:
    path = Path(path)
    data = path.read_bytes()
    key = ["/files", hashlib.sha256(data).hexdigest(), purpose]
    resp, _ = _post("/files", key, 120, files={"file": (path.name, data)}, data={"purpose": purpose})
    return resp["id"]


def transcribe(wav_path: str | Path, keywords: list[str] | None = None, purpose: str = "teach") -> dict:
    wav_path = Path(wav_path)
    audio = wav_path.read_bytes()
    request = {
        "mode": "ENDPOINTING",
        "model": TRANSCRIBE,
        "audioEncoding": "WAV",
        "languageBias": ["English", "Hindi"],
        "keywords": keywords or [],
    }
    key = ["/asr/transcribe", hashlib.sha256(audio).hexdigest(), request]
    files = {
        "request": (None, json.dumps(request), "application/json"),
        "audio": (wav_path.name, audio, "audio/wav"),
    }
    resp, latency = _post("/asr/transcribe", key, 120, files=files)
    if latency is not None:
        cost.record(TRANSCRIBE, purpose, {"audio_s": resp.get("audioDurationMs", 0) / 1000}, latency)
    return resp
