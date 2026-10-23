from applypilot.scrape import clean_jd, parse_contacts, parse_hiring_team

PANEL = """View list
Kriti Arya
Add to list
Standard Chartered India
Filters
Select all
0 selected
Dalvir Singh
India
Manager at Standard Chartered India
Ankan Das
India
Relationship Manager at SC
Reveal and save
Megha M
India
Talent Advisor at SC
Reveal and save"""


def test_parse_contacts():
    got = parse_contacts(PANEL)
    assert [c["name"] for c in got] == ["Dalvir Singh", "Ankan Das", "Megha M"]
    assert got[2]["headline"] == "Talent Advisor at SC"
    assert [c["email"] for c in got] == [None, None, None]


def test_clean_jd_strips_css():
    raw = "a { text-decoration: none; color: #464feb; } tr th { background-color: #f5f5f5; }  We are hiring a dev."
    assert clean_jd(raw) == "We are hiring a dev."
    assert clean_jd("Plain text") == "Plain text"


def test_parse_contacts_with_existing_email():
    text = PANEL.replace("Ankan Das\nIndia\nRelationship Manager at SC\nReveal and save",
                         "Ankan Das\nIndia\nRelationship Manager at SC\nAnkan.Das@sc.com")
    got = parse_contacts(text)
    assert [c["name"] for c in got] == ["Dalvir Singh", "Ankan Das", "Megha M"]
    assert got[1]["email"] == "ankan.das@sc.com"
    assert got[2]["email"] is None


def test_parse_hiring_team():
    rows = [
        {"href": "https://www.linkedin.com/in/jane-doe?miniProfileUrn=x", "text": ""},
        {"href": "https://www.linkedin.com/in/jane-doe?miniProfileUrn=x",
         "text": "Jane Doe\n· 2nd\nTalent Acquisition Lead at Acme\nJob poster"},
        {"href": "https://www.linkedin.com/company/acme/", "text": "Acme"},
    ]
    got = parse_hiring_team(rows)
    assert got == [{"name": "Jane Doe", "location": "", "headline": "Talent Acquisition Lead at Acme", "email": None,
                    "linkedin_url": "https://www.linkedin.com/in/jane-doe/", "tier": 0, "selected": False,
                    "source": "job_post"}]
    assert parse_hiring_team([]) == []
