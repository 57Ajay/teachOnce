import json

import pytest

import config
import heal
import run
import workflow
from conftest import set_drift
from workflow import Locator, Step, Target

WF = workflow.load(config.ROOT / "examples" / "pay-interstate-tax.v1.json")


def desc(**kw):
    return {"role": "", "accessible_name": "", "label_text": "", "placeholder": "", "css": "", "bbox": [1, 2, 3, 4]} | kw


def test_page_window_runs_to_the_step_that_leaves_the_page():
    i = next(k for k, s in enumerate(WF.steps) if s.id == "s06")
    assert [s.id for s in heal.page_window(WF, i)] == [f"s{n:02d}" for n in range(6, 16)]


def test_locators_from_templates_row_values_and_keeps_only_id_css():
    variables = {"tax_period": "7 days", "owner_name": "Asha Verma"}
    radio = heal.locators_from(desc(role="radio", accessible_name="7 days", label_text="7 days", css="#kab12_7"), variables)
    assert [loc.model_dump(exclude_none=True) for loc in radio] == [
        {"kind": "role", "role": "radio", "name": "{{tax_period}}"},
        {"kind": "label", "text": "{{tax_period}}"},
    ]
    field = heal.locators_from(desc(role="textbox", accessible_name="Name of Owner *", label_text="Name of Owner *",
                                    css="div > div:nth-of-type(2) > input"), variables)
    assert [loc.kind for loc in field] == ["role", "label"] and field[0].name == "Name of Owner"
    button = heal.locators_from(desc(role="button", accessible_name="Compute Payable Amount", css="#k13489a"), variables)
    assert button[-1] == Locator(kind="css", selector="#k13489a")


def step(action="fill", value="{{owner_name}}", locators=None):
    return Step(id="s07", intent="Enter the owner name", action=action, value=value,
                target=Target(description="Owner name field", noun_phrase="input box",
                              locators=locators or [Locator(kind="label", text="Owner name")]))


def test_patch_moved_prepends_new_locators_and_keeps_old_ones():
    s = step()
    entry = {"situation": "moved", "new_action": "same", "noun_phrase": "white input box", "explanation": ""}
    heal.Healer.patch(s, entry, desc(role="textbox", accessible_name="Name of Registered Owner *",
                                     label_text="Name of Registered Owner *", bbox=[179, 533, 539, 570]), {})
    assert [loc.name or loc.text for loc in s.target.locators] == [
        "Name of Registered Owner", "Name of Registered Owner", "Owner name"]
    assert s.target.description == "Owner name field" and s.target.anchor.bbox == [179, 533, 539, 570]


def test_patch_control_changed_turns_radio_into_select_with_the_same_variable():
    s = step(action="check", value=None, locators=[Locator(kind="role", role="radio", name="{{tax_period}}")])
    entry = {"situation": "control_changed", "new_action": "select", "noun_phrase": "dropdown menu", "explanation": ""}
    heal.Healer.patch(s, entry, desc(role="combobox", accessible_name="Permit Validity *", label_text="Permit Validity *"),
                      {"tax_period": "7 days"})
    assert (s.action, s.value, s.check.kind) == ("select", "{{tax_period}}", "value_equals")
    assert [loc.kind for loc in s.target.locators] == ["role", "label"]  # the radio locators are gone


def test_date_parts():
    assert run.date_parts("2026-11-03") == {"year": "2026", "month": "11", "day": "03"}


@pytest.mark.live
def test_live_heal_at_drift_1_then_no_model_calls(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTAL_URL", base_url)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(workflow, "WORKFLOWS_DIR", tmp_path / "workflows")
    set_drift(base_url, 1)
    try:
        summary = run.run(config.ROOT / "examples" / "pay-interstate-tax.v1.json", config.DATA_DIR / "rows.csv",
                          limit=3, run_id="live_heal")
    finally:
        set_drift(base_url, 0)
    results = [json.loads(line) for line in (tmp_path / "runs" / "live_heal" / "results.jsonl").read_text().splitlines()]
    assert summary["ok"] == 3 and summary["heals"] == 1
    assert [r["model_calls"] for r in results[1:]] == [0, 0]
