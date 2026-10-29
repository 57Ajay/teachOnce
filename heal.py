"""Self-healing: when a step breaks, Muse Spark works out what changed and SAM 3.1 finds the element again.

The patched workflow is verified by running the step, saved as the next version, and used by every later row.
"""
import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor

import config
import cost
import locate
import meta_client
import prompts
import sam
import workflow
from recording import stable_css, strip_required
from run import RowContext, StepFailed, execute, resolves_now, screenshot, shapes, verify
from workflow import TEMPLATE, Anchor, Check, DatePart, Interrupt, Locator, Step, Target, Variant, Workflow

DESCRIBE_JS = (config.ROOT / "static" / "describe.js").read_text()
MAX_ATTEMPTS = 2

_REF = {"type": "integer"}
_STEP = {
    "type": "object",
    "additionalProperties": False,
    "required": ["step_id", "situation", "ref", "new_action", "parts", "noun_phrase", "explanation", "confidence"],
    "properties": {
        "step_id": {"type": "string"},
        "situation": {"type": "string", "enum": ["moved", "control_changed", "split_into_parts", "not_found"]},
        "ref": _REF,
        "new_action": {"type": "string", "enum": ["same", "select", "fill", "check", "click"]},
        "parts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["unit", "ref"],
            "properties": {"unit": {"type": "string", "enum": ["day", "month", "year"]}, "ref": _REF}}},
        "noun_phrase": {"type": "string"},
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
    },
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["interruption", "steps"],
    "properties": {
        "interruption": {
            "type": "object", "additionalProperties": False,
            "required": ["present", "explanation", "dismiss_ref", "noun_phrase"],
            "properties": {"present": {"type": "boolean"}, "explanation": {"type": "string"},
                           "dismiss_ref": _REF, "noun_phrase": {"type": "string"}}},
        "steps": {"type": "array", "items": _STEP},
    },
}


class HealFailed(Exception):
    pass


def page_window(wf: Workflow, i: int) -> list[Step]:
    """The failing step and the rest of the steps on the same page (up to the step that navigates away)."""
    window = []
    for step in wf.steps[i:]:
        window.append(step)
        if step.check.kind == "url_contains":
            break
    return window


def still_resolves(ctx: RowContext, step: Step) -> bool:
    return any(resolves_now(ctx, shape) for shape in shapes(step))


def remember(step: Step):
    """Keep the step's current shape as a variant before a heal changes its kind of control."""
    shape = Variant(**step.model_dump(include={"action", "target", "value", "check", "parts"}))
    if shape not in step.variants:
        step.variants.append(shape)


def locators_from(desc: dict, variables: dict) -> list[Locator]:
    """Locators for a described element. A name equal to this row's value of a variable becomes {{variable}}."""
    def templated(text):
        return next((f"{{{{{name}}}}}" for name, value in variables.items() if value and text == value), text)

    name, label = strip_required(desc["accessible_name"]), strip_required(desc["label_text"])
    locs = []
    if desc["role"] and name:
        locs.append(Locator(kind="role", role=desc["role"], name=templated(name)))
    if label:
        locs.append(Locator(kind="label", text=templated(label)))
    if desc["placeholder"]:
        locs.append(Locator(kind="placeholder", text=desc["placeholder"]))
    if stable_css(desc["css"]) and not any(TEMPLATE.search(loc.name or loc.text or "") for loc in locs):
        locs.append(Locator(kind="css", selector=desc["css"]))
    return locs


def step_brief(step: Step, values: dict, hidden: set) -> dict:
    value = workflow.render(step.value, values) if step.value else None
    return {
        "step_id": step.id, "intent": step.intent, "action": step.action,
        "value": "***" if value in hidden else value,
        "old_description": step.target.description if step.target else "",
        "old_noun_phrase": step.target.noun_phrase if step.target else "",
        "old_locators": [loc.model_dump(exclude_none=True) for loc in step.target.locators] if step.target else [],
    }


