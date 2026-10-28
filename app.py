import json
import re
import threading

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import portal
import recording
import teach
import workflow

REC_ID = re.compile(r"rec_\d{8}_\d{6}")
MEDIA_FILES = {"teach.mp4", "narration.wav"}
WORKFLOW_FILE = re.compile(r"[\w.-]+\.(json|py)")
JOBS: dict[str, dict] = {}

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
    return templates.TemplateResponse(request, "app/home.html", {"recordings": recording.list_all()})


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
