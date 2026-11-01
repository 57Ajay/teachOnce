"""Teach pipeline: recording -> transcript -> step graph (Spark) -> workflow (Wonder) -> dry run.

Usage: uv run teach.py <rec_id> [--csv data/rows.csv] [--fresh]
"""
import argparse
import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

import compiler
import config
import cost
import meta_client
import recording
import run
import understand
import workflow
from recording import strip_required

MAX_KEYWORD_LEN = 30  # Voice Transcribe rejects longer keywords
DRY_RUN_CSV_ROWS = 2


def on_portal(url: str) -> bool:
    """The demo portal (studio recordings have a relative start URL, workflows use {{PORTAL_URL}})."""
    return not urlsplit(url).netloc or url.startswith(config.PORTAL_URL)


def password_env(url: str) -> str:
    """Where a password typed while teaching comes from at run time: PORTAL_PASSWORD, or one per site
    (https://opensource-demo.orangehrmlive.com -> ORANGEHRMLIVE_PASSWORD, http://localhost:3000 -> LOCALHOST_3000_PASSWORD)."""
    if on_portal(url):
        return "PORTAL_PASSWORD"
    u = urlsplit(url)
    labels = u.hostname.split(".")
    if len(labels) > 1 and labels[-1].isalpha():
        name = labels[-2]
    else:  # localhost or an IP address: several sites can share it, so the port is part of the name
        name = "_".join(labels + ([str(u.port)] if u.port else []))
    return re.sub(r"\W", "_", name).upper() + "_PASSWORD"


def workflow_start_url(meta: dict, start_page: str) -> str:
    if on_portal(meta["start_url"]):
        return "{{PORTAL_URL}}" + start_page
    u = urlsplit(meta["start_url"])
    return f"{u.scheme}://{u.netloc}{start_page}"


def rows_csv(meta: dict) -> Path:
    """The CSV a recording's workflow runs on: the one named when teaching on a real site, else the portal rows."""
    return config.ROOT / meta["csv"] if meta.get("csv") else config.DATA_DIR / "rows.csv"


def final_pass(events: list[dict]) -> list[dict]:
    """Drop failed submit attempts: a click that lands back on the same page is a validation retry.

    A field re-entered after a failed attempt updates the original step, so the result reads as one clean pass.
    """
    out, page_url = [], None
    for e in events:
        if e["type"] == "navigation":
            if e["url"] == page_url and out and out[-1]["type"] == "click":
                out.pop()
                continue
            page_url = e["url"]
            out.append(e)
            continue
        earlier = next((o for o in out if e["type"] == "change" and o["type"] == "change" and o["url"] == e["url"]
                        and o["target"]["css"] == e["target"]["css"]), None)
        if earlier:
            earlier.update(value=e["value"], checked=e.get("checked"), corrected=True)
            continue
        out.append(dict(e))
    return [dict(e, idx=i) for i, e in enumerate(out)]


def transcribe(rec: dict) -> list[dict]:
    path = rec["dir"] / "transcript.json"
    if not path.exists():
        if not rec["meta"].get("has_narration"):
            return []
        names = {strip_required((e.get("target") or {}).get(k)) for e in rec["events"] for k in ("accessible_name", "label_text")}
        keywords = sorted(n for n in names if n and len(n) <= MAX_KEYWORD_LEN)
        resp = meta_client.transcribe(rec["dir"] / "narration.wav", keywords=keywords, purpose="teach")
        path.write_text(json.dumps(resp, indent=2))
    turns = json.loads(path.read_text()).get("turns", [])
    return [t for t in turns if t.get("transcript", "").strip()]


def event_table(events: list[dict]) -> str:
    lines = []
    for e in events:
        t = e.get("target") or {}
        line = f"#{e['idx']} t={e['ts_ms'] / 1000:.1f}s {e['action']}"
        if e["type"] == "navigation":
            line += f" page={e['url']}"
        else:
            name, label = strip_required(t.get("accessible_name")), strip_required(t.get("label_text"))
            line += f' {t.get("role") or t.get("tag")} name="{name}"' + (f' label="{label}"' if label and label != name else "")
            if e["type"] == "change":
                line += f' value="{e.get("value")}"'
            line += f" url={e['url']}"
        lines.append(line)
    return "\n".join(lines)


