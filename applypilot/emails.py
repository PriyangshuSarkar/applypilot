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
    """Plain text, one blank line between paragraphs: greeting, the core paragraphs, the closing ask with the
    opt-out, then 'Best,' and the signature (whose own lines stay together)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", core.strip()) if p.strip()]
    paras[-1] = f"{paras[-1]} {opt_out.strip()}"  # the last core paragraph is the closing ask
    sign_off = f"Best,\n{signature.strip()}"
    return "\n\n".join([f"Hi {greeting},", *paras, sign_off])
