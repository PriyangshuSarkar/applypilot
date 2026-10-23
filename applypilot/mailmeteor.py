"""Email lookup from a LinkedIn profile URL via Mailmeteor's free LinkedIn Email Finder.

Lookups are throttled, capped per run, and stop on any sign of a block (never retry or bypass).
All page selectors and result parsing live here.
"""
import random
import re
import time

from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from applypilot.config import Mailmeteor
from applypilot.scrape import EMAIL
from applypilot.store import Store

URL = "https://mailmeteor.com/tools/linkedin-email-finder"
STATUSES = {"valid", "risky"}  # "unknown" / anything else is saved but never emailed
BLOCKED = re.compile(r"too many|rate.?limit|try again later|unusual|blocked|captcha|error code|something went wrong|quota", re.I)


class Blocked(RuntimeError):
    """Mailmeteor refused or errored; stop looking up emails for this run."""


class Gate:
    """A timer, not a sleep: `wait()` blocks only if called before the previous call's gap has run out."""

    def __init__(self, delay: tuple[float, float], clock=time.monotonic, sleep=time.sleep):
        self.delay, self.clock, self.sleep = delay, clock, sleep
        self.ready_at = 0.0

    def wait(self, idle=None) -> None:
        """Block until the gap is over. While waiting, run `idle() -> bool` (useful work; False = none left)."""
        while (left := self.ready_at - self.clock()) > 0:
            if not (idle and idle()):
                self.sleep(left)
                break
        self.ready_at = self.clock() + random.uniform(*self.delay)


def parse_result(text: str) -> dict:
    """Read the result block between the form button and the 'Example:' hint.
    -> {"email", "status": valid|risky|unknown|none, "name"}; raises Blocked on an error/limit message."""
    after = text.split("FIND EMAIL", 1)[-1]
    block = after.split("Example:", 1)[0]
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    m = EMAIL.search(block)
    if not m:
        if BLOCKED.search(block):
            raise Blocked(" ".join(lines)[:200])
        return {"email": None, "status": "none", "name": None}
    i = next(i for i, l in enumerate(lines) if m.group(0) in l)
    status = lines[i - 1].lower() if i >= 1 else "unknown"
    name = lines[i - 2] if i >= 2 else None
    if status not in STATUSES:
        status = "unknown"
    return {"email": m.group(0).lower(), "status": status, "name": name}


def find_email(page: Page, linkedin_url: str, timeout_s: int = 40) -> dict:
    try:
        page.goto(URL)
        page.wait_for_selector("#linkedin-url")
        box = page.locator("#linkedin-url")
        box.click()
        box.fill("")
        box.press_sequentially(linkedin_url, delay=random.randint(40, 80))
        time.sleep(random.uniform(0.3, 0.5))
        page.get_by_role("button", name="FIND EMAIL").click()
    except PlaywrightError as e:  # aborted load / missing form: the site is refusing us, so stop (no retry)
        raise Blocked(f"page error: {str(e).splitlines()[0][:150]}")
    # wait for the result (email, "No results" or an error), not for a fixed time; timeout_s is only a hang guard
    try:
        page.wait_for_function(
            """([email, blocked]) => {
              const block = document.body.innerText.split('FIND EMAIL').pop().split('Example:')[0];
              if (block.includes('Searching')) return false;
              return new RegExp(email).test(block) || block.includes('No results') || new RegExp(blocked, 'i').test(block);
            }""",
            arg=[EMAIL.pattern, BLOCKED.pattern], timeout=timeout_s * 1000)
    except PlaywrightTimeout:
        raise Blocked("no result before timeout")
    return parse_result(page.inner_text("body"))


class Finder:
    """Looks up contacts' emails, cached by LinkedIn URL in the store, capped per run.
    Each live lookup opens its own Mailmeteor tab and closes it again."""

    def __init__(self, ctx: BrowserContext, store: Store, cfg: Mailmeteor):
        self.ctx, self.store, self.cfg = ctx, store, cfg
        self.used = 0
        self.gate = Gate(cfg.delay_seconds)
        self.idle = None  # work to do while waiting for the gate (e.g. scraping the next job)

    def lookup(self, contact: dict) -> bool:
        """Fill contact['email'] / ['email_status']. True if a live lookup was made (not a cache hit or skip)."""
        url = contact.get("linkedin_url")
        if contact.get("email") or not url:
            return False
        cached = self.store.get_lookup(url)
        if cached:
            contact["email"], contact["email_status"] = cached
            return False
        if self.cfg.max_lookups_per_run is not None and self.used >= self.cfg.max_lookups_per_run:
            raise Blocked(f"per-run lookup cap reached ({self.cfg.max_lookups_per_run})")
        self.gate.wait(self.idle)  # blocks only if the previous lookup started less than the gap ago
        page = self.ctx.new_page()
        try:
            res = find_email(page, url)
        finally:
            page.close()
        self.used += 1
        email = res["email"] if res["status"] in STATUSES else None
        self.store.save_lookup(url, email, res["status"])
        contact["email"], contact["email_status"] = email, res["status"]
        return True
