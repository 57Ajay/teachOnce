import csv
import json

import config

SITE = config.ROOT / "test-site"


def rows(name):
    with (config.ROOT / "examples" / name).open(newline="") as f:
        return list(csv.DictReader(f))


def test_task_csvs_fit_the_test_sites_seed_data():
    seed = json.loads((SITE / "seed.json").read_text())
    emails = {c["email"] for c in seed["candidates"]}
    add, remove, schedule = rows("hire-add-candidates.csv"), rows("hire-remove-candidates.csv"), rows("hire-schedule-interviews.csv")
    assert not {r["email"] for r in add} & emails  # adding would fail as a duplicate
    assert {r["job"] for r in add} <= set(seed["jobs"])
    assert {r["email"] for r in remove} <= emails and {r["email"] for r in schedule} <= emails
    assert not {r["email"] for r in remove} & {r["email"] for r in schedule}  # both run after one reset
    schedule_page = (SITE / "src" / "schedule.tsx").read_text()
    for r in schedule:
        assert r["interviewer"] in seed["interviewers"]
        assert f'"{r["interview_type"]}"' in schedule_page and f'"{r["duration"]}"' in schedule_page
        hour, minute = map(int, r["time"].split(":"))
        assert 9 <= hour <= 17 and minute in (0, 30)
