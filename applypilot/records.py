import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class JobInfo(BaseModel):
    url: str
    linkedin_job_id: str | None = None
    title: str
    company: str
    company_url: str | None = None
    location: str | None = None
    salary_text: str | None = None
    posted_text: str | None = None
    description: str


class ContactInfo(BaseModel):
    name: str
    role: str
    email: str


class EmailDraft(BaseModel):
    to: str
    subject: str
    body: str
    validation_problems: list[str] = []
    status: str = "drafted"  # drafted | rejected | dry_run | sent | failed
    sent_at: str | None = None


class JobRecord(BaseModel):
    job: JobInfo
    contacts: list[ContactInfo] = []
    emails: list[EmailDraft] = []
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def job_id_from_url(url: str) -> str | None:
    m = re.search(r"(?:currentJobId=|/view/)(\d+)", url)
    return m.group(1) if m else None


def write_record(record: JobRecord, out_dir: str | Path = "out/jobs") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = record.job.linkedin_job_id or re.sub(r"\W+", "_", record.job.url)[-40:]
    path = out / f"{name}.json"
    path.write_text(json.dumps(record.model_dump(), indent=2, ensure_ascii=False))
    return path
