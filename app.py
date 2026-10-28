from fastapi import FastAPI
from fastapi.responses import RedirectResponse

import portal

app = FastAPI(title="Teach-Once")
app.include_router(portal.router)


@app.get("/")
def home():
    return RedirectResponse("/portal/login")
