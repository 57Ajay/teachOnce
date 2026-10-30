import bench


def case(kind, ok, rows, usd, stopped=None):
    return {"kind": kind, "ok": ok, "rows": rows, "heals": 2, "model_calls": 5, "cost_usd": usd, "duration_s": 30,
            "stopped": stopped}


def test_summary_counts_recovered_redesigns_and_correct_stops():
    s = bench.summarize([case("random", 5, 5, 0.04), case("random", 3, 5, 0.06),
                         case("needs_human", 0, 1, 0.01, stopped="new required field"), case("needs_human", 0, 1, 0.0)])
    assert (s["redesigns"], s["recovered"], s["rows_ok"], s["rows"]) == (2, 1, 8, 10)
    assert (s["usd"], s["usd_per_redesign"]) == (0.1, 0.05)
    assert (s["needs_human_cases"], s["stopped_correctly"], s["needs_human_usd"]) == (2, 1, 0.01)
