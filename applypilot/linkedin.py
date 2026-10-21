from urllib.parse import parse_qs, urlencode, urlparse

from applypilot.config import Search

BASE = "https://www.linkedin.com/jobs/search/"
DATE = {"past_24h": "r86400", "past_week": "r604800", "past_month": "r2592000"}
EXPERIENCE = {"internship": "1", "entry": "2", "associate": "3", "mid_senior": "4", "director": "5", "executive": "6"}


def build_search_url(query: str, search: Search) -> str:
    """Build a LinkedIn jobs search URL from config (pure; does not hit the network)."""
    params = {"keywords": query, "f_TPR": DATE[search.date_posted]}
    if search.geo_id:
        params["geoId"] = search.geo_id
    if search.experience:
        params["f_E"] = ",".join(EXPERIENCE[e] for e in search.experience)
    if search.salary:
        params["f_SAL"] = f"f_SA_id_{search.salary.facet}:{','.join(search.salary.values)}"
    return f"{BASE}?{urlencode(params)}"


def parse_search_url(url: str) -> dict:
    """Extract the filters we care about from a pasted LinkedIn search URL."""
    q = parse_qs(urlparse(url).query)
    first = lambda k: q.get(k, [None])[0]
    inv_date = {v: k for k, v in DATE.items()}
    inv_exp = {v: k for k, v in EXPERIENCE.items()}
    return {
        "keywords": first("keywords"),
        "geo_id": first("geoId"),
        "date_posted": inv_date.get(first("f_TPR") or ""),
        "experience": [inv_exp[c] for c in (first("f_E") or "").split(",") if c in inv_exp],
        "salary": _parse_salary(first("f_SAL")),
    }


def _parse_salary(raw: str | None) -> dict | None:
    if not raw or not raw.startswith("f_SA_id_"):
        return None
    facet, _, values = raw.removeprefix("f_SA_id_").partition(":")
    return {"facet": facet, "values": values.split(",")}
