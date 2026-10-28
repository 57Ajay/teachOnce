# Teach-Once: developer docs

## Modules

| Module | What it does |
|---|---|
| `config.py` | Loads `.env`; paths and settings. |
| `cost.py` | Price table, cost ledger (`data/costs.jsonl`), budget guard. `uv run cost.py` prints spend by purpose. |
| `meta_client.py` | Thin HTTP client for the Meta Model API: `responses`, `structured`, `upload_file`, `transcribe`. Retries, record/replay cache, logs every call's cost. |
| `sam.py` | SAM 3.1 request + output parsing into `Detection(box, confidence, mask)`, best match first. |
| `check_api.py` | Smoke test: one cheap call to Spark (structured output), SAM and Voice Transcribe. |
| `app.py` | The single FastAPI app: the portal under `/portal/*`, Teach-Once under `/app/*`, so everything is same-origin. |
| `portal.py` + `templates/portal/` | The Demoland TransitPass Portal, the fictional demo target, with drift levels. |
| `gen_data.py` | Writes fake CSV rows (`data/rows.csv`) that pass the portal's validation. |
| `workflow.py` | Workflow models (pydantic), `{{var}}` templating, immutable versioned files in `workflows/`. |
| `locate.py` | Resolves a target's locator chain to exactly one visible, enabled element. |
| `run.py` | The batch interpreter: runs a workflow over CSV rows with no model calls on the happy path. |
| `recording.py` | Saves a teach recording, cleans up raw DOM events, converts media with ffmpeg. |
| `static/recorder.js` + `templates/app/studio.html` | The teach studio: recording toolbar + the portal in a same-origin frame. |

## Meta Model API notes

Verified against the live API:

- **Auth:** `Authorization: Bearer $META_API_KEY`, base URL `https://api.meta.ai/v1`. Plain `httpx`, no SDK.
- **Reasoning:** Spark defaults to `reasoning.effort: "high"`, which burns output tokens even for trivial answers. Every call sets the effort explicitly.
- **Structured output (Responses API):** `text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": true}}`.
- **Video (Spark):** upload an mp4 to `POST /files` (`purpose=user_data`), then reference it as `{"type": "input_video", "file_id": ...}` (`input_file` works too). An 8 s 720p/10 fps clip is ~2.1k input tokens. Spark reads typed values well but misses clicks when no cursor is visible, so the DOM event log stays the source of truth for actions.
- **SAM 3.1:** a plain (non-streamed) `POST /responses` with `input_text` (a short noun phrase) + `input_image` as a **data URL** works. `metadata={"include_confidence": "true"}` adds `c=` to each box. Boxes are source pixels. It can return several matches (e.g. two buttons); pick by confidence. Cost is reported as `usage.images_processed`.
- **Voice Transcribe:** multipart `POST /asr/transcribe` with a `request` JSON part and an `audio` WAV part (mono, 16-bit, 24 kHz). `ENDPOINTING` mode returns `turns` with `startMs`/`endMs`.

## Demoland TransitPass Portal

A deliberately ordinary government-style flow: `/portal/login` → dashboard → `/portal/tax/new` (form) → review → pay → receipt (`DTP-YYYY-NNNNNN`). Demo login `operator` / `demo123` (override with `PORTAL_USER` / `PORTAL_PASSWORD`). State is in memory and resets on restart.

**Drift levels** simulate a site redesign. Set with `POST /portal/admin/drift {"level": N}` or `?drift=N` on any portal URL; the current level shows in a corner badge.

| Level | What changes |
|---|---|
| 0 | Original site. |
| 1 | Every `id`, `name` and `class` renamed; form becomes two columns in a different order; submit button moves to the top and becomes "Compute Payable Amount". |
| 2 | Level 1 + reworded labels; the date input becomes Day/Month/Year selects; the tax-period radios become a select. |
| 3 | Level 2 + a cookie-consent modal blocking every page until accepted, and a "Session notice" page before review. |

