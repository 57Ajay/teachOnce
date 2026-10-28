# Teach-Once: developer docs

## Modules

| Module | What it does |
|---|---|
| `config.py` | Loads `.env`; paths and settings. |
| `cost.py` | Price table, cost ledger (`data/costs.jsonl`), budget guard. `uv run cost.py` prints spend by purpose. |
| `meta_client.py` | Thin HTTP client for the Meta Model API: `responses`, `structured`, `upload_file`, `transcribe`. Retries, record/replay cache, logs every call's cost. |
| `sam.py` | SAM 3.1 request + output parsing into `Detection(box, confidence, mask)`, best match first. |
| `check_api.py` | Smoke test: one cheap call to Spark (structured output), SAM and Voice Transcribe. |

## Meta Model API notes

Verified against the live API:

- **Auth:** `Authorization: Bearer $META_API_KEY`, base URL `https://api.meta.ai/v1`. Plain `httpx`, no SDK.
- **Reasoning:** Spark defaults to `reasoning.effort: "high"`, which burns output tokens even for trivial answers. Every call sets the effort explicitly.
- **Structured output (Responses API):** `text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": true}}`.
- **Video (Spark):** upload an mp4 to `POST /files` (`purpose=user_data`), then reference it as `{"type": "input_video", "file_id": ...}` (`input_file` works too). An 8 s 720p/10 fps clip is ~2.1k input tokens. Spark reads typed values well but misses clicks when no cursor is visible, so the DOM event log stays the source of truth for actions.
- **SAM 3.1:** a plain (non-streamed) `POST /responses` with `input_text` (a short noun phrase) + `input_image` as a **data URL** works. `metadata={"include_confidence": "true"}` adds `c=` to each box. Boxes are source pixels. It can return several matches (e.g. two buttons); pick by confidence. Cost is reported as `usage.images_processed`.
- **Voice Transcribe:** multipart `POST /asr/transcribe` with a `request` JSON part and an `audio` WAV part (mono, 16-bit, 24 kHz). `ENDPOINTING` mode returns `turns` with `startMs`/`endMs`.

## Record/replay cache

`META_CACHE` in `.env`:

- `off` (default): always call the API.
- `record`: reuse a saved response if one exists for the exact same request, otherwise call and save it to `data/cassettes/`.
- `replay`: only saved responses; a missing one is an error. Nothing is spent.

## Tests

`uv run pytest` runs offline. Tests that hit the real API are marked `live` and skipped by default (`uv run pytest -m live` to run them).
