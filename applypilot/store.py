import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  url TEXT PRIMARY KEY, title TEXT, company TEXT, seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS emails_sent (
  id INTEGER PRIMARY KEY, email TEXT NOT NULL, job_url TEXT, subject TEXT,
  sent_on TEXT NOT NULL, dry_run INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lookups (
  linkedin_url TEXT PRIMARY KEY, email TEXT, status TEXT NOT NULL, looked_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sent_email ON emails_sent(email);
"""


class Store:
    def __init__(self, path: str | Path = "applypilot.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def job_seen(self, url: str) -> bool:
        return self.db.execute("SELECT 1 FROM jobs WHERE url=?", (url,)).fetchone() is not None

    def mark_job(self, url: str, title: str, company: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO jobs(url,title,company) VALUES(?,?,?)", (url, title, company))
        self.db.commit()

    def get_lookup(self, linkedin_url: str) -> tuple[str | None, str] | None:
        """Cached Mailmeteor result (email or None, status), or None if never looked up."""
        return self.db.execute("SELECT email, status FROM lookups WHERE linkedin_url=?", (linkedin_url,)).fetchone()

    def save_lookup(self, linkedin_url: str, email: str | None, status: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO lookups(linkedin_url,email,status) VALUES(?,?,?)",
                        (linkedin_url, email, status))
        self.db.commit()

    def already_emailed(self, email: str) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM emails_sent WHERE email=? AND dry_run=0", (email.lower(),)
            ).fetchone()
            is not None
        )

    def record_email(self, email: str, job_url: str, subject: str, dry_run: bool) -> None:
        self.db.execute(
            "INSERT INTO emails_sent(email,job_url,subject,sent_on,dry_run) VALUES(?,?,?,?,?)",
            (email.lower(), job_url, subject, date.today().isoformat(), int(dry_run)),
        )
        self.db.commit()

    def sent_today(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM emails_sent WHERE sent_on=? AND dry_run=0", (date.today().isoformat(),)
        ).fetchone()[0]