The server reads fields through the same rename map, and each form posts the layout it was rendered with (`_layout`), so a form opened before a mid-run drift switch still submits.

## Workflows and the runner

A workflow (`workflows/<id>.v<N>.json`) is a list of steps. Each step has an `action` (`goto`, `click`, `fill`, `fill_date`, `select`, `check`, `uncheck`, `press`, `wait_for`, `extract`, `assert_text`), an optional `target`, a templated `value`, and a `check` that proves it worked (`value_equals`, `url_contains`, `text_visible`, `element_visible`, `element_hidden`). Values and locator text can use `{{variable}}` (CSV columns), `{{secret}}` (env vars) and `{{PORTAL_URL}}`.

A target carries a **locator chain**, most robust first (role + accessible name, label, placeholder, text, CSS). The runner polls the chain until one locator matches exactly one visible, enabled element. That is why cosmetic drift (renamed ids) often needs no heal: the role/label locators still match.

`uv run run.py workflows/pay-interstate-tax.v1.json data/rows.csv [--start N] [--limit N] [--headed]`

- Rows run sequentially, one fresh browser context per row (clean cookies, so per-row popups behave like a new visitor). Viewport 1280×800, device scale factor 1, so screenshot pixels equal CSS pixels.
- A failing step stops the row with a typed failure: `locator_not_found`, `blocked_by_overlay` (the click hit another element, e.g. a modal), `check_failed` or `action_failed`. Steps marked `optional` are skipped on failure.
- Output goes to `data/runs/<run_id>/`: `results.jsonl` (one line per row: status, outputs, duration, model calls, cost), `events.jsonl` (the event stream the dashboard will use), `summary.json`, and `steps/*.png` screenshots (every step of the first row, every failure, every row's last step).

`workflows/pay-interstate-tax.v1.json` is hand-written for now; the teach pipeline will generate these.

## Teaching (the recorder)

Open `/app/teach/new`. The studio shows a toolbar and the portal in a 1280×800 frame (the runner's viewport). **Start teaching** asks to share the tab and the microphone, signs the portal out, and starts recording. Do the task in the frame while saying what you're doing; **Stop** uploads everything.

Why a studio page instead of injecting a script into the portal: the portal is multi-page, and every navigation would kill an injected script together with its screen and mic recorders. The studio page never navigates; because the frame is same-origin, it attaches capture-phase listeners to each page the frame loads.

A recording lands in `data/recordings/<rec_id>/`:

- `events_raw.jsonl`: every click / change / submit / Enter, with the element's role, accessible name, label, placeholder, id, name, a unique CSS path, XPath and bounding box (frame CSS pixels). Password values are stored as `***`. A typed field is timestamped when typing started.
- `events.jsonl`: one event per user intent, each with an `action` (`fill`, `fill_date`, `select`, `check`, `uncheck`, `click`, `press`, `navigation`). Focus clicks on fields, label clicks, Tab presses and submits caused by the preceding click/Enter are dropped.
- `teach.mp4`: the tab video cropped to the portal frame, 720p, 10 fps, no audio (for Muse Spark).
- `narration.wav`: mono, 16-bit, 24 kHz (for Voice Transcribe).
- `meta.json`: start time, duration, frame geometry, drift level, whether there was narration.

`/app/teach/<rec_id>` shows the video, narration and captured events.

## Record/replay cache

`META_CACHE` in `.env`:

- `off` (default): always call the API.
- `record`: reuse a saved response if one exists for the exact same request, otherwise call and save it to `data/cassettes/`.
- `replay`: only saved responses; a missing one is an error. Nothing is spent.

## Tests

The portal, runner and studio tests drive a real Chromium (the studio test uses Chromium's fake camera/mic/tab-capture flags). On a fresh machine run `uv run playwright install chromium` once. In an environment with its own Chromium, set `CHROMIUM_PATH` in `.env`.

`uv run pytest` runs offline. Tests that hit the real API are marked `live` and skipped by default (`uv run pytest -m live` to run them).
