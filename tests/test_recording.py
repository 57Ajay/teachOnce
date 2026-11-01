import re

from playwright.sync_api import sync_playwright

import config
import recording

FAKE_MEDIA = ["--auto-accept-this-tab-capture", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]


def ev(ts, type_, tag="input", input_type="text", name="", **extra):
    return {"ts_ms": ts, "type": type_, "target": {"tag": tag, "type": input_type, "accessible_name": name}, **extra}


def test_normalize_keeps_one_event_per_intent():
    raw = [
        ev(0, "click", name="Owner name"),                                  # focus click: dropped
        ev(900, "change", name="Owner name", value="Asha Verma"),
        ev(950, "keydown", key="Tab"),                                       # dropped
        ev(1000, "click", tag="label", input_type="", name="7 days"),       # label click: dropped
        ev(1001, "click", input_type="radio", name="7 days"),               # dropped, change carries it
        ev(1002, "change", input_type="radio", name="7 days", value="7", checked=True),
        ev(1100, "change", tag="select", input_type="", name="Vehicle type", value="Bus"),
        ev(1200, "change", input_type="checkbox", name="I declare", checked=True),
        ev(1300, "change", input_type="date", name="Entry date", value="2026-11-03"),
        ev(1400, "click", tag="button", input_type="submit", name="Calculate Tax"),
        ev(1450, "submit", tag="form", input_type=""),                       # caused by the click: dropped
        ev(2000, "keydown", name="Mobile number", key="Enter"),
        ev(2010, "submit", tag="form", input_type=""),                       # caused by Enter: dropped
    ]
    out = recording.normalize(raw)
    assert [(e["action"], e["target"]["accessible_name"]) for e in out] == [
        ("fill", "Owner name"),
        ("check", "7 days"),
        ("select", "Vehicle type"),
        ("check", "I declare"),
        ("fill_date", "Entry date"),
        ("click", "Calculate Tax"),
        ("press", "Mobile number"),
    ]
    assert [e["idx"] for e in out] == list(range(7))


def test_normalize_turns_a_custom_dropdown_pick_into_a_select():
    opener = {"tag": "div", "type": "", "role": "", "accessible_name": "", "label_text": "Vacancy", "css": "div > div"}
    option = {"tag": "div", "type": "", "role": "option", "accessible_name": "Software Engineer"}
    raw = [
        {"ts_ms": 100, "type": "click", "target": opener},
        {"ts_ms": 200, "type": "click", "target": opener},                  # opened and closed again
        {"ts_ms": 300, "type": "click", "target": opener},
        {"ts_ms": 400, "type": "click", "target": option},
        {"ts_ms": 500, "type": "click", "target": {"tag": "button", "type": "submit", "accessible_name": "Save"}},
    ]
    out = recording.normalize(raw)
    assert [(e["action"], e.get("value")) for e in out] == [("select", "Software Engineer"), ("click", None)]
    assert out[0]["target"]["label_text"] == "Vacancy" and out[0]["ts_ms"] == 300


def test_studio_records_a_full_teach_session(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(recording, "REC_DIR", tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=config.CHROMIUM_PATH, args=FAKE_MEDIA)
        page = browser.new_page(viewport={"width": 1320, "height": 880})
        page.goto(f"{base_url}/app/teach/new")
        page.click("#start")
        page.wait_for_selector("body.recording")
        f = page.frame_locator("#portal")
        f.get_by_label("Username").fill(config.PORTAL_USER)
        f.get_by_label("Password").fill(config.PORTAL_PASSWORD)
        f.get_by_role("button", name="Sign in").click()
        f.get_by_role("link", name="Pay Interstate Vehicle Tax").click()
        f.get_by_label("Vehicle registration number").fill("NV07AB1234")
        f.get_by_label("Vehicle type").select_option(label="Bus")
        page.wait_for_timeout(500)
        page.click("#stop")
        page.wait_for_url(re.compile(r"/app/teach/rec_\d{8}_\d{6}$"))
        rec_id = page.url.rsplit("/", 1)[1]
        browser.close()

    rec = recording.load(rec_id)
    assert rec["meta"]["viewport"] == [1280, 800]
    assert rec["meta"]["has_narration"]
    assert {"teach.mp4", "narration.wav", "events_raw.jsonl"} <= {p.name for p in rec["dir"].iterdir()}
    steps = [(e["action"], (e["target"] or {}).get("accessible_name"), e.get("value")) for e in rec["events"]]
    assert steps == [
        ("navigation", None, None),
        ("fill", "Username *", config.PORTAL_USER),
        ("fill", "Password *", "***"),
        ("click", "Sign in", None),
        ("navigation", None, None),
        ("click", "Pay Interstate Vehicle Tax Pay entry tax for vehicles crossing state borders.", None),
        ("navigation", None, None),
        ("fill", "Vehicle registration number *", "NV07AB1234"),
        ("select", "Vehicle type *", "Bus"),
    ]
    reg = rec["events"][7]["target"]
    assert reg["css"] == "#veh_no" and reg["role"] == "textbox" and reg["bbox"][2] > reg["bbox"][0]


def test_live_recorder_saves_a_recording_like_the_studio(base_url, tmp_path, monkeypatch):
    import teach_live

    monkeypatch.setattr(recording, "REC_DIR", tmp_path)
    with sync_playwright() as p:
        session = teach_live.open_session(p, f"{base_url}/portal/logout", headless=True)
        page = session["page"]
        page.get_by_label("Username").fill(config.PORTAL_USER)
        page.get_by_label("Password").fill(config.PORTAL_PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.get_by_role("link", name="Pay Interstate Vehicle Tax").click()
        page.get_by_label("Vehicle registration number").fill("NV07AB1234")
        page.get_by_label("Vehicle type").select_option(label="Bus")
        page.wait_for_timeout(300)
        rec_id = teach_live.finish(session, config.ROOT / "data" / "rows.csv")

    rec = recording.load(rec_id)
    assert rec["meta"]["viewport"] == [1280, 800] and not rec["meta"]["has_narration"]
    assert rec["meta"]["csv"] == "data/rows.csv" and rec["meta"]["duration_ms"] > 0
    steps = [(e["action"], e["url"], e.get("value")) for e in rec["events"]]
    assert steps == [
        ("navigation", "/portal/login", None),
        ("fill", "/portal/login", config.PORTAL_USER),
        ("fill", "/portal/login", "***"),
        ("click", "/portal/login", None),
        ("navigation", "/portal/dashboard", None),
        ("click", "/portal/dashboard", None),
        ("navigation", "/portal/tax/new", None),
        ("fill", "/portal/tax/new", "NV07AB1234"),
        ("select", "/portal/tax/new", "Bus"),
    ]
    assert all(a["ts_ms"] <= b["ts_ms"] for a, b in zip(rec["events"], rec["events"][1:]))
