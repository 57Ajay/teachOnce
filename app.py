import asyncio
import csv
import json
import re
import threading
import time
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config
import gen_data
import portal
import recording
import run
import teach
import workflow

REC_ID = re.compile(r"rec_\d{8}_\d{6}")
MEDIA_FILES = {"teach.mp4", "narration.wav"}
WORKFLOW_FILE = re.compile(r"[\w.-]+\.(json|py)")
RUN_ID = re.compile(r"[\w-]+")
RUN_FILE = re.compile(r"[\w.-]+\.png")
END_EVENTS = {"run_done", "run_failed"}
JOBS: dict[str, dict] = {}
RUNS: dict[str, dict] = {}

app = FastAPI(title="Teach-Once")
app.include_router(portal.router)
app.mount("/static", StaticFiles(directory=config.ROOT / "static"), name="static")
templates = Jinja2Templates(directory=config.ROOT / "templates")


def recording_or_404(rec_id: str) -> dict:
    try:
        if not REC_ID.fullmatch(rec_id):
            raise FileNotFoundError(rec_id)
        return recording.load(rec_id)
    except FileNotFoundError:
        raise HTTPException(404, "recording not found")


@app.get("/")
def home():
    return RedirectResponse("/app/")


@app.get("/app/")
def app_home(request: Request):
    return templates.TemplateResponse(request, "app/home.html", {
        "recordings": recording.list_all(), "workflows": workflow_choices(), "runs": list_runs()})


@app.get("/app/teach/new")
def studio(request: Request):
    return templates.TemplateResponse(request, "app/studio.html", {})


@app.post("/app/api/teach")
def upload_teach(meta: str = Form(...), events: UploadFile = File(...), screen: UploadFile = File(...),
                 mic: UploadFile | None = File(None)):
    meta_data = json.loads(meta) | {"drift_level": portal.DRIFT["level"]}
    rec_id = recording.save(meta_data, json.loads(events.file.read()), screen.file.read(),
                            mic.file.read() if mic else None)
    return {"rec_id": rec_id}


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else None


@app.get("/app/teach/{rec_id}")
def view_recording(request: Request, rec_id: str):
    rec = recording_or_404(rec_id)
    d = rec["dir"]
    compiled = read_json(d / "compiled.json")
    transcript = read_json(d / "transcript.json") or {}
    ctx = rec | {
        "turns": [t for t in transcript.get("turns", []) if t.get("transcript", "").strip()],
        "graph": read_json(d / "step_graph.json"),
        "compiled": compiled,
        "workflow": workflow.load(wf_path) if compiled and (wf_path := workflow.WORKFLOWS_DIR / compiled["workflow"]).exists() else None,
        "export_code": ex_path.read_text() if compiled and (ex_path := workflow.WORKFLOWS_DIR / compiled["export"]).exists() else None,
        "job": JOBS.get(rec_id),
        "run_rows": min(50, count_rows(teach.rows_csv(rec["meta"]))),
    }
    return templates.TemplateResponse(request, "app/recording.html", ctx)


@app.post("/app/api/teach/{rec_id}/compile")
def start_compile(rec_id: str):
    recording_or_404(rec_id)
    if JOBS.get(rec_id, {}).get("state") == "running":
        return JOBS[rec_id]
    job = JOBS[rec_id] = {"state": "running", "stages": [], "error": None}

    def work():
        try:
            teach.compile_recording(rec_id, on_stage=job["stages"].append)
            job["state"] = "done"
        except Exception as e:
            job.update(state="failed", error=str(e)[:600])

    threading.Thread(target=work, daemon=True).start()
    return job


@app.get("/app/api/teach/{rec_id}/compile")
def compile_status(rec_id: str):
    return JOBS.get(rec_id) or {"state": "idle", "stages": [], "error": None}


@app.get("/app/workflows/{name}")
def workflow_file(name: str):
    path = workflow.WORKFLOWS_DIR / name
    if not WORKFLOW_FILE.fullmatch(name) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="text/plain")


@app.get("/app/recordings/{rec_id}/{name}")
def recording_media(rec_id: str, name: str):
    path = recording_or_404(rec_id)["dir"] / name
    if name not in MEDIA_FILES or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/app/workflows/diffs/{name}")
def workflow_diff(name: str):
    path = workflow.WORKFLOWS_DIR / "diffs" / name
    if not WORKFLOW_FILE.fullmatch(name) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/json")


