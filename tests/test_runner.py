import csv
import json

import pytest

import config
import gen_data
import meta_client
import run
import workflow
from conftest import set_drift

WF = config.ROOT / "workflows" / "pay-interstate-tax.v1.json"


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
    summary = run.run(WF, rows_csv, run_id="happy")
    assert (summary["ok"], summary["failed"], summary["model_calls"]) == (3, 0, 0)
    results = [json.loads(line) for line in (config.RUNS_DIR / "happy" / "results.jsonl").read_text().splitlines()]
    assert all(r["outputs"]["receipt_no"].startswith("DTP-") for r in results)


@pytest.mark.parametrize("level, step_id, kind", [(1, "s15", "locator_not_found"), (3, "s04", "blocked_by_overlay")])
def test_drift_fails_cleanly_without_heal(rows_csv, base_url, level, step_id, kind):
    set_drift(base_url, level)
    try:
        summary = run.run(WF, rows_csv, limit=1, run_id=f"drift{level}")
    finally:
        set_drift(base_url, 0)
    result = json.loads((config.RUNS_DIR / f"drift{level}" / "results.jsonl").read_text())
    assert summary["failed"] == 1
    assert (result["error"]["step_id"], result["error"]["kind"]) == (step_id, kind)
    assert (config.RUNS_DIR / f"drift{level}" / "steps" / f"000_{step_id}.png").exists()
