"""Read-only LinkedIn + GetProspect scraping (employee listing only; emails come from mailmeteor.py). All DOM selectors live here so breakage stays local."""
import re

import httpx
from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from applypilot.config import Config
from applypilot.filters import contact_tier

EXT_ID = "bhbcbkonalnjkflmdkdodieehnmmeknp"  # Email Finder - GetProspect
ROW_LINK = 'a[aria-label$=" on LinkedIn"][href*="linkedin.com/in/"]'
CARD = '[componentkey^="job-card-component-ref-"]'


class Checkpoint(RuntimeError):
    """LinkedIn showed a login/captcha/security wall; stop immediately, never bypass."""


def wait_for(page: Page, selector: str, cap_ms: int = 15000) -> bool:
    """Wait for `selector` to appear; False if it never does (cap_ms is only a hang guard, not a delay)."""
    try:
        page.wait_for_selector(selector, timeout=cap_ms)
        return True
    except PlaywrightTimeout:
        return False


def wait_grows(page: Page, selector: str, count: int, cap_ms: int = 8000) -> bool:
    """Wait until more than `count` elements match `selector`; False if the list stopped growing."""
    try:
        page.wait_for_function("([sel, n]) => document.querySelectorAll(sel).length > n", arg=[selector, count],
                               timeout=cap_ms)
        return True
    except PlaywrightTimeout:
        return False


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
        cards = page.query_selector_all(CARD)
        if not cards:  # page re-rendered (LinkedIn redirects the search URL); wait for the cards to come back
            if not wait_for(page, CARD):
                break
            continue
        last_key = cards[-1].get_attribute("componentkey")
        cards[-1].scroll_into_view_if_needed()
        page.mouse.wheel(0, 1500)
        try:  # the list is virtualized (card count stays flat), so wait for the last card to change
            page.wait_for_function("([sel, k]) => { const e = [...document.querySelectorAll(sel)].pop(); "
                                   "return e && e.getAttribute('componentkey') !== k; }",
                                   arg=[CARD, last_key], timeout=5000)
        except PlaywrightTimeout:
            break  # nothing new loaded
    return ids[:limit]


