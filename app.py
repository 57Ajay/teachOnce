import json
import re

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import portal
import recording

REC_ID = re.compile(r"rec_\d{8}_\d{6}")
MEDIA_FILES = {"teach.mp4", "narration.wav"}

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


@app.get("/app/teach/{rec_id}")
def view_recording(request: Request, rec_id: str):
    return templates.TemplateResponse(request, "app/recording.html", recording_or_404(rec_id))


@app.get("/app/recordings/{rec_id}/{name}")
def recording_media(rec_id: str, name: str):
    path = recording_or_404(rec_id)["dir"] / name
    if name not in MEDIA_FILES or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
