"""Read-only LinkedIn + GetProspect scraping. All DOM selectors live here so breakage stays local."""
import random
import re

import httpx
from playwright.sync_api import BrowserContext, Page

from applypilot.config import Config
from applypilot.filters import contact_tier, pick_for_reveal

EXT_ID = "bhbcbkonalnjkflmdkdodieehnmmeknp"  # Email Finder - GetProspect
CARD = '[componentkey^="job-card-component-ref-"]'


class Checkpoint(RuntimeError):
    """LinkedIn showed a login/captcha/security wall; stop immediately, never bypass."""


def pause(lo: float = 2.5, hi: float = 6.0) -> None:
    import time

    time.sleep(random.uniform(lo, hi))


def guard(page: Page) -> None:
    if re.search(r"checkpoint|authwall|/login|captcha", page.url):
        raise Checkpoint(page.url)


def collect_job_ids(page: Page, limit: int) -> list[str]:
    """Scroll the virtualized results list and gather job ids until we have `limit`."""
    ids: list[str] = []
    for _ in range(15):
        found = page.eval_on_selector_all(CARD, "els=>els.map(e=>e.getAttribute('componentkey').split('-').pop())")
        ids += [i for i in dict.fromkeys(found) if i not in ids]
        if len(ids) >= limit:
            break
        last = page.query_selector_all(CARD)[-1]
        last.scroll_into_view_if_needed()
        page.mouse.wheel(0, 1500)
        pause(1.5, 3)
    return ids[:limit]


def read_job(page: Page, job_id: str) -> dict:
    page.goto(f"https://www.linkedin.com/jobs/view/{job_id}/")
    page.wait_for_timeout(4000)
    guard(page)
    data = page.evaluate(
        """()=>{
          const box=document.querySelector('[data-testid=expandable-text-box]');
          const jd=box?box.innerText.trim():null;
          const c=[...document.querySelectorAll('a[href*="/company/"]')].map(a=>a.href).find(Boolean);
          return {title:document.title, jd, company_href:c||null};
        }"""
    )
    parts = [p.strip() for p in data["title"].split("|")]
    m = re.match(r"(https://www\.linkedin\.com/company/[^/?]+)", data["company_href"] or "")
    return {
        "job_id": job_id,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "title": parts[0] if parts else "",
        "company": parts[1] if len(parts) > 2 else "",
        "company_url": (m.group(1) + "/") if m else None,
        "jd": clean_jd(data["jd"]),
    }


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CSS_RULE = re.compile(r"[\w\s,.#>:-]+\{\s*[\w-]+\s*:[^{}]*\}")


def clean_jd(text: str | None) -> str | None:
    """LinkedIn sometimes leaks a <style> block into the description text; drop CSS rules."""
    if not text:
        return text
    return re.sub(r"\s*(?:…|\.\.\.)\s*more\s*$", "", CSS_RULE.sub("", text).strip())


def _sidepanel_urls() -> list[str]:
    return [t["url"] for t in httpx.get("http://127.0.0.1:9222/json").json()
            if "sidepanel.html" in t["url"] and EXT_ID in t["url"]]


def open_panel(ctx: BrowserContext, page: Page, company: str) -> Page | None:
    """Open the GetProspect panel for `page`'s tab and verify it shows `company`. None if it can't be verified."""
    before = set(_sidepanel_urls())
    page.bring_to_front()
    page.click("#gp-open-panel-button")
    url = None
    for _ in range(20):  # a fresh tab gets a fresh tabId; never reuse a stale panel
        new = [u for u in _sidepanel_urls() if u not in before]
        if new:
            url = new[-1]
            break
        page.wait_for_timeout(500)
    if not url:
        return None
    panel = ctx.new_page()
    panel.set_viewport_size({"width": 420, "height": 900})
    panel.goto(url)
    panel.wait_for_timeout(4000)
    panel.get_by_role("button", name="View employees").click()
    panel.wait_for_timeout(7000)
    if company.lower() not in panel.inner_text("body")[:500].lower():
        panel.close()
        return None
    return panel


def parse_contacts(text: str) -> list[dict]:
    """Parse the side panel's employee list text: name / location / headline [/ Reveal and save | email]."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if "Select all" in lines:
        i = lines.index("Select all") + 1
        lines = lines[i + 1 :] if i < len(lines) and re.fullmatch(r"\d+ selected", lines[i]) else lines[i:]
    out, i = [], 0
    while i + 2 < len(lines):
        name, loc, headline = lines[i : i + 3]
        i += 3
        revealed, email = None, None
        if i < len(lines) and lines[i] == "Reveal and save":
            revealed, i = False, i + 1
        elif i < len(lines) and EMAIL.fullmatch(lines[i]):
            revealed, email, i = True, lines[i].lower(), i + 1
        out.append({"name": name, "location": loc, "headline": headline, "email": email, "revealed": revealed})
    return out


STOP_WORDS = re.compile(r"out of credits|no credits|upgrade|limit reached|not enough credits", re.I)


def reveal_contacts(panel: Page, targets: list[dict]) -> tuple[int, str | None]:
    """Click 'Reveal and save' on each target contact's own row. Spends GetProspect credits."""
    done = 0
    for c in targets:
        if c["revealed"] is not False:  # already revealed (or nothing to reveal)
            continue
        row = panel.get_by_text(c["name"], exact=True).first.locator(
            "xpath=ancestor::*[.//button[normalize-space()='Reveal and save']][1]"
        )
        button = row.get_by_role("button", name="Reveal and save")
        if button.count() != 1:  # ambiguous row: never guess, never spend on the wrong person
            continue
        total = panel.get_by_role("button", name="Reveal and save").count()
        button.click()
        for _ in range(16):
            panel.wait_for_timeout(500)
            if panel.get_by_role("button", name="Reveal and save").count() < total:
                break
        else:
            return done, "reveal did not complete"
        done += 1
        if STOP_WORDS.search(panel.inner_text("body")):
            return done, "credit/plan limit message"
        pause(0.8, 2)
    return done, None


def read_company_contacts(ctx: BrowserContext, company_url: str, company: str, reveal: bool = False,
                          cap: int | None = 3, max_scrolls: int = 8) -> dict:
    page = ctx.new_page()
    try:
        page.goto(company_url)
        page.wait_for_timeout(5000)
        guard(page)
        panel = open_panel(ctx, page, company)
        if panel is None:
            return {"contacts": [], "revealed_now": 0, "note": "panel could not be verified for this company"}
        try:
            prev, stalls = -1, 0
            for _ in range(max_scrolls):  # lazy-loaded list; stop after two loads that add nothing
                n = len(parse_contacts(panel.inner_text("body")))
                stalls = stalls + 1 if n == prev else 0
                if stalls >= 2:
                    break
                prev = n
                panel.mouse.move(200, 500)
                panel.mouse.wheel(0, 4000)
                panel.wait_for_timeout(3500)
            revealed_now, note = 0, None
            if reveal:
                revealed_now, note = reveal_contacts(panel, pick_for_reveal(parse_contacts(panel.inner_text("body")), cap))
            contacts = parse_contacts(panel.inner_text("body"))
            picked = {c["name"] for c in pick_for_reveal(contacts, cap)}
            for c in contacts:
                c["tier"] = contact_tier(c["headline"])
                c["selected"] = c["name"] in picked
            return {"contacts": contacts, "revealed_now": revealed_now, "note": note}
        finally:
            panel.close()
    finally:
        page.close()
        pause()
