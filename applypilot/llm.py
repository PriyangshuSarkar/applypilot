import re
import subprocess
import time
from dataclasses import dataclass

import httpx

from applypilot.config import Config
from applypilot.validate import company_short

SYSTEM = """You write cold emails for a software engineer applying to a specific role. They go to recruiters/hiring managers who skim 100 emails a day, so the email must earn attention in the first line.

Hard rules:
- Use ONLY facts from the RESUME. Never invent employers, skills, numbers or achievements.
- Use the JOB TITLE exactly as given. Ignore internal grade titles inside the description (e.g. "Senior Manager", "Engineering Analyst").
- Keep every achievement attached to exactly what the resume ties it to. NEVER combine two resume bullets into one claim or one sentence, and never put two different metrics in the same sentence.
- Prefer facts from work experience. Anything from the PROJECTS section (e.g. "Local Search Engine Website", "Developer Dotfiles") is a personal project: if you use it, say "in a side project" and never imply it was done for the employer you are writing to.
- Do not claim you built something "for" the company you are writing to.
- Never copy sentences from the resume; rewrite every fact in your own words, in first person, aimed at this JD.
- No greeting, no sign-off, no signature, no opt-out line, no placeholders like [Name].

Subject (max 9 words): specific to THIS job and company, truthful, no clickbait, no emojis, no "Re:"/"Fwd:", no questions like "Looking for a job?". Follow the SUBJECT STYLE given in the request. Do NOT put a percentage or other metric in the subject, and never reuse the same proof point as a generic template: pick what matches this JD's domain or stack.

Body (45-75 words, plain text, short sentences, exactly 2 short paragraphs separated by a blank line):
1. Hook (1 sentence): connect ONE specific need stated in the JD to the single strongest matching proof point from the resume, e.g. "You're hiring for X; I <did Y with result Z>." Start with the proof or the need, NOT with praise of the company and NOT with "I am writing to".
2. Support (1-2 sentences): one or two more resume facts that match the JD's stack or domain.
The closing question is added automatically after your text. Do NOT write any ask, question, call-to-action or company name sentence yourself.

Banned words/phrases: passionate, excited, extensive experience, proven track record, dynamic, results-driven, I hope this finds you well, perfect fit, leverage, synergy.

Output format (exactly, nothing else):
SUBJECT: <the subject line>
BODY:
<the core body>"""

SUBJECT_STYLES = [
    "Name the JD's core technology or domain, then who you are. Shape: '<domain or tech> backend engineer for your <role> opening'.",
    "Mirror the job title and add your two strongest matching skills. Shape: '<role>: <skill A> + <skill B> background'.",
    "Lead with the problem the JD describes. Shape: 'Building <thing from the JD>? I have shipped <related thing>'.",
    "Short and direct. Shape: '<Company> <role> - backend engineer, <stack from the JD>'.",
]


def subject_style(job: dict) -> str:
    digits = "".join(ch for ch in str(job.get("job_id", "0")) if ch.isdigit()) or "0"
    return SUBJECT_STYLES[int(digits) % len(SUBJECT_STYLES)]


@dataclass
class Core:
    subject: str
    body: str


def parse_core(text: str) -> Core:
    """Parse 'SUBJECT: ... / BODY: ...'; tolerate bold labels, fences and a missing BODY label."""
    t = text.replace("**", "").strip().strip("`").strip()
    m = re.search(r"SUBJECT:\s*(.+?)\s*\n+\s*(?:BODY:\s*)?(.+)", t, re.S | re.I)
    if not m or not m.group(2).strip():
        raise ValueError("reply is not in SUBJECT/BODY format")
    return Core(m.group(1).strip().strip('"'), m.group(2).strip())


def chat(cfg: Config, system: str, user: str) -> str:
    payload = {
        "model": cfg.llm.model,
        "stream": False,
        "think": False,  # hidden reasoning pass is wasted on a 100-word email and slows it a lot
        "options": {"temperature": cfg.llm.temperature, "num_ctx": cfg.llm.num_ctx},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    r = httpx.post(f"{cfg.llm.host}/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"]


def draft_core(cfg: Config, resume: str, job: dict, feedback: list[str] | None = None) -> Core:
    user = (
        f"RESUME:\n{resume}\n\n"
        f"JOB TITLE: {job['title']}\nCOMPANY (for context only): {company_short(job['company'])}\n\n"
        f"JOB DESCRIPTION:\n{(job.get('jd') or '')[:3500]}\n\n"
        f"SUBJECT STYLE for this email: {subject_style(job)}\n\n"
        "Write the subject and core body now."
    )
    if feedback:
        user += "\n\nYour previous attempt was rejected for: " + "; ".join(feedback) + ". Fix these."
    core = parse_core(chat(cfg, SYSTEM, user))
    ask = (f"Are you the right person to speak with about the {job['title']} role at "
           f"{company_short(job['company'])}, or could you point me to the hiring manager?")
    return Core(core.subject, f"{core.body.rstrip()}\n\n{ask}")


def server_up(cfg: Config) -> bool:
    try:
        return httpx.get(f"{cfg.llm.host}/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def start_llm(cfg: Config) -> subprocess.Popen | None:
    """Make sure the Ollama server is running. Returns the process only if WE started it."""
    if server_up(cfg):
        return None
    proc = subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    for _ in range(60):
        if server_up(cfg):
            return proc
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Ollama server did not start")


def stop_llm(cfg: Config, proc: subprocess.Popen | None) -> None:
    """Unload the model from memory; also stop the server if we started it."""
    try:
        httpx.post(f"{cfg.llm.host}/api/generate", json={"model": cfg.llm.model, "keep_alive": 0}, timeout=30)
    except httpx.HTTPError:
        pass
    if proc is not None:
        proc.terminate()
