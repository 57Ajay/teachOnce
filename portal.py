"""Demoland TransitPass Portal: a fictional government-style e-service used as the demo target.

A layout is a set of independent changes (traits). Levels 0-3 are fixed redesigns; level 4 is a random mix
drawn from a seed, so the healer meets redesigns nobody wrote down in advance.
"""
import hashlib
import itertools
import random
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

LABELS = {
    "plain": {"veh_no": "Vehicle registration number", "owner_name": "Owner name", "vehicle_type": "Vehicle type",
              "from_state": "From state", "to_state": "To state", "entry_date": "Entry date",
              "tax_period": "Tax period", "mobile": "Mobile number", "email": "Email (optional)",
              "purpose": "Purpose of travel"},
    "formal": {"veh_no": "Registration No. of Vehicle", "owner_name": "Name of Registered Owner",
               "vehicle_type": "Vehicle Category", "from_state": "State of Origin", "to_state": "Destination State",
               "entry_date": "Date of Entry", "tax_period": "Permit Validity", "mobile": "Contact Mobile No.",
               "email": "E-mail Address (optional)", "purpose": "Purpose of Journey"},
    "casual": {"veh_no": "Vehicle number", "owner_name": "Owner's full name", "vehicle_type": "Type of vehicle",
               "from_state": "Travelling from", "to_state": "Travelling to", "entry_date": "Date you'll enter",
               "tax_period": "Pass length", "mobile": "Phone number", "email": "Email for updates (optional)",
               "purpose": "Why are you travelling?"},
}
DECLARATION = {"plain": "I declare that the above details are correct.",
               "formal": "I hereby certify that the information furnished is true.",
               "casual": "Yes, these details are correct."}
NAV = {
    "plain": {"sign_in": "Sign in", "tile": "Pay Interstate Vehicle Tax", "proceed": "Proceed to Pay",
              "pay": "Pay Now (Demo)", "receipt_no": "Receipt No.", "notice": "Continue"},
    "alt": {"sign_in": "Log in", "tile": "Interstate tax payment", "proceed": "Continue to payment",
            "pay": "Confirm payment (Demo)", "receipt_no": "Reference number", "notice": "I understand"},
}
PURPOSES = ["Business", "Tourism", "Goods delivery", "Other"]
SECTIONS = [
    ("Vehicle details", ["veh_no", "owner_name", "vehicle_type"]),
    ("Journey details", ["from_state", "to_state", "entry_date", "tax_period", "purpose"]),
    ("Contact details", ["mobile", "email"]),
]
FORM_KEYS = ["veh_no", "owner_name", "vehicle_type", "from_state", "to_state", "entry_date", "tax_period", "mobile"]
SHUFFLED = ["mobile", "from_state", "veh_no", "tax_period", "owner_name", "to_state", "entry_date", "vehicle_type"]
SUBMIT_LABELS = ["Calculate Tax", "Compute Payable Amount", "Get amount due", "Calculate payable tax"]

LEVEL0 = dict(rename=False, labels="plain", order=None, submit="Calculate Tax", submit_top=False, date="native",
              vehicle_type="select", states="select", tax_period="radio", declaration="checkbox", mobile=True,
              email=False, wizard=False, popup=False, consent=False, notice=False, nav="plain")
LEVEL1 = LEVEL0 | dict(rename=True, order=SHUFFLED, submit="Compute Payable Amount", submit_top=True)
LEVEL2 = LEVEL1 | dict(labels="formal", date="dmy", tax_period="select")
LEVELS = [LEVEL0, LEVEL1, LEVEL2, LEVEL2 | dict(consent=True, notice=True)]


