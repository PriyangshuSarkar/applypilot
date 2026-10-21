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
    jobs_per_run: int = Field(10, ge=1)  # target: companies with at least one email to send to
    max_jobs_examined: int | None = None  # credit guard; default 2 x jobs_per_run
    dry_run: bool = True


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
    max_reveals_per_company: int | None = 3  # None = reveal everyone (spends GetProspect credits!)


class Llm(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "gemma4:12b"
    temperature: float = 0.7
    num_ctx: int = 8192
    max_attempts: int = 3


class Email(BaseModel):
    sender_name: str
    resume_path: str = "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/My CVs/Priyangshu_Sarkar.pdf"
    opt_out_line: str


class Config(BaseModel):
    search: Search
    run: Run = Run()
    limits: Limits = Limits()
    contacts: Contacts
    browser: Browser
    extension: Extension = Extension()
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