def count_rows(path) -> int:
    if not path.exists():
        return 50  # the portal's rows are generated on the first run
    with path.open(newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def rows_csv_for(workflow_file: str):
    """The CSV a workflow runs on: the one named when it was taught on a real site, else the portal's fake rows."""
    rec_id = workflow.load(config.ROOT / workflow_file).source_recording
    try:
        meta = recording.load(rec_id)["meta"] if rec_id and REC_ID.fullmatch(rec_id) else {}
    except FileNotFoundError:
        meta = {}
    return teach.rows_csv(meta)


def run_on_portal(run_id: str) -> bool:
    """The measured agent only ever ran on the portal, so other sites get no comparison."""
    if "portal" in RUNS.get(run_id, {}):
        return RUNS[run_id]["portal"]
    path = config.RUNS_DIR / run_id / "events.jsonl"
    if not path.exists():
        return True
    with path.open() as f:
        first = json.loads(f.readline() or "{}")
    return teach.on_portal(first.get("start_url", "{{PORTAL_URL}}"))


def workflow_choices() -> list[str]:
    """Workflow files that can be run, as paths relative to the repo: newest compiled or healed first, then samples."""
    runtime = sorted(workflow.WORKFLOWS_DIR.glob("*.v*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    samples = sorted((config.ROOT / "examples").glob("*.v*.json"))
    return [str(p.relative_to(config.ROOT)) for p in runtime + samples]


def baseline_reference() -> dict | None:
    """The measured computer-use agent, averaged over every row it ran (all drift levels)."""
    summary = read_json(config.DATA_DIR / "baseline_summary.json") or read_json(config.ROOT / "examples" / "baseline_summary.json")
    if not summary:
        return None
    levels = [level["baseline"] for level in summary["levels"].values()]
    rows = sum(b["rows"] for b in levels)
    mean = {k: round(sum(b["mean_per_row"][k] * b["rows"] for b in levels) / rows, 4)
            for k in ("usd", "turns", "seconds", "input_tokens")}
    return {"model": summary["model"], "rows": rows, "ok": sum(b["ok"] for b in levels), **mean}


def list_runs() -> list[dict]:
    runs = []
    for d in sorted(config.RUNS_DIR.glob("*/"), reverse=True)[:20]:
        summary = read_json(d / "summary.json")
        state = RUNS.get(d.name, {}).get("state") or ("done" if summary else "incomplete")
        runs.append({"run_id": d.name, "state": state, **(summary or {})})
    return runs


def run_dir_or_404(run_id: str):
    path = config.RUNS_DIR / run_id
    if not RUN_ID.fullmatch(run_id) or not (path.exists() or run_id in RUNS):
        raise HTTPException(404, "run not found")
    return path


class RunIn(BaseModel):
    workflow: str
    rows: int = 50
    heal: bool = True


@app.post("/app/api/runs")
def start_run(body: RunIn):
    if body.workflow not in workflow_choices():
        raise HTTPException(404, "workflow not found")
    busy = next((rid for rid, r in RUNS.items() if r["state"] == "running"), None)
    if busy:
        raise HTTPException(409, f"{busy} is still running")
    rows_csv = rows_csv_for(body.workflow)
    if rows_csv == config.DATA_DIR / "rows.csv" and not rows_csv.exists():
        gen_data.write(rows_csv)
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    RUNS[run_id] = {"state": "running", "portal": teach.on_portal(workflow.load(config.ROOT / body.workflow).start_url)}

    def work():
        try:
            run.run(config.ROOT / body.workflow, rows_csv, limit=body.rows, run_id=run_id, heal=body.heal)
            RUNS[run_id]["state"] = "done"
        except (Exception, SystemExit) as e:
            run_dir = config.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            with (run_dir / "events.jsonl").open("a") as f:
                f.write(json.dumps({"type": "run_failed", "ts": time.time(), "error": str(e)[:600]}) + "\n")
            RUNS[run_id]["state"] = "failed"

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run_id}


@app.get("/app/runs/{run_id}")
def view_run(request: Request, run_id: str):
    run_dir_or_404(run_id)
    portal = run_on_portal(run_id)
    return templates.TemplateResponse(request, "app/run.html", {
        "run_id": run_id, "portal": portal, "baseline": baseline_reference() if portal else None})


@app.get("/app/runs/{run_id}/{kind}/{name}")
def run_file(run_id: str, kind: str, name: str):
    path = run_dir_or_404(run_id) / kind / name
    if kind not in ("steps", "heals") or not RUN_FILE.fullmatch(name) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/app/api/runs/{run_id}/events")
async def run_events(request: Request, run_id: str):
    """Server-sent events: the run's events.jsonl from the start (or after Last-Event-ID), then live until the run ends."""
    path = run_dir_or_404(run_id) / "events.jsonl"
    skip = int(request.headers.get("last-event-id", -1)) + 1

    async def stream():
        n, offset, partial = 0, 0, b""
        while not await request.is_disconnected():
            active = RUNS.get(run_id, {}).get("state") == "running"  # read before the file, so nothing written after is missed
            if path.exists():
                with path.open("rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset += len(chunk)
                *lines, partial = (partial + chunk).split(b"\n")
                for line in lines:
                    n += 1
                    if n > skip:
                        yield f"id: {n - 1}\ndata: {line.decode()}\n\n"
                    if json.loads(line)["type"] in END_EVENTS:
                        return
                if lines:
                    continue
            if not active:
                yield 'data: {"type": "stream_end"}\n\n'
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
