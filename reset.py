"""Reset the demo: the portal back to the original site, no runs, and every workflow back to how it was taught.

Usage: uv run reset.py
Recordings, compiled workflows, exported scripts and the baseline/benchmark summaries are kept.
"""
import shutil

import httpx

import config
import workflow


def healed_versions() -> list:
    """Versions written by the healer (heal history or learned interruptions); compiled versions have neither."""
    healed = lambda wf: wf.interrupts or any(step.healed for step in wf.steps)
    return [p for p in sorted(workflow.WORKFLOWS_DIR.glob("*.v*.json")) if healed(workflow.load(p))]


def reset():
    try:
        httpx.post(f"{config.PORTAL_URL}/portal/admin/drift", json={"level": 0, "extra_field": False, "blocked": False},
                   timeout=5).raise_for_status()
        print("portal: original site (level 0), switches off")
    except httpx.HTTPError:
        print(f"portal: not reachable at {config.PORTAL_URL}; it starts at level 0 anyway")
    runs = sorted(config.RUNS_DIR.glob("*/")) if config.RUNS_DIR.exists() else []
    for path in runs + [config.DATA_DIR / "bench", workflow.WORKFLOWS_DIR / "diffs"]:
        shutil.rmtree(path, ignore_errors=True)
    print(f"runs: {len(runs)} deleted")
    healed = healed_versions()
    for path in healed:
        path.unlink()
    print(f"healed workflow versions: {len(healed)} deleted" + (f" ({', '.join(p.name for p in healed)})" if healed else ""))


if __name__ == "__main__":
    reset()
