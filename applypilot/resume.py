import subprocess
from pathlib import Path


def load_resume_text(path: str) -> str:
    """Extract text from the resume PDF with poppler's pdftotext."""
    pdf = Path(path).expanduser()
    if not pdf.exists():
        raise FileNotFoundError(f"resume not found: {pdf}")
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True)
    return out.stdout.strip()