def read_job(page: Page, job_id: str) -> dict:
    page.goto(f"https://www.linkedin.com/jobs/view/{job_id}/")
    wait_for(page, "[data-testid=expandable-text-box]")
    guard(page)
    data = page.evaluate(
        """()=>{
          const box=document.querySelector('[data-testid=expandable-text-box]');
          const jd=box?box.innerText.trim():null;
          const c=[...document.querySelectorAll('a[href*="/company/"]')].map(a=>a.href).find(Boolean);
          // "Meet the hiring team": climb from the heading to the nearest container holding profile links
          const h=[...document.querySelectorAll('h1,h2,h3,h4,p,span,div')]
            .find(e=>e.children.length===0 && /meet the hiring team/i.test(e.textContent));
          let node=h, team=[];
          for(let i=0;i<6&&node;i++){
            node=node.parentElement;
            team=node?[...node.querySelectorAll('a[href*="/in/"]')].map(a=>({href:a.href,text:a.innerText})):[];
            if(team.length) break;
          }
          return {title:document.title, jd, company_href:c||null, team};
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
        "hiring_team": parse_hiring_team(data["team"]),
    }


HIRING_NOISE = re.compile(r"[·•]|[·•]?\s*\d+(?:st|nd|rd|th)\+?|job poster|hiring team|message|.*connection.*|view .*profile", re.I)
PROFILE = re.compile(r"https://[\w.]+/in/[^/?#]+")


def parse_hiring_team(rows: list[dict]) -> list[dict]:
    """'Meet the hiring team' links ({href, text}; a person has an image link and a name link) -> contacts.
    They get tier 0 (the poster of a job is the best person to write to) and source 'job_post'."""
    best: dict[str, list[str]] = {}
    for r in rows:
        m = PROFILE.match(r.get("href") or "")
        lines = [l.strip() for l in (r.get("text") or "").splitlines()]
        lines = [l for l in lines if l and not HIRING_NOISE.fullmatch(l)]
        if m and lines and len(lines) > len(best.get(m.group(0), [])):
            best[m.group(0)] = lines
    return [{"name": l[0], "location": "", "headline": l[1] if len(l) > 1 else "", "email": None,
             "linkedin_url": url + "/", "tier": 0, "selected": False, "source": "job_post"}
            for url, l in best.items()]


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
    for _ in range(100):  # a fresh tab gets a fresh tabId; never reuse a stale panel
        new = [u for u in _sidepanel_urls() if u not in before]
        if new:
            url = new[-1]
            break
        page.wait_for_timeout(100)  # polling the debug endpoint, not a delay
    if not url:
        return None
    panel = ctx.new_page()
    panel.set_viewport_size({"width": 420, "height": 900})
    panel.goto(url)
    try:
        panel.get_by_role("button", name="View employees").click(timeout=15000)
    except PlaywrightTimeout:
        panel.close()
        return None
    wait_for(panel, ROW_LINK)
    if company.lower() not in panel.inner_text("body")[:500].lower():
        panel.close()
        return None
    return panel


def parse_contacts(text: str) -> list[dict]:
    """Parse the side panel's employee list text: name / location / headline [/ 'Reveal and save' | email].
    The 'Reveal and save' button text is ignored (we never click it); an email is kept if the panel already shows one."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if "Select all" in lines:
        i = lines.index("Select all") + 1
        lines = lines[i + 1 :] if i < len(lines) and re.fullmatch(r"\d+ selected", lines[i]) else lines[i:]
    out, i = [], 0
    while i + 2 < len(lines):
        name, loc, headline = lines[i : i + 3]
        i += 3
        email = None
        if i < len(lines) and lines[i] == "Reveal and save":
            i += 1
        elif i < len(lines) and EMAIL.fullmatch(lines[i]):
            email, i = lines[i].lower(), i + 1
        out.append({"name": name, "location": loc, "headline": headline, "email": email})
    return out


def panel_linkedin_urls(panel: Page) -> dict[str, str]:
    """Employee name -> LinkedIn profile URL, from the row links (aria-label '<name> on LinkedIn')."""
    pairs = panel.eval_on_selector_all(
        ROW_LINK,
        "els=>els.map(e=>[e.getAttribute('aria-label').slice(0,-' on LinkedIn'.length), e.href])",
    )
    return {name: href for name, href in pairs}


def read_company_contacts(ctx: BrowserContext, company_url: str, company: str, resolve=None,
                          max_scrolls: int = 8) -> dict:
    """List a company's employees from the GetProspect panel (free: no credits spent) with their LinkedIn URLs.
    The list lazy-loads, so `resolve(new_contacts) -> bool` is called as each batch appears (the caller looks up
    emails right then); returning True stops scrolling. Without `resolve` the whole list is read."""
    page = ctx.new_page()
    try:
        page.goto(company_url)
        wait_for(page, "#gp-open-panel-button")
        guard(page)
        panel = open_panel(ctx, page, company)
        if panel is None:
            return {"contacts": [], "note": "panel could not be verified for this company"}
        try:
            seen: dict[str, dict] = {}
            prev, stalls = -1, 0
            for _ in range(max_scrolls + 1):
                listed = parse_contacts(panel.inner_text("body"))
                urls = panel_linkedin_urls(panel)
                new = []
                for c in listed:
                    if c["name"] not in seen:
                        c.update(linkedin_url=urls.get(c["name"]), tier=contact_tier(c["headline"]), selected=False)
                        seen[c["name"]] = c
                        new.append(c)
                if resolve and new and resolve(new):
                    break
                stalls = stalls + 1 if len(listed) == prev else 0  # stop after two loads that add nothing
                if stalls >= 2:
                    break
                prev = len(listed)
                panel.mouse.move(200, 500)
                panel.mouse.wheel(0, 4000)
                wait_grows(panel, ROW_LINK, len(urls))
            return {"contacts": list(seen.values()), "note": None}
        finally:
            panel.close()
    finally:
        page.close()
