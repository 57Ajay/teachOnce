import compiler
import teach
from workflow import Workflow


def change(ts, css, name, value, url="/form"):
    return {"ts_ms": ts, "type": "change", "action": "fill", "url": url, "value": value,
            "target": {"tag": "input", "type": "text", "role": "textbox", "accessible_name": f"{name} *",
                       "label_text": f"{name} *", "placeholder": "", "css": css, "bbox": [10, 20, 110, 40]}}


def click(ts, name, url="/form"):
    return {"ts_ms": ts, "type": "click", "action": "click", "url": url,
            "target": {"tag": "button", "type": "submit", "role": "button", "accessible_name": name,
                       "label_text": "", "placeholder": "", "css": "#go", "bbox": [10, 60, 90, 80]}}


def nav(ts, url):
    return {"ts_ms": ts, "type": "navigation", "action": "navigation", "url": url, "target": None}


RECORDED = [
    nav(0, "/form"),
    change(1000, "#reg", "Registration", "bad"),
    change(2000, "#mobile", "Mobile", "123"),
    click(3000, "Submit"),
    nav(3100, "/form"),                      # validation error: same page again
    change(4000, "#reg", "Registration", "NV07AB1234"),
    click(5000, "Submit"),
    nav(5100, "/form"),                      # still failing
    change(6000, "#mobile", "Mobile", "9876543210"),
    click(7000, "Submit"),
    nav(7100, "/done"),
]


def test_final_pass_keeps_only_the_successful_attempt():
    out = teach.final_pass(RECORDED)
    assert [(e["type"], e.get("value"), e["url"]) for e in out] == [
        ("navigation", None, "/form"),
        ("change", "NV07AB1234", "/form"),
        ("change", "9876543210", "/form"),
        ("click", None, "/form"),
        ("navigation", None, "/done"),
    ]
    assert [e["idx"] for e in out] == [0, 1, 2, 3, 4]
    assert RECORDED[1]["value"] == "bad"  # the recording itself is untouched


def test_skeleton_uses_recorded_locators_and_navigation():
    sk = compiler.skeleton(teach.final_pass(RECORDED))
    assert sk[0]["locators"] == [{"kind": "role", "role": "textbox", "name": "Registration"},
                                 {"kind": "label", "text": "Registration"},
                                 {"kind": "css", "selector": "#reg"}]
    assert sk[0]["recorded_value"] == "NV07AB1234" and sk[0]["navigated_to"] is None
    assert sk[2]["action"] == "click" and sk[2]["navigated_to"] == "/done"


def wonder_output(**overrides):
    loc = lambda sel: {"kind": "css", "role": None, "name": None, "text": None, "selector": sel}
    target = lambda sel: {"description": "", "noun_phrase": "", "locators": [loc(sel)]}
    step = lambda i, action, value, sel, check="none", output=None: {
        "id": f"s{i:02d}", "intent": "", "action": action, "value": value, "output": output, "pattern": None,
        "optional": False, "target": target(sel) if sel else None, "check": {"kind": check, "value": None}}
    out = {
        "id": "demo", "name": "Demo", "start_url": "{{PORTAL_URL}}/form", "secrets": [],
        "variables": [{"name": "reg", "column": "vehicle_no", "type": "string", "example": "x", "description": ""},
                      {"name": "mobile", "column": "mobile", "type": "string", "example": "x", "description": ""}],
        "steps": [step(1, "goto", "{{PORTAL_URL}}/form", None),
                  step(2, "fill", "{{reg}}", "#reg", check="value_equals"),
                  step(3, "fill", "{{mobile}}", "#mobile"),
                  step(4, "click", None, "#go"),
                  step(5, "extract", None, "#go", output="receipt_no")],
    }
    return out | overrides


GRAPH = {"outputs": [{"name": "receipt_no", "page": "/done", "where": "", "example": ""}]}
COLUMNS = ["vehicle_no", "mobile"]
SITE = {"start_url": "{{PORTAL_URL}}/form", "password_env": "PORTAL_PASSWORD"}


def test_to_workflow_drops_nulls_and_anchors_come_from_the_recording():
    wf = compiler.to_workflow(wonder_output(), "rec_x")
    assert isinstance(wf, Workflow) and wf.version == 1 and wf.source_recording == "rec_x"
    assert wf.steps[1].target.locators[0].model_dump(exclude_none=True) == {"kind": "css", "selector": "#reg"}
    events = teach.final_pass(RECORDED)
    events[2]["target"] = dict(events[2]["target"], bbox=[10, -40, 110, -20])  # scrolled out of view
    compiler.add_anchors(wf, events)
    assert wf.steps[1].target.anchor.bbox == [10, 20, 110, 40]
    assert wf.steps[2].target.anchor is None
    assert wf.steps[4].target.anchor is None  # extract steps have no recorded element


def test_lint_accepts_a_faithful_workflow_and_names_each_problem():
    events = teach.final_pass(RECORDED)
    assert compiler.lint(compiler.to_workflow(wonder_output(), "r"), events, GRAPH, COLUMNS, SITE) == []

    bad = wonder_output(start_url="http://127.0.0.1:8000/form", secrets=[{"name": "password", "env": "PASSWORD"}])
    bad["steps"][3]["check"] = {"kind": "url_contains", "value": "/form"}
    bad["steps"][1]["target"]["locators"][0]["selector"] = "#invented"
    bad["steps"][2]["value"] = "{{phone}}"
    bad["variables"][0]["column"] = "registration"
    bad["steps"].pop()
    problems = compiler.lint(compiler.to_workflow(bad, "r"), events, GRAPH, COLUMNS, SITE)
    assert problems == [
        "start_url must be '{{PORTAL_URL}}/form'",
        "secret 'password': env must be 'PORTAL_PASSWORD'",
        "s04: url_contains '/form' is already true on /form; use a part only /done has",
        "missing the extract step for output 'receipt_no'",
        "s02: css selector '#invented' was not recorded",
        "s03: {{phone}} is not a declared variable or secret",
        "variable 'reg': column 'registration' is not in the CSV",
    ]


def test_live_recordings_get_their_own_start_url_and_password_env():
    assert teach.on_portal("/portal/login") and teach.on_portal("{{PORTAL_URL}}/portal/login")
    assert teach.on_portal("http://127.0.0.1:8000/portal/login")
    live = "https://opensource-demo.orangehrmlive.com/web/index.php/auth/login"
    assert not teach.on_portal(live)
    assert teach.password_env(live) == "ORANGEHRMLIVE_PASSWORD"
    assert teach.password_env("/portal/login") == "PORTAL_PASSWORD"
    assert teach.password_env("http://10.0.0.5:8080/login") == "10_0_0_5_PASSWORD"
    assert teach.workflow_start_url({"start_url": live}, "/web/index.php/auth/login") == live
    assert teach.workflow_start_url({"start_url": "/portal/login"}, "/portal/login") == "{{PORTAL_URL}}/portal/login"
