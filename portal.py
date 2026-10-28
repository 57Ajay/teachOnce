"""Demoland TransitPass Portal: a fictional government-style e-service used as the demo target."""
import hashlib
import itertools
import re
import secrets
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import config

STATES = ["Northvale", "Eastmarch", "Southreach", "Westholm", "Midland"]
STATE_CODES = {"Northvale": "NV", "Eastmarch": "EM", "Southreach": "SR", "Westholm": "WH", "Midland": "MD"}
VEHICLE_TYPES = ["Car", "Taxi", "Bus", "Goods"]
TAX_PERIODS = {"1": "1 day", "7": "7 days", "30": "30 days"}
DAILY_RATE = {"Car": 150, "Taxi": 220, "Bus": 650, "Goods": 480}
PERIOD_FACTOR = {"1": 1, "7": 6, "30": 20}
SERVICE_FEE = 25
REG_NO = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$")
MOBILE = re.compile(r"^[6-9]\d{9}$")

# key, label (levels 0-1), label (levels 2-3), widget
FIELDS = [
    ("veh_no", "Vehicle registration number", "Registration No. of Vehicle", "text"),
    ("owner_name", "Owner name", "Name of Registered Owner", "text"),
    ("vehicle_type", "Vehicle type", "Vehicle Category", "select"),
    ("from_state", "From state", "State of Origin", "select"),
    ("to_state", "To state", "Destination State", "select"),
    ("entry_date", "Entry date", "Date of Entry", "date"),
    ("tax_period", "Tax period", "Permit Validity", "radio"),
    ("mobile", "Mobile number", "Contact Mobile No.", "text"),
]
SECTIONS = [
    ("Vehicle details", ["veh_no", "owner_name", "vehicle_type"]),
    ("Journey details", ["from_state", "to_state", "entry_date", "tax_period"]),
    ("Contact details", ["mobile"]),
]
SHUFFLED = ["mobile", "from_state", "veh_no", "tax_period", "owner_name", "to_state", "entry_date", "vehicle_type"]

DRIFT = {"level": 0}
SESSIONS: dict[str, dict] = {}
RECEIPTS: dict[str, dict] = {}
_receipt_seq = itertools.count(123)

templates = Jinja2Templates(directory=config.ROOT / "templates")


def set_drift_from_query(drift: int | None = None):
    if drift is not None:
        DRIFT["level"] = max(0, min(3, drift))


router = APIRouter(prefix="/portal", dependencies=[Depends(set_drift_from_query)])


def alias(name: str, level: int) -> str:
    """id/name/class used in the HTML. Renamed from drift level 1 on."""
    return name if level == 0 else "k" + hashlib.sha1(name.encode()).hexdigest()[:6]


def session(request: Request) -> dict | None:
    return SESSIONS.get(request.cookies.get("dtp_session", ""))


def render(request: Request, name: str, level: int | None = None, **ctx) -> HTMLResponse:
    level = DRIFT["level"] if level is None else level
    sess = session(request)
    ctx.update(
        level=level,
        c=lambda n: alias(n, level),
        user=sess and sess.get("user"),
        show_consent=DRIFT["level"] == 3 and request.cookies.get("dtp_consent") != "1",
        path=request.url.path,
    )
    return templates.TemplateResponse(request, f"portal/{name}", ctx)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def compute_tax(vehicle_type: str, tax_period: str) -> int:
    return DAILY_RATE[vehicle_type] * PERIOD_FACTOR[tax_period] + SERVICE_FEE


def read_form(form, level: int) -> dict:
    get = lambda key: str(form.get(alias(key, level), "")).strip()
    data = {key: get(key) for key, *_ in FIELDS}
    data["veh_no"] = data["veh_no"].upper().replace(" ", "")
    if level >= 2:
        d, m, y = get("entry_date_d"), get("entry_date_m"), get("entry_date_y")
        data["entry_date"] = f"{y}-{m}-{d}" if d and m and y else ""
    data["declaration"] = get("declaration") == "on"
    return data


def validate(data: dict) -> dict:
    errors = {}
    if not REG_NO.match(data["veh_no"]):
        errors["veh_no"] = "Enter a valid registration number, e.g. NV07AB1234."
    if len(data["owner_name"]) < 2:
        errors["owner_name"] = "Enter the owner's name."
    if data["vehicle_type"] not in VEHICLE_TYPES:
        errors["vehicle_type"] = "Select a vehicle type."
    if data["from_state"] not in STATES:
        errors["from_state"] = "Select the state of origin."
    if data["to_state"] not in STATES:
        errors["to_state"] = "Select the destination state."
    elif data["to_state"] == data["from_state"]:
        errors["to_state"] = "Destination must differ from the state of origin."
    try:
        date.fromisoformat(data["entry_date"])
    except ValueError:
        errors["entry_date"] = "Enter a valid entry date."
    if data["tax_period"] not in TAX_PERIODS:
        errors["tax_period"] = "Select a tax period."
    if not MOBILE.match(data["mobile"]):
        errors["mobile"] = "Enter a 10-digit mobile number."
    if not data["declaration"]:
        errors["declaration"] = "You must accept the declaration."
    return errors


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", title="Sign in", demo_user=config.PORTAL_USER,
                  demo_password=config.PORTAL_PASSWORD)


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    level = int(form.get("_layout", 0))
    user, password = form.get(alias("username", level)), form.get(alias("password", level))
    if user != config.PORTAL_USER or password != config.PORTAL_PASSWORD:
        return render(request, "login.html", title="Sign in", error="Invalid username or password.",
                      demo_user=config.PORTAL_USER, demo_password=config.PORTAL_PASSWORD)
    token = secrets.token_urlsafe(16)
    SESSIONS[token] = {"user": user}
    response = redirect("/portal/dashboard")
    response.set_cookie("dtp_session", token, httponly=True, samesite="lax")
    return response


