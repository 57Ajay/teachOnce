# Teach-Once: developer docs

## Modules

| Module | What it does |
|---|---|
| `config.py` | Loads `.env`; paths and settings. |
| `cost.py` | Price table, cost ledger (`data/costs.jsonl`), budget guard. `uv run cost.py` prints spend by purpose. |
| `meta_client.py` | Thin HTTP client for the Meta Model API: `responses`, `structured`, `upload_file`, `transcribe`. Retries, record/replay cache, logs every call's cost. |
| `sam.py` | SAM 3.1 request + output parsing into `Detection(box, confidence, mask)`, best match first. |
| `check_api.py` | Smoke test: one cheap call to Spark (structured output), SAM and Voice Transcribe. |
| `app.py` | The single FastAPI app: the portal under `/portal/*`, Teach-Once under `/app/*`, so everything is same-origin. Starts compile jobs and runs in background threads and streams run events to the dashboard. |
| `templates/app/run.html` + `static/runs.js` | The live run dashboard. |
| `portal.py` + `templates/portal/` | The Demoland TransitPass Portal, the fictional demo target, with drift levels. |
| `gen_data.py` | Writes fake CSV rows (`data/rows.csv`) that pass the portal's validation. |
| `workflow.py` | Workflow models (pydantic), `{{var}}` templating, immutable versioned files in `data/workflows/`. |
| `locate.py` | Resolves a target's locator chain to exactly one visible, enabled element. |
| `run.py` | The batch interpreter: runs a workflow over CSV rows with no model calls on the happy path; calls the healer when a step breaks. |
| `heal.py` | Self-healing: Muse Spark triages what changed, SAM 3.1 grounds the element, the patch is verified and saved as the next version. |
| `recording.py` | Saves a teach recording, cleans up raw DOM events, converts media with ffmpeg. |
| `static/recorder.js` + `templates/app/studio.html` | The teach studio: recording toolbar + the portal in a same-origin frame. |
| `static/describe.js` | How an element is described (role, accessible name, label, css, box). Shared by the studio and, injected, by the healer. |
| `examples/` | Committed sample workflows and the measured `baseline_summary.json`. Generated and healed workflows live in `data/workflows/` (git-ignored). |
| `teach.py` | The teach pipeline: cleans the recording, then transcribe → understand → compile → dry run → export. |
| `understand.py` | Muse Spark watches the teach video with the event log and narration and returns a step graph. |
| `compiler.py` | Muse Wonder turns the recorded skeleton + step graph into a workflow; lint, repair, export script. |
| `prompts.py` | All prompts, with version tags that are logged with each call. |
| `baseline.py` | The comparison: a pure computer-use agent (Muse Spark) doing the same task from screenshots, per row. Writes `data/baseline_summary.json`. |

## Meta Model API notes

Verified against the live API:

- **Auth:** `Authorization: Bearer $META_API_KEY`, base URL `https://api.meta.ai/v1`. Plain `httpx`, no SDK.
- **Reasoning:** Spark defaults to `reasoning.effort: "high"`, which burns output tokens even for trivial answers. Every call sets the effort explicitly.
- **Structured output (Responses API):** `text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": true}}`.
- **Video (Spark):** upload an mp4 to `POST /files` (`purpose=user_data`), then reference it as `{"type": "input_video", "file_id": ...}` (`input_file` works too). An 8 s 720p/10 fps clip is ~2.1k input tokens. Spark reads typed values well but misses clicks when no cursor is visible, so the DOM event log stays the source of truth for actions.
- **SAM 3.1:** a plain (non-streamed) `POST /responses` with `input_text` (a short noun phrase) + `input_image` as a **data URL** works. `metadata={"include_confidence": "true"}` adds `c=` to each box. Boxes are source pixels. It can return several matches (e.g. two buttons); pick by confidence. Cost is reported as `usage.images_processed`.
- **Computer use (Spark):** `tools=[{"type": "computer"}]` on `/responses`, no display size or environment needed. The answer holds `computer_call` items with an **`actions` list** (Spark batches, e.g. click, type, Tab, type, Enter in one call): `click{button,x,y}`, `type{text}`, `keypress{keys}`, `scroll{x,y,scroll_x,scroll_y}`, ... Every call carries `pending_safety_checks` (code `computer_action_requires_confirmation`) and a `meta_safety_replay_receipt`. Reply with `{"type": "computer_call_output", "call_id": ..., "acknowledged_safety_checks": <the pending checks, as given>, "output": {"type": "computer_screenshot", "image_url": <PNG data URL>}}` and `previous_response_id`. Without the acknowledgement: 400 "Every pending computer safety check must be acknowledged exactly once". The receipt does not need to be echoed. Coordinates are screenshot pixels, but `scroll_y` is in wheel notches (Spark sends 5 or 6; `baseline.py` scrolls 100 px per notch). The history is kept server-side, so input tokens grow every turn (only partly cached). **A chain is capped:** the 30th request of a computer-use `previous_response_id` chain fails with a generic 400 "The request contains invalid parameters" (reproduced on a one-button page; 31 screenshots in one request and a 35-turn chain without the computer tool are fine).
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

