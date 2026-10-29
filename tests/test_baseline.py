import pytest

import baseline


class Recorder:
    """Stands in for page, page.mouse and page.keyboard; records every call."""

    def __init__(self, calls=None, prefix=""):
        self.calls = [] if calls is None else calls
        self.prefix = prefix

    def __getattr__(self, name):
        if name in ("mouse", "keyboard"):
            return Recorder(self.calls, f"{name}.")
        return lambda *args, **kw: self.calls.append((self.prefix + name, args, kw))


def performed(*actions):
    page = Recorder()
    for action in actions:
        baseline.perform(page, action)
    return page.calls


def test_computer_actions_become_playwright_calls():
    assert performed(
        {"type": "click", "button": "left", "x": 618, "y": 303},
        {"type": "type", "text": "operator"},
        {"type": "scroll", "x": 640, "y": 400, "scroll_x": 0, "scroll_y": 5},
        {"type": "drag", "path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]},
        {"type": "screenshot"},
    ) == [
        ("mouse.click", (618, 303), {"button": "left"}),
        ("keyboard.type", ("operator",), {}),
        ("mouse.move", (640, 400), {}),
        ("mouse.wheel", (0, 500), {}),
        ("mouse.move", (1, 2), {}),
        ("mouse.down", (), {}),
        ("mouse.move", (3, 4), {}),
        ("mouse.up", (), {}),
    ]


def test_keypress_names_and_chords():
    assert performed({"type": "keypress", "keys": ["CTRL", "a"]}) == [("keyboard.press", ("Control+a",), {})]
    assert performed({"type": "keypress", "keys": ["Page_Down", "ENTER", "C"]}) == [
        ("keyboard.press", ("PageDown",), {}), ("keyboard.press", ("Enter",), {}), ("keyboard.press", ("C",), {})]


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="teleport"):
        performed({"type": "teleport"})


ROW = {"vehicle_no": "SR69RB1543", "owner_name": "Kavya Saxena", "vehicle_type": "Car", "from_state": "Southreach",
       "to_state": "Eastmarch", "entry_date": "2026-11-28", "tax_period": "30 days", "mobile": "9204250596"}
RECEIPT = ("Payment Successful\nReceipt No.\tDTP-2026-000123\nVehicle registration number\tSR69RB1543\n"
           "Owner name\tKavya Saxena\nVehicle type\tCar\nRoute\tSouthreach → Eastmarch\nEntry date\t2026-11-28\n"
           "Tax period\t30 days")


def test_receipt_must_match_the_row():
    assert baseline.receipt_matches(RECEIPT, ROW)
    assert not baseline.receipt_matches(RECEIPT.replace("2026-11-28", "2026-11-27"), ROW)
    assert not baseline.receipt_matches(RECEIPT, {**ROW, "to_state": "Westholm"})


def result(status, usd, turns, seconds):
    return {"status": status, "usd": usd, "turns": turns, "actions": 2 * turns, "input_tokens": 1000 * turns,
            "cached_tokens": 0, "output_tokens": 100 * turns, "seconds": seconds}


def test_summary_extrapolates_baseline_and_teach_once():
    s = baseline.level_summary([result("ok", 0.10, 10, 100), result("failed", 0.30, 30, 300)], level=3)
    b, t = s["baseline"], s["teach_once"]
    assert (b["ok"], b["success_rate"], b["usd_per_successful_row"]) == (1, 0.5, 0.4)
    assert b["mean_per_row"]["usd"] == pytest.approx(0.2)
    assert b["extrapolated"]["per_day_10k"] == {"rows": 10_000, "usd": 2000.0, "model_calls": 200_000, "hours": 555.56}
    assert t["one_time_usd"] == 0.34
    assert t["extrapolated"]["per_day_10k"] == {"rows": 10_000, "usd": 0.34, "model_calls": 0, "hours": 4.17}
