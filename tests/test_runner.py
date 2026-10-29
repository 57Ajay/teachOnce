import csv
import json

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
