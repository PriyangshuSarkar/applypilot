from applypilot.filters import Contact, remaining_budget, select_contacts
from applypilot.store import Store
from applypilot.validate import Draft, fallback_subject, only_subject_problems, validate_draft

ALLOW = ["recruiter", "engineering manager"]


def test_select_contacts_filters_dedupes_caps():
    cs = [
        Contact("A", "Senior Recruiter", "A@x.com"),
        Contact("A2", "Recruiter", "a@x.com"),  # duplicate email
        Contact("B", "Accountant", "b@x.com"),  # irrelevant role
        Contact("C", "Engineering Manager", "c@x.com"),
        Contact("D", "Recruiter", "d@x.com"),
        Contact("E", "Recruiter", "e@x.com"),
    ]
    got = select_contacts(cs, ALLOW, 2, lambda e: e == "d@x.com")
    assert [c.email for c in got] == ["a@x.com", "c@x.com"]


def test_select_contacts_skips_already_emailed():
    cs = [Contact("A", "Recruiter", "a@x.com")]
    assert select_contacts(cs, ALLOW, 3, lambda e: True) == []


def test_remaining_budget():
    assert remaining_budget(20, 30, 5, 28) == 2
    assert remaining_budget(20, 30, 20, 0) == 0
    assert remaining_budget(20, 30, 0, 40) == 0


def test_validate_draft():
    opt = "Reply to opt out."
    ok = Draft("Backend role at Acme", f"Hi, I saw the role at Acme. {opt}")
    assert validate_draft(ok, "Acme", opt) == []
    bad = Draft("Hi", "Hello [Name], interested in a role. ")
    probs = validate_draft(bad, "Acme", opt)
    assert "contains placeholder text" in probs
    assert "missing opt-out line" in probs
    assert "does not mention the company" in probs


def test_store_dedupe_ignores_dry_runs(tmp_path):
    s = Store(tmp_path / "t.db")
    s.record_email("A@x.com", "u", "s", dry_run=True)
    assert not s.already_emailed("a@x.com")
    s.record_email("A@x.com", "u", "s", dry_run=False)
    assert s.already_emailed("a@x.com")
    assert s.sent_today() == 1


def test_contact_tier_and_pick():
    from applypilot.filters import contact_tier, pick_contacts

    assert contact_tier("Talent Acquisition Partner at X") == 0
    assert contact_tier("Senior HR Business Partner at X") == 0
    assert contact_tier("Co-Founder & CEO at X") == 1
    assert contact_tier("Vice President, Sales at X") == 2
    assert contact_tier("Software Engineer at X") == 2
    cs = [
        {"name": "eng", "headline": "Software Engineer"},
        {"name": "ceo", "headline": "CEO"},
        {"name": "hr1", "headline": "Recruiter"},
        {"name": "vp", "headline": "VP Engineering"},
        {"name": "hr2", "headline": "Head of Talent"},
    ]
    assert [c["name"] for c in pick_contacts(cs, 3)] == ["hr1", "hr2", "ceo"]
    assert [c["name"] for c in pick_contacts(cs[:2], 3)] == ["ceo", "eng"]


def test_title_excluded_and_sendable():
    from applypilot.filters import has_sendable, title_excluded

    words = ["manager", "vp", "intern"]
    assert title_excluded("Engineering Manager", words) == "manager"
    assert title_excluded("Software Engineer", words) is None
    assert title_excluded("Internal Tools Engineer", words) is None  # whole words only
    job = {"contacts": [{"selected": True, "email": "a@x.com"}, {"selected": False, "email": "b@x.com"}]}
    assert has_sendable(job, lambda e: False) is True
    assert has_sendable(job, lambda e: e == "a@x.com") is False  # selected one already emailed


def test_fill_emails_stops_at_cap_and_skips_misses():
    from applypilot.filters import fill_emails

    people = [{"name": n, "email": None} for n in "abcde"]
    hits = {"a": None, "b": "b@x.com", "c": None, "d": "d@x.com", "e": "e@x.com"}
    looked = []

    def lookup(c):
        looked.append(c["name"])
        c["email"] = hits[c["name"]]
        return True

    got = fill_emails(people, lookup, 2, max_attempts=10)
    assert [c["name"] for c in got] == ["b", "d"]
    assert looked == ["a", "b", "c", "d"]  # "e" never looked up: cap reached


def test_fill_emails_attempt_cap_and_existing_emails():
    from applypilot.filters import fill_emails

    people = [{"name": "x", "email": "x@x.com"}, {"name": "y", "email": None}, {"name": "z", "email": None}]
    calls = []
    got = fill_emails(people, lambda c: calls.append(c["name"]) or True, None, max_attempts=1)
    assert [c["name"] for c in got] == ["x"] and calls == ["y"]  # existing email is free; one live attempt only


def test_fallback_subject_is_short_and_valid():
    sub = fallback_subject("Software Engineering LMTS - Backend Distributed Systems", "Salesforce")
    assert sub == "Applying for Software Engineering LMTS at Salesforce"
    assert len(sub.split()) <= 10
    assert fallback_subject("Full Stack Engineer", "Standard Chartered India") == "Applying for Full Stack Engineer at Standard Chartered"


def test_only_subject_problems():
    assert only_subject_problems(["subject longer than 10 words; shorten it"])
    assert not only_subject_problems(["subject too similar to x", "contains placeholder text"])
    assert not only_subject_problems([])
