import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator as PwLocator
from playwright.sync_api import Page

from workflow import Locator, Target, render

POLL_MS = 150


def to_playwright(page: Page, loc: Locator, values: dict) -> PwLocator:
    r = lambda s: render(s, values) if s else s
    match loc.kind:
        case "role":
            return page.get_by_role(loc.role, name=r(loc.name)) if loc.name else page.get_by_role(loc.role)
        case "label":
            return page.get_by_label(r(loc.text))
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
