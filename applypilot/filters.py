from dataclasses import dataclass


@dataclass(frozen=True)
class Contact:
    name: str
    role: str
    email: str


def select_contacts(
    contacts: list[Contact],
    role_allowlist: list[str],
    max_per_company: int,
    already_emailed,
) -> list[Contact]:
    """Keep relevant, not-yet-emailed contacts, deduped by email, capped per company."""
    allow = [r.lower() for r in role_allowlist]
    picked: list[Contact] = []
    seen: set[str] = set()
    for c in contacts:
        email = c.email.strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        if not any(r in c.role.lower() for r in allow):
            continue
        if already_emailed(email):
            continue
        seen.add(email)
        picked.append(Contact(c.name, c.role, email))
        if len(picked) >= max_per_company:
            break
    return picked


def remaining_budget(max_per_run: int, max_per_day: int, sent_this_run: int, sent_today: int) -> int:
    return max(0, min(max_per_run - sent_this_run, max_per_day - sent_today))


import re

HR = re.compile(
    r"\bhr\b|\bhrbp\b|recruit|talent|human resources?|people (?:ops|operations|partner|team|&)|hiring|staffing|sourcer",
    re.I,
)
HEAD = re.compile(
    r"\bceo\b|chief executive|founder|owner|managing director|\bchairman\b|\bcto\b|\bcoo\b|(?<!vice )\bpresident\b", re.I
)
NOT_HEAD = re.compile(r"vice president|\bvp\b|associate|assistant|intern", re.I)


def contact_tier(headline: str) -> int:
    """0 = HR/recruiting, 1 = company head (CEO/founder/...), 2 = everyone else."""
    if HR.search(headline):
        return 0
    if HEAD.search(headline) and not NOT_HEAD.search(headline):
        return 1
    return 2


def pick_contacts(contacts: list[dict], cap: int | None) -> list[dict]:
    """Top `cap` contacts by tier (stable within a tier). Contacts that already have an email count toward the cap."""
    ranked = sorted(contacts, key=lambda c: contact_tier(c["headline"]))
    return ranked if cap is None else ranked[:cap]


def fill_emails(ranked: list[dict], lookup, cap: int | None, max_attempts: int) -> list[dict]:
    """Walk contacts best-first and stop as soon as `cap` of them have an email, so unneeded profiles are never
    looked up. `lookup(contact) -> bool` fills contact['email'] and says whether it made a live (rate-limited) lookup;
    at most `max_attempts` live lookups are made. Contacts that already have an email count toward the cap."""
    found, attempts = [], 0
    for c in ranked:
        if cap is not None and len(found) >= cap:
            break
        if not c.get("email"):
            if attempts >= max_attempts:
                break
            attempts += bool(lookup(c))
        if c.get("email"):
            found.append(c)
    return found


def title_excluded(title: str, words: list[str]) -> str | None:
    """The first excluded word found in the job title (whole-word match), else None."""
    for w in words:
        if re.search(rf"\b{re.escape(w.lower())}\b", title.lower()):
            return w
    return None


def has_sendable(job: dict, already_emailed) -> bool:
    """A collected job is worth emailing if a selected contact has an email we haven't used."""
    return any(c.get("selected") and c.get("email") and not already_emailed(c["email"]) for c in job["contacts"])
