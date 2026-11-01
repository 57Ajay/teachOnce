import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator as PwLocator
from playwright.sync_api import Page

from workflow import Locator, Target, render

POLL_MS = 150
# Same set as describe.js FIELD.
FIELD_XPATH = ("self::input[not(@type='hidden' or @type='submit' or @type='button' or @type='reset' or @type='image')]"
               " or self::select or self::textarea or @role='combobox' or @role='textbox' or @role='switch'"
               " or @role='checkbox' or @role='radio' or @contenteditable='true'"
               " or (@tabindex='0' and not(self::a or self::button))")


def xpath_literal(s: str) -> str:
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in s.split("'")) + ")"


def near_label_xpath(text: str) -> str:
    """The fields in the smallest group around a label with this text (describe.js nearLabel, the other way round)."""
    names = " or ".join(f"normalize-space(.)={xpath_literal(t)}" for t in (text, f"{text} *", f"{text}*"))
    return f"xpath=//label[{names}]/ancestor-or-self::*[.//*[{FIELD_XPATH}]][1]//*[{FIELD_XPATH}]"


def by_label(page: Page, text: str) -> PwLocator:
    """The field linked to this label, else the one field grouped with it (sites that don't link labels)."""
    linked = page.get_by_label(text)
    try:
        if linked.count():
            return linked
    except PlaywrightError:  # page is navigating
        return linked
    return page.locator(near_label_xpath(text))


def to_playwright(page: Page, loc: Locator, values: dict) -> PwLocator:
    r = lambda s: render(s, values) if s else s
    match loc.kind:
        case "role":
            return page.get_by_role(loc.role, name=r(loc.name)) if loc.name else page.get_by_role(loc.role)
        case "label":
            return by_label(page, r(loc.text))
        case "placeholder":
            return page.get_by_placeholder(r(loc.text))
        case "text":
            return page.get_by_text(r(loc.text))
        case "css":
            return page.locator(r(loc.selector))


def usable(candidate: PwLocator) -> bool:
    try:
        return candidate.count() == 1 and candidate.is_visible() and candidate.is_enabled()
    except PlaywrightError:  # page is navigating
        return False


def resolve(page: Page, target: Target, values: dict, timeout_ms: int) -> PwLocator | None:
    """First locator in the chain that matches exactly one visible, enabled element. Polls until timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for loc in target.locators:
            candidate = to_playwright(page, loc, values)
            if usable(candidate):
                return candidate
        if time.monotonic() > deadline:
            return None
        page.wait_for_timeout(POLL_MS)
