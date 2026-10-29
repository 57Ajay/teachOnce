"""Run a workflow over CSV rows. No model calls on the happy path; heals when the site has changed.

Usage: uv run run.py examples/pay-interstate-tax.v1.json data/rows.csv [--start 0] [--limit N] [--headed] [--no-heal]
"""
import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

import config
import cost
import locate
import meta_client
import workflow
from workflow import Interrupt, Step, Workflow

VIEWPORT = {"width": 1280, "height": 800}
READ_VALUE_JS = "e => e.tagName === 'SELECT' ? (e.options[e.selectedIndex]?.text ?? '') : e.value"
POLL_MS = 150


class StepFailed(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class RowContext:
    page: Page
    values: dict
    hidden: set
    interrupts: list[Interrupt]
    outputs: dict = field(default_factory=dict)


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


def clear_interrupts(ctx: RowContext) -> bool:
    """Click away any known interruption that is showing right now. No waiting."""
    for interrupt in ctx.interrupts:
        for loc in interrupt.target.locators:
            candidate = locate.to_playwright(ctx.page, loc, ctx.values)
            if locate.usable(candidate):
                candidate.click()
                ctx.page.wait_for_load_state()
                return True
    return False


def screenshot(page: Page, **kw) -> bytes | None:
    """Headless Chromium sometimes can't capture a page that is still settling; retry briefly, then give up."""
    for _ in range(3):
        try:
            page.wait_for_load_state()
            return page.screenshot(**kw)
        except PlaywrightError:
            page.wait_for_timeout(250)
    return None


def shapes(step: Step) -> list[Step]:
    """The step as last healed, then the shapes it had before (variants)."""
    return [step] + [step.model_copy(update=dict(v)) for v in step.variants]


def resolves_now(ctx: RowContext, step: Step) -> bool:
    targets = [p.target for p in step.parts] or ([step.target] if step.target else [])
    return bool(targets) and all(locate.resolve(ctx.page, t, ctx.values, 0) for t in targets)


def current_shape(ctx: RowContext, step: Step) -> Step | None:
    """The shape of the step whose controls are on the page now, or None if none shows up in time."""
    deadline = time.monotonic() + step.timeout_ms / 1000
    while True:
        for shape in shapes(step):
            if resolves_now(ctx, shape):
                return shape
        if time.monotonic() > deadline:
            return None
        ctx.page.wait_for_timeout(POLL_MS)


def date_parts(iso: str) -> dict:
    y, m, d = iso.split("-")
    return {"year": y, "month": m, "day": d}


def verify(ctx: RowContext, step: Step, el, value: str | None):
    c, page = step.check, ctx.page
    expected = workflow.render(c.value, ctx.values) if c.value else None
    try:
        match c.kind:
            case "value_equals" if step.parts:
                parts = {p.unit: locate.resolve(page, p.target, ctx.values, 0).evaluate("e => e.value") for p in step.parts}
                actual = f"{parts['year']}-{parts['month']}-{parts['day']}"
                if actual != value:
                    raise StepFailed("check_failed", f"date is {actual!r}, expected {value!r}")
            case "value_equals":
                actual = el.evaluate(READ_VALUE_JS).strip()
                if actual != value:
                    raise StepFailed("check_failed", "value does not match the secret" if value in ctx.hidden
                                     else f"value is {actual!r}, expected {value!r}")
            case "url_contains":
                deadline = time.monotonic() + step.timeout_ms / 1000
                while expected not in page.url:
                    if not clear_interrupts(ctx) and time.monotonic() > deadline:
                        raise StepFailed("check_failed", f"page is {page.url}, expected {expected}")
                    page.wait_for_timeout(POLL_MS)
            case "text_visible":
                expect(page.get_by_text(expected).first).to_be_visible(timeout=step.timeout_ms)
            case "element_visible":
                if locate.resolve(page, c.target, ctx.values, step.timeout_ms) is None:
                    raise StepFailed("check_failed", f"not visible: {c.target.description}")
            case "element_hidden":
                for loc in c.target.locators:
                    expect(locate.to_playwright(page, loc, ctx.values).first).to_be_hidden(timeout=step.timeout_ms)
    except AssertionError as e:
        raise StepFailed("check_failed", str(e).splitlines()[0]) from e


def execute(ctx: RowContext, step: Step):
    page, t = ctx.page, step.timeout_ms
    clear_interrupts(ctx)
    if step.variants:
        step = current_shape(ctx, step)
        if step is None:
            raise StepFailed("locator_not_found", "no shape of this step matches the page")
    value = workflow.render(step.value, ctx.values) if step.value is not None else None
    el = None
    targets = [p.target for p in step.parts] if step.parts else [step.target] if step.target else []
    found = [locate.resolve(page, target, ctx.values, t) for target in targets]
    if None in found:
        target = targets[found.index(None)]
        raise StepFailed("locator_not_found", f"no locator matched: {target.description or step.intent}")
    if found:
        el = found[0]
    try:
        match step.action:
            case "goto":
                page.goto(value)
            case "click":
                el.click(timeout=t)
            case "fill_date" if step.parts:
                for part, part_el in zip(step.parts, found):
                    part_el.select_option(date_parts(value)[part.unit], timeout=t)
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
                ctx.outputs[step.output] = text
            case "assert_text":
                expect(page.get_by_text(value).first).to_be_visible(timeout=t)
    except AssertionError as e:
        raise StepFailed("check_failed", str(e).splitlines()[0]) from e
    except PlaywrightError as e:
        kind = "blocked_by_overlay" if "intercepts pointer events" in str(e) else "action_failed"
        raise StepFailed(kind, str(e).splitlines()[0]) from e
    verify(ctx, step, el, value)


def run_row(browser, wf: Workflow, row_idx: int, row: dict, run_dir: Path, emit, shoot_all: bool,
            healer=None) -> tuple[dict, Workflow]:
    values = row_values(wf, row)
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    ctx = RowContext(context.new_page(), values, {values[s.name] for s in wf.secrets}, wf.interrupts)
    start, calls_before, usd_before = time.monotonic(), meta_client.stats["calls"], cost.spent_usd()
    status, error, heals = "ok", None, 0
    emit("row_start", row=row_idx, workflow=f"{wf.id}.v{wf.version}")

    def shoot(step_id):
        rel = f"steps/{row_idx:03d}_{step_id}.png"
        return rel if screenshot(ctx.page, path=run_dir / rel) else None

    i = 0
    while i < len(wf.steps):
        step = wf.steps[i]
        try:
            execute(ctx, step)
        except StepFailed as e:
            if step.optional:
                emit("step_skipped", row=row_idx, step=step.id)
                i += 1
                continue
            emit("step_fail", row=row_idx, step=step.id, kind=e.kind, message=str(e), screenshot=shoot(step.id))
            healed = healer(ctx, wf, i, e, row_idx) if healer else None
            if healed is None:
                status, error = "failed", {"step_id": step.id, "kind": e.kind, "message": str(e)}
                break
            wf, heals = healed, heals + 1
            ctx.interrupts = wf.interrupts
        last = i == len(wf.steps) - 1
        emit("step_ok", row=row_idx, step=step.id, screenshot=shoot(step.id) if shoot_all or last else None)
        i += 1
    context.close()

    result = {
        "row_idx": row_idx,
        "status": status,
        "outputs": ctx.outputs,
        "error": error,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "heals_used": heals,
        "model_calls": meta_client.stats["calls"] - calls_before,
        "cost_usd": round(cost.spent_usd() - usd_before, 6),
        "workflow": f"{wf.id}.v{wf.version}",
    }
    emit("row_done", **result)
    return result, wf


def run(workflow_path, csv_path, start_row: int = 0, limit: int | None = None, headless: bool = True,
        run_id: str | None = None, on_event=None, heal: bool = True) -> dict:
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

    healer = None
    if heal:
        import heal as healing

        healer = healing.Healer(run_dir, emit)

    started, start_version = time.monotonic(), wf.version
    emit("run_start", run_id=run_id, workflow=f"{wf.id}.v{wf.version}", rows=len(rows), start_row=start_row, heal=heal)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=config.CHROMIUM_PATH)
        for row_idx, row in enumerate(rows, start=start_row):
            result, wf = run_row(browser, wf, row_idx, row, run_dir, emit, row_idx == start_row, healer)
            results.append(result)
            with (run_dir / "results.jsonl").open("a") as f:
                f.write(json.dumps(result) + "\n")
        browser.close()

    summary = {
        "run_id": run_id,
        "workflow": f"{wf.id}.v{start_version}" + (f" -> v{wf.version}" if wf.version != start_version else ""),
        "rows": len(results),
        "ok": sum(r["status"] == "ok" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "heals": sum(r["heals_used"] for r in results),
        "model_calls": sum(r["model_calls"] for r in results),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 6),
        "duration_s": round(time.monotonic() - started, 1),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    emit("run_done", **summary)
    return summary


def print_event(event):
    if event["type"] == "row_done":
        line = f"row {event['row_idx']:>3}  {event['status']:<6} {event['duration_ms'] / 1000:5.1f}s  {event['workflow']}"
        if event["heals_used"]:
            line += f"  healed x{event['heals_used']} (${event['cost_usd']:.3f}, {event['model_calls']} calls)"
        if event["error"]:
            e = event["error"]
            line += f"  at {e['step_id']} {e['kind']}: {e['message'][:90]}"
        else:
            line += f"  {event['outputs']}"
        print(line, flush=True)
    elif event["type"] in ("heal_start", "heal_done", "heal_failed"):
        print(f"      {event['type']}: {event.get('summary', '')}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("csv")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-heal", action="store_true")
    args = ap.parse_args()
    summary = run(args.workflow, args.csv, args.start, args.limit, headless=not args.headed,
                  on_event=print_event, heal=not args.no_heal)
    print(json.dumps(summary, indent=2))
