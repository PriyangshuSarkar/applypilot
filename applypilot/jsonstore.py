import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text()) if Path(path).exists() else []


def save(path: Path, rows: list[dict]) -> None:
    """Atomic write so a crash mid-run never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def remove_job(path: Path, job_id: str) -> bool:
    """Drop the entry with this job_id; True if something was removed."""
    rows = load(path)
    kept = [r for r in rows if r.get("job_id") != job_id]
    if len(kept) == len(rows):
        return False
    save(path, kept)
    return True


def update_job(path: Path, job_id: str, **fields) -> bool:
    """Set fields (e.g. drafted_at, sent_at) on the entry with this job_id; True if it exists."""
    rows = load(path)
    for r in rows:
        if r.get("job_id") == job_id:
            r.update(fields)
            save(path, rows)
            return True
    return False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def prune(path: Path, days: int) -> int:
    """Drop entries collected more than `days` days ago (by `collected_at`); returns how many were dropped."""
    rows = load(path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept = [r for r in rows if not r.get("collected_at") or datetime.fromisoformat(r["collected_at"]) >= cutoff]
    if len(kept) != len(rows):
        save(path, kept)
    return len(rows) - len(kept)
