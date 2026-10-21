import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str


def first_name(full: str) -> str:
    return full.strip().split()[0].strip(",.") if full.strip() else "there"


def greeting_names(recipients: list[Recipient]) -> str:
    """'Megha', 'Megha and Siddhant', 'Megha, Siddhant and Anantha'."""
    names = [first_name(r.name) for r in recipients]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def assemble_body(core: str, greeting: str, opt_out: str, signature: str) -> str:
    """Plain text with single newlines only (no blank lines); opt-out follows the closing question."""
    text = f"Hi {greeting},\n{core.strip()} {opt_out.strip()}\nBest,\n{signature.strip()}"
    return re.sub(r"\n{2,}", "\n", text)