def dry_run(wf: workflow.Workflow, rec_dir, attempt: int, csv_rows: list[dict], portal: bool) -> str | None:
    """Run the draft (on the portal: at drift 0) on the first CSV rows. Returns an error or None.

    CSV rows catch a workflow that only fits the recorded example (e.g. an over-specific regex). The example itself is
    only used without a CSV: teaching already did it once, and a task that changes data (add, remove) can't be repeated.
    """
    draft = rec_dir / f"draft{attempt}.json"
    draft.write_text(wf.model_dump_json(indent=2, exclude_defaults=True))
    rows = [{v.column: row[v.column] for v in wf.variables} for row in csv_rows] or [{v.column: v.example for v in wf.variables}]
    examples = rec_dir / "examples.csv"
    with examples.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[v.column for v in wf.variables])
        writer.writeheader()
        writer.writerows(rows)
    if portal:
        httpx.post(f"{config.PORTAL_URL}/portal/admin/drift", json={"level": 0}).raise_for_status()
    run_id = f"dryrun_{rec_dir.name}_{attempt}"
    summary = run.run(draft, examples, run_id=run_id, heal=False)  # test the workflow as compiled, never pay for heals
    if summary["failed"] == 0:
        return None
    results = [json.loads(line) for line in (config.RUNS_DIR / run_id / "results.jsonl").read_text().splitlines()]
    failed = next(r for r in results if r["error"])
    e = failed["error"]
    values = ", ".join(rows[failed["row_idx"]].values())
    return f"Dry run row {failed['row_idx']} ({values}) failed at step {e['step_id']} ({e['kind']}): {e['message']}"


def step_graph(rec_dir, events: list[dict], turns: list[dict]) -> dict:
    """Spark's step graph, reused while the event table it was made from is unchanged (a recorder fix can change it)."""
    path, table = rec_dir / "step_graph.json", event_table(events)
    cached = json.loads(path.read_text()) if path.exists() else {}
    if cached.pop("event_table", None) == table:
        return cached
    graph = understand.understand(rec_dir / "teach.mp4", table, turns)
    path.write_text(json.dumps({**graph, "event_table": table}, indent=2))
    return graph


def compile_recording(rec_id: str, csv_path=None, on_stage=print):
    rec = recording.load(rec_id)
    d, meta = rec["dir"], rec["meta"]
    with open(csv_path or rows_csv(meta), newline="") as f:
        reader = csv.DictReader(f)
        columns, all_rows = reader.fieldnames, list(reader)
    csv_rows = all_rows[:DRY_RUN_CSV_ROWS]
    csv_values = {c: {row[c] for row in all_rows} for c in columns}
    portal = on_portal(meta["start_url"])
    if portal:
        httpx.get(f"{config.PORTAL_URL}/portal/admin/drift").raise_for_status()  # dry run needs the portal
    events = final_pass(rec["events"])
    site = {"start_url": workflow_start_url(meta, events[0]["url"]), "password_env": password_env(meta["start_url"])}
    if any(e.get("value") == "***" for e in events) and not (os.getenv(site["password_env"])
                                                              or getattr(config, site["password_env"], None)):
        raise RuntimeError(f"Set {site['password_env']} in .env: the dry run needs the password typed while teaching")
    spent_before, started = cost.spent_usd(), time.monotonic()

    on_stage("transcribe")
    turns = transcribe(rec)
    on_stage("understand")
    graph = step_graph(d, events, turns)
    on_stage("compile")
    wf, raw = compiler.compile_workflow(events, graph, columns, rec_id, site, csv_values=csv_values)
    on_stage("dry_run")
    error = dry_run(wf, d, 1, csv_rows, portal)
    if error:
        on_stage(f"repair: {error}")
        wf, raw = compiler.compile_workflow(events, graph, columns, rec_id, site, feedback=error, previous=raw,
                                            csv_values=csv_values)
        error = dry_run(wf, d, 2, csv_rows, portal)
    if error:
        raise RuntimeError(error)

    wf.version = workflow.next_version(wf.id)
    path = workflow.save(wf)
    on_stage("export")
    export = compiler.export_script(wf, workflow.WORKFLOWS_DIR / f"export_{wf.id}.py")
    summary = {"workflow": path.name, "export": export.name, "seconds": round(time.monotonic() - started),
               "cost_usd": round(cost.spent_usd() - spent_before, 4)}
    (d / "compiled.json").write_text(json.dumps(summary, indent=2))
    on_stage(f"saved {path.name} and {export.name} in {summary['seconds']}s, ${summary['cost_usd']:.3f}")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("rec_id")
    ap.add_argument("--csv", help="default: the CSV named when teaching, else data/rows.csv")
    ap.add_argument("--fresh", action="store_true", help="redo Spark understanding even if cached")
    args = ap.parse_args()
    if args.fresh:
        (recording.REC_DIR / args.rec_id / "step_graph.json").unlink(missing_ok=True)
    compile_recording(args.rec_id, args.csv)
