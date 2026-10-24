from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Salary(BaseModel):
    """LinkedIn salary buckets, copied from a search URL: f_SAL=f_SA_id_<facet>:<value>,<value>."""

    facet: str
    values: list[str]


class Search(BaseModel):
    queries: list[str]
    geo_id: str | None = None  # LinkedIn geoId from a search URL
    experience: list[str] = []  # internship|entry|associate|mid_senior|director|executive
    date_posted: str = "past_24h"  # past_24h | past_week | past_month
    salary: Salary | None = None
    # jobs whose LinkedIn title contains any of these words are skipped (never emailed)
    exclude_title_words: list[str] = ["principal", "staff", "director", "head", "manager", "architect", "vp", "intern"]


class Run(BaseModel):
    jobs_per_run: int = Field(10, ge=1)  # companies newly made ready (with an email) per run; skipped jobs and earlier sends do not count
    max_jobs_examined: int | None = None  # None = 2 x jobs_per_run; 0 = uncapped
    dry_run: bool = True
    keep_days: int = Field(7, ge=1)  # how long a collected job stays in contacts.json (so reruns never redo it)


class Limits(BaseModel):
    max_contacts_per_company: int = 3
    max_emails_per_run: int = 30
    max_emails_per_day: int = 30
    delay_seconds: tuple[int, int] = (45, 120)


class Contacts(BaseModel):
    role_allowlist: list[str]


class Browser(BaseModel):
    brave_path: str
    user_data_dir: str = "~/.applypilot/brave-profile"  # copy of the real data dir; Brave blocks CDP on the default one
    profile_directory: str = "Profile 1"  # the "Personal" profile
    cdp_port: int = 9222


class Extension(BaseModel):
    id: str = ""


class Mailmeteor(BaseModel):
    """Email lookup from LinkedIn profile URLs (throttled and capped)."""

    max_lookups_per_company: int | None = 2  # HR first, then CEO/founder, then others; None = everyone
    max_lookups_per_run: int | None = None  # None = no cap: keep looking until the daily goal is met
    max_attempts_per_company: int = 6  # profiles tried per company before giving up
    delay_seconds: tuple[float, float] = (10, 20)  # minimum gap between lookups (a timer, not a sleep)


class Llm(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "gemma4:12b"
    temperature: float = 0.7
    num_ctx: int = 8192
    max_attempts: int = 3


class Email(BaseModel):
    sender_name: str
    resume_path: str = "~/resume.pdf"
    opt_out_line: str


class Config(BaseModel):
    search: Search
    run: Run = Run()
    limits: Limits = Limits()
    contacts: Contacts
    browser: Browser
    extension: Extension = Extension()
    mailmeteor: Mailmeteor = Mailmeteor()
    llm: Llm = Llm()
    email: Email


class Profile(BaseModel):
    name: str
    headline: str
    years_experience: int
    links: dict[str, str] = {}
    skills: list[str]
    highlights: list[str]


def load_config(path: str | Path = "config.yaml") -> Config:
    return Config.model_validate(yaml.safe_load(Path(path).read_text()))


def load_profile(path: str | Path = "profile.yaml") -> Profile:
    return Profile.model_validate(yaml.safe_load(Path(path).read_text()))
