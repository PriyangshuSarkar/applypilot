import json

from applypilot import cli, gmail, jsonstore
from applypilot.config import Config
from applypilot.store import Store

OPT = "If this isn't relevant, just reply and I won't follow up."


def make_cfg():
    return Config.model_validate({
        "search": {"queries": ["x"]}, "contacts": {"role_allowlist": ["hr"]},
        "browser": {"brave_path": "b"}, "email": {"sender_name": "Me", "opt_out_line": OPT},
        "limits": {"delay_seconds": [0, 0]},
    })


def draft(job_id, company, to, status="draft"):
    return {"job_id": job_id, "job_title": "Dev", "company": company, "job_url": f"u/{job_id}", "to": to,
            "to_names": ["A"] * len(to), "cc": [], "subject": f"Hi {company}", "attachment": None,
            "body": f"Hi A,\nI like {company}. {OPT}\nBest,\nMe", "problems": [], "status": status}


def setup(tmp_path, monkeypatch, fail_on=()):
    emails, contacts = tmp_path / "emails.json", tmp_path / "contacts.json"
    jsonstore.save(emails, [draft("1", "Acme", ["a@acme.com"]), draft("2", "Beta", ["b@beta.com"]),
                            draft("3", "Gamma", ["g@gamma.com"], status="needs_review")])
    jsonstore.save(contacts, [{"job_id": j} for j in ("1", "2", "3")])
    sent = []

    def fake_send(service, msg):
        if msg["To"] in fail_on:
            raise RuntimeError("boom")
        sent.append(msg["To"])
        return "id"

    monkeypatch.setattr(gmail, "get_service", lambda: object())
    monkeypatch.setattr(gmail, "send", fake_send)
    monkeypatch.chdir(tmp_path)  # so a stray STOP file can't leak in
    return emails, contacts, sent, Store(tmp_path / "t.db")


def test_success_clears_send_queue_and_marks_contacts(tmp_path, monkeypatch):
    emails, contacts, sent, store = setup(tmp_path, monkeypatch)
    cli.send_step(make_cfg(), store, emails, contacts, live=True)
    assert sent == ["a@acme.com", "b@beta.com"]
    assert [d["job_id"] for d in jsonstore.load(emails)] == ["3"]      # needs_review stays
    marked = {c["job_id"]: bool(c.get("sent_at")) for c in jsonstore.load(contacts)}
    assert marked == {"1": True, "2": True, "3": False}               # kept for keep_days, marked as sent
    assert store.already_emailed("a@acme.com") and store.job_seen("u/1")


def test_failure_keeps_entry_and_continues(tmp_path, monkeypatch):
    emails, contacts, sent, store = setup(tmp_path, monkeypatch, fail_on={"a@acme.com"})
    cli.send_step(make_cfg(), store, emails, contacts, live=True)
    assert sent == ["b@beta.com"]
    assert [d["job_id"] for d in jsonstore.load(emails)] == ["1", "3"]
    assert not store.already_emailed("a@acme.com")


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    emails, contacts, sent, store = setup(tmp_path, monkeypatch)
    cli.send_step(make_cfg(), store, emails, contacts, live=False)
    assert sent == [] and len(jsonstore.load(emails)) == 3 and len(jsonstore.load(contacts)) == 3


def test_stop_file_halts(tmp_path, monkeypatch):
    emails, contacts, sent, store = setup(tmp_path, monkeypatch)
    (tmp_path / "STOP").write_text("")
    cli.send_step(make_cfg(), store, emails, contacts, live=True)
    assert sent == [] and len(jsonstore.load(emails)) == 3
