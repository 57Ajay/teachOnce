"""The comparison: a pure computer-use agent (Muse Spark) doing the same task, looking at a screenshot before every action.

Usage: uv run baseline.py data/rows.csv [--rows 5] [--levels 0 3] [--effort low] [--headed]
The portal must be running. Writes data/baseline/<run_id>/ and data/baseline_summary.json.
"""
import argparse
import base64
import csv
import json
import re
import time
from datetime import datetime

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

import config
import cost
import meta_client
import prompts

VIEWPORT = {"width": 1280, "height": 800}
MAX_TURNS = 40
MAX_ROW_USD = 0.50
MAX_NUDGES = 2
CHAIN_TURNS = 25  # the API rejects the 30th request of a computer-use chain (400 invalid parameters)
SCROLL_PX = 100  # Spark scrolls in wheel notches (scroll_y: 5), not pixels
TOOLS = [{"type": "computer"}]
SUMMARY_PATH = config.DATA_DIR / "baseline_summary.json"
RECEIPT_NO = re.compile(r"DTP-\d{4}-\d{6}")
NUDGE = ("The task is not finished: the payment receipt is not shown yet. Continue until it is. "
         "You are authorized to submit and pay without asking.")
RESUME = ("\n\nYou already started this task in an earlier session; the screenshot shows where it is now. "
          "Check what is already done and continue from there.")

# Measured with the runner and healer on this portal (DOCS.md: teach pipeline, self-healing).
TEACH_ONCE = {"compile_usd": 0.30, "heal_usd_per_redesign": 0.04, "seconds_per_row": {0: 1.1, 1: 1.1, 2: 1.1, 3: 1.5}}

KEYS = {"ENTER": "Enter", "RETURN": "Enter", "TAB": "Tab", "ESC": "Escape", "ESCAPE": "Escape", "SPACE": "Space",
        "BACKSPACE": "Backspace", "DELETE": "Delete", "CTRL": "Control", "CONTROL": "Control", "ALT": "Alt",
        "OPTION": "Alt", "SHIFT": "Shift", "CMD": "Meta", "META": "Meta", "SUPER": "Meta", "UP": "ArrowUp",
        "DOWN": "ArrowDown", "LEFT": "ArrowLeft", "RIGHT": "ArrowRight", "ARROWUP": "ArrowUp",
        "ARROWDOWN": "ArrowDown", "ARROWLEFT": "ArrowLeft", "ARROWRIGHT": "ArrowRight", "PAGEUP": "PageUp",
        "PAGEDOWN": "PageDown", "HOME": "Home", "END": "End"}
MODIFIERS = {"Control", "Alt", "Shift", "Meta"}


def key_name(key: str) -> str:
    return KEYS.get(key.upper().replace("_", ""), key)


def perform(page, action: dict):
    """Execute one computer-use action. Screenshot pixels are CSS pixels (device scale factor 1)."""
    match action["type"]:
        case "click":
            page.mouse.click(action["x"], action["y"], button={"wheel": "middle"}.get(action.get("button"), action.get("button", "left")))
        case "double_click":
            page.mouse.dblclick(action["x"], action["y"])
        case "move":
            page.mouse.move(action["x"], action["y"])
        case "drag":
            first, *rest = action["path"]
            page.mouse.move(first["x"], first["y"])
            page.mouse.down()
            for point in rest:
                page.mouse.move(point["x"], point["y"])
            page.mouse.up()
        case "scroll":
            page.mouse.move(action["x"], action["y"])
            page.mouse.wheel(action.get("scroll_x", 0) * SCROLL_PX, action.get("scroll_y", 0) * SCROLL_PX)
        case "type":
            page.keyboard.type(action["text"])
        case "keypress":
            keys = [key_name(k) for k in action["keys"]]
            if MODIFIERS & set(keys):
                page.keyboard.press("+".join(keys))
            else:
                for key in keys:
                    page.keyboard.press(key)
        case "wait":
            page.wait_for_timeout(action.get("ms", 1000))
        case "screenshot":
            pass
        case other:
            raise ValueError(f"unsupported action {other!r}")


def describe(action: dict) -> str:
    args = {k: v for k, v in action.items() if k != "type"}
    return f"{action['type']}({', '.join(f'{v!r}' for v in args.values())})"


