import re
from dataclasses import dataclass

GENERIC_SUFFIX = {"india", "ltd", "ltd.", "limited", "pvt", "pvt.", "private", "inc", "inc.", "llc", "technologies",
                  "technology", "solutions", "services", "group", "corp", "corporation", "software"}


def company_short(name: str) -> str:
    """'Standard Chartered India' -> 'Standard Chartered'; 'Tavant' stays 'Tavant'."""
    words = name.split()
    while len(words) > 1 and words[-1].lower() in GENERIC_SUFFIX:
        words.pop()
    return " ".join(words)


PLACEHOLDER = re.compile(r"\[[^\]]+\]|\{[^}]+\}|<[^>]+>|lorem ipsum", re.I)


@dataclass
class Draft:
    subject: str
    body: str


def validate_draft(draft: Draft, company: str, opt_out_line: str, max_words: int = 180) -> list[str]:
    """Return a list of problems; empty means the draft is safe to send."""
    problems: list[str] = []
    if not draft.subject.strip() or len(draft.subject) > 120:
        problems.append("bad subject length")
    if len(draft.subject.split()) > 10:
        problems.append("subject longer than 10 words; shorten it")
    if PLACEHOLDER.search(draft.subject + " " + draft.body):
        problems.append("contains placeholder text")
    if len(draft.body.split()) > max_words:
        problems.append("body too long")
    if company_short(company).lower() not in draft.body.lower():
        problems.append("does not mention the company")
    if opt_out_line.strip() not in draft.body:
        problems.append("missing opt-out line")
    return problems


DURATION = re.compile(r"\b\d+[- ]?(?:min|minute|minutes)\b", re.I)
NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?")  # skips digits inside names like S3, OBSv2, k8s


def ungrounded_numbers(text: str, resume_text: str) -> list[str]:
    """Numbers in the draft that never appear in the resume (likely invented metrics)."""
    known = set(NUMBER.findall(resume_text))
    text = DURATION.sub("", text)  # "15-minute chat" is an ask, not a claim about the resume
    return sorted(set(NUMBER.findall(text)) - known)


def _bullets(resume_text: str) -> list[set[str]]:
    """Number sets per resume bullet (pdftotext keeps the bullet glyph)."""
    chunks = re.split(r"•|\n\s*\n", resume_text)
    return [set(NUMBER.findall(DURATION.sub("", c))) for c in chunks]


def blended_numbers(text: str, resume_text: str) -> list[str]:
    """Sentences whose numbers never appear together in one resume bullet (merged achievements)."""
    bullets = _bullets(resume_text)
    bad = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", DURATION.sub("", text)):
        nums = set(NUMBER.findall(sentence))
        if len(nums) >= 2 and not any(nums <= b for b in bullets):
            bad.append(sentence.strip()[:80])
    return bad


def subject_too_similar(subject: str, others: list[str]) -> str | None:
    """Return the earlier subject this one clashes with (shared number or >=50% shared words), else None."""
    words = lambda t: set(re.findall(r"[a-z0-9%.+#]+", t.lower())) - {"for", "a", "the", "your", "at", "with", "and", "to", "-"}
    mine, my_nums = words(subject), set(NUMBER.findall(subject))
    for o in others:
        theirs = words(o)
        if (my_nums & set(NUMBER.findall(o))) or (mine and theirs and len(mine & theirs) / len(mine | theirs) >= 0.5):
            return o
    return None


SUBJECT_PROBLEMS = ("bad subject length", "subject longer than", "subject too similar")


def only_subject_problems(problems: list[str]) -> bool:
    """True if every problem is cosmetic subject trouble (length / clashing with another email's subject)."""
    return bool(problems) and all(p.startswith(SUBJECT_PROBLEMS) for p in problems)


def fallback_subject(job_title: str, company: str, max_title_words: int = 6) -> str:
    """A subject built from facts alone (<= 10 words): 'Applying for <role> at <company>'."""
    role = " ".join(re.split(r"\s+[-–—:|,]\s+", job_title.strip())[0].split()[:max_title_words])
    return f"Applying for {role} at {company_short(company)}"
