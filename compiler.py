"""Muse Wonder compiles the recorded skeleton + Spark's step graph into a workflow."""
import json
import py_compile
from pathlib import Path

from pydantic import ValidationError

import meta_client
import prompts

LOCATOR_FIELDS = {"role": ("role", "name"), "label": ("text",), "placeholder": ("text",), "text": ("text",),
                  "css": ("selector",)}


class CompileError(RuntimeError):
    pass
from recording import stable_css, strip_required
from workflow import TEMPLATE, Anchor, Workflow

_NULLABLE = {"type": ["string", "null"]}
_LOCATOR = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "role", "name", "text", "selector"],
    "properties": {"kind": {"type": "string", "enum": ["role", "label", "placeholder", "text", "css"]},
                   "role": _NULLABLE, "name": _NULLABLE, "text": _NULLABLE, "selector": _NULLABLE},
}
_TARGET = {
    "type": "object",
    "additionalProperties": False,
    "required": ["description", "noun_phrase", "locators"],
    "properties": {"description": {"type": "string"}, "noun_phrase": {"type": "string"},
                   "locators": {"type": "array", "items": _LOCATOR}},
}
_STEP = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "intent", "action", "value", "output", "pattern", "optional", "target", "check"],
    "properties": {
        "id": {"type": "string"},
        "intent": {"type": "string"},
        "action": {"type": "string", "enum": ["goto", "click", "fill", "fill_date", "select", "check", "uncheck",
                                              "press", "extract"]},
        "value": _NULLABLE,
        "output": _NULLABLE,
        "pattern": _NULLABLE,
        "optional": {"type": "boolean"},
        "target": {"anyOf": [_TARGET, {"type": "null"}]},
        "check": {"type": "object", "additionalProperties": False, "required": ["kind", "value"],
                  "properties": {"kind": {"type": "string", "enum": ["none", "value_equals", "url_contains",
                                                                     "text_visible"]},
                                 "value": _NULLABLE}},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "name", "start_url", "variables", "secrets", "steps"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "start_url": {"type": "string"},
        "variables": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "column", "type", "example", "description"],
            "properties": {k: {"type": "string"} for k in ["name", "column", "type", "example", "description"]}}},
        "secrets": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "env"],
            "properties": {"name": {"type": "string"}, "env": {"type": "string"}}}},
        "steps": {"type": "array", "items": _STEP},
    },
}


def skeleton(events: list[dict]) -> list[dict]:
    """One entry per recorded action with locator candidates built from what the recorder saw."""
    out = []
    for i, e in enumerate(events):
        if e["type"] == "navigation":
            continue
        t = e["target"]
        name = strip_required(t.get("accessible_name"))
        locators = []
        if t.get("role") and name:
            locators.append({"kind": "role", "role": t["role"], "name": name})
        if t.get("label_text"):
            locators.append({"kind": "label", "text": strip_required(t["label_text"])})
        if t.get("placeholder"):
            locators.append({"kind": "placeholder", "text": t["placeholder"]})
        if stable_css(t.get("css")):
            locators.append({"kind": "css", "selector": t["css"]})
        nxt = events[i + 1] if i + 1 < len(events) else None
        out.append({
            "event_idx": e["idx"],
            "action": e["action"],
            "page": e["url"],
            "navigated_to": nxt["url"] if nxt and nxt["type"] == "navigation" else None,
            "recorded_value": (name if t.get("type") == "radio" else e.get("value")) if e["type"] == "change" else None,
            "element": f"{t.get('tag')}[type={t.get('type')}]" if t.get("type") else t.get("tag"),
            "locators": locators,
            "bbox": t.get("bbox"),
        })
    return out


def to_workflow(out: dict, rec_id: str) -> Workflow:
    """Wonder's strict JSON uses nulls; the workflow model uses defaults."""
    def strip_nulls(d):
        return {k: v for k, v in d.items() if v is not None}

    steps = []
    for s in out["steps"]:
        step = strip_nulls(s)
        step["check"] = strip_nulls(s["check"])
        if s["target"]:
            step["target"] = dict(s["target"], locators=[strip_nulls(loc) for loc in s["target"]["locators"]])
        steps.append(step)
    return Workflow.model_validate({**out, "version": 1, "source_recording": rec_id, "steps": steps})


