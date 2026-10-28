import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

import config

WORKFLOWS_DIR = config.DATA_DIR / "workflows"
TEMPLATE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class Locator(BaseModel):
    kind: Literal["role", "label", "placeholder", "text", "css"]
    role: str | None = None
    name: str | None = None
    text: str | None = None
    selector: str | None = None


class Anchor(BaseModel):
    bbox: list[float]
    viewport: list[int] = [1280, 800]
    crop: str | None = None


class Target(BaseModel):
    description: str = ""
    noun_phrase: str = ""
    locators: list[Locator]
    anchor: Anchor | None = None


class DatePart(BaseModel):
    unit: Literal["day", "month", "year"]
    target: Target


class Interrupt(BaseModel):
    """Something that can get in the way (a consent modal, an interstitial page) and the click that clears it."""
    id: str
    description: str = ""
    target: Target


class Check(BaseModel):
    kind: Literal["none", "value_equals", "url_contains", "text_visible", "element_visible", "element_hidden"] = "none"
    value: str | None = None
    target: Target | None = None


class Step(BaseModel):
    id: str
    intent: str
    action: Literal["goto", "click", "fill", "fill_date", "select", "check", "uncheck", "press",
                    "wait_for", "extract", "assert_text"]
    target: Target | None = None
    value: str | None = None
    output: str | None = None
    pattern: str | None = None
    check: Check = Check()
    parts: list[DatePart] = []
    optional: bool = False
    timeout_ms: int = 5000
    healed: list[dict] = []


class Variable(BaseModel):
    name: str
    column: str
    type: str = "string"
    example: str = ""
    description: str = ""


class Secret(BaseModel):
    name: str
    env: str


class Workflow(BaseModel):
    id: str
    version: int
    name: str
    start_url: str
    source_recording: str | None = None
    variables: list[Variable] = []
    secrets: list[Secret] = []
    steps: list[Step]
    interrupts: list[Interrupt] = []


def render(template: str, values: dict) -> str:
    def sub(m):
        if m.group(1) not in values:
            raise KeyError(f"no value for {{{{{m.group(1)}}}}}")
        return str(values[m.group(1)])

    return TEMPLATE.sub(sub, template)


def load(path: str | Path) -> Workflow:
    return Workflow.model_validate_json(Path(path).read_text())


def path_for(workflow_id: str, version: int) -> Path:
    return WORKFLOWS_DIR / f"{workflow_id}.v{version}.json"


def latest(workflow_id: str) -> Path:
    versions = sorted(WORKFLOWS_DIR.glob(f"{workflow_id}.v*.json"), key=lambda p: int(p.stem.rsplit(".v", 1)[1]))
    if not versions:
        raise FileNotFoundError(f"no workflow {workflow_id} in {WORKFLOWS_DIR}")
    return versions[-1]


def next_version(workflow_id: str) -> int:
    try:
        return int(latest(workflow_id).stem.rsplit(".v", 1)[1]) + 1
    except FileNotFoundError:
        return 1


def save(wf: Workflow) -> Path:
    """Write a new version file. Version files are immutable."""
    path = path_for(wf.id, wf.version)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(wf.model_dump(exclude_defaults=True), indent=2) + "\n")
    return path
