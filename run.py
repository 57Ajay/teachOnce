"""Run a workflow over CSV rows. No model calls on the happy path.

Usage: uv run run.py workflows/pay-interstate-tax.v1.json data/rows.csv [--start 0] [--limit N] [--headed]
"""
import argparse
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

import config
import cost
import locate
import meta_client
import workflow
from workflow import Step, Workflow

VIEWPORT = {"width": 1280, "height": 800}
READ_VALUE_JS = "e => e.tagName === 'SELECT' ? (e.options[e.selectedIndex]?.text ?? '') : e.value"


class StepFailed(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def row_values(wf: Workflow, row: dict) -> dict:
    values = {"PORTAL_URL": config.PORTAL_URL}
    for s in wf.secrets:
        secret = os.getenv(s.env) or getattr(config, s.env, None)
        if secret is None:
            raise KeyError(f"secret {s.name}: env var {s.env} is not set")
        values[s.name] = secret
    for v in wf.variables:
        values[v.name] = row[v.column]
    return values


def verify(page: Page, step: Step, el, value: str | None, values: dict):
    c = step.check
    expected = workflow.render(c.value, values) if c.value else None
    try:
        match c.kind:
            case "value_equals":
                actual = el.evaluate(READ_VALUE_JS).strip()
                if actual != value:
                    raise StepFailed("check_failed", f"value is {actual!r}, expected {value!r}")
            case "url_contains":
                expect(page).to_have_url(re.compile(re.escape(expected)), timeout=step.timeout_ms)
            case "text_visible":
                expect(page.get_by_text(expected).first).to_be_visible(timeout=step.timeout_ms)
            case "element_visible":
                if locate.resolve(page, c.target, values, step.timeout_ms) is None:
                    raise StepFailed("check_failed", f"not visible: {c.target.description}")
            case "element_hidden":
                for loc in c.target.locators:
                    expect(locate.to_playwright(page, loc, values).first).to_be_hidden(timeout=step.timeout_ms)
    except AssertionError as e:
        raise StepFailed("check_failed", str(e).splitlines()[0]) from e


def execute(page: Page, step: Step, values: dict, outputs: dict):
    value = workflow.render(step.value, values) if step.value is not None else None
    el = None
    if step.target:
        el = locate.resolve(page, step.target, values, step.timeout_ms)
        if el is None:
            raise StepFailed("locator_not_found", f"no locator matched: {step.target.description or step.intent}")
    t = step.timeout_ms
    try:
        match step.action:
            case "goto":
                page.goto(value)
            case "click":
                el.click(timeout=t)
            case "fill" | "fill_date":
                el.fill(value, timeout=t)
            case "select":
                el.select_option(label=value, timeout=t)
            case "check":
                el.check(timeout=t)
            case "uncheck":
                el.uncheck(timeout=t)
            case "press":
                el.press(value, timeout=t) if el else page.keyboard.press(value)
            case "extract":
                text = el.inner_text(timeout=t).strip()
                if step.pattern:
                    m = re.search(step.pattern, text)
                    if not m:
                        raise StepFailed("check_failed", f"{step.pattern!r} not found in {text!r}")
                    text = m.group(0)
                outputs[step.output] = text
            case "assert_text":
                expect(page.get_by_text(value).first).to_be_visible(timeout=t)
    except AssertionError as e:
        raise StepFailed("check_failed", str(e).splitlines()[0]) from e
    except PlaywrightError as e:
        kind = "blocked_by_overlay" if "intercepts pointer events" in str(e) else "action_failed"
        raise StepFailed(kind, str(e).splitlines()[0]) from e
    verify(page, step, el, value, values)


def run_row(browser, wf: Workflow, row_idx: int, row: dict, run_dir: Path, emit, shoot_all: bool) -> dict:
    values = row_values(wf, row)
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    page = context.new_page()
    start, calls_before, usd_before = time.monotonic(), meta_client.stats["calls"], cost.spent_usd()
    outputs, status, error = {}, "ok", None
    emit("row_start", row=row_idx)

    def shoot(step_id):
        rel = f"steps/{row_idx:03d}_{step_id}.png"
        page.screenshot(path=run_dir / rel)
        return rel

    for i, step in enumerate(wf.steps):
        try:
            execute(page, step, values, outputs)
        except StepFailed as e:
            if step.optional:
                emit("step_skipped", row=row_idx, step=step.id)
                continue
            status, error = "failed", {"step_id": step.id, "kind": e.kind, "message": str(e)}
            emit("step_fail", row=row_idx, step=step.id, kind=e.kind, message=str(e), screenshot=shoot(step.id))
            break
        last = i == len(wf.steps) - 1
        emit("step_ok", row=row_idx, step=step.id, screenshot=shoot(step.id) if shoot_all or last else None)
    context.close()

    result = {
        "row_idx": row_idx,
        "status": status,
        "outputs": outputs,
        "error": error,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "heals_used": 0,
        "model_calls": meta_client.stats["calls"] - calls_before,
        "cost_usd": round(cost.spent_usd() - usd_before, 6),
    }
    emit("row_done", **result)
    return result


def run(workflow_path, csv_path, start_row: int = 0, limit: int | None = None, headless: bool = True,
        run_id: str | None = None, on_event=None) -> dict:
    wf = workflow.load(workflow_path)
    if not Path(csv_path).exists():
        raise SystemExit(f"{csv_path} not found. Generate fake rows with: uv run gen_data.py")
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    rows = rows[start_row:start_row + limit if limit else None]
    missing = {v.column for v in wf.variables} - set(rows[0] if rows else {})
    if missing:
        raise KeyError(f"CSV is missing columns: {sorted(missing)}")

    run_id = run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = config.RUNS_DIR / run_id
    (run_dir / "steps").mkdir(parents=True, exist_ok=True)

    def emit(event_type, **data):
        event = {"type": event_type, "ts": time.time(), **data}
        with (run_dir / "events.jsonl").open("a") as f:
            f.write(json.dumps(event) + "\n")
        if on_event:
            on_event(event)

    started = time.monotonic()
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=config.CHROMIUM_PATH)
        for row_idx, row in enumerate(rows, start=start_row):
            result = run_row(browser, wf, row_idx, row, run_dir, emit, shoot_all=row_idx == start_row)
            results.append(result)
            with (run_dir / "results.jsonl").open("a") as f:
                f.write(json.dumps(result) + "\n")
        browser.close()

    summary = {
        "run_id": run_id,
        "workflow": f"{wf.id}.v{wf.version}",
        "rows": len(results),
        "ok": sum(r["status"] == "ok" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "model_calls": sum(r["model_calls"] for r in results),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 6),
        "duration_s": round(time.monotonic() - started, 1),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    emit("run_done", **summary)
    return summary


def print_event(event):
    if event["type"] == "row_done":
        line = f"row {event['row_idx']:>3}  {event['status']:<6} {event['duration_ms'] / 1000:5.1f}s"
        if event["error"]:
            e = event["error"]
            line += f"  at {e['step_id']} {e['kind']}: {e['message'][:90]}"
        else:
            line += f"  {event['outputs']}"
        print(line, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("csv")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    summary = run(args.workflow, args.csv, args.start, args.limit, headless=not args.headed, on_event=print_event)
    print(json.dumps(summary, indent=2))
