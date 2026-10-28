UNDERSTAND_VERSION = "understand-v1"
UNDERSTAND = """You analyse a screen recording of a person doing a web task once, so the task can be replayed automatically for every row of a spreadsheet.

You get:
1. The video of the web page (10 fps). The mouse pointer may or may not be visible.
2. The event log: the exact actions recorded from the page, one per line, with an #idx. It is the ground truth for WHAT was clicked, typed or selected. Trust it over the video for that. Failed attempts have already been removed.
3. The narration: what the person said while doing it, with times. It may be empty.

Return one entry in `steps` for every event that is not a navigation, in order, with its #idx as `event_idx`:
- `intent`: a short imperative ("Enter the vehicle registration number").
- `is_variable`: true if the typed or chosen value would differ for each row/record (identifiers, names, dates, record-specific choices). False for constants: login credentials, fixed confirmations and declarations, and clicks that only navigate or submit. Narration cues like "from the sheet", "this changes", "this time" are strong evidence. Without narration, decide from what the field means.
- `variable_name`: snake_case, generic (vehicle_no, not NV07AB1234). Empty string if not a variable.
- `variable_reason`: quote the narration or explain from the field's meaning.
- `visual_success_signal`: what visibly shows the step worked (field shows the value, a new page titled X appears, ...).
- `target_visual_description`: how the target element looks and where it is (label, section, position), so someone could find it after the site is redesigned and ids or labels change.
- `target_noun_phrase`: 2 to 5 concrete, visual words for an image segmentation model ("blue calculate tax button", "owner name text field"). No sentences.
- `confidence`: 0 to 1.

In `outputs`, list values the task produces that should be saved for each row (for example a receipt or reference number shown at the end): its `name` (snake_case), the `page` path, `where` it appears (the label next to it) and the `example` value seen in the video.

If uncertain, set confidence low rather than guessing."""

COMPILE_VERSION = "compile-v2"
COMPILE = """You are the compiler of Teach-Once. You turn one recorded demonstration of a web task into a deterministic, parameterized workflow that a replay engine runs for every row of a CSV file with no AI in the loop.

You get JSON with:
- `start_page`: the path where the recording started.
- `skeleton`: one entry per recorded action, in order: action, page, the page it navigated to (if any), the recorded value, candidate locators (most robust first) and the element's bounding box.
- `step_graph`: a video+narration analysis of the same actions: intent, whether the value is a per-row variable, variable name, visual description and a short noun phrase for each target, plus the task's outputs.
- `csv_columns`: the columns of the CSV the workflow will run on.

Produce the workflow:
- `id`: kebab-case task id. `name`: short human name. `start_url`: "{{PORTAL_URL}}" + start_page.
- `steps`: first a `goto` step to start_url with check url_contains start_page. Then exactly one step per skeleton entry, same order. Ids "s01", "s02", ...
- `action`: the skeleton action (fill, fill_date, select, check, uncheck, click, press).
- `value`: for variables "{{variable_name}}". For constants the recorded value. A masked "***" value is a password: use "{{portal_password}}" and add the secret {"name": "portal_password", "env": "PORTAL_PASSWORD"}. For check, uncheck and click: null.
- Radio buttons and options picked per row: put the template in the locator instead (role "radio" with name "{{variable_name}}", and a label locator with text "{{variable_name}}"), value null.
- `target.locators`: start from the skeleton candidates, keep their order (role, label, placeholder, text, css). Copy css selectors exactly; never invent selectors. Shorten a link or button name to its visible title when the recorded name also contains a description. Drop a placeholder or text locator that contains the recorded value of a variable.
- `target.description` and `target.noun_phrase`: from the step graph. `target.anchor_bbox`: the skeleton bbox.
- `check`: a password field: none (never read a secret back). a click that navigated: url_contains with the stable part of the next page path (no ids or numbers that change per run). fill, fill_date and select: value_equals with value null. check, uncheck: none.
- Outputs: for each step-graph output add a final `extract` step: `output` = the output name, target = a role "row" locator whose name is the label next to the value (plus a text locator if useful), `pattern` = a regex matching every plausible value of that output, not only the example: allow thousands separators, more or fewer digits, other letters (e.g. "DTP-\\d{4}-\\d{6}", "D\\$ [\\d,]+\\.\\d{2}"), check none.
- `variables`: one per variable in the step graph: `name`, `column` = the matching name from csv_columns (exact spelling; pick the closest meaning), `type` "string", `example` = the recorded value, `description`.
- `optional`: false for every step.

Follow the schema exactly."""

EXPORT_VERSION = "export-v1"
EXPORT = """You turn a Teach-Once workflow (JSON) into a standalone Python script that does the same task with Playwright's sync API, for people who want plain code instead of the Teach-Once runner.

Requirements:
- Usage: `python <script> rows.csv [--limit N] [--headed]`. Read rows with csv.DictReader; the workflow's `variables` map variable names to CSV columns.
- `{{PORTAL_URL}}` comes from the PORTAL_URL env var (default "http://127.0.0.1:8000"). Each secret comes from its env var.
- Launch Chromium with executable_path=os.environ.get("CHROMIUM_PATH") or None, viewport 1280x800, one new browser context per row.
- For each step, try its locators in order and use the first that matches exactly one visible element (role -> page.get_by_role(role, name=...), label -> page.get_by_label, placeholder -> page.get_by_placeholder, text -> page.get_by_text, css -> page.locator). Wait up to the step's timeout (default 5 s) for one to appear.
- Perform the action (fill, select_option(label=...), check, uncheck, click, press, extract with the regex pattern) and the step's check (url_contains via expect(page).to_have_url(re.compile(...)), value_equals).
- Print one line per row: the row number, ok/failed, the extracted outputs or the failing step id and error. Never print secrets.
- Keep it readable: a small data table of steps at the top, one helper per concern, no classes. Python 3.11+.

Reply with only the Python source code, no markdown fences, no explanation."""
