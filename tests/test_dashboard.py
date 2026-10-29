import json

import httpx
import pytest

import app
import config
from conftest import set_drift


def test_baseline_reference_averages_all_measured_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    level = lambda rows, ok, usd: {"baseline": {"rows": rows, "ok": ok, "mean_per_row": {
        "usd": usd, "turns": 20 * usd * 10, "seconds": 1000 * usd, "input_tokens": 1e6 * usd}}}
    (tmp_path / "baseline_summary.json").write_text(json.dumps(
        {"model": "muse-spark-1.3", "levels": {"0": level(5, 4, 0.2), "3": level(15, 9, 0.4)}}))
    ref = app.baseline_reference()
    assert (ref["rows"], ref["ok"]) == (20, 13)
    assert ref["usd"] == pytest.approx(0.35)
    assert ref["seconds"] == pytest.approx(350)


def read_stream(url, last_id=None):
    headers = {"Last-Event-ID": str(last_id)} if last_id is not None else {}
    with httpx.stream("GET", url, headers=headers, timeout=120) as resp:
        return [(int(line[4:]) if line.startswith("id: ") else json.loads(line[6:]))
                for line in resp.iter_lines() if line.startswith(("id: ", "data: "))]


def test_run_started_from_the_dashboard_streams_its_events(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTAL_URL", base_url)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    set_drift(base_url, 0)
    r = httpx.post(f"{base_url}/app/api/runs", json={"workflow": "examples/pay-interstate-tax.v1.json", "rows": 2, "heal": False})
    run_id = r.raise_for_status().json()["run_id"]
    url = f"{base_url}/app/api/runs/{run_id}/events"

    stream = read_stream(url)
    ids, events = stream[0::2], stream[1::2]
    assert ids == list(range(len(events)))
    assert events[0]["type"] == "run_start" and events[-1]["type"] == "run_done"
    assert [e["status"] for e in events if e["type"] == "row_done"] == ["ok", "ok"]
    assert (tmp_path / "rows.csv").exists()

    resumed = read_stream(url, last_id=9)
    assert resumed[1::2] == events[10:]
    assert httpx.get(f"{base_url}/app/runs/{run_id}/steps/000_s01.png").headers["content-type"] == "image/png"
    assert httpx.get(f"{base_url}/app/runs/{run_id}/steps/..%2Fsummary.json").status_code == 404