def candidate_lines(cands: list[dict]) -> str:
    return "\n".join(
        f'ref={c["ref"]} {c["role"] or c["tag"]}{"[" + c["type"] + "]" if c["type"] else ""} '
        f'name="{c["accessible_name"]}" label="{c["label_text"]}" placeholder="{c["placeholder"]}" box={c["bbox"]}'
        for c in cands)


class Healer:
    def __init__(self, run_dir, emit):
        self.dir = run_dir / "heals"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self.count = 0

    def __call__(self, ctx: RowContext, wf: Workflow, i: int, failure: StepFailed, row_idx: int) -> Workflow | None:
        self.count += 1
        heal_id = f"h{self.count:02d}"
        step = wf.steps[i]
        started, usd_before, calls_before = time.monotonic(), cost.spent_usd(), meta_client.stats["calls"]
        self.emit("heal_start", heal=heal_id, row=row_idx, step=step.id, kind=failure.kind,
                  summary=f"{heal_id} row {row_idx} {step.id} {failure.kind}")
        record = {"heal": heal_id, "row": row_idx, "step_id": step.id, "failure": failure.kind,
                  "message": str(failure), "from_v": wf.version, "attempts": []}
        base = wf
        for attempt in range(MAX_ATTEMPTS):
            try:
                new_wf, details = self.attempt(ctx, base, i, failure, f"{heal_id}_{attempt}")
            except (HealFailed, StepFailed, meta_client.MetaAPIError) as e:
                record["attempts"].append({"error": str(e)[:300]})
                if isinstance(e, StepFailed):
                    failure = e
                    base = getattr(e, "partial", base)  # keep a patch whose action worked but whose check didn't
                continue
            record["attempts"].append(details)
            new_wf.version = max(wf.version + 1, workflow.next_version(wf.id))
            path = workflow.save(new_wf)
            self.save_diff(wf, new_wf)
            record.update(to_v=new_wf.version, verified=True, workflow=path.name)
            return self.finish(record, started, usd_before, calls_before, new_wf)
        record["verified"] = False
        return self.finish(record, started, usd_before, calls_before, None)

    def finish(self, record, started, usd_before, calls_before, new_wf):
        record.update(latency_ms=int((time.monotonic() - started) * 1000),
                      cost_usd=round(cost.spent_usd() - usd_before, 6),
                      model_calls=meta_client.stats["calls"] - calls_before)
        with (self.dir.parent / "heals.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")
        last = record["attempts"][-1] if record["attempts"] else {}
        what = last.get("summary") or last.get("error", "")
        verdict = f"v{record['from_v']} -> v{record['to_v']}" if new_wf else "unrecoverable"
        self.emit("heal_done" if new_wf else "heal_failed", **record,
                  summary=f"{record['heal']} {verdict} in {record['latency_ms'] / 1000:.1f}s, "
                          f"${record['cost_usd']:.3f}: {what}")
        return new_wf

    def attempt(self, ctx: RowContext, wf: Workflow, i: int, failure: StepFailed, tag: str):
        page = ctx.page
        page.wait_for_load_state()
        page.add_script_tag(content=DESCRIBE_JS)
        cands = page.evaluate("TeachOnceDescribe.candidates()")
        shot = screenshot(page, full_page=True)
        if shot is None:
            raise HealFailed("could not take a screenshot")
        (self.dir / f"{tag}_before.png").write_bytes(shot)

        window = [s for k, s in enumerate(page_window(wf, i)) if k == 0 or not still_resolves(ctx, s)]
        triage = meta_client.structured(
            meta_client.SPARK,
            [{"role": "user", "content": [
                {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(shot).decode()},
                {"type": "input_text", "text": (
                    f"FAILED STEP: {wf.steps[i].id} ({failure.kind}): {failure}\nCURRENT PAGE: {page.url}\n\n"
                    f"STEPS ON THIS PAGE:\n{json.dumps([step_brief(s, ctx.values, ctx.hidden) for s in window], indent=1)}"
                    f"\n\nINTERACTIVE ELEMENTS:\n{candidate_lines(cands)}")},
            ]}],
            SCHEMA,
            "heal",
            effort="medium",
            max_output_tokens=8000,
            instructions=prompts.HEAL,
            metadata={"prompt": prompts.HEAL_VERSION},
            purpose="heal",
            timeout=120,
        )
        (self.dir / f"{tag}_triage.json").write_text(json.dumps(triage, indent=2))
        new_wf = wf.model_copy(deep=True)
        variables = {v.name: ctx.values[v.name] for v in wf.variables}
        marks = []

        if triage["interruption"]["present"]:
            it = triage["interruption"]
            desc, det, path = self.ground(page, shot, cands, it["dismiss_ref"], it["noun_phrase"])
            if not desc:
                raise HealFailed(f"interruption, but nothing to click: {it['explanation']}")
            interrupt = Interrupt(id=f"i{len(new_wf.interrupts) + 1}", description=it["explanation"],
                                  target=Target(description=it["explanation"], noun_phrase=it["noun_phrase"],
                                                locators=locators_from(desc, variables)))
            marks.append(self.mark(desc, det, f"{interrupt.id}: {it['noun_phrase']} ({path})"))
            self.write_overlay(tag, shot, marks)
            button = locate.resolve(page, interrupt.target, ctx.values, 2000)
            if button is None:
                raise HealFailed(f"interruption button not clickable: {it['noun_phrase']}")
            button.click()
            page.wait_for_load_state()
            new_wf.interrupts.append(interrupt)
            ctx.interrupts = new_wf.interrupts
            step = new_wf.steps[i]
            if failure.kind == "check_failed":
                verify(ctx, step, None, workflow.render(step.value, ctx.values) if step.value else None)
            else:
                execute(ctx, step)
            return new_wf, {"summary": f"cleared interruption ({it['explanation']}) via {path}",
                            "interrupt": interrupt.model_dump(exclude_defaults=True), "path": path}

        by_id = {s["step_id"]: s for s in triage["steps"]}
        if wf.steps[i].id not in by_id or by_id[wf.steps[i].id]["situation"] == "not_found":
            raise HealFailed(f"Spark could not find {wf.steps[i].id}")
        phrases = sorted({s["noun_phrase"] for s in triage["steps"] if s["situation"] != "not_found"})
        with ThreadPoolExecutor(max_workers=6) as pool:
            detections = dict(zip(phrases, pool.map(lambda p: sam.segment(shot, p, purpose="heal"), phrases)))

        patched, patched_ids = [], set()
        for step in new_wf.steps:
            entry = by_id.get(step.id)
            if not entry or entry["situation"] == "not_found":
                continue
            if entry["situation"] == "split_into_parts":
                remember(step)
                step.parts, paths = [], set()
                for part in entry["parts"]:
                    desc, det, path = self.ground(page, shot, cands, part["ref"], entry["noun_phrase"],
                                                  detections.get(entry["noun_phrase"]))
                    if not desc:
                        raise HealFailed(f"{step.id}: no element for the {part['unit']}")
                    step.parts.append(DatePart(unit=part["unit"], target=Target(
                        description=f"{part['unit']} of: {step.intent}", noun_phrase=entry["noun_phrase"],
                        locators=locators_from(desc, variables))))
                    marks.append(self.mark(desc, det, f"{step.id} {part['unit']} ({path})"))
                    paths.add(path)
                path = "+".join(sorted(paths))
            else:
                desc, det, path = self.ground(page, shot, cands, entry["ref"], entry["noun_phrase"],
                                              detections.get(entry["noun_phrase"]))
                if not desc:
                    continue
                self.patch(step, entry, desc, variables)
                marks.append(self.mark(desc, det, f"{step.id}: {entry['noun_phrase']} ({path})"))
            step.healed.append({"version": None, "situation": entry["situation"], "path": path})
            patched.append(f"{step.id} {entry['situation']} via {path}")
            patched_ids.add(step.id)
        self.write_overlay(tag, shot, marks)
        if wf.steps[i].id not in patched_ids:
            raise HealFailed(f"nothing to patch for {wf.steps[i].id}")
        for step in new_wf.steps:
            for h in step.healed:
                h["version"] = h["version"] or max(wf.version + 1, workflow.next_version(wf.id))
        try:
            execute(ctx, new_wf.steps[i])
        except StepFailed as e:
            if e.kind == "check_failed":
                e.partial = new_wf
            raise
        return new_wf, {"summary": "; ".join(patched), "patched": patched}

    def ground(self, page, shot, cands, ref, noun_phrase, detections=None):
        """SAM finds every control that looks like the noun phrase; Spark's ref says which one is meant.

        A detection that lands on Spark's pick is the strongest evidence ("sam+spark"). Without one we trust
        Spark's pick from the accessibility tree ("a11y_pick"); without a pick, SAM's best match ("sam_text").
        """
        if detections is None:
            detections = sam.segment(shot, noun_phrase, purpose="heal") if noun_phrase else []
        wanted = cands[ref]["css"] if 0 <= ref < len(cands) else None
        first = None
        for det in detections:
            desc = page.evaluate("([x, y]) => TeachOnceDescribe.atPoint(x, y)", list(det.center))
            if desc and wanted and desc["css"] == wanted:
                return desc, det, "sam+spark"
            first = first or (desc, det)
        if wanted:
            return page.evaluate("ref => TeachOnceDescribe.byRef(ref)", ref), None, "a11y_pick"
        if first and first[0]:
            return first[0], first[1], "sam_text"
        return None, None, "none"

    @staticmethod
    def patch(step: Step, entry: dict, desc: dict, variables: dict):
        new_locs = locators_from(desc, variables)
        old = step.target
        reshaped = entry["situation"] == "control_changed" and entry["new_action"] != "same"
        if reshaped or step.parts:
            remember(step)
        if reshaped:
            templated = next((TEMPLATE.search(loc.name or loc.text or "") for loc in old.locators
                              if TEMPLATE.search(loc.name or loc.text or "")), None) if old else None
            step.action = entry["new_action"]
            step.value = step.value or (templated.group(0) if templated else None)
            if step.action in ("select", "fill"):
                step.check = Check(kind="value_equals")
            elif step.check.kind == "value_equals":
                step.check = Check()  # a radio or checkbox has no value to compare
            kept = []
        else:
            kept = [loc for loc in (old.locators if old else []) if loc not in new_locs]
        step.parts = []  # one control again, e.g. a date that was split is a single input once more
        step.target = Target(
            description=old.description if old else entry["explanation"],
            noun_phrase=entry["noun_phrase"] or (old.noun_phrase if old else ""),
            locators=new_locs + kept,
            anchor=Anchor(bbox=desc["bbox"]),
        )

    @staticmethod
    def mark(desc, det, label):
        if det:
            return det.box, det.mask, label
        return tuple(int(v) for v in desc["bbox"]), None, label

    def write_overlay(self, tag, shot, marks):
        (self.dir / f"{tag}_overlay.png").write_bytes(sam.render_overlay(shot, marks))

    @staticmethod
    def save_diff(old: Workflow, new: Workflow):
        before = {s.id: s.model_dump(exclude_defaults=True) for s in old.steps}
        changes = [{"step_id": s.id, "before": before[s.id], "after": s.model_dump(exclude_defaults=True)}
                   for s in new.steps if s.model_dump(exclude_defaults=True) != before[s.id]]
        added = [i.model_dump(exclude_defaults=True) for i in new.interrupts[len(old.interrupts):]]
        diff = {"workflow": old.id, "from": old.version, "to": new.version, "steps": changes, "interrupts_added": added}
        path = workflow.WORKFLOWS_DIR / "diffs" / f"{old.id}.v{old.version}_to_v{new.version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(diff, indent=2))
