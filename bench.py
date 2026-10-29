"""Prove the healer on redesigns nobody wrote down: random portal layouts, each one run from the original workflow.

Usage: uv run bench.py [workflow] [--redesigns 20] [--rows 5] [--seed 100]
The portal must be running. Runs land in data/runs/ (open them in the dashboard); the summary in data/bench_summary.json.
"""
import argparse
import json
from datetime import datetime

import httpx

import config
import gen_data
import run
import workflow

SUMMARY_PATH = config.DATA_DIR / "bench_summary.json"


def set_portal(**change) -> dict:
    return httpx.post(f"{config.PORTAL_URL}/portal/admin/drift", json=change).raise_for_status().json()


def summarize(results: list[dict]) -> dict:
    redesigns = [r for r in results if r["kind"] == "random"]
    handoffs = [r for r in results if r["kind"] == "needs_human"]
    n = len(redesigns) or 1
    return {
        "redesigns": len(redesigns),
        "recovered": sum(r["ok"] == r["rows"] for r in redesigns),
        "rows_ok": sum(r["ok"] for r in redesigns),
        "rows": sum(r["rows"] for r in redesigns),
        "heals": sum(r["heals"] for r in redesigns),
        "model_calls": sum(r["model_calls"] for r in redesigns),
        "usd": round(sum(r["cost_usd"] for r in redesigns), 4),
        "usd_per_redesign": round(sum(r["cost_usd"] for r in redesigns) / n, 4),
        "seconds_per_redesign": round(sum(r["duration_s"] for r in redesigns) / n, 1),
        "needs_human_cases": len(handoffs),
        "stopped_correctly": sum(bool(r["stopped"]) for r in handoffs),
        "needs_human_usd": round(sum(r["cost_usd"] for r in handoffs), 4),
    }


def bench(workflow_path, redesigns: int, rows: int, seed: int) -> dict:
    bench_id = datetime.now().strftime("bench_%Y%m%d_%H%M%S")
    rows_csv = config.DATA_DIR / "rows.csv"
    if not rows_csv.exists():
        gen_data.write(rows_csv)
    cases = [("random", {"seed": seed + k}) for k in range(redesigns)]
    cases += [("needs_human", {"extra_field": True}), ("needs_human", {"blocked": True})]
    results, runtime_dir = [], workflow.WORKFLOWS_DIR
    try:
        for n, (kind, change) in enumerate(cases):
            set_portal(level=0, extra_field=False, blocked=False)
            portal = set_portal(**change)
            # every case starts from the original workflow, so no case benefits from another's heals
            workflow.WORKFLOWS_DIR = config.DATA_DIR / "bench" / bench_id / f"case{n:02d}"
            summary = run.run(workflow_path, rows_csv, limit=rows, run_id=f"{bench_id}_{n:02d}")
            heals = config.RUNS_DIR / summary["run_id"] / "heals.jsonl"
            records = [json.loads(line) for line in heals.read_text().splitlines()] if heals.exists() else []
            heal_notes = [h.get("needs_human") or h["attempts"][-1].get("summary") or h["attempts"][-1].get("error", "")
                          for h in records]
            result = {"case": n, "kind": kind, "layout": portal["layout"], "changes": portal["changes"], **summary,
                      "heal_notes": heal_notes}
            results.append(result)
            print(f"{n:>2} {kind:<11} {portal['layout']:<12} {summary['ok']}/{summary['rows']} rows OK, "
                  f"{summary['heals']} heals, ${summary['cost_usd']:.3f}, {summary['duration_s']} s"
                  f"{'  STOPPED: ' + summary['stopped'] if summary['stopped'] else ''}", flush=True)
            if kind == "random" and summary["ok"] < summary["rows"]:
                print(f"     changes: {', '.join(portal['changes'])}\n     heals: {heal_notes}", flush=True)
    finally:
        workflow.WORKFLOWS_DIR = runtime_dir
        set_portal(level=0, extra_field=False, blocked=False)
    out = {"bench_id": bench_id, "workflow": str(workflow_path), "rows_per_case": rows, "seed": seed,
           "summary": summarize(results), "cases": results}
    SUMMARY_PATH.write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", nargs="?", default=str(config.ROOT / "examples" / "pay-interstate-tax.v1.json"))
    ap.add_argument("--redesigns", type=int, default=20)
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--seed", type=int, default=100)
    args = ap.parse_args()
    result = bench(args.workflow, args.redesigns, args.rows, args.seed)
    print(json.dumps(result["summary"], indent=2))
