import json
import os
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