def lint(wf: Workflow, events: list[dict], graph: dict, columns: list[str]) -> list[str]:
    """Deterministic checks of Wonder's output against the recording."""
    problems = []
    sk = skeleton(events)
    actions = [st for st in wf.steps if st.action not in ("goto", "extract")]
    if len(actions) != len(sk):
        problems.append(f"expected {len(sk)} action steps, one per skeleton entry; got {len(actions)}")
    for o in graph["outputs"]:
        if not any(st.action == "extract" and st.output == o["name"] for st in wf.steps):
            problems.append(f"missing the extract step for output {o['name']!r}")
    recorded_css = {loc["selector"] for entry in sk for loc in entry["locators"] if loc["kind"] == "css"}
    defined = {"PORTAL_URL"} | {v.name for v in wf.variables} | {sec.name for sec in wf.secrets}
    for st in wf.steps:
        locators = st.target.locators if st.target else []
        if st.target and not locators:
            problems.append(f"{st.id}: target has no locators")
        if st.action not in ("goto", "press") and not st.target:
            problems.append(f"{st.id}: {st.action} needs a target")
        for loc in locators:
            if not all(getattr(loc, f) for f in LOCATOR_FIELDS[loc.kind]):
                problems.append(f"{st.id}: {loc.kind} locator needs {' and '.join(LOCATOR_FIELDS[loc.kind])}")
            if loc.kind == "css" and loc.selector not in recorded_css:
                problems.append(f"{st.id}: css selector {loc.selector!r} was not recorded")
        texts = [st.value, st.check.value] + [loc.name or loc.text for loc in locators]
        for name in (n for t in texts if t for n in TEMPLATE.findall(t)):
            if name not in defined:
                problems.append(f"{st.id}: {{{{{name}}}}} is not a declared variable or secret")
    problems += [f"variable {v.name!r}: column {v.column!r} is not in the CSV" for v in wf.variables
                 if v.column not in columns]
    return problems


def compile_workflow(events: list[dict], graph: dict, columns: list[str], rec_id: str,
                     feedback: str | None = None, previous: dict | None = None) -> tuple[Workflow, dict]:
    """One Wonder call, validated and linted. Problems trigger one repair call that sees the error text."""
    payload = {"start_page": events[0]["url"], "skeleton": skeleton(events), "step_graph": graph,
               "csv_columns": columns}
    text = json.dumps(payload, indent=1)
    if feedback:
        text += f"\n\nYOUR PREVIOUS WORKFLOW:\n{json.dumps(previous)}\n\nIT FAILED:\n{feedback}\nFix it."
    out = meta_client.structured(
        meta_client.WONDER,
        text,
        SCHEMA,
        "workflow",
        effort="medium",
        max_output_tokens=24000,
        instructions=prompts.COMPILE,
        metadata={"prompt": prompts.COMPILE_VERSION},
        purpose="compile",
        timeout=300,
    )
    try:
        wf = to_workflow(out, rec_id)
        problems = lint(wf, events, graph, columns)
    except ValidationError as e:
        problems = [str(e)]
    if problems and not feedback:
        return compile_workflow(events, graph, columns, rec_id, feedback="\n".join(problems), previous=out)
    if problems:
        raise CompileError("; ".join(problems))
    add_anchors(wf, events)
    return wf, out


def add_anchors(wf: Workflow, events: list[dict]):
    """Each action step's anchor is where the recorder saw its element (lint guarantees one step per action)."""
    actions = [st for st in wf.steps if st.action not in ("goto", "extract")]
    for st, entry in zip(actions, skeleton(events)):
        bbox = entry["bbox"]
        if st.target and bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1] >= 0:
            st.target.anchor = Anchor(bbox=bbox)


def export_script(wf: Workflow, path: Path) -> Path:
    """Wonder writes a standalone Playwright script equivalent to the workflow (shown as the compiled program)."""
    resp = meta_client.responses(
        model=meta_client.WONDER,
        input=wf.model_dump_json(indent=1, exclude_defaults=True),
        instructions=prompts.EXPORT,
        reasoning={"effort": "low"},
        max_output_tokens=16000,
        metadata={"prompt": prompts.EXPORT_VERSION},
        purpose="compile",
        timeout=300,
    )
    code = meta_client.output_text(resp).strip()
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0]
    path.write_text(f"# Generated by Teach-Once (Muse Wonder) from workflow {wf.id}.v{wf.version}.\n{code.strip()}\n")
    py_compile.compile(str(path), doraise=True)
    return path