def random_traits(seed: int) -> dict:
    rng = random.Random(seed)
    chance = lambda p: rng.random() < p
    return dict(
        rename=True, labels=rng.choice(list(LABELS)), order=rng.sample(FORM_KEYS, len(FORM_KEYS)) if chance(.6) else None,
        submit=rng.choice(SUBMIT_LABELS), submit_top=chance(.5), date=rng.choice(["native", "dmy", "text"]),
        vehicle_type=rng.choice(["select", "radio", "custom"]), states=rng.choice(["select", "custom"]),
        tax_period=rng.choice(["radio", "select", "custom"]), declaration=rng.choice(["checkbox", "switch"]),
        mobile=chance(.75), email=chance(.3), wizard=chance(.35), popup=chance(.3), consent=chance(.4),
        notice=chance(.3), nav=rng.choice(list(NAV)))


def layout(key: str) -> dict:
    """Traits of a layout key: v0-v3 (fixed levels) or r<seed> (random), plus "+f" for the extra required field."""
    base, _, extra = key.partition("+")
    traits = LEVELS[int(base[1:])] if base[0] == "v" else random_traits(int(base[1:]))
    return {**traits, "key": key, "salt": "" if base[0] == "v" else base, "extra_field": extra == "f"}


def changes(L: dict) -> list[str]:
    """What differs from the original site, for people reading the dashboard or benchmark."""
    out = [f"{k}: {v}" for k, v in L.items() if k in LEVEL0 and k != "order" and v != LEVEL0[k]]
    if L["order"]:
        out.append("fields reordered")
    if L["extra_field"]:
        out.append("new required field")
    return out


DRIFT = {"level": 0, "seed": None, "extra_field": False, "blocked": False}
SESSIONS: dict[str, dict] = {}
RECEIPTS: dict[str, dict] = {}
_receipt_seq = itertools.count(123)

templates = Jinja2Templates(directory=config.ROOT / "templates")


def set_drift_from_query(drift: int | None = None):
    if drift is not None:
        DRIFT.update(level=max(0, min(3, drift)), seed=None)


def current() -> dict:
    base = f"v{DRIFT['level']}" if DRIFT["level"] < 4 else f"r{DRIFT['seed']}"
    return layout(base + ("+f" if DRIFT["extra_field"] else ""))


router = APIRouter(prefix="/portal", dependencies=[Depends(set_drift_from_query)])


def alias(name: str, L: dict) -> str:
    """id/name/class used in the HTML. Renamed in redesigned layouts."""
    return name if not L["rename"] else "k" + hashlib.sha1((L["salt"] + name).encode()).hexdigest()[:6]


def session(request: Request) -> dict | None:
    return SESSIONS.get(request.cookies.get("dtp_session", ""))


def render(request: Request, name: str, L: dict | None = None, **ctx) -> HTMLResponse:
    """L is the layout to render; a form re-shown with errors keeps the layout it was submitted with."""
    L = L or current()
    sess = session(request)
    ctx.update(L=L, c=lambda n: alias(n, L), nav=NAV[L["nav"]], user=sess and sess.get("user"),
               show_consent=current()["consent"] and request.cookies.get("dtp_consent") != "1")
    if DRIFT["blocked"]:
        return templates.TemplateResponse(request, "portal/blocked.html", ctx | {"title": "Access blocked", "user": None},
                                          status_code=403)
    return templates.TemplateResponse(request, f"portal/{name}", ctx)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def compute_tax(vehicle_type: str, tax_period: str) -> int:
    return DAILY_RATE[vehicle_type] * PERIOD_FACTOR[tax_period] + SERVICE_FEE


def read_form(form, L: dict) -> dict:
    get = lambda key: str(form.get(alias(key, L), "")).strip()
    data = {key: get(key) for key in FORM_KEYS + ["purpose"]}
    data["veh_no"] = data["veh_no"].upper().replace(" ", "")
    if L["date"] == "dmy":
        d, m, y = get("entry_date_d"), get("entry_date_m"), get("entry_date_y")
        data["entry_date"] = f"{y}-{m}-{d}" if d and m and y else ""
    elif L["date"] == "text":
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", data["entry_date"])
        data["entry_date"] = f"{m[3]}-{m[2]}-{m[1]}" if m else ""
    data["declaration"] = get("declaration") == "on"
    return data