A workflow (`<id>.v<N>.json`) is a list of steps. Each step has an `action` (`goto`, `click`, `fill`, `fill_date`, `select`, `check`, `uncheck`, `press`, `wait_for`, `extract`, `assert_text`), an optional `target`, a templated `value`, and a `check` that proves it worked (`value_equals`, `url_contains`, `text_visible`, `element_visible`, `element_hidden`). Values and locator text can use `{{variable}}` (CSV columns), `{{secret}}` (env vars) and `{{PORTAL_URL}}`.

A target carries a **locator chain**, most robust first (role + accessible name, label, placeholder, text, CSS). The runner polls the chain until one locator matches exactly one visible, enabled element. That is why cosmetic drift (renamed ids) often needs no heal: the role/label locators still match.

`uv run run.py examples/pay-interstate-tax.v1.json data/rows.csv [--start N] [--limit N] [--headed] [--no-heal]`

- Rows run sequentially, one fresh browser context per row (clean cookies, so per-row popups behave like a new visitor). Viewport 1280×800, device scale factor 1, so screenshot pixels equal CSS pixels.
- A failing step stops the row with a typed failure: `locator_not_found`, `blocked_by_overlay` (the click hit another element, e.g. a modal), `check_failed` or `action_failed`. Steps marked `optional` are skipped on failure.
- Output goes to `data/runs/<run_id>/`: `results.jsonl` (one line per row: status, outputs, duration, model calls, cost), `events.jsonl` (the event stream the dashboard shows), `summary.json`, and `steps/*.png` screenshots (every step of the first row, every failure, every row's last step).

`examples/pay-interstate-tax.v1.json` is hand-written; the teach pipeline generates the same format.

A workflow can also carry `interrupts`: things that can get in the way (a consent modal, an interstitial page) and the button that clears them. Before each step, and while a URL check waits, the runner clicks any interrupt that is showing. No model is involved; the healer learns them.

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

## Teach pipeline (recording → workflow)

`uv run teach.py <rec_id>` (or **Compile workflow** on `/app/teach/<rec_id>`). The portal must be running, because the last stage replays the draft on it. Stages:

1. **Final pass** (no model): a click that lands back on the same page was a failed submit (validation error), so it is dropped, and fields re-entered afterwards update the original step. Mistakes made while teaching don't end up in the workflow.
2. **Transcribe** (Voice Transcribe): narration → timestamped turns, with the field labels as keywords. Keywords over 30 characters are rejected by the API, so they are filtered out. No narration is fine.
3. **Understand** (Muse Spark, reasoning effort high): the 720p/10 fps video + the event table + the narration → a step graph: intent, per-row variable or constant (with the reason), a visual description and a short SAM noun phrase per target, and the task's outputs. The event log is the ground truth for actions; Spark adds meaning. Cached in `step_graph.json`.
4. **Compile** (Muse Wonder, effort medium): a deterministic skeleton (one entry per action, with locator candidates built from what the recorder saw) + the step graph + the CSV columns → a workflow under a strict JSON schema. It maps variables to CSV columns, templates values, turns masked passwords into secrets, adds checks and an extract step per output.
Anchors (where each element was during teaching) come from the recording, not from Wonder. Only id-based CSS selectors are kept as locators: a positional path like `div > div > button` can match a different element after a redesign.

5. **Lint** (no model): one step per recorded action, an extract per output, no CSS selector that wasn't recorded, every `{{var}}` declared, every column in the CSV. Problems go back to Wonder for one repair call.
6. **Dry run**: the draft runs at drift 0 on the recorded example **plus the first CSV rows**, which catches workflows that only fit the example (e.g. a regex that doesn't allow "3,025.00"). A failure goes back to Wonder with the error for one repair call.
7. **Export** (Muse Wonder, effort low): a standalone Playwright script (`data/workflows/export_<id>.py`) with the same steps, as the visible "compiled program". It reads secrets from the environment (`PORTAL_PASSWORD=demo123 python data/workflows/export_<id>.py data/rows.csv`).

The workflow is saved as `data/workflows/<id>.v<N>.json`; the recording folder gets the drafts, `examples.csv` and `compiled.json` (cost, time, file names).

Measured on a real 100 s recording: Spark ~37 s / $0.06 (26k input tokens), Wonder compile ~20 s / $0.13–0.16, export ~18 s / $0.09. About $0.25–0.40 per teach.

## Self-healing

When a step fails (`locator_not_found`, `blocked_by_overlay`, or a `check_failed` such as landing on an unexpected page), the runner hands the live page to `heal.py`:

1. **Look.** A full-page screenshot plus a numbered list of the page's interactive elements (role, accessible name, label, placeholder, box), from `describe.js`.
2. **Triage (Muse Spark, effort medium, one call per page).** Spark gets the screenshot, the element list, the failing step and every later step on the same page whose locators no longer resolve. It answers per step: `moved`, `control_changed` (radios became a dropdown), `split_into_parts` (a date input became day/month/year dropdowns) or `not_found`, with the element's ref and a short *visual* noun phrase. Or it reports an **interruption** (a consent modal, a session-notice page) and the button that clears it.
3. **Ground (SAM 3.1).** SAM segments every control matching each noun phrase ("white input box", "dropdown menu", "blue button"); one call per unique phrase, in parallel. The detection that lands on Spark's pick is the match: `sam+spark` means both models agree. If SAM has nothing there, Spark's accessibility pick is used (`a11y_pick`).
4. **Patch.** New locators are prepended (old ones kept as fallbacks), the anchor is updated, controls that changed kind get a new action, split dates get `parts`, interruptions become workflow `interrupts`.
5. **Verify** by running the failing step (or only its check, when the action already happened and the page in between was the interruption).
6. **Version.** Saved as the next immutable version with a diff in `data/workflows/diffs/`. Every later row uses it, with zero model calls.

Two attempts per heal. Everything is logged per run: `heals.jsonl` (failure, what changed, path, latency, cost) and `heals/<id>_before.png`, `_overlay.png` (SAM masks and labels drawn on the screenshot), `_triage.json`.

**What we learned about SAM on web UIs.** SAM segments visual concepts, not meanings: "input box" returns all seven text fields on the form, "dropdown menu" all four dropdowns, "checkbox" the checkbox, but "registration number text field" returns nothing, because SAM doesn't read labels. So Spark decides *which* element (meaning), and SAM confirms *where* it is and draws its exact mask (geometry). On the redesigned form both agreed on 8 of 9 elements; the small day/month/year dropdowns were not segmented and came from Spark's pick.

Measured on the demo portal (drift levels from the hand-written v1):

| Level | Heals on the first row | Time | Cost | Later rows |
|---|---|---|---|---|
| 1 (renamed ids, moved + relabelled button) | 1 (button) | ~7 s | ~$0.01 | 0 model calls |
| 2 (+ reworded labels, split date, radios → dropdown) | 1 page heal, 9 steps | ~10 s | ~$0.02 | 0 model calls |
| 3 (+ consent modal, session-notice page) | 3 (modal, page, notice) | ~25 s | ~$0.035 | 0 model calls, ~1.5 s/row |

Heals only go forward: a patched step keeps its old locators as fallbacks, but a step whose control changed kind is fixed for the new site.

## Dashboard

Everything in the demo happens in the browser at `http://localhost:8000/app/`:

1. **Teach** (`/app/teach/new`) and **Compile** (`/app/teach/<rec_id>`), as above. A compiled recording gets a **▶ Run 50 rows** button.
2. **Run** from the home page: pick any workflow (compiled, healed or a sample), the number of rows and whether to heal. Rows come from `data/rows.csv`, generated with fake data if missing. One run at a time.
3. **Portal redesign 0-3** in the header switches the demo portal's drift level live (`POST /portal/admin/drift`), also in the middle of a run.

The run page (`/app/runs/<run_id>`) follows the run live:

- **Cost meter:** this run's spend and model calls (only heals call models) next to what the measured computer-use agent would have spent on the same rows, and both at 10,000 rows a day. The agent numbers are the mean over every row in `data/baseline_summary.json` (or the committed copy in `examples/` when you haven't run the baseline yourself).
- **Row grid:** running, healing (amber), done, healed (done with an amber ring) or failed.
- **Latest screen:** the last screenshot the runner took (every step of the first row, then each row's last step and every failure).
- **Events:** row results, failures and heals, newest first.
- **Heal cards:** what broke, what the healer did, the screenshot it saw and the SAM 3.1 overlay, the time, cost and model calls, and the workflow diff (each patched step's action and first locator before and after, plus new interrupts).

The page reads `GET /app/api/runs/<run_id>/events`, a server-sent event stream that tails the run's `events.jsonl`: each event's id is its line number, so a reconnecting browser resumes where it left off, and opening a finished run replays it. The stream ends with `run_done` (or `run_failed`).

Measured in the browser: the hand-written v1, 50 rows, level 3 pressed after row 10 → 50/50 rows OK, 3 heals (v1 → v4), $0.046 and 11 model calls in total, 131 s. The agent would have needed ~$15 and ~1,350 model calls for the same 50 rows.

## Computer-use baseline

What Teach-Once is compared with: a pure computer-use agent doing the same task. `uv run baseline.py data/rows.csv [--rows 5] [--levels 0 3] [--effort low] [--headed]` (the portal must be running).

- Muse Spark (reasoning effort low, computer tool) gets the task, the row's values and a screenshot. It answers with actions; `baseline.py` executes them with Playwright at 1280×800 and sends back a new screenshot, until the receipt is shown. Same portal, same CSV rows, a fresh browser per row.
- A row is OK only if the receipt page shows the row's values. Limits per row: 40 model calls and $0.50. An agent that stops early is told to continue (at most twice).
- Because the API rejects the 30th request of a computer-use chain, a new chain starts after 25 requests with the task and the current screenshot.
- Output: `data/baseline/<run_id>/level<N>/` (a JSON transcript per row with every turn's actions, text and usage, a screenshot per turn, `results.jsonl`) and `data/baseline_summary.json`: per drift level, success rate, means per row, and extrapolations to 50 rows and 10,000 rows a day, next to Teach-Once's measured numbers.

Measured (5 rows per level, Spark effort low):

| | Agent, level 0 | Agent, level 3 | Teach-Once |
|---|---|---|---|
| Rows OK | 4/5 | 3/5 | 50/50 at every level |
| Model calls per row | 26.4 | 27.8 | 0 |
| Input tokens per row | 470k (61% cached) | 499k (60% cached) | 0 |
| Cost per row | $0.29 | $0.31 | $0 (compile once ~$0.30, ~$0.04 per redesign) |
| Time per row | 6.2 min | 7.5 min | 1.1 s (level 0), 1.5 s (level 3) |
| 10,000 rows a day | ~$2,900, 264k calls, ~1,035 h | ~$3,100, 278k calls, ~1,250 h | ~$0.30–0.34 once, 3–4 h |

The agent is not bothered by the redesign itself (it never used ids), but every row costs the same and it is unreliable. From the transcripts:

- **Native dropdowns.** A `<select>`'s option list is drawn by the browser, not the page, so it never appears in a screenshot. The agent clicks a dropdown, sees nothing, and tries letters, arrow keys and Enter; one row spent 20 calls on the two state dropdowns.
- **Reading pixels.** "Neel Iyer" in a sans-serif font reads as "Neel lyer". The agent spent 14 calls "fixing" a correct name and ran out of calls. Teach-Once's checks read the field's value.
- **Small targets.** It clicked 25–35 px below the consent modal's button and below the declaration checkbox, then fell back to Tab-navigating whole pages.
- **Variance.** The same row took 18 calls in one run and failed after 40 in the next.

## Record/replay cache

`META_CACHE` in `.env`:

- `off` (default): always call the API.
- `record`: reuse a saved response if one exists for the exact same request, otherwise call and save it to `data/cassettes/`.
- `replay`: only saved responses; a missing one is an error. Nothing is spent.

## Tests

The portal, runner and studio tests drive a real Chromium (the studio test uses Chromium's fake camera/mic/tab-capture flags). On a fresh machine run `uv run playwright install chromium` once. In an environment with its own Chromium, set `CHROMIUM_PATH` in `.env`.

`uv run pytest` runs offline. Tests that hit the real API are marked `live` and skipped by default (`uv run pytest -m live` to run them).
