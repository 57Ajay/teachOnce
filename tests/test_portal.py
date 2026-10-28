import re
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

import app
import config

ROW = {"veh_no": "NV07AB1234", "owner_name": "Asha Verma", "vehicle_type": "Bus", "from_state": "Northvale",
       "to_state": "Westholm", "entry_date": "2026-11-03", "tax_period": "7 days", "mobile": "9876543210"}
LABELS = {
    0: ["Vehicle registration number", "Owner name", "Vehicle type", "From state", "To state", "Mobile number"],
    2: ["Registration No. of Vehicle", "Name of Registered Owner", "Vehicle Category", "State of Origin",
        "Destination State", "Contact Mobile No."],
}


@pytest.fixture(scope="module")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=config.CHROMIUM_PATH)
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    context = browser.new_context(base_url=base_url, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.set_default_timeout(3000)
    yield page
    context.close()


def set_drift(base_url, level):
    httpx.post(f"{base_url}/portal/admin/drift", json={"level": level}).raise_for_status()


def fill_like_a_human(page, level):
    """Completes the flow using whatever the page currently shows (what a person would read)."""
    page.goto("/portal/login")
    if level == 3:
        page.get_by_role("button", name="Accept all").click()
    page.get_by_label("Username").fill(config.PORTAL_USER)
    page.get_by_label("Password").fill(config.PORTAL_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("link", name="Pay Interstate Vehicle Tax").click()

    reg, owner, vtype, src, dst, mobile = LABELS[0 if level < 2 else 2]
    page.get_by_label(reg).fill(ROW["veh_no"])
    page.get_by_label(owner).fill(ROW["owner_name"])
    page.get_by_label(vtype).select_option(label=ROW["vehicle_type"])
    page.get_by_label(src).select_option(label=ROW["from_state"])
    page.get_by_label(dst).select_option(label=ROW["to_state"])
    page.get_by_label(mobile).fill(ROW["mobile"])
    if level < 2:
        page.get_by_label("Entry date").fill(ROW["entry_date"])
        page.get_by_label(ROW["tax_period"]).check()
    else:
        y, m, d = ROW["entry_date"].split("-")
        page.get_by_label("Day").select_option(d)
        page.get_by_label("Month").select_option(m)
        page.get_by_label("Year").select_option(y)
        page.get_by_label("Permit Validity").select_option(label=ROW["tax_period"])
    page.get_by_role("checkbox").check()
    page.get_by_role("button", name="Calculate Tax" if level == 0 else "Compute Payable Amount").click()
    if level == 3:
        page.get_by_role("button", name="Continue").click()

    page.get_by_role("link", name="Proceed to Pay").click()
    page.get_by_role("button", name="Pay Now (Demo)").click()


def v1_script(page):
    """A brittle script written against the original (level 0) site."""
    page.goto("/portal/login")
    page.fill("#username", config.PORTAL_USER)
    page.fill("#password", config.PORTAL_PASSWORD)
    page.click("#login_btn")
    page.click("#tile_tax")
    page.fill("#veh_no", ROW["veh_no"])
    page.fill("#owner_name", ROW["owner_name"])
    page.select_option("#vehicle_type", ROW["vehicle_type"])
    page.select_option("#from_state", ROW["from_state"])
    page.select_option("#to_state", ROW["to_state"])
    page.fill("#entry_date", ROW["entry_date"])
    page.check("#tax_period_7")
    page.fill("#mobile", ROW["mobile"])
    page.check("#declaration")
    page.click("#calc_btn")
    page.click("#proceed_btn")
    page.click("#pay_btn")


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_flow_completes_at_every_level(page, base_url, level):
    set_drift(base_url, level)
    fill_like_a_human(page, level)
    assert page.get_by_role("heading", name="Payment Successful").is_visible()
    assert re.fullmatch(r"DTP-\d{4}-\d{6}", page.locator("td strong").first.inner_text())
    assert "D$ 3,925.00" in page.content()  # Bus 650/day x 6 (7-day pass) + 25 fee


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_v1_locators_break_under_drift(page, base_url, level):
    set_drift(base_url, level)
    if level == 0:
        v1_script(page)
        assert page.get_by_role("heading", name="Payment Successful").is_visible()
    else:
        with pytest.raises(PlaywrightTimeout):
            v1_script(page)


def test_invalid_form_shows_errors(page, base_url):
    set_drift(base_url, 0)
    page.goto("/portal/login")
    page.fill("#username", config.PORTAL_USER)
    page.fill("#password", config.PORTAL_PASSWORD)
    page.click("#login_btn")
    page.goto("/portal/tax/new")
    page.fill("#veh_no", "bad")
    page.click("#calc_btn")
    assert page.get_by_role("alert").is_visible()
    assert page.get_by_text("Enter a valid registration number").is_visible()
    assert page.locator("#veh_no").input_value() == "BAD"


def test_generated_rows_pass_portal_validation():
    import gen_data
    import portal

    periods = {text: key for key, text in portal.TAX_PERIODS.items()}
    for row in gen_data.generate(200, seed=1):
        data = {**row, "veh_no": row["vehicle_no"], "tax_period": periods[row["tax_period"]], "declaration": True}
        assert portal.validate(data) == {}, row