def validate(data: dict, L: dict = LEVEL0 | {"extra_field": False}) -> dict:
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
        errors["entry_date"] = "Enter the date as DD/MM/YYYY." if L["date"] == "text" else "Enter a valid entry date."
    if data["tax_period"] not in TAX_PERIODS:
        errors["tax_period"] = "Select a tax period."
    if L["mobile"] and not MOBILE.match(data["mobile"]):
        errors["mobile"] = "Enter a 10-digit mobile number."
    if L["extra_field"] and data.get("purpose") not in PURPOSES:
        errors["purpose"] = "Select the purpose of travel."
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
    L = layout(form.get("_layout", "v0"))
    user, password = form.get(alias("username", L)), form.get(alias("password", L))
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


@router.get("/dashboard")
def dashboard(request: Request):
    if not session(request):
        return redirect("/portal/login")
    return render(request, "dashboard.html", title="Dashboard")


def form_context(L: dict, values: dict, errors: dict) -> dict:
    present = {"mobile": L["mobile"], "email": L["email"], "purpose": L["extra_field"]}
    keep = lambda keys: [k for k in keys if present.get(k, True)]
    if L["order"]:
        sections = [("Application details", keep(L["order"] + ["purpose", "email"]))]
    else:
        sections = [(title, keep(keys)) for title, keys in SECTIONS if keep(keys)]
    pages = [sections]
    if L["wizard"] and not errors:  # two steps with a Next button; a form shown with errors is one page
        if L["order"]:
            keys = sections[0][1]
            pages = [[("Application details", keys[:3])], [("Application details (continued)", keys[3:])]]
        else:
            pages = [sections[:1], sections[1:]]
    widgets = {"entry_date": f"date_{L['date']}", "vehicle_type": L["vehicle_type"], "from_state": L["states"],
               "to_state": L["states"], "tax_period": L["tax_period"], "purpose": "select"}
    options = {"vehicle_type": [(v, v) for v in VEHICLE_TYPES], "from_state": [(s, s) for s in STATES],
               "to_state": [(s, s) for s in STATES], "tax_period": list(TAX_PERIODS.items()),
               "purpose": [(p, p) for p in PURPOSES]}
    return dict(title="Pay Interstate Vehicle Tax", labels=LABELS[L["labels"]], declaration=DECLARATION[L["labels"]],
                widgets=widgets, options=options, pages=pages, values=values, errors=errors,
                years=[str(date.today().year), str(date.today().year + 1)])


@router.get("/tax/new")
def tax_form(request: Request):
    sess = session(request)
    if not sess:
        return redirect("/portal/login")
    L = current()
    return render(request, "tax_new.html", L, **form_context(L, sess.get("draft", {}), {}),
                  show_popup=L["popup"] and request.cookies.get("dtp_news") != "1")


@router.post("/tax/new")
async def tax_submit(request: Request):
    sess = session(request)
    if not sess:
        return redirect("/portal/login")
    form = await request.form()
    L = layout(form.get("_layout", "v0"))
    data = read_form(form, L)
    errors = validate(data, L)
    if errors:
        return render(request, "tax_new.html", L, **form_context(L, data, errors), show_popup=False)
    sess["draft"] = data
    return redirect("/portal/tax/notice" if current()["notice"] else "/portal/tax/review")


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
    level: int | None = None  # 0-3 fixed redesigns, 4 = random (a new seed unless one is given)
    seed: int | None = None
    extra_field: bool | None = None
    blocked: bool | None = None


@router.get("/admin/drift")
def get_drift():
    L = current()
    return DRIFT | {"layout": L["key"], "changes": changes(L)}


@router.post("/admin/drift")
def post_drift(body: DriftIn):
    if body.seed is not None or body.level == 4:
        DRIFT.update(level=4, seed=body.seed if body.seed is not None else secrets.randbelow(1_000_000))
    elif body.level is not None:
        DRIFT.update(level=max(0, min(3, body.level)), seed=None)
    for flag in ("extra_field", "blocked"):
        if getattr(body, flag) is not None:
            DRIFT[flag] = getattr(body, flag)
    return get_drift()
