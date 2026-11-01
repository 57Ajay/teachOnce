import csv
import json

import httpx
import pytest

import config
import gen_data
import meta_client
import run
import workflow
from conftest import set_drift

WF = config.ROOT / "examples" / "pay-interstate-tax.v1.json"


def test_render_fills_variables_and_rejects_unknown_ones():
    assert workflow.render("{{ PORTAL_URL }}/portal/{{page}}", {"PORTAL_URL": "http://x", "page": "login"}) == "http://x/portal/login"
    with pytest.raises(KeyError, match="vehicle_no"):
        workflow.render("{{vehicle_no}}", {})


def test_save_never_overwrites_a_version(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "WORKFLOWS_DIR", tmp_path)
    wf = workflow.load(WF)
    workflow.save(wf)
    with pytest.raises(FileExistsError):
        workflow.save(wf)
    assert workflow.latest(wf.id).name == "pay-interstate-tax.v1.json"


@pytest.fixture
def rows_csv(tmp_path, base_url, monkeypatch):
    monkeypatch.setattr(config, "PORTAL_URL", base_url)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    path = tmp_path / "rows.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=gen_data.COLUMNS)
        writer.writeheader()
        writer.writerows(gen_data.generate(3, seed=3))
    return path


def test_happy_path_makes_zero_model_calls(rows_csv, base_url, monkeypatch):
    def no_model_calls(*a, **kw):
        raise AssertionError("the happy path must not call a model")

    monkeypatch.setattr(meta_client, "_post", no_model_calls)
    set_drift(base_url, 0)
    summary = run.run(WF, rows_csv, run_id="happy", heal=False)
    assert (summary["ok"], summary["failed"], summary["model_calls"]) == (3, 0, 0)
    results = [json.loads(line) for line in (config.RUNS_DIR / "happy" / "results.jsonl").read_text().splitlines()]
    assert all(r["outputs"]["receipt_no"].startswith("DTP-") for r in results)


@pytest.mark.parametrize("level, step_id, kind", [(1, "s15", "locator_not_found"), (3, "s04", "blocked_by_overlay")])
def test_drift_fails_cleanly_without_heal(rows_csv, base_url, level, step_id, kind):
    set_drift(base_url, level)
    try:
        summary = run.run(WF, rows_csv, limit=1, run_id=f"drift{level}", heal=False)
    finally:
        set_drift(base_url, 0)
    result = json.loads((config.RUNS_DIR / f"drift{level}" / "results.jsonl").read_text())
    assert summary["failed"] == 1
    assert (result["error"]["step_id"], result["error"]["kind"]) == (step_id, kind)
    assert (config.RUNS_DIR / f"drift{level}" / "steps" / f"000_{step_id}.png").exists()


def test_a_step_runs_in_whichever_shape_the_site_has_now(rows_csv, base_url, monkeypatch, tmp_path):
    """A date healed into day/month/year dropdowns still works after the site switches back to a date input."""
    monkeypatch.setattr(meta_client, "_post", lambda *a, **kw: pytest.fail("no model calls expected"))
    wf = workflow.load(WF)
    s11 = next(s for s in wf.steps if s.id == "s11")
    s11.variants = [workflow.Variant(**s11.model_dump(include={"action", "target", "value", "check", "parts"}))]
    s11.parts = [workflow.DatePart(unit=unit, target=workflow.Target(locators=[workflow.Locator(kind="role", role="combobox", name=name)]))
                 for unit, name in (("day", "Day"), ("month", "Month"), ("year", "Year"))]
    path = tmp_path / "shapes.v1.json"
    path.write_text(wf.model_dump_json())
    set_drift(base_url, 0)
    summary = run.run(path, rows_csv, limit=1, run_id="shapes", heal=False)
    assert (summary["ok"], summary["model_calls"]) == (1, 0)


def test_format_date_follows_the_fields_pattern():
    assert run.format_date("2026-11-03", "DD/MM/YYYY") == "03/11/2026"
    assert run.format_date("2026-11-03", "mm-dd-yyyy") == "11-03-2026"
    assert run.format_date("2026-11-03", "e.g. 3 Nov") == "2026-11-03"


def test_modern_controls_need_no_model_calls(rows_csv, base_url, monkeypatch):
    """Custom dropdowns (a button that opens a list) and a DD/MM/YYYY text date, same labels: no heal needed."""
    import portal

    monkeypatch.setattr(meta_client, "_post", lambda *a, **kw: pytest.fail("no model calls expected"))
    monkeypatch.setattr(portal, "random_traits", lambda seed: portal.LEVEL0 | dict(
        vehicle_type="custom", states="custom", tax_period="radio", date="text"))
    httpx.post(f"{base_url}/portal/admin/drift", json={"seed": 1}).raise_for_status()
    try:
        summary = run.run(WF, rows_csv, limit=1, run_id="modern", heal=False)
    finally:
        set_drift(base_url, 0)
    assert (summary["ok"], summary["model_calls"]) == (1, 0)


MODERN_FORM = """
<style>.box { position: relative } .box input { position: absolute; opacity: 0 } .box span { display: inline-block;
  width: 16px; height: 16px; border: 1px solid #444; position: relative; z-index: 1 } [role=listbox][hidden] { display: none }</style>
<div class="group"><div><label>Email</label></div><div><input placeholder="Type here"></div></div>
<div class="group"><div><label>Contact Number</label></div><div><input placeholder="Type here"></div></div>
<div class="group"><div><label>Vacancy</label></div><div><div class="select"><div class="text" tabindex="0">-- Select --</div><i>v</i></div>
  <div role="listbox" hidden><div role="option">Software Engineer</div><div role="option">Senior QA Lead</div></div></div></div>
<div class="group"><div><label>Consent to keep data</label></div><div><label class="box"><input type="checkbox"><span></span></label></div></div>
<script>
  const text = document.querySelector(".text"), list = document.querySelector("[role=listbox]");
  text.onclick = () => (list.hidden = !list.hidden);
  list.onclick = (e) => { text.textContent = e.target.textContent; list.hidden = true; };
</script>
"""


def test_runner_handles_unlinked_labels_custom_dropdowns_and_styled_checkboxes():
    from playwright.sync_api import sync_playwright

    import locate
    from workflow import Locator, Step, Target

    def step(action, label, value=None, check="none"):
        return Step(id="s", intent="", action=action, value=value, check={"kind": check},
                    target=Target(locators=[Locator(kind="label", text=label)]))

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=config.CHROMIUM_PATH)
        page = browser.new_page()
        page.set_content(MODERN_FORM)
        page.add_script_tag(path=config.ROOT / "static" / "describe.js")
        labels = page.evaluate("""() => [...document.querySelectorAll("input, .text")].map(
            (el) => TeachOnceDescribe.describe(el).label_text)""")
        assert labels == ["Email", "Contact Number", "Vacancy", "Consent to keep data"]
        assert page.evaluate("TeachOnceDescribe.describe(TeachOnceDescribe.interactive(document.querySelector('i'))).label_text") == "Vacancy"

        ctx = run.RowContext(page, {}, set(), [])
        run.execute(ctx, step("fill", "Contact Number", "555-0100", "value_equals"))
        run.execute(ctx, step("select", "Vacancy", "Senior QA Lead", "value_equals"))
        run.execute(ctx, step("check", "Consent to keep data"))
        assert page.locator("input").nth(1).input_value() == "555-0100"
        assert page.locator(".text").inner_text() == "Senior QA Lead"
        assert page.locator("input[type=checkbox]").is_checked()
        assert locate.by_label(page, "Email").count() == 1
        browser.close()