@router.get("/logout")
def logout(request: Request):
    SESSIONS.pop(request.cookies.get("dtp_session", ""), None)
    response = redirect("/portal/login")
    response.delete_cookie("dtp_session")
    return response


@router.post("/consent")
async def consent(request: Request):
    form = await request.form()
    next_url = str(form.get("next", "/portal/login"))
    response = redirect(next_url if next_url.startswith("/portal/") else "/portal/login")
    response.set_cookie("dtp_consent", "1", samesite="lax")
    return response


@router.get("/dashboard")
def dashboard(request: Request):
    if not session(request):
        return redirect("/portal/login")
    return render(request, "dashboard.html", title="Dashboard")


def form_context(level: int, values: dict, errors: dict) -> dict:
    labels = {key: (l0 if level < 2 else l2) for key, l0, l2, _ in FIELDS}
    widgets = {key: w for key, _, _, w in FIELDS}
    if level >= 1:
        sections = [("Application details", SHUFFLED)]
    else:
        sections = SECTIONS
    return dict(title="Pay Interstate Vehicle Tax", labels=labels, widgets=widgets, sections=sections,
                values=values, errors=errors, states=STATES, vehicle_types=VEHICLE_TYPES,
                tax_periods=TAX_PERIODS, years=[str(date.today().year), str(date.today().year + 1)])


@router.get("/tax/new")
def tax_form(request: Request):
    sess = session(request)
    if not sess:
        return redirect("/portal/login")
    level = DRIFT["level"]
    return render(request, "tax_new.html", **form_context(level, sess.get("draft", {}), {}))


@router.post("/tax/new")
async def tax_submit(request: Request):
    sess = session(request)
    if not sess:
        return redirect("/portal/login")
    form = await request.form()
    level = int(form.get("_layout", 0))
    data = read_form(form, level)
    errors = validate(data)
    if errors:
        return render(request, "tax_new.html", level=level, **form_context(level, data, errors))
    sess["draft"] = data
    return redirect("/portal/tax/notice" if DRIFT["level"] == 3 else "/portal/tax/review")


@router.get("/tax/notice")
def tax_notice(request: Request):
    if not session(request):
        return redirect("/portal/login")
    return render(request, "notice.html", title="Session notice")


@router.get("/tax/review")
def tax_review(request: Request):
    sess = session(request)
    if not sess or not sess.get("draft"):
        return redirect("/portal/tax/new")
    draft = sess["draft"]
    return render(request, "review.html", title="Review", draft=draft, tax_periods=TAX_PERIODS,
                  amount=compute_tax(draft["vehicle_type"], draft["tax_period"]))


@router.get("/tax/pay")
def tax_pay_page(request: Request):
    sess = session(request)
    if not sess or not sess.get("draft"):
        return redirect("/portal/tax/new")
    draft = sess["draft"]
    return render(request, "pay.html", title="Payment", draft=draft,
                  amount=compute_tax(draft["vehicle_type"], draft["tax_period"]))


@router.post("/tax/pay")
def tax_pay(request: Request):
    sess = session(request)
    if not sess or not sess.get("draft"):
        return redirect("/portal/tax/new")
    draft = sess.pop("draft")
    receipt_no = f"DTP-{date.today().year}-{next(_receipt_seq):06d}"
    RECEIPTS[receipt_no] = {**draft, "receipt_no": receipt_no, "paid_on": date.today().isoformat(),
                            "amount": compute_tax(draft["vehicle_type"], draft["tax_period"])}
    return redirect(f"/portal/tax/receipt/{receipt_no}")


@router.get("/tax/receipt/{receipt_no}")
def tax_receipt(request: Request, receipt_no: str):
    if not session(request) or receipt_no not in RECEIPTS:
        return redirect("/portal/dashboard")
    return render(request, "receipt.html", title="Receipt", r=RECEIPTS[receipt_no], tax_periods=TAX_PERIODS)


class DriftIn(BaseModel):
    level: int


@router.get("/admin/drift")
def get_drift():
    return DRIFT


@router.post("/admin/drift")
def post_drift(body: DriftIn):
    set_drift_from_query(body.level)
    return DRIFT
