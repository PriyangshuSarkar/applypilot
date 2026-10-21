from applypilot.filters import Contact, remaining_budget, select_contacts
from applypilot.store import Store
from applypilot.validate import Draft, validate_draft

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
    from applypilot.filters import contact_tier, pick_for_reveal

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
    assert [c["name"] for c in pick_for_reveal(cs, 3)] == ["hr1", "hr2", "ceo"]
    assert [c["name"] for c in pick_for_reveal(cs[:2], 3)] == ["ceo", "eng"]


def test_title_excluded_and_sendable():
    from applypilot.filters import has_sendable, title_excluded

    words = ["manager", "vp", "intern"]
    assert title_excluded("Engineering Manager", words) == "manager"
    assert title_excluded("Software Engineer", words) is None
    assert title_excluded("Internal Tools Engineer", words) is None  # whole words only
    job = {"contacts": [{"selected": True, "email": "a@x.com"}, {"selected": False, "email": "b@x.com"}]}
    assert has_sendable(job, lambda e: False) is True
    assert has_sendable(job, lambda e: e == "a@x.com") is False  # selected one already emailed