def receipt_matches(text: str, row: dict) -> bool:
    expected = [row["vehicle_no"], row["owner_name"], row["vehicle_type"], f"{row['from_state']} → {row['to_state']}",
                row["entry_date"], row["tax_period"]]
    return all(value in text for value in expected)


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def user_message(text: str, png: bytes) -> dict:
    return {"role": "user", "content": [{"type": "input_text", "text": text},
                                        {"type": "input_image", "image_url": data_url(png)}]}


def task_text(row: dict) -> str:
    values = "\n".join(f"- {column}: {value}" for column, value in row.items())
    return (f"Pay the interstate vehicle tax for one vehicle. Log in with username {config.PORTAL_USER} and password "
            f"{config.PORTAL_PASSWORD}, open Pay Interstate Vehicle Tax, fill in the form with exactly these values, "
            f"accept the declaration, calculate the tax, proceed to payment and pay.\n{values}")


def run_row(browser, row_idx: int, row: dict, out_dir, effort: str) -> dict:
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    page = context.new_page()
    page.goto(f"{config.PORTAL_URL}/portal/login")
    start = time.monotonic()
    totals = {"turns": 0, "actions": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "usd": 0.0}
    transcript, previous, chain, nudges, reason, final_text = [], None, 0, 0, "max_turns", ""
    pending = [user_message(task_text(row), page.screenshot())]

    while totals["turns"] < MAX_TURNS:
        if totals["usd"] >= MAX_ROW_USD:
            reason = "row_budget"
            break
        try:
            resp = meta_client.responses(
                purpose="baseline", timeout=90, model=meta_client.SPARK, tools=TOOLS, input=pending,
                instructions=prompts.BASELINE, metadata={"prompt": prompts.BASELINE_VERSION},
                reasoning={"effort": effort}, max_output_tokens=4000,
                **({"previous_response_id": previous} if previous else {}),
            )
        except meta_client.MetaAPIError as e:
            reason = f"api_error: {str(e)[:200]}"
            break
        previous, usage = resp["id"], resp.get("usage") or {}
        chain += 1
        totals["turns"] += 1
        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["cached_tokens"] += (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        totals["usd"] += cost.usd(meta_client.SPARK, usage)
        text = meta_client.output_text(resp)
        calls = [item for item in resp["output"] if item["type"] == "computer_call"]
        turn = {"turn": totals["turns"], "text": text, "usage": usage, "url": page.url, "actions": [], "errors": []}
        transcript.append(turn)

        if not calls:
            final_text = text
            if "/tax/receipt/" in page.url or nudges >= MAX_NUDGES:
                reason = "done" if "/tax/receipt/" in page.url else "gave_up"
                break
            nudges += 1
            pending = [user_message(NUDGE, page.screenshot())]
            print(f"  row {row_idx} turn {totals['turns']}: no action ({text[:80]!r}), nudged", flush=True)
            continue

        pending = []
        for call in calls:
            for action in call["actions"]:
                totals["actions"] += 1
                turn["actions"].append(action)
                try:
                    perform(page, action)
                except (PlaywrightError, ValueError, KeyError) as e:
                    turn["errors"].append(f"{describe(action)}: {str(e).splitlines()[0]}")
            page.wait_for_timeout(400)
            page.wait_for_load_state()
            shot = page.screenshot(path=out_dir / f"{row_idx:03d}_{totals['turns']:02d}.png")
            pending.append({"type": "computer_call_output", "call_id": call["call_id"],
                            "acknowledged_safety_checks": call.get("pending_safety_checks", []),
                            "output": {"type": "computer_screenshot", "image_url": data_url(shot)}})
        print(f"  row {row_idx} turn {totals['turns']}: {', '.join(describe(a) for a in turn['actions'])[:150]}"
              f"  ${totals['usd']:.4f}", flush=True)
        if chain >= CHAIN_TURNS:
            previous, chain = None, 0
            pending = [user_message(task_text(row) + RESUME, page.screenshot())]
            turn["new_chain"] = True

    receipt_text = page.inner_text("body") if "/tax/receipt/" in page.url else ""
    receipt = RECEIPT_NO.search(receipt_text)
    reported = RECEIPT_NO.search(final_text)
    context.close()
    status = "failed"
    if receipt:
        status = "ok" if receipt_matches(receipt_text, row) else "wrong_data"
    result = {
        "row_idx": row_idx, "status": status, "reason": reason,
        "receipt_no": receipt.group(0) if receipt else None, "reported_receipt_no": reported.group(0) if reported else None,
        **totals, "usd": round(totals["usd"], 6), "seconds": round(time.monotonic() - start, 1), "final_text": final_text,
    }
    (out_dir / f"{row_idx:03d}.json").write_text(json.dumps({**result, "transcript": transcript}, indent=1))
    return result


def scale(per_row: dict, rows: int, one_time_usd: float = 0.0) -> dict:
    return {"rows": rows, "usd": round(one_time_usd + per_row["usd"] * rows, 2),
            "model_calls": round(per_row["turns"] * rows), "hours": round(per_row["seconds"] * rows / 3600, 2)}


def level_summary(results: list[dict], level: int) -> dict:
    """Baseline means per row next to Teach-Once's measured numbers, both extrapolated to 50 rows and 10,000/day."""
    n = len(results)
    ok = sum(r["status"] == "ok" for r in results)
    mean = {k: round(sum(r[k] for r in results) / n, 4)
            for k in ("turns", "actions", "input_tokens", "cached_tokens", "output_tokens", "usd", "seconds")}
    total = sum(r["usd"] for r in results)
    one_time = TEACH_ONCE["compile_usd"] + (TEACH_ONCE["heal_usd_per_redesign"] if level else 0)
    teach_row = {"turns": 0, "usd": 0.0, "seconds": TEACH_ONCE["seconds_per_row"][level]}
    return {
        "baseline": {
            "rows": n, "ok": ok, "success_rate": round(ok / n, 3), "total_usd": round(total, 4),
            "usd_per_successful_row": round(total / ok, 4) if ok else None, "mean_per_row": mean,
            "extrapolated": {"rows_50": scale(mean, 50), "per_day_10k": scale(mean, 10_000)},
        },
        "teach_once": {
            "one_time_usd": round(one_time, 2), "usd_per_row": 0.0, "model_calls_per_row": 0,
            "seconds_per_row": teach_row["seconds"],
            "extrapolated": {"rows_50": scale(teach_row, 50, one_time), "per_day_10k": scale(teach_row, 10_000, one_time)},
        },
    }


def set_drift(level: int):
    httpx.post(f"{config.PORTAL_URL}/portal/admin/drift", json={"level": level}).raise_for_status()


def run(csv_path, rows: int = 5, levels=(0, 3), effort: str = "low", headless: bool = True) -> dict:
    with open(csv_path, newline="") as f:
        data = list(csv.DictReader(f))[:rows]
    run_id = datetime.now().strftime("baseline_%Y%m%d_%H%M%S")
    summary = json.loads(SUMMARY_PATH.read_text()) if SUMMARY_PATH.exists() else {}
    summary.update(model=meta_client.SPARK, effort=effort, max_turns=MAX_TURNS, prompt=prompts.BASELINE_VERSION)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=config.CHROMIUM_PATH)
        try:
            for level in levels:
                set_drift(level)
                out_dir = config.DATA_DIR / "baseline" / run_id / f"level{level}"
                out_dir.mkdir(parents=True, exist_ok=True)
                results = []
                for row_idx, row in enumerate(data):
                    result = run_row(browser, row_idx, row, out_dir, effort)
                    results.append(result)
                    print(f"level {level} row {row_idx}: {result['status']} ({result['reason']}) {result['turns']} turns, "
                          f"{result['actions']} actions, {result['input_tokens']} in / {result['output_tokens']} out, "
                          f"${result['usd']:.4f}, {result['seconds']}s, receipt {result['receipt_no']}", flush=True)
                (out_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
                summary.setdefault("levels", {})[str(level)] = {"run_id": run_id, **level_summary(results, level)}
                summary["updated_at"] = datetime.now().isoformat(timespec="seconds")
                SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
        finally:
            browser.close()
            set_drift(0)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--levels", type=int, nargs="+", default=[0, 3])
    ap.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    summary = run(args.csv, args.rows, args.levels, args.effort, headless=not args.headed)
    print(json.dumps(summary, indent=2))
    print(cost.summary())
